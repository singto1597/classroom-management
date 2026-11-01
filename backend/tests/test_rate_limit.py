"""🚦 P6.3 — จำกัดความเร็วคำขอ · 💓 heartbeat ของ push worker

═══════════════════════════════════════════════════════════════════════════════
สิ่งที่เทสต์ชุดนี้ล็อกไว้ (อ่านก่อนแก้)
═══════════════════════════════════════════════════════════════════════════════
1. **เกินเพดาน = 429 + `Retry-After` ≥ 1** — header หายหรือเป็น 0 ทำให้ client
   ยิงซ้ำทันทีเป็นลูป (ดู core/rate_limit.py)
2. **Redis ล่ม = ปล่อยผ่าน (fail-open)** — ถ้ากลับทิศเป็น fail-closed การที่ Redis
   ล่มหนึ่งครั้งจะล็อกอินไม่ได้ทั้งระบบ ซึ่งรุนแรงกว่าการถูกยิงถล่ม
3. **ตัวนับผูกกับ scope + identity** — ผู้ใช้ A ใช้เพดานจนหมดต้องไม่ทำให้ B ได้ 429
4. **ตัวนับของ endpoint สาธารณะถูกต่อสายจริง** — ทดสอบผ่าน app จริง (`/api/shared/...`)
   ไม่ใช่แค่เรียกฟังก์ชันตรง ๆ (บทเรียน "unit test เขียว แต่สายไฟไม่ได้ต่อ")
5. **`/health` รายงาน Redis/worker แต่ไม่เป็น 503** เพราะเหตุเหล่านั้น

⚠️ ใช้ `_fake_redis.FakeRedis` เท่านั้น — `REDIS_URL` ของ test runner ชี้
127.0.0.1:6379 ที่ไม่มีอะไรฟัง ⇒ การทดสอบที่พึ่ง Redis จริงจะขึ้นกับเครื่องที่รัน
"""

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from _fake_redis import BrokenRedis, FakeRedis
from core import rate_limit as rl
from core.config import settings
from core.dependencies import get_current_user
from core.heartbeat import (
    PUSH_WORKER_HEARTBEAT_KEY,
    PUSH_WORKER_HEARTBEAT_TTL_SECONDS,
    read_heartbeat_age,
    record_heartbeat,
)
from main import app as real_app

SMALL_RULE = rl.RateLimitRule(max_requests=2, window_seconds=60, message="ช้า ๆ หน่อย")


# =============================================================================
# ตัวนับ (ฟังก์ชันตรง)
# =============================================================================


@pytest.mark.asyncio
async def test_consume_allows_then_denies_and_counts_down_remaining():
    redis = FakeRedis()

    first = await rl.consume(redis, scope="auth_login", identity="1.2.3.4", rule=SMALL_RULE)
    second = await rl.consume(redis, scope="auth_login", identity="1.2.3.4", rule=SMALL_RULE)
    third = await rl.consume(redis, scope="auth_login", identity="1.2.3.4", rule=SMALL_RULE)

    assert first[0] is True and first[1] == 1
    assert second[0] is True and second[1] == 0
    assert third[0] is False and third[1] == 0
    # ยังมีเวลารออีกเกือบเต็มหน้าต่าง ⇒ ต้องไม่ใช่ 0 (client จะยิงซ้ำทันที)
    assert third[2] >= 1


@pytest.mark.asyncio
async def test_consume_keeps_identities_in_separate_buckets():
    redis = FakeRedis()

    await rl.consume(redis, scope="auth_login", identity="1.2.3.4", rule=SMALL_RULE)
    await rl.consume(redis, scope="auth_login", identity="1.2.3.4", rule=SMALL_RULE)
    denied = await rl.consume(redis, scope="auth_login", identity="1.2.3.4", rule=SMALL_RULE)
    other = await rl.consume(redis, scope="auth_login", identity="5.6.7.8", rule=SMALL_RULE)

    assert denied[0] is False
    assert other[0] is True, "IP อื่นต้องไม่ถูกตัดเพราะ IP หนึ่งใช้เพดานหมด"


@pytest.mark.asyncio
async def test_consume_resets_ttl_when_counter_has_none():
    """เคสหายาก: `INCR` สร้าง key ในจังหวะที่ตัวก่อนหน้าหมดอายุพอดี ⇒ key ไม่มี TTL

    ถ้าไม่ตั้ง TTL คืน ตัวนับจะค้างตลอดกาล — ผู้ใช้ที่ใช้ครบเพดานครั้งหนึ่งจะถูกบล็อก
    ตลอดไป แม้รอนานเท่าไรก็ไม่ปลดล็อก
    """
    redis = FakeRedis()
    key = "ratelimit:auth_login:9.9.9.9"
    redis.store[key] = ("5", None)  # มีค่าแต่ไม่มีวันหมดอายุ

    allowed, _remaining, retry_after = await rl.consume(
        redis, scope="auth_login", identity="9.9.9.9", rule=SMALL_RULE
    )

    assert allowed is False
    assert retry_after == SMALL_RULE.window_seconds
    assert redis.store[key][1] is not None, "ต้องตั้ง TTL กลับให้ตัวนับ"


# =============================================================================
# dependency ผ่าน FastAPI จริง (429 + Retry-After)
# =============================================================================


def _limited_app() -> tuple[FastAPI, TestClient]:
    app = FastAPI()
    app.state.redis = FakeRedis()

    @app.get("/ip", dependencies=[rl.rate_limit("auth_login", rule=SMALL_RULE)])
    async def by_ip():
        return {"ok": True}

    app.dependency_overrides[get_current_user] = lambda: {"user_id": 42}

    @app.get("/user", dependencies=[rl.rate_limit_per_user("activity_qr", rule=SMALL_RULE)])
    async def by_user():
        return {"ok": True}

    return app, TestClient(app)


def test_returns_429_with_retry_after_when_exceeded():
    app, client = _limited_app()

    assert client.get("/ip").status_code == 200
    assert client.get("/ip").status_code == 200

    res = client.get("/ip")

    assert res.status_code == 429, f"คาดว่า 429 แต่ได้ {res.status_code}: {res.text}"
    assert "Retry-After" in res.headers, "ขาด Retry-After ⇒ client ไม่รู้ว่าควรรอนานแค่ไหน"
    assert int(res.headers["Retry-After"]) >= 1
    assert "ช้า ๆ หน่อย" in res.json()["detail"]


def test_per_user_dependency_counts_by_user_id_not_ip():
    app, client = _limited_app()

    client.get("/user")
    client.get("/user")
    res = client.get("/user")

    assert res.status_code == 429
    assert any(key.startswith("ratelimit:activity_qr:user:42") for key in app.state.redis.store)


def test_rate_limit_disabled_by_settings(monkeypatch):
    app, client = _limited_app()
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)

    assert [client.get("/ip").status_code for _ in range(5)] == [200] * 5
    assert app.state.redis.store == {}


def test_fail_open_when_redis_is_down(monkeypatch):
    """Redis ล่ม → ต้องปล่อยผ่าน ไม่ใช่ 429/500 (นี่คือการตัดสินใจที่ตั้งใจ)"""
    app, client = _limited_app()
    app.state.redis = BrokenRedis()
    # log เตือนมี state ระดับโมดูล ต้องรีเซ็ตเพื่อให้เทสต์ไม่ขึ้นกับลำดับ
    monkeypatch.setattr(rl, "_warned_scopes", set())

    for _ in range(5):
        assert client.get("/ip").status_code == 200


# =============================================================================
# สายไฟของ app จริง — route ที่มี dependency ต้องเป็นตัวที่เราใช้จริง
# =============================================================================


def _route(path: str, method: str) -> APIRoute:
    """⚠️ ต้องกรองตาม method ด้วย — `.../checkin/qr` มีทั้ง GET (ออกบัตร) และ POST (สแกน)
    ใช้ path เดียวกัน ⇒ หาเจอตัวแรกแล้วจะตรวจผิดตัว"""
    for route in real_app.routes:
        if (
            isinstance(route, APIRoute)
            and route.path == path
            and method in route.methods
        ):
            return route
    raise AssertionError(f"ไม่พบ route {method} {path}")


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/auth/discord/login"),
        ("POST", "/api/auth/google/login"),
        ("GET", "/api/shared/activity/{token}"),
        ("POST", "/api/classroom/{target_id}/activities/{activity_id}/checkin/qr"),
    ],
)
def test_public_and_sensitive_routes_have_rate_limit_dependency(method, path):
    assert _route(path, method).dependencies, f"{method} {path} หลุดการจำกัดความเร็วไปแล้ว"


@pytest.mark.asyncio
async def test_shared_activity_route_actually_counts(client):
    """ยิงผ่าน app จริงหนึ่งครั้ง แล้วต้องเห็นตัวนับของ scope ใน Redis ปลอม

    เลือก endpoint นี้เพราะ **ไม่ต้องล็อกอิน** — ถ้าเผลอใช้ endpoint ที่มี auth
    เทสต์จะได้ 401 ก่อนถึงตัวนับ แล้วผ่านทั้งที่ไม่มีการนับจริง
    """
    fake = FakeRedis()
    original = real_app.state.redis
    real_app.state.redis = fake
    try:
        res = client.get("/api/shared/activity/" + "x" * 43)
    finally:
        real_app.state.redis = original

    # ไม่มีกิจกรรมนี้ ⇒ 404 (แต่ต้องผ่าน dependency มาก่อนแล้ว)
    assert res.status_code == 404
    assert any(key.startswith("ratelimit:shared_activity:") for key in fake.store)


# =============================================================================
# 💓 heartbeat
# =============================================================================


@pytest.mark.asyncio
async def test_record_heartbeat_sets_value_with_ttl_and_age_reads_zero():
    redis = FakeRedis()

    await record_heartbeat(redis, now=1_000.0)
    age = await read_heartbeat_age(redis, now=1_030.0)

    assert redis.store[PUSH_WORKER_HEARTBEAT_KEY][0] == "1000"
    assert redis.store[PUSH_WORKER_HEARTBEAT_KEY][1] is not None
    assert age == 30


@pytest.mark.asyncio
async def test_read_heartbeat_age_is_none_when_never_beaten():
    assert await read_heartbeat_age(FakeRedis()) is None


@pytest.mark.asyncio
async def test_read_heartbeat_age_clamps_negative_clock_skew():
    redis = FakeRedis()
    await record_heartbeat(redis, now=2_000.0)

    # API นาฬิกาช้ากว่า worker ⇒ อายัติได้ค่าติดลบ ซึ่งอ่านแล้วเข้าใจผิด
    assert await read_heartbeat_age(redis, now=1_990.0) == 0


@pytest.mark.asyncio
async def test_heartbeat_ttl_is_longer_than_reporting_floor():
    assert PUSH_WORKER_HEARTBEAT_TTL_SECONDS >= 300


@pytest.mark.asyncio
async def test_record_heartbeat_without_redis_is_a_noop():
    await record_heartbeat(None)  # ต้องไม่ throw — worker อาจรันโดยไม่มี Redis


@pytest.mark.asyncio
async def test_health_reports_redis_and_worker_without_breaking_200(client):
    """`/health` ต้องยัง 200 และบอกอายุ heartbeat — ไม่ใช่ 503 (ดู core/heartbeat.py)"""
    fake = FakeRedis()
    await record_heartbeat(fake)  # เวลาจริง ⇒ อายุต้องใกล้ 0

    original = real_app.state.redis
    real_app.state.redis = fake
    try:
        res = client.get("/health")
    finally:
        real_app.state.redis = original

    body = res.json()
    assert res.status_code == 200
    assert body["database"] == "connected"
    assert body["redis"] == "connected"
    assert 0 <= body["push_worker"]["last_beat_seconds_ago"] < 60


@pytest.mark.asyncio
async def test_health_stays_200_but_marks_redis_unavailable_when_down(client):
    """Redis ล่ม → `redis: "unavailable"` แต่ **ห้าม 503** (Swarm จะฆ่า backend ที่ดี)"""
    original = real_app.state.redis
    real_app.state.redis = BrokenRedis()
    try:
        res = client.get("/health")
    finally:
        real_app.state.redis = original

    body = res.json()
    assert res.status_code == 200
    assert body["redis"] == "unavailable"
    assert body["push_worker"]["last_beat_seconds_ago"] is None
