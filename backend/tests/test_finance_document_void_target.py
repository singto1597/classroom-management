"""🎯 `resolve_void_target()` — ตัดสินปลายทางยกเลิกของเอกสารแต่ละชนิด (pure)

ล็อกกติกาที่ frontend พึ่งพา (2026-11-27):
- INV → invoice(id)
- REC/DEP → payment_event ก่อน แล้วค่อย legacy_transaction
- PV → expense_voucher(voucher_id) แล้วค่อย legacy
- CERT → expense_voucher เท่านั้น (ห้าม fallback legacy)
- INC → income_batch(batch_id) แล้วค่อย legacy
- ACK → acknowledgement(receipt_no)
- RPT → monthly_report(id) เฉพาะ draft/final
- voided/deleted → None ทุกชนิด
"""
import pytest

from services.finance.constants import (
    DOC_TYPE_ACKNOWLEDGEMENT,
    DOC_TYPE_CERTIFICATE,
    DOC_TYPE_DEPOSIT,
    DOC_TYPE_INCOME,
    DOC_TYPE_INVOICE,
    DOC_TYPE_MONTHLY_REPORT,
    DOC_TYPE_PAYMENT_VOUCHER,
    DOC_TYPE_RECEIPT,
)
from services.finance.document_void_target import resolve_void_target


def _resolve(doc_type: str, **over):
    kwargs = {
        "doc_type": doc_type,
        "doc_id": 10,
        "doc_no": f"{doc_type.upper()}-2569-0010",
        "status": "active",
    }
    kwargs.update(over)
    return resolve_void_target(**kwargs)


def test_invoice_voids_itself():
    assert _resolve(DOC_TYPE_INVOICE) == {
        "method": "invoice", "id": 10, "receipt_no": None,
    }


@pytest.mark.parametrize("doc_type", [DOC_TYPE_RECEIPT, DOC_TYPE_DEPOSIT])
def test_receipt_and_deposit_prefer_payment_event_over_legacy(doc_type):
    """event คือเหตุการณ์รับเงินจริง — ต้องมาก่อนแถว legacy เสมอ"""
    assert _resolve(
        doc_type, payment_event_id=77, legacy_transaction_id=88,
    ) == {"method": "payment_event", "id": 77, "receipt_no": None}


@pytest.mark.parametrize("doc_type", [DOC_TYPE_RECEIPT, DOC_TYPE_DEPOSIT])
def test_receipt_and_deposit_fall_back_to_legacy(doc_type):
    assert _resolve(doc_type, legacy_transaction_id=88) == {
        "method": "legacy_transaction", "id": 88, "receipt_no": None,
    }


@pytest.mark.parametrize("doc_type", [DOC_TYPE_RECEIPT, DOC_TYPE_DEPOSIT])
def test_receipt_without_source_is_not_cancellable(doc_type):
    assert _resolve(doc_type) is None


def test_payment_voucher_uses_voucher_id_then_legacy():
    assert _resolve(DOC_TYPE_PAYMENT_VOUCHER, voucher_id=42) == {
        "method": "expense_voucher", "id": 42, "receipt_no": None,
    }
    assert _resolve(DOC_TYPE_PAYMENT_VOUCHER, legacy_transaction_id=9) == {
        "method": "legacy_transaction", "id": 9, "receipt_no": None,
    }
    assert _resolve(DOC_TYPE_PAYMENT_VOUCHER) is None


def test_certificate_only_voids_with_voucher_never_legacy():
    assert _resolve(DOC_TYPE_CERTIFICATE, voucher_id=42) == {
        "method": "expense_voucher", "id": 42, "receipt_no": None,
    }
    # 🔴 CERT ไม่มีเส้นทางยกเลิกเดี่ยว — legacy ไม่ใช่ fallback ที่ถูกต้อง
    assert _resolve(DOC_TYPE_CERTIFICATE, legacy_transaction_id=9) is None
    assert _resolve(DOC_TYPE_CERTIFICATE) is None


def test_income_uses_batch_id_then_legacy():
    assert _resolve(DOC_TYPE_INCOME, batch_id=7) == {
        "method": "income_batch", "id": 7, "receipt_no": None,
    }
    assert _resolve(DOC_TYPE_INCOME, legacy_transaction_id=9) == {
        "method": "legacy_transaction", "id": 9, "receipt_no": None,
    }
    assert _resolve(DOC_TYPE_INCOME) is None


def test_acknowledgement_uses_receipt_no():
    assert _resolve(
        DOC_TYPE_ACKNOWLEDGEMENT, doc_no="ACK-2569-0003",
    ) == {"method": "acknowledgement", "id": None, "receipt_no": "ACK-2569-0003"}
    assert _resolve(DOC_TYPE_ACKNOWLEDGEMENT, doc_no=None) is None


@pytest.mark.parametrize("status", ["draft", "final"])
def test_monthly_report_voidable_until_voided(status):
    assert _resolve(DOC_TYPE_MONTHLY_REPORT, status=status) == {
        "method": "monthly_report", "id": 10, "receipt_no": None,
    }


def test_monthly_report_voided_is_not_cancellable():
    assert _resolve(DOC_TYPE_MONTHLY_REPORT, status="voided") is None


@pytest.mark.parametrize(
    "doc_type",
    [
        DOC_TYPE_INVOICE,
        DOC_TYPE_RECEIPT,
        DOC_TYPE_PAYMENT_VOUCHER,
        DOC_TYPE_CERTIFICATE,
        DOC_TYPE_INCOME,
        DOC_TYPE_ACKNOWLEDGEMENT,
    ],
)
def test_voided_or_deleted_documents_are_not_cancellable(doc_type):
    assert _resolve(doc_type, status="voided", voucher_id=1, batch_id=1,
                    legacy_transaction_id=1) is None
    assert _resolve(doc_type, deleted=True, voucher_id=1, batch_id=1,
                    legacy_transaction_id=1) is None


def test_unknown_doc_type_returns_none():
    assert _resolve("mystery") is None
