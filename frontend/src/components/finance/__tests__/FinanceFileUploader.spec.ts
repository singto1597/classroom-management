import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

import FinanceFileUploader from '@/components/finance/FinanceFileUploader.vue'
import type { FinanceAttachmentList } from '@/types/finance'

const { uploadMock, alertMock } = vi.hoisted(() => ({
  uploadMock: vi.fn<
    (roomId: number, ownerType: string, ownerId: number, files: File[], kind?: string) => Promise<unknown>
  >(),
  alertMock: vi.fn<(title: string, text?: string, icon?: string) => Promise<unknown>>(),
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ currentRoomId: 7 }),
}))

vi.mock('@/services/finance', () => ({
  FinanceService: { uploadFinanceAttachments: uploadMock },
}))

vi.mock('@/composables/useDialog', () => ({
  useDialog: () => ({ alert: alertMock }),
}))

const listResult: FinanceAttachmentList = {
  items: [
    {
      id: '11111111-1111-1111-1111-111111111111',
      owner_type: 'transaction',
      owner_id: 5,
      file_kind: 'image',
      kind: 'expense_evidence',
      original_name: 'a.png',
      url: '/api/finance-files/11111111-1111-1111-1111-111111111111',
      thumb_url: '/api/finance-files/x?variant=thumb',
      mime: 'image/webp',
      width: 800,
      height: 600,
      page_count: null,
      bytes: 1000,
      uploaded_by: 1,
      created_at: '2026-11-26T00:00:00Z',
    },
  ],
  limits: {
    max_per_owner: 20,
    max_per_request: 5,
    image_size_limit_mb: 10,
    document_size_limit_mb: 20,
    max_total_mb: 100,
    max_pdf_pages: 30,
  },
}

function fileOf(name: string, type: string, bytes = 8): File {
  return new File([new Uint8Array(bytes)], name, { type })
}

async function pick(wrapper: ReturnType<typeof mount>, files: File[]): Promise<void> {
  const input = wrapper.find('[data-testid="finance-file-input"]')
  Object.defineProperty(input.element, 'files', { value: files, configurable: true })
  await input.trigger('change')
}

describe('FinanceFileUploader', () => {
  beforeEach(() => {
    uploadMock.mockReset()
    alertMock.mockReset()
  })

  it('buffer mode: เลือกรูป + PDF แล้ว emit update:files', async () => {
    const wrapper = mount(FinanceFileUploader, {
      props: { ownerType: 'transaction', maxCount: 20 },
    })
    await pick(wrapper, [fileOf('a.png', 'image/png'), fileOf('b.pdf', 'application/pdf')])

    const emitted = wrapper.emitted('update:files')
    expect(emitted).toBeTruthy()
    const files = emitted![emitted!.length - 1]![0] as File[]
    expect(files.map((f) => f.name)).toEqual(['a.png', 'b.pdf'])
  })

  it('ปฏิเสธชนิดไฟล์ที่ไม่ใช่รูป/PDF และไฟล์ที่เกินจำนวน', async () => {
    const wrapper = mount(FinanceFileUploader, {
      props: { ownerType: 'transaction', maxCount: 1 },
    })
    await pick(wrapper, [
      fileOf('a.docx', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'),
      fileOf('b.png', 'image/png'),
      fileOf('c.png', 'image/png'),
    ])

    expect(alertMock).toHaveBeenCalledTimes(1)
    const emitted = wrapper.emitted('update:files')
    const files = emitted![emitted!.length - 1]![0] as File[]
    expect(files.map((f) => f.name)).toEqual(['b.png'])
  })

  it('immediate mode: กดแล้วอัปโหลดผ่าน service', async () => {
    uploadMock.mockResolvedValue(listResult)
    const wrapper = mount(FinanceFileUploader, {
      props: {
        ownerType: 'transaction',
        ownerId: 5,
        maxCount: 20,
        kind: 'expense_evidence',
      },
    })
    await pick(wrapper, [fileOf('a.png', 'image/png')])

    const button = wrapper.findAll('button').find((b) => b.text().includes('แนบ 1 ไฟล์'))
    expect(button).toBeTruthy()
    await button!.trigger('click')
    await flushPromises()

    expect(uploadMock).toHaveBeenCalledTimes(1)
    const [roomId, ownerType, ownerId, files, kind] = uploadMock.mock.calls[0] as [
      number,
      string,
      number,
      File[],
      string,
    ]
    expect(roomId).toBe(7)
    expect(ownerType).toBe('transaction')
    expect(ownerId).toBe(5)
    expect(files.map((f) => f.name)).toEqual(['a.png'])
    expect(kind).toBe('expense_evidence')
    expect(wrapper.emitted('uploaded')).toBeTruthy()
  })
})
