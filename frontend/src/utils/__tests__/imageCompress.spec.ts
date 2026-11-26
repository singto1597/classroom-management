import { describe, expect, it } from 'vitest'
import {
  MAX_DIMENSION,
  WEBP_QUALITY,
  compressImage,
  compressImages,
  fitWithin,
  isHeicLike,
} from '@/utils/imageCompress'

function fileOf(name: string, type: string, bytes = 4): File {
  return new File([new Uint8Array(bytes)], name, { type })
}

describe('fitWithin', () => {
  it('ย่อด้านยาวสุดลงถึงเพดานโดยคงสัดส่วน', () => {
    expect(fitWithin(3200, 2400, 1600)).toEqual({ width: 1600, height: 1200 })
    expect(fitWithin(2400, 3200, 1600)).toEqual({ width: 1200, height: 1600 })
  })

  it('ไม่ขยายรูปที่เล็กกว่าเพดาน', () => {
    expect(fitWithin(800, 600, 1600)).toEqual({ width: 800, height: 600 })
    expect(fitWithin(1600, 900, 1600)).toEqual({ width: 1600, height: 900 })
  })

  it('กันค่าผิดรูป — คืน 0 แทน NaN', () => {
    expect(fitWithin(0, 100)).toEqual({ width: 0, height: 0 })
    expect(fitWithin(Number.NaN, 100)).toEqual({ width: 0, height: 0 })
    expect(fitWithin(-5, 10)).toEqual({ width: 0, height: 0 })
  })

  it('ค่าเริ่มต้นสอดคล้องกับค่าที่ประกาศ', () => {
    expect(MAX_DIMENSION).toBe(1600)
    expect(WEBP_QUALITY).toBe(0.8)
  })
})

describe('isHeicLike', () => {
  it('จับ HEIC/HEIF ได้ทั้งจาก type และนามสกุล', () => {
    expect(isHeicLike(fileOf('a.heic', 'image/heic'))).toBe(true)
    expect(isHeicLike(fileOf('a.heif', 'image/heif'))).toBe(true)
    // บางเบราว์เซอร์รายงาน type ว่าง ⇒ ต้องดูนามสกุลต่อ
    expect(isHeicLike(fileOf('IMG_0001.HEIC', ''))).toBe(true)
  })

  it('ไม่เข้าใจผิดว่า JPEG/PNG เป็น HEIC', () => {
    expect(isHeicLike(fileOf('a.jpg', 'image/jpeg'))).toBe(false)
    expect(isHeicLike(fileOf('a.png', 'image/png'))).toBe(false)
  })
})

describe('compressImage', () => {
  it('ไฟล์ที่ไม่ใช่รูปผ่านออกไปโดยไม่แตะ canvas', async () => {
    const pdf = fileOf('a.pdf', 'application/pdf')
    await expect(compressImage(pdf)).resolves.toBe(pdf)
  })

  it('ถอดรหัสไม่ได้ (jsdom ไม่มี createImageBitmap) ⇒ คืนไฟล์เดิม ไม่ throw', async () => {
    const jpg = fileOf('a.jpg', 'image/jpeg', 32)
    await expect(compressImage(jpg)).resolves.toBe(jpg)
  })

  it('compressImages คงลำดับและคืนไฟล์เดิมเมื่อแปลงไม่ได้', async () => {
    const a = fileOf('a.jpg', 'image/jpeg')
    const b = fileOf('b.pdf', 'application/pdf')
    const out = await compressImages([a, b])
    expect(out[0]).toBe(a)
    expect(out[1]).toBe(b)
  })
})
