import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import MoneyInput from '@/components/finance/MoneyInput.vue'

/**
 * 💰 `MoneyInput` — ช่องกรอกเงินของการเงิน v2 (FIN-V2 / P2.3)
 *
 * สิ่งที่ล็อกไว้ (เป็นเรื่องเงิน — พลาดแล้วยอดที่บันทึกไม่ตรงกับที่ครูเห็น):
 *   1. ตัวอักษร/ทศนิยมเกิน 2 ตำแหน่ง **ถูกตัดทิ้ง** ไม่ใช่ปัดขึ้น (15.999 ≠ 16.00)
 *   2. ค่าว่าง ≠ 0 — ไม่มีเงินที่พิมพ์ = `null` ไม่ใช่ "รับ 0 บาท"
 *   3. ตอน blur แสดงคั่นหลักพัน แต่ตอนพิมพ์แก้โชว์เลขล้วน
 *   4. ค่าที่ Parent ตั้งจากภายนอกต้องสะท้อนเข้าช่อง (เช่นรีเซ็ตตอนเปิดแผ่น)
 */
const mountInput = (modelValue: number | null = null) =>
  mount(MoneyInput, { props: { modelValue, label: 'เงินสดที่รับ' } })

const inputOf = (wrapper: ReturnType<typeof mountInput>) => wrapper.get('input')

/**
 * ค่า `update:modelValue` ล่าสุดที่ emit ออกไป
 *
 * ⚠️ ไม่ใช้ `.at(-1)` — tsconfig ของ repo ไม่ได้เปิด lib ES2022 ⇒ `vue-tsc` ล้ม
 */
const lastUpdate = (wrapper: ReturnType<typeof mountInput>): unknown => {
  const emitted = wrapper.emitted('update:modelValue')
  if (!emitted || emitted.length === 0) throw new Error('ยังไม่มีการ emit update:modelValue')
  return emitted[emitted.length - 1]
}

describe('MoneyInput', () => {
  it('พิมพ์ "1,250.507" ⇒ เก็บ 1250.5 (ตัดทศนิยมตำแหน่งที่ 3 ไม่ปัดขึ้น)', async () => {
    const wrapper = mountInput()
    await inputOf(wrapper).setValue('1,250.507')

    expect(lastUpdate(wrapper)).toEqual([1250.5])
    // ข้อความที่เหลืออยู่ในช่องต้องตรงกับค่าที่ถูกบันทึก (ไม่มี "7" ค้างให้ดูเหมือน 1,250.507)
    expect(inputOf(wrapper).element.value).toBe('1250.50')
  })

  it('ตัวอักษรที่พิมพ์/วางมาถูกตัดทิ้ง — "12a3" ⇒ 123', async () => {
    const wrapper = mountInput()
    await inputOf(wrapper).setValue('12a3')
    expect(lastUpdate(wrapper)).toEqual([123])
  })

  it('ค่าว่างหรือ "." เดี่ยว ๆ ⇒ null (ไม่ใช่ 0)', async () => {
    const wrapper = mountInput(100)
    await inputOf(wrapper).setValue('')
    expect(lastUpdate(wrapper)).toEqual([null])

    await inputOf(wrapper).setValue('.')
    expect(lastUpdate(wrapper)).toEqual([null])
  })

  it('ตอนพิมพ์โชว์เลขล้วน · ตอน blur จัดรูปคั่นหลักพัน', async () => {
    const wrapper = mountInput()
    const input = inputOf(wrapper)

    await input.setValue('1250.5')
    expect(input.element.value).toBe('1250.5')

    await input.trigger('blur')
    expect(input.element.value).toBe('1,250.50')
  })

  it('ค่าถูกตั้งจากภายนอก (ไม่โฟกัสอยู่) ⇒ อัปเดตช่องทันที', async () => {
    const wrapper = mountInput()
    await wrapper.setProps({ modelValue: 999.5 })
    expect(inputOf(wrapper).element.value).toBe('999.50')
  })

  it('ปุ่มล้างคืน null ให้ parent', async () => {
    const wrapper = mountInput(50)
    await inputOf(wrapper).setValue('50')

    const clear = wrapper.get('button[aria-label="ล้างยอดเงิน"]')
    await clear.trigger('click')
    expect(lastUpdate(wrapper)).toEqual([null])
  })
})
