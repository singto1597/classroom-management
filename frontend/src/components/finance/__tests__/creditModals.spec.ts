import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'

import CreditTopUpModal from '@/components/finance/CreditTopUpModal.vue'
import CreditApplyModal from '@/components/finance/CreditApplyModal.vue'
import CreditHistoryModal from '@/components/finance/CreditHistoryModal.vue'
import { FinanceService } from '@/services/finance'
import type {
  Account,
  CreditApplyPlan,
  CreditUndoResponse,
  PaymentEventCreate,
  PaymentEventResult,
  StudentCreditBalance,
  StudentCreditDetail,
  StudentCreditEntry,
} from '@/types/finance'

/**
 * 💰 โมดัลเครดิต (FIN-V2 / P3.3) — ย้ายสัญญาเดิมจาก `credit-consolidation.spec.ts`
 *
 * เดิมสัญญาชุดนี้อยู่กับหน้า `CreditList.vue` ที่ถูกยุบทิ้ง (รวมเข้าบัญชีรายบุคคล)
 * ตัวโมดัลคือที่ใหม่ของ logic เดียวกัน ⇒ assertions เดิมต้องไม่หลุด:
 *   1. เติมเครดิตส่ง `bill_selection='manual'` + `bill_ids=[]` + `excess_action='credit'`
 *      ⇒ เงินทั้งก้อนเป็นเครดิต ไม่ถูกเอาไปปิดบิลที่ครูไม่ได้เลือก
 *   2. ใช้เครดิตส่ง `amount_received='0.00'` + `use_credit=true` + `excess_action='none'`
 *      + `bill_selection='auto'` ⇒ ไม่มีเงินสด ไม่มีใบเสร็จ
 *   3. `idempotency_key` **คงเดิม** ตลอดการ retry ของแผ่นเดียว (เน็ตสะดุด = ไม่ซ้ำ)
 *   4. ตัวเลขเงินบน event result ถูกแปลงเป็น number ก่อน `formatMoney`
 */
const authState = vi.hoisted(() => ({
  currentRoomId: 7,
  currentUserName: 'ครูทดสอบ',
  canManageFinance: true,
}))

const { alertMock, confirmMock, fireMock, loadingMock, closeMock } = vi.hoisted(() => ({
  alertMock: vi.fn<(title: string, text?: string, icon?: string) => Promise<unknown>>(),
  confirmMock: vi.fn<() => Promise<{ isConfirmed: boolean }>>(),
  fireMock: vi.fn<(opts: unknown) => Promise<unknown>>(),
  loadingMock: vi.fn<(title: string, text?: string) => Promise<unknown>>(),
  closeMock: vi.fn<() => void>(),
}))

vi.mock('@/stores/auth', () => ({ useAuthStore: () => authState }))

vi.mock('@/services/finance', () => ({
  FinanceService: {
    getCreditPlan: vi.fn<() => Promise<CreditApplyPlan>>(),
    createPaymentEvent: vi.fn<
      (roomId: number, payload: PaymentEventCreate) => Promise<PaymentEventResult>
    >(),
    getStudentCredit: vi.fn<() => Promise<StudentCreditDetail>>(),
    undoCreditApplication: vi.fn<() => Promise<CreditUndoResponse>>(),
  },
}))

vi.mock('@/composables/useDialog', () => ({
  useDialog: () => ({
    alert: alertMock,
    confirm: confirmMock,
    fire: fireMock,
    loading: loadingMock,
    close: closeMock,
    notify: vi.fn<(text: string) => unknown>(),
  }),
}))

/** แทน AppSheet (Teleport) — เทสต์สนใจ payload/พฤติกรรม ไม่ใช่การจัดชั้นของแผ่น */
const AppSheetStub = defineComponent({
  name: 'AppSheet',
  props: {
    open: { type: Boolean, default: false },
    label: { type: String, default: '' },
    title: { type: String, default: '' },
    description: { type: String, default: undefined },
    size: { type: String, default: 'form' },
    dismissible: { type: Boolean, default: true },
  },
  emits: ['close'],
  template:
    '<div v-if="open" data-test="sheet"><h2>{{ title }}</h2><slot /><slot name="footer" /></div>',
})

/** แทน CreditPanel — เปิดทางให้ทดสอบ guard ฝั่งโมดัลได้ทุกแถว */
const CreditPanelStub = defineComponent({
  name: 'CreditPanel',
  props: {
    student: { type: Object, required: true },
    entries: { type: Array, default: () => [] },
    canManage: { type: Boolean, default: false },
    loading: { type: Boolean, default: false },
  },
  emits: ['topup', 'apply', 'history', 'undo'],
  template: `
    <div data-test="credit-panel">
      <button
        v-for="entry in entries"
        :key="entry.id"
        type="button"
        :data-test="'undo-' + entry.id"
        @click="$emit('undo', entry)"
      >undo</button>
    </div>
  `,
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

const EMPTY_PLAN: CreditApplyPlan = {
  status: 'ok',
  message: null,
  items: [],
  total_applied: 0,
  total_balance_after: 350,
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

const LEGACY_ENTRY: StudentCreditEntry = {
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

/** `GET …/credits/:studentId` — โมดัลใช้เฉพาะ `entries` ที่เหลือต้องครบตาม type */
const creditDetail = (entries: StudentCreditEntry[]): StudentCreditDetail => ({
  student_id: 11,
  student_no: 5,
  student_name: 'เด็กทดสอบ',
  credit_balance: 350,
  entries,
  open_bills: [],
  plan: {
    student_id: 11,
    student_no: 5,
    student_name: 'เด็กทดสอบ',
    balance_before: 350,
    allocations: [],
    total_applied: 0,
    balance_after: 350,
  },
})

const undoResponse = (overrides: Partial<CreditUndoResponse> = {}): CreditUndoResponse => ({
  status: 'ok',
  message: null,
  credit_entry_id: 1,
  reverse_entry_id: 2,
  student_id: 11,
  student_payment_id: 9,
  reverted_amount: 100,
  bill_paid_amount: 0,
  bill_status: 'pending',
  credit_balance_after: 350,
  ...overrides,
})

const buttonWithText = (wrapper: ReturnType<typeof mount>, text: string) =>
  wrapper.findAll('button').find((b) => b.text().includes(text))

const mountTopUp = () =>
  mount(CreditTopUpModal, {
    props: { open: true, student: STUDENT, accounts: ACCOUNTS },
    global: { stubs: { AppSheet: AppSheetStub } },
  })

const mountApply = () =>
  mount(CreditApplyModal, {
    props: { open: true, student: STUDENT, accounts: ACCOUNTS },
    global: { stubs: { AppSheet: AppSheetStub } },
  })

const mountHistory = (canManage = true) =>
  mount(CreditHistoryModal, {
    props: { open: true, student: STUDENT, canManage },
    global: { stubs: { AppSheet: AppSheetStub, CreditPanel: CreditPanelStub } },
  })

describe('CreditTopUpModal — เติมเงินล่วงหน้า', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    authState.canManageFinance = true
    confirmMock.mockResolvedValue({ isConfirmed: true })
    fireMock.mockResolvedValue({})
    alertMock.mockResolvedValue({})
    loadingMock.mockResolvedValue({})
  })

  it('ผ่าน event แบบ manual/[] และไม่ปิดบิล', async () => {
    vi.mocked(FinanceService.createPaymentEvent).mockResolvedValue(eventResult())
    const wrapper = mountTopUp()

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
      payer_name: 'เด็กทดสอบ',
      receiver_name: 'ครูทดสอบ',
    })
    expect(wrapper.emitted('saved')?.[0]?.[0]).toMatchObject({ deposit_no: 'DEP-2026-0001' })
    expect(wrapper.emitted('close')).toBeTruthy()
  })

  it('ใช้ idempotency_key เดิมเมื่อ retry การเติมที่ล้มเหลว', async () => {
    vi.mocked(FinanceService.createPaymentEvent)
      .mockRejectedValueOnce(new Error('เน็ตหลุด'))
      .mockResolvedValueOnce(eventResult())

    const wrapper = mountTopUp()
    await wrapper.get('#topup-amount').setValue('100')

    await buttonWithText(wrapper, 'ยืนยันเติม')!.trigger('click')
    await flushPromises()
    await buttonWithText(wrapper, 'ยืนยันเติม')!.trigger('click')
    await flushPromises()

    const calls = vi.mocked(FinanceService.createPaymentEvent).mock.calls
    expect(calls).toHaveLength(2)
    expect(calls[0]![1].idempotency_key).toBeTruthy()
    expect(calls[1]![1].idempotency_key).toBe(calls[0]![1].idempotency_key)
    expect(alertMock).toHaveBeenCalledWith(
      'เติมเงินล่วงหน้าไม่สำเร็จ',
      'เน็ตหลุด',
      'error',
    )
  })

  it('ปฏิเสธเมื่อไม่มีสิทธิ์จัดการการเงิน และไม่ยิง API', async () => {
    authState.canManageFinance = false
    const wrapper = mountTopUp()

    await wrapper.get('#topup-amount').setValue('100')
    await buttonWithText(wrapper, 'ยืนยันเติม')!.trigger('click')
    await flushPromises()

    expect(FinanceService.createPaymentEvent).not.toHaveBeenCalled()
    expect(alertMock).toHaveBeenCalledWith(
      'ไม่มีสิทธิ์',
      expect.stringContaining('เฉพาะผู้มีสิทธิ์จัดการการเงิน'),
      'error',
    )
  })

  it('ปฏิเสธยอด 0 ก่อนยิง API', async () => {
    const wrapper = mountTopUp()
    await wrapper.get('#topup-amount').setValue('0')
    // ปุ่มถูก disable แต่ยังกดผ่าน handler ตรง ๆ ไม่ได้จาก template ⇒ ตรวจว่า API ไม่ถูกเรียก
    const confirmButton = buttonWithText(wrapper, 'ยืนยันเติม')
    expect(confirmButton?.attributes('disabled')).toBeDefined()
    await flushPromises()
    expect(FinanceService.createPaymentEvent).not.toHaveBeenCalled()
  })
})

describe('CreditApplyModal — หักเครดิตปิดบิล', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    authState.canManageFinance = true
    confirmMock.mockResolvedValue({ isConfirmed: true })
    fireMock.mockResolvedValue({})
    alertMock.mockResolvedValue({})
    loadingMock.mockResolvedValue({})
  })

  it('ผ่าน event แบบไม่มีเงินสด และไม่หักบิลที่ไม่ได้เสนอ', async () => {
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
            bill_before: '100.00',
            bill_after: '0.00',
          },
        ],
      }),
    )

    const wrapper = mountApply()
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
      wallet_account_id: 5,
      note: 'ใช้เครดิตปิดบิล',
    })
    expect(fireMock).toHaveBeenCalled()
    expect(wrapper.emitted('applied')).toBeTruthy()
  })

  it('ไม่เปิดแผ่นเมื่อไม่มีบิลให้หัก (total_applied <= 0)', async () => {
    vi.mocked(FinanceService.getCreditPlan).mockResolvedValue(EMPTY_PLAN)

    const wrapper = mountApply()
    await flushPromises()

    expect(alertMock).toHaveBeenCalledWith(
      'ไม่มีบิลให้หัก',
      expect.stringContaining('ไม่มีบิลค้างชำระ'),
      'info',
    )
    expect(wrapper.emitted('close')).toBeTruthy()
    expect(FinanceService.createPaymentEvent).not.toHaveBeenCalled()
  })

  it('all-or-nothing: ล้มแล้วบอกว่ายังไม่มีรายการใดถูกหัก', async () => {
    vi.mocked(FinanceService.getCreditPlan).mockResolvedValue(PLAN)
    vi.mocked(FinanceService.createPaymentEvent).mockRejectedValue(new Error('บิลถูกปิดไปแล้ว'))

    const wrapper = mountApply()
    await flushPromises()
    await buttonWithText(wrapper, 'ยืนยันหักเครดิต')!.trigger('click')
    await flushPromises()

    expect(closeMock).toHaveBeenCalled()
    expect(alertMock).toHaveBeenCalledWith(
      'หักเครดิตไม่สำเร็จ',
      expect.stringContaining('ยังไม่มีรายการใดถูกหัก'),
      'error',
    )
    expect(wrapper.emitted('applied')).toBeFalsy()
  })

  it('ปฏิเสธเมื่อไม่มีสิทธิ์ และไม่ขอข้อเสนอ', async () => {
    authState.canManageFinance = false
    mountApply()
    await flushPromises()

    expect(FinanceService.getCreditPlan).not.toHaveBeenCalled()
    expect(alertMock).toHaveBeenCalledWith(
      'ไม่มีสิทธิ์',
      expect.stringContaining('เฉพาะผู้มีสิทธิ์จัดการการเงิน'),
      'error',
    )
  })
})

describe('CreditHistoryModal — ประวัติ + ยกเลิกการหัก', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    authState.canManageFinance = true
    confirmMock.mockResolvedValue({ isConfirmed: true })
    fireMock.mockResolvedValue({})
    alertMock.mockResolvedValue({})
    loadingMock.mockResolvedValue({})
    vi.mocked(FinanceService.getStudentCredit).mockResolvedValue(creditDetail([LEGACY_ENTRY]))
  })

  it('โหลดประวัติของนักเรียนเมื่อเปิดแผ่น', async () => {
    const wrapper = mountHistory()
    await flushPromises()

    expect(FinanceService.getStudentCredit).toHaveBeenCalledWith(7, 11)
    expect(wrapper.find('[data-test="undo-1"]').exists()).toBe(true)
  })

  it('ยกเลิกการหักแบบเดิมได้ และแจ้ง parent ให้โหลดใหม่', async () => {
    vi.mocked(FinanceService.undoCreditApplication).mockResolvedValue(undoResponse())
    const wrapper = mountHistory()
    await flushPromises()

    await wrapper.get('[data-test="undo-1"]').trigger('click')
    await flushPromises()

    expect(FinanceService.undoCreditApplication).toHaveBeenCalledWith(7, {
      credit_entry_id: 1,
      user_name: 'ครูทดสอบ',
    })
    expect(wrapper.emitted('changed')).toBeTruthy()
    // โหลดใหม่ทั้งประวัติ (ครั้งแรก + หลังยกเลิก)
    expect(FinanceService.getStudentCredit).toHaveBeenCalledTimes(2)
  })

  it('แถวที่มาจากใบรับเงินยกเลิกตรงไม่ได้ — ไม่ยิง API (backend 409)', async () => {
    vi.mocked(FinanceService.getStudentCredit).mockResolvedValue(
      creditDetail([{ ...LEGACY_ENTRY, id: 2, payment_event_id: 77, source_label: 'event' }]),
    )
    const wrapper = mountHistory()
    await flushPromises()

    await wrapper.get('[data-test="undo-2"]').trigger('click')
    await flushPromises()

    expect(FinanceService.undoCreditApplication).not.toHaveBeenCalled()
    expect(alertMock).toHaveBeenCalledWith(
      'ยกเลิกที่นี่ไม่ได้',
      expect.stringContaining('ใบรับเงิน #77'),
      'info',
    )
  })

  it('ไม่มีสิทธิ์จัดการการเงิน ⇒ ไม่ยิง API', async () => {
    const wrapper = mountHistory(false)
    await flushPromises()

    await wrapper.get('[data-test="undo-1"]').trigger('click')
    await flushPromises()

    expect(FinanceService.undoCreditApplication).not.toHaveBeenCalled()
    expect(alertMock).toHaveBeenCalledWith(
      'ไม่มีสิทธิ์',
      expect.stringContaining('เฉพาะผู้มีสิทธิ์จัดการการเงิน'),
      'error',
    )
  })
})
