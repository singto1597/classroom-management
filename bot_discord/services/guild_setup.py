"""🏗️ ตั้งเซิร์ฟเวอร์ Discord ให้พร้อมใช้ตั้งแต่บอทเข้าร่วม

═══════════════════════════════════════════════════════════════════════════════
🎯 ทำไมต้องสร้างช่องเอง
═══════════════════════════════════════════════════════════════════════════════
เดิมเซิร์ฟเวอร์ใหม่ **เงียบสนิท** จนกว่าแอดมินจะพิมพ์ `/set_channel`,
`/set_birthday_channel`, `/set_minor_channel` ครบทุกช่อง — และคนส่วนใหญ่ไม่รู้ว่า
ต้องทำ (ไม่มีอะไรบอก เพราะบอทไม่ส่งอะไรเลย) ⇒ บอทจึงต้องสร้างช่องที่มันใช้เอง
ตอนเข้าร่วม แล้วแจ้งแอดมินว่าต้องทำอะไรต่อ

═══════════════════════════════════════════════════════════════════════════════
🔑 กฎที่ต้องถือ
═══════════════════════════════════════════════════════════════════════════════
1. **idempotent** — ช่องชื่อซ้ำที่มีอยู่แล้วให้ใช้ของเดิม ห้ามสร้างซ้ำ
   (Discord ไม่บังคับ unique ชื่อ ⇒ สร้างซ้ำได้จริง และจะได้ช่องละ 2 อันที่งงทั้งห้อง)
2. **ไม่ล้มทั้งงานเพราะช่องเดียว** — บอทอาจไม่มีสิทธิ์ Manage Channels
   หรือโดน rate limit ⇒ พยายามทีละช่อง เก็บที่สำเร็จไว้ก่อน แล้ว log ที่พลาด
3. **บันทึกกับ backend แบบไม่ทับของแอดมิน** — `POST /{server_id}/channels/auto`
   เติมเฉพาะคอลัมน์ที่ว่าง (ดู `apply_channel_defaults` ฝั่ง backend)
4. **ยังไม่ผูกห้อง = ไม่ใช่ error** — ปกติบอทเข้าเซิร์ฟเวอร์ก่อน `/setup_room`
   ⇒ backend จะตอบ 404 ซึ่งแปลว่า "ยังไม่มีที่ให้บันทึก" ไม่ใช่ "พัง"
"""

import logging
from typing import Dict

import discord

from services.api_client import api_client, APIException

logger = logging.getLogger("DISCORD_BOT")

# (ชื่อช่อง, คำอธิบาย/หัวข้อ) — ลำดับนี้คือลำดับที่บอทพยายามสร้าง
CHANNEL_SPECS: tuple[tuple[str, str], ...] = (
    ("announcement", "📢 ประกาศและแจ้งเตือนหลักของห้อง (สรุปตาราง/งาน/เงิน)"),
    ("birthday", "🎂 อวยพรวันเกิดสมาชิกในห้อง"),
    ("info", "ℹ️ ข้อมูลห้องและคู่มือการใช้งานบอท"),
)

REASON = "Classroom-Sync: สร้างช่องที่บอทใช้ส่งการแจ้งเตือน"


def _can_manage_channels(guild) -> bool:
    """บอทมีสิทธิ์ Manage Channels หรือไม่

    ⚠️ `guild.me` เป็น None ได้ถ้า cache ยังไม่พร้อม ⇒ ถ้าไม่แน่ใจให้ **ลองต่อ**
       (ปล่อยให้ Discord ตอบ Forbidden เอง) ดีกว่าเดาว่าไม่มีสิทธิ์แล้วไม่ทำอะไรเลย
    """
    me = getattr(guild, "me", None)
    if me is None:
        return True
    permissions = getattr(me, "guild_permissions", None)
    if permissions is None:
        return True
    return bool(getattr(permissions, "manage_channels", False))


async def ensure_room_channels(guild) -> Dict[str, int]:
    """สร้าง/หาช่องครบชุด คืน `{ชนิด: channel_id}` ของช่องที่พร้อมใช้จริง

    คืนเฉพาะช่องที่สำเร็จ — ผู้เรียกต้องถือว่า "ขาดได้" (เช่น ไม่มีสิทธิ์) ไม่ใช่ error
    """
    if not _can_manage_channels(guild):
        logger.warning(
            "⚠️ บอทไม่มีสิทธิ์ Manage Channels ในเซิร์ฟเวอร์ %s — สร้างช่องอัตโนมัติไม่ได้",
            getattr(guild, "id", "?"),
        )
        return {}

    existing = {channel.name: channel for channel in (getattr(guild, "text_channels", None) or [])}
    ensured: Dict[str, int] = {}

    for name, topic in CHANNEL_SPECS:
        channel = existing.get(name)
        if channel is None:
            try:
                channel = await guild.create_text_channel(name=name, topic=topic, reason=REASON)
            except discord.Forbidden:
                logger.warning("⚠️ สร้างช่อง #%s ไม่ได้ (ไม่มีสิทธิ์)", name)
                continue
            except discord.HTTPException:
                logger.exception("⚠️ สร้างช่อง #%s ไม่ได้ (Discord error)", name)
                continue
            existing[name] = channel
            logger.info("✅ สร้างช่อง #%s (id=%s)", name, channel.id)
        ensured[name] = int(channel.id)

    return ensured


async def save_channels_to_backend(server_id: int, channels: Dict[str, int]) -> bool:
    """บันทึกช่องที่บอทสร้างเองลงห้องที่ผูก server นี้ — คืน False ถ้ายังผูกไม่ถึง

    🔑 ใช้ system RPC (`verify_api_key`) เพราะตอน `on_guild_join` ยังไม่มีผู้ใช้ที่ล็อกอิน
       (ดู `POST /{target_id}/channels/auto` ฝั่ง backend)
    """
    if not channels:
        return False
    try:
        await api_client.request(
            "POST",
            f"/{int(server_id)}/channels/auto",
            params={"target_type": "server"},
            json={"channels": {name: int(cid) for name, cid in channels.items()}},
        )
        return True
    except APIException as e:
        # 404 = ยังไม่ได้ `/setup_room` ⇒ เรื่องปกติ ไม่ใช่ความล้มเหลวที่ต้องตื่นตระหนก
        logger.info("ยังบันทึกช่องอัตโนมัติไม่ได้ (server_id=%s): %s", server_id, e)
        return False


def build_join_notice(channels: Dict[str, int], saved: bool) -> discord.Embed:
    """ข้อความต้อนรับแอดมินหลังบอทเข้าร่วม — บอกว่าสร้างอะไร และต้องทำอะไรต่อ"""
    if channels:
        created = "\n".join(f"• <#{cid}> — `{name}`" for name, cid in channels.items())
    else:
        created = "• ยังสร้างช่องไม่ได้ — บอทต้องมีสิทธิ์ **Manage Channels**"

    if saved:
        saved_line = "✅ บันทึกช่องเหล่านี้เข้าห้องในเว็บแล้ว"
    else:
        saved_line = (
            "ℹ️ ยังไม่ได้ผูกเซิร์ฟเวอร์นี้กับห้องในเว็บ — "
            "พิมพ์ `/setup_room` เพื่อผูกห้อง (ช่องที่สร้างไว้จะถูกบันทึกให้อัตโนมัติ)"
        )

    embed = discord.Embed(
        title="👋 Classroom-Sync เข้าร่วมเซิร์ฟเวอร์แล้ว",
        description=f"{created}\n\n{saved_line}",
        color=discord.Color.green(),
    )
    embed.add_field(
        name="ขั้นตอนถัดไป",
        value=(
            "1. `/setup_room` — ผูกเซิร์ฟเวอร์กับห้องที่สร้างไว้ในเว็บ\n"
            "2. `/set_time` — ตั้งเวลาสรุปรายวัน (ถ้าไม่ใช่ 19:00)\n"
            "3. `/mute` / `/unmute` — ปิด/เปิดการแจ้งเตือนเป็นรายช่องได้ทุกเมื่อ"
        ),
        inline=False,
    )
    embed.set_footer(text="ช่องที่ปิดการแจ้งเตือนแล้ว บอทจะไม่ส่งข้อความใด ๆ ในช่องนั้น")
    return embed


async def send_join_notice(guild, channels: Dict[str, int], saved: bool) -> None:
    """ส่งข้อความต้อนรับถ้าทำได้ — ล้มเหลวต้องไม่ทำให้ join ล้ม (แค่ log)"""
    channel = getattr(guild, "system_channel", None)
    if channel is None:
        logger.info("เซิร์ฟเวอร์ %s ไม่มี system channel — ข้ามข้อความต้อนรับ", getattr(guild, "id", "?"))
        return
    try:
        await channel.send(embed=build_join_notice(channels, saved))
    except (discord.Forbidden, discord.HTTPException):
        logger.warning("ส่งข้อความต้อนรับไม่ได้ (server_id=%s)", getattr(guild, "id", "?"))
