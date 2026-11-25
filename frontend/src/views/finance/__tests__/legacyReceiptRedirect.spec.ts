import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

import LegacyReceiptRedirect from '@/views/finance/LegacyReceiptRedirect.vue'
import { FinanceService } from '@/services/finance'

/**
 * 🔁 [FIN-V2 / P6.5] ตัวแปลงเลขเอกสารเก่า → หน้า detail ของทะเบียน
 *
 * สิ่งที่ล็อกไว้:
 *   1. สำเร็จ → `router.replace` (ไม่ใช่ push) ไป `finance-document-detail` ด้วย
 *      `(doc_type, doc_id)` ที่ **backend บอก** — ไม่เดาจาก prefix ของเลข
 *   2. 404 → empty state "ไม่พบเอกสารเลขที่นี้" + ทางออกไปทะเบียน และไม่ navigate
 *   3. error อื่น → StateBlock error + ปุ่มลองใหม่ยิงซ้ำได้
 */
const { replaceMock, routeMock } = vi.hoisted(() => ({
  replaceMock: vi.fn<() => Promise<void>>(),
  // route เก่าใช้ `:receiptNo` — component ต้องอ่านคีย์นี้ได้ด้วย (route ใหม่ใช้ `:docNo`)
  routeMock: { params: { receiptNo: 'REC-2569-0042' } as Record<string, unknown> },
}))

vi.mock('vue-router', () => ({
  RouterLink: {
    name: 'RouterLink',
    props: { to: { type: [String, Object], required: true } },
    template: `<a :href="typeof to === 'string' ? to : ''"><slot /></a>`,
  },
  useRoute: () => routeMock,
  useRouter: () => ({ replace: replaceMock }),
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ currentRoomId: 7 }),
}))

vi.mock('@/services/finance', () => ({
  FinanceService: {
    resolveDocumentByNo:
      vi.fn<(roomId: number, docNo: string) => Promise<{ doc_type: string; doc_id: number }>>(),
  },
}))

// apiStatus จริงใช้ `isAxiosError` — ในเทสต์ใช้ error ปลอมที่มีฟิลด์ status ตรง ๆ
vi.mock('@/services/api', () => ({
  apiStatus: (error: unknown) => {
    if (error && typeof error === 'object' && 'status' in error) {
      return (error as { status: number }).status
    }
    return undefined
  },
}))

const asDoc = (docType: string, docId: number) => ({ doc_type: docType, doc_id: docId })

const mountPage = async () => {
  const wrapper = mount(LegacyReceiptRedirect)
  await flushPromises()
  return wrapper
}

describe('LegacyReceiptRedirect (P6.5)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    routeMock.params = { receiptNo: 'REC-2569-0042' }
  })

  it('สำเร็จ → replace ไป finance-document-detail ด้วย (doc_type, doc_id) จาก backend', async () => {
    vi.mocked(FinanceService.resolveDocumentByNo).mockResolvedValue(
      asDoc('receipt', 901) as never,
    )

    await mountPage()

    expect(FinanceService.resolveDocumentByNo).toHaveBeenCalledWith(7, 'REC-2569-0042')
    expect(replaceMock).toHaveBeenCalledTimes(1)
    expect(replaceMock).toHaveBeenCalledWith({
      name: 'finance-document-detail',
      params: { docType: 'receipt', docId: '901' },
    })
  })

  it('404 → empty state พร้อมทางออกไปทะเบียน และไม่ navigate', async () => {
    vi.mocked(FinanceService.resolveDocumentByNo).mockRejectedValue(
      Object.assign(new Error('ไม่พบเอกสาร'), { status: 404 }),
    )

    const wrapper = await mountPage()
    const text = wrapper.text()

    expect(text).toContain('ไม่พบเอกสารเลขที่นี้')
    expect(text).toContain('REC-2569-0042')
    expect(replaceMock).not.toHaveBeenCalled()

    const hrefs = wrapper.findAll('a').map((a) => a.attributes('href'))
    expect(hrefs).toContain('/finance/documents')
  })

  it('error อื่น → StateBlock error และปุ่มลองใหม่ยิงซ้ำได้', async () => {
    const resolve = vi.mocked(FinanceService.resolveDocumentByNo)
    resolve.mockRejectedValueOnce(new Error('network down'))
    resolve.mockResolvedValueOnce(asDoc('deposit', 12) as never)

    const wrapper = await mountPage()
    expect(wrapper.text()).toContain('โหลดข้อมูลไม่สำเร็จ')
    expect(replaceMock).not.toHaveBeenCalled()

    const retry = wrapper.findAll('button').find((b) => b.text().includes('ลองอีกครั้ง'))
    expect(retry).toBeDefined()
    await retry!.trigger('click')
    await flushPromises()

    expect(resolve).toHaveBeenCalledTimes(2)
    expect(replaceMock).toHaveBeenCalledWith({
      name: 'finance-document-detail',
      params: { docType: 'deposit', docId: '12' },
    })
  })
})
