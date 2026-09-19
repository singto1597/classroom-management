import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import RegionMemberNames from '@/components/activities/RegionMemberNames.vue'

/**
 * 🎯 เทสต์ชุดนี้พิสูจน์ **จุดตัดบรรทัด** ไม่ใช่แค่ "ข้อความออกมาถูก"
 *
 * บริบท: ผู้ใช้รายงานว่าบนคอมรายชื่อเป็น "ลิสต์เดียวยาว ๆ และมีการตัดชื่อ"
 * สาเหตุที่เป็นไปได้และจับได้ยากคือ **ข้อความไทยไม่มีช่องว่างระหว่างคำ**
 * ⇒ เบราว์เซอร์ตัดบรรทัดด้วยพจนานุกรม = ตัดกลางชื่อได้
 *
 * ⚠️ ข้อจำกัดที่ต้องรู้: jsdom **ไม่มี layout engine** จึงวัดไม่ได้ว่าจริง ๆ แล้วเบราว์เซอร์
 *    ตัดบรรทัดตรงไหน สิ่งที่พิสูจน์ได้คือ **กลไกที่ทำให้ตัดบรรทัดได้** ซึ่งมีสองอย่าง:
 *      1. ทุกชื่อต้องถูกห่อด้วย `whitespace-nowrap` (ชื่อเดียวไม่ถูกตัดกลางคำ)
 *      2. ระหว่างชื่อต้องมี "ช่องว่าง" (จุดตัดบรรทัด) — ถ้าหายไป รายชื่อจะกลายเป็นแถวเดียว
 *          ยาวล้นจอ **โดยที่เทสต์แบบวัดข้อความเฉย ๆ จับไม่ได้เลย**
 *    ⇒ เทสต์นี้จึงยืนยันสองข้อนั้นตรง ๆ ไม่ใช่ยืนยันข้อความรวม
 */

/**
 * แยก DOM ลูกตรง ๆ ของ root ออกเป็น "ชื่อ" กับ "ตัวคั่น"
 * ⚠️ ต้องอ่าน `children` ตรง ๆ ไม่ใช้ `findAll('span')` — `findAll` คืน root ด้วย
 *    ทำให้ข้อความรวมทั้งก้อนปนเข้ามาเป็น "ตัวคั่น" ปลอม
 */
const partsOf = (
  wrapper: ReturnType<typeof mount>,
): { text: string; nowrap: boolean }[] => {
  const root = wrapper.element as HTMLElement
  return Array.from(root.children).map((element) => ({
    text: element.textContent ?? '',
    nowrap: element.classList.contains('whitespace-nowrap'),
  }))
}

const nowrapNames = (wrapper: ReturnType<typeof mount>): string[] =>
  partsOf(wrapper)
    .filter((part) => part.nowrap)
    .map((part) => part.text)

const separators = (wrapper: ReturnType<typeof mount>): string[] =>
  partsOf(wrapper)
    .filter((part) => !part.nowrap)
    .map((part) => part.text)

describe('RegionMemberNames', () => {
  const NAMES = ['สม', 'หญิง', 'ปลา']

  it('แสดงชื่อครบทุกคนตามลำดับที่รับมา', () => {
    const wrapper = mount(RegionMemberNames, { props: { names: NAMES } })
    expect(nowrapNames(wrapper)).toEqual(NAMES)
  })

  it('ข้อความรวมยังเป็นรายชื่อที่คั่นด้วยจุลภาคเหมือนเดิม', () => {
    const wrapper = mount(RegionMemberNames, { props: { names: NAMES } })
    expect(wrapper.text()).toBe('สม, หญิง, ปลา')
  })

  it('🔴 ทุกชื่อถูกห่อด้วย `whitespace-nowrap` — ชื่อเดียวห้ามถูกตัดกลางคำ', () => {
    const wrapper = mount(RegionMemberNames, { props: { names: NAMES } })
    expect(wrapper.findAll('span.whitespace-nowrap')).toHaveLength(NAMES.length)
  })

  it('🔴 ตัวคั่นต้องมี "ช่องว่าง" — ไม่มีช่องว่าง = ไม่มีจุดตัดบรรทัด = ล้นเป็นแถวเดียว', () => {
    const wrapper = mount(RegionMemberNames, { props: { names: NAMES } })
    const separatorsFound = separators(wrapper)
    // 3 ชื่อ → 2 ตัวคั่น (ไม่คั่นหลังชื่อสุดท้าย)
    expect(separatorsFound).toHaveLength(NAMES.length - 1)
    for (const separator of separatorsFound) {
      expect(separator).toBe(', ')
      expect(separator.endsWith(' ')).toBe(true)
    }
  })

  it('ชื่อเดียว → ไม่มีตัวคั่นเลย', () => {
    const wrapper = mount(RegionMemberNames, { props: { names: ['สม'] } })
    expect(wrapper.text()).toBe('สม')
    expect(separators(wrapper)).toHaveLength(0)
  })

  it('ไม่มีชื่อ → ว่างเปล่า ไม่มีข้อความค้าง', () => {
    const wrapper = mount(RegionMemberNames, { props: { names: [] } })
    expect(wrapper.text()).toBe('')
    expect(wrapper.findAll('span.whitespace-nowrap')).toHaveLength(0)
  })

  it('ชื่อเยอะ (12 คน) → ยังได้ชื่อครบทุกคน ไม่ถูกตัดด้วย `truncate`/`line-clamp`', () => {
    const many = Array.from({ length: 12 }, (_, index) => `คนที่${index + 1}`)
    const wrapper = mount(RegionMemberNames, { props: { names: many } })
    expect(nowrapNames(wrapper)).toEqual(many)
    expect(wrapper.findAll('span.whitespace-nowrap')).toHaveLength(12)
    expect(wrapper.text()).toBe(many.join(', '))
  })

  it('คลาสจากผู้เรียก (สี/ขนาด) ถูก merge ลง root โดยไม่ทับคลาสภายใน', () => {
    const wrapper = mount(RegionMemberNames, {
      props: { names: NAMES },
      attrs: { class: 'mt-1 block text-sm text-stone-600' },
    })
    expect(wrapper.classes()).toContain('text-stone-600')
    expect(wrapper.classes()).toContain('block')
    // คลาสของตัวห่อชื่อต้องยังอยู่ ไม่ถูกเขียนทับ
    expect(wrapper.findAll('span.whitespace-nowrap')).toHaveLength(NAMES.length)
  })
})
