/**
 * ตัวช่วยดาวน์โหลดไฟล์ที่ backend ส่งกลับมาเป็น Blob (Excel / PDF)
 *
 * 📌 ย้ายมาจากสำเนาในตัวที่อยู่ใน `FinanceDashboard.vue` และ `FinancialStatements.vue`
 *    (สองที่นั้นเหมือนกันทุกตัวอักษร) — ตอนเพิ่มหน้ากากใบเสร็จ (F3) จะกลายเป็นสำเนาที่ 3
 *    และสำเนาที่ 4 ⇒ ดึงมาไว้ที่เดียวตั้งแต่ตอนนี้
 *
 * ⚠️ ต้อง `revokeObjectURL` ทุกครั้ง ไม่งั้น Blob ทั้งก้อนถูก pin ไว้ในหน่วยความจำ
 *    จนกว่าจะปิดแท็บ (ไฟล์ Excel/PDF ของการเงินใหญ่ระดับหลายร้อย KB และครูกดซ้ำบ่อย)
 *
 * 🚨 revoke ต้อง **เลื่อนออกไป** ห้าม revoke ต่อทันทีในบรรทัดถัดจาก `click()`
 *    `click()` แค่ "เข้าคิว" การนำทางไว้ — เบราว์เซอร์ไปอ่าน blob URL จริงแบบ **asynchronous**
 *    ถ้า revoke ในคาบเดียวกัน เบราว์เซอร์บางตัว (Firefox, iOS Safari) จะอ่านไม่ทัน
 *    → **ไฟล์ถูกยกเลิกเงียบ ๆ** ไม่มี exception ให้จับ ⇒ ผู้ใช้เห็น "ดาวน์โหลดสำเร็จ"
 *    แต่ไม่มีไฟล์ หรือได้ไฟล์ 0 ไบต์ ซึ่งแยกไม่ออกจาก "ระบบพัง" สำหรับครูที่รอใบเสร็จอยู่
 *
 * ⏱️ ทำไม 1 วินาที (ไม่ใช่ 0) — และข้อจำกัดที่ต้องรู้
 *    `setTimeout(..., 0)` รับประกันแค่ว่า revoke ไปอยู่ **คนละ task** (ลำดับการทำงาน)
 *    ไม่ได้แปลว่าเบราว์เซอร์ dereference blob URL ไปแล้ว — เป็นการเดาจากพฤติกรรมที่สังเกตได้
 *    ไม่ใช่สัญญาที่มีสเปก และ **พิสูจน์ในนี้ไม่ได้** (ไม่มีเบราว์เซอร์จริงในเทสต์)
 *    1 วินาทีจึงเป็น "ระยะเผื่อ" ที่ต้นทุนต่ำมาก เพราะ blob URL อ่านจาก **หน่วยความจำในเครื่อง**
 *    ไม่ได้วิ่งผ่านเครือข่าย ⇒ งานที่รออยู่มีแค่ "เริ่มอ่าน" ไม่ใช่ "โหลดเสร็จ"
 *    (FileSaver.js เผื่อถึง 40 วินาที แต่เหตุผลของมันครอบไฟล์ใหญ่ที่ยังเขียนลงดิสก์ไม่เสร็จ
 *     ซึ่งคนละกรณีกับ blob URL)
 *    ⚠️ ถ้าปิดแท็บก่อน timeout ทำงาน revoke จะไม่ถูกเรียก — ไม่ใช่ leak เพราะ blob ถูกคืน
 *       ตอนทิ้งหน้าไปแล้ว แต่ก็อย่าอ่านคำเตือนเรื่องหน่วยความจำข้างบนแบบสัมบูรณ์
 *    🔴 และเพราะกลไกนี้ **ไม่มีเทสต์คุมได้** ⇒ ห้ามมีสำเนาโค้ดนี้ที่อื่น ให้เรียกฟังก์ชันนี้เท่านั้น
 */
export const downloadBlob = (blob: Blob, filename: string): void => {
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.setAttribute('download', filename);
  // ต้องต่อเข้า document ก่อน click() — Firefox ไม่เริ่มดาวน์โหลดให้ anchor ที่ลอยอยู่
  document.body.appendChild(link);
  link.click();
  link.remove();
  // คืนหน่วยความจำหลังจากนั้น — ห้ามย้ายขึ้นมาเป็นบรรทัดถัดจาก click()
  window.setTimeout(() => window.URL.revokeObjectURL(url), 1000);
};

/**
 * 🏷️ ชื่อไฟล์ของ **PDF รวมหลายใบ** (ไฟล์เดียว หน้าละใบ)
 *
 * 🔴 รูปเดียวกับ `pdf_filename_batch` ฝั่ง backend — ถ้าแก้ที่นั่นต้องแก้ที่นี่
 *    (backend ส่งชื่อมาใน `Content-Disposition` ด้วย แต่ `downloadBlob` ต้องได้ชื่อ
 *     **ตอนเรียก** ⇒ จะอ่าน header ก็ต้องพึ่ง CORS `expose_headers` ซึ่งพังเงียบ
 *     และแยกไม่ออกจาก "ระบบพัง" สำหรับครูที่รอไฟล์อยู่)
 *
 * 📌 ตั้งชื่อตาม **ช่วงเลขที่เอกสาร** ไม่ใช่ số lượngหรือวันที่:
 *    - บอกได้ว่าเป็นชุดไหน และตรงกับเลขที่พิมพ์อยู่บนเอกสารข้างใน
 *    - ไฟล์ที่ชื่อเป็นวันที่จะแยกไม่ออกเมื่อมีหลายชุดในวันเดียว
 *    - ไม่ผูกกับจำนวนหน้า ⇒ ไฟล์เก่าที่โหลดซ้ำยังชื่อเดิม (หาเจอง่าย)
 *
 * @param receiptNos เลขที่เอกสาร **ตามลำดับที่จะพิมพ์** (ตัวแรก/สุดท้ายคือสิ่งที่ขึ้นชื่อไฟล์)
 * @param kind       คำนำหน้าชนิดเอกสาร — 'documents' เมื่อในชุดมีปนกันมากกว่าหนึ่งชนิด
 */
export const combinedPdfFilename = (
  receiptNos: string[],
  kind: 'receipts' | 'invoices' | 'documents' = 'documents',
): string => {
  const first = (receiptNos[0] ?? 'documents').replace(/\//g, '-');
  const last = (receiptNos[receiptNos.length - 1] ?? first).replace(/\//g, '-');
  return first === last ? `${kind}-${first}.pdf` : `${kind}-${first}-to-${last}.pdf`;
};

/**
 * 🏷️ ชื่อไฟล์ Excel ของกิจกรรม — ย้ายมาจากสำเนาใน `ActivityDetail.vue`
 *
 * 🔴 รูปเดียวกับ `ExportMixin._sanitize_filename` ฝั่ง backend เป๊ะ ๆ
 *    ถ้าแก้ที่นั่นต้องแก้ที่นี่ ไม่งั้นชื่อไฟล์ที่ผู้ใช้เห็นตอนดาวน์โหลดจะไม่ตรงกับ
 *    ชื่อที่ backend ใส่ไว้ใน `Content-Disposition` (ผู้ใช้จะได้ไฟล์สองชื่อสลับกันไปมา)
 *    - อักขระต้องห้ามของ Windows (`\ / : * ? " < > |`) → `_`
 *    - ช่องว่างทุกชนิด → `_` แล้วตัด `_`/ช่องว่างหัวท้ายออก
 *    - ยาวเกิน 80 ตัว → ตัด (กัน filesystem/Discord ปฏิเสธ)
 *    - ว่างเปล่าหลังล้าง → `'กิจกรรม'` (ห้ามได้ชื่อไฟล์ที่ไม่มีชื่อ)
 */
export const safeActivityFilename = (title: string): string => {
  const cleaned = (title ?? '')
    .replace(/[\\/:*?"<>|]/g, '_')
    .replace(/\s+/g, '_')
    .replace(/^[_\s]+|[_\s]+$/g, '');
  return cleaned.slice(0, 80) || 'กิจกรรม';
};

/**
 * 🏷️ ชื่อไฟล์ของ **Excel รวมหลายกิจกรรม** (ภูมิภาคที่เลือกจากแผนภาพเวน)
 *
 * 🔴 รูปเดียวกับ `ExportCombinedMixin._combined_filename` ฝั่ง backend
 *    ตัดที่ 60 ตัวอักษร **ก่อน** ต่อท้าย `_รายชื่อผู้เข้าร่วม.xlsx`
 *    ⇒ ชื่อกิจกรรมยาว ๆ จะไม่ไปกินที่จน suffix ถูกตัดทิ้ง (ซึ่งจะทำให้ไฟล์ไม่มีนามสกุล)
 */
export const combinedActivityFilename = (titles: string[]): string => {
  const joined = titles.map(safeActivityFilename).join('_').slice(0, 60).replace(/_+$/, '');
  return `${joined || 'กิจกรรม'}_รายชื่อผู้เข้าร่วม.xlsx`;
};
