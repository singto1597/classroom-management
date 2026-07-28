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
  debts: StudentDebtItem[]; // ดึง Type เดิมที่ปลอดภัยกว่า any[] กลับมา
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
  expense_breakdown: CategoryBreakdown[]; // ดึง Type เดิมที่ปลอดภัยกว่า any[] กลับมา
}

// ✨ เพิ่ม Type ใหม่สำหรับดึงรายชื่อเด็กโดยเฉพาะ
export interface BasicStudent {
  id: number;
  student_no: number;
  first_name: string;
  last_name: string;
  nickname: string;
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

export interface FeeCollectionUpdate {
  title?: string;
  amount?: number;
  due_date?: string;
  status?: 'active' | 'closed';
  user_name?: string;
}