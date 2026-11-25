import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'

import ExpenseVoucherCreatePage from '@/views/finance/ExpenseVoucherCreate.vue'
import { FinanceService } from '@/services/finance'
import type {
  Account,
  Category,
  ExpenseVoucherCreate,
  ExpenseVoucherCreateResponse,
} from '@/types/finance'

/**
 * 💸 ใบสำคัญจ่าย — เทสต์หน้าสร้าง (FIN-V2 / P4.3)
 *
 * สิ่งที่ล็อกไว้ (brief P4.3):
 *   1. ยอดรวมอัปเดตสดเมื่อแก้จำนวนเงินของบรรทัด
 *   2. validation ฝั่งจอ: ขาดหมวด/กระเป๋า → ไม่ยิง API
 *   3. retry ที่ล้มเหลว (400) ใช้ `idempotency_key` เดิม
 *   4. คีย์ใหม่เกิดเฉพาะเมื่อกด "เริ่มใบใหม่" หลัง 409
 *   5. บรรทัด `receipt_status='none'` แสดงว่า "จะอยู่ใน CERT"
 *   6. เปลี่ยนกระเป๋าหัวใบไม่ทับกระเป๋าที่ผู้ใช้เลือกเอง (walletTouched)
 *   7. 409 แสดงข้อความและไม่ปิดฟอร์ม
 *   8. เงินไม่ถูก truncate (แสดงหลักพัน/ทศนิยมครบ)
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
    confirm: vi.fn(),
    fire: vi.fn(),
    input: vi.fn(),
    loading: vi.fn(),
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
    getBudgets: vi.fn<() => Promise<unknown[]>>(),
    createExpenseVoucher: vi.fn<
      (roomId: number, payload: ExpenseVoucherCreate) => Promise<ExpenseVoucherCreateResponse>
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
  { id: 3, account_name: 'กระเป๋าสำรอง', balance: 100 },
]

const CATEGORIES: Category[] = [
  { id: 10, category_name: 'วัสดุสำนักงาน', category_type: 'expense' },
  { id: 11, category_name: 'ค่าขนส่ง', category_type: 'expense' },
]

const CREATED: ExpenseVoucherCreateResponse = {
  id: 99,
  total_amount: 250,
  line_count: 1,
  pv_receipt_id: 501,
  pv_receipt_no: 'PV-2569-0001',
  cert_receipt_id: 601,
  cert_receipt_no: 'CERT-2569-0001',
  cert_amount: 250,
  cert_line_nos: [1],
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
  const wrapper = mount(ExpenseVoucherCreatePage, {
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

/** กรอกฟอร์มจนผ่าน validation ครบ (1 บรรทัด) */
const fillValidForm = async (wrapper: Awaited<ReturnType<typeof mountCreate>>) => {
  await wrapper.get('[data-test="payee-name"]').setValue('ร้านวัสดุการเรียน')
  await wrapper.get('[data-test="default-wallet"]').setValue('1')
  await wrapper.get('[data-test="line-description"]').setValue('กระดาษ A4')
  await wrapper.get('[data-test="line-amount"]').setValue('250')
  await wrapper.get('[data-test="line-category"]').setValue('10')
  await flushPromises()
}

const submit = async (wrapper: Awaited<ReturnType<typeof mountCreate>>) => {
  await wrapper.get('form').trigger('submit')
  await flushPromises()
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(FinanceService.getAccounts).mockResolvedValue(ACCOUNTS)
  vi.mocked(FinanceService.getCategories).mockResolvedValue(CATEGORIES)
  vi.mocked(FinanceService.getBudgets).mockResolvedValue([])
  vi.mocked(FinanceService.createExpenseVoucher).mockResolvedValue(CREATED)
  alertMock.mockResolvedValue({ isConfirmed: true })
})

describe('ExpenseVoucherCreate', () => {
  it('total_updates_when_line_amount_changes', async () => {
    const wrapper = await mountCreate()
    const amount = wrapper.get('[data-test="line-amount"]')

    await amount.setValue('250')
    await flushPromises()
    expect(wrapper.get('[data-test="voucher-total"]').text()).toContain('฿250.00')

    await amount.setValue('300.5')
    await flushPromises()
    expect(wrapper.get('[data-test="voucher-total"]').text()).toContain('฿300.50')
  })

  it('rejects_submit_when_line_missing_category_or_wallet', async () => {
    const wrapper = await mountCreate()
    await wrapper.get('[data-test="payee-name"]').setValue('ร้านวัสดุการเรียน')
    await wrapper.get('[data-test="default-wallet"]').setValue('1')
    await wrapper.get('[data-test="line-description"]').setValue('กระดาษ A4')
    await wrapper.get('[data-test="line-amount"]').setValue('250')
    // ⛔ ไม่เลือกหมวดรายจ่าย

    await submit(wrapper)

    expect(alertMock).toHaveBeenCalledTimes(1)
    expect(String(alertMock.mock.calls[0]?.[1])).toContain('หมวดรายจ่าย')
    expect(FinanceService.createExpenseVoucher).not.toHaveBeenCalled()
  })

  it('keeps_same_idempotency_key_on_failed_retry', async () => {
    vi.mocked(FinanceService.createExpenseVoucher)
      .mockRejectedValueOnce(apiError(400, 'เงินในกระเป๋าไม่พอ'))
      .mockResolvedValueOnce(CREATED)

    const wrapper = await mountCreate()
    await fillValidForm(wrapper)

    await submit(wrapper) // 400
    await submit(wrapper) // retry

    const calls = vi.mocked(FinanceService.createExpenseVoucher).mock.calls
    expect(calls).toHaveLength(2)
    const firstKey = calls[0]?.[1].idempotency_key
    expect(firstKey).toBeTruthy()
    expect(calls[1]?.[1].idempotency_key).toBe(firstKey)
  })

  it('regenerates_key_only_when_user_clicks_new_draft', async () => {
    vi.mocked(FinanceService.createExpenseVoucher)
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

    const calls = vi.mocked(FinanceService.createExpenseVoucher).mock.calls
    expect(calls).toHaveLength(2)
    expect(calls[1]?.[1].idempotency_key).not.toBe(calls[0]?.[1].idempotency_key)
  })

  it('marks_receipt_status_none_lines_as_cert', async () => {
    const wrapper = await mountCreate()

    // ค่าเริ่มต้นของบรรทัด = 'none' ⇒ ต้องเห็นป้ายว่าจะอยู่ใน CERT
    const badge = wrapper.get('[data-test="cert-badge"]')
    expect(badge.text()).toContain('จะอยู่ใน CERT')

    await wrapper.get('[data-test="line-status"]').setValue('attached')
    await flushPromises()
    expect(wrapper.find('[data-test="cert-badge"]').exists()).toBe(false)
  })

  it('does_not_overwrite_manually_chosen_wallet_when_header_wallet_changes', async () => {
    const wrapper = await mountCreate()
    await wrapper.get('[data-test="default-wallet"]').setValue('1')
    await flushPromises()

    // ผู้ใช้เลือกกระเป๋าของบรรทัดที่ 1 เอง
    await wrapper.get('[data-test="line-wallet"]').setValue('2')
    await flushPromises()

    // เพิ่มบรรทัดที่ 2 (ยังไม่แตะกระเป๋า → ตามกระเป๋าหัวใบ = 1)
    await wrapper.get('[data-test="add-line"]').trigger('click')
    await flushPromises()

    // เปลี่ยนกระเป๋าหัวใบเป็น 3
    await wrapper.get('[data-test="default-wallet"]').setValue('3')
    await flushPromises()

    const wallets = wrapper.findAll('[data-test="line-wallet"]')
    expect(wallets).toHaveLength(2)
    expect((wallets[0]?.element as HTMLSelectElement).value).toBe('2')
    expect((wallets[1]?.element as HTMLSelectElement).value).toBe('3')
  })

  it('shows_409_message_without_closing_form', async () => {
    vi.mocked(FinanceService.createExpenseVoucher).mockRejectedValueOnce(
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
  })

  it('does_not_truncate_money_text', async () => {
    const wrapper = await mountCreate()
    await wrapper.get('[data-test="line-amount"]').setValue('1234567.89')
    await flushPromises()

    const total = wrapper.get('[data-test="voucher-total"]').text()
    expect(total).toContain('฿1,234,567.89')
    expect(total).not.toContain('…')
  })
})
