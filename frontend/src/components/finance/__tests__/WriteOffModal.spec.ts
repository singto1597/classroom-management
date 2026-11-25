import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'

import WriteOffModal from '@/components/finance/WriteOffModal.vue'
import { FinanceService } from '@/services/finance'
import type {
  BillAdjustmentItem,
  BillAdjustmentRequest,
  BillAdjustmentResponse,
} from '@/types/finance'

/**
 * ✂️ `WriteOffModal` — ตัดหนี้ / ให้ส่วนลด (FIN-V2 / P6.3)
 *
 * สิ่งที่ล็อกไว้ (ทุกข้อเป็นเรื่อง "ตัดเงินผิดยอด / เกิดแถวซ้ำ"):
 *   1. ค่าเริ่มต้น = ยอดคงเหลือทั้งก้อน และปุ่มยืนยันปิดเมื่อเหตุผลว่าง
 *   2. จำนวนเกินยอดคงเหลือ / 0 / ติดลบ / ตัวอักษร → ปิดปุ่ม + ข้อความอธิบาย
 *   3. `idempotency_key` สร้าง **ตอนเปิด** และคงเดิมตอน retry หลัง error
 *   4. สำเร็จ → `saved(result)` + `close` ครั้งเดียว และส่ง amount เป็น string 2 ตำแหน่ง
 */
const { newKeySpy, generatedKeys } = vi.hoisted(() => {
  const generatedKeys: string[] = []
  const newKeySpy = vi.fn(() => {
    const key = `key-${generatedKeys.length + 1}`
    generatedKeys.push(key)
    return key
  })
  return { newKeySpy, generatedKeys }
})

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ currentRoomId: 7 }),
}))

vi.mock('@/utils/money', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/utils/money')>()
  return { ...actual, newIdempotencyKey: newKeySpy }
})

vi.mock('@/services/finance', () => ({
  FinanceService: {
    writeOffBill: vi.fn<
      (
        roomId: number,
        paymentId: number,
        payload: BillAdjustmentRequest,
      ) => Promise<BillAdjustmentResponse>
    >(),
    discountBill: vi.fn<
      (
        roomId: number,
        paymentId: number,
        payload: BillAdjustmentRequest,
      ) => Promise<BillAdjustmentResponse>
    >(),
  },
}))

/** แทน AppSheet (Teleport) — เทสต์นี้สนใจเนื้อหา/พฤติกรรม ไม่ใช่การจัดชั้นของแผ่น */
const AppSheetStub = defineComponent({
  name: 'AppSheet',
  props: { open: { type: Boolean, default: false } },
  emits: ['close'],
  template: '<div v-if="open" data-test="sheet"><slot /><slot name="footer" /></div>',
})

const ADJUSTMENT: BillAdjustmentItem = {
  id: 5,
  adjustment_type: 'write_off',
  amount: '800.00',
  status: 'active',
  written_off_total: '800.00',
  remaining: '0.00',
  bill_status: 'waived',
  journal_entry_id: '77',
  created_at: '2026-11-25T10:00:00+07:00',
  reason: 'นักเรียนย้ายโรงเรียน',
}

const RESULT: BillAdjustmentResponse = {
  status: 'success',
  message: null,
  reused: false,
  adjustment: ADJUSTMENT,
  voided_invoices: 1,
}

const mountModal = (outstanding = 800) =>
  mount(WriteOffModal, {
    props: {
      open: true,
      paymentId: 21,
      billLabel: 'ค่าโครงการ ทัศนศึกษา · นาย ก.',
      outstanding,
    },
    global: { stubs: { AppSheet: AppSheetStub } },
  })

type Wrapper = ReturnType<typeof mountModal>

const buttonByText = (wrapper: Wrapper, text: string) => {
  const btn = wrapper.findAll('button').find((b) => b.text().includes(text))
  if (!btn) throw new Error(`ไม่พบปุ่ม "${text}"`)
  return btn
}

const confirmButton = (wrapper: Wrapper) => buttonByText(wrapper, 'ยืนยันตัดหนี้')

const confirmDisabled = (wrapper: Wrapper): boolean =>
  (confirmButton(wrapper).element as HTMLButtonElement).disabled

const amountInput = (wrapper: Wrapper) => wrapper.find('#writeOffAmount')

beforeEach(() => {
  generatedKeys.length = 0
  newKeySpy.mockClear()
  vi.mocked(FinanceService.writeOffBill).mockReset()
  vi.mocked(FinanceService.discountBill).mockReset()
})

describe('WriteOffModal', () => {
  it('ค่าเริ่มต้น = ยอดคงเหลือทั้งก้อน และปุ่มยืนยันปิดเมื่อเหตุผลว่าง', () => {
    const wrapper = mountModal()

    expect((amountInput(wrapper).element as HTMLInputElement).value).toBe('800.00')
    expect(confirmDisabled(wrapper)).toBe(true)
  })

  it('กรอกเหตุผลแล้วยืนยันได้ และส่ง amount เป็น string 2 ตำแหน่งพร้อมคีย์ที่สร้างตอนเปิด', async () => {
    vi.mocked(FinanceService.writeOffBill).mockResolvedValue(RESULT)
    const wrapper = mountModal()

    await amountInput(wrapper).setValue('500')
    await wrapper.find('#writeOffReason').setValue('นักเรียนย้ายโรงเรียน')
    expect(confirmDisabled(wrapper)).toBe(false)

    await confirmButton(wrapper).trigger('click')
    await flushPromises()

    expect(FinanceService.writeOffBill).toHaveBeenCalledTimes(1)
    expect(FinanceService.writeOffBill).toHaveBeenCalledWith(7, 21, {
      amount: 500,
      reason: 'นักเรียนย้ายโรงเรียน',
      idempotency_key: 'key-1',
    })
  })

  it('จำนวนเกินยอดคงเหลือ → ปิดปุ่ม + ข้อความเตือน', async () => {
    const wrapper = mountModal(800)
    await wrapper.find('#writeOffReason').setValue('ทดสอบ')

    await amountInput(wrapper).setValue('800.01')

    expect(wrapper.text()).toContain('จำนวนเงินมากกว่ายอดคงเหลือ')
    expect(confirmDisabled(wrapper)).toBe(true)
  })

  it.each(['0', '-50', 'abc'])('จำนวน "%s" → ปิดปุ่มยืนยัน', async (raw) => {
    const wrapper = mountModal()
    await wrapper.find('#writeOffReason').setValue('ทดสอบ')

    await amountInput(wrapper).setValue(raw)

    expect(confirmDisabled(wrapper)).toBe(true)
  })

  it('เลือก "ให้ส่วนลด" → เรียก discountBill ไม่ใช่ writeOffBill', async () => {
    vi.mocked(FinanceService.discountBill).mockResolvedValue({
      ...RESULT,
      adjustment: {
        ...ADJUSTMENT,
        adjustment_type: 'discount',
        amount: '500.00',
        written_off_total: '500.00',
        remaining: '300.00',
        bill_status: 'pending',
      },
      voided_invoices: 0,
    })
    const wrapper = mountModal()

    await buttonByText(wrapper, 'ให้ส่วนลด').trigger('click')
    await amountInput(wrapper).setValue('500')
    await wrapper.find('#writeOffReason').setValue('มติห้องให้ส่วนลด')
    await buttonByText(wrapper, 'ยืนยันให้ส่วนลด').trigger('click')
    await flushPromises()

    expect(FinanceService.writeOffBill).not.toHaveBeenCalled()
    expect(FinanceService.discountBill).toHaveBeenCalledTimes(1)
  })

  it('retry หลัง error ใช้คีย์เดิม แต่เปิด modal ใหม่ได้คีย์ใหม่', async () => {
    vi.mocked(FinanceService.writeOffBill)
      .mockRejectedValueOnce(new Error('ยกเลิกรายการนี้ไปแล้ว'))
      .mockResolvedValueOnce(RESULT)
    const wrapper = mountModal()

    await wrapper.find('#writeOffReason').setValue('นักเรียนย้ายโรงเรียน')
    await confirmButton(wrapper).trigger('click')
    await flushPromises()

    // error จาก backend แสดงในกล่องแดง และ modal ไม่ปิด
    expect(wrapper.text()).toContain('ยกเลิกรายการนี้ไปแล้ว')
    expect(wrapper.emitted('close')).toBeUndefined()

    await confirmButton(wrapper).trigger('click')
    await flushPromises()

    const calls = vi.mocked(FinanceService.writeOffBill).mock.calls
    expect(calls).toHaveLength(2)
    expect(calls[0]![2].idempotency_key).toBe('key-1')
    expect(calls[1]![2].idempotency_key).toBe('key-1')

    // ปิดแล้วเปิดใหม่ → คีย์ใหม่ (ไม่ใช้ของรอบก่อน)
    await wrapper.setProps({ open: false })
    await wrapper.setProps({ open: true })
    await wrapper.find('#writeOffReason').setValue('รอบใหม่')
    await confirmButton(wrapper).trigger('click')
    await flushPromises()

    expect(newKeySpy).toHaveBeenCalledTimes(2)
    const lastCall = vi.mocked(FinanceService.writeOffBill).mock.calls
    expect(lastCall[lastCall.length - 1]![2].idempotency_key).toBe('key-2')
  })

  it('สำเร็จ → emit saved(result) + close ครั้งเดียว และดับเบิลคลิกไม่สร้างรายการที่สอง', async () => {
    let resolve!: (value: BillAdjustmentResponse) => void
    vi.mocked(FinanceService.writeOffBill).mockImplementation(
      () => new Promise<BillAdjustmentResponse>((r) => (resolve = r)),
    )
    const wrapper = mountModal()

    await wrapper.find('#writeOffReason').setValue('นักเรียนย้ายโรงเรียน')
    await confirmButton(wrapper).trigger('click')
    // ระหว่างรอ — กดซ้ำต้องไม่ยิง API ซ้ำ
    await wrapper.find('form').trigger('submit')
    await confirmButton(wrapper).trigger('click')
    expect(FinanceService.writeOffBill).toHaveBeenCalledTimes(1)

    resolve(RESULT)
    await flushPromises()

    expect(wrapper.emitted('saved')).toHaveLength(1)
    expect(wrapper.emitted('saved')![0]).toEqual([RESULT])
    expect(wrapper.emitted('close')).toHaveLength(1)
  })
})
