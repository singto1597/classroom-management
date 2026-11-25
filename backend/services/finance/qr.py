"""📱 [FIN-V2 / P2.4] PromptPay QR — EMVCo payload + SVG (pure functions ทั้งไฟล์)

═══════════════════════════════════════════════════════════════════════════════
🎯 ทำไมต้องสร้าง payload เองแทนการให้ครูปริ้น QR จากแอปธนาคาร
═══════════════════════════════════════════════════════════════════════════════
1. **ยอดฝัง (fixed)** ต้องตรงกับบิลที่กำลังเรียกเก็บ — รูปที่ครูทำนอกระบบจะไม่รู้ยอด
2. **เลขพร้อมเพย์ต้องไม่หลุดออก API** ⇒ เก็บ canonical ใน DB, mask ทุกครั้งที่คืน client
3. QR ที่สแกนแล้วโอนผิดบัญชีคือความเสียหายที่แก้ไม่ได้ ⇒ ต้องมี **golden vector**
   ล็อกสตริงไว้ และต้องคำนวณ CRC ให้ถูกตั้งแต่ไบต์แรก

📐 รูปแบบ EMVCo ที่ใช้ (Merchant Presented Mode):
   00 payload format = 01
   01 point of initiation = 11 (open) / 12 (fixed)
   29 merchant account information (PromptPay):
        00 AID = A000000677010111
        01 mobile (0066 + 9 หลัก) · 02 national ID (13) · 03 e-wallet (15)
   53 currency = 764 (THB)
   54 amount (เฉพาะ fixed, ทศนิยม 2 ตำแหน่ง ไม่มี comma)
   58 country = TH
   63 CRC = "6304" + CRC16-CCITT (4 hex ตัวพิมพ์ใหญ่)

⚠️ กฎเหล็ก
   - CRC คำนวณจาก payload **ที่รวม "6304" แล้ว** — ถ้าคำนวณก่อนต่อ tag 63 จะผิดทุกใบ
   - ความยาว TLV เป็น **ไบต์ ASCII** ⇒ ห้ามใส่ข้อความไทยใน payload (`tlv` โยน QrError)
   - เบอร์มือถือต้องเป็น `0066` + 9 หลัก (13 หลัก) — `0812345678` ตรง ๆ สแกนไม่ผ่าน
   - ไฟล์นี้ **ห้าม import asyncpg / ไม่แตะ DB** — เทสต์ pure รันได้โดยไม่ต้องมี Postgres
"""
import io
import re
from decimal import Decimal, InvalidOperation

import segno

# 🏦 AID ของ PromptPay ใน EMVCo (16 ตัวอักษร) — ค่าคงที่ของเครือข่าย ไม่ใช่ความลับ
PROMPTPAY_AID = "A000000677010111"

# 💰 ขอบเขตยอดที่รองรับ (ฟิลด์ tag 54 ของ EMVCo ยาวได้ไม่เกินนี้ในทางปฏิบัติ)
MAX_AMOUNT = Decimal("99999999.99")

VALID_QR_MODES = ("open", "fixed")

_SEPARATORS = re.compile(r"[\s\-]")
_DIGITS_ONLY = re.compile(r"[0-9]+")


class QrError(ValueError):
    """ข้อผิดพลาดของ QR — `code` คงที่ (อังกฤษ) ให้ router/service ตัดสินใจได้

    ข้อความ (`str(e)`) เป็นภาษาไทยเพื่อให้ผู้ใช้เห็นตรง ๆ
    """

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


# ═══════════════════════════════════════════════════════════════════════════
# 1) เลขพร้อมเพย์ — canonical form + mask
# ═══════════════════════════════════════════════════════════════════════════
def normalize_promptpay_id(raw: str) -> str:
    """`081-234-5678` / `0812345678` / `66812345678` → `0066812345678`

    ⚠️ ผลลัพธ์คือค่าที่ **ใช้สร้าง QR** ⇒ DB เก็บค่านี้ และ API ต้อง mask ก่อนคืนเสมอ
    """
    cleaned = _SEPARATORS.sub("", raw or "")
    if not cleaned or not _DIGITS_ONLY.fullmatch(cleaned):
        raise QrError(
            "INVALID_PROMPTPAY_ID",
            "เลขพร้อมเพย์ต้องเป็นตัวเลขล้วน (เบอร์โทร เลขบัตรประชาชน หรือ e-wallet)",
        )

    if len(cleaned) == 10 and cleaned.startswith("0"):
        # 📱 มือถือในประเทศ: 0XXXXXXXXX → 0066 + 9 หลักที่เหลือ
        return "0066" + cleaned[1:]
    if len(cleaned) == 11 and cleaned.startswith("66"):
        # 📱 มือถือที่พิมพ์รหัสประเทศมาแล้ว: 66XXXXXXXXX → 0066 + 9 หลัก
        return "0066" + cleaned[2:]
    if len(cleaned) in (13, 15):
        # 🪪 เลขบัตรประชาชน/ภาษี (13) หรือ e-wallet (15) — เก็บตามเดิม
        return cleaned

    raise QrError(
        "INVALID_PROMPTPAY_ID",
        "ความยาวเลขพร้อมเพย์ไม่ถูกต้อง — ต้องเป็นเบอร์มือถือ 10 หลัก "
        "(หรือขึ้นต้น 66), เลขบัตร 13 หลัก หรือ e-wallet 15 หลัก",
    )


def mask_promptpay_id(canonical: str) -> str:
    """canonical → รูปที่แสดงได้ (ไม่มีเลขเต็ม)

    - `0066…` (13) → `081-XXX-5678`
    - 13 หลัก (บัตร) → `*********2345`
    - 15 หลัก (e-wallet) → `***********2345`
    """
    if len(canonical) == 13 and canonical.startswith("0066"):
        digits = "0" + canonical[4:]  # 10 หลักแบบที่ผู้ใช้คุ้น
        return f"{digits[:3]}-XXX-{digits[-4:]}"
    if len(canonical) == 13:
        return "*" * 9 + canonical[-4:]
    if len(canonical) == 15:
        return "*" * 11 + canonical[-4:]
    raise QrError("INVALID_PROMPTPAY_ID", "เลขพร้อมเพย์ที่เก็บไว้ไม่ถูกรูปแบบ")


def mask_account_number(raw: str) -> str:
    """เลขบัญชีธนาคาร → เก็บ 4 ตัวท้าย ที่เหลือเป็น `*` (≤4 หลัก = `*` ทั้งหมด)"""
    cleaned = _SEPARATORS.sub("", raw or "")
    if not cleaned:
        return ""
    if len(cleaned) <= 4:
        return "*" * len(cleaned)
    return "*" * (len(cleaned) - 4) + cleaned[-4:]


# ═══════════════════════════════════════════════════════════════════════════
# 2) EMVCo — TLV + CRC + payload
# ═══════════════════════════════════════════════════════════════════════════
def crc16_ccitt(data: bytes) -> int:
    """CRC16-CCITT (init 0xFFFF, poly 0x1021) — ตรงกับที่ธนาคารใช้ตรวจ QR

    ⚠️ ไม่ใช่ CRC32 และไม่ใช่ CRC16-XMODEM (init 0) — เลขจะไม่ตรงและ QR สแกนไม่ผ่าน
    """
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def tlv(tag: str, value: str) -> str:
    """EMVCo TLV — ความยาวเป็น **จำนวนไบต์ ASCII** (ฟิลด์นี้ไม่มีข้อความไทย)"""
    try:
        encoded = value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise QrError("INVALID_PAYLOAD", "ข้อมูล QR ต้องเป็น ASCII เท่านั้น") from exc
    if len(encoded) > 99:
        raise QrError("INVALID_PAYLOAD", "ข้อมูล QR ยาวเกินขอบเขตของ EMVCo (99 ไบต์)")
    return f"{tag}{len(encoded):02d}{value}"


def _format_amount(amount) -> str:
    """ยอดเงิน → `"1250.50"` (ตรวจ ≤2 ตำแหน่ง, > 0, ไม่เกิน MAX_AMOUNT)

    รับ `Decimal` เป็นหลัก; ค่าอื่นแปลงผ่าน `str()` เพื่อไม่ให้ float เพี้ยน
    """
    try:
        value = amount if isinstance(amount, Decimal) else Decimal(str(amount))
    except (InvalidOperation, ValueError) as exc:
        raise QrError("INVALID_AMOUNT", "ยอดเงินไม่ถูกต้อง") from exc
    if not value.is_finite():
        raise QrError("INVALID_AMOUNT", "ยอดเงินไม่ถูกต้อง")

    quantized = value.quantize(Decimal("0.01"))
    if quantized != value:
        raise QrError("INVALID_AMOUNT", "ยอดเงินมีทศนิยมเกิน 2 ตำแหน่ง")
    if quantized <= 0:
        raise QrError("INVALID_AMOUNT", "ยอดเงินต้องมากกว่า 0")
    if quantized > MAX_AMOUNT:
        raise QrError("INVALID_AMOUNT", f"ยอดเงินต้องไม่เกิน {MAX_AMOUNT:,.2f} บาท")
    return format(quantized, ".2f")


def build_promptpay_payload(
    *, promptpay_id: str, qr_mode: str, amount: Decimal | None
) -> str:
    """สร้างสตริง EMVCo สำหรับ PromptPay (open = ให้ผู้จ่ายพิมพ์ยอดเอง)

    Raises:
        QrError: `INVALID_PROMPTPAY_ID` · `INVALID_AMOUNT` · `QR_MODE_MISMATCH`
    """
    canonical = normalize_promptpay_id(promptpay_id)

    if qr_mode not in VALID_QR_MODES:
        raise QrError("QR_MODE_MISMATCH", "รูปแบบ QR ต้องเป็น open หรือ fixed")
    if qr_mode == "open" and amount is not None:
        raise QrError("QR_MODE_MISMATCH", "QR แบบไม่ฝังยอดต้องไม่ระบุยอดเงิน")
    if qr_mode == "fixed" and amount is None:
        raise QrError("QR_MODE_MISMATCH", "QR แบบฝังยอดต้องระบุยอดเงิน")

    if len(canonical) == 13 and canonical.startswith("0066"):
        account_tag = "01"  # 📱 เบอร์มือถือ
    elif len(canonical) == 13:
        account_tag = "02"  # 🪪 เลขบัตรประชาชน/ภาษี
    else:
        account_tag = "03"  # 👛 e-wallet 15 หลัก

    merchant = tlv("00", PROMPTPAY_AID) + tlv(account_tag, canonical)

    parts = [
        tlv("00", "01"),            # payload format indicator
        tlv("01", "12" if qr_mode == "fixed" else "11"),
        tlv("29", merchant),        # merchant account info — PromptPay
        tlv("53", "764"),           # currency THB
    ]
    if qr_mode == "fixed":
        parts.append(tlv("54", _format_amount(amount)))
    parts.append(tlv("58", "TH"))

    # 🔴 CRC คำนวณจากสตริงที่ลงท้ายด้วย "6304" แล้ว (ยังไม่มี hex ของ CRC เอง)
    with_crc_tag = "".join(parts) + "6304"
    checksum = crc16_ccitt(with_crc_tag.encode("ascii"))
    return with_crc_tag + f"{checksum:04X}"


def render_qr_svg(payload: str) -> str:
    """payload → SVG (segno, pure Python — ไม่ต้องมี Pillow)

    ⚠️ รับเฉพาะ payload ที่สร้างจาก `build_promptpay_payload` เท่านั้น —
       ห้ามให้ client ส่ง payload มาวาด (QR phishing)
    """
    # ⚠️ `make_qr` ไม่รับ `micro` (มีเฉพาะ `segno.make`) — micro QR ไม่รองรับโดยแอปธนาคาร
    #    อยู่แล้ว และ `make_qr` บังคับ micro=False ให้เอง
    qr = segno.make_qr(payload, error="m")
    buf = io.BytesIO()
    qr.save(buf, kind="svg", xmldecl=False, border=2, scale=4)
    return buf.getvalue().decode("utf-8")
