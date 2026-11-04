import { onBeforeUnmount, readonly, ref, toValue, watch, type MaybeRefOrGetter } from 'vue';

/**
 * 🏷️ หัวข้อหน้าแบบไดนามิก — header เป็นเจ้าของ `<h1>` แต่ชื่อจริงมาเป็นบางครั้ง
 * หลังโหลดข้อมูล (เช่น ชื่อนักเรียน/กิจกรรม)
 *
 * กติกา:
 *  - `route.meta.title` คือ **fallback** ที่มีเสมอ
 *  - หน้า detail เรียก `usePageTitle(() => entity.value?.name)` ใน setup
 *    ⇒ ชื่อจะเปลี่ยนตามข้อมูลที่โหลดเสร็จ และถูกล้างเมื่อออกจากหน้า
 *  - `MainLayout`/`AppHeader` ล้าง override ทุกครั้งที่ path เปลี่ยน
 *    เพื่อไม่ให้ชื่อหน้าหนึ่งค้างไปหน้าถัดไป
 *
 * ค่าเก็บที่โมดูล (ไม่ใช่ store) โดยเจตนา: เป็นสถานะของ "เปลือก" หน้าหนึ่งหน้า
 * ไม่ต้อง persist ไม่ต้อง sync ข้ามแท็บ และไม่ควรถูก serialize ลง localStorage
 */
const override = ref<string | null>(null);

/** หัวข้อที่หน้าปัจจุบันต้องการแทน `route.meta.title` (null = ใช้ค่า meta) */
export const pageTitleOverride = readonly(override);

/** ตั้งหัวข้อไดนามิก — ค่าว่าง/null จะล้างกลับไปใช้ `route.meta.title` */
export function setPageTitle(title: string | null | undefined): void {
  const trimmed = title?.trim();
  override.value = trimmed ? trimmed : null;
}

/** ล้างหัวข้อไดนามิก */
export function clearPageTitle(): void {
  override.value = null;
}

/**
 * ผูกหัวข้อไดนามิกกับแหล่งข้อมูล reactive
 *
 * @example
 * const student = ref<Student | null>(null);
 * usePageTitle(() => student.value?.full_name);
 */
export function usePageTitle(
  source: MaybeRefOrGetter<string | null | undefined>,
): void {
  watch(
    () => toValue(source),
    (title) => setPageTitle(title ?? null),
    { immediate: true },
  );

  onBeforeUnmount(() => {
    // ล้างเฉพาะเมื่อหน้านี้ยังเป็นเจ้าของค่า — ถ้าหน้าถัดไปตั้งค่าใหม่แล้ว
    // (transition mode="out-in" ทำให้เกิดลำดับ unmount → mount) ต้องไม่ไปลบของเขา
    if (override.value === (toValue(source)?.trim() || null)) clearPageTitle();
  });
}
