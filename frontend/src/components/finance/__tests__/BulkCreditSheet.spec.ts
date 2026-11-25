import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'

import BulkCreditSheet from '@/components/finance/BulkCreditSheet.vue'
import { FinanceService } from '@/services/finance'
import type {
  CreditApplyPlan,
  CreditRoundCreate,
  CreditRoundResponse,
} from '@/types/finance'

/**
 * 💳 `BulkCreditSheet` — หักเครดิตหลายคนเป็นรอบเดียว (FIN-V2 / P3.5)
 *
 * สิ่งที่ล็อกไว้ (ทุกข้อเกี่ยวกับ "เครดิตถูกหักผิด" หรือ "ครูไม่รู้ว่าอะไรพัง"):
 *   1. retry หลังล้มใช้ `idempotency_key` เดิม — เจตนาเดียวต้องไม่กลายเป็นสองรอบ
 *   2. **ไม่ส่งคนที่ไม่มี allocations** — กัน backend สร้าง event เปล่า + ตาราง skipped ว่าง
 *   3. 409 = คีย์เดิมกับชุดนักเรียนอื่น ⇒ **ไม่ปิดแผ่นเอง** และต้องเห็นข้อความ
 *   4. ไม่มี MANAGE_FINANCE ⇒ ไม่มีปุ่มเขียน
 */
const { authState } = vi.hoisted(() => ({
  authState: { canManageFinance: true },
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    currentRoomId: 7,
    currentUserName: 'ครูทดสอบ',
    get canManageFinance() {
      return authState.canManageFinance
    },
  }),
}))

vi.mock('@/services/finance', () => ({
  FinanceService: {
    createCreditRound: vi.fn<
      (roomId: number, payload: CreditRoundCreate) => Promise<CreditRoundResponse>
    >(),
  },
}))

vi.mock('@/services/api', () => ({
  apiStatus: (error: unknown) =>
    (error as { response?: { status?: number } })?.response?.status ?? 0,
}))

/** แทน AppSheet (Teleport) — เทสต์นี้สนใจเนื้อหา/พฤติกรรม ไม่ใช่การจัดชั้นของแผ่น */
const AppSheetStub = defineComponent({
  name: 'AppSheet',
  props: { open: { type: Boolean, default: false } },
  emits: ['close'],
  template: '<div v-if="open" data-test="sheet"><slot /><slot name="footer" /></div>',
})

const PLAN: CreditApplyPlan = {
  status: 'success',
  message: null,
  items: [
    {
      student_id: 11,
      student_no: 1,
      student_name: 'อาร์ม',
      balance_before: 500,
      allocations: [
        {
          payment_id: 101,
          collection_id: 201,
          title: 'ค่าเทอม',
          due_date: null,
          bill_total: 300,
          bill_paid_before: 0,
          bill_remaining_before: 300,
          apply_amount: 300,
          bill_paid_after: 300,
          bill_status_after: 'paid',
          remaining_after: 200,
        },
      ],
      total_applied: 300,
      balance_after: 200,
    },
    {
      student_id: 12,
      student_no: 2,
      student_name: 'บี',
      balance_before: 0,
      allocations: [],
      total_applied: 0,
      balance_after: 0,
    },
  ],
  total_applied: 300,
  total_balance_after: 200,
}

const RESULT: CreditRoundResponse = {
  reused: false,
  reference_no: 'รอบหักเครดิต',
  events: [
    {
      student_id: 11,
      student_name: 'อาร์ม',
      event_id: 901,
      total_applied: 300,
      credit_used: 300,
      balance_after: 200,
      credit_entry_ids: [501],
    },
  ],
  skipped: [],
  total_applied: 300,
  total_balance_after: 200,
}

const mountSheet = () =>
  mount(BulkCreditSheet, {
    props: { open: true, plan: PLAN },
    global: { stubs: { AppSheet: AppSheetStub } },
  })

const submitButton = (wrapper: ReturnType<typeof mountSheet>) =>
  wrapper.find('[data-test="credit-round-submit"]')

describe('BulkCreditSheet', () => {
  beforeEach(() => {
    authState.canManageFinance = true
    vi.mocked(FinanceService.createCreditRound).mockReset()
  })

  it('bulk_credit_sheet_keeps_key_on_retry', async () => {
    vi.mocked(FinanceService.createCreditRound)
      .mockRejectedValueOnce(new Error('network down'))
      .mockResolvedValueOnce(RESULT)

    const wrapper = mountSheet()

    await submitButton(wrapper).trigger('click')
    await flushPromises()
    expect(FinanceService.createCreditRound).toHaveBeenCalledTimes(1)

    // 🔴 ล้มแล้วห้ามสร้างคีย์ใหม่ — กดซ้ำต้องเป็น "รอบเดิม"
    await submitButton(wrapper).trigger('click')
    await flushPromises()
    expect(FinanceService.createCreditRound).toHaveBeenCalledTimes(2)

    const firstKey = vi.mocked(FinanceService.createCreditRound).mock.calls[0]?.[1]
      ?.idempotency_key
    const secondKey = vi.mocked(FinanceService.createCreditRound).mock.calls[1]?.[1]
      ?.idempotency_key
    expect(firstKey).toBeTruthy()
    expect(secondKey).toBe(firstKey)
  })

  it('bulk_credit_sheet_excludes_zero_allocation_students', async () => {
    vi.mocked(FinanceService.createCreditRound).mockResolvedValue(RESULT)

    const wrapper = mountSheet()
    await submitButton(wrapper).trigger('click')
    await flushPromises()

    const payload = vi.mocked(FinanceService.createCreditRound).mock.calls[0]?.[1]
    expect(payload?.student_ids).toEqual([11])
    expect(wrapper.find('[data-test="credit-round-skip"]').text()).toContain('บี')
  })

  it('bulk_credit_sheet_shows_409_without_closing', async () => {
    const conflict = Object.assign(new Error('Conflict'), {
      response: { status: 409, data: { detail: 'ชุดนักเรียนอื่น' } },
    })
    vi.mocked(FinanceService.createCreditRound).mockRejectedValue(conflict)

    const wrapper = mountSheet()
    await submitButton(wrapper).trigger('click')
    await flushPromises()

    // 🔴 409 ≠ "ปิดแล้วเงียบ" — ต้องเห็นสาเหตุและแผ่นต้องยังอยู่
    expect(wrapper.emitted('close')).toBeUndefined()
    const banner = wrapper.find('[data-test="credit-round-error"]')
    expect(banner.exists()).toBe(true)
    expect(banner.text()).toContain('ชุดนักเรียนอื่น')
    expect(wrapper.find('[data-test="sheet"]').exists()).toBe(true)
  })

  it('bulk_credit_sheet_hides_write_button_without_permission', async () => {
    authState.canManageFinance = false
    const wrapper = mountSheet()

    expect(submitButton(wrapper).exists()).toBe(false)
    expect(wrapper.text()).toContain('ไม่มีสิทธิ์หักเครดิต')
  })
})
