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
  BasicStudent // ✨ Import เพิ่มเติม
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
  }
};
