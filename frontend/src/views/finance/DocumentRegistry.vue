<script setup lang="ts">
/**
 * 🗂️ [FIN-V2 / P5.2] หน้าทะเบียนเอกสารรวม — เอกสาร 8 ชนิดในตารางเดียว
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * ทำไมไม่แก้ `ReceiptList.vue`
 * ═══════════════════════════════════════════════════════════════════════════
 * ทะเบียนเดิมกรองได้ชนิดเดียว + `LIMIT 500` แข็ง + ไม่มี RPT และไม่มี cross-link
 * การ refactor ไฟล์ 1,200 บรรทัดในเฟส 5 เสี่ยงทำ legacy พังก่อน P6.5 ⇒ หน้านี้เป็น
 * **หน้าใหม่แยกสิ้นเชิง** ที่อ่าน API `GET /finance/documents` ของ P5.1
 * (P6.5 ค่อย redirect / ลบ view เก่า)
 *
 * 🔓 อ่านเปิดให้สมาชิก (`require_member` ฝั่ง backend) — ไม่มีปุ่มเขียนใด ๆ
 *    ยกเว้น "พิมพ์ชุด" ที่เป็นการอ่าน+เรนเดอร์ PDF
 *
 * 🔢 pagination เป็น **offset + 50 แถว** (สูงสุด 200 ตาม API) — ผู้ใช้ต้องเห็น `total`
 *    เพื่อตัดสินใจว่าจะแคบตัวกรองก่อนพิมพ์ชุดหรือไม่ (ไม่ทำ infinite scroll)
 *
 * 🆔 selection ใช้ composite key `${doc_type}:${doc_id}` — id ชนกันข้ามตารางได้จริง
 *    (REC id 12 กับ RPT id 12 มีพร้อมกัน)
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { RouterLink, useRouter } from 'vue-router';

import PageIntro from '@/components/ui/PageIntro.vue';
import SkeletonRows from '@/components/ui/SkeletonRows.vue';
import StateBlock from '@/components/ui/StateBlock.vue';
import DocumentFilters from '@/components/finance/DocumentFilters.vue';
import DocumentTypeBadge from '@/components/finance/DocumentTypeBadge.vue';

import { FinanceService } from '@/services/finance';
import { useAuthStore } from '@/stores/auth';
import { useDialog } from '@/composables/useDialog';
import { downloadBlob, combinedPdfFilename } from '@/utils/download';
import { createLatestGuard } from '@/utils/latest';
import { formatMoney } from '@/utils/money';
import { formatThaiDate, formatThaiDateTime } from '@/utils/datetime';
import {
  DOCUMENT_BUNDLE_MAX,
  canPrintBundle,
  selectionKey,
} from '@/utils/documentFilters';
import type {
  DocumentListItem,
  DocumentListQuery,
  PaymentChannel,
} from '@/types/finance';

const authStore = useAuthStore();
const dialog = useDialog();
const router = useRouter();
const currentRoomId = authStore.currentRoomId!;

/** ค่าปริยายเดียวกับ `REGISTRY_PAGE_DEFAULT` ฝั่ง backend */
const PAGE_SIZE = 50;

/** ตัวกรอง — เปลี่ยนค่าใดก็ตามต้องรีเซ็ต offset + selection (บทเรียน skills.md) */
const filters = ref<DocumentListQuery>({ status: 'active' });

const items = ref<DocumentListItem[]>([]);
const total = ref(0);
const limit = ref(PAGE_SIZE);
const offset = ref(0);

const isLoading = ref(true);
const hasError = ref(false);
const guard = createLatestGuard();

/** เลือกข้ามหน้าได้ — เก็บ object เต็มเพื่อพิมพ์ชุด/ตั้งชื่อไฟล์โดยไม่ต้อง fetch ซ้ำ */
const selectedItems = ref<DocumentListItem[]>([]);

const selectedKeys = computed(
  () => new Set(selectedItems.value.map((item) => selectionKey(item))),
);

const isSelected = (item: DocumentListItem): boolean =>
  selectedKeys.value.has(selectionKey(item));

const selectedTotal = computed(() =>
  selectedItems.value.reduce((sum, item) => sum + Number(item.amount ?? 0), 0),
);

// ── ป้ายชื่อช่องทาง (id → label) — โหลดครั้งเดียว ซ่อนเมื่อ endpoint ไม่พร้อม ──
const channelLabels = ref<Record<number, string>>({});

const channelLabel = (channelId: number | null): string => {
  if (channelId === null) return '—';
  return channelLabels.value[channelId] ?? `#${channelId}`;
};

// ── สถานะ ────────────────────────────────────────────────────────────────
const STATUS_LABELS: Record<string, string> = {
  active: 'ใช้งาน',
  voided: 'ยกเลิก',
  draft: 'ร่าง',
  final: 'ปิดแล้ว',
};

const statusLabel = (status: string): string => STATUS_LABELS[status] ?? status;

const isVoidedStatus = (status: string): boolean => status === 'voided';

// ── โหลด ─────────────────────────────────────────────────────────────────
/** ช่วงวันที่กลับด้าน (from > to) — backend จะคืน 0 แถวโดยไม่บอกสาเหตุ ⇒ เตือนที่หน้าจอ */
const isRangeReversed = computed(() => {
  const { from, to } = filters.value;
  return Boolean(from && to && from > to);
});

const load = async () => {
  if (isRangeReversed.value) {
    items.value = [];
    total.value = 0;
    isLoading.value = false;
    hasError.value = false;
    return;
  }

  const token = guard.begin();
  isLoading.value = true;
  hasError.value = false;
  try {
    const res = await FinanceService.getDocuments(currentRoomId, {
      ...filters.value,
      limit: PAGE_SIZE,
      offset: offset.value,
    });
    if (!guard.isCurrent(token)) return;
    items.value = res.items;
    total.value = res.total;
    limit.value = res.limit;
  } catch {
    if (!guard.isCurrent(token)) return;
    items.value = [];
    total.value = 0;
    hasError.value = true;
  } finally {
    if (guard.isCurrent(token)) isLoading.value = false;
  }
};

/** เปลี่ยนตัวกรอง ⇒ กลับหน้าแรก + ล้างที่ติ๊ก (ห้ามติ๊กค้างข้ามตัวกรอง) */
watch(
  filters,
  () => {
    offset.value = 0;
    selectedItems.value = [];
    void load();
  },
  { deep: true },
);

/** ปุ่ม "ค้นหา"/Enter — ใช้โหลดซ้ำแม้ค่าไม่ได้เปลี่ยน (เช่นกดหลังเจอ error) */
const onSubmit = () => {
  offset.value = 0;
  void load();
};

onMounted(async () => {
  void load();
  try {
    const channels: PaymentChannel[] =
      await FinanceService.getPaymentChannels(currentRoomId);
    const map: Record<number, string> = {};
    for (const channel of channels) map[channel.id] = channel.label;
    channelLabels.value = map;
  } catch {
    // ⚠️ ยังไม่มี P2.4 ในสาขานี้ = แสดง `#id` แทน ไม่ทำให้ทั้งหน้าพัง
    channelLabels.value = {};
  }
});

// ── เลือกหลายใบ → พิมพ์ชุด ───────────────────────────────────────────────
const allSelected = computed(
  () => items.value.length > 0 && items.value.every(isSelected),
);

const toggleSelected = (item: DocumentListItem) => {
  const key = selectionKey(item);
  selectedItems.value = isSelected(item)
    ? selectedItems.value.filter((entry) => selectionKey(entry) !== key)
    : [...selectedItems.value, item];
};

/** เลือก/ปลด "ทั้งหมดในหน้านี้" — ไม่แตะใบที่เลือกไว้จากหน้าอื่น */
const toggleSelectAll = () => {
  if (allSelected.value) {
    const visible = new Set(items.value.map((item) => selectionKey(item)));
    selectedItems.value = selectedItems.value.filter(
      (item) => !visible.has(selectionKey(item)),
    );
    return;
  }
  const existing = selectedKeys.value;
  const additions = items.value.filter(
    (item) => !existing.has(selectionKey(item)),
  );
  selectedItems.value = [...selectedItems.value, ...additions];
};

const isPrinting = ref(false);

const printBundle = async () => {
  if (isPrinting.value) return;
  const count = selectedItems.value.length;
  if (!canPrintBundle(count)) {
    void dialog.alert(
      'พิมพ์ชุดไม่ได้',
      count === 0
        ? 'เลือกเอกสารก่อนพิมพ์ชุด'
        : `พิมพ์ได้ครั้งละไม่เกิน ${DOCUMENT_BUNDLE_MAX} ใบ (เลือกไว้ ${count} ใบ) — กรุณาแบ่งรอบ`,
      'warning',
    );
    return;
  }
  isPrinting.value = true;
  void dialog.loading('กำลังสร้างไฟล์ PDF...', 'ระบบกำลังรวมเอกสารเป็นไฟล์เดียว');
  try {
    const refs = selectedItems.value.map((item) => ({
      doc_type: item.doc_type,
      doc_id: item.doc_id,
    }));
    const blob = await FinanceService.printDocumentBundle(currentRoomId, refs);
    const names = selectedItems.value.map(
      (item) => item.doc_no ?? `${item.doc_type}-${item.doc_id}`,
    );
    downloadBlob(blob, combinedPdfFilename(names, 'documents'));
    dialog.close();
  } catch (error: unknown) {
    dialog.close();
    void dialog.alert(
      'สร้างไฟล์ PDF ไม่สำเร็จ',
      error instanceof Error ? error.message : 'กรุณาลองใหม่อีกครั้ง',
      'error',
    );
  } finally {
    isPrinting.value = false;
  }
};

// ── pagination ───────────────────────────────────────────────────────────
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / limit.value)));
const currentPage = computed(() => Math.floor(offset.value / limit.value) + 1);
const rangeStart = computed(() => (total.value === 0 ? 0 : offset.value + 1));
const rangeEnd = computed(() => Math.min(offset.value + items.value.length, total.value));

const goToPage = (page: number) => {
  const clamped = Math.min(Math.max(1, page), pageCount.value);
  if (clamped === currentPage.value) return;
  offset.value = (clamped - 1) * limit.value;
  // ที่ติ๊กไว้ **ไม่ถูกล้าง** — ผู้ใช้เลือกข้ามหน้าเพื่อพิมพ์ชุดได้
  void load();
};

// ── นำทาง ────────────────────────────────────────────────────────────────
const openDocument = (item: Pick<DocumentListItem, 'doc_type' | 'doc_id'>) => {
  void router.push({
    name: 'finance-document-detail',
    params: { docType: item.doc_type, docId: item.doc_id },
  });
};

/** คลิกแถว = เปิด — แต่ต้องไม่กลืนคลิก checkbox/ปุ่ม/ลิงก์ที่อยู่บนแถว */
const onRowClick = (item: DocumentListItem, event: MouseEvent) => {
  const target = event.target as HTMLElement | null;
  if (target?.closest('input, button, a, label, select')) return;
  openDocument(item);
};

const amountText = (value: string | null): string =>
  value === null ? '—' : formatMoney(Number(value));

/**
 * ⏱️ `doc_at` ต่างชนิดกัน: เอกสารการเงินเป็น timestamp แต่ RPT/ช่วงสรุปอาจเป็น date-only
 * ⚠️ ห้ามยัด date-only เข้า `formatThaiDateTime` — จะขึ้น "07:00" ปลอมจากเที่ยงคืน UTC
 *    และห้ามยัด timestamp เข้า `formatThaiDate` — มันตัดสตริงเอาแต่วันที่แบบ UTC (±1 วัน)
 */
const formatDocAt = (value: string | null): string => {
  if (!value) return '—';
  return value.length === 10 ? formatThaiDate(value) : formatThaiDateTime(value);
};

onBeforeUnmount(() => {
  // กล่อง loading ค้างได้ถ้าออกหน้ากลางการสร้าง PDF
  dialog.close();
});
</script>

<template>
  <div class="space-y-4 sm:space-y-5">
    <PageIntro
      description="เอกสารทุกชนิดของห้องอยู่ในที่เดียว — กรองตามวันที่ นักเรียน ผู้รับ ช่องทาง หรือสถานะ แล้วเลือกหลายใบเพื่อพิมพ์เป็นชุด"
    >
      <template #actions>
        <RouterLink to="/finance/receipts" class="btn-ghost-ui">
          <i class="bi bi-archive" aria-hidden="true"></i>
          ทะเบียนแบบเดิม
        </RouterLink>
      </template>
    </PageIntro>

    <DocumentFilters v-model="filters" @submit="onSubmit" />

    <p
      v-if="isRangeReversed"
      class="chip bg-warn-50 text-warn-700"
      role="status"
    >
      <i class="bi bi-exclamation-triangle-fill" aria-hidden="true"></i>
      วันที่เริ่มต้องไม่มากกว่าวันที่สิ้นสุด — กรุณาแก้ช่วงวันที่
    </p>

    <!-- แถบสรุป + ปุ่มพิมพ์ชุด -->
    <div class="page-card flex flex-wrap items-center justify-between gap-3 p-3 sm:p-4">
      <div class="flex min-w-0 flex-wrap items-center gap-2">
        <span class="chip bg-canvas text-ink-2">
          <i class="bi bi-files" aria-hidden="true"></i>
          ทั้งหมด <span class="num font-bold">{{ total }}</span> รายการ
        </span>
        <p class="min-w-0 truncate text-xs font-bold text-ink-3">
          <template v-if="selectedItems.length">
            เลือก <span class="num text-brand-700">{{ selectedItems.length }}</span> ใบ —
            รวม {{ formatMoney(selectedTotal) }}
          </template>
          <template v-else>ติ๊กเลือกเอกสารเพื่อพิมพ์รวมเป็นไฟล์เดียว (หน้าละใบ)</template>
        </p>
      </div>
      <button
        v-if="selectedItems.length"
        type="button"
        class="btn-primary shrink-0"
        :disabled="isPrinting"
        @click="printBundle"
      >
        <i
          class="bi"
          :class="isPrinting ? 'bi-hourglass-split' : 'bi-file-earmark-zip'"
          aria-hidden="true"
        ></i>
        พิมพ์ชุด ({{ selectedItems.length }})
      </button>
    </div>

    <SkeletonRows v-if="isLoading" :rows="6" height="h-16" />

    <template v-else>
      <StateBlock v-if="hasError" variant="error" @retry="load" />

      <StateBlock
        v-else-if="!items.length"
        variant="empty"
        icon="bi-folder2-open"
        title="ไม่พบเอกสารตามตัวกรองนี้"
        hint="ลองขยายช่วงวันที่ เปลี่ยนสถานะเป็น 'ทั้งหมด' หรือล้างตัวกรอง"
      />

      <template v-else>
        <!-- 📱 มือถือ — การ์ดต่อแถว ไม่ใช้ตารางเลื่อนแนวนอน -->
        <div class="space-y-2.5 lg:hidden">
          <label
            class="page-card flex min-h-11 cursor-pointer items-center gap-2 p-3 text-sm font-bold text-ink-3"
          >
            <input
              type="checkbox"
              class="peer sr-only"
              :checked="allSelected"
              aria-label="เลือกเอกสารทั้งหมดในหน้านี้"
              @change="toggleSelectAll"
            />
            <span
              class="flex h-5 w-5 shrink-0 items-center justify-center rounded-md border-2 transition-colors peer-focus-visible:ring-2 peer-focus-visible:ring-brand-500/40 peer-focus-visible:ring-offset-2"
              :class="allSelected ? 'border-brand-700 bg-brand-700' : 'border-line bg-surface'"
            >
              <i
                v-if="allSelected"
                class="bi bi-check-lg text-xs font-bold text-white"
                aria-hidden="true"
              ></i>
            </span>
            เลือกทั้งหมดในหน้านี้
          </label>

          <div
            v-for="item in items"
            :key="selectionKey(item)"
            class="page-card p-4"
            @click="onRowClick(item, $event)"
          >
            <div class="flex items-start justify-between gap-3">
              <div class="flex min-w-0 items-start gap-2">
                <label class="flex cursor-pointer items-center pt-0.5">
                  <input
                    type="checkbox"
                    class="peer sr-only"
                    :checked="isSelected(item)"
                    :aria-label="`เลือกเอกสาร ${item.doc_no ?? item.doc_id}`"
                    @change="toggleSelected(item)"
                  />
                  <span
                    class="flex h-5 w-5 shrink-0 items-center justify-center rounded-md border-2 transition-colors peer-focus-visible:ring-2 peer-focus-visible:ring-brand-500/40 peer-focus-visible:ring-offset-2"
                    :class="
                      isSelected(item)
                        ? 'border-brand-700 bg-brand-700'
                        : 'border-line bg-surface'
                    "
                  >
                    <i
                      v-if="isSelected(item)"
                      class="bi bi-check-lg text-xs font-bold text-white"
                      aria-hidden="true"
                    ></i>
                  </span>
                </label>
                <div class="min-w-0">
                  <RouterLink
                    :to="{
                      name: 'finance-document-detail',
                      params: { docType: item.doc_type, docId: item.doc_id },
                    }"
                    class="num block min-h-11 text-sm font-bold text-ink hover:text-brand"
                  >
                    {{ item.doc_no ?? `#${item.doc_id}` }}
                  </RouterLink>
                  <p class="mt-0.5 text-xs text-ink-3">
                    {{ item.student_name || item.receiver_name || '—' }}
                    <span v-if="item.student_no" class="num">— เลขที่ {{ item.student_no }}</span>
                  </p>
                </div>
              </div>
              <div class="shrink-0 text-right">
                <p class="num text-base font-bold text-ink">{{ amountText(item.amount) }}</p>
                <DocumentTypeBadge :doc-type="item.doc_type" class="mt-1" />
              </div>
            </div>

            <div
              class="mt-2.5 flex flex-wrap items-center justify-between gap-2 border-t border-line pt-2.5"
            >
              <small class="num text-caption font-bold text-ink-3">
                <i class="bi bi-clock" aria-hidden="true"></i>
                {{ formatDocAt(item.doc_at) }}
              </small>
              <span
                class="chip"
                :class="
                  isVoidedStatus(item.status)
                    ? 'bg-danger-50 text-danger-700'
                    : 'bg-canvas text-ink-2'
                "
              >
                {{ statusLabel(item.status) }}
              </span>
            </div>
          </div>
        </div>

        <!-- 🖥️ เดสก์ท็อป -->
        <div class="page-card hidden overflow-hidden lg:block">
          <div class="overflow-x-auto">
            <table class="data-table">
              <thead>
                <tr>
                  <th class="w-10">
                    <label class="flex cursor-pointer items-center" title="เลือกทั้งหมดในหน้านี้">
                      <input
                        type="checkbox"
                        class="peer sr-only"
                        :checked="allSelected"
                        aria-label="เลือกเอกสารทั้งหมดในหน้านี้"
                        @change="toggleSelectAll"
                      />
                      <span
                        class="flex h-5 w-5 shrink-0 items-center justify-center rounded-md border-2 transition-colors peer-focus-visible:ring-2 peer-focus-visible:ring-brand-500/40 peer-focus-visible:ring-offset-2"
                        :class="
                          allSelected ? 'border-brand-700 bg-brand-700' : 'border-line bg-surface'
                        "
                      >
                        <i
                          v-if="allSelected"
                          class="bi bi-check-lg text-xs font-bold text-white"
                          aria-hidden="true"
                        ></i>
                      </span>
                    </label>
                  </th>
                  <th>ชนิด</th>
                  <th>เลขที่เอกสาร</th>
                  <th>วันที่</th>
                  <th>นักเรียน</th>
                  <th>ผู้รับ</th>
                  <th>ช่องทาง</th>
                  <th class="text-right">ยอด</th>
                  <th class="text-right">สถานะ</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="item in items"
                  :key="selectionKey(item)"
                  class="cursor-pointer"
                  @click="onRowClick(item, $event)"
                >
                  <td>
                    <label class="flex cursor-pointer items-center">
                      <input
                        type="checkbox"
                        class="peer sr-only"
                        :checked="isSelected(item)"
                        :aria-label="`เลือกเอกสาร ${item.doc_no ?? item.doc_id}`"
                        @change="toggleSelected(item)"
                      />
                      <span
                        class="flex h-5 w-5 shrink-0 items-center justify-center rounded-md border-2 transition-colors peer-focus-visible:ring-2 peer-focus-visible:ring-brand-500/40 peer-focus-visible:ring-offset-2"
                        :class="
                          isSelected(item)
                            ? 'border-brand-700 bg-brand-700'
                            : 'border-line bg-surface'
                        "
                      >
                        <i
                          v-if="isSelected(item)"
                          class="bi bi-check-lg text-xs font-bold text-white"
                          aria-hidden="true"
                        ></i>
                      </span>
                    </label>
                  </td>
                  <td>
                    <DocumentTypeBadge :doc-type="item.doc_type" :show-icon="false" />
                  </td>
                  <td>
                    <RouterLink
                      :to="{
                        name: 'finance-document-detail',
                        params: { docType: item.doc_type, docId: item.doc_id },
                      }"
                      class="num font-bold text-ink hover:text-brand"
                    >
                      {{ item.doc_no ?? `#${item.doc_id}` }}
                    </RouterLink>
                  </td>
                  <td class="num whitespace-nowrap text-ink-2">
                    {{ formatDocAt(item.doc_at) }}
                  </td>
                  <td>
                    <span class="block text-ink">
                      {{ item.student_name || '—' }}
                    </span>
                    <span v-if="item.student_no" class="num text-caption text-ink-3">
                      เลขที่ {{ item.student_no }}
                    </span>
                  </td>
                  <td>
                    <span class="block text-ink-2">
                      {{ item.receiver_name || '—' }}
                    </span>
                  </td>
                  <td class="max-w-40">
                    <span class="block truncate text-ink-2">
                      {{ channelLabel(item.channel_id) }}
                    </span>
                  </td>
                  <td class="num whitespace-nowrap text-right font-bold text-ink">
                    {{ amountText(item.amount) }}
                  </td>
                  <td class="text-right">
                    <span
                      class="chip"
                      :class="
                        isVoidedStatus(item.status)
                          ? 'bg-danger-50 text-danger-700'
                          : 'bg-canvas text-ink-2'
                      "
                    >
                      {{ statusLabel(item.status) }}
                    </span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- pagination -->
        <div class="flex flex-wrap items-center justify-between gap-3">
          <p class="text-xs font-bold text-ink-3">
            แสดง <span class="num">{{ rangeStart }}–{{ rangeEnd }}</span> จาก
            <span class="num">{{ total }}</span> รายการ
          </p>
          <div class="flex items-center gap-2">
            <button
              type="button"
              class="btn-ghost-ui"
              :disabled="currentPage <= 1"
              @click="goToPage(currentPage - 1)"
            >
              <i class="bi bi-chevron-left" aria-hidden="true"></i>
              ก่อนหน้า
            </button>
            <span class="num text-xs font-bold text-ink-2">
              หน้า {{ currentPage }} / {{ pageCount }}
            </span>
            <button
              type="button"
              class="btn-ghost-ui"
              :disabled="currentPage >= pageCount"
              @click="goToPage(currentPage + 1)"
            >
              ถัดไป
              <i class="bi bi-chevron-right" aria-hidden="true"></i>
            </button>
          </div>
        </div>
      </template>
    </template>
  </div>
</template>
