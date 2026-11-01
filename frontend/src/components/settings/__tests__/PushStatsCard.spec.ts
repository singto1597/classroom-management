import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

import PushStatsCard from '@/components/settings/PushStatsCard.vue'
import { NotificationService } from '@/services/notification'
import type { PushDeliveryStats } from '@/types/notification'

/**
 * 📊 `PushStatsCard` — สถิติการส่ง push (P6.5)
 *
 * สิ่งที่ล็อกไว้ (เพราะพลาดแล้ว "ไม่มีใครรู้" ไม่ใช่พังดัง ๆ):
 *   1. **`retry` ≠ `dropped`/`stale`** — ตัวเลข "จะลองใหม่" ต้องไม่กลืน "ยอมแพ้"
 *   2. **`last_round = null` ≠ ศูนย์** — ข้อความต้องเป็น "ไม่ได้รับรายงาน"
 *      ไม่ใช่ตารางที่เต็มไปด้วย 0 ซึ่งอ่านเหมือน "ส่งครบแล้ว"
 *   3. **สถานะตัวส่ง** ต้องแยก "งดส่งเพราะยังไม่ตั้งคีย์" ("disabled") ออกจาก
 *      "เงียบผิดปกติ" ("silent") และจาก "ทำงานอยู่"
 */

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({
    currentRoomId: 7,
    isAdmin: true,
    currentPermissions: [],
  }),
}))

vi.mock('@/services/notification', () => ({
  NotificationService: {
    getPushStats: vi.fn<(roomId: number) => Promise<PushDeliveryStats>>(),
  },
}))

const BASE: PushDeliveryStats = {
  room_id: 7,
  queue: {
    pending: 0,
    retry: 0,
    dropped: 0,
    stale: 0,
    sent_24h: 0,
    due_now: 0,
    oldest_due_seconds: 0,
  },
  last_round: null,
  worker_heartbeat_age_seconds: null,
  generated_at: '2026-11-01T03:00:00Z',
}

const mockStats = (patch: Partial<PushDeliveryStats> = {}) => {
  vi.mocked(NotificationService.getPushStats).mockResolvedValue({ ...BASE, ...patch })
}

const mountCard = async () => {
  const wrapper = mount(PushStatsCard)
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  vi.mocked(NotificationService.getPushStats).mockReset()
})

describe('PushStatsCard', () => {
  it('แยก "จะลองใหม่" ออกจาก "ยอมแพ้" — ไม่รวมเป็นตัวเลขเดียว', async () => {
    mockStats({
      queue: { ...BASE.queue, retry: 3, dropped: 2, stale: 1 },
    })
    const wrapper = await mountCard()

    const text = wrapper.text()
    expect(text).toContain('จะลองใหม่')
    expect(text).toContain('ยอมแพ้แล้ว')
    // 3 ที่ต้องลองใหม่ และ 3 ที่เลิกแล้ว (2 + 1) ต้องปรากฏแยกกัน
    expect(text).toMatch(/จะลองใหม่\s*3/)
    expect(text).toMatch(/ยอมแพ้แล้ว\s*3/)
    expect(text).toContain('ครบจำนวนครั้ง')
  })

  it('last_round = null แสดงว่า "ไม่ได้รับรายงาน" ไม่ใช่ตารางเลขศูนย์', async () => {
    mockStats()
    const wrapper = await mountCard()

    expect(wrapper.text()).toContain('ยังไม่ได้รับรายงานรอบล่าสุด')
    expect(wrapper.find('dl').exists()).toBe(false)
  })

  it('last_round ที่มีค่าแสดงผลของรอบ พร้อมกำกับว่าเป็น "ทั้งระบบ"', async () => {
    mockStats({
      last_round: {
        at: '2026-11-01T03:00:00Z',
        claimed: 5,
        sent: 2,
        retry: 1,
        gone: 0,
        dropped: 1,
        deferred: 3,
        stale: 0,
        enabled: true,
      },
      worker_heartbeat_age_seconds: 12,
    })
    const wrapper = await mountCard()

    expect(wrapper.text()).toContain('ใช้ร่วมทุกห้อง')
    expect(wrapper.text()).toContain('งดรบกวน')
    expect(wrapper.text()).toMatch(/งดรบกวน\s*3/)
    // ทิ้ง + หมดอายุ = 1
    expect(wrapper.text()).toMatch(/ทิ้ง\/หมดอายุ\s*1/)
  })

  it('ยังไม่ตั้ง VAPID ⇒ บอกว่า "ยังไม่ได้เปิดระบบส่ง" ไม่ใช่ "เงียบ"', async () => {
    mockStats({
      last_round: {
        at: '2026-11-01T03:00:00Z',
        claimed: 0,
        sent: 0,
        retry: 0,
        gone: 0,
        dropped: 0,
        deferred: 0,
        stale: 0,
        enabled: false,
      },
      worker_heartbeat_age_seconds: 5,
    })
    const wrapper = await mountCard()

    expect(wrapper.text()).toContain('ยังไม่ได้เปิดระบบส่งแจ้งเตือน')
    expect(wrapper.text()).not.toContain('เงียบไปแล้ว')
  })

  it('heartbeat เก่าเกิน 10 นาที ⇒ เตือนว่าเงียบ', async () => {
    mockStats({ worker_heartbeat_age_seconds: 3600 })
    const wrapper = await mountCard()

    expect(wrapper.text()).toContain('ตัวส่งแจ้งเตือนเงียบไปแล้ว')
    expect(wrapper.text()).toContain('1 ชั่วโมงที่แล้ว')
  })

  it('มีของถึงกำหนด ⇒ แสดงจำนวนและเวลารอนานสุด', async () => {
    mockStats({
      queue: { ...BASE.queue, pending: 2, due_now: 2, oldest_due_seconds: 900 },
      worker_heartbeat_age_seconds: 10,
    })
    const wrapper = await mountCard()

    expect(wrapper.text()).toContain('ถึงกำหนดแล้วแต่ยังไม่ได้ส่ง')
    expect(wrapper.text()).toContain('15 นาที')
  })

  it('โหลดไม่สำเร็จ ⇒ แสดง StateBlock พร้อมปุ่มลองใหม่', async () => {
    vi.mocked(NotificationService.getPushStats).mockRejectedValue(new Error('เครือข่ายมีปัญหา'))
    const wrapper = await mountCard()

    expect(wrapper.text()).toContain('โหลดสถิติการส่งไม่สำเร็จ')
    expect(wrapper.text()).toContain('เครือข่ายมีปัญหา')
  })
})
