import discord
import logging
import asyncio
import re
import time
import json

from datetime import datetime, timezone, timedelta
from utils.decorator.channel import check_master_channel
from utils.decorator.spender import requires_balance

from cogs.voice.voicecount import get_cache_count
from .database.redis import MasterChannelRedis as redis
from .database.db import TextChannelQuery as db
from discord.ext import commands

log = logging.getLogger(__name__)

IMMUNE_KEY = "immune:{guild_id}:{user_id}"
MAX_IMMUNE_DURATION = 86400  # 24 hours
AUTO_DC_TASK_KEY = "autodc:task:{guild_id}:{user_id}"

class AutoDisconnect(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.tasks = {}  # Menyimpan task auto-disconnect per user
        
    # ---------- Redis: Recover AutoDC Task ----------
 
    def cog_load(self):
        asyncio.create_task(self._delayed_load())

    async def _delayed_load(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(2)
        recovered_tasks = await self._load_autodc_from_redis()
        for task_data in recovered_tasks:
            guild_id = task_data["guild_id"]
            user_id = task_data["user_id"]
            disconnect_at = task_data["disconnect_at"]
            delay = disconnect_at - int(time.time())

            if delay > 0:
                task = asyncio.create_task(self._auto_dc(guild_id, user_id, delay))
                self.tasks[user_id] = task
            log.info(f"[ RECOVER AUTODC ] ---- Total: {len(self.tasks)}")

    # ---------- Redis: AutoDC Logic ----------
    
    async def _save_task_to_redis(self, guild_id: int, user_id: int, disconnect_at: int):
        key = AUTO_DC_TASK_KEY.format(guild_id=guild_id, user_id=user_id)
        payload = {
            "guild_id": guild_id,
            "user_id": user_id,
            "disconnect_at": disconnect_at
        }
        ttl = max(0, disconnect_at - int(time.time()))
        await self.bot.redis.set(key, json.dumps(payload), ex=ttl)

    async def _remove_task_from_redis(self, guild_id: int, user_id: int):
        key = AUTO_DC_TASK_KEY.format(guild_id=guild_id, user_id=user_id)
        await self.bot.redis.delete(key)
        
    async def _load_autodc_from_redis(self):
        keys = await self.bot.redis.keys("autodc:task:*")
        tasks = []
        for key in keys:
            raw = await self.bot.redis.get(key)
            if raw:
                try:
                    data = json.loads(raw)
                    tasks.append(data)
                except json.JSONDecodeError:
                    continue
        return tasks

    # ---------- Redis: Immune Logic ----------

    def _format_expire_at(self, timestamp: int, tz_offset: int = 7) -> str:
        tz = timezone(timedelta(hours=tz_offset))
        dt = datetime.fromtimestamp(timestamp, tz)
        return dt.strftime("%Y-%m-%d %H:%M:%S")

    async def _set_user_immune(self, guild_id: int, user_id: int, duration_sec: int) -> int:
        key = IMMUNE_KEY.format(guild_id=guild_id, user_id=user_id)
        expire_at = int(time.time()) + duration_sec
        await self.bot.redis.set(key, expire_at, ex=duration_sec)
        return expire_at

    async def _is_user_immune(self, guild_id: int, user_id: int) -> bool:
        key = IMMUNE_KEY.format(guild_id=guild_id, user_id=user_id)
        expire_at = await self.bot.redis.get(key)
        if expire_at:
            return int(expire_at) > int(time.time())
        return False

    async def _get_user_immune_remaining(self, guild_id: int, user_id: int) -> int:
        key = IMMUNE_KEY.format(guild_id=guild_id, user_id=user_id)
        expire_at = await self.bot.redis.get(key)
        if expire_at:
            return max(0, int(expire_at) - int(time.time()))
        return 0

    # ---------- Master Channel Validation ----------

    async def _is_valid_master_channel(self, ctx) -> bool:
        master_channel_id = await redis.get_master_channel_cache(self, ctx.guild.id)
        if master_channel_id is None:
            master_channel_id = await db.get_master_channel(ctx.guild.id)
            if master_channel_id:
                await redis.save_master_channel_cache(self, ctx.guild.id, master_channel_id)

        if master_channel_id is None:
            await ctx.reply(
                "Hubungi admin untuk mengaktifkan Channel Yumna.\n"
                "-# Fungsi ini hanya bisa digunakan untuk channel utama Yumna\n"
                "-# atau gunakan command `/set_yumna_channel` untuk mengatur channel utama"
            )
            return False

        if ctx.channel.id != master_channel_id:
            await ctx.reply(f"Hanya bisa digunakan di <#{master_channel_id}>")
            return False

        return True

    # ---------- Commands ----------

    @commands.command(name="immune")
    async def immune(self, ctx, duration: str):
        time_map = {"s": 1, "m": 60, "h": 3600}
        match = re.match(r"^(\d+)([smh])$", duration)
        user = ctx.author
        guild_id, user_id = ctx.guild.id, user.id

        if not match:
            await self._send_embed(ctx, "⚠️ Format Tidak Valid!",
                "Gunakan format seperti:\n`!immune 1h`, `!immune 30m`, `!immune 10s`", discord.Color.orange())
            return

        value, unit = int(match.group(1)), match.group(2)
        duration_sec = value * time_map[unit]

        if duration_sec > MAX_IMMUNE_DURATION:
            await self._send_embed(ctx, "⚠️ Durasi Terlalu Lama!",
                "Durasi maksimal immune adalah **24 jam**.", discord.Color.orange())
            return

        if await self._is_user_immune(guild_id, user_id):
            remaining = await self._get_user_immune_remaining(guild_id, user_id)
            expire_str = self._format_expire_at(int(time.time()) + remaining)
            await self._send_embed(ctx, "🛡️ Sudah Immune!",
                f"Kamu masih immune hingga : {expire_str} WIB.", discord.Color.blue())
            return

        expire_at = await self._set_user_immune(guild_id, user_id, duration_sec)
        expire_str = self._format_expire_at(expire_at)
        await self._send_embed(ctx, "✅ Immune Aktif!",
            f"**{user.mention}** kebal dari auto-disconnect hingga \n{expire_str} WIB.", discord.Color.green())

    @commands.command(name="cancelimmune")
    async def cancel_immune(self, ctx):
        guild_id, user_id = ctx.guild.id, ctx.author.id
        key = IMMUNE_KEY.format(guild_id=guild_id, user_id=user_id)

        if await self.bot.redis.exists(key):
            await self.bot.redis.delete(key)
            await self._send_embed(ctx, "✅ Imun Dibatalkan!",
                f"**{ctx.author.mention}** tidak lagi memiliki imun.", discord.Color.green())
        else:
            await self._send_embed(ctx, "⚠️ Tidak Ada Imun Aktif!",
                f"**{ctx.author.mention}** tidak memiliki imun yang aktif.", discord.Color.orange())

    @commands.command(name="cancel")
    async def cancel_autodc(self, ctx):
        guild_id = ctx.guild.id
        user_id = ctx.author.id

        if ctx.author.id in self.tasks:
            self.tasks[ctx.author.id].cancel()
            del self.tasks[ctx.author.id]
            await self._remove_task_from_redis(guild_id, user_id)
            await self._send_embed(ctx, "🚫 Auto-Disconnect Dibatalkan!",
                f"**{ctx.author.mention}**, auto-disconnect kamu telah berhasil dibatalkan.", discord.Color.green())
        else:
            await self._send_embed(ctx, "⚠️ Tidak Ada Auto-Disconnect Aktif!",
                f"{ctx.author.mention}, tidak ditemukan auto-disconnect aktif.", discord.Color.orange())

    @commands.command(name="dc", aliases=["autodc","disconnect"])
    @check_master_channel()
    async def _auto_dc(self, ctx, *args):

        member, duration = await self._parse_autodc_args(ctx, args)
        if not member or not duration:
            return

        if member.bot:
            return

        if not await get_cache_count(self, member.id, ctx.guild.id):
            await self._send_embed(ctx, "🔔 Aktifkan VoiceCounter",
                "User tidak mengaktifkan voice counter.", discord.Color.orange(),
                thumbnail=member.avatar.url if member.avatar else "",
                footer="v!voicecount on/off")
            return

        if await self._is_user_immune(ctx.guild.id, member.id):
            await self._send_embed(ctx, "🛡️ User Sedang Immune!",
                f"{member.mention} sedang immune dan tidak bisa di-disconnect.", discord.Color.blue())
            return

        if not member.voice or not member.voice.channel:
            await self._send_embed(ctx, "❌ Gagal!",
                "User harus berada di voice channel.", discord.Color.red())
            return

        seconds = self._parse_duration(duration)
        if seconds is None:
            await self._send_embed(ctx, "⚠️ Kesalahan!",
                "Gunakan format seperti: `v!dc 10m`, `v!dc @user 30s`", discord.Color.orange())
            return

        if not 5 <= seconds <= 86400:
            await self._send_embed(ctx, "⚠️ Kesalahan!",
                "AutoDc minimal 5 detik dan maksimal 24 jam.", discord.Color.orange())
            return

        if member.id in self.tasks:
            self.tasks[member.id].cancel()
            del self.tasks[member.id]
            refreshed = True
        else:
            refreshed = False

        guild_id = ctx.guild.id
        guild_name = ctx.guild.name
        user_name = ctx.author.display_name
        user_id = member.id       
        disconnect_at = int(time.time()) + seconds 
        await self._save_task_to_redis(guild_id, user_id, disconnect_at)


        self.tasks[member.id] = asyncio.create_task(self._disconnect_timer(ctx, member, seconds))


        await self._send_embed(
            ctx,
            title="✅ Refresh AutoDisconnect!" if refreshed else "✅ Auto-Disconnect Dimulai!",
            desc=(
                f"Timer AutoDisconnect {member.mention} diperbarui: **{duration}**."
                if refreshed else
                f"{member.mention} akan di-disconnect dalam **{duration}**."
            ),
            color=discord.Color.green(),
            footer="v!cancel untuk membatalkan."
        )
        log.info(f"[ COMMAND CALL ] -- [ AutoDC ] ---- From {user_name} on guild [ {guild_name} ]")


    # ---------- Helper & Timer Logic ----------

    async def _disconnect_timer(self, ctx, target, delay):
        guild_id, user_id = ctx.guild.id, target.id
        try:
            if delay > 120:
                await asyncio.sleep(delay - 120)
                if await self._is_user_immune(guild_id, user_id):
                    await self._send_embed(ctx, "🛡️ User Sedang Immune!",
                        f"{target.mention} sedang immune.", discord.Color.blue())
                    return
                await self._send_embed(ctx, "🔔 Auto-Disconnect",
                    f"⏳ {target.mention}, kamu akan di-disconnect dalam **2 menit**!",
                    discord.Color.orange(), footer="v!cancel untuk membatalkan.",
                    thumbnail=target.avatar.url if target.avatar else "")
                await asyncio.sleep(120)
            else:
                await asyncio.sleep(delay)

            if await self._is_user_immune(guild_id, user_id):
                await self._send_embed(ctx, "🛡️ User Sedang Immune!",
                    f"{target.mention} sedang immune.", discord.Color.blue())
                return

            if target.voice and target.voice.channel:
                if ctx.guild.me.guild_permissions.move_members:
                    await target.move_to(None)
                    await self._send_embed(ctx, "👋 Berhasil Disconnect User!",
                        f"{target.mention} telah dikeluarkan dari voice channel.", discord.Color.blue())
                else:
                    await self._send_embed(ctx, "❌ Gagal!",
                        "Bot tidak memiliki izin untuk memindahkan anggota.", discord.Color.red())
            else:
                await self._send_embed(ctx, "⚠️ Tidak Dapat Disconnect!",
                    f"{target.mention} sudah tidak ada di voice channel.", discord.Color.orange())

        except asyncio.CancelledError:
            log.info(f"[ CANCEL TASK ] Auto-disconnect dibatalkan untuk user {target}.")
        finally:
            self.tasks.pop(user_id, None)
            await self._remove_task_from_redis(guild_id, user_id)


    async def _parse_autodc_args(self, ctx, args):
        if len(args) == 1:
            return ctx.author, args[0]
        elif len(args) == 2:
            try:
                member = await commands.MemberConverter().convert(ctx, args[0])
                return member, args[1]
            except commands.BadArgument:
                await ctx.send("❌ Tidak dapat menemukan user yang dituju.")
                return None, None
        await ctx.send("❌ Format salah. Gunakan `v!dc 10m` atau `v!dc @user 10m`")
        return None, None

    def _parse_duration(self, duration: str) -> int | None:
        match = re.match(r"^(\d+)([smh])$", duration)
        if not match:
            return None
        value, unit = int(match.group(1)), match.group(2)
        time_map = {"s": 1, "m": 60, "h": 3600}
        return value * time_map[unit]

    async def _send_embed(self, ctx, title, desc, color, footer=None, thumbnail=None):
        embed = discord.Embed(title=title, description=desc, color=color, timestamp=discord.utils.utcnow())
        if footer:
            embed.set_footer(text=footer)
        if thumbnail:
            embed.set_thumbnail(url=thumbnail)
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(AutoDisconnect(bot))