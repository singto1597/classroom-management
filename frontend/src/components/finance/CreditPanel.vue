<script setup lang="ts">
/**
 * 💳 CreditPanel — แผงเครดิตของนักเรียน 1 คน (FIN-V2 / P3.3)
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * 🔑 กติกาที่ห้ามพลาด
 * ═══════════════════════════════════════════════════════════════════════════
 *  1. **ยกเลิกตรงได้เฉพาะรายการที่ไม่ได้มาจากใบรับเงิน** (`payment_event_id = null`)
 *     แถวที่มาจาก payment event ต้องยกเลิกที่ใบรับเงินนั้น (void engine, P6.1)
 *     ⇒ ห้ามแสดงปุ่มยกเลิกให้แถว event เด็ดขาด (กดแล้วได้ 409 เปล่า ๆ)
 *  2. ตัวเลขเงินใช้ `formatMoney` และ **ห้าม `truncate`** (ดู `docs/skills.md`)
 *  3. แผงนี้ **ไม่เรียก API เอง** — parent เป็นเจ้าของการโหลด/คำขอ (idempotency อยู่ที่ฟอร์ม)
 *  4. `entry_type_label` มาจาก backend — ไม่เขียนฉลากซ้ำที่นี่
 */
import type { StudentCreditBalance, StudentCreditEntry } from '@/types/finance'
import AppCard from '@/components/ui/AppCard.vue'
import AppChip from '@/components/ui/AppChip.vue'
import AppButton from '@/components/ui/AppButton.vue'
import SkeletonRows from '@/components/ui/SkeletonRows.vue'
import StateBlock from '@/components/ui/StateBlock.vue'
import { formatMoney } from '@/utils/money'
import { formatThaiDateTime } from '@/utils/datetime'

const props = withDefaults(
  defineProps<{
    student: StudentCreditBalance
    entries: StudentCreditEntry[]
    /** 🔒 `authStore.canManageFinance` — ไม่ใช่ `isAdmin` */
    canManage: boolean
    loading?: boolean
  }>(),
  { loading: false },
)

const emit = defineEmits<{
  topup: [student: StudentCreditBalance]
  apply: [student: StudentCreditBalance]
  history: [student: StudentCreditBalance]
  undo: [entry: StudentCreditEntry]
}>()

const ENTRY_TONE = {
  topup: 'ok',
  apply: 'warn',
  reverse: 'neutral',
} as const

const entryTone = (type: string) =>
  ENTRY_TONE[type as keyof typeof ENTRY_TONE] ?? 'neutral'

/** แถวนี้มาจากใบรับเงิน (payment event) หรือเป็นรายการเดิมของระบบ */
const isFromEvent = (entry: StudentCreditEntry): boolean =>
  entry.payment_event_id !== null && entry.payment_event_id !== undefined

/** ยกเลิกตรงได้เฉพาะ "หักปิดบิล" ที่ไม่ผูกกับใบรับเงิน */
const canUndoDirectly = (entry: StudentCreditEntry): boolean =>
  props.canManage && entry.entry_type === 'apply' && !isFromEvent(entry)
</script>

<template>
  <div class="space-y-4">
    <AppCard padding="md" class="space-y-3">
      <div class="flex items-start justify-between gap-3">
        <div class="min-w-0">
          <p class="text-caption font-bold text-ink-3">เครดิตคงเหลือ</p>
          <!-- 🔴 ห้ามใส่ `truncate` ที่บรรทัดตัวเลขเงิน -->
          <p
            data-test="credit-balance"
            class="num mt-0.5 text-2xl font-bold"
            :class="student.credit_balance > 0 ? 'text-ok-600' : 'text-ink-3'"
          >
            {{ formatMoney(student.credit_balance) }}
          </p>
        </div>
        <div class="shrink-0 text-right">
          <p class="text-caption font-bold text-ink-3">ต้องเก็บจริงหลังหักเครดิต</p>
          <p
            class="num mt-0.5 whitespace-nowrap text-base font-bold"
            :class="student.net_pending_amount > 0 ? 'text-danger-600' : 'text-ok-600'"
          >
            {{ formatMoney(student.net_pending_amount) }}
          </p>
        </div>
      </div>

      <div class="flex flex-wrap items-center gap-2 border-t border-line pt-2.5">
        <span class="chip shrink-0 bg-canvas text-ink-2">
          ยอดค้างดิบ {{ formatMoney(student.total_pending_amount) }}
        </span>
        <span class="text-caption text-ink-3">
          เงินก้อนนี้ยังไม่นับเป็นรายได้ จนกว่าจะถูกหักปิดบิล
        </span>
      </div>

      <div class="flex flex-wrap items-center gap-2">
        <AppButton v-if="canManage" variant="primary" @click="emit('topup', student)">
          <i class="bi bi-plus-circle" aria-hidden="true"></i>
          เติมเงินล่วงหน้า
        </AppButton>
        <AppButton
          v-if="canManage"
          variant="secondary"
          :disabled="student.credit_balance <= 0"
          @click="emit('apply', student)"
        >
          <i class="bi bi-scissors" aria-hidden="true"></i>
          ใช้เครดิตปิดบิล
        </AppButton>
        <AppButton variant="quiet" class="ml-auto" @click="emit('history', student)">
          <i class="bi bi-clock-history" aria-hidden="true"></i>
          ประวัติ
        </AppButton>
      </div>
    </AppCard>

    <SkeletonRows v-if="loading" :rows="3" height="h-16" />

    <StateBlock
      v-else-if="!entries.length"
      variant="empty"
      icon="bi-journal"
      title="ยังไม่มีรายการเครดิต"
      hint="เมื่อมีการเติมเงินล่วงหน้าหรือหักปิดบิล รายการจะปรากฏที่นี่"
    />

    <ul v-else class="space-y-2">
      <li
        v-for="entry in entries"
        :key="entry.id"
        class="rounded-control border border-line bg-surface p-3"
      >
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0">
            <div class="flex flex-wrap items-center gap-2">
              <AppChip :tone="entryTone(entry.entry_type)">
                {{ entry.entry_type_label ?? entry.entry_type }}
              </AppChip>
              <AppChip
                :tone="isFromEvent(entry) ? 'info' : 'neutral'"
                :icon="isFromEvent(entry) ? 'bi-receipt' : 'bi-archive'"
              >
                {{ isFromEvent(entry) ? `จากใบรับเงิน #${entry.payment_event_id}` : 'รายการเดิม' }}
              </AppChip>
              <span class="text-caption text-ink-3">{{ formatThaiDateTime(entry.created_at) }}</span>
            </div>
            <p class="mt-1 min-w-0 text-caption text-ink-2">
              <template v-if="entry.collection_title">{{ entry.collection_title }}</template>
              <template v-else-if="entry.receipt_no">ใบรับเงินล่วงหน้า {{ entry.receipt_no }}</template>
              <template v-else>{{ entry.note ?? '—' }}</template>
            </p>
            <p v-if="entry.recorded_by" class="mt-0.5 text-caption text-ink-3">
              โดย {{ entry.recorded_by }}
            </p>
          </div>

          <div class="shrink-0 text-right">
            <p class="num font-bold text-ink">{{ formatMoney(entry.amount) }}</p>
            <p class="text-caption text-ink-3">
              คงเหลือ {{ formatMoney(entry.balance_after) }}
            </p>

            <!-- ↩️ ยกเลิกตรงได้เฉพาะรายการหักที่ไม่ได้มาจากใบรับเงิน -->
            <AppButton
              v-if="canUndoDirectly(entry)"
              variant="quiet"
              class="mt-1.5"
              @click="emit('undo', entry)"
            >
              <i class="bi bi-arrow-counterclockwise" aria-hidden="true"></i>
              ยกเลิกการหักนี้
            </AppButton>
            <!-- 🧾 แถวจาก event: บอกทางออก ไม่ใช่ปุ่มที่กดแล้วได้ 409 -->
            <p
              v-else-if="entry.entry_type === 'apply' && isFromEvent(entry)"
              class="mt-1.5 text-caption font-bold text-ink-3"
            >
              ยกเลิกที่ใบรับเงิน
            </p>
          </div>
        </div>
      </li>
    </ul>
  </div>
</template>
