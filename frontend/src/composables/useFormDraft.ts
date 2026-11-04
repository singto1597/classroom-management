import { onBeforeUnmount, ref, watch } from 'vue'
import { useDialogStore } from '@/stores/dialog'

/**
 * 📝 ร่างฟอร์มใน `sessionStorage` — กันข้อมูลหายเมื่อผู้ใช้เผลอปิดแท็บ/กดย้อน/เน็ตหลุด
 *
 * ทำไม sessionStorage ไม่ใช่ localStorage:
 *   ร่างคือข้อมูลที่ยังไม่ยืนยัน — ถ้าอยู่ข้ามวัน ผู้ใช้จะเปิดฟอร์มมาเจอข้อมูลเก่า
 *   โดยไม่รู้ที่มา (และบนเครื่องที่ใช้ร่วมกันจะรั่วข้อมูล) ⇒ ผูกกับแท็บนี้เท่านั้น
 *
 * ทำไมต้องมี `enabled`:
 *   โหมดแก้ไข (edit) ต้องไม่เขียนทับร่างสร้างใหม่ และไม่ควรกู้ร่างข้าม id
 *   ⇒ ส่ง `() => props.mode === 'create'` เข้ามา
 *
 * @example
 * const form = reactive({ title: '' })
 * const draft = useFormDraft(form, () => `cls:draft:task:${currentRoomId}`, () => canManage.value)
 * // เมื่อบันทึกสำเร็จ
 * draft.clear()
 */
export function useFormDraft<T extends object>(
  state: T,
  key: () => string,
  enabled: () => boolean = () => true,
  delay = 400,
) {
  const restored = ref(false)
  const hasDraft = ref(false)
  let timer: ReturnType<typeof setTimeout> | null = null

  const storageKey = () => key()

  /** คืน `true` ถ้ากู้ร่างสำเร็จ — เรียกตอน setup ก่อนผู้ใช้พิมพ์ */
  const restore = (): boolean => {
    if (!enabled()) return false
    try {
      const raw = sessionStorage.getItem(storageKey())
      if (!raw) return false
      const parsed = JSON.parse(raw) as unknown
      if (!parsed || typeof parsed !== 'object') return false
      Object.assign(state, parsed)
      restored.value = true
      hasDraft.value = true
      return true
    } catch {
      return false
    }
  }

  const clear = () => {
    try {
      sessionStorage.removeItem(storageKey())
    } catch {
      // sessionStorage ถูกปิด (private mode บางเบราว์เซอร์) — ฟอร์มยังใช้งานได้ปกติ
    }
    hasDraft.value = false
    restored.value = false
  }

  watch(
    state,
    () => {
      if (!enabled()) return
      hasDraft.value = true
      if (timer) clearTimeout(timer)
      timer = setTimeout(() => {
        try {
          sessionStorage.setItem(storageKey(), JSON.stringify(state))
        } catch {
          // เก็บไม่ได้ (quota/ปิด storage) — ไม่ใช่เหตุให้ฟอร์มพัง
        }
      }, delay)
    },
    { deep: true },
  )

  onBeforeUnmount(() => {
    if (timer) clearTimeout(timer)
  })

  return { restore, clear, hasDraft, restored }
}

/**
 * 🚪 เตือนก่อนปิดแท็บ/รีโหลด เมื่อฟอร์มยังไม่ถูกบันทึก
 *
 * การเปลี่ยน route ใช้ `confirmLeave()` คู่กับ `onBeforeRouteLeave` ของหน้า
 * (กล่องสนทนากลางเท่านั้น ส่วนข้อความของ `beforeunload` แก้ไม่ได้ตามสเปก)
 *
 * `isDirty()` ต้องคืน false หลังบันทึกสำเร็จ ไม่งั้นผู้ใช้เจอคำถามซ้ำทั้งที่ส่งไปแล้ว
 */
export function useUnsavedGuard(isDirty: () => boolean) {
  const onBeforeUnload = (event: BeforeUnloadEvent) => {
    if (!isDirty()) return
    event.preventDefault()
    event.returnValue = ''
  }

  window.addEventListener('beforeunload', onBeforeUnload)

  onBeforeUnmount(() => {
    window.removeEventListener('beforeunload', onBeforeUnload)
  })
}

/** ใช้ใน `onBeforeRouteLeave` ของหน้า — แยกฟังก์ชันเพื่อให้อ่าน/ทดสอบง่าย */
export async function confirmLeave(isDirty: () => boolean): Promise<boolean> {
  if (!isDirty()) return true
  const result = await useDialogStore().confirm(
    'ยังไม่ได้บันทึก',
    'ข้อมูลที่กรอกไว้จะหายไปถ้าออกจากหน้านี้',
    {
      icon: 'warning',
      danger: true,
      confirmButtonText: 'ออกโดยไม่บันทึก',
      cancelButtonText: 'อยู่ต่อ',
    },
  )
  return result.isConfirmed
}
