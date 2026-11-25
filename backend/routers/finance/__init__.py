"""Package routers.finance — แยก finance_router ตาม resource (accounts/categories/transactions/collections/reporting/export)."""
from fastapi import APIRouter

from .accounts import router as accounts_router
from .categories import router as categories_router
from .transactions import router as transactions_router
from .collections import router as collections_router
from .reporting import router as reporting_router
from .budgets import router as budgets_router
from .receipts import router as receipts_router
from .receipt_batches import router as receipt_batches_router
from .system import router as system_router
from .credits import router as credits_router
from .export import router as export_router
from .fines import router as fines_router
# 👥 [FIN-V2 / P1.2] ผู้เกี่ยวข้องทางการเงิน + ตั้งค่าห้อง
from .people import router as people_router
# 👤 [FIN-V2 / P1.3] บัญชีรายบุคคล + statement
from .individual_accounts import router as individual_accounts_router
# 🧮 [FIN-V2 / P1.5] พรีวิวการจัดสรรเงินรับ
from .allocation import router as allocation_router
# 🧾 [FIN-V2 / P2.1] บันทึก/อ่านรายการรับเงิน (payment event)
from .payment_events import router as payment_events_router
# 📥 [FIN-V2 / P2.7] รับเงินหลายคนในรอบเดียว — ต้อง include **ก่อน** router P2.1
from .payment_events_bulk import router as payment_events_bulk_router
# 💳 [FIN-V2 / P2.4] ช่องทางชำระเงิน + PromptPay QR
from .payment_channels import router as payment_channels_router
# 🧾 [FIN-V2 / P2.6] ใบรับทราบยอดค้าง (ACK) — P5.4 จะต่อท้ายไฟล์ router นี้
from .acknowledgements import router as acknowledgements_router
# 👜 [FIN-V2 / P3.1] เงินสดรอส่งมอบ — กระเป๋า custody + การส่งมอบ + เคลื่อนไหว
from .custody import router as custody_router
# 📜 [FIN-V2 / P3.4] ประวัติการรับเงิน (อ่านอย่างเดียว)
from .payment_history import router as payment_history_router
# 💳 [FIN-V2 / P3.5] หักเครดิตหลายคนเป็นรอบเดียว (credit-only events)
from .credit_rounds import router as credit_rounds_router
# 💸 [FIN-V2 / P4.1] ใบสำคัญจ่ายหลายบรรทัด — P4.2 จะต่อ CERT ในไฟล์ service/router เดิม
from .expense_vouchers import router as expense_vouchers_router
# 💰 [FIN-V2 / P4.4] ใบรับเงินหลายบรรทัด (INC 1 ใบ + 2 ลายเซ็น)
from .income_batches import router as income_batches_router
# 🗂️ [FIN-V2 / P5.1] ทะเบียนเอกสารรวม — `/finance/documents*` (static ก่อน dynamic ภายในไฟล์)
from .documents import router as documents_router
# 📊 [FIN-V2 / P5.4] รายงานปิดงบเดือน — `/finance/monthly-reports*`
from .monthly_reports import router as monthly_reports_router
# 🚫 [FIN-V2 / P6.1] void endpoint กลาง — `/finance/documents/{doc_type}/{doc_id}/void`
#    (เฉพาะ INV/CERT — ชนิดที่แตะเงินต้องยกเลิกผ่าน router ของ resource นั้น)
from .voids import router as voids_router

router = APIRouter()
router.include_router(reporting_router)
router.include_router(accounts_router)
router.include_router(transactions_router)
router.include_router(export_router)
router.include_router(collections_router)
router.include_router(categories_router)
router.include_router(budgets_router)
router.include_router(receipts_router)
# [F5] ชุดเอกสาร — ประกาศ **หลัง** receipts โดยเจตนา: path ของกลุ่มนี้ขึ้นต้นด้วย
# `/finance/receipt-batches` ซึ่งไม่ซ้ำกับ `/finance/receipts` (คนละ segment) ⇒ ลำดับ
# ไม่มีผลกับความถูกต้อง แต่การวางติดกับ receipts ทำให้อ่านออกว่าเป็นเรื่องเดียวกัน
router.include_router(receipt_batches_router)
# [F4] เงินรับล่วงหน้า — ประกาศ **หลัง** receipts โดยเจตนา: ทุก path ของกลุ่มนี้
# ขึ้นต้นด้วย `/finance/credits` ซึ่งไม่ซ้ำกับใคร ⇒ ลำดับไม่มีผล แต่การวางไว้ท้าย
# ทำให้ diff ของงานนี้ต่อเติมท้ายไฟล์ และไม่ตัดหน้า router ที่ deploy อยู่แล้ว
router.include_router(credits_router)
# [F5/PR-3] 🔓 System RPC ของบอท — ประกาศ **ท้ายสุด** โดยเจตนา: path ขึ้นต้นด้วย
# `/finance/system` ซึ่งไม่ซ้ำกับกลุ่มใด ⇒ ลำดับไม่มีผลกับความถูกต้อง แต่การวางท้าย
# ทำให้ชัดว่าเป็นกลุ่มที่ **ข้ามด่านสมาชิก** (ดูคอมเมนต์หัวไฟล์ `system.py`)
# ⚠️ ห้ามย้าย route จากกลุ่มอื่นมาไว้ที่นี่เพื่อ "ให้บอทเรียกได้" — ขอบเขตคือ PDF อ่านเท่านั้น
router.include_router(system_router)
# ⚖️ ค่าปรับ — path ขึ้นต้น `/finance/fines` และ `/finance/fine-types` ซึ่งไม่ซ้ำกับกลุ่มใด
#    (segment `fines` ≠ `fee-collections`) ⇒ ลำดับไม่มีผล แต่ประกาศท้ายเพื่อให้ diff ต่อเติมท้ายไฟล์
router.include_router(fines_router)
# 👥 [FIN-V2 / P1.2] — path ขึ้นต้น `/finance/people` และ `/finance/settings`
#    ซึ่งไม่ซ้ำกับกลุ่มใด ⇒ ประกาศท้ายเพื่อให้ diff ต่อเติมท้ายไฟล์
router.include_router(people_router)
# 👤 [FIN-V2 / P1.3] — path ขึ้นต้น `/finance/individual-accounts` ซึ่งไม่ซ้ำกับกลุ่มใด
#    ⇒ ประกาศท้ายเพื่อให้ diff ต่อเติมท้ายไฟล์
router.include_router(individual_accounts_router)
# 🧮 [FIN-V2 / P1.5] — path ขึ้นต้น `/finance/payment-events` (preview)
#    ⚠️ ต้องอยู่ **ก่อน** router P2.1 ที่จะประกาศ `/{event_id}` — static ก่อน dynamic
router.include_router(allocation_router)
# 📥 [FIN-V2 / P2.7] — path `/finance/payment-events/bulk` (static)
#    ⚠️ ประกาศ **ก่อน** payment_events_router ตามกติกา static ก่อน dynamic
router.include_router(payment_events_bulk_router)
# 🧾 [FIN-V2 / P2.1] — path ขึ้นต้น `/finance/payment-events`
#    ⚠️ ประกาศ **หลัง** allocation_router โดยเจตนา: `/payment-events/preview` (static)
#       ต้องชนะ `/{event_id}` (dynamic) — ถ้าสลับลำดับ preview จะตอบ 422
router.include_router(payment_events_router)
# 💳 [FIN-V2 / P2.4] — path ขึ้นต้น `/finance/payment-channels` ซึ่งไม่ซ้ำกับกลุ่มใด
#    ⚠️ ภายในไฟล์ router ประกาศ `POST /preview-qr` **ก่อน** `GET /{channel_id}/qr.svg`
#       (static ก่อน dynamic) — ลำดับ include ตรงนี้ไม่มีผลกับ route ภายในไฟล์นั้น
router.include_router(payment_channels_router)
# 🧾 [FIN-V2 / P2.6] — path ขึ้นต้น `/finance/acknowledgements` ซึ่งไม่ซ้ำกับกลุ่มใด
#    ⇒ ประกาศท้ายเพื่อให้ diff ต่อเติมท้ายไฟล์ · P5.4 ต่อ GET/void ในไฟล์ router เดียวกัน
router.include_router(acknowledgements_router)
# 👜 [FIN-V2 / P3.1] — path ขึ้นต้น `/finance/custody` ซึ่งไม่ซ้ำกับกลุ่มใด
#    ⇒ ประกาศท้ายเพื่อให้ diff ต่อเติมท้ายไฟล์ (static มาก่อน dynamic ภายในไฟล์นั้น)
router.include_router(custody_router)
# 📜 [FIN-V2 / P3.4] — path ขึ้นต้น `/finance/payment-history` ซึ่งไม่ซ้ำกับกลุ่มใด
#    ⇒ ประกาศท้ายเพื่อให้ diff ต่อเติมท้ายไฟล์ (อ่านล้วน ไม่มี dynamic segment)
router.include_router(payment_history_router)
# 💳 [FIN-V2 / P3.5] — path ขึ้นต้น `/finance/credits/rounds` (static, POST) ซึ่งไม่ซ้ำ
#    กับ route ใดของ `credits_router` ⇒ ประกาศท้ายเพื่อให้ diff ต่อเติมท้ายไฟล์
router.include_router(credit_rounds_router)
# 💸 [FIN-V2 / P4.1] — path ขึ้นต้น `/finance/expense-vouchers` ซึ่งไม่ซ้ำกับกลุ่มใด
#    ⇒ ประกาศท้ายเพื่อให้ diff ต่อเติมท้ายไฟล์ · P4.2 ต่อ CERT ในไฟล์ router เดียวกัน
router.include_router(expense_vouchers_router)
# 💰 [FIN-V2 / P4.4] — path ขึ้นต้น `/finance/income-batches` ซึ่งไม่ซ้ำกับกลุ่มใด
#    ⇒ ประกาศท้ายเพื่อให้ diff ต่อเติมท้ายไฟล์ (static ก่อน dynamic ภายในไฟล์นั้น)
router.include_router(income_batches_router)
# 🗂️ [FIN-V2 / P5.1] — path ขึ้นต้น `/finance/documents` ซึ่งไม่ซ้ำกับกลุ่มใด
#    ⇒ ประกาศท้ายเพื่อให้ diff ต่อเติมท้ายไฟล์
router.include_router(documents_router)

# 📊 [FIN-V2 / P5.4] RPT — path ไม่ทับกลุ่มใด (ลำดับ include ไม่มีผลกับพฤติกรรม)
router.include_router(monthly_reports_router)

# 🚫 [FIN-V2 / P6.1] void กลาง — `/finance/documents/{doc_type}/{doc_id}/void`
#    ⚠️ ประกาศ **หลัง** documents_router โดยเจตนา: path นี้ยาวกว่า (`.../void`)
#       และเป็น POST ขณะที่ registry ใช้ GET ⇒ ไม่มีทางชนกัน แต่การวางท้ายทำให้
#       diff ของงานนี้ต่อเติมท้ายไฟล์
router.include_router(voids_router)

__all__ = ["router"]
