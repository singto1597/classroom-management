"""🚦 จำกัดความเร็วคำขอ (P6.3) — กันคำขอถล่มบน endpoint ที่ไม่ต้องล็อกอิน

═══════════════════════════════════════════════════════════════════════════════
ทำไมต้องมี (และทำไมไม่ใช้ middleware ทั้งระบบ)
═══════════════════════════════════════════════════════════════════════════════
คำขอส่วนใหญ่ในระบบนี้ต้องล็อกอินอยู่แล้ว ⇒ มี "ตัวระบุตัวตน" ที่เชื่อถือได้
(`user_id`) และมีชั้นสิทธิ์คอยกันอยู่ แต่มี 1 กลุ่มที่ **ไม่ต้องล็อกอิน**:

| scope | endpoint | เหตุผล |
|---|---|---|
| `auth_login` | `POST /api/auth/{discord,google}/login` | แลก OAuth code กับผู้ให้บริการภายนอกทุกครั้ง ⇒ ยิงถี่ = เปลืองโควตาเรา + โดน rate limit จาก Discord/Google |

จึงเลือก "ติดเป็น dependency ราย route" แทน middleware ทั้งระบบ เพราะ
- middleware จะนับทุกคำขอ (รวม dashboard ที่ยิง 2 คำขอต่อหน้า) ⇒ ต้องตั้งเพดานสูง
  จนไม่มีความหมาย หรือเสี่ยงตัดผู้ใช้จริงออก
- dependency ทำให้เพดานผูกกับ **ความหมายของ endpoint** อ่านแล้วรู้ทันทีว่าทำไม

═══════════════════════════════════════════════════════════════════════════════
Fail-open คือการตัดสินใจ — ไม่ใช่ความประมาท
═══════════════════════════════════════════════════════════════════════════════
Redis ล่ม ⇒ **ปล่อยคำขอผ่าน** (log เตือนครั้งเดียวต่อ scope) เพราะ
1. ถ้า fail-closed การที่ Redis ล่มหนึ่งครั้ง = ล็อกอินไม่ได้ทั้งระบบ (ทุกคน)
   ซึ่งรุนแรงกว่าการถูกยิงถล่มชั่วคราวมาก
2. ชั้นป้องกันอื่นยังอยู่: OAuth code ใช้ได้ครั้งเดียวและถูกตรวจกับผู้ให้บริการภายนอก
3. การจำกัดความเร็วเป็น "ชั้นลดโหลด" ไม่ใช่ "ชั้นยืนยันตัวตน"

⚠️ ตัวนับเป็น **fixed window** (`INCR` + `EXPIRE`) ไม่ใช่ sliding window:
ยอมรับว่า ณ รอยต่อหน้าต่างผู้ใช้อาจได้ถึง 2 เท่าของเพดาน — แลกกับการยิง Redis
2 คำสั่งต่อคำขอ (ไม่มี Lua ไม่มี sorted set ที่ต้องล้าง) ซึ่งพอสำหรับจุดประสงค์นี้

═══════════════════════════════════════════════════════════════════════════════
Retry-After ห้ามเป็น 0
═══════════════════════════════════════════════════════════════════════════════
ถ้า TTL ของ key ต่ำมาก (เพิ่งตั้งแล้วหมดอายุพอดี) `Retry-After: 0` ทำให้ client
ยิงซ้ำทันทีเป็นลูป ⇒ บีบขั้นต่ำ 1 วินาทีเสมอ
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, HTTPException, Request, status

from core.config import settings
from core.dependencies import get_current_user
from core.request_context import current_request_audit_context

logger = logging.getLogger("API_RATE_LIMIT")


@dataclass(frozen=True)
class RateLimitRule:
    """เพดานของ scope หนึ่ง — ค่าคงที่ ไม่ผูกกับผู้ใช้/environment"""

    max_requests: int
    window_seconds: int
    # ข้อความไทยที่ผู้ใช้เห็น — ต้องบอก "รอแล้วลองใหม่" ไม่ใช่บอกว่าเกิดข้อผิดพลาด
    message: str


# 🔢 เพดานที่ตั้งใจ — ค่าที่คนปกติไม่มีทางแตะ แต่ตัดสคริปต์ได้ทันที
DEFAULT_RULES: dict[str, RateLimitRule] = {
    # คนจริงล็อกอินไม่เกิน 2-3 ครั้ง/นาที · สคริปต์เดา code ทำได้เป็นหมื่น
    "auth_login": RateLimitRule(
        max_requests=10,
        window_seconds=60,
        message="พยายามเข้าสู่ระบบบ่อยเกินไป กรุณารอสักครู่แล้วลองใหม่",
    ),
}

# log เตือน Redis ล่ม "ครั้งเดียวต่อ scope" — ไม่งั้นทุกคำขอที่ล็อกอินจะท่วม log
_warned_scopes: set[str] = set()


def client_identity(request: Request) -> str:
    """ตัวระบุของผู้เรียก — ใช้ IP ที่ middleware/`resolve_client_ip` คำนวณไว้แล้ว

    ใช้ค่าเดียวกับ audit_logs โดยเจตนา: ถ้า `TRUSTED_PROXY_HOPS=0` (ค่าเริ่มต้น)
    ทุกคนจะได้ IP ของ Traefik ⇒ ทั้งระบบใช้บัคเก็ตเดียวกัน — ยอมรับได้ในเทสต์/dev
    แต่ **บน production ต้องตั้ง hops ให้ถูก** ไม่งั้นเพดาน 10/นาทีจะกลายเป็น
    เพดานรวมทั้งโรงเรียน (ดูคำเตือนใน core/request_context.py)
    """
    ctx = current_request_audit_context()
    if ctx is not None and ctx.ip_address:
        return ctx.ip_address
    if request.client is not None and request.client.host:
        return request.client.host
    return "unknown"


async def consume(
    redis,
    *,
    scope: str,
    identity: str,
    rule: RateLimitRule,
) -> tuple[bool, int, int]:
    """นับหนึ่งครั้งแล้วคืน `(allowed, remaining, retry_after_seconds)`

    ยิง Redis 2 คำสั่งในเส้นปกติ (`SET NX EX` + `INCR` — คำสั่งแรกสำเร็จแค่ครั้งแรก
    ของหน้าต่าง) แล้วตามด้วย `TTL`
    """
    key = f"ratelimit:{scope}:{identity}"

    created = await redis.set(key, 1, ex=rule.window_seconds, nx=True)
    count = 1 if created else int(await redis.incr(key))

    ttl = int(await redis.ttl(key))
    if ttl < 0:
        # key ถูกสร้างโดย INCR ในจังหวะที่ตัวก่อนหน้าหมดอายุพอดี ⇒ ไม่มี TTL
        # ถ้าปล่อยไว้ ตัวนับจะค้างตลอดกาล (ผู้ใช้ถูกล็อกถาวรหลังใช้ครบ)
        await redis.expire(key, rule.window_seconds)
        ttl = rule.window_seconds

    allowed = count <= rule.max_requests
    remaining = max(0, rule.max_requests - count)
    return allowed, remaining, ttl


async def enforce(
    request: Request,
    scope: str,
    *,
    rule: Optional[RateLimitRule] = None,
    identity: Optional[str] = None,
) -> None:
    """ตรวจเพดาน แล้วโยน 429 + `Retry-After` ถ้าเกิน

    เรียกจาก dependency ด้านล่างเท่านั้น — แต่แยกเป็นฟังก์ชันเพื่อให้เทสต์เรียกตรงได้
    โดยไม่ต้องประกอบ FastAPI app
    """
    if not settings.RATE_LIMIT_ENABLED:
        return

    resolved_rule = rule or DEFAULT_RULES[scope]
    redis = getattr(request.app.state, "redis", None)
    if redis is None:
        # ไม่ได้ตั้ง client เลย (เช่นสภาพแวดล้อมที่ไม่มี Redis โดยเจตนา)
        return

    who = identity or client_identity(request)
    try:
        allowed, _remaining, retry_after = await consume(
            redis, scope=scope, identity=who, rule=resolved_rule
        )
    except Exception:
        if scope not in _warned_scopes:
            _warned_scopes.add(scope)
            logger.warning(
                "Redis ใช้งานไม่ได้ — ข้ามการจำกัดความเร็วของ scope '%s' (fail-open)",
                scope,
                exc_info=True,
            )
        return

    if allowed:
        return

    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=resolved_rule.message,
        headers={"Retry-After": str(max(1, retry_after))},
    )


def rate_limit(scope: str, *, rule: Optional[RateLimitRule] = None):
    """dependency สำหรับ endpoint ที่ไม่ต้องล็อกอิน — นับตาม IP

    ใช้ใน `dependencies=[rate_limit("auth_login")]` ของ decorator
    """

    async def _dependency(request: Request) -> None:
        await enforce(request, scope, rule=rule)

    return Depends(_dependency)


def rate_limit_per_user(scope: str, *, rule: Optional[RateLimitRule] = None):
    """dependency สำหรับ endpoint ที่ล็อกอินแล้ว — นับตาม `user_id`

    ⚠️ ต้องประกาศ **หลัง** `get_current_user` ในรายการ dependency เสมอ
    (FastAPI รับประกันลำดับตามประกาศ) ไม่งั้นจะไม่มี `user_id` ให้ใช้
    """

    async def _dependency(
        request: Request, user_ctx: dict = Depends(get_current_user)
    ) -> None:
        await enforce(
            request, scope, rule=rule, identity=f"user:{user_ctx.get('user_id')}"
        )

    return Depends(_dependency)
