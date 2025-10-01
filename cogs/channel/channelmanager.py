import asyncio
import logging
import discord

from discord.ext import commands
from discord import app_commands

from services.channel import TextChannelDB as db
from services.channel import TextChannelRedis as redis

logger = logging.getLogger(__name__)

class ActiveChannel(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.disabled_channels = {}
        self.master_channels_ai = {}
        self.second_channels = {}

    async def cog_load(self):
        asyncio.create_task(self.delayed_load())
    
    async def delayed_load(self):
        await self.bot.wait_until_ready()
        await self.load_all_channel_data()
        logger.info("[ ALL CHANNEL CACHE ] --------- Load All Channel Settings.")
        
    @commands.hybrid_command(name="disable", description="Nonaktifkan channel agar tidak didengarkan Yumna.")
    @commands.has_permissions(administrator=True)
    @app_commands.describe(channel="Channel yang ingin dinonaktifkan (kosongkan untuk channel ini)")
    async def disable_channel(self, ctx: commands.Context, channel: discord.TextChannel = None):
        guild = ctx.guild

        if channel:
            target_channel = channel
        else:
            target_channel = ctx.channel

        guild_id = guild.id
        target_channel_id = target_channel.id

        self.disabled_channels.setdefault(guild_id, set()).add(target_channel_id)

        key = f"voisa:disabled_channels:{guild_id}"
        disabled = self.disabled_channels[guild_id]
        await self.bot.redis.set(key, ",".join(str(cid) for cid in disabled))

        await ctx.reply(f"🔇 Yumna tidak lagi mendengarkan channel {target_channel.mention}.", ephemeral=True)

    @commands.hybrid_command(name="enable", description="Aktifkan kembali channel agar didengarkan Yumna.")
    @commands.has_permissions(administrator=True)
    @app_commands.describe(channel="Channel yang ingin diaktifkan kembali (kosongkan untuk channel ini)")
    async def enable_channel(self, ctx: commands.Context, channel: discord.TextChannel = None):
        guild = ctx.guild

        if channel:
            target_channel = channel
        else:
            target_channel = ctx.channel

        guild_id = guild.id
        target_channel_id = target_channel.id

        self.disabled_channels.setdefault(guild_id, set()).discard(target_channel_id)

        key = f"voisa:disabled_channels:{guild_id}"
        disabled = self.disabled_channels[guild_id]
        if disabled:
            await self.bot.redis.set(key, ",".join(str(cid) for cid in disabled))
        else:
            await self.bot.redis.delete(key)

        await ctx.reply(f"✅ Channel {target_channel.mention} didengarkan kembali oleh-ku.", ephemeral=True)
        
    async def is_active_channel(self, guild_id: int, channel_id: int) -> bool:
        disabled = self.disabled_channels.get(guild_id, set())
        return channel_id not in disabled
    
# --- updated ActiveChannel.is_master_channel (replace the existing method in your ActiveChannel cog) ---
    async def is_master_channel(self, guild_id: int, channel_id: int) -> bool:
        """
        Return True if the channel_id is configured as master OR as second channel for the guild.
        This method will lazy-load values from redis/db and cache them in memory dicts:
        - self.master_channels_ai[guild_id]
        - self.second_channels[guild_id]
        """
        try:
            # 1) Try memory cache first
            master = self.master_channels_ai.get(guild_id)
            second = self.second_channels.get(guild_id)

            # 2) Load master channel if missing
            if master is None:
                try:
                    master = await redis.get_master_channel_cache(self, guild_id)
                except Exception:
                    master = None

                if not master:
                    try:
                        master = await db.get_master_channel(guild_id)
                    except Exception:
                        master = None

                    if master:
                        # persist to redis if we successfully read from DB
                        try:
                            await redis.save_master_channel_cache(self, guild_id, master)
                        except Exception:
                            pass

                # normalize and cache (allow None)
                self.master_channels_ai[guild_id] = int(master) if master else None
                master = self.master_channels_ai[guild_id]

            # 3) Load second channel if missing
            if second is None:
                try:
                    second = await redis.get_second_channel_cache(self, guild_id)
                except Exception:
                    second = None

                if not second:
                    try:
                        second = await db.get_second_channel(guild_id)
                    except Exception:
                        second = None

                    if second:
                        try:
                            await redis.save_second_channel_cache(self, guild_id, second)
                        except Exception:
                            pass

                # normalize and cache (remove if None)
                if second:
                    self.second_channels[guild_id] = int(second)
                else:
                    # ensure no stale entry
                    self.second_channels.pop(guild_id, None)

                second = self.second_channels.get(guild_id)

            # 4) Final check against cached values
            return (master is not None and channel_id == master) or (second is not None and channel_id == second)

        except Exception:
            # on any unexpected error, be conservative and deny access
            return False
                
    @commands.hybrid_command(name="set_channel", description="Set channel sebagai channel utama Yumna.")
    @commands.has_permissions(administrator=True)
    @app_commands.describe(channel="Channel yang ingin dijadikan sebagai channel utama Yumna")
    async def set_main_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        await ctx.defer()

        guild_id = ctx.guild.id
        channel_id = channel.id

        # 1. Insert ke mem dict
        self.master_channels_ai[guild_id] = channel_id

        try:
            # 2. Insert ke db
            db_insert = await db.insert_master_channel(guild_id, channel_id)
            if db_insert:
                # 3. Insert ke redis
                await redis.save_master_channel_cache(self, guild_id, channel_id)
                await ctx.reply(f"✅ Channel {channel.mention} telah diset sebagai channel utama Yumna.", ephemeral=True)
            else:
                await ctx.reply(f"❌ Gagal menyimpan channel utama ke database.", ephemeral=True)
        except Exception as e:
            await ctx.reply(f"❌ Terjadi kesalahan saat menyimpan ke database: `{e}`", ephemeral=True)
            
    @commands.hybrid_command(name="set_channel2", description="Set channel ke-2 sebagai channel utama Yumna.")
    @commands.has_permissions(administrator=True)
    @app_commands.describe(channel="Channel yang ingin dijadikan sebagai channel utama Yumna")
    async def set_second_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        await ctx.defer()

        guild_id = ctx.guild.id
        channel_id = channel.id
        
        if guild_id != self.bot.main_guild_id:
            await ctx.reply("Gagal!\n-# Guild tidak diizinkan menambah jumlah channel utama.")
            return

        # 1. Insert ke mem dict
        self.second_channels[guild_id] = channel_id

        try:
            # 2. Insert ke db
            db_insert = await db.insert_second_channel(guild_id, channel_id)
            if db_insert:
                # 3. Insert ke redis
                await redis.save_second_channel_cache(self, guild_id, channel_id)
                await ctx.reply(f"✅ Channel {channel.mention} telah diset sebagai channel utama Yumna.", ephemeral=True)
            else:
                await ctx.reply(f"❌ Gagal menyimpan channel utama ke database.", ephemeral=True)
        except Exception as e:
            await ctx.reply(f"❌ Terjadi kesalahan saat menyimpan ke database: `{e}`", ephemeral=True)
    
    async def load_all_channel_data(self):
        try:
            # 1. Ambil semua key master_channel_ai:<guild_id>
            cursor = 0
            master_keys = []
            while True:
                cursor, batch = await self.bot.redis.scan(
                    cursor=cursor,
                    match="voisa:master_channel_ai:*",
                    count=100
                )
                master_keys.extend(batch)
                if cursor == 0:
                    break

            # 2. Ambil semua key disabled_channels:<guild_id>
            cursor = 0
            disabled_keys = []
            while True:
                cursor, batch = await self.bot.redis.scan(
                    cursor=cursor,
                    match="voisa:disabled_channels:*",
                    count=100
                )
                disabled_keys.extend(batch)
                if cursor == 0:
                    break

            # 3. Proses master_keys
            for raw_key in master_keys:
                key = raw_key.decode() if isinstance(raw_key, bytes) else raw_key
                # key format: "voisa:master_channel_ai:<guild_id>"
                parts = key.split(":")
                if len(parts) != 3:
                    continue

                try:
                    guild_id = int(parts[2])
                except ValueError:
                    continue

                raw_val = await self.bot.redis.get(key)
                if raw_val:
                    try:
                        data_master = raw_val.decode("utf-8") if isinstance(raw_val, bytes) else raw_val
                        channel_id = int(data_master)
                        self.master_channels_ai[guild_id] = channel_id
                    except (ValueError, AttributeError):
                        self.master_channels_ai[guild_id] = None
                else:
                    self.master_channels_ai[guild_id] = None

            # 4. Proses disabled_keys
            for raw_key in disabled_keys:
                key = raw_key.decode() if isinstance(raw_key, bytes) else raw_key
                # key format: "voisa:disabled_channels:<guild_id>"
                parts = key.split(":")
                if len(parts) != 3:
                    continue

                try:
                    guild_id = int(parts[2])
                except ValueError:
                    continue

                raw_val = await self.bot.redis.get(key)
                if raw_val:
                    try:
                        data_disabled = raw_val.decode("utf-8") if isinstance(raw_val, bytes) else raw_val
                        channel_ids = {
                            int(cid) for cid in data_disabled.split(",") if cid.strip().isdigit()
                        }
                        self.disabled_channels[guild_id] = channel_ids
                    except Exception:
                        self.disabled_channels[guild_id] = set()
                else:
                    self.disabled_channels[guild_id] = set()

        except Exception as e:
            print(f"Error in load_all_channel_data: {e}")

async def setup(bot):
    cog = ActiveChannel(bot)
    bot.ChannelManager = cog  
    await bot.add_cog(cog)