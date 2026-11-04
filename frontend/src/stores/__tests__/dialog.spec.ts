import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useDialogStore } from '@/stores/dialog'

/**
 * ล็อกสัญญาของกล่องสนทนากลาง — ทุกหน้าเดิมเรียก `Swal.fire` แล้วรอผลแบบ
 * `{ isConfirmed, isDismissed }` ⇒ ตัวแทนต้องคืนค่าเดิมได้ ไม่งั้น migration
 * จะเปลี่ยนพฤติกรรมของหน้าเหล่านั้นเงียบ ๆ
 */

beforeEach(() => {
  setActivePinia(createPinia())
})

afterEach(() => {
  vi.useRealTimers()
})

describe('dialog store', () => {
  it('confirm — กดยืนยันคืน isConfirmed', async () => {
    const dialog = useDialogStore()
    const result = dialog.confirm('ลบรายการนี้?', 'ย้อนกลับไม่ได้')

    expect(dialog.isOpen).toBe(true)
    expect(dialog.options?.showCancelButton).toBe(true)

    await dialog.accept()
    expect(await result).toEqual({ isConfirmed: true, isDismissed: false, value: '' })
    expect(dialog.isOpen).toBe(false)
  })

  it('confirm — ปิด/ยกเลิกคืน isDismissed', async () => {
    const dialog = useDialogStore()
    const result = dialog.confirm('ยืนยัน?')

    dialog.dismiss()
    expect(await result).toEqual({ isConfirmed: false, isDismissed: true, value: '' })
  })

  it('input — ส่งค่าเริ่มต้นและคืนค่าที่พิมพ์', async () => {
    const dialog = useDialogStore()
    const result = dialog.input('ระบุเหตุผล', {
      inputValue: 'เริ่มต้น',
      inputLabel: 'เหตุผล',
    })

    expect(dialog.inputValue).toBe('เริ่มต้น')
    dialog.inputValue = 'แก้ไขแล้ว'
    await dialog.accept()

    expect(await result).toEqual({ isConfirmed: true, isDismissed: false, value: 'แก้ไขแล้ว' })
  })

  it('preConfirm แปลงค่าได้', async () => {
    const dialog = useDialogStore()
    const result = dialog.input('จำนวน', {
      input: 'number',
      preConfirm: (value) => String(Number(value) * 2),
    })

    dialog.inputValue = '21'
    await dialog.accept()

    expect((await result).value).toBe('42')
  })

  it('preConfirm ที่โยน Error ทำให้กล่องค้างและแสดงข้อความ', async () => {
    const dialog = useDialogStore()
    const result = dialog.input('จำนวน', {
      preConfirm: (value) => {
        if (!value.trim()) throw new Error('ต้องกรอกตัวเลข')
      },
    })

    dialog.inputValue = '   '
    await dialog.accept()

    expect(dialog.isOpen).toBe(true)
    expect(dialog.errorMessage).toBe('ต้องกรอกตัวเลข')

    // แก้ค่าแล้วยืนยันได้
    dialog.inputValue = '5'
    await dialog.accept()
    expect((await result).isConfirmed).toBe(true)
  })

  it('fire ซ้อนกัน — กล่องใหม่เปิด และกล่องเดิมถูกยกเลิก', async () => {
    const dialog = useDialogStore()
    const first = dialog.alert('ข้อความแรก')
    const second = dialog.alert('ข้อความที่สอง')

    expect((await first).isDismissed).toBe(true)
    expect(dialog.options?.title).toBe('ข้อความที่สอง')

    dialog.dismiss()
    expect((await second).isDismissed).toBe(true)
  })

  it('notify แสดงแล้วหายเองหลัง 2.8 วินาที', () => {
    vi.useFakeTimers()
    const dialog = useDialogStore()

    dialog.notify('บันทึกแล้ว')
    expect(dialog.toast).toEqual({ message: 'บันทึกแล้ว', icon: 'success' })

    vi.advanceTimersByTime(2800)
    expect(dialog.toast).toBeNull()
  })
})
