import axios from 'axios';

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000',
  headers: {
    'Accept': 'application/json',
    'Content-Type': 'application/json',
  },
});

// Interceptor ขาออก
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('access_token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Interceptor ขาเข้า: จัดการ Error และดักจับ 401
api.interceptors.response.use(
  (response) => response.data,
  (error) => {
    if (error.response) {
      if (error.response.status === 401) {
        localStorage.removeItem('access_token');
        window.location.href = '/login';
      }
      
      let detail = error.response.data?.detail || 'เกิดข้อผิดพลาดจาก API';
      
      // ✨ ปลดล็อก Pydantic 422 Error ให้อ่านรู้เรื่อง!
      // ถ้า Backend ส่ง Array Error มา จะจับมาแกะชื่อฟิลด์บอกให้ชัดเจน
      if (Array.isArray(detail)) {
        detail = detail.map((err: any) => {
          const field = err.loc ? err.loc[err.loc.length - 1] : 'Unknown';
          return `ฟิลด์ '${field}': ${err.msg}`;
        }).join('\n');
      }
      
      return Promise.reject(new Error(detail));
    }
    return Promise.reject(new Error('ไม่สามารถเชื่อมต่อกับ Backend ได้: ' + error.message));
  }
);

export default api;