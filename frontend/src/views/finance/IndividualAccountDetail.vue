<script setup lang="ts">
/**
 * 👤 บัญชีรายบุคคล — รายละเอียดนักเรียน 1 คน (FIN-V2 / P1.4)
 *
 * หน้านี้ **แยก route** โดยเจตนา (ไม่ใช่ modal) เพื่อส่งลิงก์ให้ผู้ปกครอง/นักเรียนได้
 * และเป็นที่ลงจอดของ "เปิดจากรายการเดินบัญชี" ในอนาคต
 *
 * 🔓 อ่านอย่างเดียว · สมาชิกห้องอ่านได้ — ห้าม gate ด้วย `isAdmin`
 * 🧾 ปุ่ม "รับเงิน" ยังไม่มี (P2.3) — การ์ดไม่มีปุ่มปลอมที่กดแล้วเงียบ
 *
 * ⚠️ เงินเป็น string 2 ตำแหน่งจาก API ⇒ `formatMoney(Number(x))` / `formatAmount(Number(x))`
 */
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { FinanceService } from '@/services/finance'
import { apiStatus } from '@/services/api'
import type { IndividualAccountItem } from '@/types/finance'
import { createLatestGuard } from '@/utils/latest'
import { formatAmount, formatMoney } from '@/utils/money'
import { formatThaiDate, formatThaiDateTime, todayIso } from '@/utils/datetime'

import StateBlock from '@/components/ui/StateBlock.vue'
import SkeletonRows from '@/components/ui/SkeletonRows.vue'
import AccountSummaryCard from '@/components/finance/AccountSummaryCard.vue'
import { useDialog } from '@/composables/useDialog'

const route = useRoute()
const authStore = useAuthStore()
const dialog = useDialog()
const currentRoomId = authStore.currentRoomId!

const account = ref<IndividualAccountItem | null>(null)
const isLoading = ref(true)
const hasError = ref(false)
const notFound = ref(false)

const detailGuard = createLatestGuard()

const studentId = computed(() => Number(route.params.studentId))

const FUND_TYPE_LABELS: Record<string, string> = {
  room_fund: 'เงินห้อง',
  pass_through: 'เก็บแทน / ผ่านมือ',
}

const fundTypeLabel = (value: string | null) => (value ? FUND_TYPE_LABELS[value] ?? value : '—')

const today = todayIso()
const isOverdue = (dueDate: string | null) => !!dueDate && dueDate < today

const loadAccount = async () => {
  const token = detailGuard.begin()
  isLoading.value = true
  hasError.value = false
  notFound.value = false
  try {
    const res = await FinanceService.getIndividualAccount(currentRoomId, studentId.value)
    if (!detailGuard.isCurrent(token)) return
    account.value = res
  } catch (error) {
    if (!detailGuard.isCurrent(token)) return
    // 404 = ไม่ใช่สมาชิกของห้องนี้ (หรือถูกลบ) — แสดง empty state ไม่ใช่ error กลาง
    if (apiStatus(error) === 404) {
      notFound.value = true
      account.value = null
      return
    }
    hasError.value = true
    void dialog.alert('เกิดข้อผิดพลาด', 'โหลดบัญชีของนักเรียนไม่สำเร็จ', 'error')
  } finally {
    if (detailGuard.isCurrent(token)) isLoading.value = false
  }
}

// route param เปลี่ยน (เช่นกดจากรายการเดินบัญชีของอีกคน) ⇒ โหลดใหม่ ไม่ค้างข้อมูลเก่า
watch(studentId, () => void loadAccount())

onMounted(loadAccount)
</script>

<template>
  <div class="space-y-3">
    <SkeletonRows v-if="isLoading" :rows="4" height="h-24" />

    <StateBlock
      v-else-if="notFound"
      variant="empty"
      icon="bi-person-x"
      title="ไม่พบบัญชีของนักเรียนคนนี้"
      hint="นักเรียนอาจถูกลบหรือไม่ได้อยู่ในห้องนี้ — กลับไปที่รายการบัญชีรายบุคคล"
    >
      <RouterLink to="/finance/individual-accounts" class="btn-ghost-ui">
        <i class="bi bi-arrow-left" aria-hidden="true"></i>
        กลับไปบัญชีรายบุคคล
      </RouterLink>
    </StateBlock>

    <StateBlock
      v-else-if="hasError"
      variant="error"
      title="โหลดบัญชีของนักเรียนไม่สำเร็จ"
      @retry="loadAccount"
    />

    <template v-else-if="account">
      <AccountSummaryCard :account="account" />

      <!-- ══════════════════════ บิลที่ยังเปิด ══════════════════════ -->
      <section class="page-card overflow-hidden">
        <div class="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
          <h2 class="font-display text-base font-bold text-ink-1">
            <i class="bi bi-receipt me-1.5 text-brand-700" aria-hidden="true"></i>
            บิลที่ยังค้าง
          </h2>
          <span class="chip bg-canvas text-ink-2">{{ account.open_bills.length }} รายการ</span>
        </div>

        <div
          v-if="!account.open_bills.length"
          class="px-4 py-8 text-center text-sm text-ink-3"
        >
          <i class="bi bi-check2-circle me-1 text-ok-600" aria-hidden="true"></i>
          ไม่มีบิลค้างของนักเรียนคนนี้
        </div>

        <template v-else>
          <!-- 📱 มือถือ: การ์ดต่อบิล -->
          <div class="space-y-2 p-3 lg:hidden">
            <div
              v-for="bill in account.open_bills"
              :key="bill.student_payment_id"
              class="rounded-control border p-3"
              :class="isOverdue(bill.due_date) ? 'border-danger-200 bg-danger-50' : 'border-line'"
            >
              <div class="flex items-start justify-between gap-3">
                <div class="min-w-0">
                  <p class="truncate text-sm font-bold text-ink-1">{{ bill.title }}</p>
                  <p class="mt-0.5 flex flex-wrap items-center gap-1.5 text-caption text-ink-3">
                    <span>{{ fundTypeLabel(bill.fund_type) }}</span>
                    <span v-if="bill.collection_kind === 'fine'" class="chip bg-warn-50 text-warn-700">
                      ค่าปรับ
                    </span>
                  </p>
                </div>
                <p class="num shrink-0 text-right text-sm font-bold text-danger-600">
                  {{ formatMoney(Number(bill.outstanding)) }}
                </p>
              </div>

              <div class="mt-2 flex items-center justify-between gap-3 text-caption text-ink-3">
                <span
                  class="flex items-center gap-1"
                  :class="isOverdue(bill.due_date) ? 'font-bold text-danger-700' : ''"
                >
                  <i class="bi bi-calendar-event" aria-hidden="true"></i>
                  {{ bill.due_date ? formatThaiDate(bill.due_date) : 'ไม่กำหนด' }}
                </span>
                <span class="num">
                  ยอด {{ formatAmount(Number(bill.amount)) }}
                  · จ่าย {{ formatAmount(Number(bill.paid_amount)) }}
                  <template v-if="Number(bill.written_off_amount) > 0">
                    · ตัด {{ formatAmount(Number(bill.written_off_amount)) }}
                  </template>
                </span>
              </div>
            </div>
          </div>

          <!-- 🖥️ เดสก์ท็อป: ตาราง -->
          <div class="hidden overflow-x-auto lg:block">
            <table class="data-table">
              <thead>
                <tr>
                  <th>ชื่อบิล</th>
                  <th>ประเภท</th>
                  <th>กำหนด</th>
                  <th class="text-right">ยอด (฿)</th>
                  <th class="text-right">จ่ายแล้ว (฿)</th>
                  <th class="text-right">ตัดจำหน่าย (฿)</th>
                  <th class="text-right">คงเหลือ (฿)</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="bill in account.open_bills"
                  :key="bill.student_payment_id"
                  :class="isOverdue(bill.due_date) ? 'bg-danger-50' : ''"
                >
                  <td class="font-bold text-ink-1">
                    {{ bill.title }}
                    <span
                      v-if="bill.collection_kind === 'fine'"
                      class="chip ms-1 bg-warn-50 text-warn-700"
                    >
                      ค่าปรับ
                    </span>
                  </td>
                  <td class="text-ink-2">{{ fundTypeLabel(bill.fund_type) }}</td>
                  <td
                    class="whitespace-nowrap"
                    :class="isOverdue(bill.due_date) ? 'font-bold text-danger-700' : 'text-ink-2'"
                  >
                    {{ bill.due_date ? formatThaiDate(bill.due_date) : 'ไม่กำหนด' }}
                  </td>
                  <td class="num whitespace-nowrap text-right text-ink-2">
                    {{ formatAmount(Number(bill.amount)) }}
                  </td>
                  <td class="num whitespace-nowrap text-right text-ink-2">
                    {{ formatAmount(Number(bill.paid_amount)) }}
                  </td>
                  <td class="num whitespace-nowrap text-right text-ink-2">
                    {{ formatAmount(Number(bill.written_off_amount)) }}
                  </td>
                  <td class="num whitespace-nowrap text-right font-bold text-danger-600">
                    {{ formatAmount(Number(bill.outstanding)) }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>
      </section>

      <!-- ══════════════════════ เครดิต ══════════════════════ -->
      <section class="page-card flex flex-wrap items-center justify-between gap-3 p-4 sm:p-5">
        <div class="flex items-center gap-3">
          <span
            class="flex h-10 w-10 shrink-0 items-center justify-center rounded-control bg-ok-50 text-ok-700"
          >
            <i class="bi bi-piggy-bank text-xl" aria-hidden="true"></i>
          </span>
          <div>
            <p class="text-caption font-bold text-ink-3">เครดิตคงเหลือ (เงินรับล่วงหน้า)</p>
            <p class="num text-lg font-bold text-ok-700">
              {{ formatMoney(Number(account.credit_balance)) }}
            </p>
            <p class="mt-0.5 text-caption text-ink-3">
              ใช้ได้ {{ formatMoney(Number(account.ready_to_apply)) }}
              — ใช้ปิดบิลได้ในขั้นตอนรับเงิน (เร็ว ๆ นี้)
            </p>
          </div>
        </div>
        <RouterLink to="/finance/credits" class="btn-ghost-ui shrink-0">
          <i class="bi bi-journal-text" aria-hidden="true"></i>
          ดูประวัติเงินรับล่วงหน้า
        </RouterLink>
      </section>

      <!-- ══════════════════════ ประวัติรับเงินล่าสุด ══════════════════════ -->
      <section class="page-card overflow-hidden">
        <div class="border-b border-line px-4 py-3">
          <h2 class="font-display text-base font-bold text-ink-1">
            <i class="bi bi-clock-history me-1.5 text-brand-700" aria-hidden="true"></i>
            ประวัติรับเงินล่าสุด
          </h2>
        </div>

        <div v-if="!account.recent_events.length" class="px-4 py-8 text-center text-sm text-ink-3">
          <i class="bi bi-inbox me-1" aria-hidden="true"></i>
          ยังไม่มีประวัติรับเงิน
        </div>

        <ul v-else class="divide-y divide-line">
          <li
            v-for="event in account.recent_events"
            :key="event.event_id"
            class="flex items-center justify-between gap-3 px-4 py-3"
          >
            <div class="min-w-0">
              <p class="text-sm font-bold text-ink-1">
                {{ formatThaiDateTime(event.event_at) }}
              </p>
              <p class="mt-0.5 text-caption text-ink-3">
                ผู้รับเงิน {{ event.receiver_name || '—' }}
                <template v-if="Number(event.credit_used) > 0">
                  · ใช้เครดิต {{ formatMoney(Number(event.credit_used)) }}
                </template>
              </p>
            </div>
            <p class="num shrink-0 text-sm font-bold text-ok-700">
              {{ formatMoney(Number(event.amount_received)) }}
            </p>
          </li>
        </ul>
      </section>
    </template>
  </div>
</template>
