import asyncio
import signal
import logging
import random
import aiohttp
import sys
import aio_pika

import discord

from core import db, redis
from discord.ext import commands, tasks
from pathlib import Path
from typing import Optional, List, Dict, Any
from utils.logger import setup_logging
from config import BotSetting, RabbitMQ
from utils.views.embed import EmbedBasicCommands as Embed

from cogs.chatbot.helper.aiutils import groq_utils


# Setup logging first
setup_logging()

log = logging.getLogger(__name__)

class YumnaBot(commands.Bot):    
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(
            command_prefix=BotSetting.PREFIX,
            intents=intents,
            help_command=None
        )
        
        # Bot attributes
        self.is_shutting_down = False
        self.http_session: Optional[aiohttp.ClientSession] = None
        self.db: Optional[Any] = None
        self.redis: Optional[Any] = None
        
        self.ai = groq_utils
        self.ai.set_bot(self)
        
        self.autodc_tasks = {}        # user_id -> task_id
        self.autodc_task_info = {}    # task_id -> {guild_id, user_id, scheduled_at, duration_str, initiator_id}
        self.autodc_immune = {}            
        

        self.main_guild_id = 1234390981470715954        

        self._status_task: Optional[asyncio.Task] = None
        
    async def on_ready(self):
        """Called when bot is ready."""
        # Ensure this runs only once
        if not getattr(self, "_ready_called", False):
            self._ready_called = True

            # Start status change task safely
            try:
                if not self.change_status.is_running():
                    self.change_status.start()
                    log.info("[ STATUS TASK ] ---------- change_status started")
            except Exception as e:
                log.error(f"[ STATUS TASK ] ---------- Failed to start change_status: {e}")

            log.info(f'[ {self.user} ] ----------- Bot is ready!')
            log.info(f'[ PREFIX ] ---------------- Loaded prefix: {BotSetting.PREFIX}')
            
            # Sync slash commands
            try:
                synced = await self.tree.sync()
                log.info(f"[ SLASH COMMANDS ] -------- Synced {len(synced)} commands")
            except Exception as e:
                log.error(f"[ SLASH COMMANDS ] -------- Sync error: {e}")
                
    @tasks.loop(seconds=60)
    async def change_status(self):
        """
        Periodic task to update bot presence.
        Uses Voicecount cog if available; if not, falls back gracefully.
        """
        try:
            # Try to get Voicecount cog (do not rely on attributes)
            voice_cog = self.get_cog('Voicecount')
            if voice_cog is None:
                # If cog not loaded yet, fallback to 0 and log debug
                voice_duration_count = 0
                log.debug("[ STATUS ] --------------- Voicecount cog not loaded; using 0")
            else:
                # Safely get voice_start_times attribute (could be any structure)
                try:
                    voice_start_times = getattr(voice_cog, 'voice_start_times', None)
                    if voice_start_times is None:
                        voice_duration_count = 0
                    else:
                        # If it's a dict/list/other, try to get its length
                        try:
                            voice_duration_count = len(voice_start_times)
                        except Exception:
                            # If it's something else, attempt safe cast
                            voice_duration_count = int(voice_start_times) if isinstance(voice_start_times, (int, float)) else 0
                except Exception as e:
                    log.error(f"[ STATUS ] --------------- Error reading voice_start_times: {e}")
                    voice_duration_count = 0

            total_guilds = len(self.guilds) if self.guilds is not None else 0

            options = [
                f"{total_guilds} servers",
                f"{voice_duration_count} people in voice"
            ]

            selected = random.choice(options)

            activity = discord.Activity(type=discord.ActivityType.listening, name=selected)
            try:
                await self.change_presence(status=discord.Status.online, activity=activity)
                log.debug(f"[ STATUS ] --------------- Presence updated: {selected}")
            except Exception as e:
                log.error(f"[ STATUS ] --------------- Failed to change presence: {e}")

        except Exception as e:
            # Catch-all to ensure loop keeps running on next tick
            log.error(f"[ STATUS LOOP ] --------- Unexpected error in change_status loop: {e}")
        

        
    ### MESSAGE HANDLER        
    async def on_message(self, message: discord.Message):
        """Handle incoming messages."""
        if message.author.bot or self.is_shutting_down:
            return

        # Handle enable/disable commands first
        if message.content.startswith(tuple(BotSetting.PREFIX)):
            ctx = await self.get_context(message)
            if ctx.command and ctx.command.name in ("enable", "disable"):
                await self.process_commands(message)
                return

        # Check if channel is active
        try:
            if hasattr(self, 'ChannelManager'):
                active = await self.ChannelManager.is_active_channel(
                    message.guild.id, message.channel.id
                )
                if not active:
                    return
        except Exception as e:
            log.error(f"[ CHANNEL CHECK ] --------- Error checking channel: {e}")
            return

        # Process commands
        if message.content.startswith(tuple(BotSetting.PREFIX)):
            await self.process_commands(message)
            return
        
    async def on_command_error(self, ctx: commands.Context, error: Exception):
        """Handle command errors."""
        error_handlers = {
            # commands.CommandNotFound: lambda: Embed.NotFound(ctx),
            commands.MissingRequiredArgument: lambda: Embed.MissingArgument(ctx),
            commands.MissingPermissions: lambda: Embed.MissingPermission(),
        }

        embed_func = error_handlers.get(type(error), lambda: Embed.GenericError(ctx))
        
        try:
            await ctx.send(embed=embed_func())
        except discord.HTTPException:
            pass  # Ignore if we can't send the error message
            
        log.error(f"[ COMMAND ERROR ] --------- {type(error).__name__}: {error}")
        
    
    ### RABBIT INIT    
    async def init_rabbit_connection(self):
        try:
            self.rabbit_conn = await aio_pika.connect_robust(RabbitMQ().RABBIT_URL)
            ch = await self.rabbit_conn.channel()
            await ch.set_qos(prefetch_count=10)

            # declare x-delayed-message exchange (plugin required)
            await ch.declare_exchange(
                RabbitMQ.AUTODC_EXCHANGE,
                type="x-delayed-message",
                durable=True,
                arguments={"x-delayed-type": "direct"}
            )

            # declare queues (idempotent)
            q = await ch.declare_queue(RabbitMQ.AUTODC_QUEUE, durable=True)
            await q.bind(RabbitMQ.AUTODC_EXCHANGE, routing_key=RabbitMQ.ROUTING_KEY)
            await ch.declare_queue(RabbitMQ.AUTODC_CANCEL_QUEUE, durable=True)

            await ch.close()
            return self.rabbit_conn
        except Exception as e:
            log.error(f"[ RABBIT MQ ] ---------- Failed to init connection: {e}")
            # re-raise so setup_hook can handle/close bot
            raise


    async def close_rabbit_connection(self):
        if getattr(self, "rabbit_conn", None):
            try:
                await self.rabbit_conn.close()
            except Exception as e:
                log.error(f"[ RABBIT MQ ] ---------- Error closing connection: {e}")

    ### SETUP HOOK
    async def setup_hook(self):
        """Called when the bot is starting up."""
        try:
            
            self.redis = await redis.init_redis()
            log.info("[ REDIS ] -------------------- Redis pool initialized")

            await db.init_db_pool()
            log.info("[ DB ] -------------------- Database pool initialized")

            self.http_session = aiohttp.ClientSession()
            log.info("[ HTTP SESSION ] ---------- HTTP session created")
            
            await self.init_rabbit_connection()
            log.info("[ RABBIT MQ ] ------------- RabbitMQ connection established")

            # Load all cogs
            await self._load_cogs()
            log.info("[ COGS ] ------------------ All cogs loaded successfully")
            
            # Setup signal handlers
            self._setup_signal_handlers()
            
        except Exception as e:
            log.error(f"[ SETUP ERROR ] ----------- Error during setup: {e}")
            await self.close()
            raise

    def _setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown."""
        if sys.platform != "win32":  # Unix systems only
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(
                    sig, lambda s=sig: asyncio.create_task(self._signal_handler(s))
                )

    async def _signal_handler(self, sig: signal.Signals):
        """Handle shutdown signals."""
        log.warning(f"[ SIGNAL ] ---------------- Received {sig.name}, initiating shutdown")
        await self._graceful_shutdown()

    async def _load_cogs(self):
        """Load all cogs from the configured folders."""
        loaded_count = 0
        failed_cogs = []

        for folder in BotSetting.COGS_FOLDER:
            folder_path = Path(f'cogs/{folder}')
            if not folder_path.exists():
                log.warning(f"[ COGS ] ------------------ Folder not found: {folder}")
                continue

            for file_path in folder_path.glob('*.py'):
                if file_path.name == '__init__.py':
                    continue

                extension_name = f'cogs.{folder}.{file_path.stem}'
                try:
                    await self.load_extension(extension_name)
                    loaded_count += 1
                    log.debug(f"[ COGS ] ------------------ Loaded: {extension_name}")
                except commands.ExtensionAlreadyLoaded:
                    log.debug(f"[ COGS ] ------------------ Already loaded: {extension_name}")
                except Exception as e:
                    failed_cogs.append((extension_name, str(e)))
                    log.error(f"[ COGS ] ------------------ Failed to load {extension_name}: {e}")

        log.info(f"[ COGS ] ------------------ Loaded {loaded_count} cogs successfully")
        if failed_cogs:
            log.warning(f"[ COGS ] ------------------ Failed to load {len(failed_cogs)} cogs")

    async def _unload_cogs(self):
        """Unload all cogs."""
        unloaded_count = 0
        
        for folder in BotSetting.COGS_FOLDER:
            folder_path = Path(f'cogs/{folder}')
            if not folder_path.exists():
                continue

            for file_path in folder_path.glob('*.py'):
                if file_path.name == '__init__.py':
                    continue

                extension_name = f'cogs.{folder}.{file_path.stem}'
                try:
                    await self.unload_extension(extension_name)
                    unloaded_count += 1
                except commands.ExtensionNotLoaded:
                    pass
                except Exception as e:
                    log.error(f"[ COGS ] ------------------ Failed to unload {extension_name}: {e}")

        log.info(f"[ COGS ] ------------------ Unloaded {unloaded_count} cogs")

    async def _graceful_shutdown(self):
        """Perform graceful shutdown."""
        if self.is_shutting_down:
            return
            
        self.is_shutting_down = True
        log.warning("[ SHUTDOWN ] -------------- Starting graceful shutdown")

        try:

            await db.close_pool()
            log.info("[ DB ] -------------------- Database pool closed")
            
            await redis.close_redis()
            log.info("[ REDIS ] -------------------- Redis pool closed")
            
            if getattr(self, "rabbit_conn", None):
                await self.close_rabbit_connection()
                log.info("[ SHUTDOWN ] ------------- RabbitMQ closed")
                
            # Close HTTP session
            if self.http_session and not self.http_session.closed:
                await self.http_session.close()
                log.info("[ SHUTDOWN ] -------------- HTTP session closed")

            # Unload cogs
            await self._unload_cogs()
            log.info("[ SHUTDOWN ] -------------- Cogs unloaded")

        except Exception as e:
            log.error(f"[ SHUTDOWN ] -------------- Error during shutdown: {e}")
        finally:
            # Close bot connection
            if not self.is_closed():
                await self.close()
            log.warning("[ SHUTDOWN ] -------------- Shutdown complete")

    async def close(self):
        """Override close to ensure cleanup."""
        if not self.is_shutting_down:
            await self._graceful_shutdown()
        await super().close()

async def main():
    """Main entry point."""
    bot = YumnaBot()
    
    try:
        async with bot:
            await bot.start(BotSetting.TOKEN)
    except KeyboardInterrupt:
        log.info("[ MAIN ] ------------------ Received keyboard interrupt")
    except Exception as e:
        log.error(f"[ MAIN ] ------------------ Fatal error: {e}")
        raise
    finally:
        log.info("[ MAIN ] ------------------ Bot stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("[ SIGNAL ] ---------------- Keyboard interrupt received")
    except Exception as e:
        log.error(f"[ FATAL ] ----------------- Fatal error: {e}")
        sys.exit(1)