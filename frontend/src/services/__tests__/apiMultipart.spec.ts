import { afterEach, describe, expect, it } from 'vitest'

import { api } from '@/services/api'
import { FinanceService } from '@/services/finance'

/**
 * 🚨 regression: axios 1.x แปลง FormData → JSON เมื่อ Content-Type เป็น application/json
 * (`transformRequest`: `if (isFormData) return hasJSONContentType ? JSON.stringify(...) : data`)
 * ⇒ backend ได้ body ที่ไม่มี `files` และตอบ 422 "Field required"
 */
const originalAdapter = api.defaults.adapter

afterEach(() => {
  api.defaults.adapter = originalAdapter
})

describe('api — multipart upload', () => {
  it('ส่ง FormData โดยไม่ถูกบังคับ Content-Type: application/json', async () => {
    let contentType: unknown = 'NOT_CAPTURED'

    api.defaults.adapter = async (config) => {
      contentType = config.headers?.get?.('Content-Type')
      return {
        data: { items: [], limits: {} },
        status: 200,
        statusText: 'OK',
        headers: {},
        config,
      }
    }

    const file = new File([new Uint8Array([1, 2, 3])], 'a.png', { type: 'image/png' })
    await FinanceService.uploadFinanceAttachments(1, 'transaction', 2, [file])

    expect(String(contentType ?? '')).not.toContain('application/json')
  })
})
