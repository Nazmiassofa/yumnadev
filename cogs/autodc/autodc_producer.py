import re
import time
import uuid
import json
import logging
import asyncio
import discord

from contextlib import asynccontextmanager
from utils.decorator.spender import requires_balance
from discord.ext import commands
from aio_pika import Message, DeliveryMode
from config import RabbitMQ
from utils.decorator.channel import check_master_channel

log = logging.getLogger(__name__)
MAX_IMMUNE_DURATION = 86400  # 24 jam

class AutoDCProducer(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.publish_channel = None
        self.exchange = None
        self._task_lock = asyncio.Lock()  # Prevent race conditions

    async def cog_load(self):
        # create channel dedicated for publishing
        if not getattr(self.bot, "rabbit_conn", None):
            raise RuntimeError("rabbit_conn not initialized on bot. Call bot.init_rabbit_connection() first.")
        
        try:
            self.publish_channel = await self.bot.rabbit_conn.channel()
            await self.publish_channel.set_qos(prefetch_count=0)
            # get exchange (assumes declared in main or idempotent if not)
            self.exchange = await self.publish_channel.get_exchange(RabbitMQ.AUTODC_EXCHANGE)
            log.info("[ AUTODC PRODUCER ] ---- Publisher channel initialized")
        except Exception as e:
            log.error(f"[ AUTODC PRODUCER ] ---- Failed to initialize: {e}")
            raise

    async def cog_unload(self):
        if getattr(self, "publish_channel", None):
            try:
                await self.publish_channel.close()
                log.info("[ AUTODC PRODUCER ] ---- Publisher channel closed")
            except Exception as e:
                log.error(f"[ AUTODC PRODUCER ] ---- Error closing channel: {e}")

    def _parse_duration(self, duration: str) -> int | None:
        match = re.match(r"^(\d+)([smh])$", duration)
        if not match:
            return None
        value, unit = int(match.group(1)), match.group(2)
        time_map = {"s": 1, "m": 60, "h": 3600}
        return value * time_map[unit]

    def _get_immune_key(self, guild_id: int, user_id: int) -> str:
        """Generate Redis key for immunity."""
        return f"autodc:immune:{guild_id}:{user_id}"

    def _get_task_key(self, user_id: int) -> str:
        """Generate Redis key for active task."""
        return f"autodc:task:{user_id}"

    async def _set_immune(self, guild_id: int, user_id: int, duration_seconds: int) -> bool:
        """Set immunity in Redis with TTL."""
        try:
            key = self._get_immune_key(guild_id, user_id)
            # Set with TTL, value is expiry timestamp for human readability
            expire_at = int(time.time()) + duration_seconds
            await self.bot.redis.setex(key, duration_seconds, expire_at)
            return True
        except Exception as e:
            log.error(f"[ AUTODC PRODUCER ] ---- Redis set_immune error: {e}")
            return False

    async def _is_immune(self, guild_id: int, user_id: int) -> bool:
        """Check if user is immune."""
        try:
            key = self._get_immune_key(guild_id, user_id)
            result = await self.bot.redis.get(key)
            return result is not None
        except Exception as e:
            log.error(f"[ AUTODC PRODUCER ] ---- Redis is_immune error: {e}")
            return False  # Default to not immune if Redis fails

    async def _remove_immune(self, guild_id: int, user_id: int) -> bool:
        """Remove immunity from Redis."""
        try:
            key = self._get_immune_key(guild_id, user_id)
            result = await self.bot.redis.delete(key)
            return result > 0
        except Exception as e:
            log.error(f"[ AUTODC PRODUCER ] ---- Redis remove_immune error: {e}")
            return False

    async def _get_immune_remaining(self, guild_id: int, user_id: int) -> int:
        """Get remaining immunity time in seconds."""
        try:
            key = self._get_immune_key(guild_id, user_id)
            ttl = await self.bot.redis.ttl(key)
            return max(0, ttl) if ttl > 0 else 0
        except Exception as e:
            log.error(f"[ AUTODC PRODUCER ] ---- Redis get_immune_remaining error: {e}")
            return 0

    async def _set_active_task(self, user_id: int, task_data: dict) -> bool:
        """Store active task in Redis."""
        try:
            key = self._get_task_key(user_id)
            # Store for 25 hours (longer than max autodc duration)
            await self.bot.redis.setex(key, 90000, json.dumps(task_data))
            return True
        except Exception as e:
            log.error(f"[ AUTODC PRODUCER ] ---- Redis set_active_task error: {e}")
            return False

    async def _get_active_task(self, user_id: int) -> dict | None:
        """Get active task from Redis."""
        try:
            key = self._get_task_key(user_id)
            result = await self.bot.redis.get(key)
            if result:
                return json.loads(result)
            return None
        except Exception as e:
            log.error(f"[ AUTODC PRODUCER ] ---- Redis get_active_task error: {e}")
            return None

    async def _remove_active_task(self, user_id: int) -> bool:
        """Remove active task from Redis."""
        try:
            key = self._get_task_key(user_id)
            result = await self.bot.redis.delete(key)
            return result > 0
        except Exception as e:
            log.error(f"[ AUTODC PRODUCER ] ---- Redis remove_active_task error: {e}")
            return False

    @asynccontextmanager
    async def _task_operation(self):
        """Context manager for atomic task operations."""
        async with self._task_lock:
            yield

    async def _publish_delayed(self, payload: dict, delay_ms: int):
        """Publish to x-delayed-message exchange."""
        if self.exchange is None:
            try:
                self.exchange = await self.publish_channel.get_exchange(RabbitMQ.AUTODC_EXCHANGE)
            except Exception as e:
                log.error(f"[ AUTODC PRODUCER ] ---- Failed to get exchange: {e}")
                raise

        body = json.dumps(payload).encode()
        msg = Message(body, headers={"x-delay": delay_ms}, delivery_mode=DeliveryMode.PERSISTENT)
        
        try:
            await self.exchange.publish(msg, routing_key=RabbitMQ.ROUTING_KEY)
            log.debug(f"[ AUTODC PRODUCER ] ---- Published delayed task {payload.get('task_id')[:8]} delay={delay_ms}ms")
        except Exception as e:
            log.error(f"[ AUTODC PRODUCER ] ---- Failed publish_delayed: {e}")
            raise

    async def _publish_cancel(self, task_id: str):
        """Publish cancel message to cancel queue."""
        try:
            body = json.dumps({"task_id": task_id}).encode()
            msg = Message(body, delivery_mode=DeliveryMode.PERSISTENT)
            await self.publish_channel.default_exchange.publish(
                msg, routing_key=RabbitMQ.AUTODC_CANCEL_QUEUE
            )
            log.debug(f"[ AUTODC PRODUCER ] ---- Published cancel for task {task_id[:8]}")
        except Exception as e:
            log.error(f"[ AUTODC PRODUCER ] ---- Failed publish_cancel: {e}")

    @commands.command(name="immune")
    @requires_balance(2500, "immune_usage")
    async def immune(self, ctx, duration: str):
        """Set immunity against auto-disconnect."""
        m = re.match(r"^(\d+)([smh])$", duration)
        if not m:
            return await ctx.send("⚠️ Format Tidak Valid! Contoh: `v!immune 1h`")
        
        value, unit = int(m.group(1)), m.group(2)
        time_map = {"s": 1, "m": 60, "h": 3600}
        duration_sec = value * time_map[unit]
        
        if duration_sec > MAX_IMMUNE_DURATION:
            return await ctx.send("⚠️ Durasi maksimal immune adalah 24 jam.")

        # Check if already immune
        if await self._is_immune(ctx.guild.id, ctx.author.id):
            remain = await self._get_immune_remaining(ctx.guild.id, ctx.author.id)
            hours, remainder = divmod(remain, 3600)
            minutes, seconds = divmod(remainder, 60)
            
            time_str = ""
            if hours > 0:
                time_str += f"{hours} jam "
            if minutes > 0:
                time_str += f"{minutes} menit "
            if seconds > 0 or not time_str:
                time_str += f"{seconds} detik"
                
            embed = discord.Embed(
                title="🛡️ Immune Status",
                description=f"{ctx.author.mention} sudah memiliki immune aktif.",
                color=discord.Color.orange()
            )
            embed.add_field(name="Sisa Waktu", value=time_str.strip())
            return await ctx.send(embed=embed)

        # Set immunity
        success = await self._set_immune(ctx.guild.id, ctx.author.id, duration_sec)
        if success:
            hours, remainder = divmod(duration_sec, 3600)
            minutes, seconds = divmod(remainder, 60)
            
            time_str = ""
            if hours > 0:
                time_str += f"{hours} jam "
            if minutes > 0:
                time_str += f"{minutes} menit "
            if seconds > 0 or not time_str:
                time_str += f"{seconds} detik"
                
            embed = discord.Embed(
                title="✅ Immune Diaktifkan",
                description=f"{ctx.author.mention} sekarang immune terhadap auto-disconnect.",
                color=discord.Color.green()
            )
            embed.add_field(name="Durasi", value=time_str.strip())
            return await ctx.send(embed=embed)
        else:
            embed = discord.Embed(
                title="❌ Gagal Mengaktifkan Immune",
                description="Terjadi kesalahan saat mengaktifkan immune. Silakan coba lagi.",
                color=discord.Color.red()
            )
            return await ctx.send(embed=embed)

    @commands.command(name="cancelimmune")
    async def cancelimmune(self, ctx):
        """Cancel immunity."""
        removed = await self._remove_immune(ctx.guild.id, ctx.author.id)
        if removed:
            embed = discord.Embed(
                title="✅ Immune Dibatalkan",
                description=f"{ctx.author.mention} tidak lagi immune terhadap auto-disconnect.",
                color=discord.Color.green()
            )
            return await ctx.send(embed=embed)
        
        embed = discord.Embed(
            title="⚠️ Tidak Ada Immune Aktif",
            description=f"{ctx.author.mention} tidak memiliki immune aktif.",
            color=discord.Color.orange()
        )
        return await ctx.send(embed=embed)

    @commands.command(name="dc", aliases=["autodc", "disconnect"])
    @check_master_channel()
    @requires_balance(2500, "autodc_usage")
    async def _auto_dc(self, ctx, *args):
        """Schedule auto-disconnect for a user."""
        # Parse arguments
        if len(args) == 1:
            target = ctx.author
            duration_str = args[0]
        elif len(args) == 2:
            try:
                target = await commands.MemberConverter().convert(ctx, args[0])
                duration_str = args[1]
            except commands.BadArgument:
                embed = discord.Embed(
                    title="❌ User Tidak Ditemukan",
                    description="Tidak dapat menemukan user yang dituju.",
                    color=discord.Color.red()
                )
                return await ctx.send(embed=embed)
        else:
            embed = discord.Embed(
                title="❌ Format Salah",
                description="Gunakan `v!dc 10m` atau `v!dc @user 10m`",
                color=discord.Color.red()
            )
            return await ctx.send(embed=embed)

        # Basic validations
        if target.bot:
            embed = discord.Embed(
                title="❌ Gagal!",
                description="Bot tidak bisa dijadwalkan untuk auto-disconnect.",
                color=discord.Color.red()
            )
            return await ctx.send(embed=embed)

        if not target.voice or not target.voice.channel:
            embed = discord.Embed(
                title="❌ Gagal!",
                description="User harus berada di voice channel untuk dijadwalkan auto-disconnect.",
                color=discord.Color.red()
            )
            return await ctx.send(embed=embed)

        # Duration validation
        seconds = self._parse_duration(duration_str)
        if seconds is None:
            embed = discord.Embed(
                title="❌ Format Durasi Salah",
                description="Gunakan format: `v!dc 10m` atau `v!dc @user 30s`\nContoh: 30s, 5m, 1h",
                color=discord.Color.red()
            )
            return await ctx.send(embed=embed)
        
        if not 5 <= seconds <= 86400:
            embed = discord.Embed(
                title="❌ Durasi Tidak Valid",
                description="Auto-DC minimal 5 detik dan maksimal 24 jam.",
                color=discord.Color.red()
            )
            return await ctx.send(embed=embed)

        # Immunity check
        if await self._is_immune(ctx.guild.id, target.id):
            remain = await self._get_immune_remaining(ctx.guild.id, target.id)
            hours, remainder = divmod(remain, 3600)
            minutes, seconds = divmod(remainder, 60)
            
            time_str = ""
            if hours > 0:
                time_str += f"{hours} jam "
            if minutes > 0:
                time_str += f"{minutes} menit "
            if seconds > 0 or not time_str:
                time_str += f"{seconds} detik"
                
            embed = discord.Embed(
                title="🛡️ User Sedang Immune",
                description=f"{target.mention} sedang immune dan tidak bisa dijadwalkan untuk auto-disconnect.",
                color=discord.Color.orange()
            )
            embed.add_field(name="Sisa Waktu Immune", value=time_str.strip())
            return await ctx.send(embed=embed)

        # Bot permission check
        if not ctx.guild.me.guild_permissions.move_members:
            embed = discord.Embed(
                title="❌ Izin Bot Tidak Cukup",
                description="Bot tidak memiliki izin Move Members untuk melakukan auto-disconnect.",
                color=discord.Color.red()
            )
            return await ctx.send(embed=embed)

        async with self._task_operation():
            # Cancel existing task if any
            old_task = await self._get_active_task(target.id)
            refreshed = False
            
            if old_task:
                await self._publish_cancel(old_task.get("task_id", ""))
                await self._remove_active_task(target.id)
                refreshed = True

            # Create new task
            task_id = uuid.uuid4().hex
            scheduled_at = int(time.time()) + seconds
            
            task_data = {
                "task_id": task_id,
                "guild_id": ctx.guild.id,
                "user_id": target.id,
                "request_by": ctx.author.id,
                "channel_id": ctx.channel.id,
                "scheduled_at": scheduled_at,
                "duration_str": duration_str
            }

            try:
                # Publish delayed message
                await self._publish_delayed(task_data, delay_ms=seconds * 1000)
                
                # Store in Redis
                await self._set_active_task(target.id, task_data)
                
                # Format time for display
                hours, remainder = divmod(seconds, 3600)
                minutes, seconds = divmod(remainder, 60)
                
                time_str = ""
                if hours > 0:
                    time_str += f"{hours} jam "
                if minutes > 0:
                    time_str += f"{minutes} menit "
                if seconds > 0 or not time_str:
                    time_str += f"{seconds} detik"
                
                embed = discord.Embed(
                    title="✅ Auto-Disconnect",
                    description=f"{target.display_name} akan disconnect dalam **{time_str.strip()}**\n-# Requester: <@{ctx.author.id}>",
                    color=discord.Color.green()
                )
                embed.set_footer(text=f"task_id: {task_id[:10]}")
                
                if refreshed:
                    embed.set_footer(text="Task diperbarui")
                
                await ctx.send(embed=embed)
                
            except Exception as e:
                log.error(f"[ AUTODC PRODUCER ] ---- Failed to schedule task: {e}")
                embed = discord.Embed(
                    title="❌ Gagal Menjadwalkan Auto-Disconnect",
                    description="Terjadi kesalahan saat menjadwalkan auto-disconnect. Silakan coba lagi.",
                    color=discord.Color.red()
                )
                await ctx.send(embed=embed)

    @commands.command(name="cancel")
    async def cancel(self, ctx):
        """Cancel active auto-disconnect."""
        async with self._task_operation():
            task_data = await self._get_active_task(ctx.author.id)
            if not task_data:
                embed = discord.Embed(
                    title="⚠️ Not Found",
                    description=f"{ctx.author.display_name} tidak memiliki jadwal auto-disconnect aktif.",
                    color=discord.Color.orange()
                )
                return await ctx.send(embed=embed)

            task_id = task_data.get("task_id")
            if task_id:
                await self._publish_cancel(task_id)
            
            await self._remove_active_task(ctx.author.id)
            
            embed = discord.Embed(
                title="✅ Auto-Disconnect Dibatalkan",
                description=f"auto-disconnect untuk {ctx.author.display_name} telah dibatalkan.",
                color=discord.Color.green()
            )
            embed.set_footer(text=f"task_id: {task_id[:10]}")
            return await ctx.send(embed=embed)

    @commands.command(name="dcstats")
    async def mystatus(self, ctx):
        """Check your immunity and active task status."""
        embed = discord.Embed(
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
        
        # Check immunity
        if await self._is_immune(ctx.guild.id, ctx.author.id):
            remaining = await self._get_immune_remaining(ctx.guild.id, ctx.author.id)
            hours, remainder = divmod(remaining, 3600)
            minutes, seconds = divmod(remainder, 60)
            
            time_str = ""
            if hours > 0:
                time_str += f"{hours} jam "
            if minutes > 0:
                time_str += f"{minutes} menit "
            if seconds > 0 or not time_str:
                time_str += f"{seconds} detik"
                
            embed.add_field(
                name="🛡️ Status Immune", 
                value=f"Aktif (sisa {time_str.strip()})", 
                inline=False
            )
        else:
            embed.add_field(
                name="🛡️ Status Immune", 
                value="Tidak aktif", 
                inline=False
            )

        # Check active task
        task_data = await self._get_active_task(ctx.author.id)
        if task_data:
            scheduled_at = task_data.get("scheduled_at", 0)
            remaining = max(0, scheduled_at - int(time.time()))
            
            hours, remainder = divmod(remaining, 3600)
            minutes, seconds = divmod(remainder, 60)
            
            time_str = ""
            if hours > 0:
                time_str += f"{hours} jam "
            if minutes > 0:
                time_str += f"{minutes} menit "
            if seconds > 0 or not time_str:
                time_str += f"{seconds} detik"
                
            task_id = task_data.get("task_id", "unknown")
            
            embed.add_field(
                name="⏰ Auto-Disconnect", 
                value=f"Aktif (sisa {time_str.strip()})", 
                inline=False
            )
            embed.set_footer(text=f"task_id : {task_id[:8]}")
        else:
            embed.add_field(
                name="⏰ Auto-Disconnect", 
                value="Tidak aktif", 
                inline=False
            )

        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(AutoDCProducer(bot))