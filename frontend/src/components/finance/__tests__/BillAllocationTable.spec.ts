import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import BillAllocationTable from '@/components/finance/BillAllocationTable.vue'
import type { AllocationLine, OpenBillItem } from '@/types/finance'

/**
 * 📋 `BillAllocationTable` — ตารางบิล + ยอดที่ระบบจัดสรรให้ (FIN-V2 / P2.3)
 *
 * สิ่งที่ล็อกไว้:
 *   1. **ยอดรวมมาจาก `totals` ของ backend เท่านั้น** — ไม่ใช่ผลบวกของบรรทัดบนจอ
 *      (engine อาจจัดสรรให้บิลที่หน้าจอยังไม่รู้จัก ⇒ บวกเองแล้วตัวเลขไม่ตรงใบเสร็จ)
 *   2. 1 บิลมี 2 บรรทัด (เงินสด + เครดิต) ต้องเห็นแยกกัน — ผู้ใช้ต้องรู้ว่าเครดิตถูกใช้ไปเท่าไร
 *   3. โหมด `manual` — ติ๊กเลือกบิลแล้ว emit id ออกไปให้ parent ส่งเป็น `bill_ids`
 */
const bill = (over: Partial<OpenBillItem> = {}): OpenBillItem => ({
  student_payment_id: 21,
  collection_id: 1,
  title: 'ค่าอาหาร',
  amount: '250.00',
  paid_amount: '0.00',
  written_off_amount: '0.00',
  outstanding: '250.00',
  due_date: null,
  status: 'open',
  collection_kind: null,
  fund_type: 'room_fund',
  ...over,
})

const line = (over: Partial<AllocationLine> = {}): AllocationLine => ({
  student_payment_id: 21,
  source: 'cash',
  amount: '100.00',
  bill_before: '250.00',
  bill_after: '150.00',
  ...over,
})

describe('BillAllocationTable', () => {
  it('แยกเงินสด/เครดิตต่อบิล + แสดงยอดคงเหลือหลังรับ', () => {
    const wrapper = mount(BillAllocationTable, {
      props: {
        bills: [bill()],
        allocations: [
          line({ source: 'cash', amount: '60.00', bill_before: '250.00', bill_after: '190.00' }),
          line({ source: 'credit', amount: '40.00', bill_before: '190.00', bill_after: '150.00' }),
        ],
        selection: 'auto',
      },
    })

    const row = wrapper.get('tbody tr')
    expect(row.text()).toContain('฿60.00')
    expect(row.text()).toContain('฿40.00')
    // ยอดหลังรับต้องเป็นค่าของบรรทัด **สุดท้าย** (ไม่ใช่ผลรวมที่พิมพ์ซ้ำ)
    expect(row.text()).toContain('฿150.00')
  })

  it('🔴 ยอดรวมใช้ `totals` จาก backend ไม่ใช่ผลบวกของบรรทัดบนจอ', () => {
    const wrapper = mount(BillAllocationTable, {
      props: {
        bills: [bill()],
        allocations: [line({ amount: '100.00', bill_after: '150.00' })],
        selection: 'auto',
        totals: {
          total_applied: '999.00',
          credit_used: '0.00',
          credit_added: '0.00',
        },
      },
    })

    // บรรทัดบนจอรวมกันได้ 100 แต่ engine บอก 999 (เช่นมีค่าปรับใหม่ที่ยังไม่อยู่ในลิสต์)
    // ⇒ ตัวเลขท้ายตารางต้องเป็นของ engine เพราะนั่นคือสิ่งที่ commit จะเขียนจริง
    expect(wrapper.get('tfoot').text()).toContain('฿999.00')
  })

  it('บิลเลยกำหนด ⇒ ไฮไลต์แดง + ป้าย "เกินกำหนด"', () => {
    const wrapper = mount(BillAllocationTable, {
      props: {
        bills: [bill({ due_date: '2020-01-01' })],
        allocations: [],
        selection: 'auto',
      },
    })

    const row = wrapper.get('tbody tr')
    expect(row.classes()).toContain('bg-danger-50')
    expect(row.text()).toContain('เกินกำหนด')
  })

  it('โหมด manual — ติ๊กบิลแล้ว emit id ออกไปให้ parent ใช้เป็น bill_ids', async () => {
    const wrapper = mount(BillAllocationTable, {
      props: {
        bills: [bill(), bill({ student_payment_id: 22, title: 'ค่าหนังสือ' })],
        allocations: [],
        selection: 'manual',
        modelValue: [],
      },
    })

    const boxes = wrapper.findAll('input[type="checkbox"]')
    expect(boxes).toHaveLength(2)

    await boxes[1]!.trigger('change')
    const emitted = wrapper.emitted('update:modelValue')
    expect(emitted?.[emitted.length - 1]).toEqual([[22]])
  })

  it('ไม่มีบิลเปิด ⇒ บอกว่ารับนี้จะเป็นเครดิต (ไม่ใช่ตารางว่างเปล่า)', () => {
    const wrapper = mount(BillAllocationTable, {
      props: { bills: [], allocations: [], selection: 'auto' },
    })

    expect(wrapper.get('tbody').text()).toContain('ไม่มีบิลเปิด')
  })
})
