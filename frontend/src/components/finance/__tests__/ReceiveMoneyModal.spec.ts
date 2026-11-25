import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import { mount } from '@vue/test-utils'

import ReceiveMoneyModal from '@/components/finance/ReceiveMoneyModal.vue'
import MoneyInput from '@/components/finance/MoneyInput.vue'
import { FinanceService } from '@/services/finance'
import { downloadBlob } from '@/utils/download'
import type {
  Account,
  AllocationPreviewRequest,
  AllocationPreviewResponse,
  FinancePerson,
  FinanceSettings,
  IndividualAccountItem,
  PaymentEventCreate,
  PaymentEventResult,
} from '@/types/finance'

/**
 * 💸 `ReceiveMoneyModal` — หน้าจอรับเงินของการเงิน v2 (FIN-V2 / P2.3)
 *
 * สิ่งที่ล็อกไว้ (ทุกข้อล้วนเป็นเรื่อง "เงินถูกบันทึกผิดรายการ"):
 *   1. **พรีวิว debounce เดียว ยอดล่าสุด** — ไม่ยิง backend ทุกตัวอักษร และไม่ใช้ผลเก่า
 *   2. **`idempotency_key` คงค่าเดิมตอน retry** — เน็ตสะดุดแล้วกดซ้ำต้องไม่กลายเป็นรายการใหม่
 *   3. **409 ระหว่าง commit = โหลดข้อมูลใหม่** ไม่ใช่ยอดเก่าเงียบ ๆ
 *   4. **เครดิตล้วน (`receipt_no = null`) ไม่มีปุ่มดาวน์โหลด REC** — ไม่มีใบเสร็จให้โหลด
 */
const { alertMock } = vi.hoisted(() => ({
  alertMock: vi.fn<(title: string, text?: string, icon?: string) => Promise<unknown>>(),
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ currentRoomId: 7 }),
}))

vi.mock('@/services/finance', () => ({
  FinanceService: {
    getIndividualAccount: vi.fn<(roomId: number, studentId: number) => Promise<IndividualAccountItem>>(),
    getAccounts: vi.fn<(roomId: number) => Promise<Account[]>>(),
    getPeople: vi.fn<(roomId: number) => Promise<FinancePerson[]>>(),
    getFinanceSettings: vi.fn<(roomId: number) => Promise<FinanceSettings>>(),
    previewPaymentEvent: vi.fn<
      (roomId: number, payload: AllocationPreviewRequest) => Promise<AllocationPreviewResponse>
    >(),
    createPaymentEvent: vi.fn<
      (roomId: number, payload: PaymentEventCreate) => Promise<PaymentEventResult>
    >(),
    downloadReceiptPdf: vi.fn<(roomId: number, receiptNo: string) => Promise<Blob>>(),
  },
}))

vi.mock('@/composables/useDialog', () => ({
  useDialog: () => ({ alert: alertMock }),
}))

vi.mock('@/utils/download', () => ({ downloadBlob: vi.fn<(blob: Blob, filename: string) => void>() }))

/** แทน AppSheet (Teleport) — เทสต์นี้สนใจเนื้อหา/พฤติกรรม ไม่ใช่การจัดชั้นของแผ่น */
const AppSheetStub = defineComponent({
  name: 'AppSheet',
  props: { open: { type: Boolean, default: false } },
  emits: ['close'],
  template: '<div v-if="open" data-test="sheet"><slot /><slot name="footer" /></div>',
})

const ACCOUNT: IndividualAccountItem = {
  student_id: 11,
  student_no: 3,
  name: 'อาร์ม',
  outstanding_total: '250.00',
  overdue_total: '0.00',
  upcoming_total: '250.00',
  credit_balance: '0.00',
  ready_to_apply: '0.00',
  open_bills: [
    {
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
    },
  ],
  recent_events: [],
}

const PREVIEW: AllocationPreviewResponse = {
  allocations: [
    {
      student_payment_id: 21,
      title: 'ค่าอาหาร',
      due_date: null,
      source: 'cash',
      amount: '100.00',
      bill_before: '250.00',
      bill_after: '150.00',
    },
  ],
  total_applied: '100.00',
  credit_used: '0.00',
  credit_added: '0.00',
  remaining_unapplied: '0.00',
  warnings: ['PARTIAL_PAYMENT'],
}

const RESULT: PaymentEventResult = {
  event_id: 9,
  receipt_no: 'REC-2569-0001',
  deposit_no: null,
  amount_received: '100.00',
  credit_used: '0.00',
  credit_added: '0.00',
  total_applied: '100.00',
  allocations: [],
  documents: [],
  reused: false,
  warnings: [],
}

const SETTINGS: FinanceSettings = {
  default_receiver_person_id: 1,
  default_wallet_account_id: 5,
  require_receiver: true,
  receipt_note: null,
}

const PEOPLE: FinancePerson[] = [
  {
    person_id: 1,
    person_type: 'teacher',
    student_id: null,
    display_name: 'ครูเอ',
    phone: null,
    roles: ['receive'],
    is_active: true,
    note: null,
  },
]

const ACCOUNTS: Account[] = [{ id: 5, account_name: 'เงินสดห้อง', balance: 0 }]

/** Error ที่ `apiStatus()` (axios) มองว่าเป็น AxiosError จริง */
const apiError = (status: number, message = 'boom'): Error => {
  const err = new Error(message) as Error & {
    isAxiosError: boolean
    response: { status: number }
  }
  err.isAxiosError = true
  err.response = { status }
  return err
}

/**
 * ปล่อยให้ promise ที่ค้างอยู่จบ (init → set state → watcher) ก่อน assert
 *
 * ใช้ `advanceTimersByTimeAsync(0)` สองรอบเพราะ ref assignment → watcher callback
 * → schedulePreview เป็นอีกชั้นของ microtask ที่ต้องรอให้ครบก่อนเทสต์อ่านค่า
 */
const flush = async () => {
  await vi.advanceTimersByTimeAsync(0)
  await vi.advanceTimersByTimeAsync(0)
}

const prime = (account: IndividualAccountItem = ACCOUNT) => {
  vi.mocked(FinanceService.getIndividualAccount).mockResolvedValue(account)
  vi.mocked(FinanceService.getAccounts).mockResolvedValue(ACCOUNTS)
  vi.mocked(FinanceService.getPeople).mockResolvedValue(PEOPLE)
  vi.mocked(FinanceService.getFinanceSettings).mockResolvedValue(SETTINGS)
  vi.mocked(FinanceService.previewPaymentEvent).mockResolvedValue(PREVIEW)
}

const mountModal = async () => {
  const wrapper = mount(ReceiveMoneyModal, {
    props: { open: true, studentId: 11, studentName: 'อาร์ม' },
    global: { stubs: { AppSheet: AppSheetStub } },
  })
  await flush()
  return wrapper
}

type Wrapper = Awaited<ReturnType<typeof mountModal>>

const typeAmount = async (wrapper: Wrapper, value: string) => {
  await wrapper.findComponent(MoneyInput).get('input').setValue(value)
}

const buttonByText = (wrapper: Wrapper, text: string) => {
  const btn = wrapper.findAll('button').find((b) => b.text().includes(text))
  if (!btn) throw new Error(`ไม่พบปุ่ม "${text}"`)
  return btn
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.mocked(FinanceService.getIndividualAccount).mockReset()
  vi.mocked(FinanceService.getAccounts).mockReset()
  vi.mocked(FinanceService.getPeople).mockReset()
  vi.mocked(FinanceService.getFinanceSettings).mockReset()
  vi.mocked(FinanceService.previewPaymentEvent).mockReset()
  vi.mocked(FinanceService.createPaymentEvent).mockReset()
  vi.mocked(FinanceService.downloadReceiptPdf).mockReset()
  vi.mocked(downloadBlob).mockReset()
  alertMock.mockReset()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('ReceiveMoneyModal', () => {
  it('พรีวิว debounce 350ms — ยิงครั้งเดียวด้วยยอดล่าสุด + payload ครบตามสัญญา', async () => {
    prime()
    const wrapper = await mountModal()

    await typeAmount(wrapper, '100')
    await vi.advanceTimersByTimeAsync(200)
    await typeAmount(wrapper, '250')

    await vi.advanceTimersByTimeAsync(349)
    expect(FinanceService.previewPaymentEvent).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(1)
    expect(FinanceService.previewPaymentEvent).toHaveBeenCalledTimes(1)

    const [roomId, payload] = vi.mocked(FinanceService.previewPaymentEvent).mock.calls[0]!
    expect(roomId).toBe(7)
    expect(payload).toEqual({
      student_id: 11,
      amount_received: '250.00',
      use_credit: false,
      excess_action: 'none',
      bill_selection: 'auto',
      bill_ids: [],
      channel_id: null,
    })
  })

  it('แสดงตารางจัดสรร + คำเตือนจาก preview เมื่อผลกลับมา', async () => {
    prime()
    const wrapper = await mountModal()

    await typeAmount(wrapper, '100')
    await vi.advanceTimersByTimeAsync(350)

    expect(wrapper.text()).toContain('ค่าอาหาร')
    expect(wrapper.text()).toContain('ยังปิดบิลไม่ครบ')
  })

  it('🔴 retry หลัง commit ล้มเหลวใช้ `idempotency_key` เดิม (ไม่สร้างรายการใหม่)', async () => {
    prime()
    vi.mocked(FinanceService.createPaymentEvent)
      .mockRejectedValueOnce(apiError(500, 'network'))
      .mockResolvedValueOnce(RESULT)

    const wrapper = await mountModal()
    await typeAmount(wrapper, '100')
    await vi.advanceTimersByTimeAsync(350)

    await buttonByText(wrapper, 'ยืนยันรับเงิน').trigger('click')
    await flush()
    expect(alertMock).toHaveBeenCalled()

    await buttonByText(wrapper, 'ยืนยันรับเงิน').trigger('click')
    await flush()

    const calls = vi.mocked(FinanceService.createPaymentEvent).mock.calls
    expect(calls).toHaveLength(2)
    const first = calls[0]![1]
    const second = calls[1]![1]
    expect(first.idempotency_key).toMatch(/^[0-9a-f]{32}$/)
    expect(second.idempotency_key).toBe(first.idempotency_key)
    // กระเป๋า/ผู้รับเงินตั้งต้นมาจาก settings — ไม่ปล่อยว่างให้ backend 400
    expect(second).toMatchObject({
      wallet_account_id: 5,
      receiver_person_id: 1,
      receiver_name: 'ครูเอ',
      payer_name: 'อาร์ม',
      amount_received: '100.00',
    })
  })

  it('409 ระหว่าง commit ⇒ โหลดบัญชีใหม่ + พรีวิวใหม่ ไม่ขึ้นหน้าสำเร็จ', async () => {
    prime()
    vi.mocked(FinanceService.createPaymentEvent).mockRejectedValue(apiError(409))

    const wrapper = await mountModal()
    await typeAmount(wrapper, '100')
    await vi.advanceTimersByTimeAsync(350)
    expect(FinanceService.getIndividualAccount).toHaveBeenCalledTimes(1)

    await buttonByText(wrapper, 'ยืนยันรับเงิน').trigger('click')
    await flush()
    await vi.advanceTimersByTimeAsync(350)

    expect(FinanceService.getIndividualAccount).toHaveBeenCalledTimes(2)
    expect(FinanceService.previewPaymentEvent).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).not.toContain('บันทึกรับเงินแล้ว')
  })

  it('🔴 เครดิตล้วน (receipt_no = null) ⇒ ไม่มีปุ่มดาวน์โหลด REC + บอกเหตุผล', async () => {
    prime({ ...ACCOUNT, credit_balance: '250.00', ready_to_apply: '250.00' })
    vi.mocked(FinanceService.createPaymentEvent).mockResolvedValue({
      ...RESULT,
      receipt_no: null,
      amount_received: '0.00',
      credit_used: '250.00',
      total_applied: '250.00',
    })

    const wrapper = await mountModal()
    // เครดิตมี ⇒ ระบบเลือก "ใช้เครดิต" ให้เองและพรีวิวได้โดยไม่ต้องพิมพ์เงินสด
    await vi.advanceTimersByTimeAsync(350)
    expect(FinanceService.previewPaymentEvent).toHaveBeenCalledTimes(1)
    expect(
      vi.mocked(FinanceService.previewPaymentEvent).mock.calls[0]![1],
    ).toMatchObject({ amount_received: '0.00', use_credit: true })

    await buttonByText(wrapper, 'ยืนยันรับเงิน').trigger('click')
    await flush()

    expect(wrapper.text()).toContain('บันทึกรับเงินแล้ว')
    expect(wrapper.text()).toContain('ไม่มีใบเสร็จใหม่')
    expect(wrapper.text()).not.toContain('ดาวน์โหลดใบเสร็จ')
  })

  it('สำเร็จแล้วกดดาวน์โหลด ⇒ เรียก API + ส่ง blob ให้ downloadBlob พร้อมชื่อไฟล์', async () => {
    prime()
    const blob = new Blob(['pdf'], { type: 'application/pdf' })
    vi.mocked(FinanceService.createPaymentEvent).mockResolvedValue(RESULT)
    vi.mocked(FinanceService.downloadReceiptPdf).mockResolvedValue(blob)

    const wrapper = await mountModal()
    await typeAmount(wrapper, '100')
    await vi.advanceTimersByTimeAsync(350)

    await buttonByText(wrapper, 'ยืนยันรับเงิน').trigger('click')
    await flush()

    await buttonByText(wrapper, 'ดาวน์โหลดใบเสร็จ').trigger('click')
    await flush()

    expect(FinanceService.downloadReceiptPdf).toHaveBeenCalledWith(7, 'REC-2569-0001')
    expect(downloadBlob).toHaveBeenCalledWith(blob, 'REC-2569-0001.pdf')
  })
})
