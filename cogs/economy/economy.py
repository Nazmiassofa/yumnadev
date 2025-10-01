import discord
import json
import logging
import asyncio

from discord.ext import commands
from utils.helper.economy import xp_for_level
from utils.time import get_current_date

from utils.decorator.channel import check_master_channel
from utils.decorator.spender import requires_balance

from utils.time import get_current_date_uptime
from services import economy
from services.dailyquest import DailyQuest
from core import db

from utils.data.emot import (LEFTSWIPE,
                             RIGHTSWIPE,
                             WHITELINE
                             )

log = logging.getLogger(__name__)

class Economy(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.dailyquest = DailyQuest(bot.redis)

    async def get_absen_data(self, guild_id: int, user_id: int):
        key = f"yumna:absen:{guild_id}:{user_id}"
        data = await self.bot.redis.get(key)
        if not data:
            return {"last_date": None, "streak": 0}
        if isinstance(data, (bytes, bytearray)):
            data = data.decode()
        try:
            return json.loads(data)
        except Exception:
            return {"last_date": None, "streak": 0}

    async def set_absen_data(self, guild_id: int, user_id: int, today: str, streak: int):
        key = f"yumna:absen:{guild_id}:{user_id}"
        data = {"last_date": today, "streak": streak}
        await self.bot.redis.set(key, json.dumps(data))
        
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
        
    @commands.command(name="absen")
    @check_master_channel()
    async def _absen(self, ctx):
        guild_id = ctx.guild.id
        user_id = ctx.author.id
        username = str(ctx.author)
        
        xp_gain = 1200
        balance_gain = 1500
        
        today_dt = get_current_date_uptime()
        try:
            # normalisasi ke date
            today_date = today_dt.date()
        except Exception:
            today_date = today_dt
        today_str = today_date.strftime("%Y-%m-%d")
        
        # Ambil data absensi
        data = await self.get_absen_data(guild_id, user_id)
        last_date = data.get("last_date")
        streak = data.get("streak", 0)
        
        if last_date == today_str:
            embed = discord.Embed(
                description="❌ Kamu sudah absen hari ini!",
                color=discord.Color.red()
            )
            return await ctx.reply(embed=embed)
    
        ok, total_time = await economy.validate_voice(guild_id, user_id, today_date)
        if not ok:
            embed = discord.Embed(
                description=f"### Voice time tidak cukup!\nyou need to join voice activity first\n-# voice time : {total_time} seconds",
                color=discord.Color.red()
            )
            return await ctx.reply(embed=embed)
        
        # Hitung streak baru
        if last_date is not None:
            from datetime import datetime, timedelta
            try:
                last_dt = datetime.strptime(last_date, "%Y-%m-%d").date()
            except Exception:
                last_dt = None

            if last_dt and today_date == last_dt + timedelta(days=1):
                streak += 1  # Lanjut streak
            else:
                streak = 1   # Reset streak
        else:
            streak = 1  # Pertama kali absen
        
        # Update economy
        result = await economy.earn_xp_balance(guild_id, user_id, username, xp_gain, balance_gain, "daily check-in", "credit")
        
        # Simpan absen terbaru
        await self.set_absen_data(guild_id, user_id, today_str, streak)
        
        # Buat embed hasil
        embed = discord.Embed(color=discord.Color.green())
        
        if result["new_level"] > result["old_level"]:
            embed.description = (
                f"### **LEVEL UP! 🎉**\n"
                f"Selamat kamu berhasil mencapai lv.**{result['new_level']}**\n"
                f"### 🔥 Streak {streak} hari!"
            )
        else:
            embed.description = (
                f"✅ **Daily Check-in**\n"
                f"### 🔥Streak {streak} hari!\n"
                f"-# You earn `{xp_gain}` XP & `{balance_gain}` vcash"
            )
            embed.set_footer(
                text=f"XP: {result['xp']} | Level: {result['new_level']}"
            )
        
        await ctx.reply(embed=embed)

    @commands.command(name="profile")
    async def get_all_stats(self, ctx: commands.Context):
        guild_id = ctx.guild.id
        user = ctx.author
        user_id = user.id
        username = str(user)

        # ambil data user dari DB
        stats = await economy.get_user(guild_id, user_id, username)

        # fallback avatar: pakai avatar user kalau ada, kalau nggak pakai icon server
        if user.avatar:
            avatar_url = user.avatar.url
        elif ctx.guild.icon:
            avatar_url = ctx.guild.icon.url
        else:
            avatar_url = ctx.author.default_avatar.url  # fallback terakhir

        current_level = stats["level"]
        current_xp = stats["xp"]

        # XP target untuk level berikutnya
        xp_next_level = xp_for_level(current_level + 1)

        # progress langsung dari 0 sampai target
        progress = current_xp
        needed = xp_next_level
        percentage = progress / needed if needed > 0 else 1

        # progress bar visual
        bar_length = 20
        filled = int(bar_length * percentage)
        bar = "█" * filled + "░" * (bar_length - filled)


        # bikin embed
        embed = discord.Embed(
            title=f"{user.display_name}'s Info",
            color=discord.Color.blurple()
        )
        embed.set_thumbnail(url=avatar_url)

        embed.description = (
            f"> Level : {stats['level']}\n"
            f"> {bar}\n> -# {progress}/{needed} XP\n\n"
            
            f"> Stats :\n"
            f"> - vcash boost +{stats['level']}%\n"
            f"> - reduce usage +{stats['level']}%\n\n"



        )

        await ctx.send(embed=embed)

        
    @commands.command(name="cash")
    async def get_cash_member(self, ctx: commands.Context):
        guild_id = ctx.guild.id
        user_id = ctx.author.id
        username = str(ctx.author)

        # Ambil data member dari service
        balance = await economy.get_balance(guild_id, user_id)
        
        # Format balance dengan pemisah ribuan
        formatted_balance = "{:,}".format(balance)

        # Buat embed
        embed = discord.Embed(
            description=(
                f"### **Cash Info**\n"
                f"> ### Balance : `{formatted_balance}` vcash\n"
                f"-# You can earn vcash from voice activity"
                ),
            color=discord.Color.blurple()
        )

        avatar = getattr(ctx.author, "display_avatar", None)
        avatar_url = avatar.url if avatar else (ctx.guild.icon.url if ctx.guild.icon else None)
        if avatar_url:
            embed.set_thumbnail(url=avatar_url)

        await ctx.reply(embed=embed)


    @commands.command(name="sendcash", aliases=["tf"])
    async def transfer_vcash(self, ctx: commands.Context, target: discord.Member = None, amount: int = None):
        guild_id = ctx.guild.id
        sender_id = ctx.author.id
        sender_username = str(ctx.author)
        
        if target is None:
            return await ctx.send(embed=discord.Embed(description="Mention user yang ingin kamu transfer!", color=discord.Color.red()))

        if amount is None:
            return await ctx.send(embed=discord.Embed(description="Masukkan jumlah yang ingin ditransfer!", color=discord.Color.red()))

        if target.bot:
            return await ctx.send(embed=discord.Embed(description="Tidak bisa transfer ke bot!", color=discord.Color.red()))

        if target.id == sender_id:
            return await ctx.send(embed=discord.Embed(description="Tidak bisa transfer ke diri sendiri!", color=discord.Color.red()))

        if amount < 1000:
            return await ctx.send(embed=discord.Embed(description=f"Minimal transfer 1000!", color=discord.Color.red()))

        # Panggil service dengan fee
        result = await economy.transfer_balance(
            guild_id, sender_id, sender_username, target.id, str(target), amount
        )

        if result is None:
            return await ctx.reply(embed=discord.Embed(description="Saldo tidak cukup!\n-# biaya admin 50%", color=discord.Color.red()))

        # Format angka
        amount_formatted = f"{result['amount']:,}"
        fee_formatted = f"{result['fee']:,}"

        embed = discord.Embed(
            title="💸 Transfer Berhasil",
            description=(
                f"**Jumlah Dikirim:** `{amount_formatted}` vcash\n"
                f"-# **Berhasil transfer ke → {target.mention}**"
            ),
            color=discord.Color.green()
        )
        embed.set_footer(text=f"tax {fee_formatted} (50%)")

        await ctx.reply(embed=embed)
        
    @commands.hybrid_command(name="transactions", aliases=["tx", "history"])
    async def transactions(self, ctx: commands.Context):
        """Command untuk menampilkan transaction history user"""
        guild_id = ctx.guild.id
        user_id = ctx.author.id
        guild_name = ctx.guild.name
        user_name = ctx.author.display_name
        
        log.info(f"[ COMMAND CALL ] ---- Command [ transactions ] dipanggil : {guild_name} | {user_name}")
        
        def formatter(embed, idx, row):
            # Menggunakan dictionary access untuk menghindari unpacking error
            try:
                username = row['username']
                amount = row['amount']
                balance_before = row['balance_before']
                balance_after = row['balance_after']
                reason = row['reason']
                tx_type = row['tx_type']
                created_at = row['created_at']
                
                amount_str = f"+{amount:,}" if amount > 0 else f"{amount:,}"
                formatted_date = created_at.strftime("%d/%m/%Y %H:%M")
                
                embed.add_field(
                    name=f"**{formatted_date}**",
                    value=(
                        f"> **{tx_type.title()}**: {reason}\n"
                        f"> **Amount**: **{amount_str}**\n"
                        f"> **Balance**: {balance_before:,} → **{balance_after:,}**"
                    ),
                    inline=False
                )
            except Exception as e:
                log.error(f"Error formatting transaction row: {e}, Row: {row}")
                embed.add_field(
                    name="**Error**",
                    value=f"Error displaying transaction data: {str(e)}",
                    inline=False
                )
        
        # Pagination untuk user transactions menggunakan service layer
        await self.paginate_user_transactions(ctx, guild_id, user_id, formatter, user_name)

    async def paginate_user_transactions(self, ctx, guild_id, user_id, formatter, user_name=None):
        """Pagination untuk user transactions dengan service layer"""
        
        DATA_PER_PAGE = 5
        
        left_str = "◀️"
        right_str = "▶️"

        start = 0
        message = None

        while True:
            # Gunakan service layer untuk mengambil data
            results = await economy.get_user_transaction_history(guild_id, user_id, DATA_PER_PAGE, start)

            if not results:
                if start == 0:
                    await ctx.send("Tidak ada data transaksi yang ditemukan")
                else:
                    await ctx.send("Tidak ada data untuk halaman selanjutnya")
                break

            embed = discord.Embed(color=discord.Color.blue())
            embed.description = f"{WHITELINE}"
            embed.set_thumbnail(url=ctx.guild.icon.url if ctx.guild.icon else None)
            embed.set_footer(text=f"{ctx.guild.name}")
            # tampilkan username jika ada
            title_user = f" — {user_name}" if user_name else ""
            embed.set_author(name=f"|  {(start // DATA_PER_PAGE) + 1}  |  Trx History{title_user}")

            for idx, row in enumerate(results, start=start + 1):
                formatter(embed, idx, row)

            if not message:
                message = await ctx.send(embed=embed)
                try:
                    await message.add_reaction(left_str)
                    await message.add_reaction(right_str)
                except Exception as e:
                    log.info(f"[ REACTION ERROR ] ------- {e}")
                    return
            else:
                await message.edit(embed=embed)

            def check(reaction, user):
                return (
                    reaction.message.id == message.id
                    and user == ctx.author
                    and str(reaction.emoji) in [left_str, right_str]
                )

            try:
                reaction, user = await self.bot.wait_for('reaction_add', timeout=60.0, check=check)
            except asyncio.TimeoutError:
                try:
                    await message.clear_reactions()
                except Exception:
                    pass
                break

            # Hapus reaction user supaya UI bersih
            try:
                try:
                    await reaction.remove(user)
                except Exception:
                    await message.remove_reaction(reaction.emoji, user)
            except Exception:
                pass

            if str(reaction.emoji) == right_str:
                start += DATA_PER_PAGE
            elif str(reaction.emoji) == left_str:
                start = max(0, start - DATA_PER_PAGE)
                
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
    await bot.add_cog(Economy(bot))
