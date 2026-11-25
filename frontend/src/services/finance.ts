import api from './api';
// 🗂️ [FIN-V2 / P5.2] ตัวแปลงตัวกรองทะเบียน → query params (ตรรกะบริสุทธิ์ มีเทสต์ใน utils)
import { buildDocumentQuery } from '@/utils/documentFilters';

import type {
  Account,
  AccountCreate,
  AccountUpdate,
  Category,
  CategoryCreate,
  TransactionList,
  TransactionCreate,
  TransactionCreateResponse, // 🧾 [F6] ผลของการบันทึกรายการ (มีเลขเอกสารของใบสำคัญจ่าย/ใบรับเงิน)
  TransactionQueryParams,
  TransferCreate,
  Collection,
  FeeCollectionCreate,
  CustomChargeCreate,
  CustomChargeResponse,
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
  CreditUndoResponse,
  FineType, // ⚖️ [P5] ค่าปรับ
  FineTypeCreate,
  FineTypeUpdate,
  FineListQuery,
  FineListResponse,
  FineDetail,
  FineIssueRequest,
  FineIssueResponse,
  FineUpdateRequest,
  FineCancelRequest,
  FineWaiverCreate,
  FineWaiverDecision,
  FineWaiverListResponse,
  FineWaiverActionResponse,
  FineRefundCreate,
  FineRefundDecision,
  FineRefundListResponse,
  FineRefundActionResponse,
  AgingResponse,
  FineSummary,
  // 👥 [FIN-V2 / P1.2] ผู้เกี่ยวข้องทางการเงิน + ตั้งค่าห้อง
  FinancePerson,
  PersonListResponse,
  PersonCreate,
  PersonUpdate,
  PeopleSyncResult,
  FinanceSettings,
  FinanceSettingsUpdate,
  // 👤 [FIN-V2 / P1.3 API → P1.4 UI] บัญชีรายบุคคล + statement
  IndividualAccountListResponse,
  IndividualAccountDetailResponse,
  IndividualAccountQuery,
  StudentStatementResponse,
  StudentStatementQuery,
  // 💸 [FIN-V2 / P2.1 API → P2.3 UI] รับเงิน 1 ครั้ง = 1 event
  AllocationPreviewRequest,
  AllocationPreviewResponse,
  PaymentEventCreate,
  PaymentEventResult,
  // 💳 [FIN-V2 / P2.4 API → P2.5 UI] ช่องทางชำระเงิน + PromptPay QR
  PaymentChannel,
  PaymentChannelListResponse,
  PaymentChannelCreate,
  PaymentChannelUpdate,
  // 📥 [FIN-V2 / P2.7] รับเงินหลายคนในรอบเดียว
  BulkPaymentEventCreate,
  BulkPaymentEventResult,
  // 👜 [FIN-V2 / P3.1 API → P3.2 UI] เงินสดรอส่งมอบ
  CustodyListResponse,
  CustodyAccountCreate,
  CustodyAccount,
  CustodyHandoverCreate,
  CustodyHandover,
  CustodyMovementListResponse,
  // 📜 [FIN-V2 / P3.4] ประวัติการรับเงิน (อ่านอย่างเดียว)
  PaymentHistoryResponse,
  PaymentHistoryQuery,
  // 💳 [FIN-V2 / P3.5] หักเครดิตหลายคนเป็นรอบเดียว
  CreditRoundCreate,
  CreditRoundResponse,
  // 💸 [FIN-V2 / P4.1 API → P4.3 UI] ใบสำคัญจ่ายหลายบรรทัด
  ExpenseVoucherCreate,
  ExpenseVoucherCreateResponse,
  ExpenseVoucherDetail,
  ExpenseVoucherListResponse,
  // 💰 [FIN-V2 / P4.4 API → P4.5 UI] ใบรับเงินหลายบรรทัด
  IncomeBatchCreate,
  IncomeBatchCreateResponse,
  IncomeBatchDetail,
  IncomeBatchListResponse,
  // 🗂️ [FIN-V2 / P5.1 API → P5.2 UI] ทะเบียนเอกสารรวม
  DocumentDetail,
  DocumentListQuery,
  DocumentListResponse,
  DocumentRefItem,
  DocumentType,
  // 🧾 [FIN-V2 / P5.4 API → P5.5 UI] ใบรับทราบยอดค้าง + รายงานปิดงบเดือน
  AckDetailResponse,
  AckIssueRequest,
  AckIssueResponse,
  AckListResponse,
  MonthlyReportCreate,
  MonthlyReportDetailResponse,
  MonthlyReportListResponse,
  MonthlyReportStatus,
  // 🚫✂️ [FIN-V2 / P6.1+P6.2 API → P6.3 UI] ยกเลิกเอกสาร/เหตุการณ์เงิน + ตัดหนี้/ให้ส่วนลดบิล
  VoidRequest,
  VoidResponse,
  BillAdjustmentRequest,
  BillAdjustmentResponse,
  BillAdjustmentListResponse,
  // 📊 [FIN-V2 / P6.4] เงินของห้อง "ตอนนี้" (snapshot ปัจจุบัน — ไม่ผูกงวดเดือน)
  MoneyOwnership,
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

  // 🏦 [F6] รับ payload ทั้งก้อนแทน `name: string` เดิม เพราะกระเป๋าต้องเก็บ "ช่องทางจ่าย"
  //    (เงินสด/โอน + ธนาคาร/เลขที่บัญชี) ที่ใบสำคัญจ่ายดึงไปพิมพ์
  //    ⚠️ ฝั่ง backend เป็น PATCH + `exclude_unset=True` ⇒ ฟิลด์ที่ไม่ส่งมา **ไม่ถูกแตะ**
  async updateAccount(roomId: number, accountId: number, payload: AccountUpdate): Promise<ApiSuccessResponse> {
    return await api.patch(`/api/classroom/${roomId}/finance/accounts/${accountId}?target_type=room`, payload) as unknown as ApiSuccessResponse;
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

  // 🧾 [F6] บันทึกรายจ่าย/รายรับ → ออกใบสำคัญจ่าย (`PV-`) หรือใบรับเงิน (`INC-`) ให้ด้วย
  //    🔑 ต้องเป็น `TransactionCreateResponse` ไม่ใช่ `ApiSuccessResponse` เปล่า ๆ
  //       ไม่งั้นเลขเอกสารที่ backend ส่งมาจะถูก TypeScript ตัดทิ้งเงียบ ๆ ที่ฝั่งจอ
  //       (ฝั่ง backend ก็มีกับดักเดียวกันที่ `response_model=` — ดูคอมเมนต์ใน
  //       `routers/finance/transactions.py`)
  async addTransaction(roomId: number, payload: TransactionCreate): Promise<TransactionCreateResponse> {
    return await api.post(`/api/classroom/${roomId}/finance/transactions?target_type=room`, payload) as unknown as TransactionCreateResponse;
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

  // 🧾 [P6.5] เรียกเก็บเงินเองรายบุคคล — หลายคน คนละยอด ภายใต้ชื่อเดียวกัน
  //    ⚠️ idempotency_key บังคับ: กดซ้ำคีย์เดิมได้ผลเดิม (ไม่สร้างบิลซ้ำ)
  async createCustomCharges(roomId: number, payload: CustomChargeCreate): Promise<CustomChargeResponse> {
    return await api.post(`/api/classroom/${roomId}/finance/custom-charges?target_type=room`, payload) as unknown as CustomChargeResponse;
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

  /**
   * 💰 หนี้ค้างของ **ตัวเอง** — ปลายทางของการ์ด "บิลค้างชำระ" บนหน้าหลัก (P3.2)
   *
   * predicate ตรงกับตัวนับใน `home/summary` (`SP.status='pending'` ของห้องนี้)
   * ⇒ จำนวนแถวในหน้านี้ = `finance.unpaid_bills` บนการ์ดเสมอ
   * 404 = ยังไม่ได้ผูกโปรไฟล์นักเรียน (ไม่ใช่ "ไม่มีหนี้") — หน้าเรียกต้องแยกสองกรณีนี้
   */
  async getMyDebts(roomId: number): Promise<StudentDebtProfile> {
    return await api.get(`/api/classroom/${roomId}/finance/me/debts?target_type=room`) as unknown as StudentDebtProfile;
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
  //
  // 🧹 [FIN-V2 / P6.5] เมธอดในหมวดนี้ **ไม่มีหน้าจอใช้แล้ว** (ทะเบียนเอกสาร P5.2 +
  //    `resolveDocumentByNo` แทน) — คงไว้เพราะ endpoint ยังเปิดตาม api-v2 §15 และ
  //    bot/สคริปต์ภายนอกอาจเรียก · ห้ามลบเพื่อ "เก็บกวาด" โดยไม่ตรวจผู้เรียกก่อน

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
  //    ⚠️ ต้อง encode — backend บังคับ pattern `^[A-Z]{2,3}-\d{4}-\d{4}$` และเลขที่ไม่ตรงรูปได้ 422
  //    (ผ่อนจาก `{3}` เป็น `{2,3}` ตอน F6 เพื่อให้ `PV-…` ของใบสำคัญจ่ายใช้ได้)
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
  },

  // ════════════════════════════════════════════════════════════════════════════
  // ⚖️ [P5] ค่าปรับ — ประเภทความผิด · ออก/แก้/ยกเลิก · คำขอยกเว้น · คำขอคืนเงิน
  // ════════════════════════════════════════════════════════════════════════════
  // 🔐 อ่าน: สมาชิกห้อง (backend กรองเฉพาะของตัวเองให้) · เขียน: ต้อง MANAGE_FINANCE
  //    ⇒ หน้าจอ gate ปุ่มเขียนด้วย `canManageFinance` ไม่ใช่ `isAdmin`
  // ⚠️ ลำดับ path: `fines/summary` **ต้องเรียกก่อน** `fines/{id}` ในฝั่ง backend แล้ว
  //    (ประกาศ fixed path ก่อน dynamic) — ฝั่ง client ไม่มีปัญหาแต่จำไว้เวลาเพิ่ม route

  // ── ประเภทความผิด ──
  async getFineTypes(roomId: number, activeOnly = false): Promise<FineType[]> {
    return await api.get(`/api/classroom/${roomId}/finance/fine-types`, {
      params: { target_type: 'room', active_only: activeOnly }
    }) as unknown as FineType[];
  },

  async createFineType(roomId: number, payload: FineTypeCreate): Promise<ApiSuccessResponse> {
    return await api.post(
      `/api/classroom/${roomId}/finance/fine-types?target_type=room`,
      payload
    ) as unknown as ApiSuccessResponse;
  },

  // ⚠️ PATCH + `exclude_unset` ฝั่ง backend ⇒ ส่งเฉพาะฟิลด์ที่จะแก้
  async updateFineType(
    roomId: number,
    fineTypeId: number,
    payload: FineTypeUpdate
  ): Promise<ApiSuccessResponse> {
    return await api.patch(
      `/api/classroom/${roomId}/finance/fine-types/${fineTypeId}?target_type=room`,
      payload
    ) as unknown as ApiSuccessResponse;
  },

  async deleteFineType(roomId: number, fineTypeId: number): Promise<ApiSuccessResponse> {
    return await api.delete(
      `/api/classroom/${roomId}/finance/fine-types/${fineTypeId}?target_type=room`
    ) as unknown as ApiSuccessResponse;
  },

  // ── ออกค่าปรับ (หลายคนพร้อมกัน) ──
  // 🔑 `idempotency_key` บังคับ — สร้างด้วย `newIdempotencyKey()` และคงเดิมตลอดการกดครั้งเดียว
  async issueFines(roomId: number, payload: FineIssueRequest): Promise<FineIssueResponse> {
    return await api.post(
      `/api/classroom/${roomId}/finance/fines?target_type=room`,
      payload
    ) as unknown as FineIssueResponse;
  },

  // 🔎 รายการค่าปรับ — `query` ที่ไม่ใส่ = ไม่กรอง (backend default limit 200)
  async listFines(roomId: number, query: FineListQuery = {}): Promise<FineListResponse> {
    return await api.get(`/api/classroom/${roomId}/finance/fines`, {
      params: { target_type: 'room', ...query }
    }) as unknown as FineListResponse;
  },

  async getFine(roomId: number, fineId: number): Promise<FineDetail> {
    return await api.get(
      `/api/classroom/${roomId}/finance/fines/${fineId}`,
      { params: { target_type: 'room' } }
    ) as unknown as FineDetail;
  },

  // ✏️ แก้ไขก่อนจ่ายเท่านั้น (backend บล็อกถ้ามีการจ่ายแล้ว) — void/ออก INV ใหม่ให้เอง
  async updateFine(
    roomId: number,
    fineId: number,
    payload: FineUpdateRequest
  ): Promise<ApiSuccessResponse> {
    return await api.patch(
      `/api/classroom/${roomId}/finance/fines/${fineId}?target_type=room`,
      payload
    ) as unknown as ApiSuccessResponse;
  },

  // ❌ ยกเลิกก่อนจ่าย (กลับ journal + soft delete บิล) — จ่ายแล้วต้องใช้ยกเว้น/คืนเงิน
  async cancelFine(
    roomId: number,
    fineId: number,
    payload: FineCancelRequest = {}
  ): Promise<ApiSuccessResponse> {
    return await api.post(
      `/api/classroom/${roomId}/finance/fines/${fineId}/cancel?target_type=room`,
      payload
    ) as unknown as ApiSuccessResponse;
  },

  // 📊 สรุปแดชบอร์ดค่าปรับ — คำนวณฝั่ง backend ทั้งหมด
  async getFineSummary(roomId: number, asOf?: string): Promise<FineSummary> {
    return await api.get(`/api/classroom/${roomId}/finance/fines/summary`, {
      params: { target_type: 'room', as_of: asOf }
    }) as unknown as FineSummary;
  },

  // ── คำขอยกเว้น / ลด ──
  async requestWaiver(
    roomId: number,
    fineId: number,
    payload: FineWaiverCreate
  ): Promise<FineWaiverActionResponse> {
    return await api.post(
      `/api/classroom/${roomId}/finance/fines/${fineId}/waivers?target_type=room`,
      payload
    ) as unknown as FineWaiverActionResponse;
  },

  async listWaivers(
    roomId: number,
    query: { status?: string; fine_id?: number; limit?: number; offset?: number } = {}
  ): Promise<FineWaiverListResponse> {
    return await api.get(`/api/classroom/${roomId}/finance/fine-waivers`, {
      params: { target_type: 'room', ...query }
    }) as unknown as FineWaiverListResponse;
  },

  // ⚠️ backend ปฏิเสธ 403 ถ้าผู้อนุมัติเป็นผู้สร้างค่าปรับหรือผู้ขอ (ห้ามอนุมัติตัวเอง)
  async approveWaiver(
    roomId: number,
    waiverId: number,
    payload: FineWaiverDecision = {}
  ): Promise<FineWaiverActionResponse> {
    return await api.post(
      `/api/classroom/${roomId}/finance/fine-waivers/${waiverId}/approve?target_type=room`,
      payload
    ) as unknown as FineWaiverActionResponse;
  },

  async rejectWaiver(
    roomId: number,
    waiverId: number,
    payload: FineWaiverDecision = {}
  ): Promise<FineWaiverActionResponse> {
    return await api.post(
      `/api/classroom/${roomId}/finance/fine-waivers/${waiverId}/reject?target_type=room`,
      payload
    ) as unknown as FineWaiverActionResponse;
  },

  async cancelWaiver(
    roomId: number,
    waiverId: number,
    payload: FineWaiverDecision = {}
  ): Promise<FineWaiverActionResponse> {
    return await api.post(
      `/api/classroom/${roomId}/finance/fine-waivers/${waiverId}/cancel?target_type=room`,
      payload
    ) as unknown as FineWaiverActionResponse;
  },

  // ── คำขอคืนเงิน ──
  async requestRefund(
    roomId: number,
    fineId: number,
    payload: FineRefundCreate
  ): Promise<FineRefundActionResponse> {
    return await api.post(
      `/api/classroom/${roomId}/finance/fines/${fineId}/refunds?target_type=room`,
      payload
    ) as unknown as FineRefundActionResponse;
  },

  async listRefunds(
    roomId: number,
    query: { status?: string; fine_id?: number; limit?: number; offset?: number } = {}
  ): Promise<FineRefundListResponse> {
    return await api.get(`/api/classroom/${roomId}/finance/fine-refunds`, {
      params: { target_type: 'room', ...query }
    }) as unknown as FineRefundListResponse;
  },

  // อนุมัติ = จ่ายเงินจริง (PV-) — backend ตรวจยอดกระเป๋าพอ + ห้ามอนุมัติตัวเอง
  async approveRefund(
    roomId: number,
    refundId: number,
    payload: FineRefundDecision = {}
  ): Promise<FineRefundActionResponse> {
    return await api.post(
      `/api/classroom/${roomId}/finance/fine-refunds/${refundId}/approve?target_type=room`,
      payload
    ) as unknown as FineRefundActionResponse;
  },

  async rejectRefund(
    roomId: number,
    refundId: number,
    payload: FineRefundDecision = {}
  ): Promise<FineRefundActionResponse> {
    return await api.post(
      `/api/classroom/${roomId}/finance/fine-refunds/${refundId}/reject?target_type=room`,
      payload
    ) as unknown as FineRefundActionResponse;
  },

  async cancelRefund(
    roomId: number,
    refundId: number,
    payload: FineRefundDecision = {}
  ): Promise<FineRefundActionResponse> {
    return await api.post(
      `/api/classroom/${roomId}/finance/fine-refunds/${refundId}/cancel?target_type=room`,
      payload
    ) as unknown as FineRefundActionResponse;
  },

  // ── 📊 รายงานอายุหนี้ ──
  async getReceivablesAging(roomId: number, asOf?: string): Promise<AgingResponse> {
    return await api.get(`/api/classroom/${roomId}/finance/receivables/aging`, {
      params: { target_type: 'room', as_of: asOf }
    }) as unknown as AgingResponse;
  },

  // ──────────────────────────── 👥 ผู้เกี่ยวข้องทางการเงิน (FIN-V2 / P1.2)
  // 🔒 ปุ่มเขียนต้อง gate ด้วย `canManageFinance` — backend บังคับ MANAGE_FINANCE อยู่แล้ว
  //    แต่การซ่อนปุ่มทำให้ผู้ใช้ไม่ต้องเจอ 403 โดยไม่รู้สาเหตุ
  async getPeople(
    roomId: number,
    query: { type?: string; active?: boolean; q?: string } = {}
  ): Promise<FinancePerson[]> {
    const res = await api.get(`/api/classroom/${roomId}/finance/people`, {
      params: { target_type: 'room', ...query }
    }) as unknown as PersonListResponse;
    return res.people;
  },

  async createPerson(roomId: number, payload: PersonCreate): Promise<FinancePerson> {
    return await api.post(
      `/api/classroom/${roomId}/finance/people?target_type=room`,
      payload
    ) as unknown as FinancePerson;
  },

  async updatePerson(
    roomId: number,
    personId: number,
    payload: PersonUpdate
  ): Promise<FinancePerson> {
    return await api.patch(
      `/api/classroom/${roomId}/finance/people/${personId}?target_type=room`,
      payload
    ) as unknown as FinancePerson;
  },

  // ปิดใช้งาน = soft delete ฝั่ง backend (แถวเดิมยังอยู่เพื่อการตรวจสอบ)
  async deletePerson(roomId: number, personId: number): Promise<{ status: string }> {
    return await api.delete(
      `/api/classroom/${roomId}/finance/people/${personId}?target_type=room`
    ) as unknown as { status: string };
  },

  async syncStudents(roomId: number): Promise<PeopleSyncResult> {
    return await api.post(
      `/api/classroom/${roomId}/finance/people/sync-students?target_type=room`
    ) as unknown as PeopleSyncResult;
  },

  async getFinanceSettings(roomId: number): Promise<FinanceSettings> {
    return await api.get(
      `/api/classroom/${roomId}/finance/settings?target_type=room`
    ) as unknown as FinanceSettings;
  },

  async updateFinanceSettings(
    roomId: number,
    payload: FinanceSettingsUpdate
  ): Promise<FinanceSettings> {
    return await api.patch(
      `/api/classroom/${roomId}/finance/settings?target_type=room`,
      payload
    ) as unknown as FinanceSettings;
  },

  // ──────────────────────────── 👤 บัญชีรายบุคคล (FIN-V2 / P1.4)
  // อ่านอย่างเดียว — สมาชิกห้องอ่านได้ (backend `require_member`) ⇒ ไม่มี gate ฝั่งนี้
  // ค่าที่ `undefined` ถูก axios ตัดทิ้งเอง ⇒ ส่ง `params` ตรง ๆ ได้ ไม่ต้องประกอบเอง

  async getIndividualAccounts(
    roomId: number,
    params: IndividualAccountQuery = {}
  ): Promise<IndividualAccountListResponse> {
    return await api.get(`/api/classroom/${roomId}/finance/individual-accounts`, {
      params: { target_type: 'room', ...params }
    }) as unknown as IndividualAccountListResponse;
  },

  async getIndividualAccount(
    roomId: number,
    studentId: number
  ): Promise<IndividualAccountDetailResponse> {
    return await api.get(
      `/api/classroom/${roomId}/finance/individual-accounts/${studentId}?target_type=room`
    ) as unknown as IndividualAccountDetailResponse;
  },

  async getStudentStatement(
    roomId: number,
    studentId: number,
    params: StudentStatementQuery = {}
  ): Promise<StudentStatementResponse> {
    return await api.get(
      `/api/classroom/${roomId}/finance/individual-accounts/${studentId}/statement`,
      { params: { target_type: 'room', ...params } }
    ) as unknown as StudentStatementResponse;
  },

  // ──────────────────────── 💸 รับเงิน 1 ครั้ง = 1 event (FIN-V2 / P2.3)
  // 🔴 เส้นใหม่เท่านั้น: 1 event → 1 REC (หลายบรรทัด) + DEP — ห้ามใช้
  //    `confirmPayment`/`confirmBatchPayment` แทน (เส้นเดิมออกใบเสร็จแยกต่อบิล)
  // ⚠️ เงินส่งเป็น **string 2 ตำแหน่ง** ตามสัญญา api-v2 §4 (Decimal ฝั่ง backend)

  async previewPaymentEvent(
    roomId: number,
    payload: AllocationPreviewRequest
  ): Promise<AllocationPreviewResponse> {
    return await api.post(
      `/api/classroom/${roomId}/finance/payment-events/preview?target_type=room`,
      payload
    ) as unknown as AllocationPreviewResponse;
  },

  async createPaymentEvent(
    roomId: number,
    payload: PaymentEventCreate
  ): Promise<PaymentEventResult> {
    return await api.post(
      `/api/classroom/${roomId}/finance/payment-events?target_type=room`,
      payload
    ) as unknown as PaymentEventResult;
  },

  // 📥 [FIN-V2 / P2.7] รับเงินหลายคนในรอบเดียว — 1 คำขอ = 1 transaction
  //    = all-or-nothing · replay ด้วยคีย์+reference_no เดิม ⇒ `reused=true`
  async createBulkPaymentEvent(
    roomId: number,
    payload: BulkPaymentEventCreate
  ): Promise<BulkPaymentEventResult> {
    return await api.post(
      `/api/classroom/${roomId}/finance/payment-events/bulk?target_type=room`,
      payload
    ) as unknown as BulkPaymentEventResult;
  },

  // ──────────────────── 💳 ช่องทางชำระเงิน + PromptPay QR (FIN-V2 / P2.5)
  // 🔴 `account_number`/`promptpay_id` เป็น write-only: ส่งได้เฉพาะตอนสร้าง/แก้
  //    — response มีแต่ `*_masked` ⇒ ห้ามนำค่า mask ใส่ payload (จะถูกเก็บเป็นเลขจริง)
  // 🔓 อ่านรายการได้ทุกสมาชิกห้อง (backend `require_member`) ⇒ ไม่ gate ฝั่งนี้

  async getPaymentChannels(roomId: number, includeInactive = false): Promise<PaymentChannel[]> {
    const res = (await api.get(`/api/classroom/${roomId}/finance/payment-channels`, {
      params: { target_type: 'room', include_inactive: includeInactive }
    })) as unknown as PaymentChannelListResponse;
    return res.channels;
  },

  async createPaymentChannel(
    roomId: number,
    payload: PaymentChannelCreate
  ): Promise<PaymentChannel> {
    return await api.post(
      `/api/classroom/${roomId}/finance/payment-channels?target_type=room`,
      payload
    ) as unknown as PaymentChannel;
  },

  async updatePaymentChannel(
    roomId: number,
    channelId: number,
    payload: PaymentChannelUpdate
  ): Promise<PaymentChannel> {
    return await api.patch(
      `/api/classroom/${roomId}/finance/payment-channels/${channelId}?target_type=room`,
      payload
    ) as unknown as PaymentChannel;
  },

  async deletePaymentChannel(
    roomId: number,
    channelId: number
  ): Promise<ApiSuccessResponse> {
    return await api.delete(
      `/api/classroom/${roomId}/finance/payment-channels/${channelId}?target_type=room`
    ) as unknown as ApiSuccessResponse;
  },

  /**
   * SVG ของ PromptPay QR (server สร้างจากเลขที่เก็บไว้ — payload ไม่เคยออกจาก backend)
   *
   * ⚠️ `amount` ส่ง **เฉพาะ** ช่องทาง `qr_mode='fixed'` (backend ตอบ 400 ถ้า open + amount
   *    และถ้า fixed ไม่มี amount) — ส่งเป็นสตริง 2 ตำแหน่งตรงกับสัญญา Decimal
   */
  async getPaymentChannelQr(
    roomId: number,
    channelId: number,
    amount?: number
  ): Promise<Blob> {
    const params: Record<string, string | number> = { target_type: 'room' };
    if (amount !== undefined && amount !== null) params.amount = amount.toFixed(2);
    return await api.get(
      `/api/classroom/${roomId}/finance/payment-channels/${channelId}/qr.svg`,
      { params, responseType: 'blob' }
    ) as unknown as Blob;
  },

  // ──────────────────── 👜 เงินสดรอส่งมอบ (FIN-V2 / P3.1 API → P3.2 UI)
  // 🔓 อ่าน: `require_member` — ทุกสมาชิกห้องเห็นยอด/ความเคลื่อนไหวได้
  // 🔒 เขียน: `MANAGE_FINANCE` (backend 403) — UI ซ่อนปุ่มด้วย `canManageFinance`
  // ⚠️ หลัง mutation ทุกครั้งให้เรียก `getCustody` ใหม่เสมอ — ห้ามคำนวณยอดฝั่งจอ

  async getCustody(roomId: number): Promise<CustodyListResponse> {
    return await api.get(
      `/api/classroom/${roomId}/finance/custody?target_type=room`
    ) as unknown as CustodyListResponse;
  },

  async createCustodyAccount(
    roomId: number,
    payload: CustodyAccountCreate
  ): Promise<CustodyAccount> {
    return await api.post(
      `/api/classroom/${roomId}/finance/custody/accounts?target_type=room`,
      payload
    ) as unknown as CustodyAccount;
  },

  async createCustodyHandover(
    roomId: number,
    payload: CustodyHandoverCreate
  ): Promise<CustodyHandover> {
    return await api.post(
      `/api/classroom/${roomId}/finance/custody/handover?target_type=room`,
      payload
    ) as unknown as CustodyHandover;
  },

  async getCustodyMovements(
    roomId: number,
    personId: number,
    params: { from?: string; to?: string } = {}
  ): Promise<CustodyMovementListResponse> {
    const query: Record<string, string | number> = { target_type: 'room' };
    if (params.from) query.from_date = params.from;
    if (params.to) query.to_date = params.to;
    return await api.get(
      `/api/classroom/${roomId}/finance/custody/${personId}/movements`,
      { params: query }
    ) as unknown as CustodyMovementListResponse;
  },

  async voidCustodyHandover(
    roomId: number,
    handoverId: number,
    payload: { reason: string }
  ): Promise<ApiSuccessResponse> {
    return await api.post(
      `/api/classroom/${roomId}/finance/custody/handovers/${handoverId}/void?target_type=room`,
      payload
    ) as unknown as ApiSuccessResponse;
  },

  // ═══ 📜 [FIN-V2 / P3.4] ประวัติการรับเงิน ═══════════════════════════════
  // อ่านอย่างเดียว — event + custody handover ในไทม์ไลน์เดียว, cursor 3 คีย์
  // ⚠️ ต้องตัด key ที่เป็น `undefined`/`''` ออกก่อนส่ง ไม่งั้น axios จะส่ง
  //    `?student_id=undefined` แล้ว backend ตอบ 422
  async getPaymentHistory(
    roomId: number,
    params: PaymentHistoryQuery = {}
  ): Promise<PaymentHistoryResponse> {
    const query: Record<string, string | number> = { target_type: 'room' };
    for (const [key, value] of Object.entries(params)) {
      if (value === undefined || value === null || value === '') continue;
      query[key] = value;
    }
    return await api.get(
      `/api/classroom/${roomId}/finance/payment-history`,
      { params: query }
    ) as unknown as PaymentHistoryResponse;
  },

  // ═══ 💳 [FIN-V2 / P3.5] หักเครดิตหลายคนเป็นรอบเดียว ═══════════════════════
  // 1 รอบ = 1 transaction = all-or-nothing · ไม่มีเงินเคลื่อนไหว (เครดิตไม่ใช่เงินสด)
  // 🔁 ยิงซ้ำด้วยคีย์เดิม + ชุดเดิม ⇒ `reused=true` (ผลเท่าเดิม)
  // 🔴 คีย์เดิม + ชุดนักเรียนต่าง ⇒ 409 — ต้องโหลดรายชื่อใหม่ ห้าม retry ด้วยคีย์เดิม
  async createCreditRound(
    roomId: number,
    payload: CreditRoundCreate
  ): Promise<CreditRoundResponse> {
    return await api.post(
      `/api/classroom/${roomId}/finance/credits/rounds?target_type=room`,
      payload
    ) as unknown as CreditRoundResponse;
  },

  // ═══ 💸 [FIN-V2 / P4.3] ใบสำคัญจ่ายหลายบรรทัด ═══════════════════════════
  // อ่านเปิดให้ member · เขียนต้องมี MANAGE_FINANCE (backend ตอบ 403 เอง)
  // 🔁 retry คีย์เดิม + payload เดิม ⇒ 200 `reused=true` (ใบเดิม)
  // 🔴 คีย์เดิม + payload ต่าง ⇒ 409 — หน้าจอต้องมีปุ่ม "เริ่มใบใหม่" (คีย์ใหม่)
  async getExpenseVouchers(
    roomId: number,
    params: { from?: string; to?: string; status?: 'active' | 'voided' } = {}
  ): Promise<ExpenseVoucherListResponse> {
    // ⚠️ ตัด key ที่เป็น `undefined`/`''` ออก ไม่งั้น axios ส่ง `from=undefined` → 422
    const query: Record<string, string> = { target_type: 'room' };
    for (const [key, value] of Object.entries(params)) {
      if (value === undefined || value === '') continue;
      query[key] = value;
    }
    return await api.get(
      `/api/classroom/${roomId}/finance/expense-vouchers`,
      { params: query }
    ) as unknown as ExpenseVoucherListResponse;
  },

  async getExpenseVoucher(roomId: number, id: number): Promise<ExpenseVoucherDetail> {
    return await api.get(
      `/api/classroom/${roomId}/finance/expense-vouchers/${id}?target_type=room`
    ) as unknown as ExpenseVoucherDetail;
  },

  async createExpenseVoucher(
    roomId: number,
    payload: ExpenseVoucherCreate
  ): Promise<ExpenseVoucherCreateResponse> {
    return await api.post(
      `/api/classroom/${roomId}/finance/expense-vouchers?target_type=room`,
      payload
    ) as unknown as ExpenseVoucherCreateResponse;
  },

  // 🖨️ PDF มาจาก P4.6 ตัวเดียว (`GET .../{id}/pdf`) — ห้ามสร้าง print view ในหน้า
  async downloadExpenseVoucherPdf(roomId: number, id: number): Promise<Blob> {
    return await api.get(
      `/api/classroom/${roomId}/finance/expense-vouchers/${id}/pdf`,
      { params: { target_type: 'room' }, responseType: 'blob' }
    ) as unknown as Blob;
  },

  // ==========================================
  // 💰 [FIN-V2 / P4.4 API → P4.5 UI] ใบรับเงินหลายบรรทัด (income batch)
  // ==========================================

  async getIncomeBatches(
    roomId: number,
    params: { from?: string; to?: string; status?: 'active' | 'voided' } = {}
  ): Promise<IncomeBatchListResponse> {
    const query: Record<string, string> = { target_type: 'room' };
    for (const [key, value] of Object.entries(params)) {
      if (value === undefined || value === '') continue;
      query[key] = value;
    }
    return await api.get(
      `/api/classroom/${roomId}/finance/income-batches`,
      { params: query }
    ) as unknown as IncomeBatchListResponse;
  },

  async getIncomeBatch(roomId: number, id: number): Promise<IncomeBatchDetail> {
    return await api.get(
      `/api/classroom/${roomId}/finance/income-batches/${id}?target_type=room`
    ) as unknown as IncomeBatchDetail;
  },

  async createIncomeBatch(
    roomId: number,
    payload: IncomeBatchCreate
  ): Promise<IncomeBatchCreateResponse> {
    return await api.post(
      `/api/classroom/${roomId}/finance/income-batches?target_type=room`,
      payload
    ) as unknown as IncomeBatchCreateResponse;
  },

  // 🖨️ PDF มาจาก P4.6 ตัวเดียว (`GET .../{id}/pdf`) — ห้ามสร้าง print view ในหน้า
  async downloadIncomeBatchPdf(roomId: number, id: number): Promise<Blob> {
    return await api.get(
      `/api/classroom/${roomId}/finance/income-batches/${id}/pdf`,
      { params: { target_type: 'room' }, responseType: 'blob' }
    ) as unknown as Blob;
  },

  // ==========================================
  // 🗂️ [FIN-V2 / P5.1 API → P5.2 UI] ทะเบียนเอกสารรวม
  // ==========================================
  //
  // 🔓 อ่านเปิดให้สมาชิก (`require_member` ฝั่ง backend) — ไม่มีเมธอดเขียนในกลุ่มนี้
  // ⚠️ `doc_types` ส่งเป็นสตริงคั่นจุลภาค และ `status: 'all'` → `include_voided=true`
  //    — แปลงที่ `buildDocumentQuery` (utils/documentFilters.ts) ที่เดียว

  async getDocuments(
    roomId: number,
    query: DocumentListQuery = {}
  ): Promise<DocumentListResponse> {
    return await api.get(
      `/api/classroom/${roomId}/finance/documents`,
      { params: { target_type: 'room', ...buildDocumentQuery(query) } }
    ) as unknown as DocumentListResponse;
  },

  async getDocumentDetail(
    roomId: number,
    docType: DocumentType,
    docId: number
  ): Promise<DocumentDetail> {
    return await api.get(
      `/api/classroom/${roomId}/finance/documents/${docType}/${docId}?target_type=room`
    ) as unknown as DocumentDetail;
  },

  // 🔗 resolver สำหรับลิงก์เก่า/ค้นด้วยเลขเอกสาร — 404 เมื่อไม่พบ (ข้อความไทยจาก backend)
  async resolveDocumentByNo(roomId: number, docNo: string): Promise<DocumentDetail> {
    return await api.get(
      `/api/classroom/${roomId}/finance/documents/by-no/${encodeURIComponent(docNo)}`,
      { params: { target_type: 'room' } }
    ) as unknown as DocumentDetail;
  },

  async downloadDocumentPdf(
    roomId: number,
    docType: DocumentType,
    docId: number
  ): Promise<Blob> {
    return await api.get(
      `/api/classroom/${roomId}/finance/documents/${docType}/${docId}/pdf`,
      { params: { target_type: 'room' }, responseType: 'blob' }
    ) as unknown as Blob;
  },

  // 🖨️ พิมพ์ชุด ≤100 ใบ (mixed layout ได้) — backend ตอบ 404 ทั้งคำขอถ้ามีใบใดขาด
  async printDocumentBundle(
    roomId: number,
    items: DocumentRefItem[]
  ): Promise<Blob> {
    return await api.post(
      `/api/classroom/${roomId}/finance/documents/print-bundle`,
      { items },
      { params: { target_type: 'room' }, responseType: 'blob' }
    ) as unknown as Blob;
  },

  // ==========================================
  // 🧾 [FIN-V2 / P5.4 API → P5.5 UI] ใบรับทราบยอดค้าง (ACK)
  // ==========================================
  //
  // ⚠️ ACK **ไม่แตะเงิน** — ใบที่ยกเลิกแล้วยังอ่าน/พิมพ์ได้ (เป็นหลักฐานว่าเคยแจ้ง)
  // 🔁 `issueAcknowledgement` ต้องได้ `idempotency_key` เดิมตอน retry
  //    — การสร้างคีย์ใหม่ต่อการกดคือ "ใบที่สอง" ในสายตา backend

  async getAcknowledgements(
    roomId: number,
    params: { from?: string; to?: string; includeVoided?: boolean } = {}
  ): Promise<AckListResponse> {
    const query: Record<string, string> = { target_type: 'room' };
    if (params.from) query.from = params.from;
    if (params.to) query.to = params.to;
    if (params.includeVoided) query.include_voided = 'true';
    return await api.get(
      `/api/classroom/${roomId}/finance/acknowledgements`,
      { params: query }
    ) as unknown as AckListResponse;
  },

  async getAcknowledgement(
    roomId: number,
    receiptNo: string
  ): Promise<AckDetailResponse> {
    return await api.get(
      `/api/classroom/${roomId}/finance/acknowledgements/${encodeURIComponent(receiptNo)}`,
      { params: { target_type: 'room' } }
    ) as unknown as AckDetailResponse;
  },

  async issueAcknowledgement(
    roomId: number,
    payload: AckIssueRequest
  ): Promise<AckIssueResponse> {
    return await api.post(
      `/api/classroom/${roomId}/finance/acknowledgements?target_type=room`,
      payload
    ) as unknown as AckIssueResponse;
  },

  async voidAcknowledgement(
    roomId: number,
    receiptNo: string,
    payload: { reason: string }
  ): Promise<ApiSuccessResponse> {
    return await api.post(
      `/api/classroom/${roomId}/finance/acknowledgements/${encodeURIComponent(receiptNo)}/void?target_type=room`,
      payload
    ) as unknown as ApiSuccessResponse;
  },

  /**
   * 🖨️ PDF ของ ACK — **ไม่มี** route เฉพาะของ ACK ใน backend (P5.4 ไม่ออกเส้นทางพิมพ์)
   * ⇒ ใช้เส้นทางทะเบียนเอกสาร: `GET /finance/documents/acknowledgement/{doc_id}/pdf`
   * ซึ่งเดินผ่าน adapter `(2, 'acknowledgement')` ของ P5.3 (ไบต์เดียวกับที่พิมพ์ชุด)
   *
   * ⚠️ ต้องรู้ `doc_id` (int) ไม่ใช่เลขที่เอกสาร ⇒ อ่าน detail ก่อน 1 คำขอ
   *    (ยอมจ่ายหนึ่ง round-trip แลกกับการไม่ต้องให้หน้าจอรู้จัก id ภายใน)
   */
  async downloadAckPdf(roomId: number, receiptNo: string): Promise<Blob> {
    const detail = (await api.get(
      `/api/classroom/${roomId}/finance/acknowledgements/${encodeURIComponent(receiptNo)}`,
      { params: { target_type: 'room' } }
    )) as unknown as AckDetailResponse;
    return await api.get(
      `/api/classroom/${roomId}/finance/documents/acknowledgement/${detail.receipt.id}/pdf`,
      { params: { target_type: 'room' }, responseType: 'blob' }
    ) as unknown as Blob;
  },

  // ==========================================
  // 📊 [FIN-V2 / P5.4 API → P5.5 UI] รายงานปิดงบเดือน (RPT)
  // ==========================================
  //
  // 🔴 `counted_cash` ส่งเป็น **string** 2 ตำแหน่ง (`"12345.00"`) — Pydantic
  //    แปลง Decimal จากสตริงได้ตรง ๆ ส่วน number จาก input มีเศษ 1e-12 ได้
  //    แล้ว backend จะตอบ 400 "ยอดต่าง" ทั้งที่ผู้ใช้นับถูก

  async getMonthlyReports(
    roomId: number,
    params: { year?: number; status?: MonthlyReportStatus } = {}
  ): Promise<MonthlyReportListResponse> {
    const query: Record<string, string> = { target_type: 'room' };
    if (params.year !== undefined) query.year = String(params.year);
    if (params.status) query.status = params.status;
    return await api.get(
      `/api/classroom/${roomId}/finance/monthly-reports`,
      { params: query }
    ) as unknown as MonthlyReportListResponse;
  },

  async getMonthlyReport(
    roomId: number,
    id: number
  ): Promise<MonthlyReportDetailResponse> {
    return await api.get(
      `/api/classroom/${roomId}/finance/monthly-reports/${id}?target_type=room`
    ) as unknown as MonthlyReportDetailResponse;
  },

  // ⚠️ backend ตอบ `MonthlyReportDetailResponse` (report + signatures) ไม่ใช่ report เดี่ยว
  async createMonthlyReport(
    roomId: number,
    payload: MonthlyReportCreate
  ): Promise<MonthlyReportDetailResponse> {
    return await api.post(
      `/api/classroom/${roomId}/finance/monthly-reports?target_type=room`,
      payload
    ) as unknown as MonthlyReportDetailResponse;
  },

  async finalizeMonthlyReport(
    roomId: number,
    id: number,
    payload: { counted_cash: string; note?: string }
  ): Promise<MonthlyReportDetailResponse> {
    return await api.post(
      `/api/classroom/${roomId}/finance/monthly-reports/${id}/finalize?target_type=room`,
      payload
    ) as unknown as MonthlyReportDetailResponse;
  },

  async voidMonthlyReport(
    roomId: number,
    id: number,
    payload: { reason: string }
  ): Promise<ApiSuccessResponse> {
    return await api.post(
      `/api/classroom/${roomId}/finance/monthly-reports/${id}/void?target_type=room`,
      payload
    ) as unknown as ApiSuccessResponse;
  },

  // 🖨️ PDF ใช้ `Content-Disposition` ฝั่ง backend — ชื่อไฟล์ที่ FE ตั้งต้องตรงกัน
  async downloadMonthlyReportPdf(roomId: number, id: number): Promise<Blob> {
    return await api.get(
      `/api/classroom/${roomId}/finance/monthly-reports/${id}/pdf`,
      { params: { target_type: 'room' }, responseType: 'blob' }
    ) as unknown as Blob;
  },

  // ══════════════════════════════════════════════════════════════════════════
  // 🚫 [FIN-V2 / P6.1 → P6.3] ยกเลิกเอกสาร/เหตุการณ์เงิน
  // ══════════════════════════════════════════════════════════════════════════
  // ⚠️ `/documents/{doc_type}/{id}/void` รับเฉพาะ `invoice` (REC/DEP → 409 ชี้ไป event,
  //    CERT → 409 ชี้ไป PV, ACK/RPT → endpoint ของมันเอง) — backend เป็นผู้ตัดสิน ไม่เดาที่จอ
  // 🔴 ไม่มี idempotency key โดยเจตนา: void เปลี่ยนสถานะซ้ำไม่ได้ การกดซ้ำต้องได้ 409

  async voidDocument(
    roomId: number,
    docType: string,
    docId: number,
    payload: VoidRequest
  ): Promise<VoidResponse> {
    return await api.post(
      `/api/classroom/${roomId}/finance/documents/${docType}/${docId}/void?target_type=room`,
      payload
    ) as unknown as VoidResponse;
  },

  async voidPaymentEvent(
    roomId: number,
    eventId: number,
    payload: VoidRequest
  ): Promise<VoidResponse> {
    return await api.post(
      `/api/classroom/${roomId}/finance/payment-events/${eventId}/void?target_type=room`,
      payload
    ) as unknown as VoidResponse;
  },

  async voidExpenseVoucher(
    roomId: number,
    voucherId: number,
    payload: VoidRequest
  ): Promise<VoidResponse> {
    return await api.post(
      `/api/classroom/${roomId}/finance/expense-vouchers/${voucherId}/void?target_type=room`,
      payload
    ) as unknown as VoidResponse;
  },

  async voidIncomeBatch(
    roomId: number,
    batchId: number,
    payload: VoidRequest
  ): Promise<VoidResponse> {
    return await api.post(
      `/api/classroom/${roomId}/finance/income-batches/${batchId}/void?target_type=room`,
      payload
    ) as unknown as VoidResponse;
  },

  // ══════════════════════════════════════════════════════════════════════════
  // ✂️ [FIN-V2 / P6.2 → P6.3] ตัดหนี้ / ให้ส่วนลดบิลโครงการ
  // ══════════════════════════════════════════════════════════════════════════
  // 🔑 `idempotency_key` สร้างตอนเปิด modal (stable ต่อ retry) — ส่งซ้ำคีย์เดิมได้ผลเดิม

  async writeOffBill(
    roomId: number,
    paymentId: number,
    payload: BillAdjustmentRequest
  ): Promise<BillAdjustmentResponse> {
    return await api.post(
      `/api/classroom/${roomId}/finance/payments/${paymentId}/write-off?target_type=room`,
      payload
    ) as unknown as BillAdjustmentResponse;
  },

  async discountBill(
    roomId: number,
    paymentId: number,
    payload: BillAdjustmentRequest
  ): Promise<BillAdjustmentResponse> {
    return await api.post(
      `/api/classroom/${roomId}/finance/payments/${paymentId}/discount?target_type=room`,
      payload
    ) as unknown as BillAdjustmentResponse;
  },

  async getBillAdjustments(
    roomId: number,
    paymentId: number
  ): Promise<BillAdjustmentListResponse> {
    return await api.get(
      `/api/classroom/${roomId}/finance/payments/${paymentId}/adjustments?target_type=room`
    ) as unknown as BillAdjustmentListResponse;
  },

  // ══════════════════════════════════════════════════════════════════════════
  // 📊 [FIN-V2 / P6.4] แดชบอร์ดเงินของห้อง (snapshot ปัจจุบัน)
  // ══════════════════════════════════════════════════════════════════════════
  // ⚠️ ไม่รับ month/year โดยเจตนา — "ตอนนี้ห้องมีเงินเท่าไหร่" ไม่ใช่ตัวเลขตามงวด
  async getMoneyOwnership(roomId: number): Promise<MoneyOwnership> {
    return await api.get(
      `/api/classroom/${roomId}/finance/dashboard/ownership?target_type=room`
    ) as unknown as MoneyOwnership;
  },
};
