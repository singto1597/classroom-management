// 🗜️ ย่อรูปฝั่งเบราว์เซอร์ก่อนอัปโหลด — ลดเวลา/แบนด์วิดท์บนมือถือ
//
// 🔴 **ไม่ใช่ด่านความปลอดภัย** — server แปลงซ้ำเสมอ (ย่อ 1600px · WebP q80 · ล้าง EXIF)
//    ⇒ ไฟล์ที่ผ่านฟังก์ชันนี้ยังต้องผ่าน pipeline ฝั่ง backend เหมือนเดิม
//
// ⚠️ **HEIC จาก iPhone:** Chrome/Android ยังถอดรหัสไม่ได้ ⇒ `createImageBitmap` โยน error
//    ⇒ คืน **ไฟล์ต้นฉบับ** ให้ server แปลงด้วย `pillow-heif` (ห้าม throw ให้ผู้ใช้เห็น error
//    ทั้งที่อัปโหลดได้จริง)
//
// ⚠️ การวาดลง canvas แล้ว `toBlob()` **ล้าง EXIF ให้เองโดยธรรมชาติ** (ไม่มีการคัดลอก metadata)
//    และใช้ `imageOrientation: 'from-image'` เพื่อให้รูปที่ถ่ายเอียงถูกหมุนก่อนวาด

import { UI_COLOR } from '@/constants/theme'

export const MAX_DIMENSION = 1600
export const WEBP_QUALITY = 0.8

/** ส่วนขยาย/ชนิดที่ถือว่าเป็น HEIC — บางเบราว์เซอร์รายงาน `type` เป็นค่าว่าง */
const HEIC_RE = /\.(hei[cf])$/i

export function isHeicLike(file: File): boolean {
  return file.type === 'image/heic' || file.type === 'image/heif' || HEIC_RE.test(file.name)
}

/**
 * ย่อขนาดให้อยู่ภายใน `max` โดยคงสัดส่วน — **ไม่ขยายรูปเล็ก**
 *
 * แยกออกมาเป็นฟังก์ชันบริสุทธิ์เพื่อให้เทสต์ได้ (jsdom ไม่มี canvas จริง)
 */
export function fitWithin(
  width: number,
  height: number,
  max: number = MAX_DIMENSION,
): { width: number; height: number } {
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
    return { width: 0, height: 0 }
  }
  const longest = Math.max(width, height)
  if (longest <= max) return { width: Math.round(width), height: Math.round(height) }
  const scale = max / longest
  return { width: Math.max(1, Math.round(width * scale)), height: Math.max(1, Math.round(height * scale)) }
}

/** ตั้งชื่อไฟล์ใหม่เป็น `.webp` — ใช้เฉพาะตอนแปลงสำเร็จ (ตัวแปลงเป็น WebP) */
function renameToWebp(name: string): string {
  const base = name.replace(/\.[^./\\]+$/, '') || 'image'
  return `${base}.webp`
}

function canvasToBlob(canvas: HTMLCanvasElement): Promise<Blob | null> {
  return new Promise((resolve) => {
    try {
      canvas.toBlob((blob) => resolve(blob), 'image/webp', WEBP_QUALITY)
    } catch {
      resolve(null)
    }
  })
}

/**
 * ย่อ/แปลงเป็น WebP — คืนไฟล์เดิมเมื่อทำไม่ได้ (HEIC, canvas ไม่มี, blob ว่าง)
 *
 * ไม่ throw โดยเจตนา: เป้าหมายคือ "พยายามช่วย" ไม่ใช่ด่านบังคับ
 */
export async function compressImage(file: File, maxDimension = MAX_DIMENSION): Promise<File> {
  if (!file.type.startsWith('image/')) return file

  let bitmap: ImageBitmap
  try {
    bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' })
  } catch {
    // HEIC/HEIF หรือไฟล์ที่เบราว์เซอร์ถอดไม่ได้ → ส่งต้นฉบับให้ server
    return file
  }

  try {
    const target = fitWithin(bitmap.width, bitmap.height, maxDimension)
    if (!target.width || !target.height) return file

    const canvas = document.createElement('canvas')
    canvas.width = target.width
    canvas.height = target.height
    const ctx = canvas.getContext('2d')
    if (!ctx) return file

    // พื้นขาวรองรับ PNG ที่มี alpha — WebP รองรับ alpha ได้ แต่พื้นขาวปลอดภัยกับทุกเบราว์เซอร์
    ctx.fillStyle = UI_COLOR.white
    ctx.fillRect(0, 0, target.width, target.height)
    ctx.drawImage(bitmap, 0, 0, target.width, target.height)

    const blob = await canvasToBlob(canvas)
    if (!blob || blob.size === 0) return file

    return new File([blob], renameToWebp(file.name), {
      type: 'image/webp',
      lastModified: Date.now(),
    })
  } finally {
    bitmap.close()
  }
}

/** ย่อหลายไฟล์พร้อมกัน — ลำดับผลลัพธ์ตรงกับอินพุต (ใช้กับ `Promise.all` ได้) */
export function compressImages(files: File[], maxDimension = MAX_DIMENSION): Promise<File[]> {
  return Promise.all(files.map((f) => compressImage(f, maxDimension)))
}
