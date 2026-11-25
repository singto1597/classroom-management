<script setup lang="ts">
/**
 * 📒 รายการเดินบัญชีนักเรียน (FIN-V2 / P1.4)
 *
 * แสดงบิล/รับเงิน/เครดิตของนักเรียน 1 คนตามช่วงวันที่ — เรียงจากเก่าไปใหม่
 * (backend เรียงให้แล้ว) พร้อม `balance_after` ของบรรทัดเครดิต
 *
 * 🔒 ไม่มี pagination โดยเจตนา: **ช่วงวันที่คือตัวจำกัด** — backend ตัดที่
 *    `STATEMENT_MAX_ROWS` (2000) แล้วตอบ 400 พร้อมข้อความไทย ⇒ หน้านี้แค่บอกผู้ใช้
 *    ให้แคบช่วงลง (ข้อความจาก backend ผ่าน `error.message` ของ interceptor)
 */
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { FinanceService } from '@/services/finance'
import { apiStatus } from '@/services/api'
import type { StudentStatementResponse } from '@/types/finance'
import { createLatestGuard } from '@/utils/latest'
import { formatMoney } from '@/utils/money'
import { formatThaiDate, formatThaiDateTime, todayIso } from '@/utils/datetime'
import { firstDayOfMonth, lastDayOfMonth, todayThaiYearMonth } from '@/utils/period'

import StateBlock from '@/components/ui/StateBlock.vue'
import SkeletonRows from '@/components/ui/SkeletonRows.vue'
import { useDialog } from '@/composables/useDialog'

const route = useRoute()
const authStore = useAuthStore()
const dialog = useDialog()
const currentRoomId = authStore.currentRoomId!

const statement = ref<StudentStatementResponse | null>(null)
const isLoading = ref(true)
const hasError = ref(false)
const notFound = ref(false)

// '' = ไม่กรอง (เว้นว่าง = ทั้งหมด) — date input คืน '' เมื่อล้างค่า
const dateFrom = ref('')
const dateTo = ref('')

const listGuard = createLatestGuard()
const studentId = computed(() => Number(route.params.studentId))

/** ป้ายประเภทบรรทัด — `description` มาจาก backend อยู่แล้ว แต่ป้ายสั้นช่วยกวาดตาง่าย */
const KIND_LABELS: Record<string, string> = {
  bill: 'บิล',
  payment: 'รับเงิน',
  payment_event: 'รับเงิน',
  credit_topup: 'เติมเครดิต',
  credit_apply: 'ใช้เครดิต',
  credit_reverse: 'คืนเครดิต',
}
const kindLabel = (kind: string) => KIND_LABELS[kind] ?? kind

const isNegative = (amount: string) => Number(amount) < 0

const loadStatement = async () => {
  const token = listGuard.begin()
  isLoading.value = true
  hasError.value = false
  notFound.value = false
  try {
    const res = await FinanceService.getStudentStatement(currentRoomId, studentId.value, {
      from: dateFrom.value || undefined,
      to: dateTo.value || undefined,
    })
    if (!listGuard.isCurrent(token)) return
    statement.value = res
  } catch (error) {
    if (!listGuard.isCurrent(token)) return
    if (apiStatus(error) === 404) {
      notFound.value = true
      statement.value = null
      return
    }
    // 400 = ช่วงกว้างเกิน 2000 แถว หรือ `from` หลัง `to` — backend ส่งข้อความไทยมาแล้ว
    if (apiStatus(error) === 400) {
      // 🧹 ล้างผลเดิมทิ้ง — ถ้าคงตารางของช่วงก่อนไว้ ผู้ใช้จะอ่านตัวเลขเก่าโดยนึกว่า
      //    เป็นผลของช่วงที่เพิ่งเลือก (dialog ไม่ได้ขึ้นค้างบนจอตลอดไป)
      statement.value = null
      void dialog.alert(
        'ช่วงข้อมูลกว้างเกินไป',
        error instanceof Error ? error.message : 'กรุณาเลือกช่วงวันที่ให้แคบลง',
        'warning'
      )
      return
    }
    hasError.value = true
    void dialog.alert('เกิดข้อผิดพลาด', 'โหลดรายการเดินบัญชีไม่สำเร็จ', 'error')
  } finally {
    if (listGuard.isCurrent(token)) isLoading.value = false
  }
}

const setToday = () => {
  const today = todayIso()
  dateFrom.value = today
  dateTo.value = today
}

const setThisMonth = () => {
  const { year, month } = todayThaiYearMonth()
  dateFrom.value = firstDayOfMonth(year, month)
  dateTo.value = lastDayOfMonth(year, month)
}

const clearRange = () => {
  dateFrom.value = ''
  dateTo.value = ''
}

// เปลี่ยนช่วงวันที่ → โหลดใหม่ (ไม่ debounce: ผู้ใช้เลือกจาก date picker แล้วจบ)
watch([dateFrom, dateTo], () => void loadStatement())

watch(studentId, () => void loadStatement())

const rangeLabel = computed(() => {
  if (!statement.value) return ''
  const from = statement.value.date_from
  const to = statement.value.date_to
  if (!from && !to) return 'ทั้งประวัติ'
  return `${from ? formatThaiDate(from) : 'เริ่มต้น'} – ${to ? formatThaiDate(to) : 'ปัจจุบัน'}`
})

onMounted(loadStatement)
</script>

<template>
  <div class="space-y-3">
    <StateBlock
      v-if="notFound"
      variant="empty"
      icon="bi-person-x"
      title="ไม่พบบัญชีของนักเรียนคนนี้"
      hint="นักเรียนอาจถูกลบหรือไม่ได้อยู่ในห้องนี้"
    >
      <RouterLink to="/finance/individual-accounts" class="btn-ghost-ui">
        <i class="bi bi-arrow-left" aria-hidden="true"></i>
        กลับไปบัญชีรายบุคคล
      </RouterLink>
    </StateBlock>

    <template v-else>
      <!-- ══════════════════════ หัว/ตัวกรอง ══════════════════════ -->
      <div class="page-card p-4 sm:p-5">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div class="min-w-0">
            <div class="flex items-center gap-2">
              <span v-if="statement" class="chip num shrink-0 bg-canvas text-ink-2">
                #{{ statement.student_no }}
              </span>
              <h2 class="font-display min-w-0 truncate text-lg font-bold text-ink-1">
                {{ statement?.name || 'รายการเดินบัญชี' }}
              </h2>
            </div>
            <p class="mt-1 text-xs text-ink-3">
              <i class="bi bi-info-circle me-1" aria-hidden="true"></i>
              ช่วง: {{ rangeLabel }} · บิล · รับเงิน · เครดิต เรียงจากเก่าไปใหม่
            </p>
          </div>

          <RouterLink
            v-if="statement"
            :to="{
              name: 'finance-individual-account-detail',
              params: { studentId: statement.student_id },
            }"
            class="btn-ghost-ui shrink-0"
          >
            <i class="bi bi-person-vcard" aria-hidden="true"></i>
            ดูบัญชีนักเรียน
          </RouterLink>
        </div>

        <div class="mt-3 flex flex-wrap items-end gap-2">
          <label class="flex flex-col gap-1 text-caption font-bold text-ink-3">
            ตั้งแต่วันที่
            <input v-model="dateFrom" type="date" class="field text-sm" aria-label="ตั้งแต่วันที่" />
          </label>
          <label class="flex flex-col gap-1 text-caption font-bold text-ink-3">
            ถึงวันที่
            <input v-model="dateTo" type="date" class="field text-sm" aria-label="ถึงวันที่" />
          </label>

          <div class="flex flex-wrap items-center gap-2">
            <button type="button" class="btn-ghost-ui" @click="setToday">วันนี้</button>
            <button type="button" class="btn-ghost-ui" @click="setThisMonth">เดือนนี้</button>
            <button
              v-if="dateFrom || dateTo"
              type="button"
              class="btn-ghost-ui"
              @click="clearRange"
            >
              ทั้งหมด
            </button>
          </div>
        </div>
      </div>

      <SkeletonRows v-if="isLoading" :rows="5" height="h-16" />

      <StateBlock
        v-else-if="hasError"
        variant="error"
        title="โหลดรายการเดินบัญชีไม่สำเร็จ"
        @retry="loadStatement"
      />

      <StateBlock
        v-else-if="!statement || !statement.entries.length"
        variant="empty"
        icon="bi-journal-text"
        title="ไม่มีรายการในช่วงเวลานี้"
        hint="ลองขยายช่วงวันที่ หรือล้างตัวกรองเพื่อดูทั้งประวัติ"
      />

      <template v-else>
        <!-- ══════════════════════ 🖥️ เดสก์ท็อป: ตาราง ══════════════════════ -->
        <div class="page-card hidden overflow-hidden lg:block">
          <div class="overflow-x-auto">
            <table class="data-table">
              <thead>
                <tr>
                  <th class="w-44">วันที่</th>
                  <th class="w-28">ประเภท</th>
                  <th>รายละเอียด</th>
                  <th class="text-right">จำนวน (฿)</th>
                  <th class="text-right">คงเหลือเครดิต (฿)</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="entry in statement.entries" :key="entry.entry_id">
                  <td class="num whitespace-nowrap text-ink-2">
                    {{ formatThaiDateTime(entry.occurred_at) }}
                  </td>
                  <td>
                    <span class="chip bg-canvas text-ink-2">{{ kindLabel(entry.kind) }}</span>
                  </td>
                  <td class="text-ink-1">{{ entry.description }}</td>
                  <td class="whitespace-nowrap text-right">
                    <span
                      class="num font-bold"
                      :class="isNegative(entry.amount) ? 'text-ok-700' : 'text-ink-1'"
                    >
                      {{ formatMoney(Number(entry.amount)) }}
                    </span>
                  </td>
                  <td class="num whitespace-nowrap text-right text-ink-2">
                    {{ entry.balance_after === null ? '—' : formatMoney(Number(entry.balance_after)) }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- ══════════════════════ 📱 มือถือ: การ์ด ══════════════════════ -->
        <div class="space-y-2.5 lg:hidden">
          <div
            v-for="entry in statement.entries"
            :key="entry.entry_id"
            class="page-card p-3.5"
          >
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0">
                <div class="flex items-center gap-1.5">
                  <span class="chip shrink-0 bg-canvas text-ink-2">{{ kindLabel(entry.kind) }}</span>
                  <span class="truncate text-sm font-bold text-ink-1">{{ entry.description }}</span>
                </div>
                <p class="num mt-1 text-caption text-ink-3">
                  {{ formatThaiDateTime(entry.occurred_at) }}
                </p>
              </div>
              <div class="shrink-0 text-right">
                <p
                  class="num text-sm font-bold"
                  :class="isNegative(entry.amount) ? 'text-ok-700' : 'text-ink-1'"
                >
                  {{ formatMoney(Number(entry.amount)) }}
                </p>
                <p v-if="entry.balance_after !== null" class="num text-caption text-ink-3">
                  คงเหลือ {{ formatMoney(Number(entry.balance_after)) }}
                </p>
              </div>
            </div>
          </div>
        </div>

        <p class="text-caption text-ink-3">
          <i class="bi bi-info-circle me-1" aria-hidden="true"></i>
          จำนวนมีเครื่องหมายตามผลต่อยอดค้างของนักเรียน (บิลเป็นบวก · รับเงินเป็นลบ)
        </p>
      </template>
    </template>
  </div>
</template>
