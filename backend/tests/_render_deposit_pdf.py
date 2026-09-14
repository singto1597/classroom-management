"""🔍 เรนเดอร์ใบรับเงินล่วงหน้า (DEP) ออกมาเป็น HTML/PDF จริง เพื่อ **ดูด้วยตา**

ไม่ใช่เทสต์ (ไม่มี `test_` นำหน้า และไม่แตะ DB) — เป็นเครื่องมือตรวจด้วยสายตาตาม
แผนงานข้อ Verification 4 เพราะ "ใบเสร็จที่ตัวเลขถูกแต่ถ้อยคำผิด" เทสต์จับไม่ได้

วิธีใช้ (จาก repo root):
    docker run --rm -d --name f4_gotenberg -p 3100:3000 gotenberg/gotenberg:8 \\
        gotenberg --api-timeout=120s --chromium-auto-start
    docker run --rm -v "$PWD/backend:/app:z" -w /app --network host \\
        -e GOTENBERG_URL=http://localhost:3100 python:3.12-slim sh -c \\
        "pip install -q -r requirements.txt && python tests/_render_deposit_pdf.py"
"""

import asyncio
import os
import sys
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.finance.pdf import html_to_pdf, render_receipt_html  # noqa: E402
from services.finance.receipts import DOC_TYPE_DEPOSIT, ReceiptsMixin  # noqa: E402

# 🧪 ข้อมูลสมมติที่ "รูปร่าง" ตรงกับที่ `_shape_receipt_detail` ผลิตจริงสำหรับ deposit
#    ค่าที่สำคัญคือ `collection_id`/`line_items` = None และ `student_payment_id` = None
DEPOSIT_DOC = {
    "id": 1,
    "receipt_no": "DEP-2569-0001",
    "doc_type": DOC_TYPE_DEPOSIT,
    "doc_type_label": "ใบรับเงินล่วงหน้า",
    "status": "active",
    "void_reason": None,
    "amount": 1500.00,
    "paid_total_after": 1500.00,
    "student_payment_id": None,
    "collection_id": None,
    "collection_title": None,
    "collection_amount": None,
    "collection_due_date": None,
    "line_items": None,
    "legacy_transaction_id": 42,
    "issued_to_name": "เด็กชายสมชาย ใจดี",
    "student_no": 7,
    "issued_by_name": "ครูสมศรี",
    # ⚠️ ต้องเป็น `datetime` จริง ไม่ใช่ ISO string — `_document_context` เรียก
    #    `_thai_datetime_text` ซึ่งอ่าน `tzinfo` ตรง ๆ (สตริงจะพังทันที)
    "issued_at": datetime(2026, 9, 14, 3, 0, tzinfo=timezone.utc),
    "event_at": datetime(2026, 9, 14, 3, 0, tzinfo=timezone.utc),
    "note": "โอนพร้อมเพย์เมื่อ 14 ก.ย. 2569",
    "room_name": "ห้อง ม.4/1",
    "room_code": "M4-1",
}

# 🧾 ใบเสร็จเงินสดของ "บิลที่จ่ายสด 300 แล้วเครดิตปิดที่เหลือ 700" — ใช้เทียบว่าถ้อยคำ
#    ต้องต่างกันจริง (คนละบริบท) แต่ **ตัวเลขของเหตุการณ์เดียวกันต้องตรงกัน**
RECEIPT_DOC = dict(
    DEPOSIT_DOC,
    receipt_no="REC-2569-0009",
    doc_type="receipt",
    doc_type_label="ใบเสร็จรับเงิน",
    amount=700.00,
    paid_total_after=1000.00,
    collection_id=5,
    collection_title="ค่าไปทัศนศึกษา",
    collection_amount=1000.00,
    collection_due_date=date(2026, 9, 10),
)


def main() -> int:
    out_dir = "/tmp/f4_pdf"
    os.makedirs(out_dir, exist_ok=True)

    for name, doc in (("deposit", DEPOSIT_DOC), ("receipt", RECEIPT_DOC)):
        ctx = ReceiptsMixin._document_context(dict(doc))
        html = render_receipt_html(ctx)
        html_path = os.path.join(out_dir, f"{name}.html")
        with open(html_path, "w", encoding="utf-8") as fh:
            fh.write(html)
        print(f"📄 {name}: HTML {len(html)} ตัวอักษร → {html_path}")

        # 🔴 ตรวจอัตโนมัติ 3 ข้อที่เทสต์ปกติจับไม่ได้ (ถ้อยคำหลุด/None หลุด)
        checks = []
        if ">None<" in html or ">None " in html:
            checks.append("❌ พบ >None< หลุดบนเอกสาร")
        for bad in ("ยอดค้างชำระ", "เรียกเก็บจาก", "ผู้รับแจ้ง"):
            if bad in html:
                where = "❌" if name == "deposit" else "✅(ถูกต้องสำหรับใบเสร็จ)"
                checks.append(f"{where} พบคำว่า '{bad}'")
        for line in checks or ["✅ ไม่พบคำผิดบริบทและไม่มี None หลุด"]:
            print(f"   {line}")

        try:
            pdf = asyncio.run(html_to_pdf(html))
            pdf_path = os.path.join(out_dir, f"{name}.pdf")
            with open(pdf_path, "wb") as fh:
                fh.write(pdf)
            print(f"   🖨️  PDF {len(pdf)} ไบต์ → {pdf_path}")
        except Exception as exc:  # noqa: BLE001 — เครื่องมือตรวจ ไม่ใช่เทสต์
            print(f"   ⚠️  แปลง PDF ไม่ได้ (Gotenberg ไม่ได้รันอยู่?): {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
