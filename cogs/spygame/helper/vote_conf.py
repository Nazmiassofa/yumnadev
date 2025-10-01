import discord
from discord.ext import commands
import asyncio

class Vote(commands.Cog):
    def __init__(self, bot, pickme_cog):
        self.bot = bot
        self.pickme_cog = pickme_cog
        self.vote_lock = asyncio.Lock()  # Lock untuk mencegah race condition

    @commands.command(name="vote")
    async def vote(self, ctx, member: discord.Member):
        """Vote a player"""
        async with self.vote_lock:  # Mencegah vote bersamaan
            try:
                guild_id = ctx.guild.id
                game = self.pickme_cog.games.get(guild_id)
                
                # Validasi dasar
                if not game or not game.get("started"):
                    await ctx.send("Tidak ada game yang berjalan.", delete_after=5)
                    return

                if ctx.author.id not in game["players"]:
                    await ctx.send("Kamu bukan pemain.", delete_after=5)
                    return

                if member.id not in game["players"]:
                    await ctx.send("User tersebut tidak ikut bermain!", delete_after=5)
                    return

                # Cek apakah pemain sudah vote
                if ctx.author.id in game["votes"]:
                    await ctx.send(f"{ctx.author.mention} Kamu sudah vote! Tidak bisa mengubah vote.", delete_after=5)
                    return

                # Simpan vote
                game["votes"][ctx.author.id] = member.id
                
                # Kirim embed notifikasi vote
                embed = discord.Embed(
                    description=f"{ctx.author.mention} menuduh {member.mention} sebagai Spy!",
                    color=discord.Color.gold()
                )
                embed.set_footer(text="Voting sedang berlangsung...")
                vote_msg = await ctx.send(embed=embed)
                
                # Hapus pesan notifikasi setelah 5 detik
                await asyncio.sleep(5)
                try:
                    await vote_msg.delete()
                except:
                    pass

                # Update voting summary
                voting_summary_embed = await self.pickme_cog.create_voting_summary(guild_id)
                if not voting_summary_embed:
                    return

                channel = ctx.channel
                
                # Hapus voting summary lama jika ada
                if "voting_summary_id" in game and game["voting_summary_id"]:
                    try:
                        old_message = await channel.fetch_message(game["voting_summary_id"])
                        await old_message.delete()
                    except (discord.NotFound, discord.HTTPException):
                        pass

                # Kirim voting summary baru
                try:
                    new_message = await channel.send(embed=voting_summary_embed)
                    game["voting_summary_id"] = new_message.id
                except discord.HTTPException as e:
                    print(f"Gagal mengirim voting summary: {e}")
                    return

                # Jika semua sudah vote, proses hasil
                if len(game["votes"]) >= len(game["players"]):
                    await self.pickme_cog.check_votes(guild_id, channel)

            except Exception as e:
                print(f"Error dalam proses voting: {e}")
                await ctx.send("Terjadi error saat memproses vote. Coba lagi.", delete_after=5)