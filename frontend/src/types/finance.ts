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
