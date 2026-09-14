/**
 * 🏁 ตัวกัน "คำตอบเก่ามาทับคำตอบใหม่" สำหรับการ fetch ที่ถูกกระตุ้นด้วยตัวกรอง
 *
 * ปัญหาที่มันแก้:
 *   หน้าจอที่ `watch(period)` แล้วยิง API มักมีคำขอซ้อนกันได้ เมื่อผู้ใช้เปลี่ยนตัวกรองเร็ว
 *   (เช่นสลับเดือน ก.ย. → ต.ค. หรือสลับ pill ใบเสร็จ ↔ ใบแจ้งหนี้) **ลำดับที่คำตอบกลับมา
 *   ไม่รับประกัน** ว่าเรียงตามลำดับที่ส่ง — โดยเฉพาะเมื่อ backend รันหลาย replica
 *   หลัง Traefik คำขอสองอันอาจถูกคนละ worker รับ ⇒ อันที่ช้ากว่าอาจเป็นอันที่ส่งก่อน
 *   ผลคือ `items` ถูกเขียนด้วยข้อมูลของ **ตัวกรองที่ผู้ใช้ไม่ได้เลือกแล้ว** ขณะที่ป้ายบนจอ
 *   บอกตัวกรองใหม่ ⇒ "ตัวเลขถูกแต่ป้ายผิด" ซึ่งแย่กว่าโหลดไม่ขึ้น เพราะดูเหมือนถูก
 *   และ `isLoading` ก็ถูกปิดไปแล้วโดยคำตอบอันแรกที่มาถึง ⇒ ไม่มีสปินเนอร์ให้รู้ว่ายังไม่จบ
 *
 * วิธีใช้:
 *   const guard = createLatestGuard();
 *   const load = async () => {
 *     const token = guard.begin();              // ← ต้นทางของคำขอ
 *     isLoading.value = true; hasError.value = false;
 *     try {
 *       const rows = await Service.get(...);
 *       if (!guard.isCurrent(token)) return;    // ← คำขอเก่า ถูกแทนที่แล้ว: ทิ้งคำตอบ
 *       items.value = rows;
 *     } catch (e) {
 *       if (!guard.isCurrent(token)) return;
 *       hasError.value = true;
 *     } finally {
 *       if (guard.isCurrent(token)) isLoading.value = false;  // ← ห้ามปิดธงแทนคำขอใหม่
 *     }
 *   };
 *
 * ⚠️ ทั้งสามจุดต้องเช็ค `isCurrent` — พลาดจุดใดจุดหนึ่งแล้วกันไม่จริง:
 *   • ไม่เช็คก่อนเขียนข้อมูล → ข้อมูลเก่าทับใหม่ (ตัวปัญหาเดิม)
 *   • ไม่เช็คก่อนปิด `isLoading` → สปินเนอร์หายทั้งที่คำขอใหม่ยังวิ่งอยู่
 *   • ไม่เช็คใน catch → error ของคำขอเก่ามาทำให้จอขึ้น error ทั้งที่คำขอใหม่สำเร็จ
 *
 * 🚫 ไม่ใช้ `AbortController` เพราะ axios จะ reject ด้วย `CanceledError` ซึ่งปะปนกับ
 *    error จริงใน `catch` และต้องแยกแยะเพิ่ม (`axios.isCancel`) — ส่วนของจริงที่ต้องการคือ
 *    "รู้ว่าคำตอบนี้ยังเป็นตัวล่าสุดไหม" ซึ่งตัวนับทำได้ตรงกว่าและไม่มี error ปลอมเกิดขึ้นเลย
 */
export interface LatestGuard {
  /** เริ่มคำขอใหม่ — คืน token ที่ต้องส่งกลับเข้า `isCurrent` */
  begin: () => number;
  /** คำขอนี้ยังเป็นอันล่าสุดอยู่ไหม */
  isCurrent: (token: number) => boolean;
}

export const createLatestGuard = (): LatestGuard => {
  let latest = 0;
  return {
    begin: () => ++latest,
    isCurrent: (token: number) => token === latest,
  };
};
