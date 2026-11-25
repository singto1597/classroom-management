"""🗂️ [FIN-V2 / P5.3] Adapter registry ของเอกสาร — "หนึ่งคู่ (layout_version, doc_type) หนึ่งตัว"

═══════════════════════════════════════════════════════════════════════════════
ทำไมต้องมี registry
═══════════════════════════════════════════════════════════════════════════════
เอกสารในระบบมีสองยุคที่ต้องอยู่ร่วมกัน:

- **legacy** (`layout_version = 1`) — ใบเสร็จ/ใบแจ้งหนี้/ใบสำคัญจ่าย/ใบรับเงินล่วงหน้า
  รุ่นเดิม พิมพ์ด้วย `_receipt_body.html` / `_voucher_body.html` **ไบต์เดิม**
- **v2** (`layout_version = 2`) — เอกสารระดับ event พิมพ์จาก snapshot ด้วย partial ของ
  ชนิดนั้น (`_receipt_body_v2.html`, `_deposit_body_v2.html`, `_invoice_body_v2.html`, …)

🔴 คีย์จึงเป็น `(layout_version, doc_type)` **ไม่ใช่ doc_type เดี่ยว** — REC v1 กับ REC v2
   ใช้เทมเพลตคนละไฟล์ และต้อง coexist ในชุดพิมพ์เดียวกันได้ (`POST /documents/print-bundle`
   รับได้ทั้งสองยุคพร้อมกัน ⇒ shell `receipt.html` เรนเดอร์ครั้งเดียว `{% include %}` ต่อใบ)

🧩 เฟสถัดไปลงทะเบียนของตัวเองโดยไม่แตะไฟล์นี้:
   - P4.6 → `(2, payment_voucher / certificate / income)` — ลงทะเบียนด้านล่างแล้วในสาขานี้
   - P5.4 → `(2, acknowledgement / monthly_report)`
   ⇒ `register()` เป็น idempotent (ลงทับคีย์เดิมได้) แต่ log เตือนเมื่อTemplate เปลี่ยน

⚠️ `build_context` ของทุก adapter เรียก `FinanceService._document_context` แบบ lazy
   (import ในฟังก์ชัน) — ห้าม import service ที่หัวไฟล์ เพราะ `service.py` import
   `receipts.py` ที่ import ไฟล์นี้ ⇒ circular import
   และ `_document_context` เรียก `resolve_adapter` แค่เพื่อเอา `body_template`
   (ไม่เรียก `build_context`) ⇒ ไม่มีการเรียกซ้ำเป็นวงกลม
"""
import logging
from dataclasses import dataclass, replace
from typing import Callable, Dict, Tuple

from .constants import (
    DOC_TYPE_ACKNOWLEDGEMENT,
    DOC_TYPE_CERTIFICATE,
    DOC_TYPE_DEPOSIT,
    DOC_TYPE_INCOME,
    DOC_TYPE_INVOICE,
    DOC_TYPE_PAYMENT_VOUCHER,
    DOC_TYPE_RECEIPT,
)

logger = logging.getLogger(__name__)

# 🖨️ ชื่อไฟล์ partial ของ shell `receipt.html`
#    🔴 ต้องตรงกับไฟล์จริงใน `templates/finance/` — พิมพ์ผิด = `TemplateNotFound`
#       **ตอนกดพิมพ์** ไม่ใช่ตอน import (เทสต์ `test_registered_templates_exist_on_disk` กันไว้)
LEGACY_RECEIPT_BODY = "_receipt_body.html"
LEGACY_VOUCHER_BODY = "_voucher_body.html"
V2_RECEIPT_BODY = "_receipt_body_v2.html"
V2_DEPOSIT_BODY = "_deposit_body_v2.html"
V2_INVOICE_BODY = "_invoice_body_v2.html"
V2_ACKNOWLEDGEMENT_BODY = "_acknowledgement_body_v2.html"
V2_VOUCHER_BODY = "_voucher_body_v2.html"
V2_CERTIFICATE_BODY = "_certificate_body_v2.html"
V2_INCOME_BODY = "_income_body_v2.html"


@dataclass(frozen=True)
class DocumentAdapter:
    """สัญญาของเอกสารหนึ่งคู่ (layout, ชนิด)

    - `body_template` — ไฟล์ partial ที่ shell จะ `{% include %}`
    - `build_context`  — `row (dict) → context ของ Jinja` (delegate ไปที่ service)
    - `can_print`      — False = ยังไม่มีเทมเพลตที่พิมพ์ได้ (ผู้เรียกตอบ 404)
    """

    layout_version: int
    doc_type: str
    body_template: str
    build_context: Callable[[dict], dict]
    can_print: bool = True


_ADAPTERS: Dict[Tuple[int, str], DocumentAdapter] = {}


def register(adapter: DocumentAdapter) -> None:
    """ลงทะเบียน adapter — คีย์เดิมถูกทับได้ (idempotent) แต่ log เตือนเมื่อเทมเพลตเปลี่ยน

    🔑 idempotent เพราะโมดูลของเฟสต่าง ๆ อาจถูก import ซ้ำ (reload ในเทสต์) และ
       การลงทะเบียนซ้ำด้วยค่าเดิมไม่ควรสร้าง warning ให้ log รก
    """
    key = (int(adapter.layout_version), adapter.doc_type)
    existing = _ADAPTERS.get(key)
    if existing is not None and existing.body_template != adapter.body_template:
        logger.warning(
            "[FIN-V2] adapter %s ถูกแทนที่: %s → %s",
            key, existing.body_template, adapter.body_template,
        )
    _ADAPTERS[key] = adapter


def resolve_adapter(layout_version: int, doc_type: str) -> DocumentAdapter:
    """หาติว adapter ของ (layout, ชนิด)

    🔴 ไม่พบของ layout ที่ขอ → **ถอยไปใช้ legacy ของชนิดนั้น** + log warning
       (กระดาษที่พิมพ์ด้วยเทมเพลตเก่า ยังดีกว่าผู้ใช้ถือใบพิมพ�์ไม่ได้)
    🔴 ไม่มีทั้งคู่ → `ValueError` ข้อความไทย (router แปลงเป็น 400 ไม่ใช่ 500)
    """
    layout = int(layout_version or 1)
    adapter = _ADAPTERS.get((layout, doc_type))
    if adapter is not None:
        return adapter

    legacy = _ADAPTERS.get((1, doc_type))
    if legacy is not None:
        logger.warning(
            "finance.document_adapter.missing layout_version=%s doc_type=%s — "
            "ถอยไปใช้เทมเพลต legacy",
            layout, doc_type,
        )
        # คง layout ที่ขอไว้ในวัตถุที่คืน (ผู้เรียกใช้ตัดสินใจเองว่าจะพิมพ์แบบไหน)
        return replace(legacy, layout_version=layout)

    raise ValueError(
        f"ยังไม่มีเทมเพลตสำหรับเอกสารชนิด '{doc_type}' "
        f"(layout_version={layout}) — เอกสารชนิดนี้เปิดได้แต่ยังพิมพ์ไม่ได้"
    )


def registered_keys() -> list:
    """คีย์ที่ลงทะเบียนแล้ว — เรียงลำดับเพื่อให้ log/เทสต์อ่านง่าย"""
    return sorted(_ADAPTERS.keys())


def _build_context(row: dict) -> dict:
    """Delegate — `FinanceService._document_context` ตัวจริง (ผ่าน MRO เต็ม)

    🔴 import ในฟังก์ชัน: `service.py` → `receipts.py` → ไฟล์นี้ ⇒ import ที่หัวไฟล์
       จะเกิด circular import ตอนบูต
    """
    from .service import FinanceService

    return FinanceService._document_context(row)


def _register_default_adapters() -> None:
    """ลงทะเบียนเอกสารที่มีเทมเพลตจริงในสาขานี้

    ⚠️ ชนิดที่ยังไม่มี partial (RPT) จงใจยังไม่ลงทะเบียน — `resolve_adapter` จะ raise
       ValueError ที่ router แปลงเป็น 400 พร้อมข้อความ ไม่ใช่ปล่อยให้ Jinja พังเป็น 500
    """
    # ── legacy (layout 1) — ไบต์เดิม ทุกกรณี ──────────────────────────────
    for doc_type in (DOC_TYPE_RECEIPT, DOC_TYPE_INVOICE, DOC_TYPE_DEPOSIT, DOC_TYPE_INCOME):
        register(DocumentAdapter(1, doc_type, LEGACY_RECEIPT_BODY, _build_context))
    register(DocumentAdapter(1, DOC_TYPE_PAYMENT_VOUCHER, LEGACY_VOUCHER_BODY, _build_context))

    # ── v2 (layout 2) — พิมพ์จาก snapshot ─────────────────────────────────
    register(DocumentAdapter(2, DOC_TYPE_RECEIPT, V2_RECEIPT_BODY, _build_context))
    # 🧾 DEP v2 เป็นใบแรกที่พิสูจน์ adapter — ไม่มีบิล จึงมี partial ของตัวเอง
    #    (ไม่ใช้ `_receipt_body_v2.html` ที่มีตารางบิล/ยอดคงเหลือซึ่ง DEP ไม่มีความหมาย)
    register(DocumentAdapter(2, DOC_TYPE_DEPOSIT, V2_DEPOSIT_BODY, _build_context))
    register(DocumentAdapter(2, DOC_TYPE_INVOICE, V2_INVOICE_BODY, _build_context))
    register(
        DocumentAdapter(2, DOC_TYPE_ACKNOWLEDGEMENT, V2_ACKNOWLEDGEMENT_BODY, _build_context)
    )
    register(DocumentAdapter(2, DOC_TYPE_PAYMENT_VOUCHER, V2_VOUCHER_BODY, _build_context))
    register(DocumentAdapter(2, DOC_TYPE_CERTIFICATE, V2_CERTIFICATE_BODY, _build_context))
    register(DocumentAdapter(2, DOC_TYPE_INCOME, V2_INCOME_BODY, _build_context))


_register_default_adapters()
