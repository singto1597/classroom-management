import api from './api';

import type {
  Account,
  AccountCreate,
  Category,
  CategoryCreate,
  TransactionList,
  TransactionCreate,
  TransactionQueryParams,
  TransferCreate,
  Collection,
  FeeCollectionCreate,
  CollectionStatus,
  FeeCollectionUpdate,
  PaymentConfirm,
  BatchPaymentConfirm, // ✨ รับเงินรวบยอดหลายบิล
  FinanceSummary,
  Debtor,
  StudentDebtProfile,
  BasicStudent, // ✨ Import เพิ่มเติม
  TrialBalance, // 📊 งบการเงิน
  IncomeStatement,
  BalanceSheet,
  Budget, // 💰 งบประมาณ (F2)
  BudgetOverview,
  BudgetCreatePayload,
  BudgetUpdatePayload,
  ReceiptListItem, // 🧾 ใบเสร็จ / ใบแจ้งหนี้ (F3)
  ReceiptDetail,
  ReceiptQueryParams,
  ReceiptIssuePayload,
  ReceiptBatchIssuePayload,
  ReceiptIssueResult,
  ReceiptBatchIssueResult
} from '@/types/finance';

// ✨ Envelope สำเร็จของ backend (SuccessResponse) — ใช้กับการสร้าง/แก้ไข/ลบทุกตัว
import type { ApiSuccessResponse } from '@/types/api';

// Query string ของ GET /finance/categories (backend อ่าน cat_type + target_type)
interface CategoryQueryParams {
  target_type: string;
  cat_type?: 'income' | 'expense';
}

// Query string ของ GET /finance/summary (backend อ่าน month + year + target_type)
interface SummaryQueryParams {
  target_type: string;
  month?: number;
  year?: number;
}

export const FinanceService = {
  // ==========================================
  // 💰 1. Accounts & Categories
  // ==========================================

  async getAccounts(roomId: number): Promise<Account[]> {
    return await api.get(`/api/classroom/${roomId}/finance/accounts?target_type=room`) as unknown as Account[];
  },

  async createAccount(roomId: number, payload: AccountCreate): Promise<ApiSuccessResponse> {
    return await api.post(`/api/classroom/${roomId}/finance/accounts?target_type=room`, payload) as unknown as ApiSuccessResponse;
  },

  async updateAccount(roomId: number, accountId: number, name: string, userName: string): Promise<ApiSuccessResponse> {
    return await api.patch(`/api/classroom/${roomId}/finance/accounts/${accountId}?target_type=room`, {
      account_name: name,
      user_name: userName
    }) as unknown as ApiSuccessResponse;
  },

  async deleteAccount(roomId: number, accountId: number): Promise<ApiSuccessResponse> {
    return await api.delete(`/api/classroom/${roomId}/finance/accounts/${accountId}?target_type=room`) as unknown as ApiSuccessResponse;
  },

  async getCategories(roomId: number, type?: 'income' | 'expense'): Promise<Category[]> {
    const params: CategoryQueryParams = { target_type: 'room' };
    if (type) params.cat_type = type;

    return await api.get(`/api/classroom/${roomId}/finance/categories`, { params }) as unknown as Category[];
  },

  async createCategory(roomId: number, payload: CategoryCreate): Promise<ApiSuccessResponse> {
    return await api.post(`/api/classroom/${roomId}/finance/categories?target_type=room`, payload) as unknown as ApiSuccessResponse;
  },

  async updateCategory(roomId: number, categoryId: number, name: string, userName: string): Promise<ApiSuccessResponse> {
    return await api.patch(`/api/classroom/${roomId}/finance/categories/${categoryId}?target_type=room`, {
      category_name: name,
      user_name: userName
    }) as unknown as ApiSuccessResponse;
  },

  async deleteCategory(roomId: number, categoryId: number): Promise<ApiSuccessResponse> {
    return await api.delete(`/api/classroom/${roomId}/finance/categories/${categoryId}?target_type=room`) as unknown as ApiSuccessResponse;
  },

  // ==========================================
  // 💸 2. Transactions & Transfers
  // ==========================================

  async getTransactions(roomId: number, filters: Partial<TransactionQueryParams> = {}): Promise<TransactionList> {
    const params = { ...filters, target_type: 'room' };
    return await api.get(`/api/classroom/${roomId}/finance/transactions`, { params }) as unknown as TransactionList;
  },

  async addTransaction(roomId: number, payload: TransactionCreate): Promise<ApiSuccessResponse> {
    return await api.post(`/api/classroom/${roomId}/finance/transactions?target_type=room`, payload) as unknown as ApiSuccessResponse;
  },

  async transferMoney(roomId: number, payload: TransferCreate): Promise<ApiSuccessResponse> {
    return await api.post(`/api/classroom/${roomId}/finance/transfer?target_type=room`, payload) as unknown as ApiSuccessResponse;
  },

  async revertTransaction(roomId: number, transactionId: number, userName: string): Promise<ApiSuccessResponse> {
    return await api.delete(`/api/classroom/${roomId}/finance/transactions/${transactionId}?target_type=room`, {
      data: { user_name: userName }
    }) as unknown as ApiSuccessResponse;
  },

  // ==========================================
  // 📦 3. Fee Collections & Payments
  // ==========================================

  // ✨ ดึงรายชื่อนักเรียนสำหรับ UI เลือกติ๊กตอนสร้างแคมเปญ
  async getActiveStudents(roomId: number): Promise<BasicStudent[]> {
    return await api.get(`/api/classroom/${roomId}/finance/students?target_type=room`) as unknown as BasicStudent[];
  },

  async getCollections(roomId: number): Promise<Collection[]> {
    return await api.get(`/api/classroom/${roomId}/finance/collections?target_type=room`) as unknown as Collection[];
  },

  async createCollection(roomId: number, payload: FeeCollectionCreate): Promise<ApiSuccessResponse> {
    return await api.post(`/api/classroom/${roomId}/finance/collections?target_type=room`, payload) as unknown as ApiSuccessResponse;
  },

  async getCollectionStatus(roomId: number, collectionId: number): Promise<CollectionStatus> {
    return await api.get(`/api/classroom/${roomId}/finance/collections/${collectionId}?target_type=room`) as unknown as CollectionStatus;
  },

  async updateCollection(roomId: number, collectionId: number, payload: FeeCollectionUpdate): Promise<ApiSuccessResponse> {
    return await api.put(`/api/classroom/${roomId}/finance/collections/${collectionId}?target_type=room`, payload) as unknown as ApiSuccessResponse;
  },

  async confirmPayment(roomId: number, paymentId: number, payload: PaymentConfirm): Promise<ApiSuccessResponse> {
    return await api.put(`/api/classroom/${roomId}/finance/payments/${paymentId}/pay?target_type=room`, payload) as unknown as ApiSuccessResponse;
  },

  // ✨ รับเงินรวบยอดหลายบิล (ปลดหนี้) — ยิงครั้งเดียว บอทแจ้งเตือน embed เดียว
  async confirmBatchPayment(roomId: number, payload: BatchPaymentConfirm): Promise<ApiSuccessResponse> {
    return await api.put(`/api/classroom/${roomId}/finance/payments/batch?target_type=room`, payload) as unknown as ApiSuccessResponse;
  },

  // ✨ API สำหรับลบรายชื่อนักเรียนออกจากแคมเปญ
  async removeStudentFromCollection(roomId: number, collectionId: number, studentId: number, userName: string): Promise<ApiSuccessResponse> {
    return await api.delete(`/api/classroom/${roomId}/finance/collections/${collectionId}/students/${studentId}?target_type=room`, {
      data: { user_name: userName }
    }) as unknown as ApiSuccessResponse;
  },

  // ==========================================
  // 📊 4. Summary & Reports
  // ==========================================

  async getSummary(roomId: number, month?: number, year?: number): Promise<FinanceSummary> {
    const params: SummaryQueryParams = { target_type: 'room' };
    if (month) params.month = month;
    if (year) params.year = year;
    return await api.get(`/api/classroom/${roomId}/finance/summary`, { params }) as unknown as FinanceSummary;
  },

  async getAllDebtors(roomId: number): Promise<Debtor[]> {
    return await api.get(`/api/classroom/${roomId}/finance/debtors?target_type=room`) as unknown as Debtor[];
  },

  async getStudentDebts(roomId: number, studentId: number): Promise<StudentDebtProfile> {
    return await api.get(`/api/classroom/${roomId}/finance/students/${studentId}/debts?target_type=room`) as unknown as StudentDebtProfile;
  },

  // 📊 งบทดลอง (Trial Balance) — ยอดสะสมถึง asOfDate (ไม่ระบุ = ทั้งหมดจนถึงตอนนี้)
  async getTrialBalance(roomId: number, asOfDate?: string): Promise<TrialBalance> {
    const params: Record<string, unknown> = { target_type: 'room' };
    if (asOfDate) params.as_of_date = asOfDate;
    return await api.get(`/api/classroom/${roomId}/finance/trial-balance`, { params }) as unknown as TrialBalance;
  },

  // 📊 งบกำไรขาดทุน — backend **บังคับ** ทั้ง start_date และ end_date (ขาดตัวใดตัวหนึ่ง = 422)
  async getIncomeStatement(roomId: number, startDate: string, endDate: string): Promise<IncomeStatement> {
    return await api.get(`/api/classroom/${roomId}/finance/income-statement`, {
      params: { target_type: 'room', start_date: startDate, end_date: endDate }
    }) as unknown as IncomeStatement;
  },

  // 📊 งบแสดงฐานะการเงิน ณ วันที่ (ไม่ระบุ = ณ วันนี้)
  async getBalanceSheet(roomId: number, asOfDate?: string): Promise<BalanceSheet> {
    const params: Record<string, unknown> = { target_type: 'room' };
    if (asOfDate) params.as_of_date = asOfDate;
    return await api.get(`/api/classroom/${roomId}/finance/balance-sheet`, { params }) as unknown as BalanceSheet;
  },

  // ==========================================
  // 💰 5. งบประมาณ (Budget) — F2
  // ==========================================

  // 📋 รายการงบ (ยังไม่มียอดใช้) — ทุกตัวกรองเป็น optional ฝั่ง backend
  async getBudgets(
    roomId: number,
    startDate?: string,
    endDate?: string,
    categoryType?: 'income' | 'expense'
  ): Promise<Budget[]> {
    const params: Record<string, unknown> = { target_type: 'room' };
    if (startDate) params.start_date = startDate;
    if (endDate) params.end_date = endDate;
    if (categoryType) params.category_type = categoryType;
    return await api.get(`/api/classroom/${roomId}/finance/budgets`, { params }) as unknown as Budget[];
  },

  // 📊 งบ + ยอดใช้จริง — backend **บังคับ** ทั้ง start_date และ end_date (ขาดตัวใดตัวหนึ่ง = 422)
  //    ⚠️ ยอด `used` ของแต่ละแถวคิดจากช่วงของ **ตัวงบเอง** (clamp ด้วย GREATEST/LEAST)
  //    ไม่ใช่ช่วงที่ส่งมากรอง — งบที่คาบเกี่ยวแค่บางส่วนจึงได้ยอดเฉพาะส่วนที่คาบเกี่ยว
  async getBudgetOverview(roomId: number, startDate: string, endDate: string): Promise<BudgetOverview> {
    return await api.get(`/api/classroom/${roomId}/finance/budgets/overview`, {
      params: { target_type: 'room', start_date: startDate, end_date: endDate }
    }) as unknown as BudgetOverview;
  },

  async createBudget(roomId: number, payload: BudgetCreatePayload): Promise<ApiSuccessResponse> {
    return await api.post(
      `/api/classroom/${roomId}/finance/budgets?target_type=room`,
      payload
    ) as unknown as ApiSuccessResponse;
  },

  async updateBudget(roomId: number, budgetId: number, payload: BudgetUpdatePayload): Promise<ApiSuccessResponse> {
    return await api.patch(
      `/api/classroom/${roomId}/finance/budgets/${budgetId}?target_type=room`,
      payload
    ) as unknown as ApiSuccessResponse;
  },

  // 🗑️ ลบ = soft delete ฝั่ง backend (หายจากหน้าจอ แต่ยังอยู่ให้ guard ของหมวดเห็น)
  async deleteBudget(roomId: number, budgetId: number, userName?: string): Promise<ApiSuccessResponse> {
    return await api.delete(`/api/classroom/${roomId}/finance/budgets/${budgetId}?target_type=room`, {
      data: { user_name: userName }
    }) as unknown as ApiSuccessResponse;
  },

  // ✨ ส่งออกประวัติการทำรายการเป็นไฟล์ Excel (รับกลับมาเป็น Blob)
  async exportTransactionsExcel(roomId: number, month?: number, year?: number, userName?: string): Promise<Blob> {
    const response = await api.post(`/api/classroom/${roomId}/finance/export?target_type=room`, {
      month,
      year,
      user_name: userName
    }, {
      // 🚨 สำคัญมาก! บังคับให้ Axios รับข้อมูลมาเป็นไฟล์ไบนารี
      responseType: 'blob'
    });

    // 👇 เติม as unknown as Blob เพื่อตบตา TypeScript ให้ยอม Build ผ่าน
    return response as unknown as Blob;
  },

  // 📒 ส่งออกสมุดรายวันทั่วไป (General Journal) สำหรับนักบัญชี — แบบ GET (month/year/ช่วงวันที่)
  async exportJournalExcel(
    roomId: number,
    month?: number,
    year?: number,
    startDate?: string,
    endDate?: string
  ): Promise<Blob> {
    const params: Record<string, unknown> = { target_type: 'room' };
    if (month) params.month = month;
    if (year) params.year = year;
    if (startDate) params.start_date = startDate;
    if (endDate) params.end_date = endDate;

    const response = await api.get(`/api/classroom/${roomId}/finance/export/journal`, {
      params,
      responseType: 'blob'
    });

    return response as unknown as Blob;
  },

  // ==========================================
  // 🧾 6. ใบเสร็จ / ใบแจ้งหนี้ (Receipt / Invoice) — F3
  // ==========================================
  //
  // 📌 ความไม่สมมาตรที่ backend ล็อกไว้ (ห้าม "แก้" ให้เท่ากัน — มันถูกเข้ารหัสใน DDL):
  //    - `doc_type: 'receipt'` = **idempotent** → กดซ้ำได้เลขเดิม, response กลับมา `reused: true`
  //    - `doc_type: 'invoice'` = **point-in-time** → กดซ้ำได้ **เลขใหม่ทุกครั้ง** (กินเลขจริง)
  //    ⇒ ปุ่มที่ออกใบแจ้งหนี้ต้องมี confirm เสมอก่อนยิง

  // 📋 รายการเอกสารของห้อง — กรองช่วงวันที่ตาม **วันตามปฏิทินไทย** (ตรงกับงบการเงิน F1)
  async getReceipts(roomId: number, params: ReceiptQueryParams = {}): Promise<ReceiptListItem[]> {
    const query: Record<string, unknown> = { target_type: 'room' };
    if (params.startDate) query.start_date = params.startDate;
    if (params.endDate) query.end_date = params.endDate;
    if (params.docType) query.doc_type = params.docType;
    if (params.studentId) query.student_id = params.studentId;

    return await api.get(`/api/classroom/${roomId}/finance/receipts`, {
      params: query
    }) as unknown as ReceiptListItem[];
  },

  // 🔎 รายละเอียดตาม **เลขที่เอกสาร** (string เช่น `REC-2569-0042`) ไม่ใช่ id
  //    ⚠️ ต้อง encode — backend บังคับ pattern `^[A-Z]{3}-\d{4}-\d{4}$` และเลขที่ไม่ตรงรูปได้ 422
  async getReceipt(roomId: number, receiptNo: string): Promise<ReceiptDetail> {
    return await api.get(
      `/api/classroom/${roomId}/finance/receipts/${encodeURIComponent(receiptNo)}`,
      { params: { target_type: 'room' } }
    ) as unknown as ReceiptDetail;
  },

  // ✍️ ออกเอกสาร 1 ใบ — ต้องมี MANAGE_FINANCE (อ่านได้ทุกคน แต่เขียนต้องมีสิทธิ์)
  async issueReceipt(roomId: number, payload: ReceiptIssuePayload): Promise<ReceiptIssueResult> {
    return await api.post(
      `/api/classroom/${roomId}/finance/receipts?target_type=room`,
      payload
    ) as unknown as ReceiptIssueResult;
  },

  // ✍️ ออกรวบยอด (all-or-nothing, 1–100 ใบ) — backend dedupe `payment_ids` ให้แล้ว
  //    ใช้ 100 เป็นเพดาน: เกินกว่านั้นควรเป็นงานเบื้องหลัง ไม่ใช่ HTTP request
  async issueReceiptsBatch(
    roomId: number,
    payload: ReceiptBatchIssuePayload
  ): Promise<ReceiptBatchIssueResult> {
    return await api.post(
      `/api/classroom/${roomId}/finance/receipts/batch?target_type=room`,
      payload
    ) as unknown as ReceiptBatchIssueResult;
  },

  // 🖨️ ดาวน์โหลด PDF — backend เรนเดอร์จากเทมเพลต Jinja2 ผ่าน Gotenberg (headless Chrome)
  //    ⚠️ 502 = Gotenberg ต่อไม่ได้/เรนเดอร์ไม่ผ่าน (ไม่ใช่ 500 ของโค้ดเรา) — ข้อความไทยมาจาก
  //       interceptor ที่คลี่ Blob error body ออกแล้ว (ดู services/api.ts)
  async downloadReceiptPdf(roomId: number, receiptNo: string): Promise<Blob> {
    const response = await api.get(
      `/api/classroom/${roomId}/finance/receipts/${encodeURIComponent(receiptNo)}/pdf`,
      { params: { target_type: 'room' }, responseType: 'blob' }
    );

    return response as unknown as Blob;
  }
};
