"""บริบทของ HTTP request ปัจจุบัน (IP จริง / User-Agent / endpoint) สำหรับ audit_logs

═══════════════════════════════════════════════════════════════════════════════
ทำไมต้องมีไฟล์นี้ (P6.1)
═══════════════════════════════════════════════════════════════════════════════
ก่อนหน้านี้ `audit_logs` มีคอลัมน์ `ip_address` / `user_agent` ครบ แต่ **ไม่มีโค้ด
เขียนลงไปเลยแม้แต่จุดเดียว** (`grep ip_address backend/` เจอแค่ที่นิยามใน logger.py)
⇒ เวลาสืบเหตุ "ใครกดลบนักเรียนคนนี้" เราได้แค่ `actor_identifier` ที่เป็น `user_id:N`
ซึ่งแปลได้ว่า *บัญชีไหน* แต่ไม่ได้บอกว่า *มาจากเครื่องไหน/เบราว์เซอร์อะไร*

ทางเลือกที่ง่ายที่สุดคือเพิ่มพารามิเตอร์ `ip_address=...` ให้ผู้เรียกทุกจุด
แต่ผู้เรียกมี 277 จุดใน 40+ ไฟล์ และทุกจุดใหม่ในอนาคตจะลืมอีก ⇒ เลือกใช้
`contextvars.ContextVar` ที่ middleware ตั้งค่าครั้งเดียวต่อ request แล้วให้
`AuditLogger.log()` อ่าน fallback เอง — ผู้เรียกไม่ต้องแก้สักบรรทัด
(ค่าที่ผู้เรียกส่งมาเองยังชนะเสมอ: `ip_address or ctx.ip_address`)

⚠️ contextvar ถูกออกแบบมาสำหรับ async โดยเฉพาะ — แต่ละ request มี context
ของตัวเอง ⇒ สองคำขอพร้อมกันไม่เห็น IP กัน (ต่างจาก global module variable)
ค่าจะถูก reset ใน `finally` ของ middleware เสมอ แม้ handler โยน exception

═══════════════════════════════════════════════════════════════════════════════
IP จริงมาจากไหน — และทำไมค่าเริ่มต้นคือ "ไม่เชื่อ header เลย"
═══════════════════════════════════════════════════════════════════════════════
topology ตอนนี้: client → Cloudflare (Flexible SSL, พอร์ต 80) → Traefik → uvicorn

`request.client.host` จะได้ **IP ของ Traefik** (ทุกคนเป็น IP เดียวกัน) ไม่ใช่ของ client
⇒ ต้องอ่านจาก header ที่ proxy เติมให้ แต่ header เหล่านั้น **client ปลอมได้** ถ้าคำขอ
ไม่ผ่าน proxy จริง (เช่นยิงตรงเข้า IP เครื่อง :8000 หรือ Traefik ที่เปิดพอร์ตสาธารณะ)

จึงต้องประกาศ "เชื่อ proxy กี่ชั้น" (`TRUSTED_PROXY_HOPS`) ด้วยความเต็มใจ:
  • 0 (ค่าเริ่มต้น) = ไม่มี proxy ที่เชื่อถือ ⇒ **ละเลย header ทั้งหมด** ใช้ TCP peer
    → ปลอดภัยที่สุดเมื่อไม่รู้ topology / ตอนรันเทสต์ / ตอน dev
  • 2 = อยู่หลัง Cloudflare + Traefik ⇒ ใช้ `CF-Connecting-IP` (Cloudflare เขียนทับ
    ค่าที่ client ส่งมาเสมอ) ถ้าไม่มีค่อยคำนวณจาก `X-Forwarded-For`
  • 1 = อยู่หลัง proxy ตัวเดียว ⇒ ใช้เฉพาะ `X-Forwarded-For` ตัวขวาสุด
    (ไม่ใช้ `CF-Connecting-IP` เพราะถ้า Cloudflare ไม่อยู่ในสายจริง header นั้น
    ก็เป็นค่าที่ client พิมพ์มาเองได้ทั้งหมด — Traefik ไม่ได้ล้าง header นี้)

🔴 กฎที่ห้ามละเมิด: **ค่าเริ่มต้นต้องเป็น 0 เสมอ** ถ้าตั้งสูงเกินจริงแล้วมีคนยิงตรงมา
audit_logs จะเต็มไปด้วย IP ปลอมที่ดูน่าเชื่อถือ — แย่กว่าไม่มี IP เลยเพราะสืบผิดทาง
"""

from __future__ import annotations

import ipaddress
import re
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Mapping, Optional

# User-Agent ยาวได้ถึง 8 KB ตามสเปก — แต่ audit ไม่ได้ต้องการรายละเอียดขนาดนั้น
# และคอลัมน์เป็น TEXT ที่ผู้ใช้ควบคุม ⇒ ตัดที่ 512 ตัวอักษร (กันแถวบวมจาก bot สแปม)
MAX_USER_AGENT_LEN = 512

# segment ของ path ที่ยาวเกินนี้ถือเป็นโทเคน (signed link / capability URL) ไม่ใช่ path จริง
# 📌 path ในระบบนี้ยาวสุดคือ `academic-periods` (16) — ตั้ง 20 จึงไม่แตะ path จริงเลย
# ส่วนเลข ID (`123`) และเลขใบเสร็จ (`REC-2569-0042`) สั้นกว่านี้มาก
_TOKEN_SEGMENT_MIN_LEN = 20


@dataclass(frozen=True)
class RequestAuditContext:
    """snapshot ของคำขอหนึ่งครั้ง — immutable เพื่อให้ส่งข้าม task ได้อย่างปลอดภัย"""

    ip_address: Optional[str]
    user_agent: Optional[str]
    endpoint: Optional[str]


_current: ContextVar[Optional[RequestAuditContext]] = ContextVar(
    "classroom_request_audit", default=None
)


def set_request_audit_context(ctx: Optional[RequestAuditContext]) -> Token:
    return _current.set(ctx)


def reset_request_audit_context(token: Token) -> None:
    _current.reset(token)


def current_request_audit_context() -> Optional[RequestAuditContext]:
    """บริบทของคำขอที่กำลังทำงานอยู่ (None = เรียกนอก request เช่น worker/cron)"""
    return _current.get()


def _normalize_ip(raw: Optional[str]) -> Optional[str]:
    """คืน IP รูปแบบบัญญัติ หรือ None ถ้าอ่านไม่ออก

    ใช้ `ipaddress` เป็นด่านเดียว เพราะ header เป็นข้อความอิสระ: ถ้าปล่อยผ่าน
    จะได้ค่าแปลก ๆ อย่าง `"unknown"`, `"1.2.3.4:443"` หรือสคริปต์ฝังใน log
    """
    if not raw:
        return None
    candidate = raw.strip().strip('"')
    if not candidate:
        return None
    # รูปแบบ `[::1]:443` (IPv6+port) — Traefik บาง config เติมพอร์ตมาด้วย
    if candidate.startswith("[") and "]" in candidate:
        candidate = candidate[1 : candidate.index("]")]
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


def _header(headers: Mapping[str, str], name: str) -> Optional[str]:
    """อ่าน header แบบไม่สนตัวพิมพ์ — รับได้ทั้ง Starlette Headers และ dict เปล่า ๆ"""
    value = headers.get(name)
    if value is not None:
        return value
    lowered = name.lower()
    for key, val in headers.items():
        if key.lower() == lowered:
            return val
    return None


def resolve_client_ip(
    peer_ip: Optional[str],
    headers: Mapping[str, str],
    trusted_hops: int,
) -> Optional[str]:
    """IP ของผู้ใช้จริง — หรือ None ถ้าหาไม่ได้อย่างน่าเชื่อถือ

    :param peer_ip: `request.client.host` (TCP peer = Traefik ตอนอยู่บน production)
    :param headers: header ของคำขอ
    :param trusted_hops: จำนวน proxy ที่เชื่อถือได้หน้า service นี้ (0 = ไม่เชื่อ header)
    """
    peer = _normalize_ip(peer_ip)
    if trusted_hops <= 0:
        return peer

    # Cloudflare อยู่หน้าสุดของสาย ⇒ ใช้ได้เฉพาะเมื่อประกาศว่าเชื่อ ≥ 2 ชั้น
    # (Cloudflare + Traefik) — ดูคำอธิบายหัวไฟล์
    if trusted_hops >= 2:
        cf_ip = _normalize_ip(_header(headers, "cf-connecting-ip"))
        if cf_ip:
            return cf_ip

    raw_chain = _header(headers, "x-forwarded-for") or ""
    # 🔀 ห้ามใช้ entry ซ้ายสุด! แต่ละ proxy **ต่อท้าย** IP ที่มันเห็น ("" client, cf "")
    # ⇒ entry ขวาสุดคือ proxy ตัวในสุด ส่วน client อยู่ที่ตำแหน่ง `len - trusted_hops`
    # entry ฝั่งซ้ายเป็นของที่ client เขียนมาเองได้ทั้งหมด (นี่คือช่องโหว่ spoof คลาสสิก)
    entries = [part.strip() for part in raw_chain.split(",") if part.strip()]
    if len(entries) < trusted_hops:
        # สายสั้นกว่าที่ประกาศไว้ ⇒ เราไม่รู้ว่าฝั่งไหนเชื่อได้ อย่าเดา
        return peer

    return _normalize_ip(entries[len(entries) - trusted_hops]) or peer


def mask_path(path: str) -> str:
    """แทน segment ที่ดูเป็นโทเคนด้วย `{token}` ก่อนลง audit_logs

    เหตุผล: capability URL ที่พาโทเคนมาใน path ตรง ๆ (เช่น `/api/link/<token>`)
    ถ้าเขียนลง audit_logs (ตารางที่คนอ่านได้กว้างกว่าตารางข้อมูลจริง) เท่ากับ
    คัดลอกสิทธิ์เข้าถึงไปวางไว้ในที่ที่คนละคนอ่านได้
    """
    parts = path.split("/")
    for index, segment in enumerate(parts):
        if len(segment) >= _TOKEN_SEGMENT_MIN_LEN:
            parts[index] = "{token}"
    return "/".join(parts)


def describe_endpoint(method: str, path: str) -> str:
    """`GET /api/classroom/7/academic/periods` — ตัด query string ทิ้งเสมอ

    query string ถูกตัดเพราะบางเส้นทางพาโทเคน/อีเมลมาใน query (เช่น redirect_url)
    และเพราะมันทำให้แถว audit แยกกลุ่มตามสถิติไม่ได้เลย
    """
    return f"{method.upper()} {mask_path(path.split('?', 1)[0])}"


def build_request_audit_context(
    peer_ip: Optional[str],
    headers: Mapping[str, str],
    method: str,
    path: str,
    trusted_hops: int,
) -> RequestAuditContext:
    user_agent = (_header(headers, "user-agent") or "").strip()
    return RequestAuditContext(
        ip_address=resolve_client_ip(peer_ip, headers, trusted_hops),
        user_agent=user_agent[:MAX_USER_AGENT_LEN] or None,
        endpoint=describe_endpoint(method, path),
    )
