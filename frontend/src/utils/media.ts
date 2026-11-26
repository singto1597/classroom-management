// 🖼️ URL ของสื่อที่ backend ส่งมาเป็น **path relative** — เติม origin ให้ก่อนใช้ใน `<img>`
//
// 🔴 **ทำไม backend ไม่ส่ง absolute URL:** เซิร์ฟเวอร์เห็น request ผ่าน Traefik/Cloudflare
//    จึงไม่รู้ว่าเบราว์เซอร์เข้าผ่านโดเมนไหน (localhost / staging / production)
//    ⇒ การเดา origin ฝั่ง backend = ลิงก์พังอย่างน้อยหนึ่ง environment เสมอ
//
// ⚠️ ค่า `VITE_API_BASE_URL` มี `/` ท้ายได้ (เช่น `https://api.piri.tld/`)
//    ⇒ ตัด `/` ท้ายก่อนต่อ ไม่งั้นได้ `//api/images/...` ซึ่ง Cloudflare ตีความเป็น path อื่น

const API_BASE = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/+$/, '')

/**
 * เติม origin ให้ path ของ backend — ปล่อย absolute URL (`https://…`) ผ่านไปตามเดิม
 * เพื่อให้ผู้เรียกใส่ลิงก์ภายนอกได้โดยไม่ถูกเติมซ้ำ
 */
export function absoluteMediaUrl(path: string): string {
  if (/^https?:\/\//i.test(path)) return path
  if (!path.startsWith('/')) return `${API_BASE}/${path}`
  return `${API_BASE}${path}`
}

/** ขนาดไฟล์แบบอ่านง่าย — ใช้กับ badge/คำอธิบายได้ ไม่ใช่ค่าที่ใช้ตัดสินใจ */
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 KB'
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
