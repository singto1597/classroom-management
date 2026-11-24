"""📣 worker เตือนผู้ค้างชำระรายวัน (Phase 6) — 1 replica, ตื่นทุก 5 นาที

═══════════════════════════════════════════════════════════════════════════════
🔁 ลำดับของแต่ละรอบ
═══════════════════════════════════════════════════════════════════════════════
1. เขียน heartbeat ลง Redis (ทุกรอบ — รวมรอบที่ยังไม่ถึงเวลาส่ง)
2. ถ้าวันนี้ยังไม่เคยส่ง **และ** เวลา (Asia/Bangkok) >= `FINANCE_REMINDER_HOUR:MINUTE`
   ⇒ ⏰ เรียก `FinanceService.apply_late_fees(as_of=วันนี้)` ก่อน (ถ้า
   `FINANCE_LATE_FEE_ENABLED`) — ออกค่าปรับล่าช้าให้บิลที่เลยกำหนดของทุกแคมเปญ
   ที่ตั้งนโยบายไว้ · ปลอดภัยต่อการเรียกซ้ำ (unique `uq_fines_late_fee_source`)
   ⇒ เรียก `FinanceService.dispatch_daily_reminders(as_of=วันนี้)`
   - กันซ้ำจริงอยู่ที่ DB (`reminder_dispatch_log` unique ต่อวัน/ช่อง)
     ⇒ worker ตายแล้วรีสตาร์ท/รันซ้ำหลัง 09:00 ไม่ทำให้ใครได้ข้อความสองครั้ง
3. ถ้าสคีมียังไม่ถูก migrate (`UndefinedTable`, SQLSTATE 42P01) ⇒ log + รอรอบถัดไป
   **ห้ามตาย** — worker ที่บูตพร้อม backend อาจเห็น DB ก่อน migration 0010 apply

⚠️ **โซนเวลาใช้ `FINANCE_REMINDER_TZ` (ค่าเริ่มต้น Asia/Bangkok) ไม่ใช่ `TZ` ของ container**
   — image ส่วนใหญ่มักตั้ง `TZ=UTC` ⇒ ถ้าอ่าน `TZ` ตรง ๆ เส้นแบ่ง "วันนี้" จะเลื่อนไป
   7 ชั่วโมง และการกันซ้ำต่อวันจะนับวันผิด
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import date, datetime
from typing import Optional
from zoneinfo import ZoneInfo

import asyncpg
import redis.asyncio as aioredis

from core.config import settings
from core.heartbeat import record_heartbeat
from services.finance_service import FinanceService

logger = logging.getLogger("API_WORKER_REMINDER")

# ตรวจทุก 5 นาที — งานจริงเกิดวันละครั้ง ต้นทุนการตื่นจึงต้องเล็กมาก
CHECK_INTERVAL_SECONDS = 300

# 🔑 heartbeat แยกจาก push_worker (`/health` อ่านคีย์ของ push เท่านั้น)
#    ⇒ ไม่ทับกัน และดูด้วย `redis-cli get finance_reminder_worker:last_beat` ได้
HEARTBEAT_KEY = "finance_reminder_worker:last_beat"

_TZ = ZoneInfo(settings.FINANCE_REMINDER_TZ)


def is_due(now: datetime, hour: int, minute: int) -> bool:
    """ถึงเวลาเตือนของวันนี้หรือยัง (เทียบแบบ (ชม., นาที) — ไม่สนวินาที)

    ⚠️ ไม่เทียบ "ช่วงแคบ" เช่น `hour == now.hour and minute == now.minute`:
       รอบตรวจ 5 นาทีอาจข้ามนาทีนั้นไปพอดี ⇒ ใช้ `>=` แล้วพึ่ง dedupe ที่ DB
    """
    return (now.hour, now.minute) >= (hour, minute)


def _is_missing_schema_error(exc: BaseException) -> bool:
    """`UndefinedTable` = migration ยังไม่ apply — worker ต้องรอ ไม่ใช่ตาย"""
    return getattr(exc, "sqlstate", None) == "42P01"


async def run_once(pool: asyncpg.Pool, *, now: Optional[datetime] = None) -> dict:
    """ตัดสินใจหนึ่งรอบ — คืน dict ที่ assert ได้ (ใช้ทั้งในลูปและในเทสต์)

    `status`:
      - `disabled`       ปิดด้วย config
      - `waiting`        ยังไม่ถึงเวลา (หรือเลยเวลาแต่ `last_dispatched` กันไว้ฝั่งลูป)
      - `schema_pending` สคีมาของ `reminder_dispatch_log` ยังไม่มี
      - `sent`           ส่งแล้ว (รวมกรณี "ส่งไปแล้ววันนี้" — สถิติ duplicate จะบอก)
    """
    moment = now or datetime.now(_TZ)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=_TZ)
    as_of = moment.astimezone(_TZ).date()

    if not settings.FINANCE_REMINDER_ENABLED:
        return {"status": "disabled", "as_of": as_of.isoformat()}

    if not is_due(moment, settings.FINANCE_REMINDER_HOUR, settings.FINANCE_REMINDER_MINUTE):
        return {"status": "waiting", "as_of": as_of.isoformat()}

    late_fee_stats: dict = {}
    try:
        if settings.FINANCE_LATE_FEE_ENABLED:
            late_fee_stats = await FinanceService.apply_late_fees(pool, as_of=as_of)
        stats = await FinanceService.dispatch_daily_reminders(pool, as_of=as_of)
    except Exception as e:  # noqa: BLE001 — แยกเฉพาะกรณี "รอสคีมา" ที่เหลือโยนต่อ
        if _is_missing_schema_error(e):
            logger.warning(
                "⏳ สคีมาการเงินยังไม่ครบ (migration ยังไม่ apply) "
                "— จะลองรอบถัดไป"
            )
            return {"status": "schema_pending", "as_of": as_of.isoformat()}
        raise

    return {"status": "sent", **stats, "late_fees": late_fee_stats}


async def run_forever(pool: asyncpg.Pool, redis=None) -> None:  # pragma: no cover — ลูปไม่รู้จบ
    """ลูปของ container — หยุดด้วย SIGTERM ตามปกติของ Swarm (grace period 10 วิ)"""
    last_dispatched: Optional[date] = None
    heartbeat_warned = False

    while True:
        if redis is not None:
            try:
                await record_heartbeat(redis, key=HEARTBEAT_KEY)
            except Exception:  # noqa: BLE001 — Redis ล่มห้ามทำให้ผู้เตือนตาย
                if not heartbeat_warned:
                    heartbeat_warned = True
                    logger.warning("เขียน heartbeat ลง Redis ไม่ได้ (จะลองรอบถัดไป)", exc_info=True)

        moment = datetime.now(_TZ)
        if last_dispatched != moment.date():
            try:
                result = await run_once(pool, now=moment)
                if result["status"] in ("sent", "disabled"):
                    last_dispatched = moment.date()
                    logger.info("📣 เตือนผู้ค้างชำระรอบวันนี้: %s", result)
                elif result["status"] == "schema_pending":
                    # ไม่ mark วันนี้ — จะลองใหม่รอบถัดไปจนกว่า migration จะ apply
                    pass
            except Exception:  # noqa: BLE001 — รอบนี้ล้ม รอบถัดไปลองใหม่
                logger.exception("ล้มเหลวในการส่งเตือนผู้ค้างชำระ (จะลองรอบถัดไป)")

        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


async def _main() -> None:  # pragma: no cover
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    pool = await asyncpg.create_pool(settings.DATABASE_URL, min_size=1, max_size=3)
    redis = aioredis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
    try:
        await run_forever(pool, redis)
    finally:
        await pool.close()
        await redis.aclose()


if __name__ == "__main__":  # pragma: no cover
    # `--once` ไว้ซ้อมบน staging: ทำงานหนึ่งรอบแล้วจบ (ไม่รอ 09:00 — ใช้เวลาจริง)
    parser = argparse.ArgumentParser(description="worker เตือนผู้ค้างชำระรายวัน")
    parser.add_argument("--once", action="store_true", help="ทำงานหนึ่งรอบแล้วออก")
    args = parser.parse_args()

    async def _once() -> None:
        logging.basicConfig(level=logging.INFO)
        pool = await asyncpg.create_pool(settings.DATABASE_URL, min_size=1, max_size=2)
        try:
            print(await run_once(pool))
        finally:
            await pool.close()

    if args.once:
        asyncio.run(_once())
    else:
        asyncio.run(_main())
