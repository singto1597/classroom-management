<script setup lang="ts">
/**
 * AccountSummaryCard — ตัวเลขสรุปของนักเรียน 1 คน (บัญชีรายบุคคล)
 *
 * 🔑 ตัวเลข 4 ช่องนี้คือ "สัญญา" ของหน้า detail:
 *   ค้างทั้งหมด · เกินกำหนด · ยังไม่ถึงกำหนด · เครดิตคงเหลือ
 * ⇒ ปุ่มเดียวบนการ์ดคือ "ดูรายการเดินบัญชี" (statement) — การรับเงินจะมาใน P2.3
 *
 * ⚠️ เงินจาก API เป็น **string** ทศนิยม 2 ตำแหน่ง ⇒ ต้อง `Number()` ก่อน `formatMoney`
 *    (ถ้าส่ง string ตรง ๆ จะได้ ฿0.00 เงียบ ๆ — ดู Gotchas ของ brief P1.4)
 */
import { computed } from 'vue'
import type { IndividualAccountItem } from '@/types/finance'
import { formatMoney } from '@/utils/money'

const props = defineProps<{
  account: IndividualAccountItem;
}>()

const money = (value: string) => formatMoney(Number(value))

const hasOverdue = computed(() => Number(props.account.overdue_total) > 0)
const hasCredit = computed(() => Number(props.account.credit_balance) > 0)
</script>

<template>
  <section class="page-card p-4 sm:p-5">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div class="min-w-0">
        <div class="flex items-center gap-2">
          <span class="chip num shrink-0 bg-canvas text-ink-2">#{{ account.student_no }}</span>
          <h2 class="font-display min-w-0 truncate text-lg font-bold text-ink-1">
            {{ account.name }}
          </h2>
        </div>
        <p class="mt-1 text-xs text-ink-3">
          <i class="bi bi-info-circle me-1" aria-hidden="true"></i>
          ยอดค้างแสดงเฉพาะบิลที่ยังไม่ชำระ — หักยอดที่จ่ายแล้วและตัดจำหน่ายแล้ว
        </p>
      </div>

      <RouterLink
        :to="{
          name: 'finance-student-statement',
          params: { studentId: account.student_id },
        }"
        class="btn-ghost-ui shrink-0"
      >
        <i class="bi bi-journal-text" aria-hidden="true"></i>
        ดูรายการเดินบัญชี
      </RouterLink>
    </div>

    <div class="mt-3.5 grid grid-cols-2 gap-2.5 sm:grid-cols-4">
      <div class="rounded-control border border-line px-3 py-2.5">
        <p class="flex items-center gap-1.5 text-caption font-bold text-ink-3">
          <i class="bi bi-cash-stack text-brand-700" aria-hidden="true"></i>
          ค้างทั้งหมด
        </p>
        <p class="num mt-1.5 text-lg font-bold text-danger-600 sm:text-xl">
          {{ money(account.outstanding_total) }}
        </p>
      </div>

      <div class="rounded-control border border-line px-3 py-2.5">
        <p class="flex items-center gap-1.5 text-caption font-bold text-ink-3">
          <i class="bi bi-exclamation-triangle" aria-hidden="true"></i>
          เกินกำหนด
        </p>
        <p
          class="num mt-1.5 text-lg font-bold sm:text-xl"
          :class="hasOverdue ? 'text-danger-700' : 'text-ink-2'"
        >
          {{ money(account.overdue_total) }}
        </p>
      </div>

      <div class="rounded-control border border-line px-3 py-2.5">
        <p class="flex items-center gap-1.5 text-caption font-bold text-ink-3">
          <i class="bi bi-calendar-event" aria-hidden="true"></i>
          ยังไม่ถึงกำหนด
        </p>
        <p class="num mt-1.5 text-lg font-bold text-ink-1 sm:text-xl">
          {{ money(account.upcoming_total) }}
        </p>
      </div>

      <div class="rounded-control border border-line px-3 py-2.5">
        <p class="flex items-center gap-1.5 text-caption font-bold text-ink-3">
          <i class="bi bi-piggy-bank" aria-hidden="true"></i>
          เครดิตคงเหลือ
        </p>
        <p
          class="num mt-1.5 text-lg font-bold sm:text-xl"
          :class="hasCredit ? 'text-ok-700' : 'text-ink-2'"
        >
          {{ money(account.credit_balance) }}
        </p>
        <p v-if="hasCredit" class="mt-0.5 text-caption text-ink-3">
          ใช้ได้ {{ money(account.ready_to_apply) }}
        </p>
      </div>
    </div>
  </section>
</template>
