import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import { mount } from '@vue/test-utils'

import BulkReceiveSheet from '@/components/finance/BulkReceiveSheet.vue'
import { FinanceService } from '@/services/finance'
import { downloadBlob } from '@/utils/download'
import type {
  Account,
  AllocationPreviewRequest,
  AllocationPreviewResponse,
  BulkPaymentEventCreate,
  BulkPaymentEventResult,
  Debtor,
  FinancePerson,
  FinanceSettings,
} from '@/types/finance'

/**
 * 📥 `BulkReceiveSheet` — รับเงินหลายคน 1 รอบ (FIN-V2 / P2.7)
 *
 * สิ่งที่ล็อกไว้ (ทุกข้อเกี่ยวกับ "เงินถูกบันทึกผิด" หรือ "ครูไม่รู้ว่าอะไรพัง"):
 *   1. ค่าเริ่มต้น = ติ๊กทุกคนที่มียอดค้าง + ยอดเต็มยอดค้าง (ไม่ใช่ 0 ที่ต้องพิมพ์ใหม่ทุกคน)
 *   2. "จ่ายครบ" ต้องใช้ `net_pending_amount` เมื่อเปิดใช้เครดิต (หักเครดิตแล้ว)
 *   3. **ต้องตรวจสอบยอด (preview) ให้ครบก่อน** กดยืนยันได้ — กันทั้งรอบล้มเพราะคนเดียว
 *   4. ส่ง **คำขอเดียว** พร้อม item ทุกคน + `channel_id: null` (รอบนี้ไม่มีช่องทาง)
 *   5. retry หลังล้มใช้ `idempotency_key` เดิม — เงินชุดเดิมต้องไม่กลายเป็นรอบใหม่
 *   6. error ระดับคน (`student_id`) ⇒ ไฮไลต์แถวนั้น + คงยอดที่พิมพ์ไว้ให้แก้ต่อ
 *   7. สำเร็จ ⇒ ดาวน์โหลด REC รวมได้
 *   8. ไม่มี MANAGE_FINANCE ⇒ ไม่มีปุ่มเขียนเลย
 */
const { alertMock, confirmMock, authState } = vi.hoisted(() => ({
  alertMock: vi.fn<(title: string, text?: string, icon?: string) => Promise<unknown>>(),
  confirmMock: vi.fn<(title: string, text?: string) => Promise<{ isConfirmed: boolean }>>(),
  authState: { canManageFinance: true },
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    currentRoomId: 7,
    get canManageFinance() {
      return authState.canManageFinance
    },
  }),
}))

vi.mock('@/services/finance', () => ({
  FinanceService: {
    getAllDebtors: vi.fn<(roomId: number) => Promise<Debtor[]>>(),
    getAccounts: vi.fn<(roomId: number) => Promise<Account[]>>(),
    getPeople: vi.fn<(roomId: number, query?: unknown) => Promise<FinancePerson[]>>(),
    getFinanceSettings: vi.fn<(roomId: number) => Promise<FinanceSettings>>(),
    previewPaymentEvent: vi.fn<
      (roomId: number, payload: AllocationPreviewRequest) => Promise<AllocationPreviewResponse>
    >(),
    createBulkPaymentEvent: vi.fn<
      (roomId: number, payload: BulkPaymentEventCreate) => Promise<BulkPaymentEventResult>
    >(),
    downloadReceiptPdf: vi.fn<(roomId: number, receiptNo: string) => Promise<Blob>>(),
    downloadCombinedPdf: vi.fn<(roomId: number, receiptNos: string[]) => Promise<Blob>>(),
  },
}))

vi.mock('@/composables/useDialog', () => ({
  useDialog: () => ({ alert: alertMock, confirm: confirmMock }),
}))

vi.mock('@/utils/download', () => ({
  downloadBlob: vi.fn<(blob: Blob, filename: string) => void>(),
  combinedPdfFilename: () => 'receipts.pdf',
}))

/** แทน AppSheet (Teleport) — เทสต์นี้สนใจเนื้อหา/พฤติกรรม ไม่ใช่การจัดชั้นของแผ่น */
const AppSheetStub = defineComponent({
  name: 'AppSheet',
  props: { open: { type: Boolean, default: false } },
  emits: ['close'],
  template: '<div v-if="open" data-test="sheet"><slot /><slot name="footer" /></div>',
})

const DEBTORS: Debtor[] = [
  {
    student_id: 11,
    student_no: 1,
    student_name: 'อาร์ม',
    overdue_count: 1,
    total_pending_amount: 250,
    credit_balance: 100,
    net_pending_amount: 150,
  },
  {
    student_id: 12,
    student_no: 2,
    student_name: 'บี',
    overdue_count: 0,
    total_pending_amount: 120,
    credit_balance: 0,
    net_pending_amount: 120,
  },
  {
    student_id: 13,
    student_no: 3,
    student_name: 'ซี',
    overdue_count: 0,
    total_pending_amount: 0,
    credit_balance: 0,
    net_pending_amount: 0,
  },
]

const PREVIEW: AllocationPreviewResponse = {
  allocations: [],
  total_applied: '250.00',
  credit_used: '0.00',
  credit_added: '0.00',
  remaining_unapplied: '0.00',
  warnings: [],
}

const RESULT: BulkPaymentEventResult = {
  status: 'success',
  message: 'บันทึกรับเงิน 2 คน เรียบร้อย',
  reference_no: 'BULK-20261125-101500',
  events: [
    {
      student_id: 11,
      student_name: 'อาร์ม',
      event: {
        event_id: 1,
        receipt_no: 'REC-2569-0001',
        deposit_no: null,
        amount_received: '250.00',
        credit_used: '0.00',
        credit_added: '0.00',
        total_applied: '250.00',
        allocations: [],
        documents: [],
        reused: false,
        warnings: [],
      },
    },
    {
      student_id: 12,
      student_name: 'บี',
      event: {
        event_id: 2,
        receipt_no: 'REC-2569-0002',
        deposit_no: null,
        amount_received: '120.00',
        credit_used: '0.00',
        credit_added: '0.00',
        total_applied: '120.00',
        allocations: [],
        documents: [],
        reused: false,
        warnings: [],
      },
    },
  ],
  total_amount_received: '370.00',
  reused: false,
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
const apiError = (status: number, data: unknown = undefined): Error => {
  const err = new Error('boom') as Error & {
    isAxiosError: boolean
    response: { status: number; data?: unknown }
  }
  err.isAxiosError = true
  err.response = { status, data }
  return err
}

const flush = async () => {
  await vi.advanceTimersByTimeAsync(0)
  await vi.advanceTimersByTimeAsync(0)
}

const prime = () => {
  vi.mocked(FinanceService.getAllDebtors).mockResolvedValue(DEBTORS)
  vi.mocked(FinanceService.getAccounts).mockResolvedValue(ACCOUNTS)
  vi.mocked(FinanceService.getPeople).mockResolvedValue(PEOPLE)
  vi.mocked(FinanceService.getFinanceSettings).mockResolvedValue(SETTINGS)
  vi.mocked(FinanceService.previewPaymentEvent).mockResolvedValue(PREVIEW)
}

const mountSheet = async () => {
  const wrapper = mount(BulkReceiveSheet, {
    props: { open: true },
    global: { stubs: { AppSheet: AppSheetStub } },
  })
  await flush()
  return wrapper
}

type Wrapper = Awaited<ReturnType<typeof mountSheet>>

const buttonByText = (wrapper: Wrapper, text: string) => {
  const btn = wrapper.findAll('button').find((b) => b.text().includes(text))
  if (!btn) throw new Error(`ไม่พบปุ่ม "${text}"`)
  return btn
}

const amountOf = (wrapper: Wrapper, name: string) =>
  wrapper.find(`input[aria-label="ยอดที่ต้องเก็บของ ${name}"]`)

const checkboxOf = (wrapper: Wrapper, name: string) =>
  wrapper.find(`input[aria-label="เลือก ${name}"]`)

/** กด "ตรวจสอบยอดทั้งหมด" แล้วรอผล preview ของทุกแถว */
const runPreview = async (wrapper: Wrapper) => {
  await buttonByText(wrapper, 'ตรวจสอบยอดทั้งหมด').trigger('click')
  await flush()
}

beforeEach(() => {
  vi.useFakeTimers()
  authState.canManageFinance = true
  vi.mocked(FinanceService.getAllDebtors).mockReset()
  vi.mocked(FinanceService.getAccounts).mockReset()
  vi.mocked(FinanceService.getPeople).mockReset()
  vi.mocked(FinanceService.getFinanceSettings).mockReset()
  vi.mocked(FinanceService.previewPaymentEvent).mockReset()
  vi.mocked(FinanceService.createBulkPaymentEvent).mockReset()
  vi.mocked(FinanceService.downloadReceiptPdf).mockReset()
  vi.mocked(FinanceService.downloadCombinedPdf).mockReset()
  vi.mocked(downloadBlob).mockReset()
  alertMock.mockReset()
  confirmMock.mockReset()
  confirmMock.mockResolvedValue({ isConfirmed: true })
})

afterEach(() => {
  vi.useRealTimers()
})

describe('BulkReceiveSheet', () => {
  it('ค่าเริ่มต้น: ติ๊กเฉพาะคนที่มียอดค้าง + ยอด = ยอดค้างเต็ม', async () => {
    prime()
    const wrapper = await mountSheet()

    expect((checkboxOf(wrapper, 'อาร์ม').element as HTMLInputElement).checked).toBe(true)
    expect((checkboxOf(wrapper, 'บี').element as HTMLInputElement).checked).toBe(true)
    expect((checkboxOf(wrapper, 'ซี').element as HTMLInputElement).checked).toBe(false)

    expect((amountOf(wrapper, 'อาร์ม').element as HTMLInputElement).value).toBe('250')
    expect((amountOf(wrapper, 'บี').element as HTMLInputElement).value).toBe('120')

    // เลขที่รับเงินของทั้งรอบถูกสร้างให้อัตโนมัติ
    expect(
      (wrapper.find('#bulk-reference').element as HTMLInputElement).value,
    ).toMatch(/^BULK-\d{8}-\d{6}$/)
  })

  it('เปิดใช้เครดิตแล้ว "จ่ายครบ" ⇒ ใช้ net ของ "คนนั้น" ไม่ใช่ยอดดิบของคนอื่น', async () => {
    prime()
    const wrapper = await mountSheet()

    await wrapper.find('input[aria-label="ใช้เครดิตคงเหลือปิดบิล"]').setValue(true)
    const jaiFull = wrapper.findAll('button').filter((b) => b.text().includes('จ่ายครบ'))
    await jaiFull[0]!.trigger('click')

    expect((amountOf(wrapper, 'อาร์ม').element as HTMLInputElement).value).toBe('150')
    // บี ไม่มีเครดิต ⇒ ยอดยังเท่าเดิม
    expect((amountOf(wrapper, 'บี').element as HTMLInputElement).value).toBe('120')
  })

  it('ต้องตรวจสอบยอด (preview) ให้ครบก่อน — ปุ่มยืนยันถูก disable จนกว่าจะผ่าน', async () => {
    prime()
    const wrapper = await mountSheet()

    expect(buttonByText(wrapper, 'ยืนยันรับเงิน').attributes('disabled')).toBeDefined()

    await runPreview(wrapper)

    // พรีวิวรายคน — 2 คนที่เลือก = 2 คำขอ
    expect(FinanceService.previewPaymentEvent).toHaveBeenCalledTimes(2)
    expect(buttonByText(wrapper, 'ยืนยันรับเงิน').attributes('disabled')).toBeUndefined()
  })

  it('ยืนยัน ⇒ ส่งคำขอเดียวพร้อมทุกคน (channel_id = null) ด้วยยอด string 2 ตำแหน่ง', async () => {
    prime()
    vi.mocked(FinanceService.createBulkPaymentEvent).mockResolvedValue(RESULT)
    const wrapper = await mountSheet()

    await runPreview(wrapper)
    await buttonByText(wrapper, 'ยืนยันรับเงิน').trigger('click')
    await flush()

    expect(confirmMock).toHaveBeenCalledTimes(1)
    const calls = vi.mocked(FinanceService.createBulkPaymentEvent).mock.calls
    expect(calls).toHaveLength(1)

    const [roomId, payload] = calls[0]!
    expect(roomId).toBe(7)
    expect(payload.idempotency_key).toMatch(/^[0-9a-f]{32}$/)
    expect(payload.reference_no).toMatch(/^BULK-\d{8}-\d{6}$/)
    expect(payload).toMatchObject({
      channel_id: null,
      wallet_account_id: 5,
      receiver_person_id: 1,
      receiver_name: 'ครูเอ',
      event_at: null,
    })
    expect(payload.items).toEqual([
      {
        student_id: 11,
        amount_received: '250.00',
        use_credit: false,
        excess_action: 'none',
        note: null,
      },
      {
        student_id: 12,
        amount_received: '120.00',
        use_credit: false,
        excess_action: 'none',
        note: null,
      },
    ])
  })

  it('🔴 retry หลัง commit ล้มเหลวใช้ `idempotency_key` เดิมของทั้งรอบ', async () => {
    prime()
    vi.mocked(FinanceService.createBulkPaymentEvent)
      .mockRejectedValueOnce(apiError(500))
      .mockResolvedValueOnce(RESULT)
    const wrapper = await mountSheet()

    await runPreview(wrapper)
    await buttonByText(wrapper, 'ยืนยันรับเงิน').trigger('click')
    await flush()
    expect(alertMock).toHaveBeenCalled()

    await buttonByText(wrapper, 'ยืนยันรับเงิน').trigger('click')
    await flush()

    const calls = vi.mocked(FinanceService.createBulkPaymentEvent).mock.calls
    expect(calls).toHaveLength(2)
    expect(calls[1]![1].idempotency_key).toBe(calls[0]![1].idempotency_key)
    expect(calls[1]![1].reference_no).toBe(calls[0]![1].reference_no)
  })

  it('error ระดับคน (student_id) ⇒ บอกชื่อคนนั้นและคงยอดที่พิมพ์ไว้ให้แก้ต่อ', async () => {
    prime()
    vi.mocked(FinanceService.createBulkPaymentEvent).mockRejectedValue(
      apiError(409, {
        detail: {
          code: 'BULK_ITEM_FAILED',
          message: 'บิลถูกปิดไปแล้ว',
          student_id: 12,
          item_code: 'BILL_NOT_OPEN',
        },
      }),
    )
    const wrapper = await mountSheet()

    await runPreview(wrapper)
    await buttonByText(wrapper, 'ยืนยันรับเงิน').trigger('click')
    await flush()

    const [title, text] = alertMock.mock.calls[0]!
    expect(title).toBe('บันทึกไม่สำเร็จ')
    expect(text).toContain('บี')
    expect(text).toContain('บิลถูกปิดไปแล้ว')

    // ไม่ขึ้นหน้าสำเร็จ + ยอดที่พิมพ์ไว้ยังอยู่ (ไม่ถูกล้าง)
    expect(wrapper.text()).not.toContain('บันทึกรับเงิน 2 คนแล้ว')
    expect((amountOf(wrapper, 'บี').element as HTMLInputElement).value).toBe('120')
  })

  it('สำเร็จ ⇒ ดาวน์โหลด REC รวมของทั้งรอบได้', async () => {
    prime()
    vi.mocked(FinanceService.createBulkPaymentEvent).mockResolvedValue(RESULT)
    vi.mocked(FinanceService.downloadCombinedPdf).mockResolvedValue(new Blob(['pdf']))
    const wrapper = await mountSheet()

    await runPreview(wrapper)
    await buttonByText(wrapper, 'ยืนยันรับเงิน').trigger('click')
    await flush()

    expect(wrapper.text()).toContain('บันทึกรับเงิน 2 คนแล้ว')

    await buttonByText(wrapper, 'ดาวน์โหลด REC ทั้งหมด').trigger('click')
    await flush()

    expect(FinanceService.downloadCombinedPdf).toHaveBeenCalledWith(7, [
      'REC-2569-0001',
      'REC-2569-0002',
    ])
    expect(downloadBlob).toHaveBeenCalledTimes(1)
  })

  it('ไม่มี MANAGE_FINANCE ⇒ ไม่มีปุ่มเขียนเลย (ไม่ใช่แค่ disable)', async () => {
    authState.canManageFinance = false
    prime()
    const wrapper = await mountSheet()

    expect(wrapper.text()).toContain('ไม่มีสิทธิ์รับเงิน')
    expect(
      wrapper.findAll('button').some((b) => b.text().includes('ยืนยันรับเงิน')),
    ).toBe(false)
    expect(
      wrapper.findAll('button').some((b) => b.text().includes('ตรวจสอบยอดทั้งหมด')),
    ).toBe(false)
    expect(FinanceService.previewPaymentEvent).not.toHaveBeenCalled()
  })
})
