<script setup lang="ts">
/**
 * 📋 BillAllocationTable — ตารางบิล + ยอดที่ระบบจัดสรรให้ (FIN-V2 / P2.3)
 *
 * 🔴 ยอด "รวม" มาจาก **ผลพรีวิวของ backend** (`totals`) ไม่ใช่ผลบวกของบรรทัดที่แสดง:
 *    หน้าจอแสดงบิลที่มีใน `bills` แต่ engine อาจจัดสรรให้บิลที่หน้าจอยังไม่รู้จัก
 *    (เช่น ออกค่าปรับใหม่ระหว่างเปิดแผ่น) — ถ้าบวกเอง ตัวเลขล่างตารางจะไม่ตรงกับ
 *    `total_applied` ที่ commit จะเขียนจริง ⇒ ครูเห็นยอดหนึ่ง ใบเสร็จอีกยอดหนึ่ง
 *
 * 🔀 1 บิลมีได้ 2 บรรทัด (เงินสด + เครดิต) — แสดงแยกคอลัมน์ ไม่รวมเป็นก้อนเดียว
 *    เพราะผู้ใช้ต้องเห็นว่าเครดิตถูกใช้ไปเท่าไร (และ DEP/เครดิตคงเหลือลดเท่าไร)
 *
 * 💰 เงินเป็น string จาก API ⇒ `Number(x)` ก่อน `formatMoney`
 */
import { computed } from 'vue'
import type { AllocationLine, BillSelection, OpenBillItem } from '@/types/finance'
import { formatMoney } from '@/utils/money'
import { formatThaiDate, todayIso } from '@/utils/datetime'

const props = withDefaults(
  defineProps<{
    bills: OpenBillItem[]
    allocations: AllocationLine[]
    selection: BillSelection
    disabled?: boolean
    /** ยอดรวมจาก `AllocationPreviewResponse` — `null` = ยังไม่มีพรีวิว */
    totals?: {
      total_applied: string
      credit_used: string
      credit_added: string
    } | null
  }>(),
  { disabled: false, totals: null },
)

const selected = defineModel<number[]>({ default: () => [] })

const today = todayIso()

const isOverdue = (dueDate: string | null | undefined) => !!dueDate && dueDate < today

interface BillRow {
  bill: OpenBillItem
  cash: number
  credit: number
  after: number | null
  touched: boolean
}

/** ต่อบิล: รวมเงินสด/เครดิตของบรรทัดที่ชี้บิลนี้ และ `bill_after` ของบรรทัดสุดท้าย */
const rows = computed<BillRow[]>(() =>
  props.bills.map((bill) => {
    const lines = props.allocations.filter((a) => a.student_payment_id === bill.student_payment_id)
    const cash = lines
      .filter((a) => a.source === 'cash')
      .reduce((sum, a) => sum + Number(a.amount), 0)
    const credit = lines
      .filter((a) => a.source === 'credit')
      .reduce((sum, a) => sum + Number(a.amount), 0)
    const last = lines[lines.length - 1]
    return {
      bill,
      cash,
      credit,
      after: last ? Number(last.bill_after) : null,
      touched: lines.length > 0,
    }
  }),
)

const isSelected = (id: number) => selected.value.includes(id)

const toggle = (id: number) => {
  if (props.disabled) return
  selected.value = isSelected(id)
    ? selected.value.filter((x) => x !== id)
    : [...selected.value, id]
}
</script>

<template>
  <div class="overflow-x-auto rounded-control border border-line">
    <table class="data-table">
      <thead>
        <tr>
          <th v-if="selection === 'manual'" class="w-10" aria-label="เลือก"></th>
          <th>บิล</th>
          <th>กำหนด</th>
          <th class="text-right">คงเหลือ (฿)</th>
          <th class="text-right">เงินสด (฿)</th>
          <th class="text-right">เครดิต (฿)</th>
          <th class="text-right">หลังรับ (฿)</th>
        </tr>
      </thead>
      <tbody>
        <tr v-if="!rows.length">
          <td :colspan="selection === 'manual' ? 7 : 6" class="px-4 py-6 text-center text-sm text-ink-3">
            ไม่มีบิลเปิดให้ปิด — ยอดนี้จะถูกเก็บเป็นเครดิต (ถ้าเลือกเก็บส่วนเกิน)
          </td>
        </tr>

        <tr
          v-for="row in rows"
          :key="row.bill.student_payment_id"
          :class="[
            isOverdue(row.bill.due_date) ? 'bg-danger-50' : '',
            row.touched ? '' : 'text-ink-3',
          ]"
        >
          <td v-if="selection === 'manual'">
            <input
              type="checkbox"
              class="h-5 w-5 accent-brand"
              :checked="isSelected(row.bill.student_payment_id)"
              :disabled="disabled"
              :aria-label="`เลือกบิล ${row.bill.title}`"
              @change="toggle(row.bill.student_payment_id)"
            />
          </td>
          <td class="font-bold text-ink-1">
            {{ row.bill.title }}
            <span
              v-if="isOverdue(row.bill.due_date)"
              class="chip ms-1 bg-danger-50 text-danger-700"
            >
              เกินกำหนด
            </span>
          </td>
          <td
            class="whitespace-nowrap"
            :class="isOverdue(row.bill.due_date) ? 'font-bold text-danger-700' : 'text-ink-2'"
          >
            {{ row.bill.due_date ? formatThaiDate(row.bill.due_date) : 'ไม่กำหนด' }}
          </td>
          <td class="num whitespace-nowrap text-right text-ink-2">
            {{ formatMoney(Number(row.bill.outstanding)) }}
          </td>
          <td class="num whitespace-nowrap text-right">
            {{ row.cash > 0 ? formatMoney(row.cash) : '—' }}
          </td>
          <td class="num whitespace-nowrap text-right">
            {{ row.credit > 0 ? formatMoney(row.credit) : '—' }}
          </td>
          <td class="num whitespace-nowrap text-right font-bold text-ink-1">
            {{ row.after !== null ? formatMoney(row.after) : '—' }}
          </td>
        </tr>
      </tbody>
      <tfoot v-if="totals">
        <tr>
          <td :colspan="selection === 'manual' ? 4 : 3" class="text-right font-bold text-ink-2">
            รวมปิดบิล
          </td>
          <td colspan="3" class="num text-right font-bold text-ink-1">
            {{ formatMoney(Number(totals.total_applied)) }}
            <span class="ms-2 text-caption font-normal text-ink-3">
              (เครดิต {{ formatMoney(Number(totals.credit_used)) }}
              · เก็บเพิ่มเป็นเครดิต {{ formatMoney(Number(totals.credit_added)) }})
            </span>
          </td>
        </tr>
      </tfoot>
    </table>
  </div>
</template>
