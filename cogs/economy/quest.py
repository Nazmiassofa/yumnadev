# cogs/economy/quest.py

import json
import discord
import logging

from discord.ext import commands
from utils.time import get_current_date_uptime, get_current_date
from utils.data.emot import WHITELINE
from services import economy

from utils.decorator.channel import check_master_channel
from services.dailyquest import DailyQuest


log = logging.getLogger(__name__)

class QuestCogs(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.dailyquest = DailyQuest(bot.redis)
        
    async def get_daily_claim_data(self, guild_id: int, user_id: int):
        key = f"yumna:dailyclaim:{guild_id}:{user_id}"
        data = await self.bot.redis.get(key)
        if not data:
            return {"last_date": None}
        if isinstance(data, (bytes, bytearray)):
            data = data.decode()
        try:
            return json.loads(data)
        except Exception:
            return {"last_date": None}

    async def set_daily_claim_data(self, guild_id: int, user_id: int, today: str):
        key = f"yumna:dailyclaim:{guild_id}:{user_id}"
        data = {"last_date": today}
        await self.bot.redis.set(key, json.dumps(data))


    @commands.command(name="daily")
    async def daily(self, ctx: commands.Context):
        """Lihat progress daily quest"""
        guild_id = ctx.guild.id
        user_id = ctx.author.id
        
        if guild_id != self.bot.main_guild_id:
            return

        date = get_current_date()

        today_dt = get_current_date_uptime()
        try:
            today_date = today_dt.date()
        except Exception:
            today_date = today_dt
        today_str = today_date.strftime("%Y-%m-%d")

        # Ambil quest dari redis
        progress = await self.dailyquest.get_quest(guild_id, user_id, date)

        # Ambil voice time dari economy
        voice_time = await economy.get_voice_time(guild_id, user_id, today_date)  # detik
        count_people = await economy.get_voice_session(guild_id, user_id)

        # Target quest harian
        QUEST_TARGETS = {
            "open_discuss": 1,
            "post_on_ᴠᴏɪꜱᴀ-ꜰᴇᴇᴅꜱ": 1,
            "post_on_ᴠᴏɪꜱᴀ-ᴍᴇᴍᴇ": 1,
            "post_on_ᴠᴏɪꜱᴀ-ꜰᴏᴏᴅꜱ": 1,
            "join_anotherworld": 1,
            "create_voice_room": 1,
            "voice_2_hours": 7200,  # 2 jam = 7200 detik
            "voice_with_5_people": 5,

        }

        # Mapping field → tampilan nama (bisa channel mention atau teks biasa)
        FIELD_DISPLAY = {
            "open_discuss": "Open a discuss on <#1371795699330449419>",
            "post_on_ᴠᴏɪꜱᴀ-ꜰᴇᴇᴅꜱ": f"Post something on <#1371794854442438717>",
            "post_on_ᴠᴏɪꜱᴀ-ᴍᴇᴍᴇ": f"Post something on <#1371794817453129800>",
            "post_on_ᴠᴏɪꜱᴀ-ꜰᴏᴏᴅꜱ": f"Post something on <#1415981198710276167>",
            "join_anotherworld": f"Join <#1378722381199183895>",
            "create_voice_room": "Create a voice room",
            "voice_2_hours": "⏱ Stay 2 hours in voice",
            "voice_with_5_people": "voice with 5 people",
        }

        embed = discord.Embed(
            title="📜 Daily Quest",
            description=f"{WHITELINE}",
            color=discord.Color.green()
        )

        for field, target in QUEST_TARGETS.items():
            if field == "voice_2_hours":
                current = voice_time
                display_value = f"{current // 60}m/{target // 60}m"
                
            elif field == "voice_with_5_people":
                current = count_people
                display_value = f"{current}/{target}"

            else:
                current = progress.get(field, 0)
                display_value = f"{current}/{target}"

            done = "`completed`" if current >= target else "`incomplete`"

            # pakai display name kalau ada di mapping, fallback ke field.title()
            field_name = FIELD_DISPLAY.get(field, field.replace("_", " ").title())

            embed.add_field(
                name=f"**{field_name}**",
                value=f"> `{display_value}` | {done} ",
                inline=False
            )
            
            embed.set_footer(text=f"{ctx.author.display_name} | dailyquest")

        await ctx.send(embed=embed)
    
    @commands.command(name="dailyclaim")
    async def daily_claim(self, ctx: commands.Context):
        """Claim hadiah dari daily quest"""
        guild_id = ctx.guild.id
        user_id = ctx.author.id
        username = str(ctx.author)
        
        if guild_id != self.bot.main_guild_id:
            log.info("[ COMMAND CALL ] --- Decline command from another guild")
            return

        today_date = get_current_date_uptime()
        today_str = today_date.strftime("%Y-%m-%d")

        # cek apakah sudah claim
        claim_data = await self.get_daily_claim_data(guild_id, user_id)
        if claim_data.get("last_date") == today_str:
            return await ctx.reply(
                embed=discord.Embed(
                    description="❌ Kamu sudah claim daily hari ini!",
                    color=discord.Color.red()
                )
            )

        # Ambil progress quest
        date = get_current_date()
        progress = await self.dailyquest.get_quest(guild_id, user_id, date)
        voice_time = await economy.get_voice_time(guild_id, user_id, today_date)
        count_people = await economy.get_voice_session(guild_id, user_id)

        # Target quest harian
        QUEST_TARGETS = {
            "open_discuss": 1,
            "post_on_ᴠᴏɪꜱᴀ-ꜰᴇᴇᴅꜱ": 1,
            "post_on_ᴠᴏɪꜱᴀ-ᴍᴇᴍᴇ": 1,
            "post_on_ᴠᴏɪꜱᴀ-ꜰᴏᴏᴅꜱ": 1,
            "join_anotherworld": 1,
            "create_voice_room": 1,
            "voice_2_hours": 7200,
            "voice_with_5_people": 5,
        }

        # Reward per quest
        QUEST_REWARDS = {
            "open_discuss": (200, 700),
            "post_on_ᴠᴏɪꜱᴀ-ꜰᴇᴇᴅꜱ": (200, 500),
            "post_on_ᴠᴏɪꜱᴀ-ᴍᴇᴍᴇ": (200, 500),
            "post_on_ᴠᴏɪꜱᴀ-ꜰᴏᴏᴅꜱ": (200, 500),
            "join_anotherworld": (250, 500),
            "create_voice_room": (250, 500),
            "voice_2_hours": (1500, 1200),
            "voice_with_5_people": (1500, 1500),
        }

        total_xp = 0
        total_balance = 0
        completed_count = 0
        total_quests = len(QUEST_TARGETS)

        for field, target in QUEST_TARGETS.items():
            if field == "voice_2_hours":
                current = voice_time
            elif field == "voice_with_5_people":
                current = count_people
            else:
                current = progress.get(field, 0)

            if current >= target:
                xp_gain, bal_gain = QUEST_REWARDS.get(field, (0, 0))
                total_xp += xp_gain
                total_balance += bal_gain
                completed_count += 1

        if total_xp == 0 and total_balance == 0:
            return await ctx.reply(
                embed=discord.Embed(
                    description="⚠️ Kamu belum menyelesaikan quest apapun hari ini.",
                    color=discord.Color.orange()
                )
            )

        # update economy
        result = await economy.earn_xp_balance(
            guild_id, user_id, username, total_xp, total_balance, "daily quest", "credit"
        )

        # simpan daily claim
        await self.set_daily_claim_data(guild_id, user_id, today_str)

        # buat embed hasil
        embed = discord.Embed(
            title="🎁 Daily Quest Claimed!",
            description=(
                f"-# Selamat, kamu mendapatkan total :\n"
                f"- XP: `{total_xp}`\n"
                f"- Balance: `{total_balance}` vcash\n\n"
                f"✅ Tugas diselesaikan: `{completed_count}/{total_quests}`"
            ),
            color=discord.Color.green()
        )
        embed.set_footer(text=f"Level: {result['new_level']} | XP: {result['xp']}")

        await ctx.reply(embed=embed)
        
async def setup(bot):
    await bot.add_cog(QuestCogs(bot))


