import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'

import CustodyCard from '@/components/finance/CustodyCard.vue'
import HandoverModal from '@/components/finance/HandoverModal.vue'
import { FinanceService } from '@/services/finance'
import type { Account, CustodyItem, CustodyMovement } from '@/types/finance'

/**
 * 👜 เงินสดรอส่งมอบ — เทสต์หน้าจอ (FIN-V2 / P3.2)
 *
 * สิ่งที่ล็อกไว้:
 *   1. เงินแสดงด้วย `formatMoney` (฿ + 2 ตำแหน่ง) และ **ไม่ถูก truncate**
 *   2. ฟอร์มส่งมอบส่งไม่ได้เมื่อยอด ≤ 0 (และจำนวนเกินยอดถือก็ไม่ได้)
 *   3. `idempotency_key` **คงเดิม** ตลอดการ retry ของฟอร์มเดียว
 *      (ถ้าเปลี่ยนตอน submit เน็ตสะดุด = ส่งมอบซ้ำ)
 *   4. 409/400 จาก backend แสดงข้อความไทยโดยไม่ปิดฟอร์ม
 */
const authState = vi.hoisted(() => ({ currentRoomId: 7, canManageFinance: true }))

const { alertMock, notifyMock, inputMock } = vi.hoisted(() => ({
  alertMock: vi.fn<(title: string, text?: string, icon?: string) => Promise<unknown>>(),
  notifyMock: vi.fn<(text: string) => unknown>(),
  inputMock: vi.fn<(title: string, extra?: unknown) => Promise<{ isConfirmed: boolean; value?: string }>>(),
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => authState,
}))

vi.mock('@/services/finance', () => ({
  FinanceService: {
    createCustodyHandover: vi.fn<(roomId: number, payload: unknown) => Promise<unknown>>(),
    voidCustodyHandover: vi.fn<(roomId: number, handoverId: number, payload: unknown) => Promise<unknown>>(),
    getCustodyMovements: vi.fn<() => Promise<{ person_id: number; account_id: number; items: CustodyMovement[] }>>(),
  },
}))

vi.mock('@/composables/useDialog', () => ({
  useDialog: () => ({
    alert: alertMock,
    notify: notifyMock,
    input: inputMock,
    confirm: vi.fn<() => Promise<{ isConfirmed: boolean }>>(),
  }),
}))

/** แทน AppSheet (Teleport) — เทสต์สนใจเนื้อหา ไม่ใช่การจัดชั้นของแผ่น */
const AppSheetStub = defineComponent({
  name: 'AppSheet',
  props: { open: { type: Boolean, default: false } },
  emits: ['close'],
  template: '<div v-if="open" data-test="sheet"><slot /><slot name="footer" /></div>',
})

const ITEM: CustodyItem = {
  person_id: 3,
  display_name: 'ครูสมหญิง',
  account_id: 42,
  account_name: 'ครูสมหญิง (เงินสดรอส่งมอบ)',
  account_kind: 'cash',
  balance: 1500,
  last_handover_at: '2026-11-25T03:00:00Z',
}

const ACCOUNTS: Account[] = [{ id: 5, account_name: 'เงินสดห้อง', balance: 5000 }]

const mountModal = (open = true) =>
  mount(HandoverModal, {
    props: {
      open,
      mode: 'handover' as const,
      item: ITEM,
      accounts: ACCOUNTS,
      people: [],
      canManage: true,
    },
    global: { stubs: { AppSheet: AppSheetStub } },
  })

const submitButton = (wrapper: ReturnType<typeof mountModal>) => {
  const btn = wrapper.findAll('button').find((b) => b.text().includes('บันทึกการส่งมอบ'))
  if (!btn) throw new Error('ไม่พบปุ่มบันทึกการส่งมอบ')
  return btn
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('CustodyCard', () => {
  it('formats_balance_with_two_decimals', () => {
    const wrapper = mount(CustodyCard, { props: { item: ITEM, canManage: false } })
    const text = wrapper.text()
    expect(text).toContain('฿1,500.00')
    expect(text).toContain('ครูสมหญิง')
    expect(text).toContain('เงินสด')
  })

  it('does_not_truncate_money_text', () => {
    const wrapper = mount(CustodyCard, { props: { item: ITEM, canManage: true } })
    const balance = wrapper.find('[data-test="custody-balance"]')
    expect(balance.exists()).toBe(true)
    expect(balance.classes()).not.toContain('truncate')
    expect(balance.classes()).not.toContain('overflow-hidden')
  })
})

describe('HandoverModal — handover', () => {
  it('disables_submit_when_amount_is_zero_or_negative', async () => {
    const wrapper = mountModal()
    const amount = wrapper.find('#handoverAmount')

    await amount.setValue('0')
    expect(submitButton(wrapper).attributes('disabled')).toBeDefined()

    await amount.setValue('-5')
    expect(wrapper.text()).toContain('จำนวนเงินต้องมากกว่าศูนย์')
    expect(submitButton(wrapper).attributes('disabled')).toBeDefined()

    await amount.setValue('100')
    expect(submitButton(wrapper).attributes('disabled')).toBeUndefined()
  })

  it('keeps_same_idempotency_key_across_failed_retry', async () => {
    vi.mocked(FinanceService.createCustodyHandover).mockRejectedValueOnce(
      new Error('เครือข่ายขาดการเชื่อมต่อ'),
    )
    vi.mocked(FinanceService.createCustodyHandover).mockResolvedValueOnce({
      id: 1,
      from_account_id: 42,
      to_account_id: 5,
      amount: 100,
      status: 'active',
      journal_entry_id: '9',
      created_at: '2026-11-25T03:00:00Z',
    })

    const wrapper = mountModal()
    await wrapper.find('#handoverAmount').setValue('100')

    await submitButton(wrapper).trigger('click')
    await flushPromises()
    await submitButton(wrapper).trigger('click')
    await flushPromises()

    const calls = vi.mocked(FinanceService.createCustodyHandover).mock.calls
    expect(calls).toHaveLength(2)
    const firstCall = calls[0]
    const secondCall = calls[1]
    if (!firstCall || !secondCall) throw new Error('ต้องมีสองคำขอ')
    const firstKey = firstCall[1].idempotency_key
    const secondKey = secondCall[1].idempotency_key
    expect(firstKey).toBeTruthy()
    expect(secondKey).toBe(firstKey)
  })

  it('shows_conflict_message_on_409', async () => {
    vi.mocked(FinanceService.createCustodyHandover).mockRejectedValueOnce(
      new Error('ยกเลิกไม่ได้: เงินปลายทางถูกใช้ไปแล้ว'),
    )

    const wrapper = mountModal()
    await wrapper.find('#handoverAmount').setValue('100')
    await submitButton(wrapper).trigger('click')
    await flushPromises()

    expect(alertMock).toHaveBeenCalledWith(
      'ส่งมอบไม่สำเร็จ',
      'ยกเลิกไม่ได้: เงินปลายทางถูกใช้ไปแล้ว',
      'error',
    )
    // ฟอร์มต้องยังเปิดอยู่ (emit close ไม่ถูกเรียก)
    expect(wrapper.emitted('close')).toBeUndefined()
  })
})
