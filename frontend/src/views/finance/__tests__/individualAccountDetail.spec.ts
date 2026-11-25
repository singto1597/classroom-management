import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'

import IndividualAccountDetail from '@/views/finance/IndividualAccountDetail.vue'
import { FinanceService } from '@/services/finance'
import type {
  Account,
  CreditUndoResponse,
  IndividualAccountItem,
  StudentCreditDetail,
  StudentCreditEntry,
} from '@/types/finance'

/**
 * 👤 บัญชีรายบุคคล — รายละเอียดนักเรียน 1 คน (ยุบเครดิตจาก /finance/credits เข้ามา)
 *
 * สิ่งที่ล็อกไว้:
 *   1. โหลดทั้ง "บัญชี" และ "ประวัติเครดิต" พร้อมกัน — เครดิตไม่ใช่หน้าอีกใบแล้ว
 *   2. ยอด string จาก individual-accounts ถูกแปลงเป็น number ก่อนเข้า `CreditPanel`
 *      (`net_pending_amount = outstanding_total - ready_to_apply`)
 *   3. ยกเลิกการหักแบบเดิมได้; แถวจากใบรับเงินให้ไปยกเลิกที่ใบรับเงิน
 *   4. 🔒 ปุ่มเขียน gate ด้วย `canManageFinance`
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

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { studentId: '11' } }),
}))

vi.mock('@/services/api', () => ({
  apiStatus: (error: unknown) => (error as { status?: number } | null)?.status,
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

vi.mock('@/services/finance', () => ({
  FinanceService: {
    getIndividualAccount: vi.fn<(roomId: number, studentId: number) => Promise<IndividualAccountItem>>(),
    getStudentCredit: vi.fn<() => Promise<StudentCreditDetail>>(),
    getAccounts: vi.fn<(roomId: number) => Promise<Account[]>>(),
    undoCreditApplication: vi.fn<() => Promise<CreditUndoResponse>>(),
  },
}))

const RouterLinkStub = defineComponent({
  name: 'RouterLink',
  props: { to: { type: [String, Object], required: true } },
  template: '<a><slot /></a>',
})

const ReceiveModalStub = defineComponent({
  name: 'ReceiveMoneyModal',
  props: { open: Boolean, studentId: Number, studentName: String },
  emits: ['close', 'saved'],
  template: '<div data-test="receive-modal" :data-open="open" />',
})

const CreditTopUpStub = defineComponent({
  name: 'CreditTopUpModal',
  props: {
    open: Boolean,
    student: { type: Object, default: null },
    accounts: { type: Array, default: () => [] },
  },
  emits: ['close', 'saved'],
  template: '<div data-test="topup-modal" :data-open="open" />',
})

const CreditApplyStub = defineComponent({
  name: 'CreditApplyModal',
  props: {
    open: Boolean,
    student: { type: Object, default: null },
    accounts: { type: Array, default: () => [] },
  },
  emits: ['close', 'applied'],
  template: '<div data-test="apply-modal" :data-open="open" />',
})

const ACCOUNT: IndividualAccountItem = {
  student_id: 11,
  student_no: 3,
  name: 'อาร์ม',
  outstanding_total: '250.00',
  overdue_total: '50.00',
  upcoming_total: '200.00',
  credit_balance: '120.00',
  ready_to_apply: '100.00',
  open_bills: [],
  recent_events: [],
}

const LEGACY_ENTRY: StudentCreditEntry = {
  id: 1,
  entry_type: 'apply',
  entry_type_label: 'หักปิดบิล',
  amount: 100,
  balance_after: 220,
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

const ACCOUNTS: Account[] = [{ id: 5, account_name: 'เงินสดห้อง', balance: 5000 }]

/** `GET …/credits/:studentId` — หน้าจอใช้เฉพาะ `entries` ที่เหลือต้องครบตาม type */
const creditDetail = (entries: StudentCreditEntry[]): StudentCreditDetail => ({
  student_id: 11,
  student_no: 3,
  student_name: 'อาร์ม',
  credit_balance: 120,
  entries,
  open_bills: [],
  plan: {
    student_id: 11,
    student_no: 3,
    student_name: 'อาร์ม',
    balance_before: 120,
    allocations: [],
    total_applied: 0,
    balance_after: 120,
  },
})

const undoResponse = (): CreditUndoResponse => ({
  status: 'ok',
  message: null,
  credit_entry_id: 1,
  reverse_entry_id: 2,
  student_id: 11,
  student_payment_id: 9,
  reverted_amount: 100,
  bill_paid_amount: 0,
  bill_status: 'pending',
  credit_balance_after: 220,
})

const stubs = {
  RouterLink: RouterLinkStub,
  ReceiveMoneyModal: ReceiveModalStub,
  CreditTopUpModal: CreditTopUpStub,
  CreditApplyModal: CreditApplyStub,
}

const mountPage = async () => {
  const wrapper = mount(IndividualAccountDetail, { global: { stubs } })
  await flushPromises()
  return wrapper
}

const buttonWithText = (wrapper: ReturnType<typeof mount>, text: string) =>
  wrapper.findAll('button').find((b) => b.text().includes(text))

describe('IndividualAccountDetail — โต๊ะทำงานของนักเรียน 1 คน', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    authState.canManageFinance = true
    confirmMock.mockResolvedValue({ isConfirmed: true })
    fireMock.mockResolvedValue({})
    alertMock.mockResolvedValue({})
    loadingMock.mockResolvedValue({})
    vi.mocked(FinanceService.getIndividualAccount).mockResolvedValue(ACCOUNT)
    vi.mocked(FinanceService.getStudentCredit).mockResolvedValue(creditDetail([LEGACY_ENTRY]))
    vi.mocked(FinanceService.getAccounts).mockResolvedValue(ACCOUNTS)
  })

  it('โหลดบัญชี + ประวัติเครดิตพร้อมกัน และแสดงเครดิตในหน้าเดียว', async () => {
    const wrapper = await mountPage()

    expect(FinanceService.getIndividualAccount).toHaveBeenCalledWith(7, 11)
    expect(FinanceService.getStudentCredit).toHaveBeenCalledWith(7, 11)

    const text = wrapper.text()
    expect(text).toContain('เครดิต (เงินรับล่วงหน้า)')
    // CreditPanel ใช้ number ⇒ ต้องแปลง string 120.00 / 250.00 ก่อน
    expect(wrapper.get('[data-test="credit-balance"]').text()).toBe('฿120.00')
    expect(text).toContain('฿150.00') // net = 250 - 100
    expect(text).toContain('ยอดค้างดิบ ฿250.00')
    expect(text).toContain('รายการเดินบัญชี')
  })

  it('กด "เติมเงินล่วงหน้า" ในแผง ⇒ เปิด CreditTopUpModal ด้วยยอดที่แปลงแล้ว', async () => {
    const wrapper = await mountPage()

    await buttonWithText(wrapper, 'เติมเงินล่วงหน้า')!.trigger('click')
    await flushPromises()

    const modal = wrapper.findComponent(CreditTopUpStub)
    expect(modal.attributes('data-open')).toBe('true')
    expect(modal.props('student')).toMatchObject({
      student_id: 11,
      credit_balance: 120,
      total_pending_amount: 250,
      net_pending_amount: 150,
    })
  })

  it('ยกเลิกการหักแบบเดิม ⇒ เรียก API แล้วโหลดใหม่ทั้งบัญชีและเครดิต', async () => {
    vi.mocked(FinanceService.undoCreditApplication).mockResolvedValue(undoResponse())
    const wrapper = await mountPage()

    await buttonWithText(wrapper, 'ยกเลิกการหักนี้')!.trigger('click')
    await flushPromises()

    expect(FinanceService.undoCreditApplication).toHaveBeenCalledWith(7, {
      credit_entry_id: 1,
      user_name: 'ครูทดสอบ',
    })
    expect(fireMock).toHaveBeenCalled()
    expect(FinanceService.getIndividualAccount).toHaveBeenCalledTimes(2)
    expect(FinanceService.getStudentCredit).toHaveBeenCalledTimes(2)
  })

  it('แถวจากใบรับเงิน — ไม่มีปุ่มยกเลิก และบอกให้ไปยกเลิกที่ใบรับเงิน', async () => {
    vi.mocked(FinanceService.getStudentCredit).mockResolvedValue(
      creditDetail([{ ...LEGACY_ENTRY, id: 2, payment_event_id: 77, source_label: 'event' }]),
    )
    const wrapper = await mountPage()

    expect(buttonWithText(wrapper, 'ยกเลิกการหักนี้')).toBeUndefined()
    expect(wrapper.text()).toContain('จากใบรับเงิน #77')
    expect(wrapper.text()).toContain('ยกเลิกที่ใบรับเงิน')
  })

  it('ไม่มีสิทธิ์จัดการการเงิน ⇒ ไม่มีปุ่มรับเงิน/เติม/หัก และไม่โหลดกระเป๋าเงิน', async () => {
    authState.canManageFinance = false
    const wrapper = await mountPage()

    expect(buttonWithText(wrapper, 'รับเงิน')).toBeUndefined()
    expect(wrapper.text()).not.toContain('เติมเงินล่วงหน้า')
    expect(wrapper.text()).not.toContain('ใช้เครดิตปิดบิล')
    expect(FinanceService.getAccounts).not.toHaveBeenCalled()
  })

  it('นักเรียนไม่อยู่ในห้อง (404) ⇒ แสดง empty state ไม่ใช่ error กลาง', async () => {
    vi.mocked(FinanceService.getIndividualAccount).mockRejectedValue({ status: 404 })
    const wrapper = await mountPage()

    expect(wrapper.text()).toContain('ไม่พบบัญชีของนักเรียนคนนี้')
    expect(alertMock).not.toHaveBeenCalled()
  })
})
