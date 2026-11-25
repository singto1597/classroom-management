<script setup lang="ts">
/**
 * 🧾 [FIN-V2 / P5.5] AckIssueModal — ออกใบรับทราบยอดค้าง (ACK) 1 ใบต่อรอบ
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * กฎที่สำคัญที่สุดของแผ่นนี้
 * ═══════════════════════════════════════════════════════════════════════════
 * 1. 🔴 **ห้ามคำนวณยอดค้างยอดรวมใน FE** — สูตรมี `written_off_amount` (P6.2) และ
 *    predicate บิลเปิดที่ backend เป็นเจ้าของ ⇒ ตัวเลขบนจอกับบนกระดาษจะไม่ตรงกัน
 *    ตั้งแต่วันแรก · แผ่นนี้จึง **ไม่แสดงยอดเงินใด ๆ** ก่อนออกเอกสาร (แสดงได้แค่
 *    จำนวนคนที่เลือก) แล้วให้ยอดจริงมาจาก response ของ backend เท่านั้น
 * 2. 🔁 `idempotency_key` สร้าง **ครั้งเดียวตอนเปิดแผ่น** (ไม่ใช่ตอนกดปุ่ม) —
 *    ดับเบิลคลิก/เน็ตหลุดแล้วกดซ้ำ ต้องได้ใบเดิม (`reused=true`) ไม่ใช่ใบที่สอง
 *    ที่ยอดซ้ำกัน ⇒ `watch(open)` สร้างคีย์ใหม่เฉพาะตอนเปิดแผ่นใหม่
 * 3. 🚫 ACK ไม่แตะเงิน — ไม่มีการเลือกกระเป๋า/ช่องทาง/เครดิตในแผ่นนี้โดยเจตนา
 *
 * 📌 รายชื่อผู้มีสิทธิ์เลือกมาจาก `getAllDebtors` (ยอดค้างปัจจุบัน) — ใช้แค่ "รายชื่อ"
 *    เพื่อให้ติ๊กได้ ไม่ใช้ยอดของมันมาบวกเอง
 *
 * @example
 * <AckIssueModal :open="issuing" @close="issuing = false" @issued="afterIssued" />
 */
import { computed, ref, watch } from 'vue';

import AppButton from '@/components/ui/AppButton.vue';
import AppSheet from '@/components/ui/AppSheet.vue';
import SkeletonRows from '@/components/ui/SkeletonRows.vue';
import StateBlock from '@/components/ui/StateBlock.vue';

import { FinanceService } from '@/services/finance';
import { useAuthStore } from '@/stores/auth';
import { useDialog } from '@/composables/useDialog';
import { newIdempotencyKey } from '@/utils/money';
import type { AckIssueRequest, AckScope, Debtor } from '@/types/finance';

const props = defineProps<{ open: boolean }>();

const emit = defineEmits<{
  close: [];
  /** ใบใหม่ออกสำเร็จ (หรือ replay ใบเดิม) — ค่าเป็นเลขที่เอกสาร */
  issued: [receiptNo: string];
}>();

const authStore = useAuthStore();
const dialog = useDialog();
const roomId = authStore.currentRoomId!;

const SCOPE_OPTIONS: { value: AckScope; label: string; icon: string }[] = [
  { value: 'room', label: 'ทั้งห้อง', icon: 'bi-people' },
  { value: 'selected', label: 'เฉพาะคนที่เลือก', icon: 'bi-person-check' },
];

const scope = ref<AckScope>('room');
const selectedIds = ref<number[]>([]);
const includeInvoice = ref(true);
const note = ref('');
const idempotencyKey = ref('');

const debtors = ref<Debtor[]>([]);
const isLoadingDebtors = ref(false);
const hasDebtorError = ref(false);
const isSaving = ref(false);

const selectedCount = computed(() => selectedIds.value.length);
const allSelected = computed(
  () => debtors.value.length > 0 && selectedCount.value === debtors.value.length,
);

const canSubmit = computed(
  () =>
    !isSaving.value &&
    idempotencyKey.value !== '' &&
    (scope.value === 'room' || selectedCount.value > 0),
);

const loadDebtors = async () => {
  isLoadingDebtors.value = true;
  hasDebtorError.value = false;
  try {
    debtors.value = await FinanceService.getAllDebtors(roomId);
  } catch {
    debtors.value = [];
    hasDebtorError.value = true;
  } finally {
    isLoadingDebtors.value = false;
  }
};

watch(
  () => props.open,
  (open) => {
    if (!open) return;
    // 🔁 คีย์ใหม่ต่อการเปิดแผ่นหนึ่งครั้ง — ห้ามย้ายไปอยู่ใน `submit()`
    try {
      idempotencyKey.value = newIdempotencyKey();
    } catch {
      idempotencyKey.value = '';
    }
    scope.value = 'room';
    selectedIds.value = [];
    includeInvoice.value = true;
    note.value = '';
    void loadDebtors();
  },
);

const toggleStudent = (studentId: number) => {
  const index = selectedIds.value.indexOf(studentId);
  if (index === -1) selectedIds.value.push(studentId);
  else selectedIds.value.splice(index, 1);
};

const toggleAll = () => {
  selectedIds.value = allSelected.value ? [] : debtors.value.map((d) => d.student_id);
};

const submit = async () => {
  if (!canSubmit.value) return;
  if (!idempotencyKey.value) {
    void dialog.alert(
      'ออกเอกสารไม่ได้',
      'เบราว์เซอร์นี้สร้างรหัสกันบันทึกซ้ำไม่ได้ — กรุณาอัปเดตเบราว์เซอร์แล้วลองใหม่',
      'error',
    );
    return;
  }

  const payload: AckIssueRequest = {
    scope: scope.value,
    include_invoice: includeInvoice.value,
    idempotency_key: idempotencyKey.value,
  };
  if (scope.value === 'selected') {
    payload.student_ids = [...selectedIds.value];
  }
  const trimmedNote = note.value.trim();
  if (trimmedNote) payload.note = trimmedNote;

  isSaving.value = true;
  try {
    const res = await FinanceService.issueAcknowledgement(roomId, payload);
    dialog.notify(
      res.reused
        ? `ใบรับทราบ ${res.receipt.receipt_no} ถูกออกไปแล้ว — เปิดใบเดิม`
        : `ออกใบรับทราบ ${res.receipt.receipt_no} แล้ว`,
    );
    emit('issued', res.receipt.receipt_no);
    emit('close');
  } catch (error: unknown) {
    // 400 (ไม่มีใครค้าง/รายชื่อว่าง) และ 409 (คีย์ซ้ำแต่ payload ต่าง) → ข้อความจาก backend
    void dialog.alert(
      'ออกใบรับทราบไม่สำเร็จ',
      error instanceof Error ? error.message : 'กรุณาลองใหม่อีกครั้ง',
      'error',
    );
  } finally {
    isSaving.value = false;
  }
};
</script>

<template>
  <AppSheet
    :open="open"
    label="ออกใบรับทราบยอดค้าง"
    title="ออกใบรับทราบยอดค้าง"
    description="เอกสารแจ้งยอดค้างให้ผู้ปกครองรับทราบ — ไม่มีการรับเงินและไม่กระทบยอดบัญชี"
    size="form"
    :dismissible="!isSaving"
    @close="emit('close')"
  >
    <div class="space-y-5">
      <!-- 1) ขอบเขต -->
      <fieldset>
        <legend class="field-label mb-1.5">ขอบเขตการแจ้ง</legend>
        <div class="flex gap-1.5" role="group" aria-label="ขอบเขตการแจ้ง">
          <button
            v-for="option in SCOPE_OPTIONS"
            :key="option.value"
            type="button"
            :aria-pressed="scope === option.value"
            class="flex min-h-11 flex-1 items-center justify-center gap-1.5 rounded-control px-2 py-2 text-sm font-bold transition-colors active:scale-[0.97]"
            :class="
              scope === option.value
                ? 'bg-brand-700 text-white'
                : 'text-ink-3 hover:bg-canvas hover:text-ink'
            "
            @click="scope = option.value"
          >
            <i :class="['bi', option.icon]" aria-hidden="true"></i>
            {{ option.label }}
          </button>
        </div>
      </fieldset>

      <!-- 2) รายชื่อ (เฉพาะ 'selected') -->
      <div v-if="scope === 'selected'" class="space-y-2">
        <div class="flex items-center justify-between gap-2">
          <p class="text-sm text-ink-2">
            เลือกแล้ว
            <span class="num font-bold text-ink-1">{{ selectedCount }}</span>
            คน
          </p>
          <button
            v-if="debtors.length"
            type="button"
            class="btn-ghost-ui min-h-9 text-sm"
            @click="toggleAll"
          >
            {{ allSelected ? 'ล้างที่เลือก' : 'เลือกทั้งหมด' }}
          </button>
        </div>

        <SkeletonRows v-if="isLoadingDebtors" :rows="4" height="h-11" />
        <StateBlock
          v-else-if="hasDebtorError"
          variant="error"
          hint="โหลดรายชื่อผู้ค้างชำระไม่สำเร็จ"
          @retry="loadDebtors"
        />
        <StateBlock
          v-else-if="!debtors.length"
          variant="empty"
          title="ไม่มีผู้ค้างชำระในขณะนี้"
          hint="เมื่อทุกคนชำระครบแล้ว ระบบจะไม่ออกใบรับทราบยอดค้างให้"
          icon="bi-check2-circle"
        />
        <ul v-else class="max-h-64 space-y-1 overflow-y-auto rounded-control border border-line p-1">
          <li v-for="debtor in debtors" :key="debtor.student_id">
            <label
              class="flex min-h-11 cursor-pointer items-center gap-2.5 rounded-control px-2 py-1.5 hover:bg-canvas"
            >
              <input
                type="checkbox"
                class="h-4 w-4 shrink-0 accent-brand-700"
                :checked="selectedIds.includes(debtor.student_id)"
                @change="toggleStudent(debtor.student_id)"
              />
              <span class="min-w-0 flex-1 truncate text-sm text-ink-1">
                {{ debtor.student_name }}
              </span>
              <span class="num shrink-0 text-xs text-ink-3">
                {{ debtor.student_no ? `เลขที่ ${debtor.student_no}` : '' }}
              </span>
            </label>
          </li>
        </ul>
      </div>

      <!-- 3) ตัวเลือกเอกสาร -->
      <label class="flex cursor-pointer items-start gap-2.5 rounded-control bg-canvas px-3 py-2.5">
        <input
          v-model="includeInvoice"
          type="checkbox"
          class="mt-0.5 h-4 w-4 shrink-0 accent-brand-700"
          :disabled="isSaving"
        />
        <span class="min-w-0">
          <span class="block text-sm font-bold text-ink-1">ออกใบแจ้งหนี้ให้แต่ละคนด้วย</span>
          <span class="block text-caption text-ink-3">
            ระบบจะออกใบแจ้งหนี้ให้ผู้ที่มียอดค้างก่อน แล้วผูกเลขใบแจ้งหนี้ไว้บนใบรับทราบ
          </span>
        </span>
      </label>

      <!-- 4) หมายเหตุ -->
      <div>
        <label class="field-label" for="ack-note">หมายเหตุ (ไม่บังคับ)</label>
        <textarea
          id="ack-note"
          v-model="note"
          class="field min-h-20"
          maxlength="255"
          :disabled="isSaving"
          placeholder="เช่น กำหนดชำระภายในวันที่ 30 พ.ย."
        ></textarea>
      </div>

      <!-- 5) คำเตือนพรีวิว — ไม่เดายอดเงินเอง -->
      <div class="flex gap-2 rounded-control border border-line bg-canvas px-3 py-2.5">
        <i class="bi bi-info-circle mt-0.5 text-ink-3" aria-hidden="true"></i>
        <p class="text-caption leading-relaxed text-ink-2">
          ยอดค้างรวมจะยืนยันตอนออกเอกสาร — ระบบไม่แสดงตัวเลขประมาณการบนจอ
          เพื่อให้ตัวเลขบนจอตรงกับบนกระดาษเสมอ
          <template v-if="scope === 'room'">
            รายชื่อจะมาจากระบบ ณ เวลาที่ออกเอกสาร
          </template>
        </p>
      </div>
    </div>

    <template #footer>
      <div class="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <AppButton
          variant="secondary"
          block
          class="sm:w-auto"
          :disabled="isSaving"
          @click="emit('close')"
        >
          ยกเลิก
        </AppButton>
        <AppButton
          variant="primary"
          block
          class="sm:w-auto"
          :loading="isSaving"
          :disabled="!canSubmit"
          @click="submit"
        >
          ออกใบรับทราบ
        </AppButton>
      </div>
    </template>
  </AppSheet>
</template>
