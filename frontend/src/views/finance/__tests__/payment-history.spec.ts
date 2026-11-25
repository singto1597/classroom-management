import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'

import PaymentHistory from '@/views/finance/PaymentHistory.vue'
import { FinanceService } from '@/services/finance'
import { todayIso } from '@/utils/datetime'
import type {
  PaymentHistoryQuery,
  PaymentHistoryResponse,
} from '@/types/finance'

/**
 * 📜 ประวัติการรับเงิน — เทสต์หน้าอ่านอย่างเดียว (FIN-V2 / P3.4)
 *
 * สิ่งที่ล็อกไว้:
 *   1. โหลดครั้งแรกส่งช่วง 30 วันล่าสุด (วันไทย) + kind=all + limit=30
 *   2. event 1 แถว = ผู้จ่าย → ผู้รับ, ยอด `total_applied`, ลิงก์ REC/DEP
 *   3. handover อยู่ไทม์ไลน์เดียวกัน และแสดง badge/เหตุผลเมื่อถูกยกเลิก
 *   4. ขยายบรรทัดแล้วเห็นยอดบิลก่อน/หลัง โดยเงินไม่ถูกตัดทศนิยม
 *   5. "โหลดเพิ่ม" ส่ง `next_cursor` เดิมกลับไป (ไม่คำนวณ offset เอง)
 *   6. เปลี่ยนชนิดรายการ → ยิงใหม่ด้วย kind ที่เลือก
 */
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ currentRoomId: 7 }),
}))

vi.mock('@/composables/useDialog', () => ({
  useDialog: () => ({
    alert: vi.fn<(title: string, text?: string, icon?: string) => Promise<unknown>>(),
    confirm: vi.fn<() => Promise<{ isConfirmed: boolean }>>(),
    fire: vi.fn<(opts: unknown) => Promise<unknown>>(),
    loading: vi.fn<() => Promise<unknown>>(),
    close: vi.fn<() => void>(),
    notify: vi.fn<(text: string) => unknown>(),
  }),
}))

vi.mock('@/services/finance', () => ({
  FinanceService: {
    getPaymentHistory: vi.fn<(roomId: number, params: PaymentHistoryQuery) => Promise<PaymentHistoryResponse>>(),
  },
}))

const RouterLinkStub = defineComponent({
  name: 'RouterLink',
  props: { to: { type: [String, Object], required: true } },
  template: '<a :href="typeof to === \'string\' ? to : \'\'"><slot /></a>',
})

const nowIso = (): string => new Date().toISOString()

const response = (overrides: Partial<PaymentHistoryResponse> = {}): PaymentHistoryResponse => ({
  items: [
    {
      kind: 'event',
      id: 901,
      occurred_at: nowIso(),
      status: 'active',
      event: {
        student_id: 12,
        student_name: 'สมชาย',
        payer_name: 'ผู้ปกครองสมชาย',
        receiver_name: 'ครูสมหญิง',
        amount_received: 1000,
        credit_used: 200,
        credit_added: 0,
        total_applied: 1200,
        reference_no: null,
        lines: [
          {
            line_kind: 'bill',
            amount: 1200,
            bill_before: 1200,
            bill_after: 0,
            collection_title: 'ค่าโครงการ',
          },
        ],
        documents: [
          { doc_type: 'receipt', receipt_no: 'REC-2569-0042', status: 'active' },
          { doc_type: 'deposit', receipt_no: 'DEP-2569-0007', status: 'active' },
        ],
      },
      handover: null,
    },
    {
      kind: 'handover',
      id: 7,
      occurred_at: nowIso(),
      status: 'voided',
      event: null,
      handover: {
        from_account_name: 'ครูสมหญิง (เงินสดรอส่งมอบ)',
        to_account_name: 'เงินสดห้อง',
        amount: 1500,
        handed_over_by_name: 'ครูสมหญิง',
        received_by_name: 'ครูสมชาย',
        note: 'ส่งมอบรอบเช้า',
        void_reason: 'บันทึกผิด',
      },
    },
  ],
  next_cursor: null,
  ...overrides,
})

const mountPage = async () => {
  const wrapper = mount(PaymentHistory, {
    global: { stubs: { RouterLink: RouterLinkStub } },
  })
  await flushPromises()
  return wrapper
}

const buttonWithText = (wrapper: ReturnType<typeof mount>, text: string) =>
  wrapper.findAll('button').find((b) => b.text().includes(text))

describe('PaymentHistory — event + handover timeline (P3.4)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(FinanceService.getPaymentHistory).mockResolvedValue(response())
  })

  it('โหลดครั้งแรกด้วยช่วง 30 วันล่าสุด + kind=all + limit=30', async () => {
    await mountPage()

    const d = new Date(`${todayIso()}T00:00:00Z`)
    d.setUTCDate(d.getUTCDate() - 29)
    const expectedFrom = d.toISOString().slice(0, 10)

    const [roomId, params] = vi.mocked(FinanceService.getPaymentHistory).mock.calls[0]!
    expect(roomId).toBe(7)
    expect(params).toMatchObject({
      from: expectedFrom,
      to: todayIso(),
      kind: 'all',
      limit: 30,
    })
    expect(params?.cursor).toBeUndefined()
  })

  it('แสดงผู้จ่าย → ผู้รับ ยอดรวม และลิงก์ REC/DEP', async () => {
    const wrapper = await mountPage()
    const text = wrapper.text()

    expect(text).toContain('ผู้ปกครองสมชาย')
    expect(text).toContain('ครูสมหญิง')
    expect(text).toContain('฿1,200.00')
    expect(text).toContain('เงินสด ฿1,000.00')
    expect(text).toContain('เครดิตใช้ ฿200.00')

    const hrefs = wrapper.findAll('a').map((a) => a.attributes('href'))
    // [P6.5] ลิงก์เอกสารชี้ `/finance/documents/by-no/...` ไม่ใช่ทางเข้า legacy แล้ว
    expect(hrefs).toContain('/finance/documents/by-no/REC-2569-0042')
    expect(hrefs).toContain('/finance/documents/by-no/DEP-2569-0007')
  })

  it('แสดง handover ในไทม์ไลน์เดียวกัน พร้อม badge ยกเลิกและเหตุผล', async () => {
    const wrapper = await mountPage()
    const text = wrapper.text()

    expect(text).toContain('ส่งมอบเงิน')
    expect(text).toContain('ครูสมหญิง (เงินสดรอส่งมอบ)')
    expect(text).toContain('เงินสดห้อง')
    expect(text).toContain('฿1,500.00')
    expect(text).toContain('ยกเลิกแล้ว')
    expect(text).toContain('บันทึกผิด')
  })

  it('ขยายบรรทัดแล้วเห็นยอดบิลก่อน/หลัง โดยไม่ตัดทศนิยมเงิน', async () => {
    const wrapper = await mountPage()

    await buttonWithText(wrapper, 'ดูรายละเอียด')!.trigger('click')
    await flushPromises()

    const table = wrapper.find('table')
    expect(table.exists()).toBe(true)
    const text = table.text()
    expect(text).toContain('ค่าโครงการ')
    expect(text).toContain('฿1,200.00')
    expect(text).toContain('฿0.00')
  })

  it('โหลดเพิ่มส่ง cursor เดิมกลับไป และไม่ทำให้แถวซ้ำ', async () => {
    const first = response({ next_cursor: 'cur-1' })
    const more = response()
    more.items = [first.items[0]!, more.items[1]!] // แถวซ้ำ 1 แถว — หน้าจอต้องไม่แสดงซ้ำ

    vi.mocked(FinanceService.getPaymentHistory)
      .mockResolvedValueOnce(first)
      .mockResolvedValueOnce(more)

    const wrapper = await mountPage()
    await buttonWithText(wrapper, 'โหลดเพิ่ม')!.trigger('click')
    await flushPromises()

    const calls = vi.mocked(FinanceService.getPaymentHistory).mock.calls
    expect(calls).toHaveLength(2)
    const second = calls[1]!
    expect(second[1]?.cursor).toBe('cur-1')

    // 901 ซ้ำ แต่ 7 มีแถวเดียว → รวมเป็น 2 แถว ไม่ใช่ 3
    expect(wrapper.findAll('article')).toHaveLength(2)
  })

  it('เปลี่ยนชนิดรายการแล้วยิงใหม่ด้วย kind ที่เลือก', async () => {
    const wrapper = await mountPage()

    await wrapper.get('#history-kind').setValue('event')
    await flushPromises()

    const calls = vi.mocked(FinanceService.getPaymentHistory).mock.calls
    expect(calls).toHaveLength(2)
    const second = calls[1]!
    expect(second[1]?.kind).toBe('event')
  })
})
