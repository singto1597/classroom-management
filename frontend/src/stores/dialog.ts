import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

/**
 * 🪟 ตัวเรียกกล่องสนทนากลาง — แทน `Swal.fire` ทั้งระบบ
 *
 * เรียกจากที่ไหนก็ได้ (`fire`, `alert`, `confirm`, `input`, `notify`) แล้วได้ Promise
 * ที่มีสัญญาการคืนค่าเหมือนเดิม: `{ isConfirmed, isDismissed, value }`
 * ตัวเรนเดอร์จริงคือ `AppDialogHost.vue` ที่ mount ครั้งเดียวใน `App.vue`
 *
 * ⚠️ ตั้งใจ **ไม่รองรับ `html`** — เนื้อหากล่องต้องเป็น Vue template ที่ type-check ได้
 *    (ไม่ใช้ `v-html` กับข้อความจากผู้ใช้)
 */

export type DialogIcon = 'success' | 'error' | 'warning' | 'info' | 'question'

export interface DialogOptions {
  title?: string
  /** ข้อความอธิบาย — หลายบรรทัดได้ แสดงเป็น paragraph */
  text?: string
  icon?: DialogIcon
  confirmButtonText?: string
  cancelButtonText?: string
  showCancelButton?: boolean
  /** ปุ่มยืนยันเป็นสีแดง (ใช้กับสิ่งที่ย้อนกลับไม่ได้) */
  danger?: boolean
  /** ช่องกรอกในกล่อง (แทน `Swal.fire({ input })`) */
  input?: 'text' | 'number' | 'textarea'
  inputValue?: string
  inputLabel?: string
  inputPlaceholder?: string
  /**
   * ตรวจ/แปลงค่าก่อนยืนยัน — คืน string เพื่อแทนค่า หรือ `void` เพื่อใช้ค่าเดิม
   * โยน Error เพื่อแสดงข้อความผิดพลาดแล้วค้างกล่องไว้
   */
  preConfirm?: (value: string) => string | void | Promise<string | void>
  /** ปิดเองหลังผ่านไปกี่มิลลิวินาที (นับเป็น "ยืนยันแล้ว") */
  timer?: number
  position?: 'responsive' | 'center' | 'bottom'
  /** แสดงสถานะกำลังทำงาน — ซ่อนปุ่มทั้งหมดและปิดด้วย Esc/ฉากหลังไม่ได้ */
  loading?: boolean
}

export interface DialogResult {
  isConfirmed: boolean
  isDismissed: boolean
  value: string
}

export interface DialogToast {
  message: string
  icon: DialogIcon
}

const DISMISSED: DialogResult = { isConfirmed: false, isDismissed: true, value: '' }
const TOAST_DURATION_MS = 2800
const DEFAULT_CONFIRM = 'ตกลง'
const DEFAULT_CANCEL = 'ยกเลิก'

export const useDialogStore = defineStore('dialog', () => {
  const options = ref<DialogOptions | null>(null)
  const inputValue = ref('')
  const errorMessage = ref('')
  const isBusy = ref(false)
  const toast = ref<DialogToast | null>(null)

  let pendingResolve: ((result: DialogResult) => void) | null = null
  let toastTimer: ReturnType<typeof setTimeout> | null = null

  const isOpen = computed(() => options.value !== null)

  const settle = (result: DialogResult) => {
    const resolve = pendingResolve
    pendingResolve = null
    options.value = null
    errorMessage.value = ''
    isBusy.value = false
    resolve?.(result)
  }

  /** เปิดกล่องสนทนา — ถ้ามีกล่องเดิมค้างอยู่ จะถูกปิดแบบ "ถูกยกเลิก" ก่อน */
  const fire = (next: DialogOptions): Promise<DialogResult> => {
    if (pendingResolve) settle(DISMISSED)
    options.value = next
    inputValue.value = next.inputValue ?? ''
    errorMessage.value = ''
    isBusy.value = false
    return new Promise<DialogResult>((resolve) => {
      pendingResolve = resolve
    })
  }

  const alert = (title: string, text?: string, icon: DialogIcon = 'info') =>
    fire({ title, text, icon, confirmButtonText: DEFAULT_CONFIRM })

  const confirm = (
    title: string,
    text?: string,
    extra: Partial<DialogOptions> = {},
  ): Promise<DialogResult> =>
    fire({
      title,
      text,
      icon: 'question',
      showCancelButton: true,
      confirmButtonText: 'ยืนยัน',
      cancelButtonText: DEFAULT_CANCEL,
      ...extra,
    })

  const input = (title: string, extra: Partial<DialogOptions> = {}): Promise<DialogResult> =>
    fire({
      title,
      input: 'text',
      showCancelButton: true,
      confirmButtonText: DEFAULT_CONFIRM,
      cancelButtonText: DEFAULT_CANCEL,
      ...extra,
    })

  /** กล่อง "กำลังทำงาน" ที่ไม่มีปุ่ม — ปิดด้วย `close()` เมื่อเสร็จ */
  const loading = (title: string, text?: string): Promise<DialogResult> =>
    fire({ title, text, loading: true, position: 'center' })

  /** ปิดกล่องปัจจุบันโดยไม่ยืนยัน */
  const close = () => dismiss()

  /** กดปุ่มยืนยัน — ผ่าน `preConfirm` ก่อนถ้ามี */
  const accept = async () => {
    const current = options.value
    if (!current || isBusy.value) return

    if (current.preConfirm) {
      isBusy.value = true
      try {
        const next = await current.preConfirm(inputValue.value)
        if (typeof next === 'string') inputValue.value = next
      } catch (error) {
        errorMessage.value =
          error instanceof Error && error.message.trim()
            ? error.message
            : 'ข้อมูลไม่ถูกต้อง กรุณาตรวจสอบอีกครั้ง'
        isBusy.value = false
        return
      }
      isBusy.value = false
    }

    settle({ isConfirmed: true, isDismissed: false, value: inputValue.value })
  }

  /** ปิดโดยไม่ยืนยัน (Esc / ฉากหลัง / ปุ่มยกเลิก) */
  const dismiss = () => {
    if (isBusy.value) return
    settle(DISMISSED)
  }

  /** ข้อความสั้น ๆ ที่หายเอง — แทน `Swal.toast` */
  const notify = (message: string, icon: DialogIcon = 'success') => {
    toast.value = { message, icon }
    if (toastTimer) clearTimeout(toastTimer)
    toastTimer = setTimeout(() => {
      toast.value = null
      toastTimer = null
    }, TOAST_DURATION_MS)
  }

  const dismissToast = () => {
    if (toastTimer) clearTimeout(toastTimer)
    toastTimer = null
    toast.value = null
  }

  return {
    options,
    inputValue,
    errorMessage,
    isBusy,
    toast,
    isOpen,
    fire,
    alert,
    confirm,
    input,
    loading,
    close,
    accept,
    dismiss,
    notify,
    dismissToast,
  }
})
