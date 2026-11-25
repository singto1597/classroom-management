import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import CreditPanel from '@/components/finance/CreditPanel.vue'
import type { StudentCreditBalance, StudentCreditEntry } from '@/types/finance'

/**
 * 💳 CreditPanel — เทสต์การแสดงผล (FIN-V2 / P3.3)
 *
 * สิ่งที่ล็อกไว้:
 *   1. เงินแสดงด้วย `formatMoney` (฿ + 2 ตำแหน่ง)
 *   2. ปุ่มยกเลิกตรง **ไม่โผล่** สำหรับแถวที่มาจากใบรับเงิน (`payment_event_id` ไม่ null)
 *      — backend ตอบ 409 ถ้ากด ⇒ UI ต้องไม่เชิญผู้ใช้กดผิด
 *   3. รายการหักแบบเดิม (legacy) ยังยกเลิกตรงได้
 *   4. ติดป้ายที่มาของแถวให้อ่านออก (จากใบรับเงิน #N / รายการเดิม)
 */
const STUDENT: StudentCreditBalance = {
  student_id: 11,
  student_no: 5,
  student_name: 'เด็กทดสอบ',
  credit_balance: 350,
  total_pending_amount: 1200,
  net_pending_amount: 850,
}

const legacyApply: StudentCreditEntry = {
  id: 1,
  entry_type: 'apply',
  entry_type_label: 'หักปิดบิล',
  amount: 100,
  balance_after: 250,
  finance_transaction_id: null,
  student_payment_id: 9,
  collection_id: 3,
  note: null,
  recorded_by: 'ครูทดสอบ',
  created_at: '2026-11-25T03:00:00Z',
  receipt_no: null,
  receipt_event_at: null,
  collection_title: 'ค่าห้อง',
  payment_event_id: null,
  source_label: 'legacy',
}

const eventApply: StudentCreditEntry = {
  ...legacyApply,
  id: 2,
  student_payment_id: null,
  payment_event_id: 77,
  source_label: 'event',
}

const mountPanel = (entries: StudentCreditEntry[]) =>
  mount(CreditPanel, {
    props: { student: STUDENT, entries, canManage: true },
  })

describe('CreditPanel', () => {
  it('แสดงยอดเงินด้วย formatMoney และไม่ตัดบรรทัดตัวเลขเงิน', () => {
    const wrapper = mountPanel([legacyApply])
    const balance = wrapper.get('[data-test="credit-balance"]')
    expect(balance.text()).toBe('฿350.00')
    expect(balance.classes()).not.toContain('truncate')
    expect(wrapper.text()).toContain('฿850.00')
  })

  it('ไม่แสดงปุ่มยกเลิกสำหรับแถวที่มาจากใบรับเงิน', () => {
    const wrapper = mountPanel([eventApply])
    const undoButtons = wrapper
      .findAll('button')
      .filter((b) => b.text().includes('ยกเลิกการหักนี้'))
    expect(undoButtons).toHaveLength(0)
    expect(wrapper.text()).toContain('จากใบรับเงิน #77')
    expect(wrapper.text()).toContain('ยกเลิกที่ใบรับเงิน')
  })

  it('ยังยกเลิกตรงได้สำหรับรายการหักแบบเดิม', async () => {
    const wrapper = mountPanel([legacyApply])
    const undo = wrapper
      .findAll('button')
      .find((b) => b.text().includes('ยกเลิกการหักนี้'))
    expect(undo).toBeTruthy()
    expect(wrapper.text()).toContain('รายการเดิม')
    await undo!.trigger('click')
    expect(wrapper.emitted('undo')?.[0]?.[0]).toMatchObject({ id: 1 })
  })

  it('ซ่อนปุ่มเขียนทั้งหมดเมื่อไม่มีสิทธิ์จัดการการเงิน', () => {
    const wrapper = mount(CreditPanel, {
      props: { student: STUDENT, entries: [legacyApply], canManage: false },
    })
    expect(wrapper.text()).not.toContain('เติมเงินล่วงหน้า')
    expect(wrapper.text()).not.toContain('ใช้เครดิตปิดบิล')
    expect(
      wrapper.findAll('button').filter((b) => b.text().includes('ยกเลิกการหักนี้')),
    ).toHaveLength(0)
  })
})
