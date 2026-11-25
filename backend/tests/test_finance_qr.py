"""📱 [FIN-V2 / P2.4] PromptPay QR — pure functions (ไม่ต้องใช้ DB)

═══════════════════════════════════════════════════════════════════════════════
🎯 ทำไมต้องมี golden vector
═══════════════════════════════════════════════════════════════════════════════
QR ที่สแกนแล้วโอนเข้าบัญชีผิดหรือยอดผิดคือความเสียหายที่ย้อนกลับไม่ได้ และ
"ดูเหมือนถูก" จากตาของคนอ่าน — ตัวตรวจเดียวที่เชื่อได้คือ **สตริงที่ธนาคารรู้จัก**
ชุดนี้จึงล็อก:

1. CRC16-CCITT (init 0xFFFF / poly 0x1021) ตรงค่า `0x29B1` ของ `"123456789"`
2. payload open/fixed ตรงไบต์-for-ไบต์กับ vector ที่คำนวณจากสเปก EMVCo
3. CRC เป็น hex 4 ตัว **พิมพ์ใหญ่** และคำนวณรวม `"6304"` (กับดักที่พังเงียบ)
4. รูปแบบเบอร์ทุกรูปที่ผู้ใช้พิมพ์ → canonical 13 หลัก `0066…` เดียวกัน
5. mask ไม่มีเลขเต็มหลุด และยอดเงินไม่มี comma/ทศนิยมเกิน 2
"""
from decimal import Decimal

import pytest

from services.finance.qr import (
    PROMPTPAY_AID, QrError, build_promptpay_payload, crc16_ccitt,
    mask_account_number, mask_promptpay_id, normalize_promptpay_id, render_qr_svg,
)

OPEN_VECTOR = (
    "00020101021129370016A00000067701011101130066812345678"
    "53037645802TH6304823E"
)
FIXED_100_VECTOR = (
    "00020101021229370016A00000067701011101130066812345678"
    "53037645406100.005802TH6304F142"
)
FIXED_1250_50_VECTOR = (
    "00020101021229370016A00000067701011101130066812345678"
    "530376454071250.505802TH6304ABEB"
)


# ═════════════════════════════════════════════════════════ 1. CRC
def test_crc16_matches_known_vector():
    """`"123456789"` → 0x29B1 (ค่าอ้างอิงมาตรฐาน CRC16-CCITT/FALSE)"""
    assert crc16_ccitt(b"123456789") == 0x29B1


def test_crc_is_last_four_uppercase():
    """CRC 4 ตัวพิมพ์ใหญ่ ไม่มี `0x` และคำนวณจากสตริงที่ลงท้าย `6304` แล้ว"""
    payload = build_promptpay_payload(
        promptpay_id="0066812345678", qr_mode="open", amount=None,
    )
    assert payload[-8:-4] == "6304"
    assert payload[-4:] == payload[-4:].upper()
    assert len(payload[-4:]) == 4
    assert int(payload[-4:], 16) == crc16_ccitt(payload[:-4].encode("ascii"))


# ═════════════════════════════════════════════════════════ 2. golden payloads
def test_open_payload_golden():
    assert build_promptpay_payload(
        promptpay_id="0066812345678", qr_mode="open", amount=None,
    ) == OPEN_VECTOR


def test_fixed_payload_100_golden():
    assert build_promptpay_payload(
        promptpay_id="0066812345678", qr_mode="fixed", amount=Decimal("100.00"),
    ) == FIXED_100_VECTOR


def test_fixed_payload_1250_50_golden():
    assert build_promptpay_payload(
        promptpay_id="0066812345678", qr_mode="fixed", amount=Decimal("1250.50"),
    ) == FIXED_1250_50_VECTOR


def test_payload_uses_promptpay_aid_tag_29():
    payload = build_promptpay_payload(
        promptpay_id="0066812345678", qr_mode="open", amount=None,
    )
    assert PROMPTPAY_AID in payload
    assert payload.startswith("0002010102112937")


# ═════════════════════════════════════════════════════════ 3. normalize
@pytest.mark.parametrize(
    "raw",
    ["081-234-5678", "0812345678", "66812345678", "66 812 345 678", "0066812345678"],
)
def test_normalize_phone_forms(raw):
    assert normalize_promptpay_id(raw) == "0066812345678"


def test_normalize_national_id_and_ewallet():
    national = "1234567890123"
    ewallet = "123456789012345"
    assert normalize_promptpay_id(national) == national
    assert normalize_promptpay_id(ewallet) == ewallet
    # tag เลขบัตรคือ 02 (13) · e-wallet 15 หลักคือ 03
    assert f"0213{national}" in build_promptpay_payload(
        promptpay_id=national, qr_mode="open", amount=None,
    )
    assert f"0315{ewallet}" in build_promptpay_payload(
        promptpay_id=ewallet, qr_mode="open", amount=None,
    )


@pytest.mark.parametrize("raw", ["", "12", "12345", "08123abc78", "0" * 12])
def test_normalize_rejects_short_or_alpha(raw):
    with pytest.raises(QrError) as exc:
        normalize_promptpay_id(raw)
    assert exc.value.code == "INVALID_PROMPTPAY_ID"


# ═════════════════════════════════════════════════════════ 4. mask
def test_mask_phone_and_national_id():
    phone = mask_promptpay_id("0066812345678")
    assert phone == "081-XXX-5678"
    assert "12345678" not in phone

    national = mask_promptpay_id("1234567890123")
    assert national == "*********0123"
    assert "123456789" not in national

    ewallet = mask_promptpay_id("123456789012345")
    assert ewallet == "***********2345"
    assert "12345678901" not in ewallet

    assert mask_account_number("1234567890") == "******7890"
    assert mask_account_number("1234") == "****"
    assert mask_account_number("123-456-7890") == "******7890"


# ═════════════════════════════════════════════════════════ 5. amount / mode guards
def test_open_with_amount_raises():
    with pytest.raises(QrError) as exc:
        build_promptpay_payload(
            promptpay_id="0066812345678", qr_mode="open", amount=Decimal("100.00"),
        )
    assert exc.value.code == "QR_MODE_MISMATCH"


def test_fixed_without_amount_raises():
    with pytest.raises(QrError) as exc:
        build_promptpay_payload(
            promptpay_id="0066812345678", qr_mode="fixed", amount=None,
        )
    assert exc.value.code == "QR_MODE_MISMATCH"


@pytest.mark.parametrize(
    "amount", [Decimal("100.001"), Decimal("0"), Decimal("-5"), Decimal("100000000.00")],
)
def test_amount_too_many_decimals_raises(amount):
    with pytest.raises(QrError) as exc:
        build_promptpay_payload(
            promptpay_id="0066812345678", qr_mode="fixed", amount=amount,
        )
    assert exc.value.code in ("INVALID_AMOUNT",)


def test_amount_is_formatted_two_decimals_without_comma():
    payload = build_promptpay_payload(
        promptpay_id="0066812345678", qr_mode="fixed", amount=Decimal("100.5"),
    )
    assert "5406100.50" in payload
    assert "," not in payload


# ═════════════════════════════════════════════════════════ 6. SVG
def test_render_qr_svg_starts_with_svg_and_has_no_script():
    """segno คืน SVG จริง และต้องไม่มี `<script>` (ฝังได้ปลอดภัยบนใบพิมพ์)"""
    svg = render_qr_svg(OPEN_VECTOR)
    assert svg.lstrip().startswith("<svg")
    assert "<script" not in svg.lower()
