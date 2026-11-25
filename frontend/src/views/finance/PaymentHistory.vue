<script setup lang="ts">
/**
 * 📜 ประวัติการรับเงิน — payment event + การส่งมอบเงินสด ในไทม์ไลน์เดียว (FIN-V2 / P3.4)
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * 🎯 หลักคิด
 * ═══════════════════════════════════════════════════════════════════════════
 * อ่านเหตุการณ์จริงแทนการไล่ดูบิลทีละใบ — 1 ครั้งที่รับเงิน = 1 แถว พร้อมผู้จ่าย
 * ผู้รับ เงินสด/เครดิตที่ใช้/เครดิตที่เพิ่ม และเอกสาร REC/DEP · handover อยู่
 * ไทม์ไลน์เดียวกัน
 *
 * 🔓 สมาชิกทุกคนอ่านได้ (`require_member` ฝั่ง backend) — 🚫 [P6.3] ผู้มีสิทธิ์จัดการ
 *    การเงินเห็นปุ่ม "ยกเลิกเหตุการณ์" บน event ที่ยัง active (ยกเลิก REC+DEP+เครดิต
 *    พร้อมกันที่ backend) — handover ไม่มีปุ่ม (P3.1 ไม่มี void endpoint ของมันเอง)
 *
 * 🔑 pagination เป็น **cursor** `(occurred_at, kind, id)` จาก backend — ห้าม
 *    ใช้ offset เอง; "โหลดเพิ่ม" ต้องส่ง `next_cursor` เดิมกลับไปเท่านั้น
 *
 * 🗓️ กลุ่มวันใช้ **วันไทย** (Asia/Bangkok) — event 23:30 UTC คือวันถัดไปในไทย
 *    (ดู `utils/datetime.ts` หัวไฟล์)
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { useAuthStore } from '@/stores/auth'
import { FinanceService } from '@/services/finance'
import type {
  PaymentHistoryItem,
  PaymentHistoryLine,
  PaymentHistoryQuery,
} from '@/types/finance'

import PageIntro from '@/components/ui/PageIntro.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppChip from '@/components/ui/AppChip.vue'
import PeriodPicker from '@/components/finance/PeriodPicker.vue'
import VoidReasonModal from '@/components/finance/VoidReasonModal.vue'
import SkeletonRows from '@/components/ui/SkeletonRows.vue'
import StateBlock from '@/components/ui/StateBlock.vue'
import { useDialog } from '@/composables/useDialog'
import { createLatestGuard } from '@/utils/latest'
import { formatMoney } from '@/utils/money'
import {
  BANGKOK_TZ,
  formatThaiDate,
  formatThaiDateTimeParts,
  todayIso,
} from '@/utils/datetime'
import { firstDayOfMonth, lastDayOfMonth, type PeriodValue } from '@/utils/period'

const authStore = useAuthStore()
const dialog = useDialog()
const roomId = authStore.currentRoomId!

const PAGE_SIZE = 30
const KIND_OPTIONS = [
  { value: 'all', label: 'ทั้งหมด' },
  { value: 'event', label: 'รับเงิน' },
  { value: 'handover', label: 'ส่งมอบเงิน' },
] as const

type HistoryKind = (typeof KIND_OPTIONS)[number]['value']

/** `YYYY-MM-DD` ย้อนหลัง n วันจากวันนี้ (วันไทย) — คำนวณผ่าน UTC เพื่อไม่ให้ TZ อุปกรณ์ดันวัน */
const isoMinusDays = (days: number): string => {
  const d = new Date(`${todayIso()}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() - days)
  return d.toISOString().slice(0, 10)
}

const defaultPeriod = (): PeriodValue => ({
  mode: 'range',
  startDate: isoMinusDays(29), // 30 วันล่าสุดรวมวันนี้
  endDate: todayIso(),
})

const period = ref<PeriodValue>(defaultPeriod())
const kind = ref<HistoryKind>('all')
const searchInput = ref('')

const items = ref<PaymentHistoryItem[]>([])
const nextCursor = ref<string | null>(null)
const isLoading = ref(true)
const isLoadingMore = ref(false)
const hasError = ref(false)
const expandedIds = ref<Set<string>>(new Set())

const guard = createLatestGuard()

const itemKey = (item: PaymentHistoryItem): string => `${item.kind}-${item.id}`

/** แปลง period ที่ผู้ใช้เลือก → ช่วงวันไทย `from`/`to` (YYYY-MM-DD) */
const rangeOf = (p: PeriodValue): { from: string; to: string } => {
  if (p.mode === 'range') return { from: p.startDate, to: p.endDate }
  if (p.mode === 'month') {
    return { from: firstDayOfMonth(p.year, p.month), to: lastDayOfMonth(p.year, p.month) }
  }
  return { from: p.asOfDate, to: p.asOfDate }
}

const buildQuery = (cursor?: string): PaymentHistoryQuery => {
  const range = rangeOf(period.value)
  const query: PaymentHistoryQuery = {
    from: range.from,
    to: range.to,
    kind: kind.value,
    limit: PAGE_SIZE,
  }
  const term = searchInput.value.trim()
  if (term) query.q = term
  if (cursor) query.cursor = cursor
  return query
}

const load = async () => {
  const token = guard.begin()
  isLoading.value = true
  hasError.value = false
  expandedIds.value = new Set()
  try {
    const res = await FinanceService.getPaymentHistory(roomId, buildQuery())
    if (!guard.isCurrent(token)) return
    items.value = res.items
    nextCursor.value = res.next_cursor
  } catch {
    if (!guard.isCurrent(token)) return
    items.value = []
    nextCursor.value = null
    hasError.value = true
  } finally {
    if (guard.isCurrent(token)) isLoading.value = false
  }
}

const loadMore = async () => {
  const cursor = nextCursor.value
  if (!cursor || isLoadingMore.value) return
  const token = guard.begin()
  isLoadingMore.value = true
  try {
    const res = await FinanceService.getPaymentHistory(roomId, buildQuery(cursor))
    if (!guard.isCurrent(token)) return
    // 🛡️ กันซ้ำ: ข้อมูลใหม่แทรกได้ แต่ cursor ถูกออกแบบมาไม่ให้ซ้ำ — กันไว้อีกชั้น
    const seen = new Set(items.value.map(itemKey))
    items.value = [...items.value, ...res.items.filter((it) => !seen.has(itemKey(it)))]
    nextCursor.value = res.next_cursor
  } catch (error: unknown) {
    if (!guard.isCurrent(token)) return
    void dialog.alert(
      'โหลดเพิ่มไม่สำเร็จ',
      error instanceof Error && error.message ? error.message : 'กรุณาลองใหม่อีกครั้ง',
      'error',
    )
  } finally {
    if (guard.isCurrent(token)) isLoadingMore.value = false
  }
}

// ── ตัวกรอง → โหลดใหม่ (ค้นหา debounce 300ms ตาม pattern autocomplete) ─────
let searchTimer: ReturnType<typeof setTimeout> | null = null
watch(searchInput, () => {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    searchTimer = null
    void load()
  }, 300)
})
watch(period, () => void load(), { deep: true })
watch(kind, () => void load())

onMounted(load)
onBeforeUnmount(() => {
  if (searchTimer) clearTimeout(searchTimer)
})

const hasFilters = computed(
  () => kind.value !== 'all' || searchInput.value.trim() !== ''
)

const clearFilters = () => {
  const nextFrom = isoMinusDays(29)
  const nextTo = todayIso()
  const current = period.value
  const wasDefault =
    kind.value === 'all' &&
    searchInput.value.trim() === '' &&
    current.mode === 'range' &&
    current.startDate === nextFrom &&
    current.endDate === nextTo
  kind.value = 'all'
  searchInput.value = ''
  period.value = { mode: 'range', startDate: nextFrom, endDate: nextTo }
  // ค่าเดิมทุกช่อง → watcher ไม่ยิง ⇒ โหลดเอง (ถ้ามีอะไรเปลี่ยน watcher จัดการแทน)
  if (wasDefault) void load()
}

// ── จัดกลุ่มตามวันไทย ────────────────────────────────────────────────────
interface DayGroup {
  key: string
  label: string
  items: PaymentHistoryItem[]
}

/** timestamp → วันที่แบบไทย YYYY-MM-DD ('en-CA' ให้รูป ISO ตรง ๆ) */
const bangkokIsoDate = (iso: string): string =>
  new Intl.DateTimeFormat('en-CA', { timeZone: BANGKOK_TZ }).format(new Date(iso))

const dayLabel = (isoDate: string): string => {
  if (isoDate === todayIso()) return 'วันนี้'
  if (isoDate === isoMinusDays(1)) return 'เมื่อวาน'
  return formatThaiDate(isoDate)
}

const groups = computed<DayGroup[]>(() => {
  const out: DayGroup[] = []
  const index = new Map<string, DayGroup>()
  for (const item of items.value) {
    const key = bangkokIsoDate(item.occurred_at)
    let group = index.get(key)
    if (!group) {
      group = { key, label: dayLabel(key), items: [] }
      index.set(key, group)
      out.push(group)
    }
    group.items.push(item)
  }
  return out
})

// ── ตัวช่วยแสดงผล ───────────────────────────────────────────────────────
/** "25 พ.ย. 2569 · 14:30 น." — timestamp ต้องแปลงเป็นโซนไทย (ห้ามใช้ formatThaiDate) */
const stamp = (iso: string): string => {
  const parts = formatThaiDateTimeParts(iso)
  return `${parts.date} · ${parts.time} น.`
}

const LINE_KIND_LABELS: Record<PaymentHistoryLine['line_kind'], string> = {
  bill: 'ปิดบิล',
  credit_apply: 'ใช้เครดิตปิดบิล',
  credit_topup: 'เติมเครดิต',
}

const DOC_TYPE_LABELS: Record<string, string> = {
  receipt: 'REC',
  deposit: 'DEP',
}

const docLabel = (docType: string): string => DOC_TYPE_LABELS[docType] ?? docType.toUpperCase()

const docLink = (receiptNo: string): string => `/finance/receipts/${encodeURIComponent(receiptNo)}`

const toggleExpanded = (item: PaymentHistoryItem) => {
  const key = itemKey(item)
  const next = new Set(expandedIds.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  expandedIds.value = next
}

const isExpanded = (item: PaymentHistoryItem): boolean => expandedIds.value.has(itemKey(item))

// ── 🚫 ยกเลิกเหตุการณ์รับเงิน (FIN-V2 / P6.3) ─────────────────────────────
//
// 🔴 ไม่มี idempotency key (ตั้งใจ) — กดซ้ำต้องได้ 409 จาก backend
// 🔴 หลังสำเร็จ **ห้ามลบการ์ดออก** — ประวัติคือหลักฐาน; reload แล้วเห็น badge "ยกเลิกแล้ว"

const canManageFinance = computed(() => authStore.canManageFinance)

const isVoidOpen = ref(false)
const isVoiding = ref(false)
const voidError = ref('')
const voidTarget = ref<PaymentHistoryItem | null>(null)

const canVoidEvent = (item: PaymentHistoryItem): boolean =>
  canManageFinance.value && !!item.event && item.status === 'active'

const openVoid = (item: PaymentHistoryItem) => {
  voidTarget.value = item
  voidError.value = ''
  isVoidOpen.value = true
}

/** สรุปสิ่งที่กำลังจะถูกกลับ — ค่าจาก event ที่ backend ส่งมา (ห้ามคำนวณ) */
const voidSummary = computed<Array<{ label: string; value: string }>>(() => {
  const target = voidTarget.value
  if (!target?.event) return []
  return [
    { label: 'ผู้จ่าย', value: target.event.payer_name },
    { label: 'ผู้รับเงิน', value: target.event.receiver_name },
    { label: 'ยอดที่ใช้', value: formatMoney(target.event.total_applied) },
    { label: 'เวลา', value: stamp(target.occurred_at) },
  ]
})

const confirmVoid = async (reason: string) => {
  const target = voidTarget.value
  if (!target || isVoiding.value) return
  isVoiding.value = true
  voidError.value = ''
  try {
    await FinanceService.voidPaymentEvent(roomId, target.id, { reason })
    isVoidOpen.value = false
    await dialog.alert(
      'ยกเลิกแล้ว',
      'เหตุการณ์รับเงินและเอกสารที่เกิดจากรายการนี้ถูกยกเลิกแล้ว — การ์ดยังอยู่ในประวัติพร้อมป้ายยกเลิก',
      'success',
    )
    // 🔄 โหลดช่วงเดิมใหม่ทั้งหน้า — ไม่พยายามแก้เฉพาะการ์ด (กันสองแหล่งความจริง)
    await load()
  } catch (error: unknown) {
    voidError.value = error instanceof Error ? error.message : 'ยกเลิกเหตุการณ์ไม่สำเร็จ'
  } finally {
    isVoiding.value = false
  }
}
</script>

<template>
  <div class="space-y-4">
    <PageIntro
      description="เหตุการณ์รับเงินและการส่งมอบเงินสด เรียงจากใหม่ไปเก่า — อ่านอย่างเดียว"
    />

    <!-- ══════════════════════ ตัวกรอง ══════════════════════ -->
    <div class="space-y-3">
      <PeriodPicker v-model="period" :modes="['range', 'month']" label="ช่วงวันที่" />

      <div class="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end">
        <div>
          <label class="field-label" for="history-kind">ชนิดรายการ</label>
          <select id="history-kind" v-model="kind" class="field sm:w-44">
            <option v-for="opt in KIND_OPTIONS" :key="opt.value" :value="opt.value">
              {{ opt.label }}
            </option>
          </select>
        </div>

        <div class="min-w-0 flex-1 sm:max-w-md">
          <label class="field-label" for="history-q">ค้นหาชื่อผู้จ่าย/ผู้รับ</label>
          <input
            id="history-q"
            v-model="searchInput"
            type="search"
            class="field"
            placeholder="พิมพ์ชื่อ…"
            autocomplete="off"
          />
        </div>

        <AppButton variant="secondary" :disabled="!hasFilters" @click="clearFilters">
          <i class="bi bi-eraser" aria-hidden="true"></i>
          ล้างตัวกรอง
        </AppButton>
      </div>
    </div>

    <SkeletonRows v-if="isLoading" :rows="5" height="h-24" />

    <StateBlock
      v-else-if="hasError"
      variant="error"
      title="โหลดประวัติการรับเงินไม่สำเร็จ"
      @retry="load"
    />

    <StateBlock
      v-else-if="!items.length"
      variant="empty"
      icon="bi-inbox"
      title="ยังไม่มีเหตุการณ์ในช่วงนี้"
      hint="ลองขยายช่วงวันที่ หรือล้างตัวกรอง"
    />

    <template v-else>
      <section v-for="group in groups" :key="group.key" class="space-y-2">
        <h2 class="flex items-center gap-2 pt-1 text-sm font-bold text-ink-2">
          <i class="bi bi-calendar3 text-brand-700" aria-hidden="true"></i>
          {{ group.label }}
          <span class="num text-caption font-normal text-ink-3">({{ group.items.length }})</span>
        </h2>

        <article
          v-for="item in group.items"
          :key="`${item.kind}-${item.id}`"
          class="page-card p-3.5 sm:p-4"
        >
          <!-- ───────────── รับเงิน (payment event) ───────────── -->
          <template v-if="item.event">
            <div class="flex flex-wrap items-start justify-between gap-2">
              <div class="min-w-0">
                <div class="flex flex-wrap items-center gap-1.5">
                  <AppChip tone="brand" icon="bi-cash-coin">รับเงิน</AppChip>
                  <AppChip v-if="item.status === 'voided'" tone="danger" icon="bi-x-circle">
                    ยกเลิกแล้ว
                  </AppChip>
                  <span class="num text-xs text-ink-3">{{ stamp(item.occurred_at) }}</span>
                </div>

                <p class="mt-1.5 flex flex-wrap items-center gap-1.5 font-bold text-ink">
                  <span>{{ item.event.payer_name }}</span>
                  <i class="bi bi-arrow-right text-ink-3" aria-hidden="true"></i>
                  <span>{{ item.event.receiver_name }}</span>
                </p>
                <p class="text-xs text-ink-3">
                  นักเรียน: {{ item.event.student_name ?? '—' }}
                  <template v-if="item.event.reference_no">
                    · อ้างอิง {{ item.event.reference_no }}
                  </template>
                </p>
              </div>

              <div class="text-right">
                <p class="text-caption text-ink-3">ยอดที่ใช้</p>
                <p class="num text-lg font-bold text-ink">
                  {{ formatMoney(item.event.total_applied) }}
                </p>
              </div>
            </div>

            <div class="mt-2 flex flex-wrap items-center gap-1.5">
              <AppChip v-if="item.event.amount_received > 0" tone="ok" icon="bi-cash">
                เงินสด {{ formatMoney(item.event.amount_received) }}
              </AppChip>
              <AppChip v-if="item.event.credit_used > 0" tone="info" icon="bi-wallet2">
                เครดิตใช้ {{ formatMoney(item.event.credit_used) }}
              </AppChip>
              <AppChip v-if="item.event.credit_added > 0" tone="warn" icon="bi-plus-circle">
                เครดิตเพิ่ม {{ formatMoney(item.event.credit_added) }}
              </AppChip>

              <RouterLink
                v-for="doc in item.event.documents"
                :key="`${doc.doc_type}-${doc.receipt_no}`"
                :to="docLink(doc.receipt_no)"
                class="chip bg-brand-tint text-brand hover:underline"
              >
                <i class="bi bi-file-earmark-text" aria-hidden="true"></i>
                {{ docLabel(doc.doc_type) }} {{ doc.receipt_no }}
                <template v-if="doc.status === 'voided'">(ยกเลิก)</template>
              </RouterLink>
            </div>

            <!-- 🚫 ยกเลิกเหตุการณ์ — เฉพาะ event ที่ยัง active และผู้มีสิทธิ์จัดการการเงิน -->
            <div v-if="canVoidEvent(item)" class="mt-2 flex justify-end">
              <AppButton variant="quiet" @click="openVoid(item)">
                <i class="bi bi-x-octagon" aria-hidden="true"></i>
                ยกเลิกเหตุการณ์
              </AppButton>
            </div>

            <button
              v-if="item.event.lines.length"
              type="button"
              class="mt-2 inline-flex min-h-9 items-center gap-1 text-xs font-bold text-brand hover:underline"
              @click="toggleExpanded(item)"
            >
              <i
                class="bi"
                :class="isExpanded(item) ? 'bi-chevron-up' : 'bi-chevron-down'"
                aria-hidden="true"
              ></i>
              {{ isExpanded(item) ? 'ซ่อนรายละเอียด' : `ดูรายละเอียด (${item.event.lines.length})` }}
            </button>

            <div
              v-if="isExpanded(item)"
              class="mt-2 overflow-x-auto rounded-control border border-line"
            >
              <table class="w-full min-w-[30rem] text-sm">
                <thead>
                  <tr class="border-b border-line bg-canvas text-left text-caption text-ink-3">
                    <th class="px-2.5 py-2 font-bold">รายการ</th>
                    <th class="px-2.5 py-2 font-bold">ประเภท</th>
                    <th class="px-2.5 py-2 text-right font-bold">ยอดบิลก่อน</th>
                    <th class="px-2.5 py-2 text-right font-bold">ยอดบิลหลัง</th>
                    <th class="px-2.5 py-2 text-right font-bold">จำนวน</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="(line, index) in item.event.lines"
                    :key="index"
                    class="border-b border-line/60 last:border-b-0"
                  >
                    <td class="px-2.5 py-2 text-ink-2">{{ line.collection_title ?? '—' }}</td>
                    <td class="px-2.5 py-2 text-ink-2">{{ LINE_KIND_LABELS[line.line_kind] }}</td>
                    <td class="num px-2.5 py-2 text-right text-ink-2">
                      {{ line.bill_before === null ? '—' : formatMoney(line.bill_before) }}
                    </td>
                    <td class="num px-2.5 py-2 text-right text-ink-2">
                      {{ line.bill_after === null ? '—' : formatMoney(line.bill_after) }}
                    </td>
                    <td class="num px-2.5 py-2 text-right font-bold text-ink">
                      {{ formatMoney(line.amount) }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </template>

          <!-- ───────────── ส่งมอบเงินสด (custody handover) ───────────── -->
          <template v-else-if="item.handover">
            <div class="flex flex-wrap items-start justify-between gap-2">
              <div class="min-w-0">
                <div class="flex flex-wrap items-center gap-1.5">
                  <AppChip tone="info" icon="bi-box-arrow-in-down">ส่งมอบเงิน</AppChip>
                  <AppChip v-if="item.status === 'voided'" tone="danger" icon="bi-x-circle">
                    ยกเลิกแล้ว
                  </AppChip>
                  <span class="num text-xs text-ink-3">{{ stamp(item.occurred_at) }}</span>
                </div>

                <p class="mt-1.5 flex flex-wrap items-center gap-1.5 font-bold text-ink">
                  <span>{{ item.handover.from_account_name ?? '—' }}</span>
                  <i class="bi bi-arrow-right text-ink-3" aria-hidden="true"></i>
                  <span>{{ item.handover.to_account_name ?? '—' }}</span>
                </p>
                <p class="text-xs text-ink-3">
                  ผู้ส่ง: {{ item.handover.handed_over_by_name ?? '—' }}
                  · ผู้รับ: {{ item.handover.received_by_name ?? '—' }}
                </p>
                <p v-if="item.handover.note" class="mt-1 text-xs text-ink-3">
                  หมายเหตุ: {{ item.handover.note }}
                </p>
                <p v-if="item.handover.void_reason" class="mt-1 text-xs text-danger-700">
                  เหตุผลยกเลิก: {{ item.handover.void_reason }}
                </p>
              </div>

              <div class="text-right">
                <p class="text-caption text-ink-3">จำนวน</p>
                <p class="num text-lg font-bold text-ink">
                  {{ formatMoney(item.handover.amount) }}
                </p>
              </div>
            </div>
          </template>
        </article>
      </section>

      <div v-if="nextCursor" class="flex justify-center pt-1">
        <AppButton variant="secondary" :loading="isLoadingMore" @click="loadMore">
          โหลดเพิ่ม
        </AppButton>
      </div>
    </template>

    <!-- ════════════════ แผ่น: ยกเลิกเหตุการณ์รับเงิน (P6.3) ════════════════ -->
    <VoidReasonModal
      :open="isVoidOpen && !!voidTarget"
      title="ยกเลิกเหตุการณ์รับเงิน"
      description="เงิน/เครดิตที่รับไว้จะถูกย้อนกลับ และเอกสาร REC/DEP ของรายการนี้จะถูกยกเลิกพร้อมกัน"
      :summary="voidSummary"
      :busy="isVoiding"
      :error-message="voidError"
      @close="isVoidOpen = false"
      @confirm="confirmVoid"
    />
  </div>
</template>
