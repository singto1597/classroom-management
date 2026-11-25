import type { ApiSuccessResponse } from '@/types/api';

export interface Account {
  id: number;
  account_name: string;
  balance: number;
  /**
   * 🏦 [F6] ช่องทางจ่ายของกระเป๋า — ตั้งครั้งเดียวที่หน้าตั้งกระเป๋าเงิน แล้วใบสำคัญจ่าย
   * ดึงไปพิมพ์เอง (ผู้ใช้ไม่ต้องเลือกช่องทางซ้ำตอนบันทึกรายจ่าย)
   * ⚠️ `undefined` = backend เวอร์ชันก่อน F6 ⇒ ถือเป็น `'cash'` ไม่ใช่ "ไม่ระบุ"
   */
  account_kind?: AccountKind;
  bank_name?: string | null;
  bank_account_no?: string | null;
  bank_account_name?: string | null;
}

export interface Category {
  id: number;
  category_name: string;
  category_type: 'income' | 'expense';
}

export interface Transaction {
  id: number;
  amount: number;
  description: string;
  transaction_type: 'income' | 'expense';
  created_at: string;
  slip_image_url: string | null;
  recorded_by: string | null;
  account_name: string | null;
  category_name: string | null;
  transfer_group_id: number | null;
}

export interface TransactionList {
  total_count: number;
  items: Transaction[];
}

export type LateFeeMode = 'none' | 'fixed' | 'percent';

export interface Collection {
  id: number;
  title: string;
  amount: number;
  due_date: string | null;
  status: 'active' | 'closed';
  /** ⏰ นโยบายค่าปรับจ่ายล่าช้า (P6.5) — ค่าเริ่มต้น 'none' = ไม่ปรับ */
  late_fee_mode?: LateFeeMode;
  /** จำนวนเงิน (fixed) หรือเปอร์เซ็นต์ (percent) */
  late_fee_amount?: number;
  late_fee_grace_days?: number;
}

export interface StudentPaymentSummary {
  total: number;
  paid: number;
  pending: number;
}

export interface StudentPaymentDetail {
  payment_id: number;
  status: 'pending' | 'paid';
  paid_amount: number;
  total_amount: number;
  paid_at: string | null;
  slip_image_url: string | null;
  student_id: number; // ✨ ฟีเจอร์ใหม่จาก AI
  student_no: number;
  first_name: string;
  last_name: string;
  nickname: string | null;
  first_name_en: string | null;
  last_name_en: string | null;
  nickname_en: string | null;
}

export interface CollectionStatus {
  collection_id: number;
  summary: StudentPaymentSummary;
  students: StudentPaymentDetail[];
}

export interface Debtor {
  student_id: number;
  student_no: number;
  student_name: string;
  overdue_count: number;
  /** 💰 ยอดค้าง **ดิบ** — ยังไม่หักเครดิตล่วงหน้าที่นักเรียนมีอยู่ */
  total_pending_amount: number;
  /**
   * 💰 [F4] เครดิตคงเหลือ (เงินรับล่วงหน้าที่ถูกหักใช้ไปบางส่วนแล้ว)
   * ⚠️ **ห้ามเอาไปลบจาก `total_pending_amount` เองที่หน้าจอ** — backend ส่ง
   *    `net_pending_amount` ที่หักแล้วมาให้แล้ว และเป็นตัวเดียวกับที่ระบบจะหักจริง
   *    (สองที่คำนวณเอง = วันหนึ่งจอกับการหักจริงไม่ตรงกันโดยไม่มีอะไรฟ้อง)
   */
  credit_balance: number;
  /** 💰 [F4] ยอดที่ต้องเก็บจริงหลังหักเครดิต — `max(total_pending_amount - credit_balance, 0)` */
  net_pending_amount: number;
}

export interface StudentDebtItem {
  payment_id: number;
  collection_id: number;
  title: string;
  amount: number;
  due_date: string | null;
  /**
   * ⚖️ [P5] `'fine'` = บิลค่าปรับ (โปรเจกต์เก็บเงินซ่อน) — **ห้ามลิงก์ไปหน้าโปรเจกต์**
   * ใช้ `fine_id` พาไป `/finance/fines/{id}` แทน
   */
  collection_kind?: string;
  /** มีค่าเมื่อบิลนี้เป็นค่าปรับ */
  fine_id?: number | null;
}

export interface StudentDebtProfile {
  student_id: number;
  student_name: string;
  total_pending_amount: number;
  debts: StudentDebtItem[]; // ใช้ Type ที่เจาะจงแทนการปล่อยเป็น array กว้าง ๆ
}

export interface CategoryBreakdown {
  category_name: string;
  total_amount: number;
}

export interface FinanceSummary {
  net_worth: number;
  total_income: number;
  total_expense: number;
  pending_collection_amount: number;
  period: string;
  expense_breakdown: CategoryBreakdown[]; // ใช้ Type ที่เจาะจงแทนการปล่อยเป็น array กว้าง ๆ
}

// ✨ เพิ่ม Type ใหม่สำหรับดึงรายชื่อเด็กโดยเฉพาะ
export interface BasicStudent {
  id: number;
  student_no: number;
  first_name: string;
  last_name: string;
  nickname: string;
  first_name_en: string | null;
  last_name_en: string | null;
  nickname_en: string | null;
}

// --- Request Payloads ---

export interface AccountCreate {
  account_name: string;
  initial_balance: number;
  /**
   * 🏦 [F6] ช่องทางจ่ายของกระเป๋า — ไม่ส่ง = `'cash'` (ค่า default ของคอลัมน์)
   * ℹ️ สามตัวธนาคารไม่บังคับที่ schema แต่ **ควรกรอกเมื่อเลือก `'transfer'`**:
   *    ใบสำคัญจ่ายจะพิมพ์เฉพาะที่มี ⇒ ใบที่จ่ายโดยไม่มีเลขบัญชีตรวจสอบย้อนหลังไม่ได้
   */
  account_kind?: AccountKind;
  bank_name?: string | null;
  bank_account_no?: string | null;
  bank_account_name?: string | null;
  user_name?: string;
}

/** แก้กระเป๋าเงิน — ชื่อ + ข้อมูลช่องทางจ่าย (ไม่แตะยอดคงเหลือ) */
export interface AccountUpdate {
  account_name: string;
  account_kind?: AccountKind;
  bank_name?: string | null;
  bank_account_no?: string | null;
  bank_account_name?: string | null;
  user_name?: string;
}

export interface CategoryCreate {
  category_name: string;
  category_type: 'income' | 'expense';
  user_name?: string;
}

export interface TransactionCreate {
  account_id: number;
  category_id: number;
  amount: number;
  description: string;
  transaction_type: 'income' | 'expense';
  slip_image_url?: string | null;
  /**
   * 🧾 [F6] "อีกฝ่าย" ของรายการ — **บังคับทั้งสองแท็บ** (ฝั่ง backend ตรวจที่ชั้น service
   * และตอบ 400 ภาษาไทย ไม่ใช่ 422)
   *
   * 🔴 ห้ามปล่อยว่างแม้แต่กรณีเดียว: ชื่อนี้คือ **คู่กรณีที่พิมพ์ลงบนกระดาษ**
   *    • แท็บรายจ่าย → ผู้เบิก/ผู้รับเงิน (ลงบนใบสำคัญจ่าย)
   *    • แท็บรายรับ  → ผู้จ่ายเงิน (ลงบนใบรับเงิน ที่ออกให้ผู้ที่จ่ายเงินเข้ามา)
   *    ปล่อยว่าง = เอกสารการเงินที่ไม่มีคู่กรณี ซึ่งตรวจสอบย้อนหลังไม่ได้
   */
  payee_name: string;
  /** ผู้อนุมัติ (ใบสำคัญจ่าย) — ไม่บังคับ: บางห้องไม่มีหัวหน้าที่เซ็น */
  approver_name?: string | null;
  /** จำนวนเอกสารแนบ (บิลเงินสด/ใบเสร็จจากร้านค้า) — `0` = ไม่ได้แนบ */
  attachment_count?: number;
  user_name: string;
}

/**
 * 🧾 [F6] คำตอบของ `POST /finance/transactions` — **รวมเลขเอกสารที่เพิ่งออก**
 *
 * 🔴 เดิม endpoint นี้ประกาศ `response_model=SuccessResponse` ซึ่ง **ตัดฟิลด์ที่ service
 *    คืนทิ้งเงียบ ๆ** ⇒ หน้าจอไม่มีทางรู้เลขเอกสารที่จะให้ผู้ใช้โหลด/อ้างอิงได้
 *    (กับดักเดียวกับ `BatchPaymentConfirmResponse` — เจอเป็นครั้งที่สองในระบบนี้)
 * ⚠️ `receipt_no` เป็น `null` ได้: รายการที่ไม่ได้ออกเอกสาร (เช่นอนาคตที่มีชนิดที่ไม่ต้องออก)
 */
export interface TransactionCreateResponse extends ApiSuccessResponse {
  receipt_no?: string | null;
  doc_type?: ReceiptDocType | null;
  doc_type_label?: string | null;
}

export interface TransferCreate {
  from_account_id: number;
  to_account_id: number;
  amount: number;
  description: string;
  user_name: string;
}

export interface FeeCollectionCreate {
  title: string;
  amount: number;
  due_date: string;
  student_ids?: number[]; // ✨ ฟีเจอร์ใหม่จาก AI
  user_name?: string;
  /** ⏰ ตั้งนโยบายค่าปรับล่าช้าได้ตั้งแต่สร้าง (P6.5) */
  late_fee_mode?: LateFeeMode;
  late_fee_amount?: number;
  late_fee_grace_days?: number;
}

// 🧾 เรียกเก็บเงินเองรายบุคคล — หลายคน คนละยอด ภายใต้ชื่อเดียวกัน (P6.5)
export interface CustomChargeItem {
  student_id: number;
  amount: number;
  note?: string;
}

export interface CustomChargeCreate {
  title: string;
  due_date: string;
  items: CustomChargeItem[];
  /** 🔑 บังคับ — กดซ้ำคีย์เดิมได้ผลเดิม ไม่สร้างบิลซ้ำ */
  idempotency_key: string;
  user_name?: string;
}

export interface CustomChargeResultItem {
  collection_id: number;
  student_id: number;
  amount: number;
  reused: boolean;
}

export interface CustomChargeResponse {
  status: string;
  message?: string | null;
  collections: CustomChargeResultItem[];
  total_amount: number;
  created: boolean;
}

export interface PaymentConfirm {
  paid_to_account_id: number;
  paid_amount: number;
  slip_image_url?: string | null;
  user_name: string;
}

// ✨ รับเงินรวบยอด (Batch) — ปลดหนี้หลายรายการของนักเรียนคนเดียวกันในครั้งเดียว
// (backend ประมวลผล atomic + แจ้งเตือน Discord รอบเดียว)
export interface BatchPaymentItem {
  payment_id: number;
  paid_amount: number;
}

export interface BatchPaymentConfirm {
  items: BatchPaymentItem[];
  paid_to_account_id: number;
  slip_image_url?: string | null;
  user_name: string;
  /**
   * 🧾 [F5] ออกใบเสร็จให้ **ทุกรายการที่รับเงินในรอบนี้** — ไม่ส่ง = เปิด (default ของ backend)
   *
   * ⚠️ เป็น `?` โดยเจตนา: ไม่ส่ง = เปิด ซึ่งเป็นพฤติกรรมที่ผู้ใช้ขอ ("กดเคลียร์หนี้แล้ว
   *    อยากได้ใบเสร็จมาพร้อมกันหมดเลย") ⇒ ส่ง `false` เท่านั้นเมื่อผู้ใช้ติ๊กปิดเอง
   */
  issue_receipts?: boolean;
}

/**
 * ผลของ `PUT /finance/payments/batch` — เงินที่รับ **บวก** ใบเสร็จที่ออกให้ในรอบนั้น
 *
 * 🔴 `receipts` เป็น object เต็ม ไม่ใช่แค่เลขที่ ⇒ หน้าจอ **ดาวน์โหลด PDF รวมได้ทันที**
 *    จากคำตอบนี้ โดยไม่ต้องยิง `GET /finance/receipts` ซ้ำแล้วเดาว่าจะกรองยังไง
 *    ให้เหลือ "เฉพาะใบที่เพิ่งออก" (ซึ่งเปราะและผิดได้ง่ายเมื่อมีใบอื่นออกแทรก)
 */
export interface BatchPaymentResult {
  status: string;
  message: string | null;
  receipts: Receipt[];
  issued_count: number;
  reused_count: number;
  /** 📚 ชุดที่ระบบจัดให้อัตโนมัติเมื่อออก ≥ 2 ใบ — `null` = ไม่ได้จัดชุด */
  batch_id: number | null;
}

export interface FeeCollectionUpdate {
  title?: string;
  amount?: number;
  due_date?: string;
  status?: 'active' | 'closed';
  user_name?: string;
  late_fee_mode?: LateFeeMode;
  late_fee_amount?: number;
  late_fee_grace_days?: number;
}

// =============================================================================
// 📊 งบการเงิน (Financial Statements) — งบทดลอง / งบกำไรขาดทุน / งบดุล
// =============================================================================
// โครงตรงกับ backend/models/finance_schemas.py (TrialBalanceResponse ฯลฯ) เป๊ะ
// ⚠️ ทุกงบอ่านจาก **journal อย่างเดียว** และถูก clamp ที่ CUTOFF_DATE (2026-09-01)
//    ถ้าผู้ใช้เลือกวันก่อนเส้น ระบบจะคืน "ว่าง" + `note` อธิบาย — ต้องแสดง note ให้เด่น

/** แถวบัญชีในงบทดลอง/งบดุล — ยอดสะสม YTD ของ ledger หนึ่งตัว */
export interface TrialBalanceLedgerRow {
  ledger_id: number;
  /** เป็น null ได้จริงใน DB (query สั่ง ORDER BY account_code NULLS LAST) */
  account_code: string | null;
  account_name: string;
  /** asset | liability | equity | revenue | expense */
  account_type: string;
  total_debit: number;
  total_credit: number;
  /** asset/expense = Dr−Cr, อื่น ๆ = Cr−Dr (ฝั่งที่เพิ่มยอดเป็นบวกเสมอ) */
  balance: number;
}

export interface TrialBalance {
  ledgers: TrialBalanceLedgerRow[];
  /** ผลรวม "ยอดรวม" ไม่ใช่สุทธิ — เท่ากันเสมอถ้า journal สมดุล */
  total_debit: number;
  total_credit: number;
  is_balanced: boolean;
  note: string | null;
}

/** บรรทัดรายได้/ค่าใช้จ่ายในงบกำไรขาดทุน */
export interface StatementLine {
  account_name: string;
  amount: number;
}

export interface IncomeStatement {
  /** ค่าที่ **ผู้ใช้ส่งมา** ไม่ใช่ค่าที่ถูก clamp แล้ว — ตัวเลขอาจครอบช่วงแคบกว่านี้ */
  start_date: string;
  end_date: string;
  revenues: StatementLine[];
  expenses: StatementLine[];
  total_revenue: number;
  total_expense: number;
  net_income: number;
  note: string | null;
}

export interface BalanceSheet {
  as_of: string;
  assets: TrialBalanceLedgerRow[];
  assets_total: number;
  liabilities: TrialBalanceLedgerRow[];
  liability_total: number;
  equities: TrialBalanceLedgerRow[];
  equity_total: number;
  retained_earnings: number;
  /** equity_total + retained_earnings */
  total_equity_side: number;
  /** liability_total + total_equity_side — ต้องเท่ากับ assets_total */
  total_liabilities_and_equity: number;
  is_balanced: boolean;
  /** memo: กำไรของงวด period_start→period_end ให้ตรวจเทียบกับงบกำไรขาดทุน */
  period_net_income: number;
  period_start: string;
  period_end: string;
  note: string | null;
}

// --- ตารางงบการเงิน (StatementTable) ---

/** คอลัมน์ที่ตารางงบแสดงได้ — 'name' คือชื่อบัญชี, ที่เหลือเป็นตัวเลข (ยกเว้น 'code') */
export type StatementColumnKey = 'code' | 'name' | 'debit' | 'credit' | 'amount';

export interface StatementColumn {
  key: StatementColumnKey;
  label: string;
  /** true = ชิดขวา + ใช้ `.num` (ตัวเลข) */
  numeric?: boolean;
}

/** แถวในตารางงบ — รวมแถวหัวกลุ่ม (มี `group`) และแถวรวมยอด (มี `isTotal`) ไว้ในชนิดเดียว */
export interface StatementRow {
  /** รหัสบัญชี (อาจเป็น null จาก DB) */
  code?: string | null;
  name?: string;
  debit?: number;
  credit?: number;
  amount?: number;
  /** ถ้ามีค่า = แถวนี้เป็นหัวข้อกลุ่ม (แสดงเป็นแถบหัวข้อ ไม่ใช่ข้อมูล) */
  group?: string;
  /** true = แถวรวมยอด (ตัวหนา + เส้นคู่) */
  isTotal?: boolean;
}

// --- Query Params ---

// ตัวกรองสำหรับดึงประวัติการทำรายการ
// โครงตรงกับ TransactionFilter ฝั่ง backend (limit/offset/start_date/end_date/account_id/category_id/transaction_type)
// ส่วน `type` เป็นคีย์ที่หน้าจอส่งซ้ำไปด้วยเพื่อความเข้ากันได้กับ payload เดิม (backend ไม่ได้อ่านค่านี้)
export interface TransactionQueryParams {
  limit: number;
  offset: number;
  type?: 'income' | 'expense';
  transaction_type?: 'income' | 'expense';
  start_date?: string;
  end_date?: string;
  account_id?: number;
  category_id?: number;
}

// --- 💰 งบประมาณ (Budget) — F2 ---
//
// 📌 สัญญาที่ backend ล็อกไว้: `start_date`/`end_date` คือ **แหล่งความจริงเดียว** ของช่วงที่คิดยอด
//    ส่วน `period_type`/`period_year`/`period_month` เป็นฟิลด์ที่ service derive มาจากช่วงนั้นเอง
//    ⇒ ห้ามเอา period_* ไปใช้คำนวณหรือไปกรองอะไรที่หน้าจอ ให้ใช้ start_date/end_date เสมอ
//    (ป้าย "รายเดือน" กับตัวเลขจะไม่มีวันขัดกันก็เพราะข้อนี้)

/** งบประมาณ 1 รายการ — ยังไม่มียอดใช้ (ได้จาก `getBudgets`) */
export interface Budget {
  id: number;
  category_id: number;
  category_name: string;
  category_type: 'income' | 'expense';
  /** 'monthly' | 'yearly' | 'custom' — derive จากช่วงวันที่ ไม่ได้รับจาก client */
  period_type: string;
  period_year: number;
  /** 1–12 และเป็น null เมื่อไม่ใช่รายเดือน */
  period_month: number | null;
  start_date: string;
  end_date: string;
  amount: number;
  note: string | null;
  created_by_name: string | null;
  created_at: string | null;
}

/** งบ 1 รายการ + ยอดใช้จริงในช่วงของ **ตัวมันเอง** (ไม่ใช่ช่วงที่ผู้ใช้กรอง) */
export interface BudgetItem {
  budget_id: number;
  category_id: number;
  category_name: string;
  category_type: 'income' | 'expense';
  amount: number;
  used: number;
  /** ติดลบได้เมื่อใช้เกินงบ — backend จงใจไม่ clamp ที่ 0 เพราะ "เกินไปเท่าไร" มีความหมาย */
  remaining: number;
  usage_pct: number | null;
  is_over: boolean;
  /** ใช้ไป 80–100% — เตือนก่อนแตก */
  is_near: boolean;
  period_start: string;
  period_end: string;
  period_type: string;
  note: string | null;
}

/** ภาพรวมงบประมาณในช่วงวันที่ที่เลือก (เฉพาะงบที่คาบเกี่ยวช่วงนั้น) */
export interface BudgetOverview {
  start_date: string;
  end_date: string;
  items: BudgetItem[];
  total_budget: number;
  total_used: number;
  over_count: number;
  warning_count: number;
}

export interface BudgetCreatePayload {
  category_id: number;
  amount: number;
  start_date: string;
  end_date: string;
  note?: string;
  user_name?: string;
}

/** PATCH — ส่งเฉพาะฟิลด์ที่จะแก้ ฟิลด์ที่ไม่ส่ง backend ไม่แตะ (model_dump(exclude_unset=True)) */
export interface BudgetUpdatePayload {
  amount?: number;
  start_date?: string;
  end_date?: string;
  note?: string;
  user_name?: string;
}

// --- 🧾 ใบเสร็จ / ใบแจ้งหนี้ (Receipt / Invoice) — F3 ---
//
// 📌 ความไม่สมมาตรที่ backend ล็อกไว้ด้วยรูปทรงของ partial unique index — **ห้าม "แก้" ให้เหมือนกัน**
//    เพราะมันถูกเข้ารหัสไว้ในระดับ DDL แล้ว (แก้ที่หน้าจอไม่ได้ และไม่ควรแก้):
//      • `receipt` = **idempotent** — 1 ใบต่อ 1 เหตุการณ์รับเงิน ออกซ้ำได้เลขเดิม
//        และ response จะบอกว่า `reused: true` (ไม่ใช่ error — การพิมพ์ซ้ำต้องปลอดภัย)
//      • `invoice` = **point-in-time** — ยอดค้างของนักเรียนเปลี่ยนเมื่อจ่ายเพิ่ม ใบเดิมจึงล้าสมัย
//        โดยธรรมชาติ ⇒ ออกซ้ำได้ **เลขใหม่ทุกครั้ง** และการกินเลขเพิ่มคือพฤติกรรมที่ถูกต้อง
//    ⇒ ปุ่มออกใบแจ้งหนี้ต้องมี confirm ก่อนเสมอ (ต่างจากใบเสร็จที่กดซ้ำได้ไม่เสียหาย)

/**
 * ชนิดเอกสาร — ตรงกับ `DOC_TYPE_*` ใน `backend/services/finance/constants.py`
 *
 * 💰 [F4] `'deposit'` = **ใบรับเงินล่วงหน้า** (`DEP-2569-0001`) — หลักฐานการรับเงิน
 *    ก้อนที่ยังไม่มีบิลรองรับ
 * ⚠️ `'deposit'` **ไม่นับเป็นใบเสร็จ** (ดู `ReceiptList.vue` ที่นับ `receiptCount`) —
 *    คนละชนิดเอกสารกัน · แต่**ต้อง**นับเป็น "เอกสารที่รับเงินแล้ว" ทุกที่ที่เทมเพลต
 *    หรือหน้าจอ branch ด้วย `is_receipt` (ไม่งั้นจะถูกพิมพ์ด้วยถ้อยคำใบแจ้งหนี้:
 *    "เรียกเก็บจาก" / "ยอดค้างชำระ" ซึ่งผิดทั้งใบ)
 *
 * 🆕 [F6] สองชนิดที่ออกให้ **รายการที่บันทึกเอง** (`POST /finance/transactions`):
 *    • `'income'` = **ใบรับเงิน** (`INC-2569-0001`) — เงินเข้าห้องที่ไม่มีบิลรองรับ
 *      ⇒ เป็น "หลักฐานว่ารับเงินมาแล้ว" เหมือน `receipt`/`deposit` (นับใน `is_receipt`)
 *    • `'payment_voucher'` = **ใบสำคัญจ่าย** (`PV-2569-0001`) — เอกสาร **สั่งจ่าย**
 *      ตามรายจ่ายที่บันทึก ⇒ 🔴 **ไม่ใช่ใบเสร็จ** ทั้งในเทมเพลตและบนหน้าจอ
 *      (หน้าจอต้องมีสาขาของตัวเอง — ถ้าปล่อยให้ตกไปสาขาใบแจ้งหนี้จะพิมพ์
 *      "เรียกเก็บจาก"/"ยอดค้างชำระ" ซึ่งกลับความหมายทั้งใบ)
 */
export type ReceiptDocType = 'receipt' | 'invoice' | 'deposit' | 'income' | 'payment_voucher';

/** ช่องทางจ่ายเงินของกระเป๋า — ตรงกับ `chk_finance_account_kind` ฝั่ง backend */
export type AccountKind = 'cash' | 'transfer';

/**
 * 🧾 หนึ่งช่วงงบประมาณที่ **ครอบวันของรายการนั้น** (snapshot ณ วันออกใบสำคัญจ่าย)
 *
 * 🔴 snapshot ไม่ใช่การ JOIN สด: แก้/ลบงบทีหลังต้องไม่เปลี่ยนกระดาษที่พิมพ์แจกไปแล้ว
 * ⚠️ งบซ้อนช่วงกันได้จริง (unique index คือ `(room_id, category_id, start_date, end_date)`
 *    เท่านั้น) ⇒ ลิสต์นี้ยาวเกิน 1 ได้ และยอดอาจถูกนับซ้ำในการสรุปรวม
 */
export interface VoucherBudget {
  id: number;
  amount: number;
  /** ISO `YYYY-MM-DD` (inclusive) */
  start_date: string;
  end_date: string;
  period_type: string;
}

/**
 * 📋 หนึ่งบรรทัดในตารางแจกแจงของใบแจ้งหนี้ **ยอดค้างรวมต่อคน**
 *
 * 🔴 นี่คือ **snapshot ณ วันออกเอกสาร** ไม่ใช่ยอดปัจจุบัน — backend เก็บไว้ใน
 *    `finance_receipts.line_items` แล้วอ่านกลับมาตรง ๆ ⇒ ใบที่พิมพ์ซ้ำหลังนักเรียน
 *    จ่ายบางส่วนจะได้บรรทัดเดิมเป๊ะ และ `sum(line_items) === amount` เสมอ
 *    ⛔ ห้ามคำนวณบรรทัดเหล่านี้ใหม่จากยอดค้างปัจจุบันที่หน้าจอ
 */
export interface ReceiptLineItem {
  title: string | null;
  amount: number;
  /** ISO `YYYY-MM-DD` — จัดรูปเป็นไทยด้วย `formatThaiDate` ที่เดียวกับวันที่อื่นในระบบ */
  due_date: string | null;
}

export interface Receipt {
  id: number;
  /** เลขที่เอกสารรูป `REC-2569-0042` / `INV-2569-0007` (ฝั่ง backend บังคับ pattern นี้ใน path param) */
  receipt_no: string;
  doc_type: ReceiptDocType;
  /** ฉลากไทย เช่น "ใบเสร็จรับเงิน" — มาจาก backend ที่เดียว อย่าเขียนซ้ำที่หน้าจอ */
  doc_type_label: string | null;
  /**
   * 🧾 เอกสารนี้พูดด้วยถ้อยคำของ **ใบเสร็จ** (เงินเข้ามือแล้ว) หรือ **ใบแจ้งหนี้** (ยังไม่ได้รับ)?
   *
   * 🔴 **ห้ามคำนวณเองที่หน้าจอจาก `doc_type`** — ใช้ฟิลด์นี้เท่านั้น
   *    backend คิดจาก `RECEIPT_LIKE_DOC_TYPES` ตัวเดียวกับที่เทมเพลต PDF ใช้พิมพ์กระดาษ
   *    ⇒ จอกับกระดาษตอบคำถามนี้ไม่ตรงกันไม่ได้
   *    (`payment_voucher` เป็น `false` โดยเจตนา — ใบสั่งจ่ายไม่ใช่หลักฐานว่ารับเงิน)
   */
  is_receipt: boolean;
  /** ปี พ.ศ. ของ **เหตุการณ์รับเงิน** (ไม่ใช่ปีที่กดพิมพ์) — คิดตามเวลาไทย */
  year_be: number;
  seq: number;
  student_payment_id: number | null;
  /** `finance_transactions.id` ของ "งวดรับเงิน" ที่เอกสารนี้ผูกอยู่ (null = บิลยุคก่อน dual-write) */
  legacy_transaction_id: number | null;
  student_id: number | null;
  collection_id: number | null;
  /** ยอดที่ออกเอกสาร **ครั้งนี้** — ไม่ใช่ยอดสะสมของบิล (ผลัดจ่าย 500/500 → ได้ 2 ใบ ใบละ 500) */
  amount: number;
  /** คำอ่านจำนวนเงินเป็นตัวอักษรไทย เช่น "หนึ่งพันบาทถ้วน" — backend เป็นคนคิด */
  amount_text: string | null;
  /** ยอดสะสมที่ชำระแล้ว ณ วันเวลาที่ออกเอกสาร */
  paid_total_after: number;
  /** snapshot ชื่อผู้ชำระ — ชื่อที่แก้ทีหลังต้องไม่ย้อนไปเปลี่ยนประวัติ */
  issued_to_name: string | null;
  issued_by_name: string | null;
  note: string | null;
  /**
   * tz-aware ISO เสมอ — Pydantic v2 เขียน UTC เป็น `Z` ไม่ใช่ `+00:00`
   * ⚠️ ถ้าวันไหนหลุดเป็น naive ให้ถือเป็นบั๊ก: JS จะตีความเป็นเวลา **ของเบราว์เซอร์**
   *    แล้วครูในไทยเห็นเวลาคลาดเคลื่อน 7 ชั่วโมง (มีเทสต์กันไว้ฝั่ง backend)
   */
  issued_at: string | null;
  /**
   * 📋 ตารางแจกแจงรายโครงการ — มีค่าเฉพาะใบแจ้งหนี้ **ยอดค้างรวมต่อคน** เท่านั้น
   *
   * `null` = เอกสารใบเดียวต่อหนึ่งบิล (ใบเสร็จทุกใบ + ใบแจ้งหนี้แบบเก่า)
   * ⚠️ ใน **ทะเบียนเอกสาร** (`getReceipts`) ค่านี้เป็น `null` เสมอโดยเจตนา — คิวรีนั้น
   *    ไม่ดึง jsonb มาด้วยเพราะโหลดได้ถึง 500 แถว ⇒ อย่าตีความว่า "ใบนี้ไม่มีตาราง"
   *    ให้เปิดหน้ารายละเอียด (`getReceipt`) จึงจะเห็นค่าจริง
   */
  line_items: ReceiptLineItem[] | null;
  /**
   * 📚 [F5] ชุดเอกสารที่ใบนี้สังกัด (`null` = ไม่ได้จัดกลุ่ม)
   *
   * ⚠️ อยู่บน `Receipt` (ไม่ใช่ `ReceiptListItem`) โดยเจตนา — คำตอบหลัง **ออกเอกสาร**
   *    ต้องบอกได้ว่าออกรอบนี้ได้ชุดไหน ผู้ใช้จะได้โหลดรวม PDF ต่อได้ทันที
   */
  batch_id: number | null;
}

/**
 * 📚 [F5] ข้อมูลชุดที่แนบมากับ **แถวในทะเบียน** (3 ฟิลด์นี้ `null` เมื่อใบนั้นไม่อยู่ในชุด)
 *
 * 🔴 `batch_size` = สมาชิก **ทั้งชุด** ไม่ใช่จำนวนที่รอดตัวกรอง ⇒ ต้องแสดงคู่กับความยาว
 *    ของกลุ่มเสมอ ("แสดง 3 จาก 20 ใบ") ไม่งั้นผู้ใช้จะอ่านว่า "ชุดนี้มี 3 ใบ" แล้วโหลด
 *    PDF ขาดไป 17 ใบโดยไม่มีอะไรฟ้อง
 *    ⛔ ห้ามคำนวณ `batch_size` เองที่หน้าจอจากความยาวของกลุ่มที่กรองแล้ว
 */
export interface ReceiptBatchFields {
  /** ชื่อที่ผู้ใช้ตั้งไว้ — `null` = ให้หน้าจอประกอบชื่อเอง (ดู `utils/receiptGroups`) */
  batch_title: string | null;
  batch_size: number | null;
  /** จำนวนสมาชิกที่ถูกยกเลิก/ลบ — ยังนับอยู่ใน `batch_size` */
  batch_voided_count: number | null;
}

/** แถวในหน้ารายการ — backend แนบชื่อแคมเปญ/เลขที่นักเรียนมาให้ตารางแสดงได้โดยไม่ต้องยิงเพิ่ม */
export interface ReceiptListItem extends Receipt, ReceiptBatchFields {
  collection_title: string | null;
  student_no: number | null;
}

/**
 * 🧾 [F6] ข้อมูลเฉพาะของ **ใบสำคัญจ่าย** — ทั้งชุดเป็น `null` สำหรับเอกสารชนิดอื่น
 *
 * 🔴 อยู่บน `ReceiptDetail` (ไม่ใช่ `ReceiptListItem`) ด้วยเหตุผลเดียวกับ `line_items`:
 *    ทะเบียนโหลดได้ถึง 500 แถวและ **ไม่ดึง `voucher_snapshot` (jsonb) มาด้วย**
 *    ⇒ `null` ในทะเบียนแปลว่า "ไม่มีข้อมูล" ไม่ได้แปลว่า "ใบนี้ไม่ใช่ใบสำคัญจ่าย"
 *    ให้เปิดหน้ารายละเอียดก่อนตัดสินใจ
 *
 * ⚠️ ทุกค่าเป็น **snapshot ณ วันออกเอกสาร** — เปลี่ยนชื่อหมวด/แก้เลขบัญชี/แก้งบทีหลัง
 *    ต้องไม่ย้อนไปเปลี่ยนกระดาษที่พิมพ์แจกไปแล้ว
 */
export interface VoucherFields {
  /** ผู้อนุมัติ — ไม่บังคับ (แล้วแต่ตกลงกันในห้อง) ⇒ `null` = ไม่มีช่องให้เซ็น */
  approver_name: string | null;
  /** จำนวนเอกสารแนบ (บิลเงินสด/ใบเสร็จจากร้านค้า) — `0` = ไม่ได้แนบ */
  attachment_count: number;
  /** ชื่อกระเป๋าที่จ่ายออก เช่น "🪙 กระเป๋าเงินสด" */
  account_name: string | null;
  account_kind: AccountKind | null;
  /** สามตัวนี้มีค่าเฉพาะ `account_kind === 'transfer'` */
  bank_name: string | null;
  bank_account_no: string | null;
  bank_account_name: string | null;
  /** หมวดหมู่งบประมาณของรายการนี้ (F2) */
  category_name: string | null;
  /**
   * งบที่ครอบวันของรายการ — **ลิสต์ว่าง = "ไม่อยู่ในงบประมาณที่ตั้งไว้"**
   * ⚠️ อย่าแสดงช่องว่างเมื่อลิสต์ว่าง: "ไม่มีงบ" ต่างจาก "ยังไม่ได้ตั้งงบ"
   */
  budgets: VoucherBudget[];
}

/** หน้ารายละเอียด — ได้ข้อมูลระดับแคมเปญ/ห้องเพิ่ม สำหรับหัวเอกสารบนหน้าจอ */
export interface ReceiptDetail extends ReceiptListItem, VoucherFields {
  collection_amount: number | null;
  collection_due_date: string | null;
  room_name: string | null;
  room_code: string | null;
}

export interface ReceiptIssuePayload {
  payment_id: number;
  /**
   * ไม่ส่ง = ใช่งวดรับเงิน **ล่าสุด** ของบิลนั้น
   * ส่ง = ระบุ "งวด" ที่ต้องการออกเอกสาร (`finance_transactions.id` ของงวดนั้น)
   */
  transaction_id?: number;
  doc_type: ReceiptDocType;
  note?: string;
  user_name?: string;
}

/** ตัวกรองของ `getReceipts` — ทุกตัวเป็น optional ฝั่ง backend */
export interface ReceiptQueryParams {
  /** ช่วงวันที่กรองตาม **วันตามปฏิทินไทย** ไม่ใช่ UTC (บิลช่วง 17:00–24:00 UTC ตกเป็นวันรุ่งขึ้นของไทย) */
  startDate?: string;
  endDate?: string;
  docType?: ReceiptDocType;
  studentId?: number;
}

export interface ReceiptBatchIssuePayload {
  /** 1–100 ใบต่อครั้ง — เกินกว่านี้ backend ตอบ 422 */
  payment_ids: number[];
  doc_type: ReceiptDocType;
  note?: string;
  user_name?: string;
}

export interface ReceiptIssueResult {
  status: string;
  message: string | null;
  receipt: Receipt;
  /** `true` = คืนใบเดิมที่มีอยู่แล้ว ไม่ได้ออกใหม่ (ไม่ใช่ error) */
  reused: boolean;
}

export interface ReceiptBatchIssueResult {
  status: string;
  message: string | null;
  receipts: Receipt[];
  issued_count: number;
  reused_count: number;
}

/**
 * ✍️ ออกใบแจ้งหนี้ "ยอดค้างรวมต่อคน" ให้กลุ่มนักเรียนที่เลือก — 1 คน = 1 ใบ
 *
 * 🎯 เลือก **"คน"** ไม่ใช่ "บิล": ยอดบนใบคือยอดค้างรวมทุกบิลที่ยัง pending ของคนนั้น
 *    ⇒ ไม่มี `payment_id` ในเพย์โหลดนี้โดยเจตนา
 */
export interface ReceiptInvoiceIssuePayload {
  /** 1–100 คนต่อครั้ง — เกินกว่านี้ backend ตอบ 422 */
  student_ids: number[];
  note?: string;
  user_name?: string;
}

/** ✍️ ออกใบแจ้งหนี้ให้ **ทุกคนที่มียอดค้าง** ในห้อง — ไม่ส่งรายชื่อไป (ระบบหาเอง) */
export interface ReceiptRoomInvoicePayload {
  note?: string;
  user_name?: string;
}

/** คนที่ถูก **ข้าม** ในการออกทั้งห้อง พร้อมเหตุผล — ผู้ใช้ต้องรู้ว่าทำไมได้ไม่ครบ */
export interface InvoiceSkipItem {
  student_id: number;
  student_no: number | null;
  student_name: string | null;
  reason: string;
}

export interface InvoiceBatchIssueResult {
  status: string;
  message: string | null;
  receipts: Receipt[];
  /** = `receipts.length` — **ไม่นับ** คนที่ถูกข้าม (คนละความหมายกับ `skipped`) */
  issued_count: number;
  skipped: InvoiceSkipItem[];
}

// ══════════════════════════════════════════════════════════════════════════════
// 📚 [F5] ชุดเอกสาร (Document Batch)
// ══════════════════════════════════════════════════════════════════════════════
// 🔑 "ชุด" ไม่ใช่เอกสารทางบัญชี — **ไม่มีเลขรันของตัวเองและไม่กินเลขเอกสาร**
//    ⇒ ยุบชุด/ย้ายใบเข้าชุด ไม่แตะ `receipt_no` `amount` หรือ `status` ของใบเลย
//
// ⚠️ `source` บอก "ใครสร้างชุดนี้" ไม่ใช่ "ใครแก้ล่าสุด" และ **ผู้ใช้แก้ไม่ได้**
//    (PATCH ไม่รับฟิลด์นี้) ⇒ ใช้เพื่ออธิบายที่มาบนหน้าจอเท่านั้น
// ══════════════════════════════════════════════════════════════════════════════

/** ที่มาของชุด — ตรงกับ `BATCH_SOURCE_*` ฝั่ง backend */
export type ReceiptBatchSource = 'auto' | 'manual' | 'room';

export interface ReceiptBatch {
  id: number;
  room_id: number;
  /** ชื่อที่ผู้ใช้ตั้ง — `null` = ให้หน้าจอประกอบชื่อเอง (ห้ามตีความเป็น "ไม่มีชื่อ") */
  title: string | null;
  source: ReceiptBatchSource;
  note: string | null;
  created_by: number | null;
  created_by_name: string | null;
  /** สมาชิกที่ยัง `active` — ตัวที่ `total_amount` นับด้วย */
  active_count: number;
  /** สมาชิกที่ถูกยกเลิก/ลบ (ยังนับอยู่ใน `batch_size`) */
  voided_count: number;
  /** = `active_count + voided_count` — ขนาด **ทั้งชุด** ไม่ขึ้นกับตัวกรองใด ๆ */
  batch_size: number;
  /** ยอดรวม **เฉพาะใบที่ยัง active** (ใบที่ถูกยกเลิกไม่ใช่เงินแล้ว) */
  total_amount: number;
  /** ช่วงวันที่ของเอกสาร (= วันที่ที่พิมพ์บนกระดาษ) — `null` เมื่อชุดว่าง */
  first_doc_at: string | null;
  last_doc_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

/** ชุด + เอกสารทุกใบในชุด — **รวมใบที่ถูกยกเลิก** เพื่อให้ตัวเลขตรงกับ `voided_count` */
export interface ReceiptBatchDetail {
  batch: ReceiptBatch;
  receipts: ReceiptDetail[];
}

/** 📥 สร้างชุดจากเลขที่เอกสารที่ติ๊กเลือก (1–100 ใบ — เกินกว่านี้ backend ตอบ 400) */
export interface ReceiptBatchCreatePayload {
  /** ⚠️ ส่งใน **body** เท่านั้น — ห้ามย้ายไป query string (กับดัก axios `key[]=`) */
  receipt_nos: string[];
  title?: string;
  note?: string;
  user_name?: string;
}

export interface ReceiptBatchMutationResult {
  batch: ReceiptBatch;
  /**
   * 🔁 `false` = มีชุดที่สมาชิกชุดเดียวกันอยู่แล้ว ระบบคืนชุดเดิมให้ (ไม่ใช่ error)
   *    ⇒ หน้าจอไม่ควรขึ้น "สร้างสำเร็จ" — ควรบอกว่ามีชุดนี้อยู่แล้ว
   */
  created: boolean;
}

/** 📥 **ตั้งสมาชิกทั้งชุด** (ไม่ใช่ "เพิ่มเข้า") — ใบที่หายจากลิสต์จะถูกถอดออกจากชุด */
export interface ReceiptBatchSetReceiptsPayload {
  receipt_nos: string[];
}

/**
 * 📥 แก้ชื่อ/โน้ต — ส่งมาแค่ฟิลด์ที่จะแก้
 *
 * ⚠️ ส่ง `title: null` = **ล้างชื่อ** (กลับไปใช้ชื่อที่หน้าจอประกอบ) ต่างจาก "ไม่ส่งมา"
 *    ⇒ ต้องส่ง `null` ให้ชัดเจน ไม่ใช่ `undefined` (axios ตัด `undefined` ออกจาก body)
 */
export interface ReceiptBatchUpdatePayload {
  title?: string | null;
  note?: string | null;
}

export interface ReceiptBatchDissolveResult {
  batch_id: number;
  /** จำนวนใบที่ถูกปลดออกจากชุด — **เอกสารไม่ถูกแตะ** (ยัง active, เลขที่/ยอดเดิม) */
  detached_count: number;
}

// ══════════════════════════════════════════════════════════════════════════════
// 💰 [F4] เงินรับล่วงหน้า — เครดิตคงเหลือรายนักเรียน
// ══════════════════════════════════════════════════════════════════════════════
// 🔑 แนวคิดที่ต้องเข้าใจก่อนแตะหน้าจอพวกนี้ (ตรงกับ `backend/services/finance/credits.py`):
//
//    เติมเครดิต (top-up)  = รับเงินก้อนเข้ามาพัก  → Dr สินทรัพย์ / Cr **หนี้สิน**
//                           ⇒ ⚠️ **ยังไม่ใช่รายได้** ของห้อง
//    หักเครดิต (apply)    = เอาเงินพักไปปิดบิล    → Dr หนี้สิน / Cr รายได้
//                           ⇒ รายได้เกิด **ตรงนี้** จังหวะเดียว
//
// ⇒ หน้าจอต้องไม่พูดว่า "รายได้" ตอนเติมเงิน และต้องไม่พูดว่า "จ่ายเงิน" ตอนหักเครดิต
//    (เงินเข้ามาตั้งแต่ตอนเติมแล้ว — ตอนหักไม่มีเงินเคลื่อนไหวเลย)
//
// ⚙️ กติกาที่ล็อกไว้ (ผู้ใช้เลือก): **ระบบเสนอ → ครูยืนยัน** ไม่หักเองเงียบ ๆ
//    ⇒ ต้องมีขั้น "ดูข้อเสนอ" (`CreditApplyPlan`) คั่นก่อน `applyCredit` เสมอ
//    และข้อเสนอต้องมาจาก `getCreditPlan` ตัวเดียวกับที่ `applyCredit` ใช้จริง
// ══════════════════════════════════════════════════════════════════════════════

/** ประเภทของแถวในบัญชีเครดิต (append-only) — ตรงกับ `CREDIT_ENTRY_*` ฝั่ง backend */
export type CreditEntryType = 'topup' | 'apply' | 'reverse';

/** แถวในหน้า "เงินรับล่วงหน้า" — นักเรียนทุกคนในห้อง (คนไม่มีเครดิตก็อยู่ ยอด 0) */
export interface StudentCreditBalance {
  student_id: number;
  student_no: number;
  student_name: string;
  /** เครดิตคงเหลือปัจจุบัน = `balance_after` ของแถวล่าสุด */
  credit_balance: number;
  /** ยอดค้างดิบ (ยังไม่หักเครดิต) */
  total_pending_amount: number;
  /** ยอดที่ต้องเก็บจริงหลังหักเครดิต — ใช้ตัวนี้เป็นตัวเลขหลักบนจอ */
  net_pending_amount: number;
}

/** 1 แถวในประวัติเครดิตของนักเรียน */
export interface StudentCreditEntry {
  id: number;
  entry_type: CreditEntryType;
  /** ฉลากไทย เช่น "เติมเงินล่วงหน้า" — มาจาก backend ที่เดียว อย่าเขียนซ้ำที่หน้าจอ */
  entry_type_label: string | null;
  /** บวกเสมอ — ทิศทางมาจาก `entry_type` */
  amount: number;
  /** ยอดคงเหลือ **หลัง** รายการนี้ (snapshot ไม่ใช่ผลรวม) */
  balance_after: number;
  finance_transaction_id: number | null;
  student_payment_id: number | null;
  collection_id: number | null;
  note: string | null;
  recorded_by: string | null;
  /** ISO 8601 (มี timezone) — backend ส่ง timestamptz มาจากตารางที่ใช้ `WITH TIME ZONE` */
  created_at: string | null;
  /** เลขใบรับเงินล่วงหน้า (DEP-…) ที่ผูกกับรายการเติมนี้ — `null` สำหรับรายการหัก */
  receipt_no: string | null;
  receipt_event_at: string | null;
  /** ชื่อบิล/แคมเปญที่รายการหักนี้ไปปิด */
  collection_title: string | null;
}

/** บิลที่ยังค้างของนักเรียน 1 คน (ยอดดิบ ยังไม่หักเครดิต) */
export interface CreditOpenBill {
  payment_id: number;
  collection_id: number;
  title: string | null;
  due_date: string | null;
  total_amount: number;
  paid_amount: number;
  remaining_amount: number;
}

/** หนึ่งบิลที่จะถูกหัก (หรือถูกหักไปแล้ว) — บรรทัดในข้อเสนอการหัก */
export interface CreditAllocationItem {
  payment_id: number;
  collection_id: number;
  title: string | null;
  due_date: string | null;
  bill_total: number;
  bill_paid_before: number;
  bill_remaining_before: number;
  /** ยอดที่เครดิตจะจ่ายให้บิลนี้ในรอบนี้ */
  apply_amount: number;
  bill_paid_after: number;
  bill_status_after: string;
  /** เครดิตที่ยังเหลือหลังจ่ายบิลนี้ */
  remaining_after: number;
}

/**
 * ข้อเสนอการหักของนักเรียน 1 คน
 * ⚠️ ชนิดเดียวกันนี้ถูกใช้ **ทั้งตอนดูตัวอย่างและตอนลงมือ** โดยเจตนา — สิ่งที่ครูเห็น
 *    ก่อนกดกับสิ่งที่ระบบทำต้องเป็นตัวเลขชุดเดียวกันเป๊ะ
 */
export interface CreditPlanItem {
  student_id: number;
  student_no: number | null;
  student_name: string | null;
  balance_before: number;
  allocations: CreditAllocationItem[];
  total_applied: number;
  balance_after: number;
}

/** คำตอบของทั้ง `GET …/credits/plan` และ `POST …/credits/apply` */
export interface CreditApplyPlan {
  status: string;
  message: string | null;
  items: CreditPlanItem[];
  total_applied: number;
  total_balance_after: number;
  /** จำนวนบิลที่ถูกปิด (มีค่าเฉพาะตอน apply จริง) */
  bills_paid?: number | null;
}

/** รายละเอียดเครดิตของนักเรียน 1 คน (หน้าประวัติ) */
export interface StudentCreditDetail {
  student_id: number;
  student_no: number;
  student_name: string;
  credit_balance: number;
  /** เรียงใหม่ → เก่า (แถวล่าสุดอยู่บน) */
  entries: StudentCreditEntry[];
  open_bills: CreditOpenBill[];
  plan: CreditPlanItem;
}

export interface CreditTopUpRequest {
  student_id: number;
  amount: number;
  /** กระเป๋าที่เงินเข้าจริง — ต้องเลือกเสมอ (ขา Dr ของ journal) */
  paid_to_account_id: number;
  slip_image_url?: string | null;
  note?: string | null;
  user_name?: string | null;
  /**
   * 🔑 รหัสกันบันทึกซ้ำ **บังคับ** (8–64 ตัวอักษร) — สร้างใหม่ต่อการกดหนึ่งครั้ง
   * ⚠️ ห้ามสร้างใหม่ตอน retry ไม่งั้นจะได้เครดิตสองรอบจากการกดครั้งเดียว
   *    (สร้างด้วย `newIdempotencyKey()` ใน `utils/money.ts` แล้วเก็บไว้ทั้งรอบการกด)
   */
  idempotency_key: string;
}

export interface CreditTopUpResponse {
  status: string;
  message: string | null;
  credit_entry_id: number;
  student_id: number;
  student_name: string;
  amount: number;
  balance_after: number;
  finance_transaction_id: number | null;
  journal_entry_id: string | null;
  /** ใบรับเงินล่วงหน้า (DEP) ที่ออกให้ทันที — เป็นหลักฐานเดียวของรายการนี้ */
  receipt: Receipt | null;
  /** `true` = ใบ DEP ใบเดิมถูกนำกลับมาใช้ (ไม่กินเลขใหม่) */
  receipt_reused: boolean;
  /** `true` = ทั้งรายการถูกกันซ้ำ (idempotency key เดิม) ไม่ได้เติมเงินรอบสอง */
  reused: boolean;
}

export interface CreditApplyRequest {
  /** 1–100 คน — ทั้งชุด all-or-nothing */
  student_ids: number[];
  user_name?: string | null;
}

export interface CreditUndoRequest {
  credit_entry_id: number;
  reason?: string | null;
  user_name?: string | null;
}

/**
 * ⚠️ ไม่ใช่ `StudentCreditEntry`: การยกเลิก **สร้างแถวใหม่** (reverse) และ **ลบแถวเดิม**
 * ⇒ คำตอบอธิบาย "ผลลัพธ์ที่เกิดขึ้น" ไม่ใช่รูปร่างของแถวใดแถวหนึ่ง
 */
export interface CreditUndoResponse {
  status: string;
  message: string | null;
  credit_entry_id: number;
  reverse_entry_id: number;
  student_id: number;
  student_payment_id: number | null;
  reverted_amount: number;
  bill_paid_amount: number;
  bill_status: string;
  credit_balance_after: number;
}

// ════════════════════════════════════════════════════════════════════════════
// ⚖️ [P5] ค่าปรับ — ประเภทความผิด · บิลค่าปรับ · คำขอยกเว้น · คำขอคืนเงิน
// ════════════════════════════════════════════════════════════════════════════
// 🔑 การอ่าน (list/detail/summary/aging) เปิดให้สมาชิกห้อง — backend กรองให้
//    นักเรียนเห็นเฉพาะของตัวเองอยู่แล้ว ⇒ หน้าจอไม่ต้องซ่อนข้อมูลเอง
// ✍️ การเขียน (ออก/แก้/ยกเลิก/ขอยกเว้น/ขอคืนเงิน/อนุมัติ) ต้อง `MANAGE_FINANCE`
//    ⇒ gate ปุ่มด้วย `canManageFinance` **ไม่ใช่ `isAdmin`** (ดูบทเรียนใน services/finance.ts)

/** ประเภทความผิดของห้อง — `default_amount` = อัตราเริ่มต้น, `default_due_days` = กี่วันให้ชำระ */
export interface FineType {
  id: number;
  name: string;
  default_amount: number;
  default_due_days: number;
  description: string | null;
  is_active: boolean;
  sort_order: number;
}

export interface FineTypeCreate {
  name: string;
  default_amount?: number;
  default_due_days?: number;
  description?: string | null;
  sort_order?: number;
}

/** PATCH — ส่งเฉพาะฟิลด์ที่จะแก้ (backend ใช้ `exclude_unset`) */
export interface FineTypeUpdate {
  name?: string;
  default_amount?: number;
  default_due_days?: number;
  description?: string | null;
  sort_order?: number;
  is_active?: boolean;
}

/** สถานะค่าปรับ — ค่าดิบจาก DB (แปลไทยด้วย `FINE_STATUS_LABELS`) */
export type FineStatus = 'issued' | 'partially_paid' | 'paid' | 'waived' | 'cancelled' | 'refunded';

/** 1 ค่าปรับ = 1 บิล (`student_payment_id`) = 1 ใบ INV- */
export interface Fine {
  id: number;
  room_id: number;
  batch_id: number | null;
  fine_type_id: number | null;
  /** snapshot ชื่อประเภท ณ ตอนออก — ประเภทถูกลบทีหลังก็ยังแสดงชื่อเดิมได้ */
  fine_type_name: string;
  student_id: number;
  student_no: number | null;
  student_name: string | null;
  /** โปรเจกต์เก็บเงินซ่อนที่ค่าปรับสร้างขึ้น — หน้าจอไม่ควรลิงก์ไปหน้านี้ */
  hidden_collection_id: number | null;
  student_payment_id: number;
  invoice_receipt_id: number | null;
  invoice_no: string | null;
  incident_date: string;
  due_date: string;
  reason: string;
  original_amount: number;
  /** ยอดปัจจุบัน (อาจถูกแก้/ยกเว้นจาก `original_amount`) */
  amount: number;
  waived_amount: number;
  refunded_amount: number;
  paid_amount: number;
  /** ยอดคงเหลือ = `amount - paid_amount` (0 เมื่อยกเลิก/ชำระครบ) */
  outstanding: number;
  status: string;
  evidence_url: string | null;
  note: string | null;
  created_by: number | null;
  created_at: string | null;
  collection_kind: string;
}

export interface FineBatch {
  id: number;
  fine_type_id: number | null;
  fine_type_name: string;
  incident_date: string;
  due_date: string;
  reason: string;
  amount_per_student: number;
  student_count: number;
  total_amount: number;
}

/** ออกค่าปรับหลายคนในครั้งเดียว — `students[].amount` ไม่ใส่ = ใช้ `default_amount` */
export interface FineIssueStudent {
  student_id: number;
  amount?: number;
}

export interface FineIssueRequest {
  fine_type_id: number;
  students: FineIssueStudent[];
  incident_date: string;
  due_date?: string | null;
  reason: string;
  evidence_url?: string | null;
  note?: string | null;
  /** 🔑 8–64 ตัวอักษร · สร้างด้วย `newIdempotencyKey()` และคงเดิมทั้งรอบการกด */
  idempotency_key: string;
  user_name?: string | null;
}

export interface FineIssueResponse {
  batch: FineBatch;
  fines: Fine[];
  totals: Record<string, number>;
  invoice_nos: string[];
  /** `true` = idempotency key เดิม → คืนผลเดิม ไม่ได้ออกซ้ำ */
  reused: boolean;
}

export interface FineListResponse {
  fines: Fine[];
  total: number;
}

export interface FineUpdateRequest {
  amount?: number;
  incident_date?: string;
  due_date?: string;
  reason?: string;
  evidence_url?: string | null;
  note?: string | null;
  user_name?: string | null;
}

export interface FineCancelRequest {
  reason?: string | null;
  user_name?: string | null;
}

/** หมวดเหตผลยกเว้น — `discount` = ส่วนลด (contra-revenue), `uncollectible` = หนี้สูญ (ค่าใช้จ่าย) */
export type WaiverReasonCategory = 'discount' | 'uncollectible';

export interface FineWaiver {
  id: number;
  room_id: number;
  fine_id: number;
  amount: number;
  reason_category: string;
  reason: string;
  status: string;
  requested_by: number | null;
  requested_at: string | null;
  decided_by: number | null;
  decided_at: string | null;
  decision_note: string | null;
}

export interface FineWaiverCreate {
  amount: number;
  reason_category: WaiverReasonCategory;
  reason: string;
  user_name?: string | null;
}

export interface FineWaiverDecision {
  note?: string | null;
  user_name?: string | null;
}

export interface FineWaiverListResponse {
  waivers: FineWaiver[];
  total: number;
}

/** ผลตอบกลับของ request/approve/reject/cancel คำขอยกเว้น — ใช้ `waiver` เสมอ (ยกเว้นตอนสร้าง) */
export interface FineWaiverActionResponse {
  status: string;
  message: string | null;
  waiver?: FineWaiver;
  id?: number;
}

export interface FineRefund {
  id: number;
  room_id: number;
  fine_id: number;
  account_id: number;
  amount: number;
  reason: string;
  status: string;
  requested_by: number | null;
  requested_at: string | null;
  decided_by: number | null;
  decided_at: string | null;
  decision_note: string | null;
  transaction_id: number | null;
  document_id: number | null;
}

export interface FineRefundCreate {
  account_id: number;
  amount: number;
  reason: string;
  user_name?: string | null;
}

export interface FineRefundDecision {
  note?: string | null;
  user_name?: string | null;
}

export interface FineRefundListResponse {
  refunds: FineRefund[];
  total: number;
}

/** ผลตอบกลับคำขอคืนเงิน — ตอนอนุมัติมี `receipt_no` (PV-) กลับมาด้วย */
export interface FineRefundActionResponse {
  status: string;
  message: string | null;
  refund?: FineRefund;
  id?: number;
  receipt_no?: string | null;
}

/** รายละเอียดค่าปรับ = ค่าปรับ + คำขอยกเว้น/คืนเงินทั้งหมดของใบนั้น */
export interface FineDetail extends Fine {
  waivers: FineWaiver[];
  refunds: FineRefund[];
}

export interface FineListQuery {
  status?: string;
  student_id?: number;
  fine_type_id?: number;
  batch_id?: number;
  from_date?: string;
  to_date?: string;
  search?: string;
  limit?: number;
  offset?: number;
}

// ──────────────────────────── 📊 รายงานอายุหนี้ (aging)

export type AgingBucketKey = 'no_due' | 'not_due' | '1_30' | '31_60' | '61_90' | 'over_90';

export interface AgingBucket {
  bucket: string;
  label: string;
  count: number;
  amount: number;
  project_amount: number;
  fine_amount: number;
}

export interface AgingRow {
  payment_id: number;
  student_id: number;
  student_no: number | null;
  student_name: string;
  collection_id: number;
  collection_title: string;
  collection_kind: string;
  /** มีค่าเมื่อบิลนี้เป็นค่าปรับ — ใช้ลิงก์ไป `/finance/fines/{fine_id}` */
  fine_id: number | null;
  due_date: string | null;
  outstanding: number;
  overdue_days: number;
  bucket: string;
  bucket_label: string;
}

export interface AgingResponse {
  as_of: string;
  project_total: number;
  fine_total: number;
  grand_total: number;
  buckets: AgingBucket[];
  rows: AgingRow[];
}

// ──────────────────────────── ⚖️ สรุปรายการค่าปรับ (แดชบอร์ด)

/** `totals` เป็น Dict ฝั่ง backend — ประกาศเป็น interface แบนเพื่อให้ type-check จับชื่อฟิลด์ได้ */
export interface FineSummaryTotals {
  count: number;
  original_total: number;
  outstanding_total: number;
  paid_total: number;
  waived_total: number;
  refunded_total: number;
  overdue_count: number;
  overdue_amount: number;
  due_soon_count: number;
  due_soon_amount: number;
}

export interface FineSummaryStatusRow {
  status: string;
  count: number;
  amount: number;
  outstanding: number;
}

export interface FineSummaryTypeRow {
  fine_type_name: string;
  count: number;
  amount: number;
  outstanding: number;
}

export interface FineSummaryDebtorRow {
  student_id: number;
  student_no: number | null;
  student_name: string;
  count: number;
  outstanding: number;
}

export interface FineSummary {
  as_of: string;
  totals: FineSummaryTotals;
  by_status: FineSummaryStatusRow[];
  by_type: FineSummaryTypeRow[];
  top_debtors: FineSummaryDebtorRow[];
}

// ──────────────────────────── 👥 ผู้เกี่ยวข้องทางการเงิน (FIN-V2 / P1.2)
// 🎭 ต้องตรงกับ CHECK ของ DB: chk_finance_people_roles / chk_finance_people_student_link
export type PersonType = 'student' | 'teacher' | 'external';
export type PersonRole = 'receive' | 'pay' | 'approve';

/** แถวจาก `GET /finance/people` — ชื่อเป็น snapshot ที่ครูแก้ได้ในทะเบียน */
export interface FinancePerson {
  person_id: number;
  person_type: PersonType;
  student_id: number | null;
  display_name: string;
  phone: string | null;
  roles: PersonRole[];
  is_active: boolean;
  note: string | null;
}

export interface PersonListResponse {
  people: FinancePerson[];
}

export interface PersonCreate {
  person_type: PersonType;
  student_id?: number | null;
  display_name: string;
  phone?: string | null;
  roles?: PersonRole[];
  is_active?: boolean;
  note?: string | null;
}

export type PersonUpdate = Partial<Omit<PersonCreate, 'person_type'>> & {
  person_type?: PersonType;
};

/** ผลของปุ่ม "ซิงก์รายชื่อนักเรียน" — `skipped` เผื่ออนาคต (ตอนนี้ 0) */
export interface PeopleSyncResult {
  created: number;
  updated: number;
  skipped: number;
}

/** ค่าเริ่มต้นของหน้าจอรับเงิน — GET คืนค่า default เสมอแม้ยังไม่เคยตั้งค่า */
export interface FinanceSettings {
  default_receiver_person_id: number | null;
  default_wallet_account_id: number | null;
  require_receiver: boolean;
  receipt_note: string | null;
}

export type FinanceSettingsUpdate = Partial<FinanceSettings>;

// ──────────────────────────── 👤 บัญชีรายบุคคล (FIN-V2 / P1.3 API → P1.4 UI)
// ⚠️ เงินทุกฟิลด์เป็น **string ทศนิยม 2 ตำแหน่ง** ตามสัญญา api-v2
//    ⇒ ต้อง `formatMoney(Number(x))` ก่อนแสดงผลเสมอ (ดู Gotchas ของ brief P1.4)

/** ตัวกรองสถานะของหน้า list — ตรงกับ `VALID_ACCOUNT_STATUS` ฝั่ง backend */
export type IndividualAccountStatus = 'all' | 'outstanding' | 'credit' | 'settled';

/** ประเภทเงินของบิล — `fee_collections.fund_type` (มิติรายงาน ไม่ใช่บัญชีแยก) */
export type FundType = 'room_fund' | 'pass_through';

/** บิลที่ยังเปิด (ยังค้าง) ของนักเรียน 1 ใบ — `open_bills` ใน `IndividualAccountItem` */
export interface OpenBillItem {
  student_payment_id: number;
  collection_id: number | null;
  title: string;
  amount: string;
  paid_amount: string;
  written_off_amount: string;
  outstanding: string;
  /** ISO date `YYYY-MM-DD` (ไม่ใช่ timestamp) — ใช้ `formatThaiDate` */
  due_date: string | null;
  status: string;
  collection_kind: string | null;
  fund_type: FundType | null;
}

/** เหตุการณ์รับเงินล่าสุด — ว่างได้จนถึง P2.1 (ตาราง event ยังไม่มีข้อมูลจริง) */
export interface RecentPaymentEventItem {
  event_id: number;
  /** ISO timestamp — ใช้ `formatThaiDateTime` */
  event_at: string;
  amount_received: string;
  credit_used: string;
  receiver_name: string | null;
}

/** บัญชีของนักเรียน 1 คน — รวมยอดค้าง/เครดิต/บิลเปิด/เหตุการณ์ล่าสุด */
export interface IndividualAccountItem {
  student_id: number;
  student_no: number;
  name: string;
  outstanding_total: string;
  overdue_total: string;
  upcoming_total: string;
  credit_balance: string;
  ready_to_apply: string;
  open_bills: OpenBillItem[];
  recent_events: RecentPaymentEventItem[];
}

/** รายการทั้งห้อง — `as_of` = "วันนี้" ตามเวลาไทยที่ backend ใช้ตัดสิน overdue */
export interface IndividualAccountListResponse {
  as_of: string;
  items: IndividualAccountItem[];
}

/** รายละเอียดคนเดียว — รูปร่างเดียวกับ item ใน list เพื่อใช้ component เดียว */
export type IndividualAccountDetailResponse = IndividualAccountItem;

export interface IndividualAccountQuery {
  status?: IndividualAccountStatus;
  q?: string;
  fund_type?: string;
}

/** ประเภทบรรทัดใน statement — `payment_event` ยังว่างจนถึง P2.1 */
export type StatementEntryKind =
  | 'bill'
  | 'payment'
  | 'payment_event'
  | 'credit_topup'
  | 'credit_apply'
  | 'credit_reverse';

/** บรรทัดเดินบัญชี — `amount` มีเครื่องหมายแล้ว (บิล + · รับเงิน −) */
export interface StudentStatementEntry {
  entry_id: string;
  kind: string;
  /** ISO timestamp — ใช้ `formatThaiDateTime` */
  occurred_at: string;
  description: string;
  amount: string;
  /** ยอดเครดิตคงเหลือหลังรายการ — มีเฉพาะบรรทัดเครดิต */
  balance_after: string | null;
  reference_id: number | null;
}

/** โครงเอกสารใน statement — P5.1 (registry) จะเติมข้อมูลจริง รอบนี้ `[]` เสมอ */
export interface StatementDocumentItem {
  doc_type: string;
  doc_no: string | null;
  issued_at: string | null;
  amount: string | null;
}

/** statement ตามช่วงวันที่ — เรียง `occurred_at` จากเก่าไปใหม่ */
export interface StudentStatementResponse {
  student_id: number;
  student_no: number;
  name: string;
  date_from: string | null;
  date_to: string | null;
  entries: StudentStatementEntry[];
  documents: StatementDocumentItem[];
}

export interface StudentStatementQuery {
  from?: string;
  to?: string;
}

// ──────────────────────── 💸 รับเงิน 1 ครั้ง = 1 event (FIN-V2 / P2.1 API → P2.3 UI)
// ⚠️ เงินทุกฟิลด์เป็น **string ทศนิยม 2 ตำแหน่ง** ตามสัญญา api-v2 §4
//    ⇒ `formatMoney(Number(x))` ก่อนแสดงผล · request ส่ง string เสมอ (ไม่ส่ง number)

/** แหล่งเงินของบรรทัดจัดสรร — 1 บรรทัด = 1 แหล่ง (ห้ามรวมเงินสด+เครดิตในบรรทัดเดียว) */
export type AllocationSource = 'cash' | 'credit'

/** เงินเกินหลังปิดบิล: เก็บเป็นเครดิต หรือปฏิเสธ (`none` = backend ตอบ 400) */
export type ExcessAction = 'credit' | 'none'

/** เลือกบิลที่จะปิด: `auto` = ทุกบิลเปิด · `manual` = เฉพาะ `bill_ids` */
export type BillSelection = 'auto' | 'manual'

/**
 * บรรทัดจัดสรร 1 บรรทัด — ใช้ทั้งผล preview และผล commit
 *
 * 🔴 `amount`/`bill_before`/`bill_after` เป็น string ⇒ ต้อง `Number(...)` ก่อนคำนวณ
 *    preview มีฟิลด์บริบทของบิล (`title`, `due_date`, …) มาด้วย ส่วน commit มีชุดเดียวกับ
 *    snapshot ที่เขียนลง `line_items` ⇒ ทำเป็น optional ให้ type เดียวใช้ได้ทั้งคู่
 */
export interface AllocationLine {
  student_payment_id: number;
  /** บิลบรรทัดนี้ปิด — ข้อมูลบริบทมีใน preview, ไม่มีใน commit */
  collection_id?: number | null;
  title?: string;
  collection_kind?: string | null;
  fund_type?: FundType | null;
  /** ISO date `YYYY-MM-DD` — ใช้ `formatThaiDate` */
  due_date?: string | null;
  source: AllocationSource;
  amount: string;
  bill_before: string;
  bill_after: string;
}

/** คำขอพรีวิว — ยังไม่เขียนอะไรลง DB (commit แยกที่ `PaymentEventCreate`) */
export interface AllocationPreviewRequest {
  student_id: number;
  amount_received: string;
  use_credit: boolean;
  excess_action: ExcessAction;
  bill_selection: BillSelection;
  bill_ids: number[];
  channel_id: number | null;
}

/** ผลพรีวิว — สมการ `amount_received + credit_used = total_applied + credit_added` ผ่านเสมอ */
export interface AllocationPreviewResponse {
  allocations: AllocationLine[];
  total_applied: string;
  credit_used: string;
  credit_added: string;
  remaining_unapplied: string;
  warnings: string[];
}

/** คำขอบันทึกรับเงิน — ต้องมี `idempotency_key` (สร้างครั้งเดียวต่อการกด 1 ครั้ง) */
export interface PaymentEventCreate extends AllocationPreviewRequest {
  idempotency_key: string;
  /** กระเป๋าที่รับเงินเข้า — backend บังคับ > 0 */
  wallet_account_id: number;
  payer_name: string | null;
  payer_person_id: number | null;
  receiver_person_id: number | null;
  receiver_name: string | null;
  note: string | null;
  /** ISO timestamp — `null` = ให้ DB ใช้เวลาปัจจุบัน */
  event_at: string | null;
}

/** เอกสารที่ event นี้สร้าง (REC/DEP, `layout_version=2`) */
export interface PaymentEventDocument {
  id: number;
  doc_type: 'receipt' | 'deposit';
  receipt_no: string;
  amount: string;
  layout_version: number;
  event_at: string | null;
  issued_at: string | null;
  status: string;
}

/**
 * ผลของ `POST /finance/payment-events`
 *
 * 🔁 `reused=true` = backend คืน event เดิมจาก `idempotency_key` (กดซ้ำ/เน็ตหลุด)
 * ⚠️ `receipt_no` เป็น `null` ได้เมื่อ "ใช้เครดิตปิดบิลล้วน" (ไม่มีเงินสด ⇒ ไม่มีใบเสร็จใหม่)
 */
export interface PaymentEventResult {
  event_id: number;
  receipt_no: string | null;
  deposit_no: string | null;
  amount_received: string;
  credit_used: string;
  credit_added: string;
  total_applied: string;
  allocations: AllocationLine[];
  documents: PaymentEventDocument[];
  reused: boolean;
  warnings: string[];
}

// ──────────────────────── 💳 ช่องทางชำระเงิน + PromptPay QR (FIN-V2 / P2.4–P2.5)
// 🔴 ชื่อฟิลด์ตรงกับ `PaymentChannelResponse` ของ backend เป๊ะ ๆ — `*_masked`
//    มีไว้แสดงเท่านั้น **ห้ามส่งกลับ** ตอนบันทึก (backend จะเก็บสตริงดอกจันลง DB)
//    ค่าเต็ม (`account_number`/`promptpay_id`) เป็น write-only และมีแต่ใน create payload

export type PaymentChannelType = 'cash' | 'bank_transfer' | 'promptpay' | 'custom_qr'

export type QrMode = 'open' | 'fixed'

export interface PaymentChannel {
  id: number
  channel_type: PaymentChannelType
  label: string
  wallet_account_id: number | null
  wallet_account_name: string | null
  account_name: string | null
  bank_name: string | null
  account_number_masked: string | null
  promptpay_id_masked: string | null
  qr_mode: QrMode | null
  is_primary: boolean
  is_active: boolean
  sort_order: number
  has_qr: boolean
}

export interface PaymentChannelListResponse {
  channels: PaymentChannel[]
}

export interface PaymentChannelCreate {
  channel_type: PaymentChannelType
  label: string
  wallet_account_id: number | null
  account_name: string | null
  bank_name: string | null
  /** เลขบัญชีเต็ม — write-only (API ไม่คืน) */
  account_number: string | null
  /** เบอร์/เลขบัตร/e-wallet เต็ม — write-only (API ไม่คืน) */
  promptpay_id: string | null
  qr_mode: QrMode | null
  is_primary: boolean
  is_active: boolean
  sort_order?: number | null
}

/**
 * PATCH ช่องทาง — ส่งเฉพาะคีย์ที่เปลี่ยน
 *
 * ⚠️ การ **ไม่ส่ง** คีย์ ≠ การส่ง `null`: backend ใช้ `exclude_unset` จึงตีความ
 *    "ไม่ส่ง" ว่าคงค่าเดิม และ `null` ว่า "ล้างค่า" ⇒ ช่องความลับที่เว้นว่างต้อง
 *    **ละคีย์ออก** ไม่ใช่ส่งค่าว่าง
 */
export type PaymentChannelUpdate = Partial<Omit<PaymentChannelCreate, 'channel_type'>> & {
  channel_type?: PaymentChannelType
}

// ──────────────────────── 📥 รับเงินหลายคนในรอบเดียว (FIN-V2 / P2.7)
// 1 คำขอ = 1 transaction = all-or-nothing · 1 นักเรียน = 1 event + REC/DEP ของตัวเอง
// ⚠️ bulk ใช้ `bill_selection='auto'` เท่านั้น และ **ไม่เลือกช่องทาง** ในรอบนี้
//    (`channel_id: null` — service ตั้ง snapshot เป็น `{}`)

export interface BulkPaymentItemInput {
  student_id: number
  /** string 2 ตำแหน่ง — `roundMoney(amount).toFixed(2)` */
  amount_received: string
  use_credit: boolean
  excess_action: ExcessAction
  note?: string | null
}

export interface BulkPaymentEventCreate {
  /** คีย์ของทั้งรอบ — backend สร้างคีย์ย่อยต่อคน (`{key[:48]}:{student_id}`) */
  idempotency_key: string
  /** เลขที่รับเงินเดียวติดทุก event (ไม่ unique ใน DB — service บังคับใต้ล็อกห้อง) */
  reference_no: string
  channel_id: number | null
  wallet_account_id: number
  receiver_person_id: number | null
  receiver_name: string
  note: string | null
  /** ISO timestamp — `null` = DB NOW ครั้งเดียวทั้งรอบ (ปี พ.ศ. เดียวกัน) */
  event_at: string | null
  items: BulkPaymentItemInput[]
}

export interface BulkPaymentEventItemResult {
  student_id: number
  student_name: string
  event: PaymentEventResult
}

/**
 * ผลของ `POST /finance/payment-events/bulk`
 *
 * 🔁 `reused=true` = ทั้งรอบเคยบันทึกแล้ว (คีย์ + reference_no เดิม) — ไม่มี REC ใหม่
 * 🔴 `event.receipt_no` เป็น `null` ได้เมื่อคนนั้นใช้เครดิตปิดบิลล้วน
 */
export interface BulkPaymentEventResult {
  status: string
  message: string
  reference_no: string
  events: BulkPaymentEventItemResult[]
  /** string 2 ตำแหน่ง — ผลรวมเงินสดของทั้งรอบ */
  total_amount_received: string
  reused: boolean
}

/** detail object ของ error ระดับ item (backend `BulkPaymentFailure` มี student_id) */
export interface BulkPaymentErrorDetail {
  code: 'BULK_ITEM_FAILED'
  message: string
  student_id: number
  item_code: string
}
