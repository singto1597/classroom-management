"""Name utilities — English-primary identity + Thai display + NFC normalization.

เหตุผล (ดู docs/skills.md + งาน refactor นี้):
- ระบบยึดชื่อภาษาอังกฤษเป็น "กุญแจตัวตน" (identity/dedupe/search) เพราะชื่อไทยมีปัญหา
  Unicode composition: สระ อำ เขียนได้ 2 แบบคือ อำ (U+0E33 precomposed) กับ อา+นิคหิต
  (U+0E32 + U+0E4D decomposed) — เป็น codepoint คนละตัวแต่ความหมายเดียวกัน → match กันไม่เจอ
- NFC normalization ทำให้สองแบบนั้นกลายเป็น "ตัวเดียวกัน" ก่อนเก็บ/ค้น
- ชื่อไทยเป็นแค่ "ของแสดงผล" — ถ้ามีให้ใช้ไทยก่อน แล้วค่อยใช้ชื่ออังกฤษแทน
"""
from __future__ import annotations

import unicodedata
from typing import Optional, Tuple

# 🚨 สระอำ มี 3 รูปแบบที่ "ความหมายเดียวกัน" แต่เป็น codepoint คนละตัว:
#   - อำ (precomposed): U+0E33
#   - อาํ : U+0E32 (สระอา) + U+0E4D (นิคหิต)
#   - อํา : U+0E4D (นิคหิต) + U+0E32 (สระอา)   ← ลำดับนี้คือ NFD ของ U+0E33
# ⚠️ Python `unicodedata.normalize("NFC", ...)` ยุบ 3 รูปแบบนี้ให้เป็นตัวเดียวกันไม่ได้
# (U+0E33 ไม่มี canonical decomposition ใน Unicode เวอร์ชันที่ Python ใช้) → ต้อง map เอง
_THAI_SARA_AM = "ำ"
_THAI_SARA_AA = "า"
_THAI_NIKHAHIT = "ํ"


def normalize_nfc(value: Optional[str]) -> str:
    """Normalize ชื่อไทยให้เป็น "รูปแบบเดียว" ก่อนเก็บ/ค้น.

    - NFC (best effort สำหรับ case อื่น) + strip
    - 🌟 collapse สระอำ 3 รูปแบบ → U+0E33 เดียว (กัน match กันไม่เจอ)
    """
    if value is None:
        return ""
    s = unicodedata.normalize("NFC", str(value)).strip()
    s = s.replace(_THAI_SARA_AA + _THAI_NIKHAHIT, _THAI_SARA_AM)
    s = s.replace(_THAI_NIKHAHIT + _THAI_SARA_AA, _THAI_SARA_AM)
    return s


def normalize_en(value: Optional[str]) -> str:
    """Normalize ชื่ออังกฤษสำหรับ identity: NFC + strip + casefold (ไม่ไวตัวพิมพ์)."""
    if value is None:
        return ""
    return unicodedata.normalize("NFC", str(value)).strip().casefold()


def identity_pair(
    first_en: Optional[str],
    last_en: Optional[str],
    first_th: Optional[str],
    last_th: Optional[str],
) -> Tuple[str, str]:
    """คู่ key สำหรับ dedupe/identity — ชอบชื่ออังกฤษก่อน (ถ้ามี) ไม่งั้น fallback เป็นไทย NFC.

    ใช้ใน add_student / bulk_add_students เพื่อ "คนชื่อเดียวกัน = user คนเดียวกัน" โดยที่
    ชื่ออังกฤษเป็นตัวตัดสินหลัก (ตามนโยบาย English-primary)."""
    ef = normalize_en(first_en)
    el = normalize_en(last_en)
    if ef or el:
        return (ef, el)
    return (normalize_nfc(first_th).replace(" ", "").casefold(), normalize_nfc(last_th).replace(" ", "").casefold())


def display_name(
    first_th: Optional[str],
    last_th: Optional[str],
    first_en: Optional[str] = None,
    last_en: Optional[str] = None,
) -> str:
    """ชื่อสำหรับแสดงผล: ชื่อไทยก่อน (ถ้ามี) แล้วค่อยชื่ออังกฤษ.

    คืน string ว่างถ้าไม่มีชื่อเลย — caller เป็นคนจัดการ fallback (เช่น nickname)."""
    th = f"{(first_th or '').strip()} {(last_th or '').strip()}".strip()
    if th:
        return th
    en = f"{(first_en or '').strip()} {(last_en or '').strip()}".strip()
    return en
