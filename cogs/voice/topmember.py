import discord, asyncio, logging, random

from typing import Optional

from discord.ext import commands, tasks

from utils.time import get_current_date_uptime
from utils.views.embed import cooldown_embed
from .helper.pil import create_daily_stats_card

from .voicecount import get_cache_count
from core.db import db_connection
from .database.dbcounter import VoiceSummaryQuery as db
from .database.redis import TopMemberCoolDown as cd

from utils.data.emot import (LEFTSWIPE,
                             RIGHTSWIPE, 
                             WHITELINE,
                             YELLOWCROWN
                            )

log = logging.getLogger(__name__)

DATA_PER_PAGE = 5

async def animate_thinking(message, stop_event: asyncio.Event):
    dots = 0
    while not stop_event.is_set():
        dots = (dots + 1) % 4
        await message.edit(content=f"_Processing_{'...'[:dots]}")
        await asyncio.sleep(0.5)

def _format_time_seconds(seconds):
    return f"{seconds:,}".replace(",", ".") + " detik"

def _format_time_minutes(seconds):
    minutes = seconds // 60
    return f"{minutes:,}".replace(",", ".") + " menit"

def _format_time(seconds):
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours} Jam {minutes} Menit"

class TopMember(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.database_refresh.start()  # Mulai saat Cog di-load
        
    def cog_unload(self):
        self.database_refresh.cancel()
        
    @tasks.loop(hours=3)
    async def database_refresh(self):
        try:
            async with db_connection() as conn:
                # await conn.execute("SELECT * FROM voisa.voice_counts limit 1;")
                await conn.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY voisa.topglobal;")
                await asyncio.sleep(30)
                await conn.execute("REFRESH MATERIALIZED VIEW voisa.voice_leaderboard")
                log.info("[ VoiceStats ] REFRESH topglobal & leaderboard berhasil.")
        except Exception as e:
            logging.exception(f"[ VoiceStats ] Gagal refresh materialized view: {e}")

    @database_refresh.before_loop
    async def before_refresh(self):
        await self.bot.wait_until_ready()

    async def paginate_dailyrank(self, ctx, base_query, params, formatter):
        async with db_connection() as conn:
            if not conn:
                log.error("[ COGS ERROR ] ---- Gagal terhubung kedatabase -- [ DailyRankCommand ]")
                return

            start = 0
            message = None  # Inisialisasi message di luar loop

            while True:
                results = await conn.fetch(base_query, *(params + [DATA_PER_PAGE, start]))

                if not results:
                    if start == 0:
                        await ctx.send("Tidak ada data yang ditemukan untuk guild ini")
                    else:
                        await ctx.send("Tidak ada data untuk halaman selanjutnya")
                    break

                embed = discord.Embed(color=discord.Color.blue())
                embed.description = f"{WHITELINE}"
                embed.set_thumbnail(url=ctx.guild.icon.url if ctx.guild.icon else None)
                embed.set_footer(text=f"{ctx.guild.name}")
                embed.set_author(name=f"|  {(start // DATA_PER_PAGE) + 1}  |  Top Daily Rank")

                for idx, row in enumerate(results, start=start + 1):
                    formatter(embed, idx, row)

                if not message:
                    message = await ctx.send(embed=embed)
                    await message.add_reaction(LEFTSWIPE)
                    await message.add_reaction(RIGHTSWIPE)
                else:
                    await message.edit(embed=embed)

                def check(reaction, user):
                    return (
                        reaction.message.id == message.id
                        and user == ctx.author
                        and str(reaction.emoji) in [LEFTSWIPE, RIGHTSWIPE]
                    )

                try:
                    reaction, user = await self.bot.wait_for('reaction_add', timeout=60.0, check=check)
                except asyncio.TimeoutError:
                    try:
                        await message.clear_reactions()
                    except:
                        pass
                    break

                try:
                    await message.remove_reaction(reaction.emoji, user)
                except:
                    pass

                if str(reaction.emoji) == RIGHTSWIPE:
                    start += DATA_PER_PAGE
                elif str(reaction.emoji) == LEFTSWIPE:
                    start = max(0, start - DATA_PER_PAGE)
                    
    @commands.hybrid_command(name="topglobal", description="Menampilkan top global members")
    async def top_guild(self, ctx: commands.Context):
        guild_id = ctx.guild.id
        user_id = ctx.author.id
        guild_name = ctx.guild.name
        user_name = ctx.author.display_name
        
        
        if not await get_cache_count(self, user_id, guild_id):
            embed = discord.Embed(
                title="🔔 Aktifkan Voice Counter",
                description=f"{user_name} tidak mengaktifkan voice counter\nYumna tidak bisa menampilkan topglobal",
                color=discord.Color.orange(),
                timestamp=discord.utils.utcnow()
            )
            embed.set_footer(text="v!voicecount on/off")
            embed.set_thumbnail(url=ctx.author.avatar.url if ctx.author.avatar else "")
            await ctx.send(embed=embed)
            log.info(f"[ IGNORE TOPGLOBAL COMMAND ]: {ctx.guild.name} [{ctx.author.name}]")
            return
        
        log.info (f"[ COMMAND CALL ] ---- Command [ topglobal ] dipanggil : {guild_name} | {user_name}")


        cooldown_time = await cd.top_global_cooldown(self, guild_id, user_id, cooldown_seconds=30)
                
        if cooldown_time > 0:
            embed = await cooldown_embed(cooldown_time)
            await ctx.send(embed=embed)
            return
        await self.top_guild_member(ctx)
        
    async def top_guild_member(self, ctx, start_index=0):
        query = (
            "SELECT username, total_time, join_count AS join_count "  # join_count diset dummy 0 karena tidak tersedia di view
            "FROM voisa.topglobal "
            "WHERE guild_id = $1 "
            "ORDER BY total_time DESC "
            "LIMIT $2 OFFSET $3;"
        )

        # time_formatter = random.choice([_format_time, _format_time_minutes, _format_time_seconds])

        def formatter(embed, idx, row):
            username, total_sec, joins = row
            time_str = _format_time(int(total_sec))
            atrib = YELLOWCROWN if idx == 1 else ""
            embed.add_field(
                name=f"**{idx}. {username}** {atrib}",
                value=f"> Voice Time: **{time_str}**\n"
                    f"> Voice Join: **{joins}**\n",  # tetap ditampilkan meski dummy
                inline=False
            )

        await self.paginate_topguild(ctx, query, [ctx.guild.id], formatter)
        
    async def paginate_topguild(self, ctx, query, params, formatter):
        async with db_connection() as conn:
            if not conn:
                await ctx.send("Maaf ada kesalahan, coba lagi nanti")
                return

            start = 0
            message = None  # Inisialisasi message di luar loop

            while True:
                results = await conn.fetch(query, *(params + [DATA_PER_PAGE, start]))

                if not results:
                    if start == 0:
                        await ctx.send("Tidak ada data yang ditemukan.")
                    else:
                        await ctx.send("Anda telah mencapai akhir daftar.")
                    break

                embed = discord.Embed(color=discord.Color.blue())
                embed.description = f"{WHITELINE}"
                embed.set_thumbnail(url=ctx.guild.icon.url if ctx.guild.icon else None)
                embed.set_footer(text=f"{ctx.guild.name} | Delay 2-3 hours ")
                embed.set_author(name=f"|  {(start // DATA_PER_PAGE) + 1}  |  Top Guild Rank")


                for idx, row in enumerate(results, start=start + 1):
                    formatter(embed, idx, row)

                if not message:
                    message = await ctx.send(embed=embed)
                    await message.add_reaction(LEFTSWIPE)
                    await message.add_reaction(RIGHTSWIPE)
                else:
                    await message.edit(embed=embed)

                def check(reaction, user):
                    return (
                        reaction.message.id == message.id
                        and user == ctx.author
                        and str(reaction.emoji) in [LEFTSWIPE, RIGHTSWIPE]
                    )

                try:
                    reaction, user = await self.bot.wait_for('reaction_add', timeout=60.0, check=check)
                except asyncio.TimeoutError:
                    try:
                        await message.clear_reactions()
                    except:
                        pass
                    break

                try:
                    await message.remove_reaction(reaction.emoji, user)
                except:
                    pass

                if str(reaction.emoji) == RIGHTSWIPE:
                    start += DATA_PER_PAGE
                elif str(reaction.emoji) == LEFTSWIPE:
                    start = max(0, start - DATA_PER_PAGE)


    async def daily_rank_guild(self, ctx, start_index=0):
        today = get_current_date_uptime()
        query = (
            "SELECT username, total_time FROM voisa.voice_counts "
            "WHERE count_date = $1 AND guild_id = $2 "
            "ORDER BY total_time DESC LIMIT $3 OFFSET $4;"
        )

        time_formatter = random.choice([_format_time, _format_time_minutes, _format_time_seconds])

        def formatter(embed, idx, row):
            username, total_sec = row
            time_str = time_formatter(int(total_sec))
            atrib = YELLOWCROWN if idx == 1 else ""
            embed.add_field(
                name=f"{idx}. **{username}** {atrib}",
                value=f"> Voice Time: **{time_str}**",
                inline=False
            )
        await self.paginate_dailyrank(ctx, query, [today, ctx.guild.id], formatter)

    @commands.hybrid_command(name="dailyrank", description="Menampilkan daily rank")
    async def dailyrank(self, ctx: commands.Context):
        guild_id = ctx.guild.id
        user_id = ctx.author.id
        guild_name = ctx.guild.name
        user_name = ctx.author.display_name
        
        if not await get_cache_count(self, user_id, guild_id):
            embed = discord.Embed(
                title="🔔 Aktifkan Voice Counter",
                description=f"{user_name} tidak mengaktifkan voice counter\nYumna tidak bisa menampilkan dailyrank",
                color=discord.Color.orange(),
                timestamp=discord.utils.utcnow()
            )
            embed.set_footer(text="v!voicecount on/off")
            embed.set_thumbnail(url=ctx.author.avatar.url if ctx.author.avatar else "")
            await ctx.send(embed=embed)
            log.info(f"[ IGNORE DAILYRANK COMMAND ]: {ctx.guild.name} [{ctx.author.name}]")
            return

        log.info (f"[ COMMAND CALL ] ---- Command [ dailyrank ] dipanggil : {guild_name} | {user_name}")
        

        cooldown_time = await cd.dailyrank_cooldown(self, guild_id, user_id, cooldown_seconds=30)
                
        if cooldown_time > 0:
            embed = await cooldown_embed(cooldown_time)
            await ctx.send(embed=embed)
            return
        await self.daily_rank_guild(ctx)
        
    @commands.hybrid_command(name="dailyinfo", description="Tampilkan statistik daily kamu")
    async def daily_info_image(self, ctx: commands.Context, member: discord.Member = None):
        if member is None:
            member = ctx.author

        user_id = member.id
        guild_id = member.guild.id
        guild_name = ctx.guild.name
        user_name = ctx.author.display_name

        if not await get_cache_count(self, user_id, guild_id):
            embed = discord.Embed(
                title="🔔 Aktifkan Voice Counter",
                description=f"{user_name} tidak mengaktifkan voice counter\nYumna tidak bisa menampilkan dailyinfo",
                color=discord.Color.orange(),
                timestamp=discord.utils.utcnow()
            )
            embed.set_footer(text="v!voicecount on/off")
            embed.set_thumbnail(url=member.avatar.url if member.avatar else "")
            await ctx.send(embed=embed)
            log.info(f"[ IGNORE DAILYINFO COMMAND ]: {ctx.guild.name} [{ctx.author.name}]")
            return
        
        log.info (f"[ COMMAND CALL ] ---- Command [ dailyinfo ] dipanggil : {guild_name} | {user_name}")

        cooldown_time = await cd.dailyinfo_cooldown(self, guild_id, user_id, cooldown_seconds=30)
                
        if cooldown_time > 0:
            embed = await cooldown_embed(cooldown_time)
            await ctx.send(embed=embed)
            return

        thinking_message = await ctx.reply("_Processing_")

        try:
            today = get_current_date_uptime()
            result = await db.get_mydaily(user_id,
                                          guild_id,
                                          today)
            if result:
                total_time = result["total_time"]
                avatar_url = member.display_avatar.url if member.display_avatar else ctx.bot.user.display_avatar.url

                image = create_daily_stats_card(member.name, avatar_url, total_time)
                file = discord.File(fp=image, filename="daily_stats.png")

                await thinking_message.edit(content=None, attachments=[file])
            else:
                await thinking_message.edit(content=f"Tidak ada data\n-# {member.mention}, belum memiliki statistik.")

        except Exception as e:
            await thinking_message.edit(content="Terjadi kesalahan dalam mengambil data dari database.")
            log.error(f"❌ Database error (dailyinfo2): {e}")
            
    def censor_id(self, guild_id):
        id_str = str(guild_id)
        if len(id_str) <= 5:
            return "*****"
        return f"{id_str[:-5]}*****"

    @commands.command(name="leaderboard")
    async def voice_leaderboard(self, ctx):
        guild_name = ctx.guild.name
        user_name = ctx.author.display_name

        log.info (f"[ COMMAND CALL ] ---- Command [ leaderboard ] dipanggil : {guild_name} | {user_name}")

        top_guilds = await db.get_top_guilds()
        if not top_guilds:
            await ctx.send("Tidak ada data leaderboard yang tersedia.")
            return

        embed = discord.Embed(color=discord.Color.blue())
        embed.description = f"{WHITELINE}"
        embed.set_thumbnail(url=ctx.guild.icon.url if ctx.guild.icon else None)
        embed.set_footer(text=f"{ctx.guild.name}")
        embed.set_author(name=f"Voice Leaderboard")

        for idx, guild_data in enumerate(top_guilds[:5], start=1):  # Ambil top 5
            guild_obj = self.bot.get_guild(guild_data['guild_id'])
            if guild_obj:
                guild_name = guild_obj.name
            else:
                guild_name = f"Guild ID: {self.censor_id(guild_data['guild_id'])}"

            time_str = _format_time(int(guild_data['total_voice']))
            atrib = YELLOWCROWN if idx == 1 else ""

            embed.add_field(
                name=f"**{idx}. {guild_name}** {atrib}",
                value=(
                    f"> **Username:** {guild_data['username']}\n"
                    f"> **Voice Time:** {time_str}\n"
                    f"> **Total Joins:** {guild_data['total_joins']}"
                ),
                inline=False
            )

        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(TopMember(bot))
