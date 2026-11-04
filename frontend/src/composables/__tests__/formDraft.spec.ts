import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent, h, nextTick, reactive } from 'vue'

import { confirmLeave, useFormDraft, useUnsavedGuard } from '@/composables/useFormDraft'

/**
 * 📝 `useFormDraft` / `useUnsavedGuard` / `confirmLeave` — กลไกกันข้อมูลฟอร์มหาย
 *
 * เทสต์นี้ล็อกสิ่งที่พังแล้วจะเจ็บแบบเงียบ ๆ:
 *  1. ร่างถูกเขียนช้ากว่าที่คิด (debounce) — ถ้าลืม `advanceTimers` เนื้อหาจะยังไม่อยู่ใน storage
 *  2. ร่างของห้อง/แท็บหนึ่งไปโผล่ในอีกที่หนึ่ง — key ต้องถูกคำนวณสดทุกครั้ง ไม่ใช่ครั้งเดียวตอน setup
 *  3. `enabled()` false ต้องไม่เขียนเลย (โหมดแก้ไขต้องไม่ทับร่างโหมดสร้าง)
 *  4. storage ถูกปิด/มี JSON พัง ต้องไม่ทำให้ฟอร์มล่ม — คืน false เฉย ๆ
 *
 * ⚠️ `onBeforeUnmount` ใน composable ต้องถูกเรียกภายใต้ component instance จริง
 *    ⇒ ใช้ `mount()` แทนเรียกฟังก์ชันลอย ๆ (ไม่งั้นได้ warning และ listener ไม่ถูกถอด)
 */

// dialog store ถูก mock เพราะเทสต์นี้สนใจ "ตัดสินใจถามไหม + คืนค่าอะไร" ไม่ใช่หน้าตาแผ่น
const { dialogConfirm } = vi.hoisted(() => ({
  dialogConfirm: vi.fn<(title: string) => Promise<{ isConfirmed: boolean; isDismissed: boolean; value: string }>>(
    (_title) => Promise.resolve({ isConfirmed: true, isDismissed: false, value: '' }),
  ),
}))
vi.mock('@/stores/dialog', () => ({
  useDialogStore: () => ({ confirm: dialogConfirm }),
}))

const mountDraft = <T extends object>(
  state: T,
  key: () => string,
  enabled?: () => boolean,
): ReturnType<typeof useFormDraft> => {
  let api: ReturnType<typeof useFormDraft> | null = null
  mount(
    defineComponent({
      setup() {
        api = useFormDraft(state, key, enabled)
        return () => h('div')
      },
    }),
  )
  if (!api) throw new Error('useFormDraft ไม่ได้ถูกเรียกตอน setup')
  return api as ReturnType<typeof useFormDraft>
}

beforeEach(() => {
  sessionStorage.clear()
  dialogConfirm.mockClear()
})

afterEach(() => {
  vi.useRealTimers()
  sessionStorage.clear()
})

describe('useFormDraft', () => {
  it('เขียนร่างลง sessionStorage หลัง debounce (400ms) ไม่ใช่ทันที', async () => {
    vi.useFakeTimers()
    const state = reactive({ title: '' })
    mountDraft(state, () => 'k')

    state.title = 'การบ้านหน้า 45'
    await nextTick()

    // ยังไม่ถึงเวลา ⇒ ยังไม่มีอะไรถูกเขียน
    expect(sessionStorage.getItem('k')).toBeNull()

    vi.advanceTimersByTime(400)
    expect(JSON.parse(sessionStorage.getItem('k') ?? '{}')).toEqual({ title: 'การบ้านหน้า 45' })
  })

  it('พิมพ์รัว ๆ แล้วเก็บเฉพาะค่าล่าสุด (debounce ทับกัน)', async () => {
    vi.useFakeTimers()
    const state = reactive({ title: '' })
    mountDraft(state, () => 'k')

    state.title = 'a'
    await nextTick()
    vi.advanceTimersByTime(200)
    state.title = 'ab'
    await nextTick()
    vi.advanceTimersByTime(200)
    state.title = 'abc'
    await nextTick()
    vi.advanceTimersByTime(400)

    expect(JSON.parse(sessionStorage.getItem('k') ?? '{}')).toEqual({ title: 'abc' })
  })

  it('key ถูกคำนวณสดทุกครั้ง — เปลี่ยนห้องแล้วร่างไม่ปนกัน', async () => {
    vi.useFakeTimers()
    const roomId = { value: 1 }
    const first = reactive({ note: '' })
    mountDraft(first, () => `draft:${roomId.value}`)

    first.note = 'ห้องหนึ่ง'
    await nextTick()
    vi.advanceTimersByTime(400)

    roomId.value = 2
    first.note = 'ห้องสอง'
    await nextTick()
    vi.advanceTimersByTime(400)

    expect(JSON.parse(sessionStorage.getItem('draft:1') ?? '{}')).toEqual({ note: 'ห้องหนึ่ง' })
    expect(JSON.parse(sessionStorage.getItem('draft:2') ?? '{}')).toEqual({ note: 'ห้องสอง' })
  })

  it('restore() เติมค่าลง state และคืน true', () => {
    sessionStorage.setItem('k', JSON.stringify({ title: 'ร่างเดิม', detail: 'x' }))
    const state = reactive({ title: '', detail: '' })
    const draft = mountDraft(state, () => 'k')

    expect(draft.restore()).toBe(true)
    expect(state.title).toBe('ร่างเดิม')
    expect(state.detail).toBe('x')
    expect(draft.restored.value).toBe(true)
    expect(draft.hasDraft.value).toBe(true)
  })

  it('restore() คืน false เมื่อไม่มีร่าง / JSON พัง / ไม่ใช่ object', () => {
    const state = reactive({ title: 'คงเดิม' })
    const draft = mountDraft(state, () => 'k')

    expect(draft.restore()).toBe(false)

    sessionStorage.setItem('k', '{not json')
    expect(draft.restore()).toBe(false)
    expect(state.title).toBe('คงเดิม')

    sessionStorage.setItem('k', '"ข้อความ"')
    expect(draft.restore()).toBe(false)
    expect(draft.restored.value).toBe(false)
  })

  it('enabled() false ⇒ ไม่เขียนร่างเลย (โหมดแก้ไขไม่ทับร่างโหมดสร้าง)', async () => {
    vi.useFakeTimers()
    const state = reactive({ title: '' })
    mountDraft(state, () => 'k', () => false)

    state.title = 'แก้ไขกิจกรรม'
    await nextTick()
    vi.advanceTimersByTime(1000)

    expect(sessionStorage.getItem('k')).toBeNull()
  })

  it('clear() ลบร่างและรีเซ็ตธง', async () => {
    vi.useFakeTimers()
    const state = reactive({ title: '' })
    const draft = mountDraft(state, () => 'k')

    sessionStorage.setItem('k', JSON.stringify({ title: 'เก่า' }))
    draft.restore()

    draft.clear()
    expect(sessionStorage.getItem('k')).toBeNull()
    expect(draft.hasDraft.value).toBe(false)
    expect(draft.restored.value).toBe(false)
  })
})

describe('useUnsavedGuard', () => {
  const mountGuard = (isDirty: () => boolean) => {
    mount(
      defineComponent({
        setup() {
          useUnsavedGuard(isDirty)
          return () => h('div')
        },
      }),
    )
  }

  const dispatchBeforeUnload = (): Event => {
    const event = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(event)
    return event
  }

  it('ฟอร์มสะอาด ⇒ ไม่บล็อกการปิดแท็บ', () => {
    mountGuard(() => false)
    const event = dispatchBeforeUnload()
    expect(event.defaultPrevented).toBe(false)
  })

  it('ฟอร์มยังไม่บันทึก ⇒ preventDefault', () => {
    mountGuard(() => true)
    const event = dispatchBeforeUnload()
    expect(event.defaultPrevented).toBe(true)
  })
})

describe('confirmLeave', () => {
  it('ไม่ถามเมื่อฟอร์มสะอาด', async () => {
    await expect(confirmLeave(() => false)).resolves.toBe(true)
    expect(dialogConfirm).not.toHaveBeenCalled()
  })

  it('ถามด้วย dialog เมื่อฟอร์มยังไม่บันทึก และคืนผลตามที่ผู้ใช้เลือก', async () => {
    await expect(confirmLeave(() => true)).resolves.toBe(true)
    expect(dialogConfirm).toHaveBeenCalledTimes(1)
    expect(dialogConfirm.mock.calls[0]?.[0]).toBe('ยังไม่ได้บันทึก')

    dialogConfirm.mockResolvedValueOnce({ isConfirmed: false, isDismissed: false, value: '' })
    await expect(confirmLeave(() => true)).resolves.toBe(false)
  })
})
