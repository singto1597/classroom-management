<script setup lang="ts">
/**
 * ExpenseVoucherCreate — สร้างใบสำคัญจ่ายหลายบรรทัด (FIN-V2 / P4.3)
 * `/finance/expense-vouchers/new`
 *
 * 🔑 กติกาสำคัญ (brief P4.3):
 *   1. `idempotency_key` สร้าง **ตอน mount** ครั้งเดียว — retry ที่เน็ตสะดุดต้องใช้คีย์เดิม
 *      ไม่งั้นเงินถูกหักซ้ำ; คีย์ใหม่เกิดเฉพาะเมื่อผู้ใช้กด "เริ่มใบใหม่" (หลัง 409)
 *   2. กระเป๋าหัวใบ (`default_wallet_account_id`) เป็นแค่ค่าเริ่มต้น ⇒ บรรทัดที่ผู้ใช้
 *      **เลือกกระเป๋าเองแล้ว** (`walletTouched`) ห้ามถูกทับ
 *   3. CERT ไม่ได้คำนวณที่นี่ — แสดงแค่ว่าบรรทัดไหน "จะอยู่ใน CERT"; ยอดจริงอ่านจาก
 *      server หลังบันทึก (`cert_amount`/`cert_line_nos` ในหน้ารายละเอียด)
 *   4. `paper_bill_count` = 0 เสมอเมื่อสถานะไม่ใช่ `paper` (บังคับใน editor)
 *
 * ⚠️ `voucher_date` ส่งเป็น `YYYY-MM-DD` (วันไทย) ไม่ใช่ ISO datetime
 * ⚠️ เงินในช่องกรอกเป็น `number` — ห้ามใช้ `formatMoney` กับ input
 */
import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';

import PageIntro from '@/components/ui/PageIntro.vue';
import StateBlock from '@/components/ui/StateBlock.vue';
import SkeletonRows from '@/components/ui/SkeletonRows.vue';
import PersonPicker from '@/components/finance/PersonPicker.vue';
import ExpenseLineEditor from '@/components/finance/ExpenseLineEditor.vue';

import { FinanceService } from '@/services/finance';
import { apiStatus } from '@/services/api';
import { useAuthStore } from '@/stores/auth';
import { useDialog } from '@/composables/useDialog';
import { formatMoney, newIdempotencyKey, roundMoney } from '@/utils/money';
import { todayIso } from '@/utils/datetime';
import type {
  Account,
  Budget,
  Category,
  ExpenseVoucherCreate,
  ExpenseVoucherLinePayload,
  FinancePerson,
} from '@/types/finance';

/** บรรทัดในฟอร์ม = payload + ธง "ผู้ใช้แตะกระเป๋าเองแล้ว" (ไม่ส่งขึ้น server) */
interface DraftLine extends ExpenseVoucherLinePayload {
  walletTouched: boolean;
}

const authStore = useAuthStore();
const router = useRouter();
const dialog = useDialog();

const currentRoomId = authStore.currentRoomId!;
const currentUserName = authStore.currentUserName ?? '';
const canManageFinance = computed(() => authStore.canManageFinance);

const accounts = ref<Account[]>([]);
const categories = ref<Category[]>([]);
const budgets = ref<Budget[]>([]);
const isLoading = ref(true);
const hasError = ref(false);

const payeeName = ref('');
const payeePersonId = ref<number | null>(null);
const voucherDate = ref(todayIso());
const defaultWalletId = ref(0);
const note = ref('');

const approverPersonId = ref<number | null>(null);
const approverName = ref(currentUserName);

/**
 * 🔑 คีย์เดียวต่อ "การกรอกหนึ่งครั้ง" — สร้างตอน mount (ไม่ใช่ตอน submit)
 *    retry ทุกครั้งจนกว่าจะสำเร็จ/กดเริ่มใบใหม่ใช้ค่านี้เสมอ
 */
const idempotencyKey = ref(newIdempotencyKey());

const isSubmitting = ref(false);
/**
 * 409 = คีย์เดิม + payload ต่าง ⇒ ต้องเริ่มใบใหม่ด้วยคีย์ใหม่
 * ไม่ใช่แก้ payload แล้วยิงซ้ำคีย์เดิม (จะ 409 ตลอดไป)
 */
const needsNewDraft = ref(false);

const makeLine = (walletId: number): DraftLine => ({
  description: '',
  amount: 0,
  category_id: 0,
  budget_id: null,
  wallet_account_id: walletId,
  receipt_status: 'none',
  paper_bill_count: 0,
  attachment_placeholder: null,
  funding_source: 'room_fund',
  walletTouched: false,
});

const lines = ref<DraftLine[]>([makeLine(0)]);

const fetchInitData = async () => {
  isLoading.value = true;
  hasError.value = false;
  try {
    const [accRes, catRes, budgetRes] = await Promise.all([
      FinanceService.getAccounts(currentRoomId),
      FinanceService.getCategories(currentRoomId, 'expense'),
      FinanceService.getBudgets(currentRoomId, undefined, undefined, 'expense'),
    ]);
    accounts.value = accRes;
    categories.value = catRes.filter((c) => c.category_type === 'expense');
    budgets.value = budgetRes;
  } catch {
    hasError.value = true;
  } finally {
    isLoading.value = false;
  }
};

// ────────────────────────────────────────────────────────────────
// 🧾 บรรทัด
// ────────────────────────────────────────────────────────────────
const updateLine = (index: number, payload: ExpenseVoucherLinePayload) => {
  const prev = lines.value[index];
  if (!prev) return;
  // 🔒 ถ้าผู้ใช้เปลี่ยนกระเป๋าของบรรทัดนี้เอง = แตะแล้ว ห้ามทับภายหลัง
  const walletTouched =
    prev.walletTouched || payload.wallet_account_id !== prev.wallet_account_id;
  lines.value.splice(index, 1, { ...payload, walletTouched });
};

const addLine = () => {
  lines.value.push(makeLine(defaultWalletId.value));
};

const removeLine = (index: number) => {
  if (lines.value.length <= 1) return;
  lines.value.splice(index, 1);
};

/**
 * เปลี่ยนกระเป๋าหัวใบ → อัปเดตเฉพาะบรรทัดที่ยังไม่ถูกแตะ
 * 🔴 ห้าม map ทับทุกบรรทัด — จะทำลายค่าที่ผู้ใช้ตั้งใจแก้
 */
const onDefaultWalletChange = () => {
  const walletId = defaultWalletId.value;
  lines.value = lines.value.map((line) =>
    line.walletTouched ? line : { ...line, wallet_account_id: walletId },
  );
};

const onPayeePersonChange = (person: FinancePerson | null) => {
  if (person) payeeName.value = person.display_name;
};

const onApproverPersonChange = (person: FinancePerson | null) => {
  if (person) approverName.value = person.display_name;
};

// ────────────────────────────────────────────────────────────────
// 💰 ยอดรวม / ยอดต่อกระเป๋า / คำเตือนเงินไม่พอ
// ────────────────────────────────────────────────────────────────
const totalAmount = computed(() =>
  roundMoney(
    lines.value.reduce((sum, line) => sum + (Number.isFinite(line.amount) ? line.amount : 0), 0),
  ),
);

/** จำนวนบรรทัดที่จะทำให้เกิด CERT (ยอดจริง server คิดจาก DB) */
const certLineCount = computed(
  () => lines.value.filter((line) => line.receipt_status === 'none').length,
);

const walletTotals = computed(() => {
  const sums = new Map<number, number>();
  for (const line of lines.value) {
    if (!line.wallet_account_id) continue;
    sums.set(
      line.wallet_account_id,
      roundMoney((sums.get(line.wallet_account_id) ?? 0) + (line.amount || 0)),
    );
  }
  return [...sums.entries()]
    .map(([accountId, amount]) => ({
      accountId,
      name: accounts.value.find((a) => a.id === accountId)?.account_name ?? `#${accountId}`,
      amount,
    }))
    .filter((row) => row.amount > 0);
});

/** กระเป๋าที่จะติดลบ — **เตือนเท่านั้น** ไม่บล็อก (server เป็นผู้ตัดสิน) */
const insufficientWallets = computed(() =>
  walletTotals.value
    .map((row) => ({ ...row, balance: accounts.value.find((a) => a.id === row.accountId)?.balance ?? 0 }))
    .filter((row) => row.amount > row.balance),
);

// ────────────────────────────────────────────────────────────────
// ✅ ตรวจฝั่งจอ ( backend บังคับซ้ำ)
// ────────────────────────────────────────────────────────────────
const validate = (): string | null => {
  if (!payeeName.value.trim()) {
    return 'กรุณาระบุชื่อผู้รับเงิน เพราะชื่อนี้พิมพ์ลงบนใบสำคัญจ่าย';
  }
  if (!voucherDate.value) return 'กรุณาระบุวันที่ใบสำคัญจ่าย';
  if (!defaultWalletId.value) return 'กรุณาเลือกกระเป๋าเริ่มต้นของใบ';
  if (lines.value.length === 0) return 'ต้องมีอย่างน้อย 1 บรรทัด';

  for (const [i, line] of lines.value.entries()) {
    const at = `บรรทัดที่ ${i + 1}`;
    if (!line.description.trim()) return `${at}: กรุณาระบุรายละเอียด`;
    if (!(line.amount > 0)) return `${at}: จำนวนเงินต้องมากกว่า 0`;
    if (!line.category_id) return `${at}: กรุณาเลือกหมวดรายจ่าย`;
    if (!line.wallet_account_id) return `${at}: กรุณาเลือกกระเป๋าที่จ่าย`;
  }
  if (!(totalAmount.value > 0)) return 'ยอดรวมต้องมากกว่า 0';
  return null;
};

/**
 * ตัดธงฝั่งจอ (`walletTouched`) ออกก่อนส่ง server — เขียนฟิลด์ของ payload ตรง ๆ
 * แทน destructuring-omit เพราะฟิลด์ใหม่ที่เพิ่มทีหลังจะไม่หลุดไปกับ payload
 * โดยไม่ตั้งใจ (TS บังคับให้แก้ฟังก์ชันนี้เมื่อมีฟิลด์บังคับใหม่)
 */
const toPayloadLine = (line: DraftLine): ExpenseVoucherLinePayload => ({
  description: line.description.trim(),
  amount: line.amount,
  category_id: line.category_id,
  budget_id: line.budget_id,
  wallet_account_id: line.wallet_account_id,
  receipt_status: line.receipt_status,
  paper_bill_count: line.paper_bill_count,
  attachment_placeholder: line.attachment_placeholder,
  funding_source: line.funding_source,
});

const buildPayload = (): ExpenseVoucherCreate => ({
  idempotency_key: idempotencyKey.value,
  default_wallet_account_id: defaultWalletId.value,
  payee_person_id: payeePersonId.value,
  payee_name: payeeName.value.trim(),
  voucher_date: voucherDate.value,
  note: note.value.trim() || null,
  total_amount: totalAmount.value,
  approved_by_person_id: approverPersonId.value,
  approved_by_name: approverName.value.trim() || null,
  lines: lines.value.map(toPayloadLine),
});

/** 🆕 หลัง 409 — คีย์ใหม่ + ฟอร์มว่าง (ผู้ใช้ต้องกรอกใบใหม่ ไม่ใช่แก้ของเดิม) */
const startNewDraft = () => {
  idempotencyKey.value = newIdempotencyKey();
  needsNewDraft.value = false;
  payeeName.value = '';
  payeePersonId.value = null;
  voucherDate.value = todayIso();
  defaultWalletId.value = 0;
  note.value = '';
  approverPersonId.value = null;
  approverName.value = currentUserName;
  lines.value = [makeLine(0)];
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
    const result = await FinanceService.createExpenseVoucher(currentRoomId, buildPayload());
    dialog.notify(`บันทึกใบสำคัญจ่าย ${result.pv_receipt_no} แล้ว`);
    void router.push({
      name: 'finance-expense-voucher-detail',
      params: { id: result.id },
    });
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : 'บันทึกใบสำคัญจ่ายไม่สำเร็จ';
    const status = apiStatus(error);
    if (status === 409) {
      needsNewDraft.value = true;
      void dialog.alert(
        'คีย์นี้ถูกใช้แล้ว',
        `${message} — ใบนี้ถูกส่งไปแล้วด้วยข้อมูลชุดเดิม ตรวจสอบรายการหรือกด "เริ่มใบใหม่" เพื่อสร้างใบใหม่ด้วยคีย์ใหม่`,
        'error',
      );
    } else if (status === 400 || status === 403) {
      // คงฟอร์มและคีย์เดิม — ผู้ใช้แก้ข้อมูลแล้วลองใหม่ได้ (400 = ข้อมูลไม่ผ่าน, 403 = ไม่มีสิทธิ์)
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
      description="หนึ่งใบสั่งจ่ายได้หลายรายการ — PV ออกทุกครั้ง และ CERT ออกเฉพาะบรรทัดที่ไม่มีใบเสร็จ"
    >
      <template #actions>
        <RouterLink to="/finance/expense-vouchers" class="btn-ghost-ui">
          <i class="bi bi-arrow-left" aria-hidden="true"></i>
          กลับรายการ
        </RouterLink>
      </template>
    </PageIntro>

    <SkeletonRows v-if="isLoading" :rows="4" height="h-24" />
    <StateBlock
      v-else-if="hasError"
      variant="error"
      hint="โหลดกระเป๋า/หมวดรายจ่าย/งบประมาณไม่สำเร็จ"
      @retry="fetchInitData"
    />

    <!-- 🔒 สมาชิกที่ไม่มี MANAGE_FINANCE เห็นหน้ารายการได้ แต่สร้างไม่ได้ -->
    <StateBlock
      v-else-if="!canManageFinance"
      variant="error"
      title="ไม่มีสิทธิ์สร้างใบสำคัญจ่าย"
      hint="ต้องมีสิทธิ์จัดการการเงิน (MANAGE_FINANCE) — ติดต่อแอดมินของห้อง"
      icon="bi-lock"
    >
      <RouterLink to="/finance/expense-vouchers" class="btn-ghost-ui mt-2">
        กลับรายการ
      </RouterLink>
    </StateBlock>

    <StateBlock
      v-else-if="!accounts.length"
      variant="empty"
      title="ยังไม่มีกระเป๋าเงิน"
      hint="เพิ่มกระเป๋าเงินได้ที่หน้าตั้งค่าการเงินก่อนสร้างใบสำคัญจ่าย"
      icon="bi-wallet2"
    />

    <form v-else class="space-y-4 sm:space-y-5" @submit.prevent="handleSubmit">
      <!-- ① หัวใบ -->
      <div class="page-card p-4 sm:p-6">
        <h2 class="section-title mb-3 flex items-center gap-2">
          <i class="bi bi-cash-coin text-brand-700" aria-hidden="true"></i>
          ข้อมูลหัวใบ
        </h2>

        <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 sm:gap-4">
          <div>
            <label class="field-label" for="voucherPayee">
              ผู้รับเงิน <span class="text-danger-600">*</span>
            </label>
            <input
              id="voucherPayee"
              v-model="payeeName"
              type="text"
              class="field"
              maxlength="150"
              placeholder="เช่น ร้านวัสดุการเรียน"
              data-test="payee-name"
            />
            <div class="mt-2">
              <PersonPicker
                v-model="payeePersonId"
                placeholder="เลือกผู้รับเงินจากทะเบียน (ไม่บังคับ)"
                @change="onPayeePersonChange"
              />
            </div>
          </div>

          <div>
            <label class="field-label" for="voucherDate">
              วันที่ใบสำคัญจ่าย <span class="text-danger-600">*</span>
            </label>
            <input
              id="voucherDate"
              v-model="voucherDate"
              type="date"
              class="field"
              data-test="voucher-date"
            />

            <label class="field-label mt-3" for="defaultWallet">
              กระเป๋าเริ่มต้น <span class="text-danger-600">*</span>
            </label>
            <select
              id="defaultWallet"
              v-model.number="defaultWalletId"
              class="field"
              data-test="default-wallet"
              @change="onDefaultWalletChange"
            >
              <option :value="0" disabled>— เลือกกระเป๋า —</option>
              <option v-for="acc in accounts" :key="acc.id" :value="acc.id">
                {{ acc.account_name }} (เหลือ {{ formatMoney(acc.balance) }})
              </option>
            </select>
            <p class="mt-1 text-xs text-ink-3">
              ใช้เป็นค่าเริ่มต้นของทุกบรรทัด — บรรทัดที่เลือกกระเป๋าเองแล้วจะไม่ถูกทับ
            </p>
          </div>

          <div class="sm:col-span-2">
            <label class="field-label" for="voucherNote">หมายเหตุ (ไม่บังคับ)</label>
            <input
              id="voucherNote"
              v-model="note"
              type="text"
              class="field"
              maxlength="500"
              placeholder="เช่น ซื้อของเข้าห้องก่อนกีฬาสี"
            />
          </div>
        </div>
      </div>

      <!-- ② บรรทัด -->
      <div class="page-card p-4 sm:p-6">
        <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h2 class="section-title flex items-center gap-2">
            <i class="bi bi-list-check text-brand-700" aria-hidden="true"></i>
            รายการเบิกจ่าย
            <span class="text-sm font-normal text-ink-3">({{ lines.length }} บรรทัด)</span>
          </h2>
          <button type="button" class="btn-ghost-ui" data-test="add-line" @click="addLine">
            <i class="bi bi-plus-lg" aria-hidden="true"></i>
            เพิ่มบรรทัด
          </button>
        </div>

        <div class="space-y-3">
          <ExpenseLineEditor
            v-for="(line, i) in lines"
            :key="i"
            :model-value="line"
            :categories="categories"
            :budgets="budgets"
            :accounts="accounts"
            :index="i + 1"
            :can-remove="lines.length > 1"
            :default-wallet-account-id="defaultWalletId"
            @update:model-value="(payload) => updateLine(i, payload)"
            @remove="removeLine(i)"
          />
        </div>

        <!-- 💰 สรุปยอด -->
        <div class="mt-4 rounded-card bg-canvas p-3 sm:p-4">
          <div class="flex flex-wrap items-center justify-between gap-2">
            <p class="text-sm font-bold text-ink-2">ยอดรวมทั้งใบ</p>
            <p class="num text-xl font-bold text-ink-1" data-test="voucher-total">
              {{ formatMoney(totalAmount) }}
            </p>
          </div>
          <p v-if="certLineCount" class="mt-1 text-xs font-bold text-warn-700">
            {{ certLineCount }} บรรทัดจะอยู่ใน CERT — ระบบคำนวณยอด CERT จากข้อมูลจริงหลังบันทึก
          </p>
          <p v-else class="mt-1 text-xs text-ink-3">
            ทุกบรรทัดมีหลักฐาน ⇒ จะไม่ออกใบรับรองแทนใบเสร็จ
          </p>

          <ul v-if="walletTotals.length" class="mt-2 space-y-1 text-xs text-ink-3">
            <li v-for="row in walletTotals" :key="row.accountId" class="flex justify-between gap-2">
              <span class="min-w-0 truncate">จ่ายจาก {{ row.name }}</span>
              <span class="num shrink-0 font-bold text-ink-2">{{ formatMoney(row.amount) }}</span>
            </li>
          </ul>
        </div>
      </div>

      <!-- ③ ลายเซ็น -->
      <div class="page-card p-4 sm:p-6">
        <h2 class="section-title mb-3 flex items-center gap-2">
          <i class="bi bi-pen text-brand-700" aria-hidden="true"></i>
          ลายเซ็นบนเอกสาร
        </h2>

        <div class="grid grid-cols-1 gap-3 sm:grid-cols-3 sm:gap-4">
          <div>
            <p class="field-label">ผู้จัดทำ</p>
            <p class="field flex items-center bg-canvas text-ink-2">
              {{ currentUserName || '—' }}
            </p>
            <p class="mt-1 text-xs text-ink-3">ชื่อผู้ใช้ที่เข้าสู่ระบบ (แก้ไม่ได้)</p>
          </div>

          <div>
            <label class="field-label" for="approverName">ผู้อนุมัติ</label>
            <input
              id="approverName"
              v-model="approverName"
              type="text"
              class="field"
              maxlength="150"
              placeholder="เช่น หัวหน้าห้อง"
              data-test="approver-name"
            />
            <div class="mt-2">
              <PersonPicker
                v-model="approverPersonId"
                :roles="['approve']"
                placeholder="เลือกผู้อนุมัติจากทะเบียน"
                @change="onApproverPersonChange"
              />
            </div>
          </div>

          <div>
            <p class="field-label">ผู้รับเงิน</p>
            <p class="field flex min-w-0 items-center truncate bg-canvas text-ink-2">
              {{ payeeName.trim() || '—' }}
            </p>
            <p class="mt-1 text-xs text-ink-3">ใช้ชื่อเดียวกับช่องผู้รับเงินด้านบน</p>
          </div>
        </div>
      </div>

      <!-- ④ แถบเตือน -->
      <div class="page-card border-warn-200 bg-warn-50 p-4 text-sm text-warn-700 sm:p-5">
        <p class="flex items-start gap-2">
          <i class="bi bi-info-circle mt-0.5 shrink-0" aria-hidden="true"></i>
          <span>
            PV จะถูกออกทุกครั้ง · CERT จะถูกออกเฉพาะบรรทัดที่ไม่มีใบเสร็จ
            (ยอด CERT ไม่เท่ากับยอดรวมทั้งใบเสมอ)
          </span>
        </p>
        <p v-if="insufficientWallets.length" class="mt-2 flex items-start gap-2" data-test="insufficient-warning">
          <i class="bi bi-exclamation-triangle mt-0.5 shrink-0" aria-hidden="true"></i>
          <span>
            เงินในกระเป๋าอาจไม่พอ:
            <span v-for="row in insufficientWallets" :key="row.accountId" class="font-bold">
              {{ row.name }} ต้องจ่าย {{ formatMoney(row.amount) }} แต่เหลือ {{ formatMoney(row.balance) }}
            </span>
            — ระบบจะตรวจซ้ำตอนบันทึก
          </span>
        </p>
      </div>

      <!-- ⑤ ส่ง -->
      <div class="page-card p-4 sm:p-5">
        <!-- 🔁 409: คีย์เดิม payload ต่าง — ทางออกเดียวคือเริ่มใบใหม่ (คีย์ใหม่) -->
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
          data-test="submit-voucher"
        >
          <span
            v-if="isSubmitting"
            class="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white"
            aria-hidden="true"
          ></span>
          <span>{{ isSubmitting ? 'กำลังบันทึก...' : 'บันทึกใบสำคัญจ่าย' }}</span>
        </button>
      </div>
    </form>
  </div>
</template>
