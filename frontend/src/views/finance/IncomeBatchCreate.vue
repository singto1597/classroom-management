<script setup lang="ts">
/**
 * IncomeBatchCreate — สร้างใบรับเงินหลายบรรทัด (FIN-V2 / P4.5)
 * `/finance/income-batches/new`
 *
 * 🔑 กติกาสำคัญ (brief P4.5):
 *   1. `idempotency_key` สร้าง **ตอน mount** ครั้งเดียว — retry หลังเน็ตสะดุดใช้คีย์เดิม
 *      ไม่งั้นเงินเข้าซ้ำ; คีย์ใหม่เกิดเฉพาะเมื่อกด "เริ่มใบใหม่" (หลัง 409)
 *   2. **กระเป๋าเดียวทั้งใบ** (`wallet_account_id`) — บรรทัดไม่มีช่องกระเป๋าต่อบรรทัด
 *      ตาม schema ของ P4.4 (ห้ามเพิ่ม "เผื่ออนาคต" — backend จะไม่รับ)
 *   3. ผู้จ่ายเป็นข้อความอิสระ (`payer_name`) — ไม่มี picker/autocomplete
 *   4. ผู้รับ: เลือก person (role `receive`) มาก่อนเสมอ; ไม่เลือกจึงใช้ข้อความอิสระ
 *   5. ช่องทางที่ผูกกระเป๋าอื่น ⇒ backend 400 ⇒ เตือน + บล็อกก่อน submit
 *
 * ⚠️ `income_date` ส่งเป็น `YYYY-MM-DD` (วันไทย) ไม่ใช่ ISO datetime
 * ⚠️ เงินในช่องกรอกเป็น `number` — ห้ามใช้ `formatMoney` กับ input
 */
import { computed, onMounted, ref, watch } from 'vue';
import { useRouter } from 'vue-router';

import PageIntro from '@/components/ui/PageIntro.vue';
import StateBlock from '@/components/ui/StateBlock.vue';
import SkeletonRows from '@/components/ui/SkeletonRows.vue';
import PersonPicker from '@/components/finance/PersonPicker.vue';
import IncomeLineEditor from '@/components/finance/IncomeLineEditor.vue';

import { FinanceService } from '@/services/finance';
import { apiStatus } from '@/services/api';
import { useAuthStore } from '@/stores/auth';
import { useDialog } from '@/composables/useDialog';
import { formatMoney, newIdempotencyKey, roundMoney } from '@/utils/money';
import { todayIso } from '@/utils/datetime';
import type {
  Account,
  Category,
  FinancePerson,
  IncomeBatchCreate,
  IncomeBatchLinePayload,
  PaymentChannel,
} from '@/types/finance';

const authStore = useAuthStore();
const router = useRouter();
const dialog = useDialog();

const currentRoomId = authStore.currentRoomId!;
const currentUserName = authStore.currentUserName ?? '';
const canManageFinance = computed(() => authStore.canManageFinance);

const accounts = ref<Account[]>([]);
const categories = ref<Category[]>([]);
const channels = ref<PaymentChannel[]>([]);
const isLoading = ref(true);
const hasError = ref(false);

// ── หัวใบ ────────────────────────────────────────────────────────────
const payerName = ref('');
const receiverPersonId = ref<number | null>(null);
const receiverName = ref('');
const walletAccountId = ref(0);
const channelId = ref<number | null>(null);
const incomeDate = ref(todayIso());
const note = ref('');

/**
 * 🔑 คีย์เดียวต่อ "การกรอกหนึ่งครั้ง" — สร้างตอน mount (ไม่ใช่ตอน submit)
 *    retry ทุกครั้งจนกว่าจะสำเร็จ/กดเริ่มใบใหม่ใช้ค่านี้เสมอ
 */
const idempotencyKey = ref(newIdempotencyKey());

const isSubmitting = ref(false);
/** 409 = คีย์เดิม + payload ต่าง ⇒ ต้องเริ่มใบใหม่ด้วยคีย์ใหม่ */
const needsNewDraft = ref(false);

const makeLine = (): IncomeBatchLinePayload => ({
  description: '',
  amount: 0,
  category_id: 0,
});

const lines = ref<IncomeBatchLinePayload[]>([makeLine()]);

const activeChannels = computed(() => channels.value.filter((c) => c.is_active));

const fetchInitData = async () => {
  isLoading.value = true;
  hasError.value = false;
  try {
    const [accRes, catRes, channelRes] = await Promise.all([
      FinanceService.getAccounts(currentRoomId),
      FinanceService.getCategories(currentRoomId, 'income'),
      FinanceService.getPaymentChannels(currentRoomId),
    ]);
    accounts.value = accRes;
    categories.value = catRes.filter((c) => c.category_type === 'income');
    channels.value = channelRes;
  } catch {
    hasError.value = true;
  } finally {
    isLoading.value = false;
  }
};

// ────────────────────────────────────────────────────────────────
// 🧾 บรรทัด
// ────────────────────────────────────────────────────────────────
const updateLine = (index: number, payload: IncomeBatchLinePayload) => {
  lines.value.splice(index, 1, payload);
};

const addLine = () => {
  lines.value.push(makeLine());
};

const removeLine = (index: number) => {
  if (lines.value.length <= 1) return;
  lines.value.splice(index, 1);
};

const totalAmount = computed(() =>
  roundMoney(
    lines.value.reduce((sum, line) => sum + (Number.isFinite(line.amount) ? line.amount : 0), 0),
  ),
);

// ────────────────────────────────────────────────────────────────
// 👤 ผู้รับ / 💳 ช่องทาง
// ────────────────────────────────────────────────────────────────
const onReceiverPersonChange = (person: FinancePerson | null) => {
  // เลือกจากทะเบียน = ชื่อบนเอกสารมาจากทะเบียนเสมอ ⇒ ล้างข้อความที่พิมพ์ค้างไว้
  if (person) receiverName.value = person.display_name;
};

const onClearReceiverPerson = () => {
  receiverPersonId.value = null;
};

const selectedChannel = computed(
  () => activeChannels.value.find((c) => c.id === channelId.value) ?? null,
);

/**
 * 🚫 ช่องทางที่ผูกรกระเป๋า ≠ กระเป๋าที่เลือก ⇒ backend ตอบ 400
 *    ⇒ เตือนบนจอและบล็อกก่อนยิง API (ไม่เงียบ ๆ ส่งไปให้พัง)
 */
const channelWalletMismatch = computed(() => {
  const channel = selectedChannel.value;
  if (!channel || channel.wallet_account_id === null) return false;
  return channel.wallet_account_id !== walletAccountId.value;
});

const channelLabel = (channel: PaymentChannel): string => {
  const parts = [channel.label];
  if (channel.bank_name) parts.push(channel.bank_name);
  if (channel.account_number_masked) parts.push(channel.account_number_masked);
  return parts.filter(Boolean).join(' · ');
};

const clearChannel = () => {
  channelId.value = null;
};

// เปลี่ยนกระเป๋าเป็นอันที่ช่องทางไม่ตรง → ล้างช่องทางทิ้ง (ผู้ใช้ต้องเลือกใหม่ให้ตรง)
watch(walletAccountId, () => {
  if (channelWalletMismatch.value) channelId.value = null;
});

// ────────────────────────────────────────────────────────────────
// ✅ ตรวจฝั่งจอ (backend บังคับซ้ำ)
// ────────────────────────────────────────────────────────────────
const validate = (): string | null => {
  if (!payerName.value.trim()) {
    return 'กรุณาระบุชื่อผู้จ่าย เพราะชื่อนี้พิมพ์ลงบนใบรับเงิน';
  }
  if (!receiverPersonId.value && !receiverName.value.trim()) {
    return 'กรุณาระบุผู้รับเงิน (เลือกจากทะเบียนหรือพิมพ์ชื่อ)';
  }
  if (!walletAccountId.value) {
    return 'กรุณาเลือกกระเป๋าที่เงินจะเข้า — ใบรับเงินใช้กระเป๋าเดียวทั้งใบ';
  }
  if (!incomeDate.value) return 'กรุณาระบุวันที่รับเงิน';
  if (channelWalletMismatch.value) {
    return 'ช่องทางที่เลือกผูกกับกระเป๋าอื่น — เลือกช่องทางที่ตรงกับกระเป๋าหรือล้างช่องทาง';
  }
  if (lines.value.length === 0) return 'ต้องมีอย่างน้อย 1 บรรทัด';

  for (const [i, line] of lines.value.entries()) {
    const at = `บรรทัดที่ ${i + 1}`;
    if (!line.description.trim()) return `${at}: กรุณาระบุรายละเอียด`;
    if (!(line.amount > 0)) return `${at}: จำนวนเงินต้องมากกว่า 0`;
    if (!line.category_id) return `${at}: กรุณาเลือกหมวดรายรับ`;
  }
  if (!(totalAmount.value > 0)) return 'ยอดรวมต้องมากกว่า 0';
  return null;
};

const buildPayload = (): IncomeBatchCreate => ({
  idempotency_key: idempotencyKey.value,
  payer_name: payerName.value.trim(),
  receiver_person_id: receiverPersonId.value,
  // person ชนะเสมอฝั่ง server — ส่งข้อความเฉพาะเมื่อไม่มี person
  receiver_name: receiverPersonId.value ? null : receiverName.value.trim(),
  wallet_account_id: walletAccountId.value,
  channel_id: channelId.value,
  income_date: incomeDate.value,
  note: note.value.trim() || null,
  total_amount: totalAmount.value,
  lines: lines.value.map((line) => ({
    description: line.description.trim(),
    amount: line.amount,
    category_id: line.category_id,
  })),
});

/** 🆕 หลัง 409 — คีย์ใหม่ + ฟอร์มว่าง (ผู้ใช้ต้องกรอกใบใหม่ ไม่ใช่แก้ของเดิม) */
const startNewDraft = () => {
  idempotencyKey.value = newIdempotencyKey();
  needsNewDraft.value = false;
  payerName.value = '';
  receiverPersonId.value = null;
  receiverName.value = '';
  walletAccountId.value = 0;
  channelId.value = null;
  incomeDate.value = todayIso();
  note.value = '';
  lines.value = [makeLine()];
};

const handleSubmit = async () => {
  if (isSubmitting.value) return;

  const problem = validate();
  if (problem) {
    void dialog.alert('ตรวจสอบข้อมูล', problem, 'warning');
    return;
  }

  isSubmitting.value = true;
  needsNewDraft.value = false;
  try {
    const result = await FinanceService.createIncomeBatch(currentRoomId, buildPayload());
    dialog.notify(`บันทึกใบรับเงิน ${result.inc_receipt_no} แล้ว`);
    void router.push({
      name: 'finance-income-batch-detail',
      params: { id: result.id },
    });
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : 'บันทึกใบรับเงินไม่สำเร็จ';
    const status = apiStatus(error);
    if (status === 409) {
      needsNewDraft.value = true;
      void dialog.alert(
        'คีย์นี้ถูกใช้แล้ว',
        `${message} — ใบนี้ถูกส่งไปแล้วด้วยข้อมูลชุดเดิม ตรวจสอบรายการหรือกด "เริ่มใบใหม่" เพื่อสร้างใบใหม่ด้วยคีย์ใหม่`,
        'error',
      );
    } else if (status === 400 || status === 403) {
      // คงฟอร์มและคีย์เดิม — ผู้ใช้แก้ข้อมูลแล้วลองใหม่ได้
      void dialog.alert('บันทึกไม่สำเร็จ', message, 'error');
    } else {
      void dialog.alert('บันทึกไม่สำเร็จ', message, 'error');
    }
  } finally {
    isSubmitting.value = false;
  }
};

onMounted(() => {
  void fetchInitData();
});
</script>

<template>
  <div class="space-y-4 sm:space-y-5">
    <PageIntro
      description="รายรับอื่นที่ไม่ใช่บิลนักเรียน — หลายหมวดในใบเดียว เงินเข้าที่กระเป๋าเดียว และออก INC 1 ใบ"
    >
      <template #actions>
        <RouterLink to="/finance/income-batches" class="btn-ghost-ui">
          <i class="bi bi-arrow-left" aria-hidden="true"></i>
          กลับรายการ
        </RouterLink>
      </template>
    </PageIntro>

    <SkeletonRows v-if="isLoading" :rows="4" height="h-24" />
    <StateBlock
      v-else-if="hasError"
      variant="error"
      hint="โหลดกระเป๋า/หมวดรายรับ/ช่องทางชำระเงินไม่สำเร็จ"
      @retry="fetchInitData"
    />

    <!-- 🔒 สมาชิกที่ไม่มี MANAGE_FINANCE ดูรายการได้ แต่สร้างไม่ได้ -->
    <StateBlock
      v-else-if="!canManageFinance"
      variant="error"
      title="ไม่มีสิทธิ์สร้างใบรับเงิน"
      hint="ต้องมีสิทธิ์จัดการการเงิน (MANAGE_FINANCE) — ติดต่อแอดมินของห้อง"
      icon="bi-lock"
    >
      <RouterLink to="/finance/income-batches" class="btn-ghost-ui mt-2">
        กลับรายการ
      </RouterLink>
    </StateBlock>

    <StateBlock
      v-else-if="!accounts.length"
      variant="empty"
      title="ยังไม่มีกระเป๋าเงิน"
      hint="เพิ่มกระเป๋าเงินได้ที่หน้าตั้งค่าการเงินก่อนสร้างใบรับเงิน"
      icon="bi-wallet2"
    />

    <form v-else class="space-y-4 sm:space-y-5" @submit.prevent="handleSubmit">
      <!-- ① หัวใบ -->
      <div class="page-card p-4 sm:p-6">
        <h2 class="section-title mb-3 flex items-center gap-2">
          <i class="bi bi-cash-stack text-brand-700" aria-hidden="true"></i>
          ข้อมูลหัวใบ
        </h2>

        <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 sm:gap-4">
          <div>
            <label class="field-label" for="incomePayer">
              ผู้จ่าย <span class="text-danger-600">*</span>
            </label>
            <input
              id="incomePayer"
              v-model="payerName"
              type="text"
              class="field"
              maxlength="150"
              placeholder="เช่น ผู้ปกครองกลุ่ม 6/1, สมาคมผู้ปกครอง"
              data-test="payer-name"
            />
            <p class="mt-1 text-xs text-ink-3">
              ชื่ออิสระ — พิมพ์ลงเอกสารตามที่กรอก ไม่ผูกกับบัญชีนักเรียน
            </p>
          </div>

          <div>
            <label class="field-label" for="incomeDate">
              วันที่รับเงิน <span class="text-danger-600">*</span>
            </label>
            <input
              id="incomeDate"
              v-model="incomeDate"
              type="date"
              class="field"
              data-test="income-date"
            />
          </div>

          <div>
            <label class="field-label" for="incomeReceiver">ผู้รับเงิน <span class="text-danger-600">*</span></label>
            <PersonPicker
              v-model="receiverPersonId"
              :roles="['receive']"
              placeholder="เลือกผู้รับเงินจากทะเบียน"
              @change="onReceiverPersonChange"
            />
            <input
              id="incomeReceiver"
              v-model="receiverName"
              type="text"
              class="field mt-2"
              maxlength="150"
              placeholder="หรือพิมพ์ชื่อผู้รับเงินเอง"
              :disabled="receiverPersonId !== null"
              data-test="receiver-name"
            />
            <p v-if="receiverPersonId !== null" class="mt-1 text-xs text-ink-3">
              ใช้ชื่อจากทะเบียน —
              <button type="button" class="font-bold text-brand-700 hover:underline" @click="onClearReceiverPerson">
                พิมพ์เองแทน
              </button>
            </p>
          </div>

          <div>
            <label class="field-label" for="incomeWallet">
              กระเป๋าที่เงินเข้า <span class="text-danger-600">*</span>
            </label>
            <select
              id="incomeWallet"
              v-model.number="walletAccountId"
              class="field"
              data-test="wallet"
            >
              <option :value="0" disabled>— เลือกกระเป๋า —</option>
              <option v-for="acc in accounts" :key="acc.id" :value="acc.id">
                {{ acc.account_name }} (เหลือ {{ formatMoney(acc.balance) }})
              </option>
            </select>
            <p class="mt-1 text-xs text-ink-3">กระเป๋าเดียวทั้งใบ — ทุกบรรทัดเข้าที่นี่</p>
          </div>

          <div class="sm:col-span-2">
            <label class="field-label" for="incomeChannel">ช่องทางรับเงิน (ไม่บังคับ)</label>
            <select
              id="incomeChannel"
              v-model.number="channelId"
              class="field"
              data-test="channel"
            >
              <option :value="null">— ไม่ระบุช่องทาง —</option>
              <option v-for="ch in activeChannels" :key="ch.id" :value="ch.id">
                {{ channelLabel(ch) }}
              </option>
            </select>
            <div
              v-if="channelWalletMismatch"
              class="mt-2 flex flex-wrap items-center justify-between gap-2 rounded-control bg-warn-50 p-2 text-sm text-warn-700"
              data-test="channel-wallet-warning"
            >
              <span>
                <i class="bi bi-exclamation-triangle" aria-hidden="true"></i>
                ช่องทางนี้ผูกกับกระเป๋าอื่น — บันทึกไม่ได้จนกว่าจะเลือกให้ตรง
              </span>
              <button type="button" class="btn-ghost-ui !py-1" data-test="clear-channel" @click="clearChannel">
                ล้างช่องทาง
              </button>
            </div>
          </div>

          <div class="sm:col-span-2">
            <label class="field-label" for="incomeNote">หมายเหตุ (ไม่บังคับ)</label>
            <input
              id="incomeNote"
              v-model="note"
              type="text"
              class="field"
              maxlength="500"
              placeholder="เช่น รายรับจากการขายของงานกีฬาสี"
            />
          </div>
        </div>
      </div>

      <!-- ② บรรทัด -->
      <div class="page-card p-4 sm:p-6">
        <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h2 class="section-title flex items-center gap-2">
            <i class="bi bi-list-check text-brand-700" aria-hidden="true"></i>
            รายการรับเงิน
            <span class="text-sm font-normal text-ink-3">({{ lines.length }} บรรทัด)</span>
          </h2>
          <button type="button" class="btn-ghost-ui" data-test="add-line" @click="addLine">
            <i class="bi bi-plus-lg" aria-hidden="true"></i>
            เพิ่มบรรทัด
          </button>
        </div>

        <div class="space-y-3">
          <IncomeLineEditor
            v-for="(line, i) in lines"
            :key="i"
            :model-value="line"
            :categories="categories"
            :index="i + 1"
            :can-remove="lines.length > 1"
            @update:model-value="(payload) => updateLine(i, payload)"
            @remove="removeLine(i)"
          />
        </div>

        <div class="mt-4 rounded-card bg-canvas p-3 sm:p-4">
          <div class="flex flex-wrap items-center justify-between gap-2">
            <p class="text-sm font-bold text-ink-2">ยอดรวมทั้งใบ</p>
            <p class="num text-xl font-bold text-ink-1" data-test="income-total">
              {{ formatMoney(totalAmount) }}
            </p>
          </div>
          <p class="mt-1 text-xs text-ink-3">
            เงินเข้าที่กระเป๋าที่เลือกด้านบนครั้งเดียวเท่ายอดรวม — INC ออก 1 ใบ
          </p>
        </div>
      </div>

      <!-- ③ ลายเซ็น -->
      <div class="page-card p-4 sm:p-6">
        <h2 class="section-title mb-3 flex items-center gap-2">
          <i class="bi bi-pen text-brand-700" aria-hidden="true"></i>
          ลายเซ็นบนเอกสาร
        </h2>

        <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 sm:gap-4">
          <div>
            <p class="field-label">ผู้ออก</p>
            <p class="field flex items-center bg-canvas text-ink-2">
              {{ currentUserName || '—' }}
            </p>
            <p class="mt-1 text-xs text-ink-3">ชื่อผู้ใช้ที่เข้าสู่ระบบ (แก้ไม่ได้)</p>
          </div>

          <div>
            <p class="field-label">ผู้รับเงิน</p>
            <p class="field flex min-w-0 items-center truncate bg-canvas text-ink-2">
              {{ receiverPersonId ? receiverName : receiverName.trim() || '—' }}
            </p>
            <p class="mt-1 text-xs text-ink-3">ใช้ชื่อเดียวกับช่องผู้รับเงินด้านบน</p>
          </div>
        </div>
      </div>

      <!-- ④ ส่ง -->
      <div class="page-card p-4 sm:p-5">
        <div
          v-if="needsNewDraft"
          class="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-control bg-danger-50 p-3 text-sm text-danger-700"
          data-test="conflict-banner"
        >
          <p>คีย์นี้ถูกใช้กับข้อมูลชุดเดิมแล้ว — ต้องเริ่มใบใหม่เพื่อเปลี่ยนข้อมูล</p>
          <button type="button" class="btn-ghost-ui" data-test="new-draft" @click="startNewDraft">
            <i class="bi bi-file-earmark-plus" aria-hidden="true"></i>
            เริ่มใบใหม่
          </button>
        </div>

        <button
          type="submit"
          class="btn-primary w-full py-3"
          :disabled="isSubmitting"
          data-test="submit-batch"
        >
          <span
            v-if="isSubmitting"
            class="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white"
            aria-hidden="true"
          ></span>
          <span>{{ isSubmitting ? 'กำลังบันทึก...' : 'บันทึกใบรับเงิน' }}</span>
        </button>
      </div>
    </form>
  </div>
</template>
