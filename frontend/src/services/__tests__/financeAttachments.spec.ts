import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { FinanceAttachmentList } from '@/types/finance'

const { getMock, postMock, deleteMock } = vi.hoisted(() => ({
  getMock: vi.fn<(url: string) => Promise<unknown>>(),
  postMock: vi.fn<(url: string, body?: FormData) => Promise<unknown>>(),
  deleteMock: vi.fn<(url: string) => Promise<unknown>>(),
}))

vi.mock('../api', () => ({
  default: { get: getMock, post: postMock, delete: deleteMock },
}))

import { FinanceService } from '@/services/finance'

const emptyList: FinanceAttachmentList = {
  items: [],
  limits: {
    max_per_owner: 20,
    max_per_request: 5,
    image_size_limit_mb: 10,
    document_size_limit_mb: 20,
    max_total_mb: 100,
    max_pdf_pages: 30,
  },
}

function fileOf(name: string, type: string): File {
  return new File([new Uint8Array([1, 2, 3])], name, { type })
}

describe('FinanceService finance attachments', () => {
  beforeEach(() => {
    getMock.mockReset()
    postMock.mockReset()
    deleteMock.mockReset()
  })

  it('list ใช้ path ของ owner ที่กำหนด', async () => {
    getMock.mockResolvedValue(emptyList)
    await FinanceService.getFinanceAttachments(7, 'student_payment', 42)
    expect(getMock).toHaveBeenCalledWith(
      '/api/classroom/7/finance/attachments/student_payment/42?target_type=room',
    )
  })

  it('upload ส่ง FormData โดยไม่ตั้ง Content-Type เอง (ให้ axios เติม boundary)', async () => {
    postMock.mockResolvedValue(emptyList)
    const png = fileOf('a.png', 'image/png')
    const pdf = fileOf('b.pdf', 'application/pdf')

    await FinanceService.uploadFinanceAttachments(7, 'transaction', 99, [png, pdf], 'expense_evidence')

    const [url, body] = postMock.mock.calls[0] as [string, FormData]
    expect(url).toBe('/api/classroom/7/finance/attachments/transaction/99?target_type=room')
    expect(body).toBeInstanceOf(FormData)
    const files = body.getAll('files') as File[]
    expect(files.map((f) => f.name)).toEqual(['a.png', 'b.pdf'])
    expect(body.get('kind')).toBe('expense_evidence')
  })

  it('delete ใช้ attachment id', async () => {
    deleteMock.mockResolvedValue({ status: 'success' })
    await FinanceService.deleteFinanceAttachment(7, 'abc-def')
    expect(deleteMock).toHaveBeenCalledWith(
      '/api/classroom/7/finance/attachments/abc-def?target_type=room',
    )
  })
})
