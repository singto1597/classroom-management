import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'

import IncomeBatchCreatePage from '@/views/finance/IncomeBatchCreate.vue'
import { FinanceService } from '@/services/finance'
import type {
  Account,
  Category,
  IncomeBatchCreate,
  IncomeBatchCreateResponse,
  PaymentChannel,
} from '@/types/finance'

/**
 * 💰 ใบรับเงิน — เทสต์หน้าสร้าง (FIN-V2 / P4.5)
 *
 * สิ่งที่ล็อกไว้ (brief P4.5):
 *   1. ยอดรวมอัปเดตสดเมื่อแก้จำนวนเงินของบรรทัด
 *   2. validation ฝั่งจอ: ไม่มีผู้จ่าย/ผู้รับ → ไม่ยิง API
 *   3. กระเป๋าเดียวทั้งใบ — ไม่มีช่อง wallet ต่อบรรทัด และ payload มี wallet เดียว
 *   4. retry ที่ล้มเหลว (400) ใช้ `idempotency_key` เดิม
 *   5. คีย์ใหม่เกิดเฉพาะเมื่อกด "เริ่มใบใหม่" หลัง 409
 *   6. 409 แสดงข้อความและไม่ปิดฟอร์ม
 *   7. เงินไม่ถูก truncate
 *   8. ช่องทางที่ผูกกระเป๋าอื่น → เตือนและบล็อกก่อน submit
 */
const authState = vi.hoisted(() => ({
  currentRoomId: 7,
  currentUserName: 'ครูผู้จัดทำ',
  canManageFinance: true,
}))

const { alertMock, notifyMock, pushMock } = vi.hoisted(() => ({
  alertMock: vi.fn<(title: string, text?: string, icon?: string) => Promise<unknown>>(),
  notifyMock: vi.fn<(message: string, icon?: string) => unknown>(),
  pushMock: vi.fn<(to: unknown) => void>(),
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => authState,
}))

vi.mock('@/composables/useDialog', () => ({
  useDialog: () => ({
    alert: alertMock,
    notify: notifyMock,
    confirm: vi.fn<() => Promise<{ isConfirmed: boolean }>>(),
    fire: vi.fn<(opts: unknown) => Promise<unknown>>(),
    input: vi.fn<(opts: unknown) => Promise<unknown>>(),
    loading: vi.fn<() => Promise<unknown>>(),
  }),
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: pushMock }),
  useRoute: () => ({ params: { id: '1' } }),
}))

vi.mock('@/services/finance', () => ({
  FinanceService: {
    getAccounts: vi.fn<() => Promise<Account[]>>(),
    getCategories: vi.fn<() => Promise<Category[]>>(),
    getPaymentChannels: vi.fn<() => Promise<PaymentChannel[]>>(),
    getPeople: vi.fn<() => Promise<unknown[]>>(),
    createIncomeBatch: vi.fn<
      (roomId: number, payload: IncomeBatchCreate) => Promise<IncomeBatchCreateResponse>
    >(),
  },
}))

const RouterLinkStub = defineComponent({
  name: 'RouterLink',
  props: { to: { type: [String, Object], required: true } },
  template: '<a><slot /></a>',
})

const ACCOUNTS: Account[] = [
  { id: 1, account_name: 'เงินสดห้อง', balance: 5000 },
  { id: 2, account_name: 'ธนาคารห้อง', balance: 1000 },
]

const CATEGORIES: Category[] = [
  { id: 20, category_name: 'เงินบริจาค', category_type: 'income' },
  { id: 21, category_name: 'รายได้อื่น', category_type: 'income' },
]

const CHANNELS: PaymentChannel[] = [
  {
    id: 5,
    channel_type: 'bank_transfer',
    label: 'โอนเข้าบัญชีห้อง',
    wallet_account_id: 1,
    wallet_account_name: 'เงินสดห้อง',
    account_name: 'ห้อง 6/1',
    bank_name: 'กสิกร',
    account_number_masked: 'xxx-x-x1234-5',
    promptpay_id_masked: null,
    qr_mode: null,
    is_primary: true,
    is_active: true,
    sort_order: 1,
    has_qr: false,
  },
  {
    id: 6,
    channel_type: 'cash',
    label: 'เงินสด (ช่องทางสำรอง)',
    wallet_account_id: 2,
    wallet_account_name: 'ธนาคารห้อง',
    account_name: null,
    bank_name: null,
    account_number_masked: null,
    promptpay_id_masked: null,
    qr_mode: null,
    is_primary: false,
    is_active: true,
    sort_order: 2,
    has_qr: false,
  },
]

const CREATED: IncomeBatchCreateResponse = {
  id: 77,
  total_amount: 150,
  line_count: 2,
  inc_receipt_id: 701,
  inc_receipt_no: 'INC-2569-0001',
  created_at: '2026-11-25T03:00:00Z',
  reused: false,
}

/** error รูปแบบ AxiosError ขั้นต่ำที่ `apiStatus()` อ่านได้ */
const apiError = (status: number, message = 'ข้อมูลไม่ผ่าน') => {
  const error = new Error(message) as Error & {
    isAxiosError: boolean
    response: { status: number; data: { detail: string } }
  }
  error.isAxiosError = true
  error.response = { status, data: { detail: message } }
  return error
}

const mountCreate = async () => {
  const wrapper = mount(IncomeBatchCreatePage, {
    global: {
      stubs: {
        RouterLink: RouterLinkStub,
        PersonPicker: true,
      },
    },
  })
  await flushPromises()
  return wrapper
}

type Wrapper = Awaited<ReturnType<typeof mountCreate>>

/** กรอกฟอร์มจนผ่าน validation ครบ (1 บรรทัด) */
const fillValidForm = async (wrapper: Wrapper) => {
  await wrapper.get('[data-test="payer-name"]').setValue('ผู้ปกครองกลุ่ม 6/1')
  await wrapper.get('[data-test="receiver-name"]').setValue('ครูสมหญิง')
  await wrapper.get('[data-test="wallet"]').setValue('1')
  await wrapper.get('[data-test="line-description"]').setValue('เงินสนับสนุนกีฬาสี')
  await wrapper.get('[data-test="line-amount"]').setValue('250')
  await wrapper.get('[data-test="line-category"]').setValue('20')
  await flushPromises()
}

const submit = async (wrapper: Wrapper) => {
  await wrapper.get('form').trigger('submit')
  await flushPromises()
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(FinanceService.getAccounts).mockResolvedValue(ACCOUNTS)
  vi.mocked(FinanceService.getCategories).mockResolvedValue(CATEGORIES)
  vi.mocked(FinanceService.getPaymentChannels).mockResolvedValue(CHANNELS)
  vi.mocked(FinanceService.getPeople).mockResolvedValue([])
  vi.mocked(FinanceService.createIncomeBatch).mockResolvedValue(CREATED)
  alertMock.mockResolvedValue({ isConfirmed: true })
})

describe('IncomeBatchCreate', () => {
  it('total_updates_when_line_amount_changes', async () => {
    const wrapper = await mountCreate()
    const amount = wrapper.get('[data-test="line-amount"]')

    await amount.setValue('250')
    await flushPromises()
    expect(wrapper.get('[data-test="income-total"]').text()).toContain('฿250.00')

    await amount.setValue('300.5')
    await flushPromises()
    expect(wrapper.get('[data-test="income-total"]').text()).toContain('฿300.50')
  })

  it('rejects_submit_without_payer_or_receiver', async () => {
    const wrapper = await mountCreate()
    await wrapper.get('[data-test="receiver-name"]').setValue('ครูสมหญิง')
    await wrapper.get('[data-test="wallet"]').setValue('1')
    await wrapper.get('[data-test="line-description"]').setValue('เงินสนับสนุน')
    await wrapper.get('[data-test="line-amount"]').setValue('100')
    await wrapper.get('[data-test="line-category"]').setValue('20')
    // ⛔ ไม่กรอกชื่อผู้จ่าย

    await submit(wrapper)

    expect(alertMock).toHaveBeenCalledTimes(1)
    expect(String(alertMock.mock.calls[0]?.[1])).toContain('ผู้จ่าย')
    expect(FinanceService.createIncomeBatch).not.toHaveBeenCalled()

    // มีผู้จ่ายแล้วแต่ยังไม่มีผู้รับ → ยังไม่ยิง API
    await wrapper.get('[data-test="payer-name"]').setValue('ผู้ปกครองกลุ่ม 6/1')
    await wrapper.get('[data-test="receiver-name"]').setValue('')
    await submit(wrapper)

    expect(FinanceService.createIncomeBatch).not.toHaveBeenCalled()
    expect(String(alertMock.mock.calls[1]?.[1])).toContain('ผู้รับเงิน')
  })

  it('keeps_single_wallet_for_all_lines', async () => {
    const wrapper = await mountCreate()
    await fillValidForm(wrapper)

    await wrapper.get('[data-test="add-line"]').trigger('click')
    await flushPromises()
    const descriptions = wrapper.findAll('[data-test="line-description"]')
    const amounts = wrapper.findAll('[data-test="line-amount"]')
    const categories = wrapper.findAll('[data-test="line-category"]')
    await descriptions[1]?.setValue('ขายของงานกีฬาสี')
    await amounts[1]?.setValue('50')
    await categories[1]?.setValue('21')

    // 👜 กระเป๋าเดียวทั้งใบ — ไม่มีช่องกระเป๋าต่อบรรทัด
    expect(wrapper.findAll('[data-test="wallet"]')).toHaveLength(1)
    expect(wrapper.findAll('[data-test="line-wallet"]')).toHaveLength(0)

    await submit(wrapper)

    const [, payload] = vi.mocked(FinanceService.createIncomeBatch).mock.calls[0]!
    expect(payload.wallet_account_id).toBe(1)
    expect(payload.lines).toHaveLength(2)
    for (const line of payload.lines) {
      expect('wallet_account_id' in line).toBe(false)
    }
    expect(payload.total_amount).toBe(300)
  })

  it('keeps_same_idempotency_key_on_failed_retry', async () => {
    vi.mocked(FinanceService.createIncomeBatch)
      .mockRejectedValueOnce(apiError(400, 'หมวดนี้ไม่ใช่หมวดรายรับ'))
      .mockResolvedValueOnce(CREATED)

    const wrapper = await mountCreate()
    await fillValidForm(wrapper)

    await submit(wrapper) // 400
    await submit(wrapper) // retry

    const calls = vi.mocked(FinanceService.createIncomeBatch).mock.calls
    expect(calls).toHaveLength(2)
    const firstKey = calls[0]?.[1].idempotency_key
    expect(firstKey).toBeTruthy()
    expect(calls[1]?.[1].idempotency_key).toBe(firstKey)
  })

  it('regenerates_key_only_when_user_clicks_new_draft', async () => {
    vi.mocked(FinanceService.createIncomeBatch)
      .mockRejectedValueOnce(apiError(409, 'คีย์นี้เคยใช้กับข้อมูลอื่น'))
      .mockResolvedValueOnce(CREATED)

    const wrapper = await mountCreate()
    await fillValidForm(wrapper)
    await submit(wrapper) // 409

    expect(wrapper.find('[data-test="conflict-banner"]').exists()).toBe(true)
    await wrapper.get('[data-test="new-draft"]').trigger('click')
    await flushPromises()

    // ฟอร์มถูกล้าง → กรอกใหม่แล้วส่งด้วยคีย์ใหม่
    await fillValidForm(wrapper)
    await submit(wrapper)

    const calls = vi.mocked(FinanceService.createIncomeBatch).mock.calls
    expect(calls).toHaveLength(2)
    expect(calls[1]?.[1].idempotency_key).not.toBe(calls[0]?.[1].idempotency_key)
  })

  it('shows_409_message_without_closing_form', async () => {
    vi.mocked(FinanceService.createIncomeBatch).mockRejectedValueOnce(
      apiError(409, 'คีย์นี้เคยใช้กับข้อมูลอื่น'),
    )

    const wrapper = await mountCreate()
    await fillValidForm(wrapper)
    await submit(wrapper)

    expect(alertMock).toHaveBeenCalledTimes(1)
    expect(alertMock.mock.calls[0]?.[0]).toBe('คีย์นี้ถูกใช้แล้ว')
    // ฟอร์มและค่าที่กรอกยังอยู่
    expect(wrapper.find('[data-test="conflict-banner"]').exists()).toBe(true)
    expect((wrapper.get('[data-test="line-amount"]').element as HTMLInputElement).value).toBe('250')
    expect((wrapper.get('[data-test="payer-name"]').element as HTMLInputElement).value).toBe(
      'ผู้ปกครองกลุ่ม 6/1',
    )
  })

  it('does_not_truncate_money_text', async () => {
    const wrapper = await mountCreate()
    await wrapper.get('[data-test="line-amount"]').setValue('1234567.89')
    await flushPromises()

    const total = wrapper.get('[data-test="income-total"]').text()
    expect(total).toContain('฿1,234,567.89')
    expect(total).not.toContain('…')
  })

  it('warns_when_channel_wallet_differs_from_selected_wallet', async () => {
    const wrapper = await mountCreate()
    await fillValidForm(wrapper)
    await flushPromises()

    // ช่องทาง 5 ผูกกระเป๋า 1 → เข้ากัน ไม่มีคำเตือน
    await wrapper.get('[data-test="channel"]').setValue('5')
    await flushPromises()
    expect(wrapper.find('[data-test="channel-wallet-warning"]').exists()).toBe(false)

    // ช่องทาง 6 ผูกกระเป๋า 2 แต่ฟอร์มเลือกกระเป๋า 1 → ต้องเตือนและบล็อกก่อน submit
    await wrapper.get('[data-test="channel"]').setValue('6')
    await flushPromises()
    expect(wrapper.find('[data-test="channel-wallet-warning"]').exists()).toBe(true)

    await submit(wrapper)

    expect(FinanceService.createIncomeBatch).not.toHaveBeenCalled()
    expect(String(alertMock.mock.calls[0]?.[1])).toContain('ช่องทาง')
  })
})
