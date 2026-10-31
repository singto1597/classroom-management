import api from './api';
import type { VersionInfo } from '@/types/version';

export const VersionService = {
  /** GET /api/version — ใช้ยืนยันว่า frontend คุยกับ backend image ไหน */
  async getVersion(): Promise<VersionInfo> {
    return await api.get('/api/version');
  },
};
