import logging
import discord

from collections import defaultdict

from .database.redis import StatistikRedis as redis
from utils.views.embed import cooldown_embed
from utils.decorator.channel import check_master_channel
from utils.decorator.spender import requires_balance

from datetime import datetime, timedelta, timezone
from discord.ext import commands
from typing import Optional
from .database.dbcounter import StatisticSummaryQuery as db

from .helper.pil import ( 
                         create_topfriends_card, 
                         generate_dual_chart_card,
                         generate_user_chart_card
                         )

from utils.time import get_current_date_uptime

log = logging.getLogger(__name__)

def _format_time(seconds):
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours} Jam {minutes} Menit"

class TopMemberStats(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    @commands.hybrid_command(name="topfriends", description="Lihat teman voice terdekat seseorang.")
    @check_master_channel()
    @requires_balance(1500, "topfriends_usage")
    async def topfriends(self, ctx: commands.Context, target: Optional[discord.Member] = None, duration: str = "30d"):
        target = target or ctx.author
        guild_id = ctx.guild.id
        user_id = target.id
        guild_name = ctx.guild.name
        user_name = ctx.author.display_name
        
        cooldown_time = await redis.statistik_cooldown(self, guild_id, user_id, cooldown_seconds=10)
                
        if cooldown_time > 0:
            embed = await cooldown_embed(cooldown_time)
            await ctx.send(embed=embed)
            return

        # Validasi durasi (default: 7 hari)
        if duration.lower().endswith("d") and duration[:-1].isdigit():
            days = int(duration[:-1])
            if days > 120:
                await ctx.send("Durasi maksimal adalah 120 hari. Gunakan contoh: `!topfriends 60d`")
                return
        else:
            await ctx.send("Format durasi tidak valid. Gunakan contoh: `!topfriends 7d`")
            return

        thinking_msg = await ctx.reply("_Processing_")

        today = get_current_date_uptime()
        start_date = today - timedelta(days=days - 1)
        end_date = today + timedelta(days=1)

        top_friends = await db.get_top_friends(guild_id, user_id, start_date, end_date, limit=4)

        if not top_friends:
            await thinking_msg.edit(content="Belum ada data voice.")
            return

        total_all_overlap = sum(f["total_overlap_seconds"] for f in top_friends) or 1

        # Total voice time dari seluruh overlap teman (digunakan untuk pie dan display total)
        total_voice_seconds = sum(f["total_overlap_seconds"] for f in top_friends) or 1
        formatted_total = _format_time(total_voice_seconds)

        log.info(f"[ COMMAND CALL ] ---- Command [ TopFriends ] dipanggil : {guild_name} | {user_name}")

        formatted_all = []
        for f in top_friends:
            member = ctx.guild.get_member(f["friend_id"])
            percent = f["total_overlap_seconds"] / total_all_overlap * 100
            formatted_all.append({
                "avatar_url": member.display_avatar.url if member else ctx.bot.user.display_avatar.url,
                "name": member.display_name if member else "Unknown User",
                "total_time_str": _format_time(f["total_overlap_seconds"]),
                "sessions": f["sessions_together"],
                "percent": percent
            })

        # Ambil 4 teratas
        top_4 = formatted_all[:4]
        others_total = sum(f["percent"] for f in formatted_all[4:])

        if others_total > 0:
            top_4.append({
                "name": "Others",
                "percent": round(others_total, 2)
            })
                    
        total_percent = sum(fr["percent"] for fr in top_4)
        for fr in top_4:
            fr["percent"] = round(fr["percent"] * 100 / total_percent, 2)

        img_bytes = create_topfriends_card(
            formatted_friends=top_4,
            target_avatar_url=target.display_avatar.url,
            target_name=target.display_name,
            total_time=formatted_total
        )


        file = discord.File(img_bytes, filename="topfriends.png")
        await thinking_msg.edit(
            content=f"Topfriends {target.display_name} — {days} hari terakhir",
            attachments=[file]
        )

            
    @commands.command(name="guildstats", aliases=['gstats','gs'])
    @check_master_channel()
    @requires_balance(1200, "guildstats_usage")
    async def statistik_grafik(self, ctx, duration: str = "7d"):
        guild_id = ctx.guild.id
        avatar_url = ctx.guild.icon.url if ctx.guild.icon else ctx.bot.user.display_avatar.url
        guild_name = ctx.guild.name
        total_member = sum(1 for m in ctx.guild.members if not m.bot)
        guild_since = ctx.guild.created_at.strftime("%d %B %Y")  # "10 Juli 2025"
        user_name = ctx.author.display_name
        user_id = ctx.author.id
        
        cooldown_time = await redis.statistik_cooldown(self, guild_id, user_id, cooldown_seconds=10)
                
        if cooldown_time > 0:
            embed = await cooldown_embed(cooldown_time)
            await ctx.send(embed=embed)
            return

        if duration.lower().endswith("d") and duration[:-1].isdigit():
            days = int(duration[:-1])    
        
        log.info (f"[ COMMAND CALL ] ---- Command [ GuildStats ] dipanggil : {guild_name} | {user_name}")

        thinking_msg = await ctx.reply("_Processing_")

        today = get_current_date_uptime()
        start_date = today - timedelta(days=days - 1)
        end_date = today + timedelta(days=1)

        voice_counts = await db.get_voice_stats(guild_id, start_date, today)
        vc_summary = await db.get_voice_stats_summary(guild_id, start_date, today)
        
        voice_traffic = await db.get_voice_traffic(guild_id, start_date, end_date)
        vt_summary = await db.get_voice_traffic_summary(guild_id,start_date, end_date)

        if not voice_counts and not voice_traffic:
            await thinking_msg.edit(content="⚠️ Tidak ada data aktivitas voice ditemukan.")
            return

        user_data = [(str(row["count_date"]), row["total_users"]) for row in voice_counts or []]
        traffic_data = [(str(row["activity_date"]), row["total_traffic"]) for row in voice_traffic or []]

        chart = generate_dual_chart_card(avatar_url, 
                                         guild_name, 
                                         total_member, 
                                         guild_since, 
                                         user_data,
                                         traffic_data,
                                         vc_summary,
                                         vt_summary)

        file = discord.File(chart, filename="voice_stats.png")
        await thinking_msg.edit(
            content=f"Statistik voice: {days} hari terakhir",
            attachments=[file]
        )        

            
    @commands.command(name="userstats", aliases=["ustats","us"])
    @check_master_channel()
    @requires_balance(1200, "userstats_usage")
    async def statistik_user(self, ctx, target: Optional[discord.Member] = None, duration: str = "7d"):

        target = target or ctx.author
        guild_id = ctx.guild.id
        user_id  = target.id
        
        cooldown_time = await redis.statistik_cooldown(self, guild_id, user_id, cooldown_seconds=10)
                
        if cooldown_time > 0:
            embed = await cooldown_embed(cooldown_time)
            await ctx.send(embed=embed)
            return

        thinking_msg = await ctx.reply("_Processing_")

        # 1. Parse duration
        if not (duration.lower().endswith("d") and duration[:-1].isdigit()):
            return await ctx.send("⚠️ Format duration: `<angka>d`, misal `7d`.")
        days = int(duration[:-1])

        # 2. Hitung rentang tanggal
        today      = get_current_date_uptime()
        start_date = today - timedelta(days=days - 1)
        end_date   = today + timedelta(days=1)

        # 3. Ambil data harian dan summary
        time_rows       = await db.get_user_time_per_day(guild_id, user_id, start_date, today)
        sess_rows       = await db.get_user_sessions_per_day(guild_id, user_id, start_date, end_date)
        raw_time_sum    = await db.get_user_time_summary(guild_id, user_id, start_date, today)
        session_summary = await db.get_user_sessions_summary(guild_id, user_id, start_date, end_date)

        if not time_rows and not sess_rows:
            await thinking_msg.edit(content="⚠️ Tidak ada data aktivitas voice ditemukan.")
            return

        # 4. Bangun struktur per-tanggal
        data = defaultdict(lambda: {"time": 0, "sessions": 0})
        for r in time_rows:
            data[r["count_date"]]["time"] = r["total_time_seconds"]
        for r in sess_rows:
            data[r["session_date"]]["sessions"] = r["session_count"]

        # 5. Buat list untuk plotting
        user_data    = [(dt.strftime("%Y-%m-%d"), data[dt]["time"])     for dt in sorted(data)]
        session_data = [(dt.strftime("%Y-%m-%d"), data[dt]["sessions"]) for dt in sorted(data)]

        # 6. Konversi summary time → jam, rounding
        if raw_time_sum:
            time_summary = {
                "sum":      round(raw_time_sum["sum"]    / 3600, 1),
                "avg":      round(raw_time_sum["avg"]    / 3600, 1),
                "min":      round(raw_time_sum["min"]    / 3600, 1),
                "min_date": raw_time_sum["min_date"],
                "max":      round(raw_time_sum["max"]    / 3600, 1),
                "max_date": raw_time_sum["max_date"],
            }
        else:
            time_summary = {"sum":"-","avg":"-","min":"-","min_date":None,"max":"-","max_date":None}

        wib = timezone(timedelta(hours=7))
        created_at = target.created_at.astimezone(wib).strftime("%d %b %Y")  # contoh: 12 Jul 2025
        joined_at  = target.joined_at.astimezone(wib).strftime("%d %b %Y")

        # 7. Generate image
        chart = generate_user_chart_card(
            avatar_url      = target.display_avatar.url,
            username        = target.display_name,
            user_data       = user_data,
            session_data    = session_data,
            time_summary    = time_summary,
            session_summary = session_summary,
            join_discord = created_at,
            join_server = joined_at
        )

        # 8. Kirim ke Discord
        file = discord.File(chart, filename="user_stats.png")
        await thinking_msg.edit(
            content=f"Statistik {target.display_name} — {days} hari terakhir",
            attachments=[file]
        )

async def setup(bot):
    await bot.add_cog(TopMemberStats(bot))
