import logging
import asyncio
import json
from time import monotonic
from datetime import datetime, timezone
from utils.decorator.spender import requires_balance

from discord.ext import commands, tasks
from utils.time import get_current_date_uptime
from .database.dbcounter import VoiceCounterQuery as db
from .database.redis import VoiceCount as cd
from utils.views.embed import daily_cooldown

from services import economy

log = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 3600
VOICE_EVENT_CACHE_TTL = 86400  # sekitar 24 jam

async def get_cache_count(self, member_id: int, guild_id: int) -> bool:
    key = f"voice:is_count:{guild_id}:{member_id}"
    try:
        cached = await self.bot.redis.get(key)
        if cached is not None:
            return cached.decode() == "1" if isinstance(cached, bytes) else str(cached) == "1"
        is_count = await db.validate_member_count(member_id, guild_id)
        await self.bot.redis.set(key, "1" if is_count else "0", ex=CACHE_TTL_SECONDS)
        return is_count
    except Exception as e:
        log.error(f"Error in get_cache_count: {e}")
        return False

class Voicecount(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
        # Struktur data untuk voice counter (tidak diubah)
        self.voice_start_times = {}    # member_id -> start_time (monotonic)
        self.voice_count_buffer = {}   # member_id -> jumlah join sejak terakhir flush
        self.voice_guild_map = {}      # member_id -> guild_id
        self.voice_channel_map = {}    # member_id -> current channel_id
        self.voice_lock = asyncio.Lock()  # untuk synchronisasi
        self._event_lock = asyncio.Lock()
        self.track_member_stats.start()

    async def cog_load(self):
        asyncio.create_task(self.loaded_cogs_start())

    async def loaded_cogs_start(self):
        await self.bot.wait_until_ready()
        # Delay ekstra untuk memastikan guilds, members ter-cache
        await asyncio.sleep(5)
        
        log.info("[ VOICE INIT ] Starting initial voice channel scan...")
        start_time = monotonic()
        member_count = 0
        
        async with self.voice_lock:
            for guild in self.bot.guilds:
                if not guild.voice_channels:
                    continue
                for channel in guild.voice_channels:
                    if self.is_ignored(channel):
                        continue
                    for member in channel.members:
                        if member.bot:
                            continue
                        member_id = member.id
                        guild_id = guild.id
                        # Cek apakah count diaktifkan untuk user
                        if not await get_cache_count(self, member_id, guild_id):
                            continue
                        # Set state counter seperti semula
                        self.voice_start_times[member_id] = monotonic()
                        self.voice_guild_map[member_id] = guild_id
                        self.voice_channel_map[member_id] = channel.id
                        member_count += 1
                        # Event log: proses join via Redis
                        key = f"voice:join:{guild_id}:{member_id}"
                        exists = await self.bot.redis.get(key)
                        if not exists:
                            asyncio.create_task(
                                self.process_join_event(
                                    guild_id=guild_id,
                                    member_id=member_id,
                                    channel_id=channel.id
                                )
                            )
                        else:
                            # Key sudah ada: bot restart cepat; bila ingin reset join_time ke now, uncomment:
                            # asyncio.create_task(self.process_join_event(...))
                            pass
        
        duration = round(monotonic() - start_time, 2)
        log.info(f"[ VOICE INIT ] Completed scan in {duration}s. Tracking {member_count} members in voice channels.")

    def reset_state(self):
        # Reset semua state internal
        self.voice_start_times.clear()
        self.voice_count_buffer.clear()
        self.voice_guild_map.clear()
        self.voice_channel_map.clear()
        
    async def cog_unload(self):
        # Cancel loop dan reset state
        if self.track_member_stats.is_running():
            self.track_member_stats.cancel()
        self.reset_state()

    async def process_join_event(self, guild_id: int, member_id: int, channel_id: int):
        try:
            await asyncio.wait_for(self._event_lock.acquire(), timeout=1.0)
        except asyncio.TimeoutError:
            log.warning("Event lock timeout, skip logging")
            return

        try:
            key = f"voice:join:{guild_id}:{member_id}"
            data = {
                "channel_id": channel_id,
                "join_time": datetime.now(timezone.utc).isoformat()
            }
            await self.bot.redis.set(key, json.dumps(data), ex=VOICE_EVENT_CACHE_TTL)
            log.debug(f"[ VOICE LOG ] process_join_event: set Redis key {key}")
        except Exception as e:
            log.error(f"Gagal simpan join event untuk {member_id}: {e}", exc_info=True)
        finally:
            # pastikan selalu dilepas
            self._event_lock.release()

    async def process_leave_event(self, guild_id: int, member_id: int, channel_id: int):
        try:
            await asyncio.wait_for(self._event_lock.acquire(), timeout=1.0)
        except asyncio.TimeoutError:
            log.warning("Event lock timeout, skip logging")
            return
        try:
            key = f"voice:join:{guild_id}:{member_id}"
            cached = await self.bot.redis.get(key)
            if not cached:
                log.warning(f"[ VOICE LOG ][ ORPHAN LEAVE ] Tidak ditemukan join untuk user {member_id} di guild {guild_id}, abaikan leave.")
                return
            data = json.loads(cached)
            # Parse join_time; hasil ISO format termasuk offset +00:00
            try:
                join_time = datetime.fromisoformat(data["join_time"])
            except Exception:
                # Jika parsing gagal, hapus key
                log.warning(f"[ VOICE LOG ] Gagal parse join_time untuk key {key}, menghapus key.")
                await self.bot.redis.delete(key)
                return

            leave_time = datetime.now(timezone.utc)
            # Pastikan join_time juga aware UTC; jika parsed hasil naive, bisa menambahkan:
            if join_time.tzinfo is None:
                join_time = join_time.replace(tzinfo=timezone.utc)
            duration = int((leave_time - join_time).total_seconds())
            
            await db.insert_voice_event(
                guild_id=guild_id,
                user_id=member_id,
                channel_id=channel_id,
                join_time=join_time,
                leave_time=leave_time,
                duration=duration
            )
            
            # --- hitung reward ---
            balance_gain = int(duration / 3600 * 1000)  # 1000 per jam
            xp_gain = int(duration / 3600 * 200)        # 200 per jam
            
            if balance_gain > 0 or xp_gain > 0:
                try:
                    await economy.earn_xp_balance(
                        guild_id=guild_id,
                        user_id=member_id,
                        username="unknown",  # bisa diganti fetch username kalau ada
                        xp_gain=xp_gain,
                        balance_gain=balance_gain,
                        reason="voice_activity",
                        tx_type="credit"
                    )
                    log.debug(f"[ VOICE REWARD ] {member_id} + {balance_gain} balance, +{xp_gain} xp (durasi {duration}s)")
                except Exception as e:
                    log.error(f"Gagal update reward untuk {member_id}: {e}", exc_info=True)

            await self.bot.redis.delete(key)
        except Exception as e:
            log.error(f"Gagal proses leave event untuk {member_id}: {e}", exc_info=True)
        finally:
            self._event_lock.release()
            
    def get_current_channel_id(self, guild_id: int, member_id: int) -> int | None:
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return None
        member = guild.get_member(member_id)
        if not member or not member.voice or not member.voice.channel:
            return None
        return member.voice.channel.id

    def is_ignored(self, channel) -> bool:
        IGNORED_CATEGORIES = {1378722805884915863,1406382443652579403, 1409061694914953236}
        return channel.category_id in IGNORED_CATEGORIES if channel and channel.category_id else False

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot:
            return

        async with self.voice_lock:
            guild_id = member.guild.id
            member_id = member.id
            username = member.name

            # Cek apakah count diaktifkan untuk user
            if not await get_cache_count(self, member_id, guild_id):
                # log.info(f"[ IGNORE VOICE COUNT ]: {member.guild.name} [{username}]")
                return

            # Join: sebelum None, sesudah ada channel
            if before.channel is None and after.channel is not None:
                if not self.is_ignored(after.channel):  # Tambahkan pengecekan di sini
                    await self.on_voice_join(member_id, guild_id, monotonic())

            # Move: kedua non-None dan ID berbeda
            elif before.channel is not None and after.channel is not None:
                if before.channel.id != after.channel.id:
                    await self.on_voice_move(member_id, guild_id, monotonic(), username)
                # Jika ID sama: hanya mute/deafen dsb., ignore

            # Leave: sebelum ada channel, sesudah None
            elif before.channel is not None and after.channel is None:
                if not self.is_ignored(before.channel):  # Tambahkan pengecekan di sini
                    await self.on_voice_leave(member_id, guild_id, monotonic(), username)

    async def on_voice_join(self, member_id, guild_id, current_time):
        self.voice_start_times[member_id] = current_time
        self.voice_guild_map[member_id] = guild_id
        self.voice_count_buffer[member_id] = self.voice_count_buffer.get(member_id, 0) + 1

        # Event log join
        channel_id = self.get_current_channel_id(guild_id, member_id)
        if channel_id is not None:
            self.voice_channel_map[member_id] = channel_id
            log.debug(f"[ VOICE JOIN ] calling process_join_event for {member_id}")
            await self.process_join_event(guild_id=guild_id, member_id=member_id, channel_id=channel_id)
        else:
            log.warning(f"[ VOICE JOIN ] Gagal ambil channel_id untuk user {member_id} di guild {guild_id}")

    async def on_voice_move(self, member_id, guild_id, current_time, username):
        # 2) Ambil old & new channel untuk event log dan pengecekan ignored
        old_channel_id = self.voice_channel_map.get(member_id)
        new_channel_id = self.get_current_channel_id(guild_id, member_id)
        
        # Dapatkan objek channel untuk pengecekan ignored
        guild = self.bot.get_guild(guild_id)
        old_channel = guild.get_channel(old_channel_id) if old_channel_id else None
        new_channel = guild.get_channel(new_channel_id) if new_channel_id else None
        
        old_ignored = self.is_ignored(old_channel)
        new_ignored = self.is_ignored(new_channel)
        
        # === HANDLING IGNORED CATEGORIES ===
        
        # Scenario 1: Dari channel biasa ke ignored category
        if not old_ignored and new_ignored:
            # 1) Selesaikan durasi lama (sama seperti fungsi asli)
            if member_id in self.voice_start_times:
                duration = round(current_time - self.voice_start_times.pop(member_id))
                try:
                    await self.update_time(guild_id, member_id, username, duration)
                except Exception as e:
                    log.error(f"Gagal update_time di move: {e}")
            
            # 3) Proses leave event untuk channel lama
            if old_channel_id:
                log.debug(f"[ VOICE MOVE ] leave {old_channel_id} (moving to ignored) for {member_id}")
                await self.process_leave_event(guild_id, member_id, old_channel_id)
            
            # Cleanup state - user masuk ke ignored category
            self.voice_guild_map.pop(member_id, None)
            self.voice_channel_map.pop(member_id, None)
            # Jangan hapus voice_count_buffer karena masih bisa dipakai nanti
            return
        
        # Scenario 2: Dari ignored category ke channel biasa  
        elif old_ignored and not new_ignored:
            # Mulai tracking baru (seperti join)
            # 4) Update state counter
            self.voice_start_times[member_id] = current_time
            self.voice_guild_map[member_id] = guild_id
            self.voice_count_buffer[member_id] = self.voice_count_buffer.get(member_id, 0) + 1
            
            # 5) Update channel map
            if new_channel_id is not None:
                self.voice_channel_map[member_id] = new_channel_id
                # 3) Proses join event untuk channel baru
                log.debug(f"[ VOICE MOVE ] join {new_channel_id} (from ignored) for {member_id}")
                await self.process_join_event(guild_id, member_id, new_channel_id)
            else:
                self.voice_channel_map.pop(member_id, None)
            return
        
        # Scenario 3: Kedua channel diabaikan - tidak perlu tracking apapun
        elif old_ignored and new_ignored:
            return
        
        # === FUNGSI ASLI - Move antar channel biasa ===
        # Scenario 4: Move antar channel biasa (tidak ada yang ignored)
        elif not old_ignored and not new_ignored:
            # 1) Counter logic: selesaikan durasi lama dan buffer join (FUNGSI ASLI)
            if member_id in self.voice_start_times:
                duration = round(current_time - self.voice_start_times[member_id])
                try:
                    await self.update_time(guild_id, member_id, username, duration)
                except Exception as e:
                    log.error(f"Gagal update_time di move: {e}")

            # 3) Proses event log sesi lama & baru (FUNGSI ASLI)
            if old_channel_id is not None and new_channel_id is not None and old_channel_id != new_channel_id:
                log.debug(f"[ VOICE MOVE ] leave {old_channel_id}, join {new_channel_id} for {member_id}")
                await self.process_leave_event(guild_id, member_id, old_channel_id)
                await self.process_join_event(guild_id, member_id, new_channel_id)

            # 4) Update state counter (FUNGSI ASLI)
            self.voice_start_times[member_id] = current_time
            self.voice_guild_map[member_id] = guild_id
            self.voice_count_buffer[member_id] = self.voice_count_buffer.get(member_id, 0) + 1

            # 5) Update channel map (FUNGSI ASLI)
            if new_channel_id is not None:
                self.voice_channel_map[member_id] = new_channel_id
            else:
                self.voice_channel_map.pop(member_id, None)

    async def on_voice_leave(self, member_id, guild_id, current_time, username):
        # Counter logic tetap:
        if member_id in self.voice_start_times:
            duration = round(current_time - self.voice_start_times.pop(member_id))
            gid = self.voice_guild_map.pop(member_id, guild_id)
            try:
                await self.update_time(gid, member_id, username, duration)
            except Exception as e:
                log.error(f"Gagal update_time di leave: {e}")

        # Event log leave
        channel_id = self.voice_channel_map.pop(member_id, None)
        if channel_id is not None:
            log.debug(f"[ VOICE LEAVE ]  calling process_leave_event for {member_id}")
            await self.process_leave_event(guild_id, member_id, channel_id)
        else:
            log.warning(f"[ VOICE LEAVE ] channel_id tidak ditemukan untuk user {member_id} di guild {guild_id}")

    async def update_time(self, guild_id: int, member_id: int, username: str, duration: int):
        today = get_current_date_uptime()
        try:
            await db.update_voice_duration(guild_id, member_id, today, username, duration)
        except Exception as e:
            log.error(f"Gagal update waktu voice: {e}")

    @tasks.loop(seconds=60)
    async def track_member_stats(self):
        now = monotonic()
        today = get_current_date_uptime()

        async with self.voice_lock:
            voice_duration_count = len(self.voice_start_times)
            voice_join_count_total = sum(self.voice_count_buffer.values())
            
            if voice_duration_count == 0 and voice_join_count_total == 0:
                return

            batch_data = []
            # --- Proses voice duration ---
            items = list(self.voice_start_times.items())
            for member_id, start_time in items:
                guild_id = self.voice_guild_map.get(member_id)
                username = self.bot.get_user(member_id).name if self.bot.get_user(member_id) else "unknown"
                duration = round(now - start_time)
                if guild_id and self.bot.get_user(member_id):
                    self.voice_start_times[member_id] = now
                    batch_data.append((guild_id, member_id, today, username, duration, 0))

            # --- Proses voice join count ---
            for member_id, count in list(self.voice_count_buffer.items()):
                guild_id = self.voice_guild_map.get(member_id)
                username = self.bot.get_user(member_id).name if self.bot.get_user(member_id) else "unknown"
                if guild_id and self.bot.get_user(member_id):
                    batch_data.append((guild_id, member_id, today, username, 0, count))
                self.voice_count_buffer.pop(member_id, None)

        total_records = len(batch_data)
        if total_records > 0:
            try:
                await db.batch_update_voice_stats(batch_data)
                #log.info(f"[ FLUSH ALL BUFFER ] ----- [ SUCCESS ] --- Total: [{total_records}]")
            except Exception as e:
                log.error(f"[ FLUSH ALL BUFFER ] ----- [ FAILED ] Gagal melakukan batch update: {e}")
        else:
            logging.debug("[ FLUSH ALL BUFFER ] ----- [ EMPTY ] Tidak ada data untuk di-flush.")

    @track_member_stats.before_loop
    async def before_flush_all(self):
        await self.bot.wait_until_ready()
        
    @commands.command(name="setcount")
    @commands.has_permissions(administrator=True)
    async def set_guild_count(self, ctx, option: str):
        guild_id = ctx.guild.id
        user_id = ctx.author.id
        option = option.lower()
        if option == "on":
            enabled = True
        elif option == "off":
            enabled = False
        else:
            await ctx.send("Gunakan `on` atau `off`.")
            return
        
        cooldown_time = await cd._guild_count_cooldown(self, guild_id, user_id, cooldown_seconds=86400)
                
        if cooldown_time > 0:
            embed = await daily_cooldown(cooldown_time)
            await ctx.send(embed=embed)
            return
        try:
            await db.guild_count_option(guild_id, enabled)
            cache_key = f"voice:is_count:{guild_id}:{user_id}"
            is_count = await db.validate_member_count(user_id, guild_id)
            await self.bot.redis.set(cache_key, "1" if is_count else "0", ex=CACHE_TTL_SECONDS)
            if enabled:
                await ctx.send("✅ **Voice count diaktifkan** di guild ini.\nSemua aktivitas voice akan mulai dihitung.")
            else:
                await ctx.send("⚠️ **Voice count dinonaktifkan** di guild ini.\nAktivitas voice tidak akan dihitung.")
        except Exception as e:
            log.error(f"Gagal update guild count: {e}")
            await ctx.send(f"Gagal update: {e}")

    @commands.command(name="voicecount", aliases=["countme"])
    @requires_balance(20000, "voicecount_usage")
    async def set_user_count(self, ctx, option: str):
        user_id = ctx.author.id
        guild_id = ctx.guild.id
        option = option.lower()
        
        if option == "on":
            enabled = True
        elif option == "off":
            enabled = False
        else:
            await ctx.send("Gunakan `on` atau `off`.")
            return
        
        cooldown_time = await cd._voice_count_cooldown(self, guild_id, user_id, cooldown_seconds=86400)
                
        if cooldown_time > 0:
            embed = await daily_cooldown(cooldown_time)
            await ctx.send(embed=embed)
            return
            
        try:
            async with self.voice_lock:
                # Update database setting
                await db.user_count_option(guild_id, user_id, enabled)
                
                # Update cache
                cache_key = f"voice:is_count:{guild_id}:{user_id}"
                is_count = await db.validate_member_count(user_id, guild_id)
                await self.bot.redis.set(cache_key, "1" if is_count else "0", ex=CACHE_TTL_SECONDS)
                
                if enabled:
                    # Jika countme diaktifkan, set voice_start_times jika user sedang di voice channel
                    member = ctx.guild.get_member(user_id)
                    if member and member.voice and member.voice.channel:
                        self.voice_start_times[user_id] = monotonic()
                        self.voice_guild_map[user_id] = guild_id
                        self.voice_channel_map[user_id] = member.voice.channel.id
                        # Pastikan event log join jika belum ada
                        key = f"voice:join:{guild_id}:{user_id}"
                        exists = await self.bot.redis.get(key)
                        if not exists:
                            asyncio.create_task(
                                self.process_join_event(
                                    guild_id=guild_id,
                                    member_id=user_id,
                                    channel_id=member.voice.channel.id
                                )
                            )
                    await ctx.send("✅ **Voice count diaktifkan**\n-# Yumna akan memperhatikan kamu ~")
                else:
                    # Jika countme dinonaktifkan, hapus semua data terkait user ini
                    if user_id in self.voice_start_times:
                        self.voice_start_times.pop(user_id)
                    if user_id in self.voice_guild_map:
                        self.voice_guild_map.pop(user_id)
                    if user_id in self.voice_channel_map:
                        self.voice_channel_map.pop(user_id)
                    if user_id in self.voice_count_buffer:
                        self.voice_count_buffer.pop(user_id)
                    # Hapus juga Redis join key jika ada
                    key = f"voice:join:{guild_id}:{user_id}"
                    await self.bot.redis.delete(key)
                    await ctx.send("⚠️ **Voice count dinonaktifkan**\n-# Yumna tidak lagi memperhatikanmu ~")
                    
        except Exception as e:
            log.error(f"Gagal setting user voice count: {e}")
            await ctx.send(f"Ada kesalahan, coba lagi nanti ...")

async def setup(bot):
    await bot.add_cog(Voicecount(bot))
    
