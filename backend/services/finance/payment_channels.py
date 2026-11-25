"""💳 [FIN-V2 / P2.4] ช่องทางชำระเงินของห้อง + PromptPay QR

═══════════════════════════════════════════════════════════════════════════════
🎯 ช่องทางคือ "ตัวตนของบัญชีที่เงินจะเข้า" ไม่ใช่แค่ป้ายชื่อ
═══════════════════════════════════════════════════════════════════════════════
ก่อนหน้านี้ `channel_id` ใน event/INV เป็นข้อความอิสระ ⇒ ตอบไม่ได้ว่าโอนเข้าบัญชีไหน,
ครูพิมพ์ชื่อบัญชีผิด, และ QR ที่ฝังในใบแจ้งหนี้ไม่สัมพันธ์กับยอดจริง
ตาราง `finance_payment_channels` (P1.1) แก้ด้วยการทำให้ช่องทางเป็น **แถวจริง**:

- เปิดใช้งานได้ **ไม่เกิน 3** ช่องทาง และมี **primary 1 ตัว** (ไม่ใช่ DB constraint
  ทั้งคู่ — ตรวจใต้ `_lock_room_money` ใน transaction เดียวกัน)
- `bank_transfer` เก็บเฉพาะ **เลขบัญชีที่ mask แล้ว**
- `promptpay` เก็บ **canonical ID เต็ม** ในคอลัมน์ `promptpay_id_masked`
  (ข้อจำกัดของ schema 0012 — ไม่มีคอลัมน์อื่นให้เก็บ) ⇒ **ห้ามส่งคอลัมน์นี้ออก API
  ตรง ๆ** ทุก response ต้องผ่าน `qr.mask_promptpay_id`
- QR สร้างจากฟังก์ชัน pure ใน `qr.py` — payload ไม่เคยออกจาก server

⚠️ กติกา MRO: อยู่ **ก่อน** `AccountsMixin` ใน `FinanceService` และใช้ชื่อเฉพาะ
   (`list_payment_channels`, `create_payment_channel`, …) — ไม่ชนกับ mixin ใด
⚠️ รูปแบบพารามิเตอร์เหมือน service อื่น (`server_id`/`room_id` → `resolve_room_id`)
   เพื่อให้เส้นทางบอท (`server_id`) ใช้ได้โดยไม่ต้องมีโค้ดพิเศษใน router
"""
import time
from typing import Optional

import asyncpg

from core.exceptions import RoomNotFoundError
from core.rbac import require_member, require_permission

from .base import _lock_room_money, service_logger
from .qr import (
    VALID_QR_MODES, QrError, build_promptpay_payload, mask_account_number,
    mask_promptpay_id, normalize_promptpay_id, render_qr_svg,
)

# 🎭 ชนิดช่องทางตาม DDL 0012 — `custom_qr` มีใน DB แต่ยังไม่รองรับการใช้งานจริง
VALID_CHANNEL_TYPES = ("cash", "bank_transfer", "promptpay", "custom_qr")

# 🔢 กติกา: เปิดใช้งานได้ไม่เกิน 3 ช่องทางต่อห้อง
MAX_ACTIVE_CHANNELS = 3

# 📋 คอลัมน์ที่ "ปลอดภัยจะส่งออก" — เลือกทีละคอลัมน์ ห้าม `SELECT *`
_CHANNEL_SELECT = """
    c.id, c.channel_type, c.label, c.wallet_account_id,
    a.account_name AS wallet_account_name,
    c.account_name, c.bank_name, c.account_number_masked, c.promptpay_id_masked,
    c.qr_mode, c.is_primary, c.is_active, c.sort_order,
    c.created_at, c.updated_at, c.deleted_at
"""

_CHANNEL_FROM = """
    FROM finance_payment_channels c
    LEFT JOIN finance_accounts a
           ON a.id = c.wallet_account_id AND a.deleted_at IS NULL
"""


def _clean(value: Optional[str]) -> Optional[str]:
    """ตัดช่องว่างหัว-ท้าย; ค่าว่าง/None → None"""
    if value is None:
        return None
    text = value.strip()
    return text or None


def _mask_stored_promptpay(value: Optional[str]) -> Optional[str]:
    """ค่าที่เก็บใน `promptpay_id_masked` → รูปที่ส่งออกได้

    ⚠️ คอลัมน์นี้เก็บ **canonical เต็ม** (ข้อจำกัด schema) — ถ้าค่าเสียหาย
       ให้ถอยไปใช้ mask ทั่วไป ไม่ใช่ปล่อยให้หน้าจอทั้งหน้า 500
    """
    if not value:
        return None
    try:
        return mask_promptpay_id(value)
    except QrError:
        return mask_account_number(value)


class PaymentChannelsMixin:
    """ช่องทางชำระเงิน (`finance_payment_channels`) + QR preview"""

    # ─────────────────────────────────────────────────────────────────────
    # ตัวช่วยภายใน
    # ─────────────────────────────────────────────────────────────────────
    @classmethod
    def _shape_channel(cls, row) -> dict:
        """แถว → dict สำหรับ response/audit (mask แล้วเท่านั้น)"""
        raw_promptpay = row["promptpay_id_masked"]
        raw_account = row["account_number_masked"]
        return {
            "id": row["id"],
            "channel_type": row["channel_type"],
            "label": row["label"],
            "wallet_account_id": row["wallet_account_id"],
            "wallet_account_name": row["wallet_account_name"],
            "account_name": row["account_name"],
            "bank_name": row["bank_name"],
            "account_number_masked": mask_account_number(raw_account) if raw_account else None,
            "promptpay_id_masked": _mask_stored_promptpay(raw_promptpay),
            "qr_mode": row["qr_mode"],
            "is_primary": row["is_primary"],
            "is_active": row["is_active"],
            "sort_order": row["sort_order"],
            "has_qr": bool(
                row["channel_type"] == "promptpay"
                and raw_promptpay
                and row["qr_mode"] in VALID_QR_MODES
            ),
        }

    @classmethod
    async def _assert_wallet_in_room(
        cls, conn: asyncpg.Connection, room_id: int, wallet_account_id: int
    ) -> None:
        """กระเป๋าต้องเป็นของห้องนี้และยังไม่ถูกลบ — กันการผูกข้ามห้องผ่าน API"""
        found = await conn.fetchval(
            """SELECT 1 FROM finance_accounts
               WHERE id = $1 AND room_id = $2 AND deleted_at IS NULL""",
            wallet_account_id, room_id,
        )
        if not found:
            raise ValueError("ไม่พบกระเป๋าเงินนี้ในห้องเรียน")

    @classmethod
    async def _count_active_channels(
        cls, conn: asyncpg.Connection, room_id: int, *, exclude_id: Optional[int] = None
    ) -> int:
        return await conn.fetchval(
            """SELECT COUNT(*) FROM finance_payment_channels
               WHERE room_id = $1 AND is_active AND deleted_at IS NULL
                 AND ($2::BIGINT IS NULL OR id <> $2)""",
            room_id, exclude_id,
        )

    @classmethod
    async def _has_primary(
        cls, conn: asyncpg.Connection, room_id: int, *, exclude_id: Optional[int] = None
    ) -> bool:
        return bool(await conn.fetchval(
            """SELECT 1 FROM finance_payment_channels
               WHERE room_id = $1 AND is_primary AND deleted_at IS NULL
                 AND ($2::BIGINT IS NULL OR id <> $2)
               LIMIT 1""",
            room_id, exclude_id,
        ))

    @classmethod
    async def _clear_primary(
        cls, conn: asyncpg.Connection, room_id: int, *, exclude_id: Optional[int] = None
    ) -> None:
        """ถอดสถานะ primary จากทุกตัว (ก่อนตั้งตัวใหม่ — partial unique กันชน)"""
        await conn.execute(
            """UPDATE finance_payment_channels
               SET is_primary = FALSE, updated_at = NOW()
               WHERE room_id = $1 AND is_primary AND deleted_at IS NULL
                 AND ($2::BIGINT IS NULL OR id <> $2)""",
            room_id, exclude_id,
        )

    @classmethod
    async def _promote_next_primary(
        cls, conn: asyncpg.Connection, room_id: int
    ) -> None:
        """ถ้าไม่มี primary ที่ active อยู่ → ตั้งตัวที่ sort_order น้อยสุดเป็น primary

        เรียกหลังปิดใช้งาน/ลบตัวที่เป็น primary — ระบบต้องมี QR หลักเสมอเมื่อยังมี
        ช่องทางที่ใช้ได้ (ถ้าไม่มีเหลือ = ไม่มี primary ซึ่งถูกต้อง)
        """
        has_active_primary = await conn.fetchval(
            """SELECT 1 FROM finance_payment_channels
               WHERE room_id = $1 AND is_primary AND is_active AND deleted_at IS NULL
               LIMIT 1""",
            room_id,
        )
        if has_active_primary:
            return
        await conn.execute(
            """UPDATE finance_payment_channels
               SET is_primary = TRUE, updated_at = NOW()
               WHERE id = (
                   SELECT id FROM finance_payment_channels
                   WHERE room_id = $1 AND is_active AND deleted_at IS NULL
                   ORDER BY sort_order ASC, id ASC
                   LIMIT 1
               )""",
            room_id,
        )

    @classmethod
    async def _next_sort_order(cls, conn: asyncpg.Connection, room_id: int) -> int:
        return await conn.fetchval(
            """SELECT COALESCE(MAX(sort_order), 0) + 10
               FROM finance_payment_channels WHERE room_id = $1""",
            room_id,
        )

    @classmethod
    async def _load_channel(
        cls,
        conn: asyncpg.Connection,
        room_id: int,
        channel_id: int,
        *,
        for_update: bool = False,
    ):
        """โหลดแถวช่องทางของห้อง (ยังไม่กรอง deleted — ผู้เรียกตัดสินใจเอง)"""
        lock = " FOR UPDATE OF c" if for_update else ""
        return await conn.fetchrow(
            f"""SELECT {_CHANNEL_SELECT} {_CHANNEL_FROM}
                WHERE c.id = $1 AND c.room_id = $2{lock}""",
            channel_id, room_id,
        )

    @staticmethod
    def _channel_fields_from_create(req) -> dict:
        """ตรวจฟิลด์ตามชนิดช่องทาง (create) → ค่าคอลัมน์ที่พร้อม INSERT"""
        channel_type = req.channel_type
        if channel_type not in VALID_CHANNEL_TYPES:
            raise ValueError("ชนิดช่องทางไม่ถูกต้อง")
        if channel_type == "custom_qr":
            raise ValueError("ยังไม่รองรับช่องทาง QR กำหนดเองในรอบนี้")

        label = _clean(req.label)
        if not label:
            raise ValueError("ชื่อช่องทางต้องไม่ว่าง")
        account_name = _clean(req.account_name)

        fields = {
            "channel_type": channel_type,
            "label": label,
            "account_name": account_name,
            "bank_name": None,
            "account_number_masked": None,
            "promptpay_id_masked": None,
            "qr_mode": None,
        }

        if channel_type == "bank_transfer":
            bank_name = _clean(req.bank_name)
            if not account_name:
                raise ValueError("ช่องทางโอนเงินต้องระบุชื่อบัญชี")
            if not bank_name:
                raise ValueError("ช่องทางโอนเงินต้องระบุธนาคาร")
            if not _clean(req.account_number):
                raise ValueError("ช่องทางโอนเงินต้องระบุเลขบัญชี")
            fields["bank_name"] = bank_name
            fields["account_number_masked"] = mask_account_number(req.account_number)
        elif channel_type == "promptpay":
            if not account_name:
                raise ValueError("ช่องทางพร้อมเพย์ต้องระบุชื่อบัญชี")
            if not _clean(req.promptpay_id):
                raise ValueError("ช่องทางพร้อมเพย์ต้องระบุเลขพร้อมเพย์")
            if req.qr_mode not in VALID_QR_MODES:
                raise ValueError("ช่องทางพร้อมเพย์ต้องเลือกรูปแบบ QR (open หรือ fixed)")
            # 🔴 canonical เต็มถูกเก็บในคอลัมน์ *_masked ตามข้อจำกัด schema 0012
            fields["promptpay_id_masked"] = normalize_promptpay_id(req.promptpay_id)
            fields["qr_mode"] = req.qr_mode

        return fields

    @staticmethod
    def _channel_fields_from_update(current, updates: dict) -> dict:
        """รวมค่าปัจจุบัน + ที่ส่งมา → ค่าคอลัมน์สุดท้ายที่ผ่านการตรวจแล้ว

        ⚠️ เมื่อ `channel_type` เปลี่ยน จะ **ล้างฟิลด์ของชนิดเดิม** โดยอัตโนมัติ
           (ไม่เก็บเลขบัญชี/พร้อมเพย์ค้างไว้ในช่องทางที่ไม่ใช้แล้ว)
        """
        channel_type = updates.get("channel_type", current["channel_type"])
        if channel_type not in VALID_CHANNEL_TYPES:
            raise ValueError("ชนิดช่องทางไม่ถูกต้อง")
        if channel_type == "custom_qr":
            raise ValueError("ยังไม่รองรับช่องทาง QR กำหนดเองในรอบนี้")

        label = _clean(updates.get("label", current["label"]))
        if not label:
            raise ValueError("ชื่อช่องทางต้องไม่ว่าง")

        account_name = _clean(updates.get("account_name", current["account_name"]))
        bank_name = _clean(updates.get("bank_name", current["bank_name"]))
        qr_mode = updates.get("qr_mode", current["qr_mode"])

        if "account_number" in updates:
            raw_account = _clean(updates["account_number"])
            account_masked = mask_account_number(raw_account) if raw_account else None
        else:
            account_masked = current["account_number_masked"]

        if "promptpay_id" in updates:
            raw_promptpay = _clean(updates["promptpay_id"])
            promptpay_canonical = (
                normalize_promptpay_id(raw_promptpay) if raw_promptpay else None
            )
        else:
            promptpay_canonical = current["promptpay_id_masked"]

        # 🧹 ฟิลด์ของชนิดอื่นต้องไม่ค้างอยู่ (ทั้งตอนเปลี่ยนชนิดและตอนแก้แถวเดิม)
        if channel_type != "promptpay":
            promptpay_canonical = None
            qr_mode = None
        if channel_type != "bank_transfer":
            account_masked = None
            bank_name = None

        if channel_type == "bank_transfer":
            if not account_name:
                raise ValueError("ช่องทางโอนเงินต้องระบุชื่อบัญชี")
            if not bank_name:
                raise ValueError("ช่องทางโอนเงินต้องระบุธนาคาร")
            if not account_masked:
                raise ValueError("ช่องทางโอนเงินต้องระบุเลขบัญชี")
        elif channel_type == "promptpay":
            if not account_name:
                raise ValueError("ช่องทางพร้อมเพย์ต้องระบุชื่อบัญชี")
            if not promptpay_canonical:
                raise ValueError("ช่องทางพร้อมเพย์ต้องระบุเลขพร้อมเพย์")
            if qr_mode not in VALID_QR_MODES:
                raise ValueError("ช่องทางพร้อมเพย์ต้องเลือกรูปแบบ QR (open หรือ fixed)")
        else:
            # cash: ไม่มีฟิลด์เฉพาะ — เก็บเฉพาะชื่อบัญชี (ถ้ามี)
            pass

        return {
            "channel_type": channel_type,
            "label": label,
            "account_name": account_name,
            "bank_name": bank_name,
            "account_number_masked": account_masked,
            "promptpay_id_masked": promptpay_canonical,
            "qr_mode": qr_mode,
        }

    # ─────────────────────────────────────────────────────────────────────
    # อ่าน
    # ─────────────────────────────────────────────────────────────────────
    @classmethod
    async def list_payment_channels(
        cls,
        pool: asyncpg.Pool,
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        user_id: Optional[int] = None,
        include_inactive: bool = False,
    ) -> list:
        """รายชื่อช่องทางของห้อง — primary มาก่อน แล้วเรียงตาม sort_order

        📖 สมาชิกห้องอ่านได้ (ต้องเปิด QR เพื่อจ่ายได้) แต่ต้องเป็นสมาชิกห้องนี้
        """
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_member(conn, target_room_id, user_id)

                where = ["c.room_id = $1", "c.deleted_at IS NULL"]
                if not include_inactive:
                    where.append("c.is_active")

                rows = await conn.fetch(
                    f"""SELECT {_CHANNEL_SELECT} {_CHANNEL_FROM}
                        WHERE {' AND '.join(where)}
                        ORDER BY c.is_primary DESC, c.sort_order ASC, c.id ASC""",
                    target_room_id,
                )
                result = [cls._shape_channel(r) for r in rows]

                await service_logger.log(
                    conn=conn, action="VIEW", actor_identifier=actor_identifier,
                    client_source=client_source, room_id=target_room_id, user_id=user_id,
                    entity_type="FINANCE_PAYMENT_CHANNEL", status="success",
                    endpoint_or_command="FinanceService.list_payment_channels",
                    execution_time_ms=int((time.time() - start_time) * 1000),
                )
                return result
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="VIEW", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_PAYMENT_CHANNEL", status="failed",
                        error_detail=str(e),
                        endpoint_or_command="FinanceService.list_payment_channels",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise e

    # ─────────────────────────────────────────────────────────────────────
    # เขียน
    # ─────────────────────────────────────────────────────────────────────
    @classmethod
    async def create_payment_channel(
        cls,
        pool: asyncpg.Pool,
        req,
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> dict:
        """เพิ่มช่องทางชำระเงิน 1 ช่องทาง"""
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")

                fields = cls._channel_fields_from_create(req)

                async with conn.transaction():
                    # 🔒 ล็อกห้องก่อน — primary/active count เป็น invariant ข้ามแถว
                    await _lock_room_money(conn, target_room_id)

                    if req.wallet_account_id is not None:
                        await cls._assert_wallet_in_room(
                            conn, target_room_id, req.wallet_account_id
                        )

                    is_active = bool(req.is_active)
                    if is_active and await cls._count_active_channels(
                        conn, target_room_id
                    ) >= MAX_ACTIVE_CHANNELS:
                        raise ValueError(
                            f"ห้องนี้เปิดใช้งานช่องทางครบ {MAX_ACTIVE_CHANNELS} ช่องทางแล้ว"
                        )

                    if req.is_primary and not is_active:
                        raise ValueError("ช่องทางหลักต้องเปิดใช้งาน")

                    # 🎯 primary ตัวแรก: ตั้งให้เองเมื่อยังไม่มี — ระบบต้องมี QR หลัก
                    is_primary = bool(req.is_primary)
                    if is_active and not is_primary and not await cls._has_primary(
                        conn, target_room_id
                    ):
                        is_primary = True
                    if is_primary:
                        # 🔴 clear ก่อน insert ไม่งั้นชน partial unique primary
                        await cls._clear_primary(conn, target_room_id)

                    sort_order = (
                        req.sort_order
                        if req.sort_order is not None
                        else await cls._next_sort_order(conn, target_room_id)
                    )

                    row = await conn.fetchrow(
                        f"""WITH inserted AS (
                                INSERT INTO finance_payment_channels
                                    (room_id, channel_type, label, wallet_account_id,
                                     account_name, bank_name, account_number_masked,
                                     promptpay_id_masked, qr_mode, is_primary, is_active,
                                     sort_order)
                                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                                RETURNING id, channel_type, label, wallet_account_id,
                                          account_name, bank_name, account_number_masked,
                                          promptpay_id_masked, qr_mode, is_primary,
                                          is_active, sort_order, created_at, updated_at,
                                          deleted_at
                            )
                            SELECT {_CHANNEL_SELECT}
                            FROM inserted c
                            LEFT JOIN finance_accounts a
                                   ON a.id = c.wallet_account_id AND a.deleted_at IS NULL""",
                        target_room_id, fields["channel_type"], fields["label"],
                        req.wallet_account_id, fields["account_name"],
                        fields["bank_name"], fields["account_number_masked"],
                        fields["promptpay_id_masked"], fields["qr_mode"],
                        is_primary, is_active, sort_order,
                    )

                    await service_logger.log(
                        conn=conn, action="CREATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_PAYMENT_CHANNEL",
                        entity_id=str(row["id"]), status="success",
                        new_values=cls._shape_channel(row),
                        endpoint_or_command="FinanceService.create_payment_channel",
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )
                return cls._shape_channel(row)
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="CREATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_PAYMENT_CHANNEL", status="failed",
                        error_detail=str(e),
                        endpoint_or_command="FinanceService.create_payment_channel",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def update_payment_channel(
        cls,
        pool: asyncpg.Pool,
        channel_id: int,
        req,
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> dict:
        """แก้ไขช่องทาง — PATCH เฉพาะฟิลด์ที่ส่งมา"""
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")

                updates = req.model_dump(exclude_unset=True)

                async with conn.transaction():
                    # 🔒 ล็อกห้องก่อนอ่าน-แก้แถว
                    await _lock_room_money(conn, target_room_id)

                    current = await cls._load_channel(
                        conn, target_room_id, channel_id, for_update=True
                    )
                    if not current or current["deleted_at"] is not None:
                        raise ValueError("ไม่พบช่องทางชำระเงินนี้")

                    wallet_account_id = updates.get(
                        "wallet_account_id", current["wallet_account_id"]
                    )
                    if wallet_account_id is not None:
                        await cls._assert_wallet_in_room(
                            conn, target_room_id, wallet_account_id
                        )

                    fields = cls._channel_fields_from_update(current, updates)

                    new_active = bool(updates.get("is_active", current["is_active"]))
                    if new_active and not current["is_active"]:
                        if await cls._count_active_channels(
                            conn, target_room_id, exclude_id=channel_id
                        ) >= MAX_ACTIVE_CHANNELS:
                            raise ValueError(
                                f"ห้องนี้เปิดใช้งานช่องทางครบ {MAX_ACTIVE_CHANNELS} ช่องทางแล้ว"
                            )

                    requested_primary = bool(
                        updates.get("is_primary", current["is_primary"])
                    )
                    if "is_primary" in updates and updates["is_primary"] and not new_active:
                        raise ValueError("ช่องทางหลักต้องเปิดใช้งาน")
                    # ปิดใช้งาน = พ้นจากสถานะหลักอัตโนมัติ (promote ตัวถัดไปด้านล่าง)
                    if not new_active:
                        requested_primary = False

                    if requested_primary and not current["is_primary"]:
                        # 🔴 clear ก่อน UPDATE ไม่งั้นชน partial unique primary
                        await cls._clear_primary(
                            conn, target_room_id, exclude_id=channel_id
                        )

                    sort_order = updates.get("sort_order", current["sort_order"])
                    row = await conn.fetchrow(
                        f"""WITH updated AS (
                                UPDATE finance_payment_channels
                                SET channel_type = $3, label = $4, wallet_account_id = $5,
                                    account_name = $6, bank_name = $7,
                                    account_number_masked = $8, promptpay_id_masked = $9,
                                    qr_mode = $10, is_primary = $11, is_active = $12,
                                    sort_order = $13, updated_at = NOW()
                                WHERE id = $1 AND room_id = $2
                                RETURNING id, channel_type, label, wallet_account_id,
                                          account_name, bank_name, account_number_masked,
                                          promptpay_id_masked, qr_mode, is_primary,
                                          is_active, sort_order, created_at, updated_at,
                                          deleted_at
                            )
                            SELECT {_CHANNEL_SELECT}
                            FROM updated c
                            LEFT JOIN finance_accounts a
                                   ON a.id = c.wallet_account_id AND a.deleted_at IS NULL""",
                        channel_id, target_room_id,
                        fields["channel_type"], fields["label"], wallet_account_id,
                        fields["account_name"], fields["bank_name"],
                        fields["account_number_masked"], fields["promptpay_id_masked"],
                        fields["qr_mode"], requested_primary, new_active, sort_order,
                    )

                    # ปิด/ถอด primary → ระบบต้องมี primary ถ้ายังมีช่องทาง active
                    if not requested_primary:
                        await cls._promote_next_primary(conn, target_room_id)
                        row = await cls._load_channel(conn, target_room_id, channel_id)

                    await service_logger.log(
                        conn=conn, action="UPDATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_PAYMENT_CHANNEL",
                        entity_id=str(channel_id), status="success",
                        old_values=cls._shape_channel(current),
                        new_values=cls._shape_channel(row),
                        endpoint_or_command="FinanceService.update_payment_channel",
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )
                return cls._shape_channel(row)
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="UPDATE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_PAYMENT_CHANNEL", entity_id=str(channel_id),
                        status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.update_payment_channel",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise e

    @classmethod
    async def delete_payment_channel(
        cls,
        pool: asyncpg.Pool,
        channel_id: int,
        client_source: str,
        actor_identifier: str,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> dict:
        """ปิดช่องทาง = soft delete เท่านั้น (+ promote primary ตัวถัดไป)"""
        start_time = time.time()
        target_room_id = room_id
        try:
            async with pool.acquire() as conn:
                target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
                await require_permission(conn, target_room_id, user_id, "MANAGE_FINANCE")

                async with conn.transaction():
                    # 🔒 ล็อกห้องก่อนอ่าน-แก้แถว
                    await _lock_room_money(conn, target_room_id)

                    current = await cls._load_channel(
                        conn, target_room_id, channel_id, for_update=True
                    )
                    if not current or current["deleted_at"] is not None:
                        raise ValueError("ไม่พบช่องทางชำระเงินนี้")

                    await conn.execute(
                        """UPDATE finance_payment_channels
                           SET deleted_at = NOW(), is_active = FALSE, is_primary = FALSE,
                               updated_at = NOW()
                           WHERE id = $1""",
                        channel_id,
                    )
                    await cls._promote_next_primary(conn, target_room_id)

                    await service_logger.log(
                        conn=conn, action="DELETE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_PAYMENT_CHANNEL",
                        entity_id=str(channel_id), status="success",
                        old_values=cls._shape_channel(current),
                        endpoint_or_command="FinanceService.delete_payment_channel",
                        execution_time_ms=int((time.time() - start_time) * 1000),
                    )
                return {"status": "success", "message": "ปิดใช้งานช่องทางชำระเงินแล้ว"}
        except Exception as e:
            exec_time = int((time.time() - start_time) * 1000)
            try:
                async with pool.acquire() as log_conn:
                    await service_logger.log(
                        conn=log_conn, action="DELETE", actor_identifier=actor_identifier,
                        client_source=client_source, room_id=target_room_id, user_id=user_id,
                        entity_type="FINANCE_PAYMENT_CHANNEL", entity_id=str(channel_id),
                        status="failed", error_detail=str(e),
                        endpoint_or_command="FinanceService.delete_payment_channel",
                        execution_time_ms=exec_time,
                    )
            except Exception:
                pass
            raise e

    # ─────────────────────────────────────────────────────────────────────
    # QR (อ่านอย่างเดียว — ไม่เขียน DB ไม่ log payload)
    # ─────────────────────────────────────────────────────────────────────
    @classmethod
    async def _load_channel_for_qr(
        cls,
        conn: asyncpg.Connection,
        room_id: int,
        channel_id: int,
        amount,
    ):
        row = await cls._load_channel(conn, room_id, channel_id)
        if not row or row["deleted_at"] is not None:
            raise RoomNotFoundError("ไม่พบช่องทางชำระเงินนี้")
        if not row["is_active"]:
            raise ValueError("ช่องทางนี้ปิดใช้งานอยู่")
        if row["channel_type"] != "promptpay":
            raise QrError("CHANNEL_QR_UNSUPPORTED", "ช่องทางนี้ไม่รองรับการสร้าง QR")
        if not row["promptpay_id_masked"]:
            raise QrError("INVALID_PROMPTPAY_ID", "ช่องทางนี้ยังไม่มีเลขพร้อมเพย์")
        return row

    @classmethod
    async def get_channel_qr_svg(
        cls,
        pool: asyncpg.Pool,
        channel_id: int,
        amount,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> str:
        """สร้าง SVG ของ QR ช่องทางนี้ — ไม่แตะ DB (อ่านอย่างเดียว 100%)

        🔎 `amount` เป็น `Decimal | None` ตาม query string — ส่งเข้า
           `build_promptpay_payload` ตรง ๆ (ห้ามแปลงเป็น float)
        """
        async with pool.acquire() as conn:
            target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
            await require_member(conn, target_room_id, user_id)
            row = await cls._load_channel_for_qr(
                conn, target_room_id, channel_id, amount
            )
            payload = build_promptpay_payload(
                promptpay_id=row["promptpay_id_masked"],
                qr_mode=row["qr_mode"],
                amount=amount,
            )
            return render_qr_svg(payload)

    @classmethod
    async def preview_channel_qr(
        cls,
        pool: asyncpg.Pool,
        req,
        server_id: Optional[int] = None,
        room_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> dict:
        """พรีวิว QR ก่อนบันทึกช่องทาง — คืนเฉพาะ SVG (ห้ามคืน payload)"""
        async with pool.acquire() as conn:
            target_room_id = await cls.resolve_room_id(conn, server_id, room_id)
            await require_member(conn, target_room_id, user_id)
            row = await cls._load_channel_for_qr(
                conn, target_room_id, req.channel_id, req.amount
            )
            payload = build_promptpay_payload(
                promptpay_id=row["promptpay_id_masked"],
                qr_mode=row["qr_mode"],
                amount=req.amount,
            )
            return {"svg": render_qr_svg(payload)}
