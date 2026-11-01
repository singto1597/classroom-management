import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import FormSuccess from '@/components/ui/FormSuccess.vue'

/**
 * ✅ `FormSuccess` — หน้ายืนยันหลังบันทึกสำเร็จ (แทน Swal ที่ปิดเองใน 1.5 วิ)
 *
 * สิ่งที่ล็อกไว้: ต้องประกาศ `role="status"` + `aria-live="polite"` เพราะผลลัพธ์
 * ถูกแทนที่แบบ "ไม่มีการเปลี่ยนหน้า" — ถ้าไม่มี aria-live ผู้ใช้โปรแกรมอ่านจอ
 * จะไม่รู้ว่าบันทึกสำเร็จแล้ว (หน้าจอดูเหมือนเดิม)
 */
describe('FormSuccess', () => {
  it('announce ผลลัพธ์ผ่าน role=status + aria-live=polite', () => {
    const wrapper = mount(FormSuccess, { props: { title: 'เพิ่มนักเรียนแล้ว' } })
    const root = wrapper.get('[role="status"]')
    expect(root.attributes('aria-live')).toBe('polite')
  })

  it('แสดง title, hint และ slot ทางไปต่อ', () => {
    const wrapper = mount(FormSuccess, {
      props: { title: 'เพิ่มนักเรียนเรียบร้อยแล้ว', hint: 'เลขที่ 12 อาร์ม' },
      slots: { default: '<a href="/students">ดูรายชื่อ</a>' },
    })

    expect(wrapper.text()).toContain('เพิ่มนักเรียนเรียบร้อยแล้ว')
    expect(wrapper.text()).toContain('เลขที่ 12 อาร์ม')
    expect(wrapper.get('a').attributes('href')).toBe('/students')
  })

  it('ไม่แสดง hint เมื่อไม่ส่งมา', () => {
    const wrapper = mount(FormSuccess, { props: { title: 'สำเร็จ' } })
    expect(wrapper.text()).toBe('สำเร็จ')
  })

  it('ไอคอนเริ่มต้นเป็นติ๊กสีเขียว และเปลี่ยนได้ผ่าน prop', () => {
    const def = mount(FormSuccess, { props: { title: 'ok' } })
    expect(def.get('i').classes()).toContain('bi-check-circle-fill')

    const custom = mount(FormSuccess, { props: { title: 'ok', icon: 'bi-ticket-perforated-fill' } })
    expect(custom.get('i').classes()).toContain('bi-ticket-perforated-fill')
  })
})
