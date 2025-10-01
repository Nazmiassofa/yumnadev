import discord, asyncio, logging

from discord.ext import commands

from utils.views.embed import cooldown_embed
from core.db import db_connection
from utils.data.emot import (LEFTSWIPE,
                             RIGHTSWIPE, 
                             WHITELINE,
                             YELLOWCROWN
                            )

log = logging.getLogger(__name__)

DATA_PER_PAGE = 5

class SambungKataRank(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def censor_id(self, guild_id):
        id_str = str(guild_id)
        if len(id_str) <= 5:
            return "*****"
        return f"{id_str[:-5]}*****"

    async def _resolve_username(self, user_id: int) -> str:
        """
        Usahakan mengambil username cached dulu, bila tidak ada fetch dari API.
        Jika gagal, tampilkan user id yang disensor (supaya tidak bocor).
        """
        try:
            user = self.bot.get_user(user_id)
            if user:
                return f"{user.name}#{user.discriminator}"
            # fetch_user bisa raise; kita tangani
            user = await self.bot.fetch_user(user_id)
            return f"{user.name}#{user.discriminator}"
        except Exception:
            # fallback ke id yang disensor (atau plain id jika mau)
            return f"User ID: {str(user_id)}"

    async def paginate_sambung(self, ctx, base_query, params, formatter):
        """
        Pagination rebroadcast mirip function paginate_topguild di contoh.
        """
        async with db.getter_word() as conn:
            if not conn:
                await ctx.send("Maaf ada kesalahan, coba lagi nanti")
                return

            start = 0
            message = None  # Inisialisasi message di luar loop

            while True:
                results = await conn.fetch(base_query, *(params + [DATA_PER_PAGE, start]))

                if not results:
                    if start == 0:
                        await ctx.send("Tidak ada data yang ditemukan.")
                    else:
                        await ctx.send("Anda telah mencapai akhir daftar.")
                    break

                embed = discord.Embed(color=discord.Color.blue())
                embed.description = f"{WHITELINE}"
                embed.set_thumbnail(url=ctx.guild.icon.url if ctx.guild.icon else None)
                embed.set_footer(text=f"{ctx.guild.name} | YumnaBot ")
                embed.set_author(name=f"|  {(start // DATA_PER_PAGE) + 1}  |  Top Sambung Kata")

                # Formatter bertanggung jawab menambahkan field per baris
                for idx, row in enumerate(results, start=start + 1):
                    await formatter(embed, idx, row)

                if not message:
                    message = await ctx.send(embed=embed)
                    try:
                        await message.add_reaction(LEFTSWIPE)
                        await message.add_reaction(RIGHTSWIPE)
                    except Exception:
                        # jika gagal menambahkan reaction (permissions), tetap lanjut
                        pass
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
                    except Exception:
                        pass
                    break

                try:
                    await message.remove_reaction(reaction.emoji, user)
                except Exception:
                    pass

                if str(reaction.emoji) == RIGHTSWIPE:
                    start += DATA_PER_PAGE
                elif str(reaction.emoji) == LEFTSWIPE:
                    start = max(0, start - DATA_PER_PAGE)


    @commands.hybrid_command(name="skrank", description="Menampilkan top global pemain Sambung Kata")
    async def topsambungkata(self, ctx: commands.Context):
        """
        Command utama: cek apakah user mengaktifkan voice counter (sama flow dengan contoh),
        lalu cek cooldown, dan panggil paginate yang mengambil data dari voisa.sambungkata
        """
        guild_id = ctx.guild.id
        user_id = ctx.author.id
        guild_name = ctx.guild.name
        user_name = ctx.author.display_name

        # Query: ambil user_id, total_points, total_wins, games_played -> urut berdasarkan total_wins desc
        query = (
            "SELECT user_id, total_points, total_wins, games_played "
            "FROM voisa.sambungkata "
            "WHERE guild_id = $1 "
            "ORDER BY total_wins DESC "
            "LIMIT $2 OFFSET $3;"
        )
                
        async def formatter(embed, idx, row):
            user_id_db, total_points, total_wins, games_played = row
            member = ctx.guild.get_member(int(user_id_db))
            username = member.display_name if member else f"User ID: {user_id_db}"
            atrib = YELLOWCROWN if idx == 1 else ""
            embed.add_field(
                name=f"**{idx}. {username}** {atrib}",
                value=(
                    f"> Wins: **{int(total_wins)}**\n"
                    f"> Points: **{int(total_points)}**\n"
                    f"> Games: **{int(games_played)}**\n"
                ),
                inline=False
            )


        await self.paginate_sambung(ctx, query, [ctx.guild.id], formatter)


async def setup(bot):
    await bot.add_cog(SambungKataRank(bot))
