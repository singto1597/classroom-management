"""H9 — `/health` ต้องคืน **503** เมื่อต่อ DB ไม่ได้ ไม่ใช่ 200

## บั๊กที่เทสต์ชุดนี้ล็อก (พบจากการตรวจระบบ 2026-09-23)

`health_check()` ใน `main.py` เดิมเขียนไว้แบบนี้

    try:
        async with app.state.db_pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return {"status": "ok", "database": "connected"}
    except Exception:
        return {"status": "error"}          # ← HTTP status ยังเป็น 200

สาขา `except` **ไม่ได้ตั้ง status code** ⇒ FastAPI คืน **200 พร้อม body ที่บอกว่า error**

## ทำไมถึงร้ายแรง (ไม่ใช่แค่เรื่องความสวยงามของ API)

`docker-compose.app.yml` ผูก healthcheck ของ backend ไว้กับ `curl -f http://localhost:8000/health`
และ `curl -f` (fail) จะ exit != 0 **เฉพาะเมื่อ HTTP status >= 400**

⇒ เมื่อไหร่ก็ตามที่ backend ต่อ DB ไม่ได้ มันยัง **ตอบ 200** ⇒ `curl -f` **ผ่าน**
⇒ Swarm นับว่า task นั้น `healthy` ทั้งที่ให้บริการจริงไม่ได้เลย

ผลที่ตามมา: ระหว่าง rolling update (`order: start-first`, `replicas: 3`) Swarm จะ
**ฆ่า task เก่าที่ใช้งานได้จริงทิ้ง** เพื่อไปแทนด้วย task ใหม่ที่ต่อ DB ไม่ได้
⇒ ผู้ใช้เจอ error จากทุก request แทนที่จะเป็น "deploy ล้ม แล้วของเก่ายังรับงานอยู่"

เป็นบั๊กตระกูลเดียวกับที่ frontend เจอตอนไม่มี healthcheck (502 ตอน deploy) ต่างกันแค่ชั้น:
อันนั้น task ใหม่ยังไม่ทันฟังพอร์ต อันนี้ task ใหม่ฟังพอร์ตแล้วแต่ตอบ error ทุกคำขอ

## ⚠️ ผลข้างเคียงที่ตั้งใจไว้ (ไม่ใช่บั๊ก)

เมื่อ DB ล่มจริง task ที่ healthcheck ไม่ผ่านจะถูก Swarm **ฆ่าแล้วเริ่มใหม่** เป็นวงจร
ซึ่งดูเหมือนแย่ แต่ถูกต้องกว่า: task นั้นให้บริการไม่ได้อยู่แล้ว และการตายทำให้เห็นใน
`docker service ps` แทนที่จะเงียบ ๆ คืน 200 แล้วให้ผู้ใช้เป็นคนเจอ error เอง

## ขอบเขตของเทสต์

เทสต์นี้สลับ `app.state.db_pool` เป็นตัวปลอม (ไม่มีเทสต์ไหนในชุดเดิมแตะ `app.state` เลย)
เพื่อจำลอง "DB ต่อไม่ได้" โดยไม่ต้องดับ Postgres จริง — สิ่งที่ถูกทดสอบคือ **การแปลง
exception เป็น HTTP status** ซึ่งเป็นตรรกะของ `main.py` ไม่ใช่ของ asyncpg
"""
import pathlib
import re

import pytest

from main import app

pytestmark = pytest.mark.asyncio


# =============================================================================
# Pool ปลอม 2 แบบ — คนละจุดที่พัง
# =============================================================================


class _AcquireFailsPool:
    """พังตอน `acquire()` — connection ใหม่สร้างไม่ได้ (DB ล่ม/รหัสผ่านผิด)"""

    def acquire(self):
        raise ConnectionRefusedError("จำลอง: ต่อ PostgreSQL ไม่ได้")


class _QueryFailsPool:
    """พังตอนสั่ง SQL — pool ยังอยู่แต่ connection ตายกลางทาง

    เจอบ่อยกว่าแบบแรกในทางปฏิบัติ (DB ถูก restart / network ถูกตัด ระหว่างที่ pool
    ยังถือ connection เก่าอยู่) และเป็นเหตุผลว่าทำไม `try` ต้องคร่อมทั้งบล็อก
    ไม่ใช่แค่ตอน acquire
    """

    class _Conn:
        async def fetchval(self, *_args, **_kwargs):
            raise ConnectionResetError("จำลอง: connection ถูกตัดกลางทาง")

    class _Ctx:
        def __init__(self, conn):
            self._conn = conn

        async def __aenter__(self):
            return self._conn

        async def __aexit__(self, *_exc):
            return False

    def acquire(self):
        return self._Ctx(self._Conn())


# =============================================================================
# เส้นปกติ — ต้องไม่พังของเดิม
# =============================================================================


async def test_health_ok_when_db_reachable(client):
    """DB ต่อได้ → 200 + body บอก connected (พฤติกรรมเดิม ต้องคงไว้)"""
    res = client.get("/health")

    assert res.status_code == 200, f"คาดว่า 200 แต่ได้ {res.status_code}: {res.text}"
    assert res.json() == {"status": "ok", "database": "connected"}


# =============================================================================
# เส้นที่ล็อกบั๊ก — DB ใช้ไม่ได้ ต้องเป็น 503
# =============================================================================


async def test_health_returns_503_when_acquire_fails(client, monkeypatch):
    """🔴 เทสต์หลัก — `acquire()` พัง → ต้องได้ 503 ไม่ใช่ 200

    ถ้าบั๊กเดิมกลับมา เทสต์นี้จะ fail ด้วยข้อความ `503 != 200`
    """
    monkeypatch.setattr(app.state, "db_pool", _AcquireFailsPool())

    res = client.get("/health")

    assert res.status_code == 503, (
        f"🔴 บั๊ก H9 กลับมาแล้ว — /health คืน {res.status_code} ตอนต่อ DB ไม่ได้ "
        "(ต้องเป็น 503) ⇒ `curl -f` ใน Swarm healthcheck ผ่าน ⇒ "
        "task ที่ให้บริการไม่ได้ถูกนับว่า healthy"
    )


async def test_health_returns_503_when_query_fails(client, monkeypatch):
    """pool ยังอยู่แต่ connection ตายกลางทาง → ก็ต้องเป็น 503 เหมือนกัน"""
    monkeypatch.setattr(app.state, "db_pool", _QueryFailsPool())

    res = client.get("/health")

    assert res.status_code == 503, f"คาดว่า 503 แต่ได้ {res.status_code}: {res.text}"


async def test_health_does_not_leak_exception_detail(client, monkeypatch):
    """body ต้องไม่พา exception จริงออกไป — `/health` เป็น public route (ไม่มี auth)

    ข้อความจาก asyncpg อาจมี host/port/user ของ DB ติดมา ⇒ ต้องคืนค่าคงที่เท่านั้น
    """
    monkeypatch.setattr(app.state, "db_pool", _AcquireFailsPool())

    res = client.get("/health")
    body = res.text

    assert "ConnectionRefusedError" not in body
    assert "จำลอง" not in body  # ข้อความ exception ต้นทาง
    assert res.json() == {"detail": {"status": "error", "database": "disconnected"}}


# =============================================================================
# ล็อก "สายไฟ" ระหว่าง 503 กับ healthcheck ของ Swarm
# =============================================================================


def _find_compose_file() -> pathlib.Path | None:
    """หา `docker-compose.app.yml` จากราก repo

    ⚠️ **เดินขึ้นจาก `__file__` ไม่ได้ใช้ `parents[N]` ตรง ๆ** — เพราะในคอนเทนเนอร์
    `test_runner` เมานต์แค่ `./backend:/app` ⇒ ราก repo **ไม่ได้อยู่ในคอนเทนเนอร์**
    (บน host ไฟล์อยู่ที่ `parents[2]` แต่ในคอนเทนเนอร์ `parents[2]` ชี้ไปที่ `/`)
    จึงต้องเดินขึ้นหาจริง แล้วคืน `None` ถ้าไม่เจอ เพื่อให้เทสต์ `skip` อย่างซื่อสัตย์
    แทนที่จะ fail ด้วยเหตุผลหลอก ๆ ว่า "โครง compose เปลี่ยน"

    ตำแหน่งที่สอง (`/repo/`) คือที่ที่ `docker-compose.test.yml` เมานต์ไฟล์นี้เข้าไป
    โดยเฉพาะ — ดูเหตุผลในไฟล์นั้น
    """
    candidates = [base / "docker-compose.app.yml" for base in pathlib.Path(__file__).resolve().parents]
    candidates.append(pathlib.Path("/repo/docker-compose.app.yml"))

    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _backend_healthcheck_test() -> str:
    """ดึงบรรทัด `test:` ของ healthcheck ใน service `backend` จาก docker-compose.app.yml

    ⚠️ **ไม่ใช้ `yaml` module โดยเจตนา** — `PyYAML` ไม่อยู่ใน `requirements.txt`
    (ยืนยันแล้ว: `docker run --entrypoint python classroom-production-backend:9fbe3ad
    -c "import yaml"` → ModuleNotFoundError) การเพิ่ม dependency เข้า production image
    เพียงเพื่อให้เทสต์อ่านไฟล์ compose ได้ ถือว่าไม่คุ้ม ⇒ แยกด้วย indent เอา

    วิธีแยก: หา service block ด้วย indent 2 ช่อง แล้วตัดที่ชื่อ service ถัดไป
    (ข้ามบรรทัดคอมเมนต์ เพราะ `  # ...` ก็ขึ้นต้นด้วยอักขระที่ไม่ใช่ช่องว่าง)
    """
    compose_path = _find_compose_file()
    assert compose_path is not None, "ไม่พบ docker-compose.app.yml"
    lines = compose_path.read_text(encoding="utf-8").splitlines()

    block: list[str] = []
    inside = False
    for line in lines:
        if re.match(r"^  backend:\s*$", line):
            inside = True
            continue
        if inside:
            # ชื่อ service อื่น (indent 2 ช่อง ตัวอักษร/ขีดล่าง) = จบ block ของ backend
            if re.match(r"^  [A-Za-z_][\w-]*:\s*$", line):
                break
            block.append(line)

    assert block, "หา service `backend` ใน docker-compose.app.yml ไม่เจอ — โครงไฟล์เปลี่ยนไปแล้ว?"

    inside_healthcheck = False
    for line in block:
        if re.match(r"^    healthcheck:\s*$", line):
            inside_healthcheck = True
            continue
        if inside_healthcheck:
            stripped = line.strip()
            if stripped.startswith("#") or not stripped:
                continue
            if re.match(r"^      test:", line):
                return stripped
            # key ระดับเดียวกับ healthcheck = ออกนอก block แล้ว
            if re.match(r"^    [A-Za-z_]", line):
                break

    raise AssertionError(
        "ไม่พบ healthcheck ของ service `backend` — ถ้าตั้งใจถอดออก ต้องแก้เทสต์นี้ด้วย"
    )


async def test_swarm_healthcheck_is_wired_to_the_503():
    """🔗 ถ้าไม่มีเทสต์นี้ การแก้ 503 จะไร้ผล — ต้องมีคน *ใช้* status code นั้น

    `curl -f` คือตัวแปลง "status >= 400" ให้เป็น exit code != 0 ที่ Swarm เข้าใจ
    ถ้ามีใครถอด `-f` ออก หรือเปลี่ยนไปยิง path อื่น 503 ที่เพิ่งทำไปก็ไม่มีความหมาย
    """
    if _find_compose_file() is None:
        pytest.skip(
            "ไม่พบ docker-compose.app.yml — รันเทสต์นี้จากราก repo (บน host) "
            "หรือเพิ่ม mount ของไฟล์ compose เข้า docker-compose.test.yml"
        )

    test_cmd = _backend_healthcheck_test()

    assert "curl" in test_cmd, f"healthcheck ต้องใช้ curl: {test_cmd}"
    assert re.search(r'["\s]-f["\s]', test_cmd), (
        f"🔴 ขาด `-f` — curl จะ exit 0 แม้ได้ 503 ⇒ Swarm นับ task ที่ DB หลุดว่า healthy: {test_cmd}"
    )
    assert "/health" in test_cmd, f"ต้องยิงไปที่ /health (path ที่คืน 503): {test_cmd}"
