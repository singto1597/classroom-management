"""Facade ที่รวมทุก mixin ของโมดูลการเงินเป็น FinanceService (public API เดิม)"""
from .base import BaseMixin
from .ledger import LedgerMixin
# 📒 เกณฑ์คงค้าง — วางติดกับ LedgerMixin เพราะพึ่ง `_resolve_*_ledger`/`_insert_journal_entry`
#    ของมันโดยตรง (ไม่มีชื่อฟังก์ชันชนกับ mixin อื่น)
from .accrual import AccrualMixin
from .accounts import AccountsMixin
from .categories import CategoriesMixin
from .transactions import TransactionsMixin
from .collections import CollectionsMixin
from .reporting import ReportingMixin
from .budgets import BudgetsMixin
from .receipts import ReceiptsMixin
from .receipt_batches import ReceiptBatchesMixin
from .credits import CreditsMixin
from .backfill import BackfillMixin
from .export import ExportMixin
# ⚖️ ค่าปรับ — `FineTypesMixin`/`FinesMixin` พึ่ง `_create_bills_with_accrual`,
#    `_post_bill_adjustment`, `_issue_fine_invoice`, `_void_invoice_for_payment`
#    (มาจาก Accrual/ReceiptsMixin) และวิธี MRO: mixin ที่ import ไว้บนสุดชนะ
#    ⇒ ทั้งสองวาง **ก่อน** Accrual/Receipts โดยไม่มีชื่อฟังก์ชันชนกันเลย
from .fine_types import FineTypesMixin
from .fines import FinesMixin
# 💸 คำขอยกเว้น/คืนเงิน — พึ่ง `_load_fine_for_update`/`_sync_fine_status`/
#    `_issue_fine_invoice`/`_void_invoice_for_payment` ของ Fines/Receipts
from .waivers import WaiversMixin
from .refunds import RefundsMixin
# 📊 รายงานผู้ค้างชำระ (aging) + สรุปค่าปรับ — อ่านอย่างเดียว ใช้ `_open_bill_predicate`
#    ของ AccrualMixin · วางตรงนี้ได้เพราะชื่อ (`get_receivables_aging`/`get_fine_summary`)
#    ไม่ชนกับ mixin ใด — ถ้าอนาคตมีชื่อชน ให้ย้ายมixin นี้ **ก่อน** ตัวที่ชน
from .receivables import ReceivablesMixin
# 📣 เตือนผู้ค้างชำระรายวัน (Phase 6) — ใช้ `_open_bill_predicate` (AccrualMixin) และ
#    `_get_room_server_id` (BaseMixin) ผ่าน MRO ของ FinanceService · ไม่มีชื่อฟังก์ชันชน
from .reminders import RemindersMixin
# ⏰ ค่าปรับจ่ายล่าช้าอัตโนมัติ (Phase 6.5) — ใช้ `_open_bill_predicate` (Accrual),
#    `_create_bills_with_accrual`, `_issue_fine_invoice` (Receipts), `_lock_room_money`
#    และ `notify_user` · ไม่มีชื่อชนกับ mixin ใด (`apply_late_fees` เป็นชื่อใหม่)
from .late_fees import LateFeesMixin
# 🧾 เรียกเก็บเงินเองรายบุคคล (Phase 6.5) — ใช้ `_create_bills_with_accrual` ผ่าน MRO
from .custom_charges import CustomChargesMixin
# 👥 [FIN-V2 / P1.2] ผู้เกี่ยวข้องทางการเงิน + finance_settings — ไม่พึ่ง helper ของ
#    mixin ใด (ใช้ `resolve_room_id` จาก BaseMixin ผ่าน MRO) แต่วางก่อน Accrual/Ledger
#    ตามกติกา "mixin ใหม่วางก่อนตัวที่มันอาจพึ่ง" · P2.1+ อ่าน `default_receiver` จากที่นี่
from .people import PeopleMixin
# 👤 [FIN-V2 / P1.3] บัญชีรายบุคคล — ใช้ `_open_bill_predicate` (AccrualMixin) และ
#    `resolve_room_id` (BaseMixin) ผ่าน MRO ⇒ ต้องวาง **ก่อน** AccrualMixin
#    (กติกา: mixin ใหม่วางก่อนตัวที่มันพึ่ง) · ไม่มีชื่อฟังก์ชันชนกับ mixin ใด
from .individual_accounts import IndividualAccountsMixin
# 🧮 [FIN-V2 / P1.5] เครื่องจัดสรรเงินรับ (preview) — พึ่ง `_open_bill_predicate`
#    (AccrualMixin) และ `_load_credit_balance` (CreditsMixin) ⇒ ต้องวาง **ก่อน**
#    ทั้งสองตัวตามกติกา MRO · engine เองอยู่ใน `allocation.py` แบบ pure function
from .allocation import AllocationMixin
# 🧾 [FIN-V2 / P2.1] event + เอกสาร v2 — พึ่ง `_confirm_single_payment` (Collections),
#    `_apply_plan_locked`/`_load_credit_balance` (Credits), `_display_name`/
#    `_thai_year_be` (Receipts) และ `_open_bill_predicate` (Accrual) ผ่าน MRO
#    ⇒ ไม่ override ฟังก์ชันใดของ mixin เดิม (ชื่อขึ้นต้น `_issue_event_*` ทั้งหมด)
from .payment_events import PaymentEventsMixin
from .bulk_receive import BulkReceiveMixin
from .receipts_v2 import ReceiptsV2Mixin
# 🧾 [FIN-V2 / P2.6] INV v2 + ACK — override `_issue_invoice_aggregate` (ReceiptsMixin)
#    และ `_body_template_for` (DocumentsMixin) ผ่าน MRO ⇒ ต้องอยู่ใน MRO **ก่อน** ทั้งคู่
#    (ชื่ออื่นเป็นชื่อใหม่: `issue_acknowledgements`/`_invoice_channel_snapshot`/…)
from .invoice_documents import InvoiceDocumentsMixin
# 🧾 [FIN-V2 / P2.2] context/template ของเอกสาร v2 — `_document_context` (ReceiptsMixin)
#    dispatch มาที่ `_document_context_v2` ผ่าน MRO ⇒ mixin นี้ต้องอยู่ใน MRO ก่อนเรียก
#    (ชื่อไม่ชนกับ mixin ใด — `_body_template_for`/`_v2_line_items`/`_document_context_v2`)
from .documents import DocumentsMixin
# 💳 [FIN-V2 / P2.4] ช่องทางชำระเงิน + PromptPay QR — ใช้ `_lock_room_money`/
#    `resolve_room_id`/`service_logger` ผ่าน MRO และ `qr.py` แบบ pure function
#    (ไม่มีชื่อฟังก์ชันชนกับ mixin ใด ⇒ วางก่อน AccountsMixin ตาม brief)
from .payment_channels import PaymentChannelsMixin
# 👜 [FIN-V2 / P3.1] เงินสดรอส่งมอบ — พึ่ง `_resolve_asset_ledger`/
#    `_insert_journal_entry` (LedgerMixin) และ `resolve_room_id` (BaseMixin) ผ่าน MRO
#    ⇒ ต้องวาง **ก่อน** สองตัวนั้น · ไม่มีชื่อฟังก์ชันชนกับ mixin ใด
from .custody import CustodyMixin
# 💳 [FIN-V2 / P3.5] หักเครดิตหลายคนเป็นรอบเดียว — พึ่ง `_build_plan_for_students`/
#    `_apply_plan_locked` (CreditsMixin), `_lock_room_money`/`_lock_payments_in_order`
#    (BaseMixin) และ `assert_plan_equation` (allocation.py) ผ่าน MRO
#    ⇒ ต้องวาง **ก่อน** CreditsMixin/BaseMixin ตามกติกา "mixin ใหม่วางก่อนตัวที่พึ่ง"
#    (ชื่อใหม่ทั้งหมด: `create_credit_round` — ไม่ชนกับ mixin ใด)
from .credit_rounds import CreditRoundsMixin
# 💸 [FIN-V2 / P4.1] ใบสำคัญจ่ายหลายบรรทัด — พึ่ง `_resolve_asset_ledger`/
#    `_insert_journal_entry` (LedgerMixin) และ `resolve_room_id` (BaseMixin) ผ่าน MRO
#    ⇒ ต้องวาง **ก่อน** สองตัวนั้น · ไม่มีชื่อฟังก์ชันชนกับ mixin ใด
#    (ชื่อใหม่ทั้งหมด: `create_expense_voucher`/`list_expense_vouchers`/…)
from .expense_vouchers import ExpenseVouchersMixin
# 💰 [FIN-V2 / P4.4] ใบรับเงินหลายบรรทัด — พึ่ง `_resolve_asset_ledger`/
#    `_insert_journal_entry` (LedgerMixin), `resolve_room_id`/`_get_room_server_id`
#    (BaseMixin) และ `_resolve_actor_name` (ExpenseVouchersMixin) ผ่าน MRO
#    ⇒ ต้องอยู่ **ก่อน** LedgerMixin/BaseMixin · ไม่มีชื่อฟังก์ชันชนกับ mixin ใด
from .income_batches import IncomeBatchesMixin
# 🗂️ [FIN-V2 / P5.1] ทะเบียนเอกสารรวม — อ่านอย่างเดียว; เรียก `_shape_receipt_detail`/
#    `_document_context(s)` (ReceiptsMixin) และ `render_receipt_pdf` ผ่าน MRO
#    ⇒ ต้องอยู่ **หลัง** ReceiptsMixin และก่อน Accrual/Ledger ตามกติกาทั่วไป
#    (ชื่อใหม่ทั้งหมด: `list_documents`/`get_document_detail`/…)
from .document_registry import DocumentRegistryMixin


class FinanceService(
    # ⚖️ ค่าปรับมาก่อนเสมอ — ชื่อฟังก์ชันไม่ชนกับ mixin ใด แต่การวางหน้ารับประกันว่า
    #    ถ้าวันหนึ่งมีชื่อชน (เช่น `update_fine`) ตัวค่าปรับจะชนะอย่างชัดเจน
    WaiversMixin,
    RefundsMixin,
    FinesMixin,
    FineTypesMixin,
    ReceivablesMixin,
    # 📣 วางติด ReceivablesMixin (ทั้งคู่อ่านอย่างเดียว/ไม่ชนชื่อ) — ถ้าอนาคตมีชื่อชน
    #    ให้ย้ายตัวที่ **ไม่ควรชนะ** ลงไปข้างล่าง (MRO: ตัวบนชนะ)
    RemindersMixin,
    # ⏰🧾 P6.5 — สองตัวนี้พึ่ง `_create_bills_with_accrual` (AccrualMixin) และ
    #    `_issue_fine_invoice` (ReceiptsMixin) ผ่าน MRO ⇒ วางไว้บนได้เหมือน mixin ค่าปรับ
    LateFeesMixin,
    CustomChargesMixin,
    ExportMixin,
    ReportingMixin,
    # 🧾 [FIN-V2 / P2.6] — MRO ต้องเป็น InvoiceDocumentsMixin → DocumentsMixin → ReceiptsMixin
    #    ⇒ INV ที่ออกผ่าน `issue_invoices*` กลายเป็น v2 (override `_issue_invoice_aggregate`)
    #    และ `_body_template_for` ของ INV/ACK ชนะ version ของ DocumentsMixin
    InvoiceDocumentsMixin,
    # 🧾 [FIN-V2 / P2.2] — วาง**ก่อน** `ReceiptsMixin` ตาม brief (mixin ที่อยู่บนชนะ)
    #    `ReceiptsMixin._document_context` เรียก `cls._document_context_v2` ผ่าน MRO
    DocumentsMixin,
    ReceiptsMixin,
    # 📚 วาง **หลัง** `ReceiptsMixin` โดยเจตนา: `ReceiptBatchesMixin` ไม่ได้ override
    #    ฟังก์ชันใดของ ReceiptsMixin (ชื่อไม่ชนกันเลย) ⇒ ลำดับไม่มีผลกับพฤติกรรม
    #    แต่การวางติดกันทำให้อ่านออกว่า "ชุดเอกสารเป็นเรื่องของทะเบียนเอกสาร"
    #    ⚠️ ห้ามย้าย `ReceiptsMixin` ไปหลัง mixin ที่พึ่ง `_shape_receipt*`/`_RECEIPT_COLUMNS`
    ReceiptBatchesMixin,
    # 🗂️ [FIN-V2 / P5.1] — ทะเบียนเอกสารรวม (อ่านอย่างเดียว) วางติด ReceiptBatchesMixin
    #    ตาม brief · พึ่ง `_shape_receipt_detail`/`_document_context(s)` ของ ReceiptsMixin
    #    และ `_document_context_v2` ของ DocumentsMixin ผ่าน MRO ⇒ อยู่ใต้ทั้งคู่แล้ว
    DocumentRegistryMixin,
    CreditsMixin,
    BudgetsMixin,
    CollectionsMixin,
    # 🧾 [FIN-V2 / P2.1] — วาง **หลัง** Receipts/Credits/Collections ตามที่ brief กำหนด
    #    (ไม่มีชื่อฟังก์ชันชนกัน: `_issue_event_*`/`create_payment_event` เป็นชื่อใหม่)
    #    ⚠️ `PaymentEventsMixin` เรียก `_money_str` ของ AllocationMixin ผ่าน MRO
    #       และ `_issue_event_*` ของ ReceiptsV2Mixin — ทั้งคู่ค้นเจอด้านล่างได้เสมอ
    PaymentEventsMixin,
    # 📥 [FIN-V2 / P2.7] รับเงินหลายคน — ใช้ `_commit_payment_event_locked` ของ
    #    PaymentEventsMixin ผ่าน MRO (ไม่ประกาศ method ซ้ำ)
    BulkReceiveMixin,
    ReceiptsV2Mixin,
    TransactionsMixin,
    CategoriesMixin,
    # 💳 [FIN-V2 / P2.4] — ช่องทางชำระเงิน + QR (อ่านผ่าน `require_member`,
    #    เขียนผ่าน `MANAGE_FINANCE` ใต้ล็อกห้อง) · วางก่อน AccountsMixin ตาม brief
    PaymentChannelsMixin,
    AccountsMixin,
    BackfillMixin,
    # 👥 [FIN-V2 / P1.2] — อ่าน/เขียนทะเบียนผู้เกี่ยวข้อง + ตั้งค่าห้อง (ไม่มีชื่อชน)
    PeopleMixin,
    # 👤 [FIN-V2 / P1.3] — บัญชีรายบุคคล + statement (อ่านอย่างเดียว)
    #    พึ่ง `_open_bill_predicate()` ของ AccrualMixin ⇒ อยู่ก่อนมันตามกติกา MRO
    IndividualAccountsMixin,
    # 👜 [FIN-V2 / P3.1] — เงินสดรอส่งมอบ (กระเป๋า custody + ส่งมอบ)
    #    พึ่ง `_resolve_asset_ledger`/`_insert_journal_entry` (LedgerMixin) และ
    #    `resolve_room_id` (BaseMixin) ⇒ ต้องอยู่ **ก่อน** LedgerMixin/BaseMixin
    #    (ชื่อใหม่ทั้งหมด: `create_custody_account`/`create_handover`/…)
    CustodyMixin,
    # 💳 [FIN-V2 / P3.5] — รอบหักเครดิตหลายคน (1 คน = 1 credit-only event)
    #    พึ่ง `_build_plan_for_students`/`_apply_plan_locked` (CreditsMixin) และ
    #    `_lock_*` (BaseMixin) ⇒ อยู่ก่อนทั้งคู่ตามกติกา MRO
    #    (ชื่อใหม่ทั้งหมด ⇒ ไม่ override ฟังก์ชันใดของ mixin เดิม)
    CreditRoundsMixin,
    # 💸 [FIN-V2 / P4.1] — ใบสำคัญจ่ายหลายบรรทัด (1 ใบ = N txn + N journal + 1 PV)
    #    พึ่ง `_resolve_asset_ledger`/`_insert_journal_entry` (LedgerMixin) และ
    #    `resolve_room_id` (BaseMixin) ⇒ อยู่ก่อนทั้งคู่ตามกติกา MRO
    ExpenseVouchersMixin,
    # 💰 [FIN-V2 / P4.4] — ใบรับเงินหลายบรรทัด (1 ใบ = N txn + N journal + 1 INC)
    #    พึ่ง helper เดียวกับ P4.1 ⇒ อยู่ติดกันก่อน LedgerMixin/BaseMixin
    IncomeBatchesMixin,
    # 🧮 [FIN-V2 / P1.5] — preview การจัดสรร (อ่านอย่างเดียว)
    #    พึ่ง `_open_bill_predicate()` (Accrual) และ `_load_credit_balance` (Credits)
    #    ⇒ อยู่ก่อนทั้งคู่ตามกติกา MRO (mixin ที่อยู่บนชนะ)
    AllocationMixin,
    AccrualMixin,
    LedgerMixin,
    BaseMixin,
):
    """Service การเงินรวม — ประกอบจาก mixin ย่อยตามความรับผิดชอบ (ดู services/finance/*)"""
    pass
