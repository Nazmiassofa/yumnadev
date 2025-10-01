import discord
import random
import logging
import asyncio

from core.db import db_connection
from discord.ext import commands

log = logging.getLogger(__name__)

async def get_random_word(self):

    async with db_connection() as conn:
        if not conn:
            return None, None
        try:
            result = await conn.fetchrow("""
                SELECT id, normal_word, pickme_word
                FROM voisa.undercover
                WHERE is_active = TRUE
                ORDER BY random()
                LIMIT 1
            """)

            if result:
                return result['id'], result['normal_word'], result['pickme_word']
            else:
                return None, None
        except Exception as e:
            print(f"Error fetching pickme words: {e}")
            return None, None
        
class JoinGameView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=300)
        self.cog = cog

    @discord.ui.button(label="🚀 Join Game", style=discord.ButtonStyle.blurple, custom_id="join_pickme")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        game = self.cog.games.get(interaction.guild.id)
        if not game or game["started"]:
            await interaction.response.send_message("Game sudah dimulai.", ephemeral=True)
            return

        if interaction.user.id in game["players"]:
            await interaction.response.send_message("Kamu sudah bergabung!", ephemeral=True)
            return

        game["players"].append(interaction.user.id)
        await interaction.response.send_message("Kamu bergabung!", ephemeral=True)
        await self.cog.update_join_embed(interaction.guild.id)

    @discord.ui.button(label="🎯 Start Game!", style=discord.ButtonStyle.danger, custom_id="start_game")
    async def start_game_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        game = self.cog.games.get(interaction.guild.id)
        if not game:
            await interaction.response.send_message("Tidak ada game yang ditemukan.", ephemeral=True)
            return

        if interaction.user.id != game["host"]:
            await interaction.response.send_message("Hanya Host yang dapat memulai game.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        started = await self.cog.start_game(interaction.guild.id)
        if not started:
            await interaction.followup.send("Butuh 3 player untuk mulai!")
            return

        await interaction.followup.send("Game dimulai! periksa DM kalian.")

class PickMeGame(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.games = {}
        
    @commands.command(name="spystop")
    async def stop_game(self, ctx):
        try:
            await ctx.message.delete()
        except discord.Forbidden:
            pass  # Kalau bot tidak punya permission, skip saja
        except discord.HTTPException:
            pass  # Error lain juga dilewati saja

        game = self.games.get(ctx.guild.id)
        
        if not game:
            embed = discord.Embed(
                        title="Game tidak ditemukan!",
                        description="Tidak ada game yang sedang berjalan",
                        color=discord.Color.red()
                    )
            await ctx.send(embed=embed)
            return
        
        if ctx.channel.id != game["channel_id"]:
            embed = discord.Embed(
                        title="Channel Salah",
                        description="Tidak ada game yang berjalan di-channel ini.",
                        color=discord.Color.red()
                    )
            await ctx.send(embed=embed)
            return

        if ctx.author.id != game["host"]:
            embed = discord.Embed(
                        title="Maaf Kamu bukan Host!",
                        description="Game hanya bisa dihentikan oleh Host!",
                        color=discord.Color.red()
                    )
            await ctx.send(embed=embed)
            return

        channel = self.bot.get_channel(game["channel_id"])
        
        if game.get("view_message_id"):
            try:
                view_message = await channel.fetch_message(game["view_message_id"])
                await view_message.delete()
            except discord.NotFound:
                pass
            except Exception as e:
                print(f"Error deleting view (join/start) message: {e}")
                
        if channel:
            if game.get("message_id"):
                try:
                    main_message = await channel.fetch_message(game["message_id"])
                    embed = discord.Embed(
                        title="Game Dihentikan",
                        description="Host menghentikan permainan ini ❌",
                        color=discord.Color.red()
                    )
                    embed.add_field(name="", value="Silahkan ketik `h!spy` untuk memulai game", inline=True)
                    await main_message.edit(embed=embed, view=None)  # 👈 view=None supaya tombol Join hilang
                    main_message = await channel.fetch_message(game["message_id"])
                    await asyncio.sleep(2)
                    await main_message.delete()
                    await ctx.send(embed=embed)

                except discord.NotFound:
                    pass
                except Exception as e:
                    print(f"Error editing main game message: {e}")

            # Hapus voting summary message
            if game.get("voting_summary_id"):
                try:
                    voting_message = await channel.fetch_message(game["voting_summary_id"])
                    await voting_message.delete()
                except discord.NotFound:
                    pass
                except Exception as e:
                    print(f"Error deleting voting summary message: {e}")

        # Akhirnya hapus data game
        self.games.pop(ctx.guild.id, None)

    @commands.command(name="spyreset")
    async def pickme_reset(self, ctx):
        """Reset game manually"""
        self.games.pop(ctx.guild.id, None)
        log.info(f"Game direset dichannel {ctx.guild.id}")
        await ctx.send("Spy game reset!")

    @commands.command(name="spy")
    async def pickme(self, ctx):
        id, normal_word, pickme_word = await get_random_word(self)
        if not normal_word or not pickme_word or not id:
            await ctx.send("Gagal mengambil kata dari database. Coba lagi nanti.")
            return 
                
        if ctx.guild.id in self.games:
            await ctx.send("ada game yang sedang berjalan diserver ini!")
            return

        view = JoinGameView(self)
        header = discord.Embed(color=discord.Color.gold()).set_image(url="https://cdn.discordapp.com/attachments/1372943431034208338/1372943453293379736/5.png?ex=68289cbb&is=68274b3b&hm=4970ff418b307f54a6b90107087e660d4c0d9224934bf7dad2440d9d50075ec5&")

        header2 = discord.Embed(color=discord.Color.blue()).set_image(url="https://cdn.discordapp.com/attachments/1372943431034208338/1372943515482591252/5.png?ex=68289cca&is=68274b4a&hm=838a99e3165b464e8fa2e9dc58bdce1186c88b4747740d343860819c13efc578&")
        
        embed = discord.Embed(
            title="🎮 Spy vs Citizen 🎮",
            description="Ada orang yang dapat kata berbeda diantara kita, temukan dia!\n\n"
                        "**Panduan:**\n"
                        "> 1. Diskusikan siapa yang memiliki kata berbeda diantara kalian\n"
                        "> 2. Berikan clue untuk kata yang kalian dapat diChannel ini\n"
                        "> 3. Vote orang tersebut dengan `v!vote`",
            color=discord.Color.gold()
        )
        embed.set_image  # Ganti dengan URL gambar Anda
        embed.set_footer(text=f"Host {ctx.author.display_name}")
        await ctx.send(embeds=[header])
        msg = await ctx.send(embed=embed)
        view_message = await ctx.send(view=view)  # ⬅️ simpan view message
        # await ctx.send(embeds=[header2])
        # await ctx.send(view=view)

        
        self.games[ctx.guild.id] = {
            "host": ctx.author.id,
            "message_id": msg.id,
            "players": [],
            "started": False,
            "clues": {},
            "votes": {},
            "word_pickme": pickme_word,
            "word_normal": normal_word,
            "pickme_id": None,
            "voting_summary_id": None,
            "view_message_id": view_message.id,  # ⬅️ save ID tombol Join/Start
            "channel_id": ctx.channel.id
        }
        log.info(f"Message ID set: {msg.id}")
        log.info(f"ID:[{id}] {pickme_word} dan {normal_word}") 


    async def update_join_embed(self, guild_id):
        game = self.games.get(guild_id)
        if not game:
            log.info(f"Game tidak ditemukan untuk guild {guild_id}")
            return

        channel = self.bot.get_channel(game["channel_id"])
        if not channel:
            log.info(f"Channel tidak ditemukan untuk guild {guild_id}")
            return

        try:
            # Pastikan message_id valid
            if not game.get("message_id"):
                log.info("Message ID is missing")
                return

            message = await channel.fetch_message(game["message_id"])
            
            # Buat embed baru jika tidak ada
            if not message.embeds:
                embed = discord.Embed(title="Who's The Spy?")
            else:
                embed = message.embeds[0]
                
            # Update players list
            players_list = []
            for player_id in game["players"]:
                member = channel.guild.get_member(player_id)
                players_list.append(f"• {member.display_name if member else f'<@{player_id}>'}")
            
            embed.clear_fields()
            embed.add_field(
                name=f"Pemain ({len(game['players'])}/15)",
                value="\n".join(players_list) if players_list else "Tidak ada pemain",
                inline=False
            )
            
            await message.edit(embed=embed)
            
        except discord.NotFound:
            print("Original message not found, creating new one")
            # Buat message baru jika yang lama hilang
            new_msg = await channel.send(embed=embed)
            game["message_id"] = new_msg.id
        except Exception as e:
            print(f"Error updating join embed: {e}")

    async def start_game(self, guild_id):
        game = self.games.get(guild_id)
        if not game:
            return False

        players = game["players"]

        if len(players) < 3:
            return False

        pickme = random.choice(players)
        game["pickme_id"] = pickme

        channel = self.bot.get_channel(game["channel_id"])
        if not channel:
            return False

        try:
            message = await channel.fetch_message(game["message_id"])
            embed = discord.Embed(
                title="🎮 Game dimulai! 🎮",
                description="Periksa pesan DM untuk melihat kata yang kamu dapat!\n\n"
                            "**Game Rules:**\n"
                            "> 1. Ada 1 pemain yang memiliki kata berbeda\n"
                            "> 2. Cari pemain yang memiliki kata berbeda dengan berdiskusi\n"
                            f"> 3. Gunakan `v!vote @user` untuk menuduh",
                color=discord.Color.green()
            )
            embed.add_field(
                name="Pemain",
                value="\n".join([f"• <@{p}>" for p in players]),
                inline=False
            )
            embed.set_footer(text="Game in progress...")
            await message.edit(embed=embed, view=None)
        except discord.NotFound:
            pass

        # Kirim Voting Summary + Simpan voting_summary_id
        voting_embed = await self.create_voting_summary(guild_id)
        if voting_embed:
            voting_msg = await channel.send(embed=voting_embed)
            game["voting_summary_id"] = voting_msg.id  # <-- PENTING! SAVE ID!

        # Kirim kata ke DM pemain
        for player_id in players:
            try:
                user = await self.bot.fetch_user(player_id)
                word = game["word_pickme"] if player_id == pickme else game["word_normal"]
                
                # role = "**PickMe** 🎯" if player_id == pickme else "**Normal Player** 🎉"
                
                dm_embed = discord.Embed(
                    title="Kata rahasia",
                    description=f"Kamu mendapatkan: **{word}**",
                    color=discord.Color.gold()
                )
                dm_embed.add_field(
                        name="Tips",
                        value="Diskusikan dan beri clue tentang kata yang kamu dapat dichannel tempat kamu bermain!\nCari siapa diantara kalian yang sekiranya adalah Spy",
                        inline=False
                    )
                    
                
                await user.send(embed=dm_embed)
            except discord.Forbidden:
                await channel.send(f"<@{player_id}> Tidak bisa kirim DM. Aktifkan DM server!")

        game["started"] = True
        return True

    async def check_votes(self, guild_id, channel):
        game = self.games.get(guild_id)
        if not game:
            return

        votes = game["votes"]
        pickme_id = game["pickme_id"]

        vote_count = {}
        for voted in votes.values():
            vote_count[voted] = vote_count.get(voted, 0) + 1

        if not vote_count:
            embed = discord.Embed(
                title="Game Ended",
                description="Tidak ada yang melakukan Vote. Game Berakhir.",
                color=discord.Color.light_grey()
            )
            await channel.send(embed=embed)
            self.games.pop(guild_id, None)
            return

        # Cari siapa yang paling banyak di-vote
        most_voted = max(vote_count, key=vote_count.get)

        # Kalau Spy yang di-vote, Citizen menang
        if most_voted == pickme_id:
            embed = discord.Embed(
                title="Citizen Menang! 🎉",
                description="Spy telah ditemukan dan dieliminasi!",
                color=discord.Color.green()
            )
            pickme_member = channel.guild.get_member(pickme_id)
            embed.add_field(
                name="Spy",
                value=pickme_member.mention if pickme_member else f"<@{pickme_id}>",
                inline=False
            )
            embed.add_field(
                name="-------------------------------------",
                value=f"Spy: **{game['word_pickme']}**\nCitizen: **{game['word_normal']}**",
                inline=False
            )
            await channel.send(embed=embed)
            self.games.pop(guild_id, None)
            return

        # Kalau bukan Spy yang di-vote, eliminasi pemain
        if most_voted in game["players"]:
            game["players"].remove(most_voted)

            eliminated_member = channel.guild.get_member(most_voted)
            eliminated_name = eliminated_member.display_name if eliminated_member else f"<@{most_voted}>"

            embed = discord.Embed(
                description=f"{eliminated_name} telah dieliminasi! ❌",
                color=discord.Color.red()
            )
            await channel.send(embed=embed)

        # 🔥 Setelah eliminasi, CEK JUMLAH PEMAIN
        if len(game["players"]) <= 2:
            if pickme_id in game["players"]:
                result = "Spy Menang! 🎯"
                color = discord.Color.gold()
            else:
                result = "Citizen Menang! 🎉"
                color = discord.Color.green()

            embed = discord.Embed(
                title="**Game Berakhir!**",
                description=result,
                color=color
            )
            pickme_member = channel.guild.get_member(pickme_id)
            embed.add_field(
                name="Spy",
                value=pickme_member.mention if pickme_member else f"<@{pickme_id}>",
                inline=False
            )
            embed.add_field(
                name="-------------------------------------",
                value=f"Spy: **{game['word_pickme']}**\nCitizen: **{game['word_normal']}**",
                inline=False
            )
            await channel.send(embed=embed)
            self.games.pop(guild_id, None)
            return

        # Kalau belum end game, baru reset dan lanjut ke ronde baru
        game["votes"] = {}

        await self.update_join_embed(guild_id)

        embed = discord.Embed(
            title="Ronde Berikutnya",
            description="Silahkan diskusi dan vote lagi dengan `v!vote @user`!",
            color=discord.Color.blurple()
        )
        await channel.send(embed=embed)


    
    async def create_voting_summary(self, guild_id):
        game = self.games.get(guild_id)
        if not game:
            return None
        
        channel = self.bot.get_channel(game["channel_id"])
        if not channel:
            return None
        
        vote_count = {}
        for voted_id in game["votes"].values():
            vote_count[voted_id] = vote_count.get(voted_id, 0) + 1
        
        voting_results = []
        for player_id in game["players"]:
            member = channel.guild.get_member(player_id)
            count = vote_count.get(player_id, 0)
            voting_results.append(f"{member.display_name if member else f'<@{player_id}>'}: {count} ")
        
        embed = discord.Embed(
            title="📊 User yang diduga Spy",
            description="\n".join(voting_results),
            color=discord.Color.blurple()
        )
        
        if game["pickme_id"]:
            embed.set_footer(text="Spy ada di antara kalian!")
        
        return embed

    
# async def setup(bot):
#     pass