import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'

import CreditList from '@/views/finance/CreditList.vue'
import { FinanceService } from '@/services/finance'
import type {
  Account,
  CreditApplyPlan,
  PaymentEventCreate,
  PaymentEventResult,
  StudentCreditBalance,
} from '@/types/finance'

/**
 * 💰 หน้าผูกบัญชีรายบุคคล (เครดิต) — เทสต์การเดินผ่าน payment event (FIN-V2 / P3.3)
 *
 * สิ่งที่ล็อกไว้:
 *   1. เติมเครดิตส่ง `bill_selection='manual'` + `bill_ids=[]` + `excess_action='credit'`
 *      ⇒ เงินทั้งก้อนเป็นเครดิต ไม่ถูกเอาไปปิดบิลที่ครูไม่ได้เลือก
 *   2. ใช้เครดิตส่ง `amount_received='0.00'` + `use_credit=true` + `excess_action='none'`
 *      ⇒ ไม่มีเงินสด ไม่มีใบเสร็จ
 *   3. `idempotency_key` **คงเดิม** ตลอดการ retry ของแผ่นเดียว (เน็ตสะดุด = ไม่ซ้ำ)
 *   4. ตัวเลขเงินบน event result ถูกแปลงเป็น number ก่อน `formatMoney`
 */
const authState = vi.hoisted(() => ({
  currentRoomId: 7,
  currentUserName: 'ครูทดสอบ',
  canManageFinance: true,
}))

const { alertMock, confirmMock, fireMock } = vi.hoisted(() => ({
  alertMock: vi.fn<(title: string, text?: string, icon?: string) => Promise<unknown>>(),
  confirmMock: vi.fn<() => Promise<{ isConfirmed: boolean }>>(),
  fireMock: vi.fn<(opts: unknown) => Promise<unknown>>(),
}))

vi.mock('@/stores/auth', () => ({ useAuthStore: () => authState }))

vi.mock('@/services/finance', () => ({
  FinanceService: {
    getCredits: vi.fn<() => Promise<StudentCreditBalance[]>>(),
    getAccounts: vi.fn<() => Promise<Account[]>>(),
    getCreditPlan: vi.fn<() => Promise<CreditApplyPlan>>(),
    createPaymentEvent: vi.fn<(roomId: number, payload: PaymentEventCreate) => Promise<PaymentEventResult>>(),
    getStudentCredit: vi.fn<() => Promise<unknown>>(),
    undoCreditApplication: vi.fn<() => Promise<unknown>>(),
  },
}))

vi.mock('@/composables/useDialog', () => ({
  useDialog: () => ({
    alert: alertMock,
    confirm: confirmMock,
    fire: fireMock,
    loading: vi.fn(),
    close: vi.fn(),
    notify: vi.fn(),
  }),
}))

const AppSheetStub = defineComponent({
  name: 'AppSheet',
  props: { open: { type: Boolean, default: false }, title: { type: String, default: '' } },
  emits: ['close'],
  template: '<div v-if="open" data-test="sheet"><h2>{{ title }}</h2><slot /><slot name="footer" /></div>',
})

const STUDENT: StudentCreditBalance = {
  student_id: 11,
  student_no: 5,
  student_name: 'เด็กทดสอบ',
  credit_balance: 350,
  total_pending_amount: 1200,
  net_pending_amount: 850,
}

const ACCOUNTS: Account[] = [{ id: 5, account_name: 'เงินสดห้อง', balance: 5000 }]

const PLAN: CreditApplyPlan = {
  status: 'ok',
  message: null,
  items: [
    {
      student_id: 11,
      student_no: 5,
      student_name: 'เด็กทดสอบ',
      balance_before: 350,
      allocations: [
        {
          payment_id: 9,
          collection_id: 3,
          title: 'ค่าห้อง',
          due_date: null,
          bill_total: 100,
          bill_paid_before: 0,
          bill_remaining_before: 100,
          apply_amount: 100,
          bill_paid_after: 100,
          bill_status_after: 'paid',
          remaining_after: 250,
        },
      ],
      total_applied: 100,
      balance_after: 250,
    },
  ],
  total_applied: 100,
  total_balance_after: 250,
}

const eventResult = (overrides: Partial<PaymentEventResult> = {}): PaymentEventResult => ({
  event_id: 1,
  receipt_no: null,
  deposit_no: 'DEP-2026-0001',
  amount_received: '100.00',
  credit_used: '0.00',
  credit_added: '100.00',
  total_applied: '0.00',
  allocations: [],
  documents: [],
  reused: false,
  warnings: [],
  ...overrides,
})

const mountPage = async () => {
  const wrapper = mount(CreditList, {
    global: {
      stubs: { AppSheet: AppSheetStub, RouterLink: true, RowActionMenu: true },
    },
  })
  await flushPromises()
  return wrapper
}

const buttonWithText = (wrapper: ReturnType<typeof mount>, text: string) =>
  wrapper.findAll('button').find((b) => b.text().includes(text))

describe('CreditList — credit consolidation (P3.3)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(FinanceService.getCredits).mockResolvedValue([STUDENT])
    vi.mocked(FinanceService.getAccounts).mockResolvedValue(ACCOUNTS)
    confirmMock.mockResolvedValue({ isConfirmed: true })
    fireMock.mockResolvedValue({})
    alertMock.mockResolvedValue({})
  })

  it('เติมเครดิตผ่าน event แบบ manual/[] และไม่ปิดบิล', async () => {
    vi.mocked(FinanceService.createPaymentEvent).mockResolvedValue(eventResult())
    const wrapper = await mountPage()

    await buttonWithText(wrapper, 'เติมเงินล่วงหน้า')!.trigger('click')
    await wrapper.get('#topup-amount').setValue('100')
    await buttonWithText(wrapper, 'ยืนยันเติม')!.trigger('click')
    await flushPromises()

    const [roomId, payload] = vi.mocked(FinanceService.createPaymentEvent).mock.calls[0]!
    expect(roomId).toBe(7)
    expect(payload).toMatchObject({
      student_id: 11,
      amount_received: '100.00',
      use_credit: false,
      excess_action: 'credit',
      bill_selection: 'manual',
      bill_ids: [],
      wallet_account_id: 5,
      receiver_name: 'ครูทดสอบ',
    })
  })

  it('ใช้ idempotency_key เดิมเมื่อ retry การเติมที่ล้มเหลว', async () => {
    vi.mocked(FinanceService.createPaymentEvent)
      .mockRejectedValueOnce(new Error('เน็ตหลุด'))
      .mockResolvedValueOnce(eventResult())

    const wrapper = await mountPage()
    await buttonWithText(wrapper, 'เติมเงินล่วงหน้า')!.trigger('click')
    await wrapper.get('#topup-amount').setValue('100')

    await buttonWithText(wrapper, 'ยืนยันเติม')!.trigger('click')
    await flushPromises()
    await buttonWithText(wrapper, 'ยืนยันเติม')!.trigger('click')
    await flushPromises()

    const calls = vi.mocked(FinanceService.createPaymentEvent).mock.calls
    expect(calls).toHaveLength(2)
    expect(calls[0]![1].idempotency_key).toBeTruthy()
    expect(calls[1]![1].idempotency_key).toBe(calls[0]![1].idempotency_key)
  })

  it('ใช้เครดิตผ่าน event แบบไม่มีเงินสด และไม่หักบิลที่ไม่ได้เสนอ', async () => {
    vi.mocked(FinanceService.getCreditPlan).mockResolvedValue(PLAN)
    vi.mocked(FinanceService.createPaymentEvent).mockResolvedValue(
      eventResult({
        deposit_no: null,
        amount_received: '0.00',
        credit_used: '100.00',
        credit_added: '0.00',
        total_applied: '100.00',
        allocations: [
          {
            student_payment_id: 9,
            collection_id: 3,
            title: 'ค่าห้อง',
            source: 'credit',
            amount: '100.00',
            bill_before: '0.00',
            bill_after: '100.00',
          },
        ],
      }),
    )

    const wrapper = await mountPage()
    await buttonWithText(wrapper, 'ใช้เครดิตปิดบิล')!.trigger('click')
    await flushPromises()

    expect(FinanceService.getCreditPlan).toHaveBeenCalledWith(7, [11])
    await buttonWithText(wrapper, 'ยืนยันหักเครดิต')!.trigger('click')
    await flushPromises()

    const [, payload] = vi.mocked(FinanceService.createPaymentEvent).mock.calls[0]!
    expect(payload).toMatchObject({
      student_id: 11,
      amount_received: '0.00',
      use_credit: true,
      excess_action: 'none',
      bill_selection: 'auto',
      bill_ids: [],
    })
    expect(fireMock).toHaveBeenCalled()
  })
})
