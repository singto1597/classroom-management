<script setup lang="ts">
/**
 * ReceiptDetail — รายละเอียดเอกสาร 1 ใบ + ปุ่มดาวน์โหลด PDF — F3
 *
 * 🔓 อ่านเปิดให้สมาชิกทุกคน (ตรงกับ `require_member` ฝั่ง backend)
 *
 * 📌 เลือกแสดงข้อมูล **ชุดเดียวกับที่เทมเพลต PDF ใช้** (`backend/templates/finance/receipt.html`)
 *    โดยตั้งใจ — จอต้องไม่บอกอย่าง เอกสารบอกอีกอย่าง ไม่งั้นครูจะเถียงกับผู้ปกครองไม่ได้
 *    ถ้าแก้เลย์เอาต์ที่นี่ ต้องไปดูเทมเพลตนั้นด้วย
 *
 * ⚠️ `receipt_no` เป็น **string** (`REC-2569-0042`) ไม่ใช่ id — และ backend บังคับ pattern
 *    ด้วย `Path(..., pattern=...)` ⇒ เลขที่มั่วจะได้ 422 ไม่ใช่ 404
 *
 * ⚠️ ห้ามใช้ `formatThaiDate` กับ `issued_at` — ดูเหตุผลใน `formatThaiDateTime` (utils/period.ts)
 */
import { computed, onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import Swal from 'sweetalert2';

import PageHeader from '@/components/ui/PageHeader.vue';
import StateBlock from '@/components/ui/StateBlock.vue';
import SkeletonRows from '@/components/ui/SkeletonRows.vue';

import { FinanceService } from '@/services/finance';
import { useAuthStore } from '@/stores/auth';
import { downloadBlob } from '@/utils/download';
import { formatThaiDate, formatThaiDateTime } from '@/utils/period';
import { voucherChannel as voucherChannelOf } from '@/utils/voucherChannel';
import type { ReceiptDetail } from '@/types/finance';

const route = useRoute();
const authStore = useAuthStore();
const currentRoomId = authStore.currentRoomId!;

const receiptNo = String(route.params.receiptNo ?? '');

const detail = ref<ReceiptDetail | null>(null);
const isLoading = ref(true);
const errorMessage = ref('');

/**
 * 🧾 เอกสารนี้พูดด้วยถ้อยคำของ "ใบเสร็จ" (เงินเข้ามือแล้ว) หรือ "ใบแจ้งหนี้" (ยังไม่ได้รับเงิน)?
 *
 * 🔴 **อ่านจาก backend เท่านั้น — ห้ามคำนวณเองจาก `doc_type` อีก**
 *    ของเดิมหน้านี้เขียนว่า `['receipt','deposit'].includes(doc_type)` ซึ่งเป็นสำเนาที่สอง
 *    ของคำตอบเดียวกับที่เทมเพลต PDF คิด (คอมเมนต์เดิมข้างบนเตือนกับดักนี้ไว้เองแล้ว)
 *    ⇒ เพิ่มชนิดที่ 4 แล้วลืมแก้ฝั่งใดฝั่งหนึ่ง = เอกสารอ่านผิดทั้งใบโดยไม่มี error ให้เห็น
 *    ตอนนี้ backend ส่ง `is_receipt` มาจาก `RECEIPT_LIKE_DOC_TYPES` ตัวเดียวกับที่
 *    `_document_context` ใช้พิมพ์กระดาษ ⇒ จอกับกระดาษตอบไม่ตรงกันไม่ได้อีก
 */
const isReceipt = computed(() => detail.value?.is_receipt ?? false);

/**
 * 💸 ใบสำคัญจ่าย — **ไม่ใช่ใบเสร็จ และไม่ใช่ใบแจ้งหนี้** ⇒ ต้องมีสาขาของตัวเอง
 *
 * 🔴 ถ้าปล่อยให้ตกไปสาขาใบแจ้งหนี้ จะพิมพ์ "เรียกเก็บจาก"/"ยอดค้างชำระ" บนเอกสาร
 *    ที่ **จ่ายเงินออก** ซึ่งกลับความหมายทั้งใบ (กับดักเดียวกับที่ `receipt.html` เลี่ยง
 *    ด้วยการแยกไฟล์ partial — ที่นี่เลี่ยงด้วยสาขาที่สาม)
 */
const isVoucher = computed(() => detail.value?.doc_type === 'payment_voucher');

/** 💰 ใบรับเงินล่วงหน้าโดยเฉพาะ — ถ้อยคำต่างจากใบเสร็จ/ใบแจ้งหนี้ทั้งใบ */
const isDeposit = computed(() => detail.value?.doc_type === 'deposit');

/**
 * 🏦 ช่องทางจ่ายเงินของใบสำคัญจ่าย — มาจาก **กระเป๋าที่รายการนั้นจ่ายออก** (snapshot)
 * `null` = เอกสารชนิดอื่น หรือข้อมูลช่องทางหาย ⇒ ซ่อนแถวไป ดีกว่าแสดงช่องว่าง
 */
const voucherChannel = computed<string | null>(() => voucherChannelOf(detail.value));

/**
 * 🏷️ ป้ายของ `paid_total_after`
 * ⚠️ ของเดิมเป็น 2 ทาง (`isReceipt ? 'ยอดสะสมที่ชำระแล้ว' : 'ชำระแล้ว'`) ⇒ ใบรับเงินล่วงหน้า
 *    จะได้คำว่า "ยอดสะสมที่ชำระแล้ว" ซึ่ง **ผิดบริบท**: เงินก้อนนี้ไม่ได้ "ชำระ" บิลใบไหน
 *    มันคือเครดิตที่ห้องรับมาถือไว้ ⇒ ต้องมีสาขาที่สาม
 */
const paidTotalLabel = computed(() => {
  if (isDeposit.value) return 'ยอดที่รับไว้เป็นเครดิต';
  return isReceipt.value ? 'ยอดสะสมที่ชำระแล้ว' : 'ชำระแล้ว';
});

/** คงเหลือ ณ วันที่ออกเอกสาร — ต้องมีทั้งสองยอดถึงจะคำนวณได้ (มิฉะนั้นซ่อนแถวไปเลย) */
const remaining = computed<number | null>(() => {
  const d = detail.value;
  if (!d || d.collection_amount === null) return null;
  return d.collection_amount - d.paid_total_after;
});

const formatMoney = (value: number): string =>
  `${value < 0 ? '−' : ''}฿${Math.abs(value).toLocaleString('th-TH', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;

const load = async () => {
  isLoading.value = true;
  errorMessage.value = '';
  try {
    detail.value = await FinanceService.getReceipt(currentRoomId, receiptNo);
  } catch (error: unknown) {
    // 404 (ไม่พบ/ต่างห้อง) กับ 422 (เลขที่รูปไม่ตรง) ต่างกันที่ข้อความ — ส่งต่อทั้งดุ้น
    errorMessage.value = error instanceof Error ? error.message : 'โหลดเอกสารไม่สำเร็จ';
  } finally {
    isLoading.value = false;
  }
};

const isDownloading = ref(false);

const downloadPdf = async () => {
  if (isDownloading.value || !detail.value) return;
  isDownloading.value = true;
  try {
    const blob = await FinanceService.downloadReceiptPdf(currentRoomId, detail.value.receipt_no);
    downloadBlob(blob, `${detail.value.doc_type}-${detail.value.receipt_no}.pdf`);
  } catch (error: unknown) {
    // 502 = Gotenberg ล่ม/เรนเดอร์ไม่ผ่าน (ไม่ใช่ 500 ของโค้ดเรา) — service แปลงเป็นไทยให้แล้ว
    Swal.fire(
      'สร้างไฟล์ PDF ไม่สำเร็จ',
      error instanceof Error ? error.message : 'กรุณาลองใหม่อีกครั้ง',
      'error',
    );
  } finally {
    isDownloading.value = false;
  }
};

onMounted(() => {
  void load();
});
</script>

<template>
  <div class="space-y-4 sm:space-y-5">
    <PageHeader
      eyebrow="Finance Document"
      :title="detail?.receipt_no || 'รายละเอียดเอกสาร'"
      :description="detail?.doc_type_label || 'เอกสารการเงิน'"
    >
      <template #actions>
        <RouterLink to="/finance/receipts" class="btn-ghost-ui" title="กลับทะเบียนเอกสาร">
          <i class="bi bi-arrow-left" aria-hidden="true"></i>
          กลับทะเบียนเอกสาร
        </RouterLink>
      </template>
    </PageHeader>

    <SkeletonRows v-if="isLoading" :rows="4" height="h-20" />

    <StateBlock
      v-else-if="!detail"
      variant="error"
      icon="bi-file-earmark-x"
      title="ไม่พบเอกสารนี้"
      :hint="errorMessage"
      @retry="load"
    />

    <template v-else>
      <!-- 🧾 เนื้อเอกสาร — โครงเดียวกับเทมเพลต PDF เพื่อให้จอกับกระดาษตรงกัน -->
      <div class="page-card p-4 sm:p-6">
        <div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div class="min-w-0">
            <h2 class="font-display text-lg font-bold text-stone-900">
              {{ detail.doc_type_label || detail.doc_type }}
            </h2>
            <p class="text-sm text-stone-500">
              {{ detail.room_name || '—' }}
              <span v-if="detail.room_code" class="num">({{ detail.room_code }})</span>
            </p>
          </div>
          <div class="shrink-0 sm:text-right">
            <p class="num font-display text-base font-bold text-stone-900">
              เลขที่ {{ detail.receipt_no }}
            </p>
            <p class="num text-xs text-stone-500">
              วันที่ {{ formatThaiDateTime(detail.issued_at) }}
            </p>
          </div>
        </div>

        <hr class="my-4 border-t-2 border-stone-900" />

        <dl class="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2">
          <div>
            <dt class="text-xs font-bold uppercase tracking-wider text-stone-400">
              <!-- ⚠️ ใบแจ้งหนี้ "ยังไม่ได้รับเงิน" — ใช้ "ได้รับเงินจาก" ไม่ได้ (ความหมายผิด)
                   💸 ใบสำคัญจ่าย "จ่ายออก" — ใช้ได้แค่ "ผู้เบิก/ผู้รับเงิน" -->
              {{ isVoucher ? 'ผู้เบิก/ผู้รับเงิน' : isReceipt ? 'ได้รับเงินจาก' : 'เรียกเก็บจาก' }}
            </dt>
            <dd class="mt-0.5 font-bold text-stone-900">
              {{ detail.issued_to_name || '—' }}
              <span v-if="detail.student_no" class="num text-sm font-normal text-stone-500">
                — เลขที่ {{ detail.student_no }}
              </span>
            </dd>
          </div>

          <div>
            <dt class="text-xs font-bold uppercase tracking-wider text-stone-400">
              <!-- 💸 ใบสำคัญจ่ายไม่มีแคมเปญ — สิ่งที่ต้องรู้คือ "หมวดหมู่" ที่ตัดงบ -->
              {{ isVoucher ? 'หมวดหมู่งบประมาณ' : 'รายการ' }}
            </dt>
            <dd class="mt-0.5 text-stone-700">
              <template v-if="isVoucher">{{ detail.category_name || '—' }}</template>
              <template v-else>
                <RouterLink
                  v-if="detail.collection_id"
                  :to="`/finance/collections/${detail.collection_id}`"
                  class="font-bold text-brand-700 hover:underline"
                >
                  {{ detail.collection_title || `โปรเจกต์ #${detail.collection_id}` }}
                </RouterLink>
                <span v-else>{{ detail.collection_title || '—' }}</span>
              </template>
            </dd>
          </div>

          <div v-if="detail.collection_due_date">
            <dt class="text-xs font-bold uppercase tracking-wider text-stone-400">กำหนดชำระ</dt>
            <dd class="num mt-0.5 text-stone-700">
              {{ formatThaiDate(detail.collection_due_date) }}
            </dd>
          </div>

          <div>
            <dt class="text-xs font-bold uppercase tracking-wider text-stone-400">ผู้ออกเอกสาร</dt>
            <dd class="mt-0.5 text-stone-700">{{ detail.issued_by_name || '—' }}</dd>
          </div>
        </dl>

        <!-- 📋 ตารางโครงการ — ใบแจ้งหนี้รวมยอดต้องบอกได้ว่ายอดพาดหัวมาจากโครงการใดบ้าง
             🔴 ตัวเลขทุกบรรทัดมาจาก **snapshot ณ วันออกเอกสาร** (คอลัมน์ `line_items`)
                ไม่ใช่ยอดค้างปัจจุบัน ⇒ เปิดใบเดิมอีกกี่เดือนก็เห็นชุดเดิม และผลรวมของ
                บรรทัดเหล่านี้เท่ากับ `detail.amount` เสมอ (ทั้งคู่มาจาก snapshot ก้อนเดียวกัน)
             ℹ️ กระดาษตัดที่ 12 บรรทัด (รักษาสัญญา "หน้าละคน") แล้วปิดท้ายด้วย "และอีก N โครงการ"
                ส่วนจอนี้ **ไม่ตัด** เพราะเลื่อนดูได้ ⇒ จอนี้คือ "รายละเอียดทั้งหมด"
                ที่กระดาษอ้างถึง — ข้อมูลชุดเดียวกัน แค่กระดาษเห็นไม่ครบทุกบรรทัด -->
        <section v-if="detail.line_items?.length" class="mt-4">
          <h3 class="text-xs font-bold uppercase tracking-wider text-stone-400">
            รายการที่ค้างชำระ ({{ detail.line_items.length }} โครงการ)
          </h3>

          <!-- 📱 มือถือ -->
          <ul class="mt-2 space-y-2 lg:hidden">
            <li
              v-for="(item, index) in detail.line_items"
              :key="`${index}-${item.title}`"
              class="flex items-start justify-between gap-3 rounded-xl border border-stone-200 px-3 py-2"
            >
              <div class="min-w-0">
                <p class="text-sm font-bold text-stone-900">
                  {{ item.title || 'รายการชำระเงิน' }}
                </p>
                <p v-if="item.due_date" class="num text-xs text-stone-500">
                  กำหนดชำระ {{ formatThaiDate(item.due_date) }}
                </p>
              </div>
              <span class="num shrink-0 text-sm text-stone-900">{{ formatMoney(item.amount) }}</span>
            </li>
          </ul>

          <!-- 🖥️ เดสก์ท็อป -->
          <div class="mt-2 hidden overflow-x-auto lg:block">
            <table class="data-table">
              <thead>
                <tr>
                  <th class="w-16">ลำดับ</th>
                  <th>รายละเอียด</th>
                  <th class="text-right">จำนวนเงิน</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(item, index) in detail.line_items" :key="`${index}-${item.title}`">
                  <td class="num">{{ index + 1 }}</td>
                  <td>
                    {{ item.title || 'รายการชำระเงิน' }}
                    <span v-if="item.due_date" class="num text-xs text-stone-500">
                      (กำหนดชำระ {{ formatThaiDate(item.due_date) }})
                    </span>
                  </td>
                  <td class="num text-right">{{ formatMoney(item.amount) }}</td>
                </tr>
              </tbody>
              <tfoot>
                <tr>
                  <td colspan="2" class="text-right font-bold">รวมทั้งสิ้น</td>
                  <td class="num text-right font-bold">{{ formatMoney(detail.amount) }}</td>
                </tr>
              </tfoot>
            </table>
          </div>

          <p
            class="num mt-2 flex items-center justify-between gap-3 rounded-xl bg-stone-50 px-3 py-2 text-sm font-bold text-stone-900 lg:hidden"
          >
            <span>รวมทั้งสิ้น</span>
            <span>{{ formatMoney(detail.amount) }}</span>
          </p>
        </section>

        <!-- 💰 กล่องยอดเงิน + คำอ่าน — หัวใจของเอกสาร ใช้ดีไซน์เดียวกับ .amount-box ใน PDF -->
        <div
          class="mt-4 flex flex-col gap-1.5 rounded-2xl border-2 border-stone-900 px-4 py-3 sm:flex-row sm:items-baseline sm:justify-between sm:gap-4"
        >
          <span class="font-display text-base font-bold text-stone-900">
            ({{ detail.amount_text || '—' }})
          </span>
          <span class="font-display num text-xl font-bold text-stone-900">
            {{ formatMoney(detail.amount) }}
          </span>
        </div>

        <!-- 💸 ข้อมูลเฉพาะใบสำคัญจ่าย — ทั้งชุดเป็น snapshot ณ วันออกเอกสาร
             🔴 "ไม่อยู่ในงบประมาณที่ตั้งไว้" ต้องพิมพ์ออกมา ไม่ใช่เว้นว่าง:
                ช่องว่างบนใบจ่ายอ่านได้ว่า "ไม่มีงบ" ซึ่งต่างจาก "ยังไม่ได้ตั้งงบ" -->
        <dl v-if="isVoucher" class="mt-4 grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2">
          <div v-if="voucherChannel">
            <dt class="text-xs font-bold uppercase tracking-wider text-stone-400">จ่ายเงินผ่าน</dt>
            <dd class="mt-0.5 text-stone-700">
              {{ voucherChannel }}
              <span v-if="detail.account_name" class="text-stone-500">({{ detail.account_name }})</span>
            </dd>
          </div>

          <div v-if="detail.approver_name">
            <dt class="text-xs font-bold uppercase tracking-wider text-stone-400">ผู้อนุมัติ</dt>
            <dd class="mt-0.5 text-stone-700">{{ detail.approver_name }}</dd>
          </div>

          <div>
            <dt class="text-xs font-bold uppercase tracking-wider text-stone-400">เอกสารแนบ</dt>
            <dd class="mt-0.5 text-stone-700">
              <template v-if="detail.attachment_count > 0">
                แนบมาด้วย <span class="num">{{ detail.attachment_count }}</span> ใบ
                (บิลเงินสด/ใบเสร็จจากร้านค้า)
              </template>
              <template v-else>ไม่ได้แนบเอกสารมา</template>
            </dd>
          </div>

          <div class="sm:col-span-2">
            <dt class="text-xs font-bold uppercase tracking-wider text-stone-400">
              หมวดหมู่งบประมาณ (F2)
            </dt>
            <dd class="mt-0.5 text-stone-700">
              <!-- ⚠️ `.length` ตรง ๆ **โดยเจตนา ไม่เติม `?.`** — คีย์นี้ backend รับประกัน
                   ว่ามีเสมอ (`VoucherFields` ใน models/finance_schemas.py + เทสต์ที่ยิง
                   เส้นทาง JSON ตรง ๆ) ⇒ ถ้าวันหนึ่งมันหายไปอีก ให้ **throw** แล้วรู้ตัว
                   ดีกว่าเติม `?.` แล้วเงียบ ๆ ตกลง `v-else` ที่พิมพ์ว่า "ไม่อยู่ในงบประมาณ
                   ที่ตั้งไว้" ซึ่งเป็นคำโกหก (ต่างจากจอขาวที่เห็นแล้วรู้ว่าพัง) -->
              <ul v-if="detail.budgets.length" class="space-y-1">
                <li v-for="budget in detail.budgets" :key="budget.id" class="num">
                  {{ detail.category_name || 'ไม่ระบุหมวด' }} — งบ
                  {{ formatThaiDate(budget.start_date) }}–{{ formatThaiDate(budget.end_date) }}
                  ({{ formatMoney(budget.amount) }})
                </li>
              </ul>
              <span v-else class="text-amber-700">
                ไม่อยู่ในงบประมาณที่ตั้งไว้ (หมวด: {{ detail.category_name || 'ไม่ระบุ' }})
              </span>
              <!-- ⚠️ งบซ้อนช่วงกันได้จริง (unique index คือ (room_id, category_id,
                   start_date, end_date) เท่านั้น) ⇒ ถ้าแสดงหลายก้อนโดยไม่เตือน
                   ผู้ใช้จะบวกเองแล้วได้ยอดที่ถูกนับซ้ำ -->
              <p v-if="detail.budgets.length > 1" class="mt-1 text-xs text-amber-700">
                <i class="bi bi-exclamation-triangle" aria-hidden="true"></i>
                รายการนี้อยู่ในงบมากกว่าหนึ่งช่วง — ยอดอาจถูกนับซ้ำในการสรุปรวม
              </p>
            </dd>
          </div>
        </dl>

        <!-- 💰 ยอดแบบ "ต่อบิล" — เป็นแนวคิดของใบเสร็จ/ใบแจ้งหนี้เท่านั้น
             🔴 ใบสำคัญจ่ายไม่มี "ยอดเต็มของรายการ" และไม่มี "ยอดค้างชำระ" เลย
                (`collection_amount` เป็น NULL) ⇒ แสดงไปก็มีแต่ทำให้อ่านผิด -->
        <dl v-else class="mt-4 grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2">
          <div v-if="detail.collection_amount !== null">
            <dt class="text-xs font-bold uppercase tracking-wider text-stone-400">
              ยอดเต็มของรายการ
            </dt>
            <dd class="num mt-0.5 text-stone-700">{{ formatMoney(detail.collection_amount) }}</dd>
          </div>

          <div>
            <dt class="text-xs font-bold uppercase tracking-wider text-stone-400">
              {{ paidTotalLabel }}
            </dt>
            <dd class="num mt-0.5 text-stone-700">{{ formatMoney(detail.paid_total_after) }}</dd>
          </div>

          <div v-if="remaining !== null">
            <dt class="text-xs font-bold uppercase tracking-wider text-stone-400">
              {{ isReceipt ? 'คงเหลือ' : 'ยอดค้างชำระ' }}
            </dt>
            <dd
              class="num mt-0.5 font-bold"
              :class="remaining > 0 ? 'text-red-600' : 'text-emerald-700'"
            >
              {{ formatMoney(remaining) }}
            </dd>
          </div>
        </dl>

        <p v-if="detail.note" class="mt-4 text-sm text-stone-500">หมายเหตุ: {{ detail.note }}</p>

        <p class="num mt-5 text-center text-[11px] text-stone-400">
          เอกสารฉบับนี้ออกโดยระบบบริหารจัดการห้องเรียน — เลขที่ {{ detail.receipt_no }}
        </p>
      </div>

      <!-- 🔁 คำอธิบายความไม่สมมาตร — ครูต้องรู้ว่ากดซ้ำได้หรือไม่ก่อนกด -->
      <div class="page-card flex items-start gap-3 p-4">
        <i
          class="bi bi-info-circle mt-0.5 shrink-0 text-lg text-brand-700"
          aria-hidden="true"
        ></i>
        <p class="text-sm leading-relaxed text-stone-600">
          <template v-if="isVoucher">
            ใบสำคัญจ่ายผูกกับ <b>รายจ่ายที่บันทึกไว้</b> หนึ่งรายการ — พิมพ์ซ้ำได้เลขเดิมเสมอ
            <br />💰 หมวดหมู่/ช่องทางจ่าย/งบประมาณบนใบนี้เป็น <b>snapshot ณ วันที่ออกเอกสาร</b>
            — แก้ชื่อหมวด แก้เลขบัญชี หรือแก้งบทีหลัง จะไม่ย้อนไปเปลี่ยนใบที่พิมพ์แจกแล้ว
            <br />⚠️ การ <b>ยกเลิกรายการจ่าย</b> จะยกเลิกใบนี้ตามไปด้วย (ใบจะถูกประทับว่า
            ยกเลิก ไม่ถูกลบ)
          </template>
          <template v-else-if="isDeposit">
            ใบรับเงินล่วงหน้าเป็นหลักฐานว่า <b>ได้รับเงินเข้ามาแล้ว</b> แต่เงินก้อนนี้ยัง
            <b>ไม่นับเป็นรายได้</b> ของห้อง — ระบบถือไว้เป็น <b>เครดิตคงเหลือ</b> ของนักเรียน
            และจะนับเป็นรายได้ก็ต่อเมื่อถูกหักไปปิดบิลเท่านั้น
            <br />⚠️ ใบนี้ <b>ไม่ผูกกับบิลใบใด</b> — จึงไม่มียอดค้างชำระ และไม่ออกใหม่
            ตราบใดที่รายการเดิมยังอยู่ (แก้ไขให้ถูกต้องได้โดยยกเลิกรายการนั้น)
          </template>
          <template v-else-if="isReceipt">
            ใบเสร็จผูกกับ <b>เหตุการณ์รับเงิน</b> หนึ่งครั้ง — ออกซ้ำจะได้เลขเดิมเสมอ
            (พิมพ์กี่ครั้งก็ปลอดภัย ไม่กินเลขใหม่)
          </template>
          <template v-else>
            ใบแจ้งหนี้เป็นเอกสาร <b>ณ จุดเวลา</b> — ยอดค้างเปลี่ยนเมื่อนักเรียนจ่ายเพิ่ม
            การออกใหม่จึงได้เลขใหม่ทุกครั้ง และฉบับนี้จะยังคงยอดเดิมไว้เป็นหลักฐาน
          </template>
        </p>
      </div>

      <div class="flex flex-col gap-2 sm:flex-row sm:justify-end">
        <button
          type="button"
          class="btn-primary w-full sm:w-auto"
          :disabled="isDownloading"
          @click="downloadPdf"
        >
          <i
            class="bi"
            :class="isDownloading ? 'bi-hourglass-split' : 'bi-file-earmark-pdf'"
            aria-hidden="true"
          ></i>
          {{ isDownloading ? 'กำลังสร้างไฟล์...' : 'ดาวน์โหลด PDF' }}
        </button>
      </div>
    </template>
  </div>
</template>
