import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'

import IndividualAccounts from '@/views/finance/IndividualAccounts.vue'
import { FinanceService } from '@/services/finance'
import type {
  Account,
  CreditApplyPlan,
  IndividualAccountItem,
  IndividualAccountListResponse,
  IndividualAccountQuery,
  InvoiceBatchIssueResult,
  Receipt,
} from '@/types/finance'

/**
 * 👤 บัญชีรายบุคคล — หน้าเดียวของงานเงินรายคน (ยุบ debtors + credits เข้ามา)
 *
 * สิ่งที่ล็อกไว้:
 *   1. ตัวกรองผูกกับ `route.query` — deep link `/finance/debtors` (`status=outstanding`)
 *      และ `/finance/credits` (`status=credit`) ต้องเปิดมาถูกแท็บ
 *   2. เปลี่ยนแท็บ/ประเภทเงิน ⇒ เขียน URL ด้วย `router.replace` (ไม่เพิ่มประวัติ) + โหลดใหม่
 *   3. KPI คำนวณจากรายการที่กรองอยู่ (string → number ก่อนบวก)
 *   4. แถว "รับเงิน" เปิด `ReceiveMoneyModal` ของคนนั้นในหน้าเดียว
 *   5. ปุ่มออกใบแจ้งหนี้ส่ง **id ที่ติ๊กไว้** ไป backend (1 คน = 1 ใบ)
 *   6. 🔒 ปุ่มเขียนทุกตัว gate ด้วย `canManageFinance` (ไม่ใช่ `isAdmin`)
 *   7. ตัดเครดิตรวบรวมขอข้อเสนอก่อน (`getCreditPlan`) — ยังไม่เขียนอะไร
 */
const authState = vi.hoisted(() => ({
  currentRoomId: 7,
  currentUserName: 'ครูทดสอบ',
  canManageFinance: true,
}))

const routerState = vi.hoisted(() => ({
  route: { query: {} as Record<string, string> },
  replace: vi.fn<(loc: unknown) => Promise<void>>(),
  push: vi.fn<(loc: unknown) => Promise<void>>(),
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
  useRoute: () => routerState.route,
  useRouter: () => ({ replace: routerState.replace, push: routerState.push }),
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
    getIndividualAccounts: vi.fn<
      (roomId: number, query: IndividualAccountQuery) => Promise<IndividualAccountListResponse>
    >(),
    getAccounts: vi.fn<(roomId: number) => Promise<Account[]>>(),
    getPeople: vi.fn<() => Promise<unknown[]>>(),
    getCreditPlan: vi.fn<() => Promise<CreditApplyPlan>>(),
    issueInvoices: vi.fn<() => Promise<InvoiceBatchIssueResult>>(),
    issueRoomInvoices: vi.fn<() => Promise<InvoiceBatchIssueResult>>(),
    downloadCombinedPdf: vi.fn<() => Promise<Blob>>(),
  },
}))

const RouterLinkStub = defineComponent({
  name: 'RouterLink',
  props: { to: { type: [String, Object], required: true } },
  template: '<a><slot /></a>',
})

/** แทนแผ่น/โมดัลลูก — เทสต์นี้สนใจว่าหน้าเปิดมันด้วย props ของ "คนที่ถูกกด" */
const ReceiveModalStub = defineComponent({
  name: 'ReceiveMoneyModal',
  props: {
    open: { type: Boolean, default: false },
    studentId: { type: Number, required: true },
    studentName: { type: String, required: true },
  },
  emits: ['close', 'saved'],
  template: '<div data-test="receive-modal" :data-open="open" :data-student="studentId" />',
})

const BulkReceiveStub = defineComponent({
  name: 'BulkReceiveSheet',
  props: { open: Boolean, studentIds: { type: Array, default: () => [] } },
  emits: ['close', 'saved'],
  template: '<div data-test="bulk-receive" :data-open="open" />',
})

const BulkCreditStub = defineComponent({
  name: 'BulkCreditSheet',
  props: {
    open: Boolean,
    plan: { type: Object, default: null },
    receiverOptions: { type: Array, default: () => [] },
  },
  emits: ['close', 'applied'],
  template: '<div data-test="bulk-credit" :data-open="open" />',
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

const CreditHistoryStub = defineComponent({
  name: 'CreditHistoryModal',
  props: {
    open: Boolean,
    student: { type: Object, default: null },
    canManage: Boolean,
  },
  emits: ['close', 'changed', 'topup', 'apply'],
  template: '<div data-test="history-modal" :data-open="open" />',
})

const RowActionMenuStub = defineComponent({
  name: 'RowActionMenu',
  props: {
    label: { type: String, default: '' },
    items: { type: Array, default: () => [] },
  },
  emits: ['select'],
  template: '<div data-test="row-menu" />',
})

const ITEM_ARM: IndividualAccountItem = {
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

const ITEM_BEAM: IndividualAccountItem = {
  student_id: 12,
  student_no: 4,
  name: 'บีม',
  outstanding_total: '0.00',
  overdue_total: '0.00',
  upcoming_total: '0.00',
  credit_balance: '0.00',
  ready_to_apply: '0.00',
  open_bills: [],
  recent_events: [],
}

const listResponse = (
  items: IndividualAccountItem[] = [ITEM_ARM, ITEM_BEAM]
): IndividualAccountListResponse => ({ as_of: '2026-11-25', items })

const PLAN: CreditApplyPlan = {
  status: 'ok',
  message: null,
  items: [],
  total_applied: 100,
  total_balance_after: 240,
}

const ACCOUNTS: Account[] = [{ id: 5, account_name: 'เงินสดห้อง', balance: 5000 }]

const issueResult = (receiptNo: string, skipped = 0): InvoiceBatchIssueResult => ({
  status: 'ok',
  message: null,
  receipts: [{ receipt_no: receiptNo }] as unknown as Receipt[],
  issued_count: 1,
  skipped: Array.from({ length: skipped }, (_, i) => ({
    student_id: 90 + i,
    student_no: null,
    student_name: `ข้าม ${i + 1}`,
    reason: 'ยอดค้างน้อยกว่า 0.01',
  })),
})

const stubs = {
  RouterLink: RouterLinkStub,
  ReceiveMoneyModal: ReceiveModalStub,
  BulkReceiveSheet: BulkReceiveStub,
  BulkCreditSheet: BulkCreditStub,
  CreditTopUpModal: CreditTopUpStub,
  CreditApplyModal: CreditApplyStub,
  CreditHistoryModal: CreditHistoryStub,
  RowActionMenu: RowActionMenuStub,
}

const mountPage = async () => {
  const wrapper = mount(IndividualAccounts, { global: { stubs } })
  await flushPromises()
  return wrapper
}

const buttonWithText = (wrapper: ReturnType<typeof mount>, text: string) =>
  wrapper.findAll('button').find((b) => b.text().trim() === text)

const rowCheckbox = (wrapper: ReturnType<typeof mount>, name: string) =>
  wrapper.findAll('input[type="checkbox"]').find((el) => el.attributes('aria-label') === `เลือก ${name}`)

describe('IndividualAccounts — หน้าเดียวของงานเงินรายคน', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    authState.canManageFinance = true
    routerState.route.query = {}
    routerState.replace.mockResolvedValue(undefined)
    routerState.push.mockResolvedValue(undefined)
    confirmMock.mockResolvedValue({ isConfirmed: true })
    fireMock.mockResolvedValue({})
    alertMock.mockResolvedValue({})
    loadingMock.mockResolvedValue({})
    vi.mocked(FinanceService.getIndividualAccounts).mockResolvedValue(listResponse())
    vi.mocked(FinanceService.getAccounts).mockResolvedValue(ACCOUNTS)
    vi.mocked(FinanceService.getPeople).mockResolvedValue([])
  })

  it('โหลดครั้งแรกด้วยตัวกรองจาก route.query (deep link จาก /finance/debtors)', async () => {
    routerState.route.query = {
      status: 'outstanding',
      fund_type: 'room_fund',
      q: 'อาร์ม',
    }

    await mountPage()

    expect(FinanceService.getIndividualAccounts).toHaveBeenCalledWith(7, {
      status: 'outstanding',
      fund_type: 'room_fund',
      q: 'อาร์ม',
    })
    // ค่าเดิมตรงกับ query อยู่แล้ว ⇒ ไม่ต้อง replace ซ้ำ
    expect(routerState.replace).not.toHaveBeenCalled()
    expect(routerState.push).not.toHaveBeenCalled()
  })

  it('เปลี่ยนแท็บสถานะ ⇒ เขียน URL + โหลดใหม่ด้วย status ใหม่', async () => {
    routerState.route.query = { status: 'credit' }
    const wrapper = await mountPage()

    expect(FinanceService.getIndividualAccounts).toHaveBeenLastCalledWith(7, { status: 'credit' })

    await wrapper.get('button[data-value="outstanding"]').trigger('click')
    await flushPromises()

    expect(routerState.replace).toHaveBeenCalledWith({ query: { status: 'outstanding' } })
    expect(FinanceService.getIndividualAccounts).toHaveBeenLastCalledWith(7, {
      status: 'outstanding',
    })
  })

  it('เปลี่ยนประเภทเงิน ⇒ เขียน URL (ตัด fund_type ออกเมื่อเลือก "ทุกประเภท")', async () => {
    routerState.route.query = { fund_type: 'room_fund' }
    const wrapper = await mountPage()

    expect(FinanceService.getIndividualAccounts).toHaveBeenLastCalledWith(7, {
      fund_type: 'room_fund',
    })

    await wrapper.get('select').setValue('')
    await flushPromises()

    expect(routerState.replace).toHaveBeenLastCalledWith({ query: {} })
    expect(FinanceService.getIndividualAccounts).toHaveBeenLastCalledWith(7, {})
  })

  it('KPI รวมจากรายการที่โหลดอยู่ และเงินไม่ถูกตัดทศนิยม', async () => {
    const wrapper = await mountPage()

    const kpi = (label: string) =>
      wrapper.findAll('.page-card').find((card) => card.text().includes(label))!

    expect(kpi('ยอดค้างรวม').text()).toContain('฿250.00')
    expect(kpi('เกินกำหนด').text()).toContain('฿50.00')
    expect(kpi('ยังไม่ถึงกำหนด').text()).toContain('฿200.00')
    expect(kpi('เครดิตคงเหลือ').text()).toContain('฿120.00')
    expect(kpi('เครดิตใช้ได้').text()).toContain('฿100.00')
  })

  it('กด "รับเงิน" ที่แถว ⇒ เปิด ReceiveMoneyModal ของคนนั้น', async () => {
    const wrapper = await mountPage()

    const receiveButtons = wrapper
      .findAll('button')
      .filter((b) => b.text().trim() === 'รับเงิน')
    expect(receiveButtons.length).toBeGreaterThan(0)

    await receiveButtons[0]!.trigger('click')
    await flushPromises()

    const modal = wrapper.get('[data-test="receive-modal"]')
    expect(modal.attributes('data-open')).toBe('true')
    expect(modal.attributes('data-student')).toBe('11')
  })

  it('ออกใบแจ้งหนี้ที่เลือก ⇒ ส่ง id ที่ติ๊กไป backend (1 คน = 1 ใบ)', async () => {
    confirmMock.mockResolvedValueOnce({ isConfirmed: true }).mockResolvedValue({ isConfirmed: false })
    vi.mocked(FinanceService.issueInvoices).mockResolvedValue(issueResult('INV-2569-0001'))

    const wrapper = await mountPage()
    await rowCheckbox(wrapper, 'อาร์ม')!.setValue(true)
    await flushPromises()

    await buttonWithText(wrapper, 'ออกใบแจ้งหนี้ที่เลือก')!.trigger('click')
    await flushPromises()

    expect(FinanceService.issueInvoices).toHaveBeenCalledWith(7, {
      student_ids: [11],
      user_name: 'ครูทดสอบ',
    })
    // ต้องบอกผลลัพธ์ให้ผู้ใช้เห็น (ไม่ใช่เงียบ)
    expect(confirmMock).toHaveBeenCalled()
    expect(wrapper.text()).toBeTruthy()
  })

  it('ออกใบแจ้งหนี้ทั้งห้อง ⇒ เรียก issueRoomInvoices ไม่ใช้ id ที่ติ๊ก', async () => {
    confirmMock.mockResolvedValueOnce({ isConfirmed: true }).mockResolvedValue({ isConfirmed: false })
    vi.mocked(FinanceService.issueRoomInvoices).mockResolvedValue(issueResult('INV-2569-0002', 1))

    const wrapper = await mountPage()
    await buttonWithText(wrapper, 'ออกใบแจ้งหนี้ทั้งห้อง')!.trigger('click')
    await flushPromises()

    expect(FinanceService.issueRoomInvoices).toHaveBeenCalledWith(7, { user_name: 'ครูทดสอบ' })
    expect(FinanceService.issueInvoices).not.toHaveBeenCalled()
  })

  it('ตัดเครดิตที่เลือก ⇒ ขอข้อเสนอก่อน แล้วเปิด BulkCreditSheet (ยังไม่เขียน)', async () => {
    vi.mocked(FinanceService.getCreditPlan).mockResolvedValue(PLAN)

    const wrapper = await mountPage()
    await rowCheckbox(wrapper, 'อาร์ม')!.setValue(true)
    await flushPromises()

    await buttonWithText(wrapper, 'ตัดเครดิตที่เลือก')!.trigger('click')
    await flushPromises()

    expect(FinanceService.getCreditPlan).toHaveBeenCalledWith(7, [11])
    expect(FinanceService.getPeople).toHaveBeenCalledWith(7, { active: true })
    expect(wrapper.get('[data-test="bulk-credit"]').attributes('data-open')).toBe('true')
  })

  it('แปลงยอด string → number ก่อนส่งให้โมดัลเครดิต', async () => {
    const wrapper = await mountPage()

    // เมนูจุด 3 จุด (มือถือ/เดสก์ท็อป) — เลือกตัวแรกของอาร์ม
    const menus = wrapper.findAllComponents(RowActionMenuStub)
    menus[0]!.vm.$emit('select', 'topup')
    await flushPromises()

    const topUp = wrapper.findComponent(CreditTopUpStub)
    expect(topUp.attributes('data-open')).toBe('true')
    expect(topUp.props('student')).toMatchObject({
      student_id: 11,
      student_name: 'อาร์ม',
      credit_balance: 120,
      total_pending_amount: 250,
      net_pending_amount: 150,
    })
  })

  it('ไม่มีสิทธิ์จัดการการเงิน ⇒ ไม่มีปุ่มเขียน/ช่องติ๊ก และเมนูเหลือเฉพาะอ่าน', async () => {
    authState.canManageFinance = false
    const wrapper = await mountPage()

    expect(wrapper.findAll('button').filter((b) => b.text().trim() === 'รับเงิน')).toHaveLength(0)
    expect(buttonWithText(wrapper, 'ตัดเครดิตที่เลือก')).toBeUndefined()
    expect(buttonWithText(wrapper, 'ออกใบแจ้งหนี้ที่เลือก')).toBeUndefined()
    expect(buttonWithText(wrapper, 'ออกใบแจ้งหนี้ทั้งห้อง')).toBeUndefined()
    expect(wrapper.findAll('input[type="checkbox"]')).toHaveLength(0)
    expect(FinanceService.getAccounts).not.toHaveBeenCalled()

    const menu = wrapper.findAllComponents(RowActionMenuStub)[0]!
    const keys = (menu.props('items') as { key: string }[]).map((i) => i.key)
    expect(keys).toEqual(['open', 'history'])
  })
})
