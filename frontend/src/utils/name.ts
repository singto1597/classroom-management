// 🌟 ชื่อสำหรับแสดงผล: ชื่อไทยก่อน (ถ้ามี) แล้วค่อยชื่ออังกฤษ
// — ตามนโยบาย English-primary identity, Thai display (mirror จาก backend/core/name_utils.py)
export interface NameParts {
  first_name?: string | null
  last_name?: string | null
  first_name_en?: string | null
  last_name_en?: string | null
}

export function displayName(p: NameParts): string {
  const thFirst = (p.first_name || '').trim()
  const thLast = (p.last_name || '').trim()
  if (thFirst || thLast) return `${thFirst} ${thLast}`.trim()
  const enFirst = (p.first_name_en || '').trim()
  const enLast = (p.last_name_en || '').trim()
  return `${enFirst} ${enLast}`.trim()
}
