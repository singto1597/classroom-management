<script setup lang="ts">
/**
 * 📊 รายงานอายุหนี้ (Aging) — ผู้ค้างชำระทุกบิล ณ วันที่เลือก
 *
 * ════════════════════════════════════════════════════════════════════════════
 * 🔑 อ่านค่าอย่างเดียว — ไม่มีปุ่มเขียน และไม่นับเครดิตที่ยังไม่ถูกใช้
 * ════════════════════════════════════════════════════════════════════════════
 * ยอดค้างต่อบิล = `ยอดบิล - ชำระแล้ว` ตาม predicate "บิลเปิด" ตัวเดียวกับทั้งระบบ
 * ⇒ ยอดรวมหน้านี้ต้องตรงกับหน้าผู้ค้างชำระ/AR/ใบแจ้งหนี้รวม (ถ้าไม่ตรง = บั๊ก ไม่ใช่ตัวเลขต่างมุม)
 *
 * ถังอายุหนี้ (คำนวณฝั่ง backend, ส่งมาแล้ว):
 *   ไม่ระบุกำหนด · ยังไม่ครบกำหนด · ค้าง 1–30 · 31–60 · 61–90 · เกิน 90 วัน
 *   ⚠️ ครบกำหนด *วันนี้* = "ยังไม่ครบกำหนด" (overdue 0) ไม่ใช่ "ค้าง 1 วัน"
 *
 * 📌 ค่าปรับมีลิงก์ไปหน้า `/finance/fines/{id}` — ห้ามพาไปหน้าโปรเจกต์ซ่อน
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { FinanceService } from '@/services/finance'
import type { AgingResponse, AgingRow } from '@/types/finance'
import PageIntro from '@/components/ui/PageIntro.vue'
import StateBlock from '@/components/ui/StateBlock.vue'
import SkeletonRows from '@/components/ui/SkeletonRows.vue'
import AppTabs from '@/components/ui/AppTabs.vue'
import AppButton from '@/components/ui/AppButton.vue'
import AppChip from '@/components/ui/AppChip.vue'
import { createLatestGuard } from '@/utils/latest'
import { formatMoney } from '@/utils/money'
import { formatThaiDate, todayIso } from '@/utils/datetime'
import { useDialog } from '@/composables/useDialog'
import { downloadBlob } from '@/utils/download'

const authStore = useAuthStore()
const dialog = useDialog()
const currentRoomId = authStore.currentRoomId!
const currentUserName = authStore.currentUserName

const asOf = ref(todayIso())
const report = ref<AgingResponse | null>(null)
const isLoading = ref(true)
const hasError = ref(false)
const kindFilter = ref('all')
const isExporting = ref(false)

const guard = createLatestGuard()

const load = async () => {
  const token = guard.begin()
  isLoading.value = true
  hasError.value = false
  try {
    const res = await FinanceService.getReceivablesAging(currentRoomId, asOf.value)
    if (!guard.isCurrent(token)) return
    report.value = res
  } catch {
    if (!guard.isCurrent(token)) return
    hasError.value = true
  } finally {
    if (guard.isCurrent(token)) isLoading.value = false
  }
}

onMounted(load)
watch(asOf, load)

const kindTabs = computed(() => {
  const r = report.value
  return [
    { value: 'all', label: 'ทั้งหมด', count: r?.rows.length ?? 0 },
    {
      value: 'project',
      label: 'ค่าโครงการ',
      count: r ? r.rows.filter((row) => row.collection_kind !== 'fine').length : 0,
    },
    {
      value: 'fine',
      label: 'ค่าปรับ',
      count: r ? r.rows.filter((row) => row.collection_kind === 'fine').length : 0,
    },
  ]
})

const visibleRows = computed<AgingRow[]>(() => {
  const rows = report.value?.rows ?? []
  if (kindFilter.value === 'all') return rows
  if (kindFilter.value === 'fine') return rows.filter((r) => r.collection_kind === 'fine')
  return rows.filter((r) => r.collection_kind !== 'fine')
})

/** ยอดที่เลยกำหนดจริง (ไม่รวม "ยังไม่ครบกำหนด" / "ไม่ระบุกำหนด") */
const overdueAmount = computed(() => {
  const buckets = report.value?.buckets ?? []
  return buckets
    .filter((b) => ['1_30', '31_60', '61_90', 'over_90'].includes(b.bucket))
    .reduce((sum, b) => sum + b.amount, 0)
})

const kindLabel = (kind: string) => (kind === 'fine' ? 'ค่าปรับ' : 'โปรเจกต์')

const rowLink = (row: AgingRow) =>
  row.fine_id ? `/finance/fines/${row.fine_id}` : `/finance/collections/${row.collection_id}`

/** 📥 ส่งออกสมุดรายงานการเงิน (มีชีต "รายงานอายุหนี้" อยู่ท้ายเล่ม) */
const handleExport = async () => {
  if (isExporting.value) return
  isExporting.value = true
  void dialog.loading('กำลังสร้างไฟล์ Excel…', 'ระบบกำลังรวมรายงานการเงินทั้งเล่มให้คุณ')
  try {
    const iso = todayIso()
    const year = Number(iso.slice(0, 4))
    const month = Number(iso.slice(5, 7))
    const blob = await FinanceService.exportTransactionsExcel(
      currentRoomId,
      month,
      year,
      currentUserName ?? undefined,
    )
    const be = year + 543
    downloadBlob(blob, `รายงานการเงิน_${String(month).padStart(2, '0')}-${be}.xlsx`)
    dialog.close()
    dialog.notify('ดาวน์โหลดไฟล์ Excel แล้ว')
  } catch (error: unknown) {
    dialog.close()
    void dialog.alert(
      'ส่งออกไม่สำเร็จ',
      error instanceof Error ? error.message : 'ไม่มีไฟล์ถูกดาวน์โหลด',
      'error',
    )
  } finally {
    isExporting.value = false
  }
}
</script>

<template>
  <div class="space-y-4">
    <PageIntro
      description="ผู้ค้างชำระทุกบิล — แยกโปรเจกต์เก็บเงิน/ค่าปรับ × ถังอายุหนี้ ณ วันที่เลือก"
    >
      <template #actions>
        <AppButton variant="secondary" :loading="isExporting" @click="handleExport">
          <i class="bi bi-file-earmark-excel" aria-hidden="true"></i>
          ส่งออก Excel
        </AppButton>
      </template>
    </PageIntro>

    <div class="flex flex-wrap items-end gap-2">
      <div>
        <label class="field-label" for="aging-as-of">ณ วันที่</label>
        <input id="aging-as-of" v-model="asOf" type="date" class="field w-auto" />
      </div>
      <p class="pb-2.5 text-xs text-ink-3">
        ยอดค้างคิดจากบิลที่ยังเปิดอยู่ (ไม่นับเครดิตที่ยังไม่ถูกใช้)
      </p>
    </div>

    <SkeletonRows v-if="isLoading" :rows="4" height="h-20" />

    <StateBlock
      v-else-if="hasError"
      variant="error"
      title="โหลดรายงานอายุหนี้ไม่สำเร็จ"
      @retry="load"
    />

    <template v-else-if="report">
      <!-- ══════════════════════ KPI ══════════════════════ -->
      <div class="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
        <div class="page-card p-3.5">
          <p class="flex items-center gap-1.5 text-caption font-bold text-ink-3">
            <i class="bi bi-box-seam text-brand-700" aria-hidden="true"></i>
            ค้างชำระค่าโครงการ
          </p>
          <p class="num mt-1.5 text-lg font-bold text-ink sm:text-2xl">
            {{ formatMoney(report.project_total) }}
          </p>
        </div>

        <div class="page-card p-3.5">
          <p class="flex items-center gap-1.5 text-caption font-bold text-ink-3">
            <i class="bi bi-shield-exclamation text-brand-700" aria-hidden="true"></i>
            ค้างชำระค่าปรับ
          </p>
          <p class="num mt-1.5 text-lg font-bold text-ink sm:text-2xl">
            {{ formatMoney(report.fine_total) }}
          </p>
        </div>

        <div class="page-card p-3.5">
          <p class="flex items-center gap-1.5 text-caption font-bold text-ink-3">
            <i class="bi bi-cash-stack text-brand-700" aria-hidden="true"></i>
            รวมลูกหนี้ทั้งสิ้น
          </p>
          <p class="num mt-1.5 text-lg font-bold text-ink sm:text-2xl">
            {{ formatMoney(report.grand_total) }}
          </p>
        </div>

        <div class="page-card p-3.5">
          <p class="flex items-center gap-1.5 text-caption font-bold text-ink-3">
            <i class="bi bi-exclamation-triangle text-danger-600" aria-hidden="true"></i>
            เลยกำหนดแล้ว
          </p>
          <p class="num mt-1.5 text-lg font-bold text-danger-600 sm:text-2xl">
            {{ formatMoney(overdueAmount) }}
          </p>
        </div>
      </div>

      <!-- ══════════════════════ สรุปตามถัง ══════════════════════ -->
      <div class="page-card p-4 sm:p-5">
        <h2 class="section-title mb-3 flex items-center gap-2">
          <i class="bi bi-bar-chart-steps text-brand-700" aria-hidden="true"></i>
          สรุปตามถังอายุหนี้
        </h2>

        <div class="overflow-x-auto">
          <table class="w-full min-w-[34rem] text-sm">
            <thead>
              <tr class="border-b border-line text-left text-caption text-ink-3">
                <th class="py-2 pr-3 font-bold">ถังอายุหนี้</th>
                <th class="py-2 pr-3 text-right font-bold">จำนวน</th>
                <th class="py-2 pr-3 text-right font-bold">โครงการ</th>
                <th class="py-2 pr-3 text-right font-bold">ค่าปรับ</th>
                <th class="py-2 text-right font-bold">รวม</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="b in report.buckets"
                :key="b.bucket"
                class="border-b border-line/60 last:border-b-0"
              >
                <td class="py-2 pr-3 font-bold text-ink-2">{{ b.label }}</td>
                <td class="num py-2 pr-3 text-right text-ink-2">{{ b.count }}</td>
                <td class="num py-2 pr-3 text-right text-ink-2">
                  {{ formatMoney(b.project_amount) }}
                </td>
                <td class="num py-2 pr-3 text-right text-ink-2">{{ formatMoney(b.fine_amount) }}</td>
                <td class="num py-2 text-right font-bold text-ink">{{ formatMoney(b.amount) }}</td>
              </tr>
            </tbody>
            <tfoot>
              <tr class="border-t border-line font-bold">
                <td class="py-2 pr-3 text-ink">รวมทั้งสิ้น</td>
                <td class="num py-2 pr-3 text-right text-ink">{{ report.rows.length }}</td>
                <td class="num py-2 pr-3 text-right text-ink">
                  {{ formatMoney(report.project_total) }}
                </td>
                <td class="num py-2 pr-3 text-right text-ink">{{ formatMoney(report.fine_total) }}</td>
                <td class="num py-2 text-right text-ink">{{ formatMoney(report.grand_total) }}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      </div>

      <!-- ══════════════════════ รายละเอียดต่อบิล ══════════════════════ -->
      <div class="space-y-2">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <h2 class="section-title flex items-center gap-2">
            <i class="bi bi-list-ul text-brand-700" aria-hidden="true"></i>
            รายละเอียด ({{ visibleRows.length }})
          </h2>
        </div>

        <AppTabs v-model="kindFilter" :tabs="kindTabs" variant="segmented" group-label="กรองประเภทบิล" />

        <StateBlock
          v-if="!visibleRows.length"
          variant="empty"
          icon="bi-check2-circle"
          title="ไม่มีบิลค้างชำระในมุมมองนี้"
          hint="ลองเปลี่ยนวันที่ หรือสลับตัวกรองประเภท"
        />

        <div v-else class="overflow-x-auto rounded-card border border-line bg-surface">
          <table class="w-full min-w-[46rem] text-sm">
            <thead>
              <tr class="border-b border-line bg-canvas text-left text-caption text-ink-3">
                <th class="px-3 py-2.5 font-bold">นักเรียน</th>
                <th class="px-3 py-2.5 font-bold">รายการ</th>
                <th class="px-3 py-2.5 font-bold">ประเภท</th>
                <th class="px-3 py-2.5 font-bold">กำหนดชำระ</th>
                <th class="px-3 py-2.5 text-right font-bold">เลยกำหนด</th>
                <th class="px-3 py-2.5 font-bold">ถัง</th>
                <th class="px-3 py-2.5 text-right font-bold">คงค้าง</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="row in visibleRows"
                :key="row.payment_id"
                class="border-b border-line/60 last:border-b-0 hover:bg-canvas"
              >
                <td class="px-3 py-2.5">
                  <RouterLink :to="rowLink(row)" class="font-bold text-ink hover:text-brand">
                    {{ row.student_name }}
                  </RouterLink>
                  <span v-if="row.student_no" class="block text-caption text-ink-3">
                    เลขที่ {{ row.student_no }}
                  </span>
                </td>
                <td class="max-w-56 px-3 py-2.5">
                  <RouterLink :to="rowLink(row)" class="block truncate text-ink-2 hover:text-brand">
                    {{ row.collection_title }}
                  </RouterLink>
                </td>
                <td class="px-3 py-2.5">
                  <AppChip :tone="row.collection_kind === 'fine' ? 'warn' : 'neutral'">
                    {{ kindLabel(row.collection_kind) }}
                  </AppChip>
                </td>
                <td class="px-3 py-2.5 text-ink-2">
                  {{ row.due_date ? formatThaiDate(row.due_date) : 'ไม่ระบุ' }}
                </td>
                <td class="num px-3 py-2.5 text-right" :class="row.overdue_days > 0 ? 'text-danger-600 font-bold' : 'text-ink-3'">
                  {{ row.overdue_days > 0 ? `${row.overdue_days} วัน` : '—' }}
                </td>
                <td class="px-3 py-2.5">
                  <span
                    class="chip"
                    :class="
                      row.overdue_days > 0
                        ? 'bg-danger-50 text-danger-700'
                        : 'bg-canvas text-ink-2'
                    "
                  >
                    {{ row.bucket_label }}
                  </span>
                </td>
                <td class="num px-3 py-2.5 text-right font-bold text-ink">
                  {{ formatMoney(row.outstanding) }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>
  </div>
</template>
