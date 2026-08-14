import discord
from discord import app_commands
from discord.ext import commands
import datetime

from services.api_client import api_client, APIException

THAI_TZ = datetime.timezone(datetime.timedelta(hours=7))

# 🏷️ ป้ายสถานะกิจกรรม (ไทย)
ACTIVITY_STATUS_LABELS = {
    "upcoming": "🟦 กำลังจะมา",
    "ongoing": "🟨 กำลังดำเนินการ",
    "completed": "🟩 เสร็จสิ้น",
    "cancelled": "⬛ ยกเลิก",
}


def _format_thai_date(date_str: str) -> str:
    """'2026-10-15' → '15/10/2569' (พ.ศ.)"""
    try:
        d = datetime.datetime.strptime(str(date_str), "%Y-%m-%d").date()
        return f"{d.day}/{d.month}/{d.year + 543}"
    except (ValueError, TypeError):
        return str(date_str)


def _render_activity_embed(activity: dict, title: str = "🎪 กิจกรรมที่กำลังจะมาถึง", color: discord.Color = discord.Color.purple()) -> discord.Embed:
    """สร้าง embed กิจกรรมหนึ่งกิจกรรม — ดึง metadata (location_url, tags, agenda) มาใช้"""
    meta = activity.get("metadata") or {}
    if not isinstance(meta, dict):
        meta = {}

    status_label = ACTIVITY_STATUS_LABELS.get(activity.get("status"), activity.get("status", "upcoming"))
    embed = discord.Embed(
        title=f"📢 {activity.get('title', 'กิจกรรม')}",
        description=f"{status_label} · วันที่ **{_format_thai_date(activity.get('activity_date'))}**\n⏱️ ชั่วโมงจิตอาสา: {activity.get('base_hours', 0)} ชม.",
        color=color,
    )

    # 📍 สถานที่
    location_url = meta.get("location_url")
    location_name = meta.get("location_name")
    if location_url or location_name:
        text = ""
        if location_name:
            text += f"**{location_name}** "
        if isinstance(location_url, str) and location_url:
            if location_url.startswith("http"):
                text += f"[📍 คลิกเพื่อดู Google Maps]({location_url})"
            else:
                text += f"[📍 {location_url}](https://www.google.com/maps/search/?api=1&query={location_url})"
        embed.add_field(name="📍 สถานที่", value=text.strip() or "—", inline=False)

    # 📋 กำหนดการ
    agenda = meta.get("agenda")
    if agenda:
        if isinstance(agenda, list):
            lines = "\n".join(f"• {str(i).strip()}" for i in agenda if str(i).strip())
        else:
            lines = "\n".join(f"• {i.strip()}" for i in str(agenda).split("|") if i.strip())
        if lines:
            embed.add_field(name="📋 กำหนดการคร่าว ๆ", value=lines[:1024], inline=False)

    # 🏷️ แท็ก
    tags = meta.get("tags")
    if tags:
        if isinstance(tags, list):
            tag_str = " · ".join(f"#{str(t)}" for t in tags if str(t).strip())
        else:
            tag_str = " · ".join(f"#{t.strip()}" for t in str(tags).split(",") if t.strip())
        if tag_str:
            embed.add_field(name="🏷️ หมวดหมู่", value=tag_str, inline=False)

    # 👥 ผู้เข้าร่วม
    embed.add_field(name="👥 ผู้เข้าร่วม", value=f"{activity.get('participant_count', 0)} คน", inline=True)

    description = activity.get("description")
    if description and str(description).strip():
        embed.add_field(name="📄 รายละเอียด", value=str(description)[:1024], inline=False)

    embed.set_footer(text="ระบบบันทึกกิจกรรมและผู้เข้าร่วม")
    return embed


class ActivityCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="activities", description="ดูรายการกิจกรรมที่กำลังจะมาถึงของห้อง")
    async def activities(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            headers = {"X-Discord-Id": str(interaction.user.id)}
            # 🚨 แทรก target_type="server" — backend route คือ /{server_id}/activities
            activities_data = await api_client.request(
                "GET", f"/{interaction.guild_id}/activities",
                params={"target_type": "server", "status": "upcoming"},
                headers=headers,
            )
            if not activities_data:
                return await interaction.followup.send("🎉 ยังไม่มีกิจกรรมที่กำลังจะมาถึงเลยครับ", ephemeral=True)

            # เรียงตามวัน
            upcoming = sorted(
                activities_data,
                key=lambda a: str(a.get("activity_date", "")),
            )

            # แสดงกิจกรรมใกล้สุด 5 กิจกรรม (embed มี field จำกัด)
            shown = upcoming[:5]
            embed = discord.Embed(
                title="🎪 กิจกรรมที่กำลังจะมาถึง",
                description=f"พบทั้งหมด **{len(upcoming)}** กิจกรรม แสดง **{len(shown)}** รายการที่ใกล้ที่สุด",
                color=discord.Color.purple(),
            )
            for activity in shown:
                meta = activity.get("metadata") or {}
                if not isinstance(meta, dict):
                    meta = {}
                location = meta.get("location_name") or meta.get("location_url") or "ไม่ระบุ"
                if isinstance(location, str) and location.startswith("http"):
                    location = "📍 มีลิงก์แผนที่"
                embed.add_field(
                    name=f"{_format_thai_date(activity.get('activity_date'))} — {activity.get('title')}",
                    value=(
                        f"⏱️ {activity.get('base_hours', 0)} ชม. · 👥 {activity.get('participant_count', 0)} คน\n"
                        f"📍 {location}\n"
                        f"🏷️ {', '.join(f'#{t}' for t in (meta.get('tags') or [])[:3]) if meta.get('tags') else ''}".strip()
                    ),
                    inline=False,
                )

            await interaction.followup.send(embed=embed)
        except APIException as e:
            await interaction.followup.send(f"❌ {e}", ephemeral=True)

    @app_commands.command(name="my_roles", description="เช็คว่างานหน้าต้องทำหน้าที่อะไร / ขึ้นรถบัสคันไหน")
    async def my_roles(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            headers = {"X-Discord-Id": str(interaction.user.id)}
            # 🚨 แทรก target_type="server" — backend route คือ /{server_id}/activities/me/roles
            roles = await api_client.request(
                "GET", f"/{interaction.guild_id}/activities/me/roles",
                params={"target_type": "server"},
                headers=headers,
            )
            if not roles:
                return await interaction.followup.send(
                    "🎈 คุณยังไม่ได้เข้าร่วมกิจกรรมใด ๆ ครับ\nพิมพ์ `/activities` เพื่อดูกิจกรรมของห้อง",
                    ephemeral=True,
                )

            # เอากิจกรรมที่ยังไม่จบ (upcoming/ongoing) + ที่ผ่านมา
            today = datetime.datetime.now(THAI_TZ).date()
            upcoming_roles = [r for r in roles if r.get("status") in ("upcoming", "ongoing")]
            past_roles = [
                r for r in roles
                if r.get("status") in ("completed", "cancelled")
                or (r.get("activity_date") and datetime.datetime.strptime(str(r["activity_date"]), "%Y-%m-%d").date() < today)
            ]

            embed = discord.Embed(
                title="🎪 หน้าที่ของฉันในกิจกรรม",
                description=f"พบทั้งหมด **{len(roles)}** รายการ (ยังไม่จบ {len(upcoming_roles)})",
                color=discord.Color.purple(),
            )

            # 📅 กิจกรรมที่ยังมาไม่ถึง → โชว์เบอร์รถบัส (metadata.bus_number)
            if upcoming_roles:
                for r in sorted(upcoming_roles, key=lambda x: str(x.get("activity_date", ""))):
                    pm = r.get("participant_metadata") or {}
                    if not isinstance(pm, dict):
                        pm = {}
                    role_label = {
                        "participant": "ผู้เข้าร่วม",
                        "staff": "ทีมงาน",
                        "leader": "หัวหน้ากลุ่ม",
                    }.get(r.get("role_type"), r.get("role_type", "ผู้เข้าร่วม"))
                    detail = r.get("role_detail") or role_label
                    bus = pm.get("bus_number")
                    bus_line = f"\n🚌 ขึ้นรถบัสคัน **{bus}**" if bus else ""
                    embed.add_field(
                        name=f"📅 {_format_thai_date(r.get('activity_date'))} — {r.get('title')}",
                        value=(
                            f"**หน้าที่:** {detail}\n"
                            f"⏱️ ชั่วโมง: {r.get('earned_hours', r.get('base_hours', 0))} ชม.{bus_line}"
                        ),
                        inline=False,
                    )
            else:
                embed.add_field(name="📭 กิจกรรมที่ยังมาไม่ถึง", value="ไม่มี", inline=False)

            # 🏁 ประวัติที่ผ่านมา (ไม่บังคับ แต่ช่วยดูผลงาน)
            if past_roles:
                past_text = "\n".join(
                    f"• **{r.get('title')}** — {r.get('role_detail') or 'ผู้เข้าร่วม'} ({_format_thai_date(r.get('activity_date'))})"
                    for r in past_roles[:5]
                )
                embed.add_field(name="🏁 ที่ผ่านมา", value=past_text[:1024], inline=False)

            await interaction.followup.send(embed=embed, ephemeral=True)
        except APIException as e:
            await interaction.followup.send(f"❌ {e}", ephemeral=True)


async def setup(bot):
    await bot.add_cog(ActivityCommands(bot))
