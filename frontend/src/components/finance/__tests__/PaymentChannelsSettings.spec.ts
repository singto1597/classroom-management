import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'

import PaymentChannelsSettings from '@/components/finance/PaymentChannelsSettings.vue'
import RowActionMenu from '@/components/ui/RowActionMenu.vue'
import { FinanceService } from '@/services/finance'
import { downloadBlob } from '@/utils/download'
import type {
  Account,
  PaymentChannel,
  PaymentChannelCreate,
  PaymentChannelUpdate,
} from '@/types/finance'

/**
 * 💳 `PaymentChannelsSettings` — แท็บช่องทางชำระเงิน (FIN-V2 / P2.5)
 *
 * สิ่งที่ล็อกไว้:
 *   1. **เลขเต็มไม่ขึ้นจอ/ไม่ย้อนกลับ backend** — response มีแต่ `*_masked`
 *      การแก้ไขต้องเริ่มช่องว่างและละคีย์ออก (ส่ง `null` = ล้างค่าจริง)
 *   2. **`active ≤ 3`** — ปุ่มเพิ่ม disable และการเปิดช่องทางที่ 4 ถูกดักก่อนเรียก API
 *   3. **`primary` ต้อง active** — ปุ่มตั้งหลัก disable เมื่อปิดใช้งาน
 *   4. QR: open สร้างทันที / fixed ต้องมียอดก่อน และ object URL ต้องถูก revoke
 */
const authState = vi.hoisted(() => ({ currentRoomId: 7, canManageFinance: true }))

const { alertMock, confirmMock, notifyMock, objectUrl } = vi.hoisted(() => ({
  alertMock: vi.fn<(title: string, text?: string, icon?: string) => Promise<unknown>>(),
  confirmMock: vi.fn<() => Promise<{ isConfirmed: boolean }>>(),
  notifyMock: vi.fn<(text: string) => unknown>(),
  objectUrl: {
    create: vi.fn<() => string>(() => 'blob:channel-qr'),
    revoke: vi.fn<(url: string) => void>(),
  },
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => authState,
}))

vi.mock('@/services/finance', () => ({
  FinanceService: {
    getPaymentChannels: vi.fn<(roomId: number, includeInactive?: boolean) => Promise<PaymentChannel[]>>(),
    getAccounts: vi.fn<(roomId: number) => Promise<Account[]>>(),
    createPaymentChannel: vi.fn<
      (roomId: number, payload: PaymentChannelCreate) => Promise<PaymentChannel>
    >(),
    updatePaymentChannel: vi.fn<
      (roomId: number, channelId: number, payload: PaymentChannelUpdate) => Promise<PaymentChannel>
    >(),
    deletePaymentChannel: vi.fn<
      (roomId: number, channelId: number) => Promise<{ status: string }>
    >(),
    getPaymentChannelQr: vi.fn<() => Promise<Blob>>(),
  },
}))

vi.mock('@/composables/useDialog', () => ({
  useDialog: () => ({ alert: alertMock, confirm: confirmMock, notify: notifyMock }),
}))

vi.mock('@/utils/download', () => ({ downloadBlob: vi.fn<(blob: Blob, filename: string) => void>() }))

/** แทน AppSheet (Teleport) — เทสต์สนใจเนื้อหา ไม่ใช่การจัดชั้นของแผ่น */
const AppSheetStub = defineComponent({
  name: 'AppSheet',
  props: { open: { type: Boolean, default: false } },
  emits: ['close'],
  template: '<div v-if="open" data-test="sheet"><slot /><slot name="footer" /></div>',
})

const ACCOUNTS: Account[] = [{ id: 5, account_name: 'เงินสดห้อง', balance: 0 }]

const PROMPTPAY_OPEN: PaymentChannel = {
  id: 1,
  channel_type: 'promptpay',
  label: 'พร้อมเพย์ครูเอ',
  wallet_account_id: 5,
  wallet_account_name: 'เงินสดห้อง',
  account_name: 'ครูเอ',
  bank_name: null,
  account_number_masked: null,
  promptpay_id_masked: '081-XXX-5678',
  qr_mode: 'open',
  is_primary: true,
  is_active: true,
  sort_order: 10,
  has_qr: true,
}

const PROMPTPAY_FIXED: PaymentChannel = {
  ...PROMPTPAY_OPEN,
  id: 4,
  label: 'พร้อมเพย์ฝังยอด',
  qr_mode: 'fixed',
  is_primary: false,
  sort_order: 40,
}

const CASH: PaymentChannel = {
  id: 2,
  channel_type: 'cash',
  label: 'เงินสด',
  wallet_account_id: 5,
  wallet_account_name: 'เงินสดห้อง',
  account_name: null,
  bank_name: null,
  account_number_masked: null,
  promptpay_id_masked: null,
  qr_mode: null,
  is_primary: false,
  is_active: true,
  sort_order: 20,
  has_qr: false,
}

const BANK: PaymentChannel = {
  id: 3,
  channel_type: 'bank_transfer',
  label: 'กรุงไทย',
  wallet_account_id: null,
  wallet_account_name: null,
  account_name: 'ครูเอ',
  bank_name: 'กรุงไทย',
  account_number_masked: '******7890',
  promptpay_id_masked: null,
  qr_mode: null,
  is_primary: false,
  is_active: true,
  sort_order: 30,
  has_qr: false,
}

const INACTIVE: PaymentChannel = {
  ...CASH,
  id: 6,
  label: 'เงินสดเก่า',
  is_active: false,
  sort_order: 60,
}

const mountComponent = async () => {
  const wrapper = mount(PaymentChannelsSettings, {
    global: { stubs: { AppSheet: AppSheetStub } },
  })
  await flushPromises()
  return wrapper
}

type Wrapper = Awaited<ReturnType<typeof mountComponent>>

const buttonByLabel = (wrapper: Wrapper, label: string) => {
  const btn = wrapper.find(`button[aria-label="${label}"]`)
  if (!btn.exists()) throw new Error(`ไม่พบปุ่ม "${label}"`)
  return btn
}

const buttonByText = (wrapper: Wrapper, text: string) => {
  const btn = wrapper.findAll('button').find((b) => b.text().includes(text))
  if (!btn) throw new Error(`ไม่พบปุ่ม "${text}"`)
  return btn
}

beforeEach(() => {
  authState.currentRoomId = 7
  authState.canManageFinance = true

  vi.mocked(FinanceService.getPaymentChannels).mockReset().mockResolvedValue([PROMPTPAY_OPEN, CASH])
  vi.mocked(FinanceService.getAccounts).mockReset().mockResolvedValue(ACCOUNTS)
  vi.mocked(FinanceService.createPaymentChannel).mockReset().mockResolvedValue(CASH)
  vi.mocked(FinanceService.updatePaymentChannel).mockReset().mockResolvedValue(CASH)
  vi.mocked(FinanceService.deletePaymentChannel).mockReset().mockResolvedValue({ status: 'success' })
  vi.mocked(FinanceService.getPaymentChannelQr)
    .mockReset()
    .mockResolvedValue(new Blob(['<svg/>'], { type: 'image/svg+xml' }))

  alertMock.mockReset()
  confirmMock.mockReset().mockResolvedValue({ isConfirmed: true })
  notifyMock.mockReset()
  vi.mocked(downloadBlob).mockReset()

  objectUrl.create.mockClear()
  objectUrl.revoke.mockClear()
  Object.defineProperty(URL, 'createObjectURL', {
    value: objectUrl.create,
    configurable: true,
    writable: true,
  })
  Object.defineProperty(URL, 'revokeObjectURL', {
    value: objectUrl.revoke,
    configurable: true,
    writable: true,
  })
})

describe('PaymentChannelsSettings', () => {
  it('แสดงรายการด้วยค่า mask เท่านั้น', async () => {
    vi.mocked(FinanceService.getPaymentChannels).mockResolvedValue([PROMPTPAY_OPEN, BANK])
    const wrapper = await mountComponent()

    expect(FinanceService.getPaymentChannels).toHaveBeenCalledWith(7, true)
    expect(wrapper.text()).toContain('พร้อมเพย์ครูเอ')
    expect(wrapper.text()).toContain('081-XXX-5678')
    expect(wrapper.text()).toContain('******7890')
    expect(wrapper.text()).not.toContain('0066812345678')
    expect(wrapper.text()).not.toContain('1234567890')
  })

  it('ซ่อนปุ่มเขียนเมื่อไม่มี MANAGE_FINANCE แต่ยังดู QR ได้', async () => {
    authState.canManageFinance = false
    const wrapper = await mountComponent()

    expect(wrapper.find('button[aria-label="แก้ไข พร้อมเพย์ครูเอ"]').exists()).toBe(false)
    expect(wrapper.findAll('button').some((b) => b.text().includes('เพิ่มช่องทาง'))).toBe(false)
    // อ่าน/ดู QR เปิดให้สมาชิกห้องทุกคน
    expect(wrapper.find('button[aria-label="ดู QR ของ พร้อมเพย์ครูเอ"]').exists()).toBe(true)
  })

  it('ปุ่มเพิ่มช่องทาง disabled เมื่อเปิดใช้งานครบ 3', async () => {
    const third = { ...BANK, id: 3 }
    vi.mocked(FinanceService.getPaymentChannels).mockResolvedValue([
      PROMPTPAY_OPEN,
      CASH,
      third,
    ])
    const wrapper = await mountComponent()

    const add = buttonByText(wrapper, 'เพิ่มช่องทาง')
    expect(add.attributes('disabled')).toBeDefined()
  })

  it('เปิดช่องทางที่ 4 แจ้งเตือนและไม่เรียก API', async () => {
    vi.mocked(FinanceService.getPaymentChannels).mockResolvedValue([
      PROMPTPAY_OPEN,
      CASH,
      BANK,
      INACTIVE,
    ])
    const wrapper = await mountComponent()

    await buttonByLabel(wrapper, 'เปิดใช้งาน เงินสดเก่า').trigger('click')
    await flushPromises()

    expect(alertMock).toHaveBeenCalledWith(
      'ครบ 3 ช่องทางแล้ว',
      expect.stringContaining('ครบ 3 ช่องทาง'),
      'warning',
    )
    expect(FinanceService.updatePaymentChannel).not.toHaveBeenCalled()
  })

  it('สร้าง PromptPay: ส่งชนิด/เลขเต็ม/qr_mode/primary ตามที่กรอก', async () => {
    const wrapper = await mountComponent()

    await buttonByText(wrapper, 'เพิ่มช่องทาง').trigger('click')
    await wrapper.find('#channelType').setValue('promptpay')
    await wrapper.find('#channelLabel').setValue('พร้อมเพย์ใหม่')
    await wrapper.find('#channelPromptpayName').setValue('ครูบี')
    await wrapper.find('#channelPromptpayId').setValue('0891234567')
    await wrapper.find('#channelQrMode').setValue('fixed')
    await wrapper.find('#channelWallet').setValue('5')

    await buttonByText(wrapper, 'บันทึก').trigger('click')
    await flushPromises()

    expect(FinanceService.createPaymentChannel).toHaveBeenCalledTimes(1)
    const [roomId, payload] = vi.mocked(FinanceService.createPaymentChannel).mock.calls[0]!
    expect(roomId).toBe(7)
    expect(payload).toMatchObject({
      channel_type: 'promptpay',
      label: 'พร้อมเพย์ใหม่',
      promptpay_id: '0891234567',
      qr_mode: 'fixed',
      wallet_account_id: 5,
      is_primary: false,
      is_active: true,
      account_number: null,
    })
  })

  it('แก้ไข: ช่องความลับว่าง ⇒ ละคีย์ออก (ไม่ส่ง null)', async () => {
    vi.mocked(FinanceService.getPaymentChannels).mockResolvedValue([PROMPTPAY_OPEN])
    const wrapper = await mountComponent()

    await buttonByLabel(wrapper, 'แก้ไข พร้อมเพย์ครูเอ').trigger('click')
    // ห้าม prefill mask ลงช่องกรอก
    const secretInput = wrapper.find('#channelPromptpayId').element as HTMLInputElement
    expect(secretInput.value).toBe('')

    await wrapper.find('#channelLabel').setValue('พร้อมเพย์ครูเอ (ใหม่)')
    await buttonByText(wrapper, 'บันทึก').trigger('click')
    await flushPromises()

    expect(FinanceService.updatePaymentChannel).toHaveBeenCalledTimes(1)
    const [roomId, channelId, payload] =
      vi.mocked(FinanceService.updatePaymentChannel).mock.calls[0]!
    expect(roomId).toBe(7)
    expect(channelId).toBe(1)
    expect(payload).toMatchObject({ label: 'พร้อมเพย์ครูเอ (ใหม่)', qr_mode: 'open' })
    expect(payload).not.toHaveProperty('promptpay_id')
    expect(payload).not.toHaveProperty('account_number')
    expect(payload).not.toHaveProperty('channel_type')
  })

  it('แก้ไขอยู่เปลี่ยนชนิดช่องทางไม่ได้', async () => {
    const wrapper = await mountComponent()
    await buttonByLabel(wrapper, 'แก้ไข พร้อมเพย์ครูเอ').trigger('click')

    const select = wrapper.find('#channelType').element as HTMLSelectElement
    expect(select.disabled).toBe(true)
  })

  it('ลบต้องยืนยันก่อน แล้วเรียก API + โหลดใหม่', async () => {
    const wrapper = await mountComponent()
    const menus = wrapper.findAllComponents(RowActionMenu)
    expect(menus.length).toBeGreaterThan(0)

    menus[0]!.vm.$emit('select', 'delete')
    await flushPromises()

    expect(confirmMock).toHaveBeenCalled()
    expect(FinanceService.deletePaymentChannel).toHaveBeenCalledWith(7, 1)
    expect(FinanceService.getPaymentChannels).toHaveBeenCalledTimes(2)
  })

  it('ปุ่มตั้งเป็นหลัก disabled เมื่อปิดใช้งาน / เรียก update เมื่อแถวเปิดใช้งาน', async () => {
    vi.mocked(FinanceService.getPaymentChannels).mockResolvedValue([
      PROMPTPAY_OPEN,
      CASH,
      INACTIVE,
    ])
    const wrapper = await mountComponent()

    expect(
      buttonByLabel(wrapper, 'ตั้ง เงินสดเก่า เป็นช่องทางหลัก').attributes('disabled'),
    ).toBeDefined()
    // ตัวที่เป็นหลักอยู่แล้วก็ตั้งซ้ำไม่ได้ (แต่ไม่ disabled เพราะ active)
    expect(
      buttonByLabel(wrapper, 'ตั้ง พร้อมเพย์ครูเอ เป็นช่องทางหลัก').attributes('disabled'),
    ).toBeDefined()

    await buttonByLabel(wrapper, 'ตั้ง เงินสด เป็นช่องทางหลัก').trigger('click')
    await flushPromises()

    expect(FinanceService.updatePaymentChannel).toHaveBeenCalledWith(7, 2, { is_primary: true })
  })

  it('QR open: สร้างทันทีโดยไม่ส่ง amount', async () => {
    const wrapper = await mountComponent()

    await buttonByLabel(wrapper, 'ดู QR ของ พร้อมเพย์ครูเอ').trigger('click')
    await flushPromises()

    expect(FinanceService.getPaymentChannelQr).toHaveBeenCalledWith(7, 1, undefined)
    const img = wrapper.find('img[alt="PromptPay QR ของ พร้อมเพย์ครูเอ"]')
    expect(img.exists()).toBe(true)
    expect(img.attributes('src')).toBe('blob:channel-qr')
    // ไม่มี v-html: เนื้อหา SVG ไม่ถูกฝังเป็น DOM
    expect(wrapper.find('svg').exists()).toBe(false)
  })

  it('QR fixed: ต้องกรอกยอดให้ถูกก่อนจึงเรียก API', async () => {
    vi.mocked(FinanceService.getPaymentChannels).mockResolvedValue([PROMPTPAY_FIXED])
    const wrapper = await mountComponent()

    await buttonByLabel(wrapper, 'ดู QR ของ พร้อมเพย์ฝังยอด').trigger('click')
    await flushPromises()
    // เปิดแผ่นแล้วแต่ยังไม่สร้าง — รอผู้ใช้กรอกยอด
    expect(FinanceService.getPaymentChannelQr).not.toHaveBeenCalled()

    await wrapper.find('#qrAmount').setValue('0')
    await buttonByText(wrapper, 'สร้าง QR').trigger('click')
    await flushPromises()
    expect(alertMock).toHaveBeenCalled()
    expect(FinanceService.getPaymentChannelQr).not.toHaveBeenCalled()

    await wrapper.find('#qrAmount').setValue('250.50')
    await buttonByText(wrapper, 'สร้าง QR').trigger('click')
    await flushPromises()
    expect(FinanceService.getPaymentChannelQr).toHaveBeenCalledWith(7, 4, 250.5)
  })

  it('ปิดแผ่น QR ⇒ revoke object URL (ไม่ค้างหน่วยความจำ)', async () => {
    const wrapper = await mountComponent()

    await buttonByLabel(wrapper, 'ดู QR ของ พร้อมเพย์ครูเอ').trigger('click')
    await flushPromises()
    expect(objectUrl.create).toHaveBeenCalledTimes(1)

    await buttonByText(wrapper, 'ปิด').trigger('click')
    await flushPromises()

    expect(objectUrl.revoke).toHaveBeenCalledWith('blob:channel-qr')
    expect(wrapper.find('img[alt="PromptPay QR ของ พร้อมเพย์ครูเอ"]').exists()).toBe(false)
  })

  it('แสดง badge หลัก และ ปิดใช้งาน ตามสถานะจริง', async () => {
    vi.mocked(FinanceService.getPaymentChannels).mockResolvedValue([
      PROMPTPAY_OPEN,
      INACTIVE,
    ])
    const wrapper = await mountComponent()

    expect(wrapper.text()).toContain('หลัก')
    expect(wrapper.text()).toContain('ปิดใช้งาน')
    expect(wrapper.text()).toContain('1/3')
  })

  it('โหลดล้มเหลว ⇒ StateBlock error + ปุ่มลองใหม่เรียก API ซ้ำ', async () => {
    vi.mocked(FinanceService.getPaymentChannels).mockRejectedValue(new Error('backend ล่ม'))
    const wrapper = await mountComponent()

    expect(wrapper.text()).toContain('backend ล่ม')
    expect(FinanceService.getPaymentChannels).toHaveBeenCalledTimes(1)

    await buttonByText(wrapper, 'ลองอีกครั้ง').trigger('click')
    await flushPromises()
    expect(FinanceService.getPaymentChannels).toHaveBeenCalledTimes(2)
  })
})
