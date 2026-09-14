export interface Account {
  id: number;
  account_name: string;
  balance: number;
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

export interface Collection {
  id: number;
  title: string;
  amount: number;
  due_date: string | null;
  status: 'active' | 'closed';
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
  total_pending_amount: number;
}

export interface StudentDebtItem {
  payment_id: number;
  collection_id: number;
  title: string;
  amount: number;
  due_date: string | null;
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
  user_name: string;
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
}

export interface FeeCollectionUpdate {
  title?: string;
  amount?: number;
  due_date?: string;
  status?: 'active' | 'closed';
  user_name?: string;
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

/** ชนิดเอกสาร — ตรงกับ `DOC_TYPE_*` ใน `backend/services/finance/constants.py` */
export type ReceiptDocType = 'receipt' | 'invoice';

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
}

/** แถวในหน้ารายการ — backend แนบชื่อแคมเปญ/เลขที่นักเรียนมาให้ตารางแสดงได้โดยไม่ต้องยิงเพิ่ม */
export interface ReceiptListItem extends Receipt {
  collection_title: string | null;
  student_no: number | null;
}

/** หน้ารายละเอียด — ได้ข้อมูลระดับแคมเปญ/ห้องเพิ่ม สำหรับหัวเอกสารบนหน้าจอ */
export interface ReceiptDetail extends ReceiptListItem {
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
