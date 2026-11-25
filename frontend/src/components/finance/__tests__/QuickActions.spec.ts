import { describe, expect, it } from 'vitest'
import { defineComponent } from 'vue'
import { mount } from '@vue/test-utils'

import QuickActions from '@/components/finance/QuickActions.vue'

/**
 * 🚀 QuickActions — ทางลัดที่ backend กำหนด (FIN-V2 / P6.4)
 *
 * สิ่งที่ล็อกไว้:
 *   1. action ที่ FE ไม่รู้จักถูก **ข้าม** ไม่ใช่ throw (เพิ่มฝั่ง server ก่อนได้)
 *   2. `actions` ว่าง → ไม่ render บล็อก
 *   3. route หลักชี้ถูกหน้า (receive → individual-accounts, handover → custody)
 */

/** RouterLink จำลอง — เทสต์สนใจ `to` ที่ถูกส่ง ไม่ใช่การ navigate จริง */
const RouterLinkStub = defineComponent({
  name: 'RouterLink',
  props: { to: { type: [String, Object], required: true } },
  template: '<a :href="to"><slot /></a>',
})

const mountActions = (actions: string[]) =>
  mount(QuickActions, {
    props: { actions },
    global: { stubs: { RouterLink: RouterLinkStub } },
  })

describe('QuickActions', () => {
  it('render เฉพาะ action ที่รู้จัก — ค่าที่ไม่รู้จักถูกข้ามโดยไม่ throw', () => {
    const wrapper = mountActions(['receive', 'bogus'])

    const links = wrapper.findAll('a')
    expect(links).toHaveLength(1)
    expect(links[0]!.text()).toContain('รับเงิน')
  })

  it('actions ว่าง → ไม่ render บล็อก', () => {
    const wrapper = mountActions([])

    expect(wrapper.find('.page-card').exists()).toBe(false)
    expect(wrapper.findAll('a')).toHaveLength(0)
  })

  it('receive → /finance/individual-accounts และ handover → /finance/custody', () => {
    const wrapper = mountActions(['receive', 'handover'])

    const hrefs = wrapper.findAll('a').map((a) => a.attributes('href'))
    expect(hrefs).toEqual(['/finance/individual-accounts', '/finance/custody'])
  })
})
