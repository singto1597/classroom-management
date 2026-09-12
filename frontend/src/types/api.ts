/**
 * Type ของ "ซองตอบกลับ" (response envelope) ที่ใช้ร่วมกันทุก service
 * อ้างอิงจาก backend/models/finance_schemas.py → SuccessResponse
 */

/** คำตอบสำเร็จมาตรฐานของ backend (ใช้กับการสร้าง/แก้ไข/ลบเกือบทุก endpoint) */
export interface ApiSuccessResponse {
  status: string;
  message?: string | null;
}

/**
 * รูปแบบ error ของ FastAPI/Pydantic (HTTP 422)
 * ใช้ใน services/api.ts เพื่อแกะ `detail` ที่เป็น array ให้เป็นข้อความอ่านรู้เรื่อง
 */
export interface PydanticValidationError {
  loc?: (string | number)[];
  msg?: string;
  type?: string;
}
