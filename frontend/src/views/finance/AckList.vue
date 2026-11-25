<script setup lang="ts">
/**
 * 🧾 [FIN-V2 / P5.5] AckList — ใบรับทราบยอดค้าง (ACK) — `/finance/acknowledgements`
 *
 * 🔓 อ่านเปิดให้สมาชิก (backend `require_member`) · ปุ่มออกใบเฉพาะ `canManageFinance`
 *    (backend บังคับ `MANAGE_FINANCE` ซ้ำ)
 *
 * ⚠️ ACK = "รับทราบหนี้" ไม่ใช่หลักฐานชำระเงิน — ไม่มียอดรับเงิน/ช่องทางชำระ
 *    และการยกเลิกไม่กระทบยอดบัญชีใด ๆ
 *
 * 🖨️ ใบที่ **ยกเลิกแล้วพิมพ์ได้เสมอ** — เป็นหลักฐานว่าเคยแจ้งใครไว้ เทมเพลตประทับ
 *    "ยกเลิก" ให้เอง · ปุ่มพิมพ์จึงไม่ถูกปิดตามสถานะ
 *
 * 🗓️ ตัวกรองเป็นช่วงวันที่ (`from`/`to`) เท่านั้น — endpoint ไม่มี `as_of`/`month`
 *    ⇒ ใช้ `toRange()` แปลง ปฏิเสธโหมดที่แปลงไม่ได้
 */
import { computed, onMounted, ref, watch } from 'vue';
import { useRouter } from 'vue-router';

import PageIntro from '@/components/ui/PageIntro.vue';
import StateBlock from '@/components/ui/StateBlock.vue';
import SkeletonRows from '@/components/ui/SkeletonRows.vue';
import PeriodPicker from '@/components/finance/PeriodPicker.vue';
import AckIssueModal from '@/components/finance/AckIssueModal.vue';

import { FinanceService } from '@/services/finance';
import { useAuthStore } from '@/stores/auth';
import { useDialog } from '@/composables/useDialog';
import { createLatestGuard } from '@/utils/latest';
import { downloadBlob } from '@/utils/download';
import { formatMoney } from '@/utils/money';
import { formatThaiDateTimeParts } from '@/utils/datetime';
import {
  isRangeReversed,
  toRange,
  todayThaiYearMonth,
  type PeriodValue,
} from '@/utils/period';
import type { AckListItem } from '@/types/finance';

const authStore = useAuthStore();
const router = useRouter();
const dialog = useDialog();
const currentRoomId = authStore.currentRoomId!;

const canManageFinance = computed(() => authStore.canManageFinance);

const initial = todayThaiYearMonth();
const period = ref<PeriodValue>({ mode: 'month', month: initial.month, year: initial.year });

const items = ref<AckListItem[]>([]);
const isLoading = ref(true);
const hasError = ref(false);
const isIssuing = ref(false);
/** เลขที่เอกสารที่กำลังดาวน์โหลด PDF — ใช้โชว์ spinner เฉพาะแถวนั้น */
const printingNo = ref<string | null>(null);

// 🏁 ตัวกรองเปลี่ยนเร็ว ๆ ได้ ⇒ คำตอบเก่าห้ามทับคำตอบใหม่
const guard = createLatestGuard();

const scopeLabel = (scope: string | null): string => {
  if (scope === 'room') return 'ทั้งห้อง';
  if (scope === 'selected') return 'รายคน';
  return '—';
};

const displayDate = (item: AckListItem) => formatThaiDateTimeParts(item.event_at ?? item.issued_at);

const load = async () => {
  if (isRangeReversed(period.value)) return;
  if (period.value.mode === 'asof') return;
  const range = toRange(period.value);

  const token = guard.begin();
  isLoading.value = true;
  hasError.value = false;
  try {
    const res = await FinanceService.getAcknowledgements(currentRoomId, {
      from: range.startDate,
      to: range.endDate,
      // 🔎 หน้านี้เป็นมุมมองตรวจสอบ — ใบที่ยกเลิกแล้วต้องเห็น (พร้อมป้าย) ไม่ใช่หายไป
      includeVoided: true,
    });
    if (!guard.isCurrent(token)) return;
    items.value = res.items;
  } catch {
    if (!guard.isCurrent(token)) return;
    items.value = [];
    hasError.value = true;
  } finally {
    if (guard.isCurrent(token)) isLoading.value = false;
  }
};

watch(period, () => {
  void load();
});

onMounted(() => {
  void load();
});

const openDetail = (item: AckListItem) => {
  void router.push({
    name: 'finance-acknowledgement-detail',
    params: { receiptNo: item.receipt_no },
  });
};

const printPdf = async (item: AckListItem) => {
  if (printingNo.value) return;
  printingNo.value = item.receipt_no;
  try {
    const blob = await FinanceService.downloadAckPdf(currentRoomId, item.receipt_no);
    downloadBlob(blob, `${item.receipt_no}.pdf`);
  } catch (error: unknown) {
    void dialog.alert(
      'สร้างไฟล์ PDF ไม่สำเร็จ',
      error instanceof Error ? error.message : 'กรุณาลองใหม่อีกครั้ง',
      'error',
    );
  } finally {
    printingNo.value = null;
  }
};

const afterIssued = (receiptNo: string) => {
  void load();
  void router.push({
    name: 'finance-acknowledgement-detail',
    params: { receiptNo },
  });
};
</script>

<template>
  <div class="space-y-4 sm:space-y-5">
    <PageIntro
      description="แจ้งยอดค้างให้ผู้ปกครองรับทราบ — 1 ใบต่อรอบ (ทั้งห้องหรือรายคน) และไม่มีผลต่อยอดเงิน"
    >
      <template #actions>
        <button type="button" class="btn-ghost-ui" :disabled="isLoading" @click="load">
          <i class="bi bi-arrow-clockwise" aria-hidden="true"></i>
          รีเฟรช
        </button>
        <button
          v-if="canManageFinance"
          type="button"
          class="btn-primary"
          @click="isIssuing = true"
        >
          <i class="bi bi-plus-lg" aria-hidden="true"></i>
          ออกใบรับทราบยอดค้าง
        </button>
      </template>
    </PageIntro>

    <PeriodPicker v-model="period" :modes="['month', 'range']" label="ช่วงที่ออกเอกสาร" />

    <SkeletonRows v-if="isLoading" :rows="5" height="h-14" />
    <StateBlock
      v-else-if="hasError"
      variant="error"
      hint="โหลดรายการใบรับทราบไม่สำเร็จ"
      @retry="load"
    />
    <StateBlock
      v-else-if="!items.length"
      variant="empty"
      title="ยังไม่มีใบรับทราบยอดค้างในช่วงนี้"
      hint="ออกใบแรกเพื่อแจ้งยอดค้างให้ผู้ปกครอง — ระบบดึงรายชื่อผู้ค้างให้เอง"
      icon="bi-receipt"
    >
      <button v-if="canManageFinance" type="button" class="btn-primary mt-2" @click="isIssuing = true">
        ออกใบรับทราบยอดค้าง
      </button>
    </StateBlock>

    <template v-else>
      <p class="px-1 text-sm text-ink-3">
        พบ <span class="num font-bold text-ink-2">{{ items.length }}</span> ใบ
      </p>

      <div class="page-card overflow-hidden">
        <div class="overflow-x-auto">
          <table class="data-table">
            <thead>
              <tr>
                <th>เลขที่</th>
                <th>วันที่</th>
                <th>ขอบเขต</th>
                <th class="text-right">จำนวนนักเรียน</th>
                <th class="text-right">ยอดค้างรวม</th>
                <th>สถานะ</th>
                <th class="text-right">พิมพ์</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="item in items"
                :key="item.receipt_no"
                class="cursor-pointer"
                @click="openDetail(item)"
              >
                <td class="whitespace-nowrap">
                  <span class="num font-bold text-ink-1">{{ item.receipt_no }}</span>
                </td>
                <td class="whitespace-nowrap">
                  <span class="block">{{ displayDate(item).date }}</span>
                  <span class="block text-caption text-ink-3">{{ displayDate(item).time }} น.</span>
                </td>
                <td class="whitespace-nowrap text-ink-2">{{ scopeLabel(item.scope) }}</td>
                <td class="num text-right text-ink-2">{{ item.entry_count }}</td>
                <td class="num whitespace-nowrap text-right font-bold text-ink">
                  {{ formatMoney(item.amount) }}
                </td>
                <td>
                  <span
                    class="chip"
                    :class="
                      item.status === 'voided'
                        ? 'bg-danger-50 text-danger-700'
                        : 'bg-ok-50 text-ok-700'
                    "
                  >
                    {{ item.status === 'voided' ? 'ยกเลิกแล้ว' : 'ใช้งาน' }}
                  </span>
                </td>
                <td class="text-right">
                  <!-- 🖨️ ใบที่ยกเลิกแล้วก็พิมพ์ได้ (หลักฐานว่าเคยแจ้ง) -->
                  <button
                    type="button"
                    class="btn-ghost-ui min-h-9 text-sm"
                    :disabled="printingNo !== null"
                    :aria-label="`พิมพ์ใบรับทราบ ${item.receipt_no}`"
                    @click.stop="printPdf(item)"
                  >
                    <span
                      v-if="printingNo === item.receipt_no"
                      class="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-r-transparent"
                      aria-hidden="true"
                    ></span>
                    <i v-else class="bi bi-printer" aria-hidden="true"></i>
                    พิมพ์
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>

    <AckIssueModal
      :open="isIssuing"
      @close="isIssuing = false"
      @issued="afterIssued"
    />
  </div>
</template>
