"""[F3] แปลงจำนวนเงินเป็นตัวอักษรไทย ("หนึ่งพันบาทถ้วน" / "...ห้าสิบสตางค์")

แยกเป็นโมดูลเดี่ยว (ไม่ใช่ helper ปนกับเวลา) เพราะ:
- เป็น **pure function** ล้วน ไม่แตะ DB/เวลา → เทสต์ได้โดยไม่ต้องมีฐานข้อมูล
- มีตารางคำอ่านของตัวเอง การไปอยู่รวมกับ helpers.py ที่เป็นเรื่อง timezone จะทำให้อ่านยาก

📌 เกติกาที่ล็อกตามมาตรฐาน BAHTTEXT ของไทย (สิ่งที่นักบัญชี/เหรัญญิกคาดหวัง):
   1. ยอดไม่ถึง 1 บาท (มีแต่เศษสตางค์) → อ่าน **เฉพาะสตางค์ ไม่มีคำว่า "บาท"**
      0.50 → "ห้าสิบสตางค์"   (ไม่ใช่ "ศูนย์บาทห้าสิบสตางค์")
   2. ไม่มีเศษสตางค์ → ลงท้าย "ถ้วน":  100 → "หนึ่งร้อยบาทถ้วน"
   3. ศูนย์ → "ศูนย์บาทถ้วน"
   4. หลักหน่วยเป็น 1 และยังมีหลักสูงกว่าอยู่ → "เอ็ด" (11 → "สิบเอ็ด", 101 → "หนึ่งร้อยเอ็ด")
      แต่ถ้าเลขนั้นมีหลักเดียว → "หนึ่ง" (1 → "หนึ่ง")
   5. หลักสิบเป็น 1 → "สิบ" (ไม่ใช่ "หนึ่งสิบ"); เป็น 2 → "ยี่สิบ"
"""
from decimal import Decimal, ROUND_HALF_UP
from typing import Union

_THAI_DIGITS = ["ศูนย์", "หนึ่ง", "สอง", "สาม", "สี่", "ห้า", "หก", "เจ็ด", "แปด", "เก้า"]
# ตำแหน่งภายในกลุ่ม 6 หลัก (หลักหน่วย → หลักแสน); หลักล้านจัดการแยกด้านล่าง
_THAI_POSITIONS = ["", "สิบ", "ร้อย", "พัน", "หมื่น", "แสน"]

# ใช้ Decimal เท่านั้น ห้าม float — 0.1 + 0.2 แบบ float ทำให้เศษสตางค์เพี้ยนได้
# (กฎ backend: NUMERIC/DECIMAL ต้องระวังเรื่อง float)
_CENT = Decimal("0.01")
_MILLION = 1_000_000


def _read_group(n: int, has_higher_above: bool = False) -> str:
    """อ่านจำนวนเต็ม 0..999,999 เป็นคำอ่านไทย (ไม่รวมคำว่า 'ล้าน'); 0 → สตริงว่าง

    `has_higher_above` = มีหลักสูงกว่ารอบนอกกลุ่มนี้อยู่ (เช่นมี "ล้าน" นำหน้า) —
    จำเป็นเพราะกฎ "เอ็ด" พิจารณา **หลักหน่วยของจำนวนทั้งหมด** ไม่ใช่ภายในกลุ่ม:
    1,000,001 ต้องอ่าน "หนึ่งล้านเอ็ด" ไม่ใช่ "หนึ่งล้านหนึ่ง"
    (และ 701 ก็ยังเป็น "เจ็ดร้อยเอ็ด" เพราะในกลุ่มเดียวกันมี 7 อยู่หน้าแล้ว)
    """
    if n <= 0:
        return ""
    has_higher = has_higher_above or n >= 10  # ใช้ตัดสินกฎ "เอ็ด" ของหลักหน่วย
    parts = []
    pos = 0
    while n > 0:
        digit = n % 10
        if digit:
            if pos == 0:
                # หลักหน่วย: 1 → "เอ็ด" เมื่อยังมีหลักสูงกว่า, ไม่งั้น "หนึ่ง"
                parts.append("เอ็ด" if digit == 1 and has_higher else _THAI_DIGITS[digit])
            elif pos == 1:
                # หลักสิบ: 1 → "สิบ", 2 → "ยี่สิบ", อื่น ๆ → digit + "สิบ"
                if digit == 1:
                    parts.append("สิบ")
                elif digit == 2:
                    parts.append("ยี่สิบ")
                else:
                    parts.append(_THAI_DIGITS[digit] + "สิบ")
            else:
                parts.append(_THAI_DIGITS[digit] + _THAI_POSITIONS[pos])
        n //= 10
        pos += 1
    return "".join(reversed(parts))


def _read_int(n: int, has_higher_above: bool = False) -> str:
    """อ่านจำนวนเต็มบวก/ศูนย์เป็นคำอ่านไทย รองรับหลักล้านซ้อนกัน (1,000,000,000 ก็ได้)"""
    if n == 0:
        return _THAI_DIGITS[0]
    if n < _MILLION:
        return _read_group(n, has_higher_above)
    # เรียกซ้ำฝั่ง "ล้าน" เพราะไทยอ่าน "หนึ่งพันล้าน" (ไม่ใช่แยกส่วนมาอ่าน "พัน" + "ล้าน")
    # 🎯 เศษที่เหลือ "มีหลักสูงกว่านำหน้าแล้ว" เสมอ (ตัวล้านเอง) → ส่ง flag ต่อ
    #    เพื่อให้ 1,000,001 ออกมาเป็น "หนึ่งล้านเอ็ด" ตามไวยากรณ์ไทย
    return _read_int(n // _MILLION) + "ล้าน" + _read_group(n % _MILLION, has_higher_above=True)


def baht_text(amount: Union[int, float, str, Decimal]) -> str:
    """แปลงจำนวนเงินเป็นตัวอักษรไทย (มาตรฐาน BAHTTEXT)

    ปัดเป็นทศนิยม 2 ตำแหน่งแบบ ROUND_HALF_UP ก่อนอ่านเสมอ — ยอดที่เก็บใน DB เป็น
    DECIMAL(15,2) อยู่แล้ว จึงไม่ควรมีเศษเกิน แต่กันไว้เพื่อไม่ให้ "บาท" กับ "สตางค์"
    ที่พิมพ์บนใบเสร็จไม่ตรงกับตัวเลขที่โชว์ข้าง ๆ

    >>> baht_text(1000)
    'หนึ่งพันบาทถ้วน'
    >>> baht_text(Decimal("1234.50"))
    'หนึ่งพันสองร้อยสามสิบสี่บาทห้าสิบสตางค์'
    >>> baht_text(Decimal("0.50"))
    'ห้าสิบสตางค์'
    """
    # str() ก่อนสร้าง Decimal เสมอ: Decimal(0.1) จะได้ 0.1000000000000000055511...
    value = amount if isinstance(amount, Decimal) else Decimal(str(amount))
    if not value.is_finite():
        raise ValueError(f"จำนวนเงินต้องเป็นตัวเลขจำกัด: {amount!r}")

    negative = value < 0
    # คิดเป็น "สตางค์" (จำนวนเต็ม) แล้วค่อยแยก — เลี่ยงการลบ Decimal ที่อาจเหลือเศษทศนิยม
    cents = int((abs(value)).quantize(_CENT, rounding=ROUND_HALF_UP) * 100)
    baht, satang = divmod(cents, 100)

    if baht == 0 and satang == 0:
        text = "ศูนย์บาทถ้วน"
    elif baht == 0:
        # กฎ BAHTTEXT ข้อ 1: ไม่ถึง 1 บาท อ่านเฉพาะสตางค์
        text = f"{_read_int(satang)}สตางค์"
    elif satang == 0:
        text = f"{_read_int(baht)}บาทถ้วน"
    else:
        text = f"{_read_int(baht)}บาท{_read_int(satang)}สตางค์"

    # ยอดติดลบไม่ควรเกิดบนใบเสร็จ (DDL มี CHECK amount > 0) แต่ถ้าเกิด ต้องไม่เงียบ ๆ ทิ้งเครื่องหมาย
    return f"ลบ{text}" if negative else text
