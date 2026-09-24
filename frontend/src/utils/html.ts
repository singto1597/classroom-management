/**
 * 🔒 Escape ข้อความก่อนยัดลง HTML ของ SweetAlert2
 *
 * **ทำไมต้องมี:** SweetAlert2 เรนเดอร์ทั้ง `html:` **และ `title:`** ด้วย `innerHTML`
 * (ดู `node_modules/sweetalert2/dist/sweetalert2.js` → `parseHtmlToContainer(params.title, title)`)
 * ⇒ ข้อความที่ผู้ใช้พิมพ์เองแล้วถูก interpolate ลงไป **ถูกตีความเป็นมาร์กอัป**
 * ไม่ใช่ข้อความ
 *
 * ⚠️ **ทำไม Vue ช่วยไม่ได้:** ในเทมเพลต Vue escape ให้อัตโนมัติ แต่ `Swal.fire({...})`
 *    เป็น **JavaScript** ที่ต่อ string เอง ⇒ ไม่มีอะไร escape ให้เลย
 *    ⇒ จุดที่ปลอดภัยทั้งแอปกลายเป็นจุดที่อันตรายที่สุด โดยดูจากโค้ดไม่ออก
 *
 * **ความเสียหายที่เป็นไปได้:**
 * - อย่างน้อย: เครื่องหมายคำพูดตัวเดียวในชื่อ (เช่น `กระเป๋า "ห้อง 1"`) หลุดออกจาก
 *   `value="…"` แล้วฟอร์มเพี้ยน — ผู้ใช้แก้ข้อมูลเดิมไม่ได้อีก
 * - อย่างมาก: `<img src=x onerror=…>` ในชื่อนักเรียน ⇒ สคริปต์ทำงานในเซสชันของครู
 *   (DOMParser ที่ Swal ใช้ทำให้ `<script>` เฉย แต่ event handler ยังทำงาน)
 *
 * **วิธีใช้:** escape **เฉพาะค่าที่ interpolate** ไม่ใช่ทั้งก้อน HTML
 * ```ts
 * html: `ลบ <b>${escapeHtml(displayName(student))}</b> ?`   // ✅
 * html: escapeHtml(`ลบ <b>${name}</b> ?`)                    // ❌ มาร์กอัปหายหมด
 * ```
 * ถ้าข้อความล้วนและไม่ต้องการมาร์กอัปเลย ให้ใช้ `text:` แทน — Swal ตั้งด้วย
 * `textContent` จึงปลอดภัยโดยธรรมชาติ (ดีที่สุดเมื่อทำได้)
 */

/** Escape ทุกอักขระที่มีความหมายใน HTML — ใช้ได้ทั้ง element content และ attribute ที่ครอบด้วย `"` */
export const escapeHtml = (value: unknown): string =>
  String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');

/**
 * ชื่อพ้องของ `escapeHtml` สำหรับจุดที่ค่าลงไปอยู่ใน attribute
 * (`value="…"`, `class="…"`) — แยกชื่อไว้ให้อ่านแล้วรู้ทันทีว่ากำลังกันอะไร
 */
export const escapeAttr = escapeHtml;
