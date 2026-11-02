"""P6.1 — audit บันทึก IP จริง / User-Agent / endpoint (และไม่เชื่อ header ปลอม)

🔴 กฎที่เทสต์ชุดนี้ล็อกไว้
1. `TRUSTED_PROXY_HOPS = 0` (ค่าเริ่มต้น) ⇒ **ละเลย header ทั้งหมด** IP ที่ลง audit
   ต้องเป็น TCP peer (Traefik) ไม่ใช่ค่าที่ client พิมพ์มา — ถ้าเทสต์นี้แดงแปลว่า
   ใครก็เขียน IP ปลอมลง audit_logs ได้
2. Cloudflare อยู่หน้าสุด ⇒ ใช้ `CF-Connecting-IP` ได้เฉพาะเมื่อประกาศเชื่อ ≥ 2 ชั้น
   (CF + Traefik) ไม่ใช่ 1 ชั้น
3. `X-Forwarded-For` ต้องอ่านจาก **ขวา** (`len - trusted_hops`) — entry ซ้ายสุดเป็น
   ของที่ client เขียนเองได้ทั้งหมด
4. ค่าที่ service ส่งมาเอง (`endpoint_or_command="create_academic_year"`) **ต้องชนะ**
   ค่า default จาก contextvar — ไม่งั้นชื่อ action ใน audit จะกลายเป็น path ดิบ
5. `user_agent` เป็นข้อความที่ผู้ใช้ควบคุม ⇒ ต้องถูกตัดความยาวก่อนลง DB
"""

import pytest
from fastapi.testclient import TestClient

from core.config import settings
from core.logger import AuditLogger
from core.request_context import (
    MAX_USER_AGENT_LEN,
    RequestAuditContext,
    build_request_audit_context,
    current_request_audit_context,
    describe_endpoint,
    mask_path,
    reset_request_audit_context,
    resolve_client_ip,
    set_request_audit_context,
)
from main import app

# IP ของ "Traefik" ในเทสต์ — TestClient ยอมให้กำหนด peer เองได้ (httpx `client=`)
PEER_IP = "203.0.113.9"
TRUSTED = "198.51.100.7"   # IP ของผู้ใช้จริงที่ CF ส่งมา
SPOOF = "1.1.1.1"          # ค่าที่ client พยายามยัดมา


# =============================================================================
# resolve_client_ip — ตรรกะล้วน ไม่ต้องมี DB/HTTP
# =============================================================================
@pytest.mark.parametrize(
    "trusted_hops, headers, expected",
    [
        # 0 = ไม่เชื่อ header ใด ๆ แม้จะดูถูกต้อง (นี่คือค่าเริ่มต้นของ production)
        (0, {"x-forwarded-for": SPOOF}, PEER_IP),
        (0, {"cf-connecting-ip": SPOOF}, PEER_IP),
        (0, {"x-forwarded-for": SPOOF, "cf-connecting-ip": SPOOF}, PEER_IP),
        # 1 ชั้น = proxy ตัวเดียว ⇒ ใช้ XFF ตัวขวาสุด
        (1, {"x-forwarded-for": SPOOF}, SPOOF),
        # 1 ชั้น **ห้าม** ใช้ CF-Connecting-IP (Cloudflare ไม่อยู่ในสายที่ประกาศ)
        (1, {"cf-connecting-ip": SPOOF}, PEER_IP),
        # 2 ชั้น = Cloudflare + Traefik ⇒ CF-Connecting-IP ชนะเสมอ
        (2, {"cf-connecting-ip": TRUSTED, "x-forwarded-for": SPOOF}, TRUSTED),
        # 2 ชั้น ไม่มี CF header ⇒ client = entry ที่ len - 2 (ไม่ใช่ซ้ายสุด!)
        (2, {"x-forwarded-for": f"{SPOOF}, 9.9.9.9, {TRUSTED}"}, "9.9.9.9"),
        # สายสั้นกว่าที่ประกาศ ⇒ ไม่เดา ใช้ peer
        (2, {"x-forwarded-for": SPOOF}, PEER_IP),
        # ค่าขยะเป็น IP → ตกกลับไปใช้ peer (ไม่ใช่เก็บข้อความดิบลง DB)
        (1, {"x-forwarded-for": "not-an-ip"}, PEER_IP),
        (2, {"cf-connecting-ip": "unknown"}, PEER_IP),
    ],
)
def test_resolve_client_ip(trusted_hops, headers, expected):
    assert resolve_client_ip(PEER_IP, headers, trusted_hops) == expected


def test_resolve_client_ip_normalizes_ipv6_with_port():
    # Traefik บาง config ส่ง `[::1]:443` มา — ต้องได้ `::1` ไม่ใช่สตริงดิบ
    assert resolve_client_ip("[::1]:443", {}, 0) == "::1"


def test_resolve_client_ip_without_peer_is_none():
    assert resolve_client_ip(None, {"x-forwarded-for": "1.2.3.4"}, 0) is None


def test_header_lookup_is_case_insensitive():
    # Starlette เก็บ header เป็นตัวพิมพ์เล็ก แต่ dict เปล่า ๆ ในเทสต์อาจไม่ใช่
    assert resolve_client_ip(PEER_IP, {"CF-Connecting-IP": TRUSTED}, 2) == TRUSTED


# =============================================================================
# describe_endpoint / mask_path — อย่าเอาโทเคนจาก path ลงตาราง audit
# =============================================================================
def test_describe_endpoint_drops_query_string():
    assert (
        describe_endpoint("post", "/api/classroom/7/finance/receipts?token=secret")
        == "POST /api/classroom/7/finance/receipts"
    )


def test_describe_endpoint_masks_long_opaque_segments():
    # capability URL พาโทเคนมาใน path ตรง ๆ — ต้องไม่หลุดลง audit_logs
    masked = describe_endpoint("GET", "/api/link/ab12cd34ef56gh78ij90kl12")
    assert masked == "GET /api/link/{token}"


def test_mask_path_keeps_real_path_segments():
    # path จริงของระบบต้องไม่ถูก mask — ไม่งั้นสถิติแยกหน้าไม่ได้
    for path in (
        "/api/classroom/7/academic/periods",
        "/api/classroom/7/settings/academic-periods",
        "/api/classroom/7/finance/receipts/REC-2569-0042",
    ):
        assert mask_path(path) == path


def test_user_agent_is_truncated():
    ctx = build_request_audit_context(
        PEER_IP,
        {"user-agent": "A" * (MAX_USER_AGENT_LEN + 10)},
        "GET",
        "/health",
        0,
    )
    assert ctx.user_agent is not None
    assert len(ctx.user_agent) == MAX_USER_AGENT_LEN


def test_missing_user_agent_is_none_not_empty_string():
    ctx = build_request_audit_context(PEER_IP, {}, "GET", "/health", 0)
    assert ctx.user_agent is None


# =============================================================================
# Integration — ผ่าน middleware จริง + เขียนลง DB จริง
# =============================================================================
def _trusted_test_client(running: TestClient) -> TestClient:
    """TestClient ที่ TCP peer เป็น IP จริง (ค่าเริ่มต้นคือ string `testclient`)

    ⚠️ ต้องยืม `portal` ของ fixture `client` มาใช้ — ไม่ใช่จะ hack เล่น ๆ:
    `asyncpg` pool ผูกกับ event loop ตอนที่ lifespan สร้างมัน ถ้า TestClient
    ตัวใหม่ไปสร้าง loop ใหม่ (ซึ่งมันทำแบบนั้นเมื่อไม่มี `with`) จะได้
    `Future ... attached to a different loop` ทันที
    ⇒ ยืม portal = ยิงคำขอผ่าน loop เดียวกับที่ pool เกิด
    """
    borrowed = TestClient(app, client=(PEER_IP, 43210))
    borrowed.portal = running.portal
    return borrowed


def _create_year(client: TestClient, room_id: int, headers: dict):
    return client.post(
        f"/api/classroom/{room_id}/academic/years?target_type=room",
        headers=headers,
        json={"year_be": 2569, "start_date": "2026-05-01", "end_date": "2027-03-31"},
    )


async def _last_audit(db_pool):
    row = await db_pool.fetchrow(
        """
        SELECT ip_address, user_agent, endpoint_or_command
        FROM audit_logs
        WHERE service_name = 'ACADEMIC' AND action = 'CREATE'
        ORDER BY created_at DESC
        LIMIT 1
        """
    )
    assert row is not None, "ไม่พบแถว audit เลย — เทสต์จะเขียวหลอกถ้าไม่ assert ตรงนี้"
    return row


@pytest.mark.asyncio
async def test_default_hops_ignore_spoofed_headers(client, admin_headers, db_pool, monkeypatch):
    """ค่าเริ่มต้น (0): client ยัด header ปลอมมา แต่ audit ต้องบันทึก peer เท่านั้น"""
    monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", 0)

    resp = _create_year(
        _trusted_test_client(client),
        admin_headers.room_id,
        {
            **admin_headers,
            "X-Forwarded-For": SPOOF,
            "CF-Connecting-IP": SPOOF,
            "User-Agent": "pytest-agent/1.0",
        },
    )
    assert resp.status_code == 200, resp.text

    row = await _last_audit(db_pool)
    assert row["ip_address"] == PEER_IP
    assert row["user_agent"] == "pytest-agent/1.0"
    # ค่าที่ service ส่งเองต้องชนะ default จาก contextvar
    assert row["endpoint_or_command"] == "create_academic_year"


@pytest.mark.asyncio
async def test_two_hops_use_cf_connecting_ip(client, admin_headers, db_pool, monkeypatch):
    monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", 2)

    resp = _create_year(
        _trusted_test_client(client),
        admin_headers.room_id,
        {**admin_headers, "CF-Connecting-IP": TRUSTED, "X-Forwarded-For": SPOOF},
    )
    assert resp.status_code == 200, resp.text

    assert (await _last_audit(db_pool))["ip_address"] == TRUSTED


@pytest.mark.asyncio
async def test_context_is_reset_after_request(client, admin_headers, db_pool, monkeypatch):
    """กันกับดัก contextvar ค้าง: คำขอถัดไปห้ามได้ IP ของคนก่อนหน้า"""
    monkeypatch.setattr(settings, "TRUSTED_PROXY_HOPS", 2)
    respond = _create_year(
        _trusted_test_client(client),
        admin_headers.room_id,
        {**admin_headers, "CF-Connecting-IP": TRUSTED},
    )
    assert respond.status_code == 200, respond.text

    assert current_request_audit_context() is None


@pytest.mark.asyncio
async def test_audit_logger_falls_back_to_context_for_endpoint(db_pool, admin_headers):
    """service ที่ไม่ส่ง endpoint/ip มาเลย ยังได้ค่าที่อ่านรู้เรื่อง"""
    ctx = RequestAuditContext(
        ip_address=TRUSTED, user_agent="ctx-agent", endpoint="POST /api/x"
    )
    token = set_request_audit_context(ctx)
    try:
        async with db_pool.acquire() as conn:
            await AuditLogger(service_name="ACADEMIC").log(
                conn=conn,
                action="CREATE",
                actor_identifier="user_id:1",
                client_source="WEB_APP",
                room_id=admin_headers.room_id,
                user_id=admin_headers.user_id,
            )
    finally:
        reset_request_audit_context(token)

    row = await _last_audit(db_pool)
    assert row["ip_address"] == TRUSTED
    assert row["user_agent"] == "ctx-agent"
    assert row["endpoint_or_command"] == "POST /api/x"


@pytest.mark.asyncio
async def test_explicit_values_win_over_context(db_pool, admin_headers):
    """ผู้เรียกที่ส่งค่ามาเองต้องไม่ถูก context ทับ"""
    token = set_request_audit_context(
        RequestAuditContext(ip_address=TRUSTED, user_agent="ctx", endpoint="POST /api/x")
    )
    try:
        async with db_pool.acquire() as conn:
            await AuditLogger(service_name="ACADEMIC").log(
                conn=conn,
                action="CREATE",
                actor_identifier="user_id:1",
                client_source="WEB_APP",
                room_id=admin_headers.room_id,
                user_id=admin_headers.user_id,
                endpoint_or_command="explicit_endpoint",
                ip_address="192.0.2.44",
                user_agent="explicit-agent",
            )
    finally:
        reset_request_audit_context(token)

    row = await _last_audit(db_pool)
    assert row["ip_address"] == "192.0.2.44"
    assert row["user_agent"] == "explicit-agent"
    assert row["endpoint_or_command"] == "explicit_endpoint"
