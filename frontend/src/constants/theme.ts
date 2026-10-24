/**
 * 🎨 สีสำหรับโค้ด JavaScript — SweetAlert2, Chart.js, และ HTML ที่ประกอบเอง
 *
 * ทำไมต้องมีไฟล์นี้แยกจาก Tailwind:
 *   Tailwind แปลงคลาสเป็น CSS ตอน build แต่ SweetAlert2/Chart.js รับ **ค่า hex**
 *   ผ่าน JS ⇒ ก่อนหน้านี้มี hex กระจายอยู่ ~190 จุดใน 40 ไฟล์ (`confirmButtonColor:
 *   '#1d4ed8'` ซ้ำ 96 ครั้ง) ซึ่งแก้พร้อมกันไม่ได้และไม่มีอะไรจับได้เมื่อพิมพ์ผิด
 *
 * ⚠️ ทุกค่าต้องตรงกับสเกลใน `tailwind.config.js` — เป็น "สำเนาที่สอง" โดยเจตนา
 *    เพราะ JS อ่าน CSS variable ไม่ได้ตรง ๆ ในทุกบริบท (Swal รับค่าเป็น prop)
 *    ถ้าเปลี่ยนพาเลตต์ ให้แก้ tailwind.config.js **และ** ไฟล์นี้พร้อมกัน
 *
 * ⚠️ ไฟล์นี้เป็นหนึ่งในสองที่อนุญาตให้มี hex (อีกที่คือ `src/assets/main.css`)
 *    ด่าน `npm run lint:colors` ตรวจ — อย่าเพิ่ม hex ที่อื่น
 */

export const UI_COLOR = {
  // ── แบรนด์ (สิ่งที่กดได้ / สิ่งที่ต้องดู) ──────────────────────────────
  brand: '#1d4ed8', // brand-700 — ปุ่มยืนยันของ Swal, ลิงก์
  brandStrong: '#1e40af', // brand-800
  brandMid: '#2563eb', // brand-600
  brandLight: '#3b82f6', // brand-500
  brandSoft: '#eff6ff', // brand-50 — พื้นป้าย

  // ── สถานะ ─────────────────────────────────────────────────────────────
  ok: '#059669', // ok-600 — เชื่อมต่อแล้ว / สำเร็จ
  okSoft: '#ecfdf5', // ok-50
  okBorder: '#a7f3d0', // ok-200

  warn: '#b45309', // warn-700 — ข้อความ "ข้าม/ค้าง"
  danger: '#dc2626', // danger-600 — ปุ่มยืนยันที่ทำลายข้อมูล
  dangerStrong: '#b91c1c', // danger-700
  dangerSoft: '#fef2f2', // danger-50
  dangerBorder: '#fecaca', // danger-200

  // ── กลาง (stone) ──────────────────────────────────────────────────────
  ink: '#1c1917', // stone-900 — ตัวอักษรหลัก
  neutral: '#78716c', // stone-500 — ปุ่มยกเลิก, คำอธิบาย
  subtle: '#a8a29e', // stone-400 — ข้อความจาง
  border: '#e7e5e4', // stone-200
  surface: '#f5f5f4', // stone-100
  paper: '#fafaf9', // paper
  white: '#ffffff',
} as const

/**
 * สีแบรนด์ของผู้ให้บริการล็อกอิน — เจ้าของแบรนด์กำหนดตายตัว เปลี่ยนเองไม่ได้
 * (โลโก้ Google ใน `views/auth/Login.vue` ก็เป็นสีชุดเดียวกัน)
 */
export const PROVIDER_COLOR = {
  google: '#ea4335',
  discord: '#5865f2',
} as const

/**
 * สีกราฟ — เรียงจาก "สำคัญ" ไป "รอง" ใช้ของแบรนด์ก่อนเสมอ
 * (แยกจาก UI_COLOR เพราะกราฟต้องการชุดที่วางข้างกันแล้วแยกออกได้)
 */
export const CHART_COLORS = [
  UI_COLOR.brand,
  UI_COLOR.brandMid,
  UI_COLOR.brandLight,
  '#93c5fd', // brand-300
  UI_COLOR.neutral,
  UI_COLOR.subtle,
  '#d6d3d1', // stone-300
] as const
