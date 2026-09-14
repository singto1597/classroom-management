"""💰 คำสั่งการเงินใน Discord — `/finance summary|debtors|collection|my-debts`

## หลักการของ cog นี้: **โง่ที่สุดเท่าที่จะเป็นได้**

repo นี้ไม่มี test harness ของบอท → cog ไม่ถูก CI ตรวจ ทุกอย่างที่ "คิด" ได้
(params, validate, แปลงตัวเลข/วันที่, ประกอบ embed) อยู่ใน `services/finance_api.py`
cog ทำแค่ 4 อย่าง: `defer()` → เรียกฟังก์ชัน → `followup.send(embed=...)` → จับ error

## กฎที่ยึดทุกคำสั่ง

- **`defer()` ก่อนเรียก API เสมอ** — กฎ 3 วินาทีของ Discord (API หลังบ้านช้ากว่านั้นได้ง่าย ๆ)
- **ตอบเป็น `discord.Embed` เสมอ** — ห้ามส่งข้อความดิบ
- **error เป็น ephemeral เสมอ** — ข้อความ error อาจมีรายละเอียดภายใน ไม่ควรโชว์ทั้งห้อง
- **`my-debts` เป็น ephemeral ทั้งเส้น** — เป็นข้อมูลส่วนบุคคลของนักเรียน (defer + followup)
- **`summary` รับ month/year เป็น `Choice`** — กันผู้ใช้พิมพ์เลขเดือนนอกช่วง และบังคับ
  "คู่กันหรือไม่ส่งเลย" ที่ `finance_api.validate_period`
"""
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from services import finance_api
from services.api_client import APIException

MONTH_CHOICES = [
    app_commands.Choice(name=f"{i}. {finance_api.THAI_MONTHS[i - 1]}", value=i)
    for i in range(1, 13)
]


@app_commands.guild_only()
class FinanceCommands(commands.Cog):
    """คำสั่งการเงิน — ครู/เหรัญญิกดูภาพรวมของห้อง และนักเรียนดูหนี้ของตัวเอง"""

    finance = app_commands.Group(name="finance", description="คำสั่งการเงินของห้องเรียน")

    def __init__(self, bot):
        self.bot = bot

    # ------------------------------------------------------------------ helpers
    async def _reply(self, interaction: discord.Interaction, embed: discord.Embed, ephemeral: bool) -> None:
        """ส่ง embed — ใช้ `followup` เพราะทุกคำสั่ง `defer()` ไปแล้ว."""
        await interaction.followup.send(embed=embed, ephemeral=ephemeral)

    async def _reply_error(self, interaction: discord.Interaction, error: Exception) -> None:
        """error เป็น ephemeral เสมอ + log ไว้ที่ console ของบอท.

        ⚠️ จับ `Exception` กว้าง ไม่ใช่แค่ `APIException` — ถ้าปล่อยให้หลุด ผู้ใช้จะเห็น
        "The application did not respond" ซึ่งวินิจฉัยอะไรไม่ได้เลย (บอทไม่มี harness ให้ debug)

        `ValueError` = ข้อความ validate ของเราเอง (เช่น "ต้องระบุเดือนและปีพร้อมกัน")
        ⇒ ต้องแสดงข้อความนั้นตรง ๆ **ห้ามกลายเป็น "ข้อผิดพลาดที่ไม่คาดคิด"** ไม่งั้นผู้ใช้
        ไม่มีทางรู้ว่าต้องแก้ input ยังไง
        """
        if isinstance(error, (APIException, ValueError)):
            message = str(error)
        else:
            print(f"⚠️ [finance_cmd] {type(error).__name__}: {error}")
            message = f"เกิดข้อผิดพลาดที่ไม่คาดคิด ({type(error).__name__}) กรุณาแจ้งผู้ดูแลระบบครับ"
        try:
            await interaction.followup.send(f"❌ {message}", ephemeral=True)
        except discord.HTTPException:
            # followup ถูกใช้ไปแล้ว/หมดอายุ — กลืนไว้ ไม่ให้ cog พังทั้งตัว
            pass

    # ------------------------------------------------------------------ /finance summary
    @finance.command(name="summary", description="ดูภาพรวมการเงินของห้อง (ครู/เหรัญญิก)")
    @app_commands.describe(
        month="เดือนที่ต้องการดู (ต้องเลือกคู่กับปี)",
        year="ปี ค.ศ. เช่น 2026 (ต้องเลือกคู่กับเดือน) — เว้นว่างทั้งคู่ = ภาพรวมทั้งหมด",
    )
    @app_commands.choices(month=MONTH_CHOICES)
    async def finance_summary(
        self,
        interaction: discord.Interaction,
        month: Optional[app_commands.Choice[int]] = None,
        year: Optional[app_commands.Range[int, 2000, 2100]] = None,
    ):
        await interaction.response.defer()
        try:
            month_value = month.value if month else None
            year_value = int(year) if year is not None else None
            data = await finance_api.get_summary(
                interaction.guild_id, interaction.user.id, month=month_value, year=year_value
            )
            embed = finance_api.build_summary_embed(data, month_value, year_value)
            await self._reply(interaction, embed, ephemeral=False)
        except Exception as e:  # noqa: BLE001 — ดูเหตุผลใน _reply_error
            await self._reply_error(interaction, e)

    # ------------------------------------------------------------------ /finance debtors
    @finance.command(name="debtors", description="ดูรายชื่อลูกหนี้ค้างชำระทั้งห้อง (ครู/เหรัญญิก)")
    async def finance_debtors(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            rows = await finance_api.get_debtors(interaction.guild_id, interaction.user.id)
            await self._reply(interaction, finance_api.build_debtors_embed(rows), ephemeral=False)
        except Exception as e:  # noqa: BLE001
            await self._reply_error(interaction, e)

    # ------------------------------------------------------------------ /finance collection
    @finance.command(name="collection", description="ดูสถานะแคมเปญเก็บเงินรายตัว (ครู/เหรัญญิก)")
    @app_commands.describe(collection_id="รหัสแคมเปญเก็บเงิน (ดูได้จากหน้าเว็บหรือข้อความแจ้งเก็บเงิน)")
    async def finance_collection(self, interaction: discord.Interaction, collection_id: int):
        await interaction.response.defer()
        try:
            data = await finance_api.get_collection(interaction.guild_id, interaction.user.id, collection_id)
            await self._reply(interaction, finance_api.build_collection_embed(data), ephemeral=False)
        except Exception as e:  # noqa: BLE001
            await self._reply_error(interaction, e)

    # ------------------------------------------------------------------ /finance my-debts
    @finance.command(name="my-debts", description="ดูยอดค้างชำระของตัวเอง (เห็นคนเดียว)")
    async def finance_my_debts(self, interaction: discord.Interaction):
        # 🔒 ephemeral ทั้งเส้น: defer ก็ต้อง ephemeral ไม่งั้น followup ที่ตามมาจะกลายเป็นข้อความสาธารณะ
        await interaction.response.defer(ephemeral=True)
        try:
            data = await finance_api.get_my_debts(interaction.guild_id, interaction.user.id)
            await self._reply(interaction, finance_api.build_my_debts_embed(data), ephemeral=True)
        except Exception as e:  # noqa: BLE001
            await self._reply_error(interaction, e)


async def setup(bot):
    await bot.add_cog(FinanceCommands(bot))
