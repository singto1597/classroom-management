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
  BatchPaymentResult, // 🧾 ผลของการรับเงินรวบยอด (มีใบเสร็จที่ออกให้ในรอบนั้นด้วย)
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
  ReceiptBatchIssueResult,
  ReceiptInvoiceIssuePayload,
  ReceiptRoomInvoicePayload,
  InvoiceBatchIssueResult,
  ReceiptBatch, // 📚 [F5] ชุดเอกสาร
  ReceiptBatchDetail,
  ReceiptBatchCreatePayload,
  ReceiptBatchSetReceiptsPayload,
  ReceiptBatchUpdatePayload,
  ReceiptBatchMutationResult,
  ReceiptBatchDissolveResult,
  StudentCreditBalance, // 💰 [F4] เงินรับล่วงหน้า / เครดิตคงเหลือรายนักเรียน
  StudentCreditDetail,
  CreditApplyPlan,
  CreditTopUpRequest,
  CreditTopUpResponse,
  CreditApplyRequest,
  CreditUndoRequest,
  CreditUndoResponse
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
  // 🧾 [F5] และออกใบเสร็จให้ทุกรายการในรอบเดียวกัน (ปิดได้ด้วย `issue_receipts: false`)
  //    ⇒ คำตอบจึงไม่ใช่ `ApiSuccessResponse` ธรรมดา แต่มี `receipts` มาด้วย
  async confirmBatchPayment(roomId: number, payload: BatchPaymentConfirm): Promise<BatchPaymentResult> {
    return await api.put(`/api/classroom/${roomId}/finance/payments/batch?target_type=room`, payload) as unknown as BatchPaymentResult;
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
  },

  // ✍️ ใบแจ้งหนี้ "ยอดค้างรวมต่อคน" — 1 คน = 1 ใบ (all-or-nothing ทั้งชุด)
  //    ⚠️ ต่างจากใบเสร็จ: **กดซ้ำไม่ได้เลขเดิม** (point-in-time) ⇒ UI ต้อง confirm ก่อนยิงเสมอ
  async issueInvoices(
    roomId: number,
    payload: ReceiptInvoiceIssuePayload
  ): Promise<InvoiceBatchIssueResult> {
    return await api.post(
      `/api/classroom/${roomId}/finance/receipts/invoices?target_type=room`,
      payload
    ) as unknown as InvoiceBatchIssueResult;
  },

  // ✍️ ออกใบแจ้งหนี้ทั้งห้อง — ระบบเป็นคนหาว่าใครค้าง (ไม่ส่งรายชื่อไปจากหน้าจอ)
  //    ⚠️ เป็น **การเขียนจริงทุกคน**: กดซ้ำ = กินเลข INV ชุดใหม่ ⇒ ต้อง confirm ที่ UI
  async issueRoomInvoices(
    roomId: number,
    payload: ReceiptRoomInvoicePayload = {}
  ): Promise<InvoiceBatchIssueResult> {
    return await api.post(
      `/api/classroom/${roomId}/finance/receipts/invoices/room?target_type=room`,
      payload
    ) as unknown as InvoiceBatchIssueResult;
  },

  // 🖨️ รวมเอกสารหลายใบเป็น PDF **ไฟล์เดียว หน้าละใบ**
  //    ⚠️ `POST` (ไม่ใช่ GET) เพราะเลข 100 ใบใส่ query string ไม่ได้
  //    ⚠️ เพดาน 100 ฉบับบังคับที่ backend ⇒ เกินได้ **400 พร้อมข้อความไทยที่บอกทางออก**
  //       (ไม่ใช่ 422 ของ Pydantic) — เช็คที่ UI ก่อนยิงเพื่อไม่ให้เสียรอบเปล่า
  async downloadCombinedPdf(roomId: number, receiptNos: string[]): Promise<Blob> {
    const response = await api.post(
      `/api/classroom/${roomId}/finance/receipts/pdf?target_type=room`,
      { receipt_nos: receiptNos },
      { responseType: 'blob' }
    );

    return response as unknown as Blob;
  },

  // ════════════════════════════════════════════════════════════════════════════
  // 📚 [F5] ชุดเอกสาร — จัดกลุ่มเอกสารเพื่อยุบการแสดงผลในทะเบียน
  // ════════════════════════════════════════════════════════════════════════════
  // 🔑 "ชุด" ไม่ใช่เอกสาร: ไม่มีเลขรันของตัวเองและ **ไม่กินเลขเอกสาร** ⇒ ยุบชุด/ย้ายใบ
  //    ไม่แตะ `receipt_no`/`amount`/`status` ของใบเลย (ต่างจาก "ยกเลิกรายการ" โดยสิ้นเชิง)
  //
  // 🔒 อ่าน 2 ตัวเปิดให้ **สมาชิกห้อง** ทุกคน — เขียน 4 ตัวต้อง `MANAGE_FINANCE`
  //    ⇒ หน้าจอต้อง gate ปุ่มเขียนด้วย `canManageFinance` **ไม่ใช่ `isAdmin`**
  //    (เหตุผลเดียวกับ F4 — ดูคอมเมนต์ยาวในกลุ่มเครดิตด้านล่าง)
  //
  // ⚠️ `receipt_nos` ไปใน **body** ของ POST/PUT เท่านั้น — ห้ามย้ายไป query string
  //    เพราะ axios จะ serialize array เป็น `receipt_nos[]=` ซึ่ง FastAPI มองไม่เห็น
  //    แล้วกลายเป็น 422 ที่อ่านไม่ออก (กับดักเดียวกับ `downloadCombinedPdf`)

  // 📋 ชุดเอกสารทั้งหมดของห้อง (ใหม่สุดก่อน) — ชุดที่สมาชิกถูกยกเลิกครบแล้วจะไม่ถูกคืน
  async getReceiptBatches(roomId: number): Promise<ReceiptBatch[]> {
    return await api.get(`/api/classroom/${roomId}/finance/receipt-batches`, {
      params: { target_type: 'room' }
    }) as unknown as ReceiptBatch[];
  },

  // 🔎 รายละเอียดชุด + เอกสารทุกใบ **รวมใบที่ถูกยกเลิก** (ตัวเลขจะได้ตรงกับ `voided_count`)
  async getReceiptBatch(roomId: number, batchId: number): Promise<ReceiptBatchDetail> {
    return await api.get(
      `/api/classroom/${roomId}/finance/receipt-batches/${batchId}`,
      { params: { target_type: 'room' } }
    ) as unknown as ReceiptBatchDetail;
  },

  // ✍️ สร้างชุดจากเลขที่เอกสารที่ติ๊กเลือก (1–100 ใบ — เกินกว่านี้ backend ตอบ 400)
  //    🔁 กดซ้ำด้วยเซตเดิม **ปลอดภัย**: backend คืนชุดเดิมพร้อม `created: false`
  //       ⇒ ไม่ต้องมี idempotency key และไม่ต้อง confirm ที่ UI
  async createReceiptBatch(
    roomId: number,
    payload: ReceiptBatchCreatePayload
  ): Promise<ReceiptBatchMutationResult> {
    return await api.post(
      `/api/classroom/${roomId}/finance/receipt-batches?target_type=room`,
      payload
    ) as unknown as ReceiptBatchMutationResult;
  },

  // ✍️ **ตั้งสมาชิกทั้งชุด** (PUT semantics) — ใบที่หายจากลิสต์จะถูกถอดออกจากชุด
  //    ⚠️ ส่งรายชื่อ **ครบทุกใบที่ต้องการให้อยู่ในชุด** ไม่ใช่แค่ใบที่เพิ่ม
  //       (ส่งเซตย่อย = ถอดใบที่ไม่ได้ส่งออก — ตั้งใจ เป็นความหมายของ PUT)
  async setReceiptBatchReceipts(
    roomId: number,
    batchId: number,
    payload: ReceiptBatchSetReceiptsPayload
  ): Promise<ReceiptBatchMutationResult> {
    return await api.put(
      `/api/classroom/${roomId}/finance/receipt-batches/${batchId}/receipts?target_type=room`,
      payload
    ) as unknown as ReceiptBatchMutationResult;
  },

  // ✍️ เปลี่ยนชื่อ/โน้ต — ส่งมาแค่ฟิลด์ที่จะแก้
  //    ⚠️ `title: null` = ล้างชื่อ (กลับไปใช้ชื่อที่หน้าจอประกอบ) ไม่ใช่ "ไม่แก้"
  async updateReceiptBatch(
    roomId: number,
    batchId: number,
    payload: ReceiptBatchUpdatePayload
  ): Promise<ReceiptBatchMutationResult> {
    return await api.patch(
      `/api/classroom/${roomId}/finance/receipt-batches/${batchId}?target_type=room`,
      payload
    ) as unknown as ReceiptBatchMutationResult;
  },

  // ✍️ ยุบชุด — **เอกสารไม่ถูกแตะเลย** แค่หลุดออกจากชุด (`detached_count` = จำนวนที่ปลด)
  //    ⚠️ ไม่ใช่ "ลบเอกสาร": ใบเสร็จทุกใบยัง active และเลขที่/ยอดเดิมครบ
  async deleteReceiptBatch(roomId: number, batchId: number): Promise<ReceiptBatchDissolveResult> {
    return await api.delete(
      `/api/classroom/${roomId}/finance/receipt-batches/${batchId}?target_type=room`
    ) as unknown as ReceiptBatchDissolveResult;
  },

  // ════════════════════════════════════════════════════════════════════════════
  // 💰 [F4] เงินรับล่วงหน้า — เครดิตคงเหลือรายนักเรียน
  // ════════════════════════════════════════════════════════════════════════════
  // 🔑 อ่าน 3 ตัว (`getCredits` / `getCreditPlan` / `getStudentCredit`) เปิดให้ **สมาชิกห้อง**
  //    ทุกคน — เขียน 3 ตัว (เติม/หัก/ยกเลิกการหัก) ต้อง `MANAGE_FINANCE`
  //    ⇒ หน้าจอต้อง gate ปุ่มเขียนด้วย `canManageFinance` **ไม่ใช่ `isAdmin`**
  //    (บทเรียนจาก `DebtorList.vue`: เหรัญญิกที่มี MANAGE_FINANCE แต่ไม่ใช่แอดมิน
  //     ต้องใช้ได้ — ถ้า gate ด้วย `isAdmin` ฟีเจอร์นี้จะใช้ไม่ได้กับคนที่ควรใช้ที่สุด)
  // ════════════════════════════════════════════════════════════════════════════

  // 📋 นักเรียนทุกคนของห้อง + เครดิตคงเหลือ + ยอดค้างสุทธิ (คนไม่มีเครดิตก็อยู่ ยอด 0)
  async getCredits(roomId: number): Promise<StudentCreditBalance[]> {
    return await api.get(`/api/classroom/${roomId}/finance/credits`, {
      params: { target_type: 'room' }
    }) as unknown as StudentCreditBalance[];
  },

  // 🔎 ข้อเสนอการหักของนักเรียนที่เลือก — **อ่านล้วน ไม่เขียนอะไร**
  //    ⚠️ ต้องเรียกตัวนี้ก่อน `applyCredit` เสมอ เพื่อให้ครูเห็นตัวเลขจริงก่อนยืนยัน
  //    ⚠️ `studentIds` ว่างไม่ได้ (backend บังคับ 1–100) ⇒ ให้ผู้เรียกกันเองที่ UI
  async getCreditPlan(roomId: number, studentIds: number[]): Promise<CreditApplyPlan> {
    // 🔴 ห้ามส่ง array ผ่าน `params:` ของ axios — axios 1.x serialize เป็น **`student_ids[]=1`**
    //    (วงเล็บเหลี่ยม) แต่ FastAPI `Query(List[int])` ต้องการ **คีย์ซ้ำ** `student_ids=1&student_ids=2`
    //    ⇒ ของเดิมได้ **422 `{"loc":["query","student_ids"],"type":"missing"}`** เพราะ FastAPI
    //    มองชื่อพารามิเตอร์ว่าเป็น `student_ids[]` ไม่ใช่ `student_ids` แล้วหา `student_ids` ไม่เจอ
    //    ⚠️ กับดักนี้ **เทสต์ฝั่ง backend จับไม่ได้เลย** เพราะ TestClient ส่งคีย์ซ้ำให้เองอยู่แล้ว
    //       (เจอจากการเรนเดอร์หน้าจริงในเบราว์เซอร์แล้วดักดู URL ที่ออกไป — ดู docs/skills.md)
    //    ⇒ ใช้ `URLSearchParams` สร้างสตริงเอง แบบเดียวกับ `ActivityService.getActivities`
    const query = new URLSearchParams({ target_type: 'room' });
    studentIds.forEach((id) => query.append('student_ids', String(id)));

    return await api.get(
      `/api/classroom/${roomId}/finance/credits/plan?${query}`
    ) as unknown as CreditApplyPlan;
  },

  // 🔎 ประวัติเครดิตของนักเรียน 1 คน + บิลค้าง + ข้อเสนอการหัก
  async getStudentCredit(roomId: number, studentId: number): Promise<StudentCreditDetail> {
    return await api.get(
      `/api/classroom/${roomId}/finance/credits/${studentId}`,
      { params: { target_type: 'room' } }
    ) as unknown as StudentCreditDetail;
  },

  // 💵 เติมเงินล่วงหน้า (รับเงินจริง) — ออกใบ DEP ให้ทันที
  //    ⚠️ `idempotency_key` **บังคับ** และต้องคงค่าเดิมตลอดการกดหนึ่งครั้ง (ดู `utils/money.ts`)
  async topUpCredit(roomId: number, payload: CreditTopUpRequest): Promise<CreditTopUpResponse> {
    return await api.post(
      `/api/classroom/${roomId}/finance/credits?target_type=room`,
      payload
    ) as unknown as CreditTopUpResponse;
  },

  // ✂️ หักเครดิตไปปิดบิลของนักเรียนที่เลือก — ทั้งชุด all-or-nothing
  //    ⚠️ ไม่มีเงินเคลื่อนไหวในจังหวะนี้ (เงินเข้ามาตั้งแต่ตอนเติม) ⇒ ไม่มีใบเสร็จใหม่
  //       หลักฐานคือใบ DEP ต้นทาง + ประวัติเครดิต
  async applyCredit(roomId: number, payload: CreditApplyRequest): Promise<CreditApplyPlan> {
    return await api.post(
      `/api/classroom/${roomId}/finance/credits/apply?target_type=room`,
      payload
    ) as unknown as CreditApplyPlan;
  },

  // ↩️ ยกเลิก "การหัก" 1 รายการ (คืนเครดิตเข้ากระเป๋านักเรียน + เปิดบิลกลับเป็นค้าง)
  //    ⚠️ ใช้ยกเลิก **การเติม** ไม่ได้ — การเติมต้อง `revertTransaction` (ซึ่ง void ใบ DEP ด้วย)
  async undoCreditApplication(
    roomId: number,
    payload: CreditUndoRequest
  ): Promise<CreditUndoResponse> {
    return await api.post(
      `/api/classroom/${roomId}/finance/credits/undo?target_type=room`,
      payload
    ) as unknown as CreditUndoResponse;
  }
};
