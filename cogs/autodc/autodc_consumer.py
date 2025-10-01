import json
import time
import logging
import asyncio

import discord
from discord.ext import commands
from aio_pika import IncomingMessage
from config import RabbitMQ

log = logging.getLogger(__name__)

class AutoDCConsumer(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.cancelled_task_ids = set()
        self.consumer_channel = None
        self.cancel_q = None
        self.autodc_q = None
        self._max_cancelled_tasks = 1000  # Prevent memory leak
        
    async def cog_load(self):
        # create channel dedicated for consuming
        if not getattr(self.bot, "rabbit_conn", None):
            raise RuntimeError("rabbit_conn not initialized on bot. Call bot.init_rabbit_connection() first.")
        
        try:
            self.consumer_channel = await self.bot.rabbit_conn.channel()
            await self.consumer_channel.set_qos(prefetch_count=5)

            # declare/attach queues
            self.cancel_q = await self.consumer_channel.declare_queue(RabbitMQ.AUTODC_CANCEL_QUEUE, durable=True)
            self.autodc_q = await self.consumer_channel.declare_queue(RabbitMQ.AUTODC_QUEUE, durable=True)
            await self.autodc_q.bind(RabbitMQ.AUTODC_EXCHANGE, routing_key=RabbitMQ.ROUTING_KEY)

            # start consuming
            await self.cancel_q.consume(self._on_cancel_message, no_ack=False)
            await self.autodc_q.consume(self._on_autodc_message, no_ack=False)
            
            log.info("[ AUTODC CONSUMER ] ----- Consumer started successfully")
            
        except Exception as e:
            log.error(f"[ AUTODC CONSUMER ] ----- Failed to initialize: {e}")
            raise

    async def cog_unload(self):
        if getattr(self, "consumer_channel", None):
            try:
                await self.consumer_channel.close()
                log.info("[ AUTODC CONSUMER ] ----- Consumer channel closed")
            except Exception as e:
                log.error(f"[ AUTODC CONSUMER ] ----- Error closing consumer channel: {e}")

    def _get_immune_key(self, guild_id: int, user_id: int) -> str:
        """Generate Redis key for immunity."""
        return f"autodc:immune:{guild_id}:{user_id}"

    def _get_task_key(self, user_id: int) -> str:
        """Generate Redis key for active task."""
        return f"autodc:task:{user_id}"

    async def _is_immune(self, guild_id: int, user_id: int) -> bool:
        """Check if user is immune using Redis."""
        try:
            key = self._get_immune_key(guild_id, user_id)
            result = await self.bot.redis.get(key)
            return result is not None
        except Exception as e:
            log.error(f"[ AUTODC CONSUMER ] ----- Redis is_immune error: {e}")
            return False  # Default to not immune if Redis fails

    async def _remove_active_task(self, user_id: int) -> bool:
        """Remove active task from Redis."""
        try:
            key = self._get_task_key(user_id)
            result = await self.bot.redis.delete(key)
            return result > 0
        except Exception as e:
            log.error(f"[ AUTODC CONSUMER ] ----- Redis remove_active_task error: {e}")
            return False

    def _cleanup_cancelled_tasks(self):
        """Prevent memory leak from cancelled_task_ids set."""
        if len(self.cancelled_task_ids) > self._max_cancelled_tasks:
            # Keep only the most recent half
            task_list = list(self.cancelled_task_ids)
            self.cancelled_task_ids = set(task_list[-self._max_cancelled_tasks//2:])
            log.debug(f"[ AUTODC CONSUMER ] ----- Cleaned up cancelled tasks, now {len(self.cancelled_task_ids)}")

    async def _send_embed_to_channel(self, channel_id: int, title: str, desc: str, color=discord.Color.blue()):
        """Send embed message with fallback channels.
        Robust permission checks (uses guild.me), fallback to plain text if embed_links missing.
        """
        embed = discord.Embed(
            title=title,
            description=desc,
            color=color,
            timestamp=discord.utils.utcnow()
        )

        async def try_send(ch):
            if not ch or not hasattr(ch, "send"):
                return False

            # determine bot member for permission checks (may be None for DM channels)
            bot_member = None
            try:
                bot_member = getattr(ch, "guild", None) and ch.guild.me
            except Exception:
                bot_member = None

            # permissions_for expects a Member/Role; if we have a guild member, use it
            perms = None
            try:
                perms = ch.permissions_for(bot_member) if bot_member is not None else None
            except Exception as e:
                log.debug(f"[ AUTODC CONSUMER ] ----- permissions_for failed for channel {getattr(ch,'id',None)}: {e}")
                perms = None

            # If permissions are available, require send_messages.
            if perms is not None and not perms.send_messages:
                log.debug(f"[ AUTODC CONSUMER ] ----- Bot cannot send messages in channel {getattr(ch,'id',None)}")
                return False

            # If embed_links blocked but sending messages allowed, fall back to plain text so user still receives info
            try:
                if perms is not None and not perms.embed_links and perms.send_messages:
                    # fallback to plain text
                    text = f"**{title}**\n{desc}"
                    try:
                        await ch.send(text)
                        return True
                    except discord.Forbidden:
                        log.debug(f"[ AUTODC CONSUMER ] ----- Forbidden sending plain text to {getattr(ch,'id',None)}")
                        return False
                    except Exception as e:
                        log.debug(f"[ AUTODC CONSUMER ] ----- Error sending plain text to {getattr(ch,'id',None)}: {e}")
                        return False

                # Normal case: try to send embed
                await ch.send(embed=embed)
                return True

            except discord.Forbidden:
                log.debug(f"[ AUTODC CONSUMER ] ----- Forbidden sending embed to {getattr(ch,'id',None)}")
                return False
            except discord.HTTPException as e:
                log.debug(f"[ AUTODC CONSUMER ] ----- HTTPException sending embed to {getattr(ch,'id',None)}: {e}")
                return False
            except Exception as e:
                log.error(f"[ AUTODC CONSUMER ] ----- Unexpected error sending to channel {getattr(ch,'id',None)}: {e}")
                return False

        # 1) Try primary configured channel
        if channel_id:
            channel = self.bot.get_channel(channel_id)
            if channel:
                sent = await try_send(channel)
                if sent:
                    return True
                else:
                    log.debug(f"[ AUTODC CONSUMER ] ----- Primary channel {channel_id} unavailable or no permission, trying fallbacks")

        # 2) Try each guild's system channel
        for guild in self.bot.guilds:
            sys_ch = guild.system_channel
            if sys_ch:
                # use guild.me for permission check inside try_send
                sent = await try_send(sys_ch)
                if sent:
                    return True

        # 3) Final fallback: any text channel in any guild where bot can send
        for guild in self.bot.guilds:
            # prefer visible text channels (skip categories/voice)
            for ch in guild.text_channels:
                sent = await try_send(ch)
                if sent:
                    return True

        log.warning("[ AUTODC CONSUMER ] ----- Could not send embed to any channel")
        return False


    async def _disconnect_member(self, guild_id: int, user_id: int, info: dict):
        """Disconnect member from voice channel with comprehensive checks."""
        guild = self.bot.get_guild(guild_id)
        channel_id = info.get("channel_id")
        request_by = info.get("request_by")
        task_id = info.get("task_id", "unknown")

        if not guild:
            await self._send_embed_to_channel(
                channel_id or 0, 
                "❌ Gagal Auto-Disconnect", 
                "Guild not found.",
                discord.Color.red()
            )
            return

        member = guild.get_member(user_id)
        if not member:
            await self._send_embed_to_channel(
                channel_id, 
                "❌ Gagal Auto-Disconnect", 
                f"User <@{user_id}> tidak ditemukan di server.",
                discord.Color.red()
            )
            return

        # Check immunity before disconnect (double-check)
        if await self._is_immune(guild_id, user_id):
            await self._send_embed_to_channel(
                channel_id,
                "🛡️ User Sedang Immune",
                f"<@{user_id}> sedang immune — auto-disconnect dibatalkan.\n"
                f"-# Requester : <@{request_by}>",
                discord.Color.orange()
            )
            return

        # Check if user is still in voice
        if not member.voice or not member.voice.channel:
            await self._send_embed_to_channel(
                channel_id,
                "⚠️ Tidak Dapat Disconnect",
                f"<@{user_id}> sudah tidak ada di voice channel.\n"
                f"-# Requester : <@{request_by}>",
                discord.Color.orange()
            )
            return

        # Check bot permissions
        if not guild.me.guild_permissions.move_members:
            await self._send_embed_to_channel(
                channel_id,
                "❌ Gagal Disconnect",
                f"Bot tidak memiliki izin untuk memindahkan anggota.\n"
                f"Task: `{task_id[:8]}`",
                discord.Color.red()
            )
            return

        # Attempt to disconnect
        try:
            old_channel = member.voice.channel.name
            await member.move_to(None)
            
            await self._send_embed_to_channel(
                channel_id,
                "👋 Berhasil Disconnect",
                f"{member.display_name} Telah dikeluarkan dari voice-channel\n"
                f"-# Requester: <@{request_by}>",
                discord.Color.green()
            )
            
            log.info(f"[ AUTODC CONSUMER ] ----- Successfully disconnected {member} from {old_channel}")
            
        except discord.HTTPException as e:
            log.error(f"[ AUTODC CONSUMER ] ----- Failed to move member {member}: {e}")
            await self._send_embed_to_channel(
                channel_id,
                "❌ Gagal Disconnect",
                f"Gagal memindahkan {member.mention}: `{str(e)[:100]}`\n"
                f"Task: `{task_id[:8]}`",
                discord.Color.red()
            )
        except Exception as e:
            log.error(f"[ AUTODC CONSUMER ] ----- Unexpected error disconnecting {member}: {e}")
            await self._send_embed_to_channel(
                channel_id,
                "❌ Error Disconnect",
                f"Terjadi error saat disconnect {member.mention}\n"
                f"Task: `{task_id[:8]}`",
                discord.Color.red()
            )

    async def _on_cancel_message(self, message: IncomingMessage):
        """Handle cancel message from RabbitMQ."""
        async with message.process():
            try:
                data = json.loads(message.body.decode())
                task_id = data.get("task_id")
                
                if not task_id:
                    log.warning("[ AUTODC CONSUMER ] ----- Received cancel message without task_id")
                    return

                # Add to cancelled set
                self.cancelled_task_ids.add(task_id)
                
                # Cleanup cancelled tasks set if too large
                self._cleanup_cancelled_tasks()
                
                log.debug(f"[ AUTODC CONSUMER ] ----- Marked task {task_id[:8]} as cancelled")
                
            except json.JSONDecodeError as e:
                log.error(f"[ AUTODC CONSUMER ] ----- Invalid JSON in cancel message: {e}")
            except Exception as e:
                log.error(f"[ AUTODC CONSUMER ] ----- Error handling cancel message: {e}")

    async def _on_autodc_message(self, message: IncomingMessage):
        """Handle autodc message from RabbitMQ."""
        async with message.process():
            try:
                data = json.loads(message.body.decode())
                task_id = data.get("task_id")
                guild_id = data.get("guild_id")
                user_id = data.get("user_id")

                if not all([task_id, guild_id, user_id]):
                    log.warning("[ AUTODC CONSUMER ] ----- Received autodc message with missing data")
                    return

                # Check if task was cancelled
                if task_id in self.cancelled_task_ids:
                    self.cancelled_task_ids.discard(task_id)
                    log.debug(f"[ AUTODC CONSUMER ] ----- Ignored cancelled task {task_id[:8]}")
                    return

                log.info(f"[ AUTODC CONSUMER ] ----- Processing autodc task {task_id[:8]} for user {user_id}")

                # Perform disconnect
                await self._disconnect_member(guild_id, user_id, data)

                # Cleanup Redis (remove active task)
                await self._remove_active_task(user_id)
                
                log.debug(f"[ AUTODC CONSUMER ] ----- Completed autodc task {task_id[:8]}")

            except json.JSONDecodeError as e:
                log.error(f"[ AUTODC CONSUMER ] ----- Invalid JSON in autodc message: {e}")
            except Exception as e:
                log.error(f"[ AUTODC CONSUMER ] ----- Error handling autodc message: {e}")

    @commands.command(name="clear_cancelled")
    @commands.has_permissions(administrator=True)
    async def clear_cancelled(self, ctx):
        """Clear cancelled tasks from memory (admin only)."""
        count = len(self.cancelled_task_ids)
        self.cancelled_task_ids.clear()
        await ctx.send(f"✅ Cleared {count} cancelled task IDs from memory.")

async def setup(bot):
    await bot.add_cog(AutoDCConsumer(bot))