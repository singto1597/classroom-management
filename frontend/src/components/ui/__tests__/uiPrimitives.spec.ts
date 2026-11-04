import { afterEach, describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'

import AppButton from '@/components/ui/AppButton.vue'
import AppCard from '@/components/ui/AppCard.vue'
import AppChip from '@/components/ui/AppChip.vue'
import AppEmptyState from '@/components/ui/AppEmptyState.vue'
import AppSheet from '@/components/ui/AppSheet.vue'
import AppTabs from '@/components/ui/AppTabs.vue'
import IconButton from '@/components/ui/IconButton.vue'
import PageIntro from '@/components/ui/PageIntro.vue'
import StateBlock from '@/components/ui/StateBlock.vue'
import StatusBadge from '@/components/ui/StatusBadge.vue'

/**
 * UI primitives กลาง (P1.6) — เทสต์ล็อกสัญญาที่ทุกวิวพึ่งพา:
 * ขนาดพื้นที่กด 44px · ชื่อสำหรับ screen reader · สถานะไม่พึ่งสีอย่างเดียว
 */

const RouterLinkStub = defineComponent({
  props: { to: { type: [String, Object], required: true } },
  setup(props, { slots }) {
    return () => h('a', { href: String(props.to) }, slots.default?.())
  },
})

const mountButton = (props: Record<string, unknown> = {}, slots = {}) =>
  mount(AppButton, {
    props,
    slots,
    global: { stubs: { RouterLink: RouterLinkStub } },
  })

afterEach(() => {
  document.body.innerHTML = ''
})

describe('AppButton', () => {
  it('เรนเดอร์ปุ่มจริงพร้อม type ที่ส่งมา', () => {
    const w = mountButton({ type: 'submit' }, { default: 'บันทึก' })
    const btn = w.get('button')
    expect(btn.attributes('type')).toBe('submit')
    expect(btn.text()).toContain('บันทึก')
    expect(btn.classes()).toContain('btn-primary')
  })

  it('loading ทำให้ปุ่มกดไม่ได้และประกาศ aria-busy', () => {
    const w = mountButton({ loading: true }, { default: 'กำลังบันทึก' })
    const btn = w.get('button')
    expect(btn.attributes('disabled')).toBeDefined()
    expect(btn.attributes('aria-busy')).toBe('true')
    expect(w.find('.animate-spin').exists()).toBe(true)
  })

  it('disabled ตรง ๆ ก็กดไม่ได้', () => {
    const w = mountButton({ disabled: true }, { default: 'ปิด' })
    expect(w.get('button').attributes('disabled')).toBeDefined()
  })

  it('ส่ง to แล้วเรนเดอร์เป็นลิงก์ ไม่ใช่ปุ่ม', () => {
    const w = mountButton({ to: '/tasks' }, { default: 'ไปงาน' })
    expect(w.find('button').exists()).toBe(false)
    expect(w.get('a').attributes('href')).toBe('/tasks')
  })

  it('ลิงก์ที่ disabled ถูกกันไม่ให้พาออกไป', async () => {
    const w = mountButton({ to: '/tasks', disabled: true }, { default: 'ไปงาน' })
    const a = w.get('a')
    expect(a.attributes('aria-disabled')).toBe('true')
    expect(a.attributes('tabindex')).toBe('-1')
    const event = new MouseEvent('click', { bubbles: true, cancelable: true })
    a.element.dispatchEvent(event)
    expect(event.defaultPrevented).toBe(true)
  })

  it('variant ต่างกันใช้คลาสต่างกัน', () => {
    const secondary = mountButton({ variant: 'secondary' }, { default: 'ยกเลิก' })
    const danger = mountButton({ variant: 'danger' }, { default: 'ลบ' })
    expect(secondary.get('button').classes()).toContain('btn-ghost-ui')
    expect(danger.get('button').classes()).toContain('btn-danger')
  })
})

describe('IconButton', () => {
  it('มี aria-label จาก prop label เสมอ', () => {
    const w = mount(IconButton, { props: { label: 'ปิดเมนู', icon: 'bi-x-lg' } })
    const btn = w.get('button')
    expect(btn.attributes('aria-label')).toBe('ปิดเมนู')
    expect(btn.attributes('title')).toBe('ปิดเมนู')
  })

  it('ขนาดพื้นที่กด 44×44', () => {
    const w = mount(IconButton, { props: { label: 'ปิด', icon: 'bi-x' } })
    const classes = w.get('button').classes()
    expect(classes).toContain('h-11')
    expect(classes).toContain('w-11')
  })

  it('ยิง click ออกไป', async () => {
    const w = mount(IconButton, { props: { label: 'ปิด', icon: 'bi-x' } })
    await w.get('button').trigger('click')
    expect(w.emitted('click')).toHaveLength(1)
  })
})

describe('AppChip / StatusBadge', () => {
  it('chip ใช้โทนพาสเทลตามที่ขอ', () => {
    const w = mount(AppChip, { props: { tone: 'warn' }, slots: { default: 'รออนุมัติ' } })
    expect(w.classes()).toContain('bg-warn-50')
    expect(w.classes()).toContain('text-warn-700')
    expect(w.text()).toBe('รออนุมัติ')
  })

  it('StatusBadge มีทั้งจุดสีและข้อความ — ไม่พึ่งสีอย่างเดียว', () => {
    const w = mount(StatusBadge, { props: { tone: 'ok', label: 'กำลังเรียน' } })
    expect(w.text()).toContain('กำลังเรียน')
    expect(w.find('span[aria-hidden="true"]').exists()).toBe(true)
    expect(w.classes()).toContain('bg-ok-50')
  })
})

describe('AppTabs', () => {
  const tabs = [
    { value: 'pending', label: 'ยังไม่เสร็จ', count: 8 },
    { value: 'done', label: 'เสร็จแล้ว', count: 3 },
    { value: 'all', label: 'ทั้งหมด' },
  ] as const

  it('แสดงจำนวนเฉพาะแท็บที่มี count', () => {
    const w = mount(AppTabs, {
      props: { modelValue: 'pending', tabs, groupLabel: 'กรองสถานะ' },
    })
    const buttons = w.findAll('button')
    expect(buttons).toHaveLength(3)
    expect(buttons[0]?.text()).toContain('8')
    expect(buttons[2]?.text()).not.toContain('0')
  })

  it('เป็น tablist และใช้ aria-selected ตามแท็บที่เลือก', () => {
    const w = mount(AppTabs, {
      props: { modelValue: 'done', tabs, groupLabel: 'กรองสถานะ' },
    })
    expect(w.get('[role="tablist"]').attributes('aria-label')).toBe('กรองสถานะ')
    const buttons = w.findAll('button[role="tab"]')
    expect(buttons[0]?.attributes('aria-selected')).toBe('false')
    expect(buttons[1]?.attributes('aria-selected')).toBe('true')
    expect(buttons[0]?.attributes('tabindex')).toBe('-1')
    expect(buttons[1]?.attributes('tabindex')).toBe('0')
  })

  it('ค่าเริ่มต้นเป็นแท็บขีดเส้นใต้ ไม่ใช่พิลแบ่งส่วน', () => {
    const w = mount(AppTabs, {
      props: { modelValue: 'pending', tabs, groupLabel: 'กรองสถานะ' },
    })
    expect(w.html()).toContain('border-b')
    expect(w.find('[role="tablist"]').classes()).toContain('border-b')
  })

  it('variant="segmented" ใช้พิลในกรอบเดียว', () => {
    const w = mount(AppTabs, {
      props: { modelValue: 'pending', tabs, groupLabel: 'กรองสถานะ', variant: 'segmented' },
    })
    expect(w.find('[role="tablist"]').classes()).not.toContain('border-b')
    expect(w.html()).toContain('rounded-control')
    expect(w.findAll('button[role="tab"]')).toHaveLength(3)
  })

  it('คลิกแล้วส่งค่าใหม่', async () => {
    const w = mount(AppTabs, {
      props: { modelValue: 'pending', tabs, groupLabel: 'กรองสถานะ' },
    })
    await w.findAll('button')[2]?.trigger('click')
    expect(w.emitted('update:modelValue')?.[0]).toEqual(['all'])
  })

  it('ลูกศรขวาเลื่อนไปแท็บถัดไปและเลือกให้', async () => {
    const w = mount(AppTabs, {
      props: { modelValue: 'pending', tabs, groupLabel: 'กรองสถานะ' },
    })
    const list = w.get('[role="tablist"]')
    await list.trigger('keydown', { key: 'ArrowRight' })
    expect(w.emitted('update:modelValue')?.[0]).toEqual(['done'])
  })

  it('End ไปแท็บสุดท้าย', async () => {
    const w = mount(AppTabs, {
      props: { modelValue: 'pending', tabs, groupLabel: 'กรองสถานะ' },
    })
    await w.get('[role="tablist"]').trigger('keydown', { key: 'End' })
    expect(w.emitted('update:modelValue')?.[0]).toEqual(['all'])
  })
})

describe('PageIntro', () => {
  it('แสดงคำโปรยและปุ่ม โดยไม่สร้าง h1 (header เป็นเจ้าของชื่อหน้า)', () => {
    const w = mount(PageIntro, {
      props: { description: 'รายชื่อนักเรียนในห้องนี้' },
      slots: { actions: '<button>เพิ่มนักเรียน</button>' },
    })
    expect(w.find('h1').exists()).toBe(false)
    expect(w.text()).toContain('รายชื่อนักเรียนในห้องนี้')
    expect(w.find('button').text()).toBe('เพิ่มนักเรียน')
  })

  it('ไม่มีคำโปรยและไม่มีปุ่ม ⇒ ไม่เรนเดอร์อะไร', () => {
    const w = mount(PageIntro)
    expect(w.find('header').exists()).toBe(false)
  })
})

describe('AppEmptyState / StateBlock', () => {
  it('empty state แสดงหัวข้อ คำอธิบาย และทางออกจาก slot', () => {
    const w = mount(AppEmptyState, {
      props: { title: 'ยังไม่มีนักเรียน', hint: 'เพิ่มคนแรก' },
      slots: { default: '<button>เพิ่มนักเรียน</button>' },
    })
    expect(w.text()).toContain('ยังไม่มีนักเรียน')
    expect(w.text()).toContain('เพิ่มคนแรก')
    expect(w.find('button').text()).toBe('เพิ่มนักเรียน')
  })

  it('StateBlock empty ใช้การ์ดขอบทึบ ไม่ใช่เส้นประ', () => {
    const w = mount(StateBlock, { props: { variant: 'empty', title: 'ว่าง' } })
    expect(w.html()).not.toContain('border-dashed')
    expect(w.text()).toContain('ว่าง')
  })

  it('StateBlock error มีปุ่มลองใหม่ที่ยิง retry', async () => {
    const w = mount(StateBlock, { props: { variant: 'error' } })
    const btn = w.get('button')
    expect(btn.text()).toContain('ลองอีกครั้ง')
    await btn.trigger('click')
    expect(w.emitted('retry')).toHaveLength(1)
  })
})

describe('AppCard', () => {
  it('รวมคลาส page-card กับระยะขอบที่ขอ', () => {
    const w = mount(AppCard, { props: { padding: 'md', hover: true } })
    expect(w.classes()).toContain('page-card')
    expect(w.classes()).toContain('p-4')
    expect(w.classes()).toContain('card-hover')
  })
})

describe('AppSheet', () => {
  it('ย้ายเนื้อหาไป body และผูก aria กับชื่อแผ่น', async () => {
    const w = mount(AppSheet, {
      props: { open: true, label: 'ตัวกรอง', title: 'กรองรายการ' },
      attachTo: document.body,
    })
    await Promise.resolve()
    const dialog = document.querySelector('[role="dialog"]')
    expect(dialog).not.toBeNull()
    expect(dialog?.getAttribute('aria-modal')).toBe('true')
    const labelledBy = dialog?.getAttribute('aria-labelledby')
    expect(labelledBy).toBeTruthy()
    expect(document.getElementById(labelledBy ?? '')?.textContent).toContain('กรองรายการ')
    w.unmount()
  })

  it('Esc ส่ง close', async () => {
    const w = mount(AppSheet, {
      props: { open: true, label: 'ตัวกรอง' },
      attachTo: document.body,
    })
    await Promise.resolve()
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(w.emitted('close')).toHaveLength(1)
    w.unmount()
  })

  it('ปิดแล้วไม่มี dialog ค้างใน body', async () => {
    const w = mount(AppSheet, {
      props: { open: true, label: 'ตัวกรอง' },
      attachTo: document.body,
    })
    await w.setProps({ open: false })
    expect(document.querySelector('[role="dialog"]')).toBeNull()
    w.unmount()
  })

  it('ผูก aria-describedby กับคำอธิบาย และเรนเดอร์ footer ในแผ่น', async () => {
    const w = mount(AppSheet, {
      props: { open: true, label: 'ยืนยัน', title: 'ลบข้อมูล', description: 'ย้อนกลับไม่ได้' },
      slots: { footer: '<button>ยืนยัน</button>' },
      attachTo: document.body,
    })
    await Promise.resolve()
    const dialog = document.querySelector('[role="dialog"]')
    const describedBy = dialog?.getAttribute('aria-describedby')
    expect(describedBy).toBeTruthy()
    expect(document.getElementById(describedBy ?? '')?.textContent).toContain('ย้อนกลับไม่ได้')
    expect(dialog?.querySelector('footer button')?.textContent).toBe('ยืนยัน')
    w.unmount()
  })

  it('dismissible=false ปิดด้วย Esc ไม่ได้', async () => {
    const w = mount(AppSheet, {
      props: { open: true, label: 'กำลังบันทึก', dismissible: false },
      attachTo: document.body,
    })
    await Promise.resolve()
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(w.emitted('close')).toBeUndefined()
    w.unmount()
  })

  it('Tab วนอยู่ในแผ่น (focus trap) และคืนโฟกัสเมื่อปิด', async () => {
    const trigger = document.createElement('button')
    document.body.appendChild(trigger)
    trigger.focus()

    const w = mount(AppSheet, {
      props: { open: false, label: 'ฟอร์ม' },
      slots: { default: '<button id="first">หนึ่ง</button><button id="last">สอง</button>' },
      attachTo: document.body,
    })
    await w.setProps({ open: true })
    await Promise.resolve()

    const close = document.querySelector<HTMLButtonElement>(
      '[role="dialog"] button[aria-label="ปิดแผ่น"]',
    )
    const last = document.getElementById('last')
    expect(close).not.toBeNull()
    expect(last).not.toBeNull()

    // โฟกัสอยู่ที่ตัวสุดท้าย → Tab ต้องกลับไปตัวแรกในแผ่น (ปุ่มปิด)
    last?.focus()
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab' }))
    expect(document.activeElement).toBe(close)

    // Shift+Tab จากตัวแรก → ย้อนกลับไปตัวสุดท้าย
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true }))
    expect(document.activeElement).toBe(last)

    await w.setProps({ open: false })
    expect(document.activeElement).toBe(trigger)
    w.unmount()
  })

  it('ล็อกการเลื่อนหน้าไว้ระหว่างเปิดและคืนค่าเมื่อปิด', async () => {
    const w = mount(AppSheet, {
      props: { open: false, label: 'ตัวเลือก' },
      attachTo: document.body,
    })
    await w.setProps({ open: true })
    expect(document.body.style.overflow).toBe('hidden')
    await w.setProps({ open: false })
    expect(document.body.style.overflow).not.toBe('hidden')
    w.unmount()
  })
})
