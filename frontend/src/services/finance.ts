import api from './api'; 

import type { 
  Account, 
  AccountCreate, 
  Category, 
  CategoryCreate, 
  Transaction, 
  TransactionList,
  TransactionCreate,
  TransferCreate,
  Collection,
  FeeCollectionCreate,
  CollectionStatus,
  FeeCollectionUpdate,
  PaymentConfirm,
  FinanceSummary,
  Debtor,
  StudentDebtProfile,
  BasicStudent // ✨ Import เพิ่มเติม
} from '@/types/finance';

export const FinanceService = {
  // ==========================================
  // 💰 1. Accounts & Categories
  // ==========================================
  
  async getAccounts(roomId: number): Promise<Account[]> {
    return await api.get(`/api/classroom/${roomId}/finance/accounts?target_type=room`) as unknown as Account[];
  },

  async createAccount(roomId: number, payload: AccountCreate): Promise<any> {
    return await api.post(`/api/classroom/${roomId}/finance/accounts?target_type=room`, payload);
  },

  async updateAccount(roomId: number, accountId: number, name: string, userName: string): Promise<any> {
    return await api.patch(`/api/classroom/${roomId}/finance/accounts/${accountId}?target_type=room`, { 
      account_name: name,
      user_name: userName
    });
  },

  async deleteAccount(roomId: number, accountId: number): Promise<any> {
    return await api.delete(`/api/classroom/${roomId}/finance/accounts/${accountId}?target_type=room`);
  },

  async getCategories(roomId: number, type?: 'income' | 'expense'): Promise<Category[]> {
    const params: any = { target_type: 'room' };
    if (type) params.cat_type = type;
    
    return await api.get(`/api/classroom/${roomId}/finance/categories`, { params }) as unknown as Category[];
  },

  async createCategory(roomId: number, payload: CategoryCreate): Promise<any> {
    return await api.post(`/api/classroom/${roomId}/finance/categories?target_type=room`, payload);
  },

  async updateCategory(roomId: number, categoryId: number, name: string, userName: string): Promise<any> {
    return await api.patch(`/api/classroom/${roomId}/finance/categories/${categoryId}?target_type=room`, { 
      category_name: name,
      user_name: userName
    });
  },

  async deleteCategory(roomId: number, categoryId: number): Promise<any> {
    return await api.delete(`/api/classroom/${roomId}/finance/categories/${categoryId}?target_type=room`);
  },

  // ==========================================
  // 💸 2. Transactions & Transfers
  // ==========================================

  async getTransactions(roomId: number, filters: any = {}): Promise<TransactionList> {
    const params = { ...filters, target_type: 'room' };
    return await api.get(`/api/classroom/${roomId}/finance/transactions`, { params }) as unknown as TransactionList;
  },

  async addTransaction(roomId: number, payload: TransactionCreate): Promise<any> {
    return await api.post(`/api/classroom/${roomId}/finance/transactions?target_type=room`, payload);
  },

  async transferMoney(roomId: number, payload: TransferCreate): Promise<any> {
    return await api.post(`/api/classroom/${roomId}/finance/transfer?target_type=room`, payload);
  },

  async revertTransaction(roomId: number, transactionId: number, userName: string): Promise<any> {
    return await api.delete(`/api/classroom/${roomId}/finance/transactions/${transactionId}?target_type=room`, {
      data: { user_name: userName }
    });
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

  async createCollection(roomId: number, payload: FeeCollectionCreate): Promise<any> {
    return await api.post(`/api/classroom/${roomId}/finance/collections?target_type=room`, payload);
  },

  async getCollectionStatus(roomId: number, collectionId: number): Promise<CollectionStatus> {
    return await api.get(`/api/classroom/${roomId}/finance/collections/${collectionId}?target_type=room`) as unknown as CollectionStatus;
  },

  async updateCollection(roomId: number, collectionId: number, payload: FeeCollectionUpdate): Promise<any> {
    return await api.put(`/api/classroom/${roomId}/finance/collections/${collectionId}?target_type=room`, payload);
  },

  async confirmPayment(roomId: number, paymentId: number, payload: PaymentConfirm): Promise<any> {
    return await api.put(`/api/classroom/${roomId}/finance/payments/${paymentId}/pay?target_type=room`, payload);
  },

  // ✨ API สำหรับลบรายชื่อนักเรียนออกจากแคมเปญ
  async removeStudentFromCollection(roomId: number, collectionId: number, studentId: number, userName: string): Promise<any> {
    return await api.delete(`/api/classroom/${roomId}/finance/collections/${collectionId}/students/${studentId}?target_type=room`, {
      data: { user_name: userName }
    });
  },

  // ==========================================
  // 📊 4. Summary & Reports
  // ==========================================

  async getSummary(roomId: number, month?: number, year?: number): Promise<FinanceSummary> {
    const params: any = { target_type: 'room' };
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
  }
};