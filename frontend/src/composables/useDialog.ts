import { useDialogStore } from '@/stores/dialog'

/**
 * ทางเรียกกล่องสนทนากลางแบบสั้น
 *
 * @example
 * const dialog = useDialog()
 * const { isConfirmed } = await dialog.confirm('ลบรายการนี้?', 'ย้อนกลับไม่ได้')
 * dialog.notify('บันทึกแล้ว')
 */
export function useDialog() {
  return useDialogStore()
}
