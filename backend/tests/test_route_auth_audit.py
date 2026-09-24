"""
เทสต์เชิงระบบ — ทุก route ต้องมี auth dependency

**ที่มา:** การตรวจระบบเมื่อ 2026-09-23 พบว่า `GET /api/classroom/{target_id}/summary`
เป็น route เดียวจาก 106 ตัวที่ไม่มี auth dependency ใด ๆ เลย และหลุดขึ้น production จริง
ทั้งที่ชุดเทสต์ 1,065 ตัวเขียวทั้งหมด — เพราะเทสต์ที่มีอยู่ตรวจ *business logic*
(เรียก service ตรง ๆ) ไม่ได้ตรวจ *route wiring* เลยสักตัว

ไฟล์นี้ปิดช่องนั้นแบบเป็นระบบ: ไล่ทุก route จาก `app.routes` แล้วยืนยันว่าทุกตัว
มี auth dependency อย่างน้อยหนึ่งตัว ยกเว้นรายชื่อที่อนุญาตซึ่งระบุเหตุผลไว้ชัด

**ทำไมตรวจแบบ static ไม่ใช่ยิง HTTP:**
การยิง HTTP จริงจะปนกันเรื่องอื่น — route ที่มี `resolve_target_to_room_id` อาจตอบ 404
ก่อนถึง auth (ซึ่งก็เป็นบั๊กอีกแบบ ดู `test_daily_summary_auth.py`), route ที่มี body
อาจตอบ 422 การตรวจ dependency graph ตรง ๆ จึงชี้เป้าได้แม่นกว่าว่า "route นี้ไม่มีด่าน"
ส่วนการยิง HTTP จริงมีเทสต์แยกต่อ endpoint อยู่แล้ว

**เมื่อเทสต์นี้ล้ม:** อย่าเพิ่งไปเพิ่มชื่อ route ลง `PUBLIC_ROUTES`
ให้ถามก่อนว่า route นั้นควรเป็น public จริงไหม — ปกติคำตอบคือไม่
"""
from fastapi.routing import APIRoute

from core.dependencies import get_current_user, get_current_user_or_bot, verify_api_key

# หมายเหตุ: ไฟล์นี้เป็นเทสต์ sync ล้วน (ตรวจ dependency graph ไม่ต้องแตะ DB/HTTP)
# จึงไม่ต้องมี `pytestmark = pytest.mark.asyncio`


# === dependency ที่นับว่าเป็น "ด่าน auth" ===
AUTH_DEPENDENCIES = {
    get_current_user,        # เว็บ (JWT) + บอท (X-API-Key + X-Discord-Id)
    get_current_user_or_bot, # บอท system identity (ไม่มีแถวใน users)
    verify_api_key,          # system RPC — บอทเท่านั้น
}


# === route ที่ตั้งใจให้เข้าได้โดยไม่ต้อง auth (allowlist) ===
# ⚠️ ทุกบรรทัดต้องมีเหตุผลกำกับ — "ลืมใส่" ไม่ใช่เหตุผล
PUBLIC_ROUTES: dict[tuple[str, str], str] = {
    ("POST", "/api/auth/discord/login"):
        "OAuth callback ของ Discord — ผู้ใช้ยังไม่มีบัญชีในระบบ ณ จุดนี้ จึงยังไม่มีอะไรให้ auth",
    ("POST", "/api/auth/google/login"):
        "OAuth callback ของ Google — เหตุผลเดียวกับ discord/login",
    ("GET", "/health"):
        "health check ของ Traefik/load balancer — ต้องไม่ต้องมี credential",
}


def _collect_dep_calls(dependant) -> set:
    """ไล่ dependency graph ลงไปทั้งต้น แล้วเก็บ callable ทุกตัวที่เจอ"""
    calls = set()
    for sub in dependant.dependencies:
        if sub.call is not None:
            calls.add(sub.call)
        calls |= _collect_dep_calls(sub)
    return calls


def _iter_api_routes():
    """คืน (method, path, route) ของทุก APIRoute ในแอป — ข้าม static mount/docs"""
    from main import app

    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            yield method, route.path, route


def test_every_route_declares_auth_dependency():
    """ทุก route ต้องมี auth dependency อย่างน้อยหนึ่งตัว ยกเว้นที่อยู่ใน allowlist"""
    offenders = []

    for method, path, route in _iter_api_routes():
        if (method, path) in PUBLIC_ROUTES:
            continue
        if _collect_dep_calls(route.dependant) & AUTH_DEPENDENCIES:
            continue
        offenders.append(f"  {method:6} {path}")

    assert not offenders, (
        f"พบ {len(offenders)} route ที่ไม่มี auth dependency ใด ๆ:\n"
        + "\n".join(offenders)
        + "\n\nถ้า route เหล่านี้ควรเป็น public จริง ให้เพิ่มลง PUBLIC_ROUTES พร้อมเหตุผล\n"
        "ถ้าเป็น system RPC ของบอท ให้ใช้ Depends(verify_api_key)\n"
        "ถ้าเป็นของเว็บ ให้ใช้ Depends(get_current_user)\n"
        "⚠️ อย่าใช้ require_member กับ system RPC — ดู docs/skills.md"
    )


def test_public_allowlist_has_no_stale_entries():
    """ทุก entry ใน allowlist ต้องมี route จริงรองรับ — กัน allowlist ที่ค้างจนกลายเป็นรู"""
    live = {(m, p) for m, p, _ in _iter_api_routes()}
    stale = sorted(set(PUBLIC_ROUTES) - live)

    assert not stale, (
        "allowlist มี entry ที่ไม่มี route รองรับแล้ว (route ถูกลบ/เปลี่ยนชื่อ):\n"
        + "\n".join(f"  {m:6} {p}" for m, p in stale)
        + "\n\nลบบรรทัดเหล่านี้ออกจาก PUBLIC_ROUTES — allowlist ที่ค้างคือรูที่ไม่มีใครเห็น"
    )


def test_auth_dependency_set_matches_reality():
    """กัน auth dependency ตัวใหม่ที่เพิ่มทีหลังแล้วเทสต์นี้ไม่รู้จัก

    ถ้าเพิ่ม dependency ด้าน auth ตัวใหม่ใน core/dependencies.py แล้วไม่อัปเดต
    AUTH_DEPENDENCIES เทสต์นี้จะเตือน — ไม่งั้น route ที่ใช้ตัวใหม่จะถูกมองว่า
    "ไม่มี auth" แล้วกลายเป็น false positive ที่คนจะไปปิดด้วยการเพิ่ม allowlist
    """
    import core.dependencies as deps
    from main import app

    known = AUTH_DEPENDENCIES | {deps.get_db_pool, deps.resolve_target_to_room_id}
    unknown = set()

    for _, _, route in _iter_api_routes():
        for call in _collect_dep_calls(route.dependant):
            if getattr(call, "__module__", "") != "core.dependencies":
                continue
            if call not in known:
                unknown.add(call.__name__)

    assert not unknown, (
        f"พบ dependency จาก core.dependencies ที่เทสต์นี้ไม่รู้จัก: {sorted(unknown)}\n"
        "ถ้าตัวใดเป็นด่าน auth ให้เพิ่มเข้า AUTH_DEPENDENCIES"
    )


def test_route_count_is_not_silently_shrinking():
    """กัน router ถูกถอดออกจาก main.py โดยไม่มีใครรู้

    ตัวเลขนี้ *ตั้งใจ* ให้ต้องอัปเดตมือเมื่อเพิ่ม/ลบ route — เป็นสัญญาณเตือน
    ไม่ใช่ภาระ ถ้าเทสต์ล้มเพราะเพิ่งเพิ่ม route จริง ให้ปรับตัวเลขแล้ว commit มาด้วยกัน
    """
    expected = 127

    actual = len(list(_iter_api_routes()))
    assert actual == expected, (
        f"จำนวน route เปลี่ยนจาก {expected} เป็น {actual}\n"
        "ถ้าเพิ่ม/ลบ route จริง ให้ปรับ `expected` ในไฟล์นี้ในคอมมิตเดียวกัน\n"
        "ถ้าไม่ได้ตั้งใจ ให้ตรวจว่า router ถูกถอดออกจาก main.py หรือเปล่า"
    )
