import discord
import asyncio
import random
from discord.ext import commands

with open("utils/data/kosakata.txt", "r", encoding="utf-8") as file:
    kosakata = [kata.strip() for kata in file.readlines()]

def pilih_kata_acak():
    return random.choice(kosakata)

class RangkaiKataGame(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.games = {}  # Menyimpan state game per channel
    
    class JoinView(discord.ui.View):
        def __init__(self, ctx, game):
            super().__init__(timeout=30)
            self.ctx = ctx
            self.game = game
            self.task = None

        @discord.ui.button(label="Join", style=discord.ButtonStyle.gray, emoji="➕", row=0)
        async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
            if interaction.user not in self.game['players']:
                self.game['players'].append(interaction.user)
                await interaction.response.defer()
                
                embed = interaction.message.embeds[0]
                embed.set_field_at(
                    0,
                    name="Pemain:",
                    value="\n".join([p.mention for p in self.game['players']]) or "-"
                )
                await interaction.message.edit(embed=embed)
                await interaction.followup.send(f"{interaction.user.mention} joined!", ephemeral=True)
            else:
                await interaction.response.send_message("⚠️ Already joined!", ephemeral=True)

        @discord.ui.button(label="Start", style=discord.ButtonStyle.green, emoji="▶️", row=0)
        async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
            if len(self.game['players']) < 2:
                await interaction.response.send_message("⚠️ butuh 2+ player!", ephemeral=True)
                return
                
            await interaction.response.defer()
            self.stop()
            if self.task:
                self.task.cancel()
            await self.game['message'].edit(embed=discord.Embed(
                title="Rangkai Kata 🎲",
                description="✅ **Game started!**",
                color=discord.Color.green()
            ), view=None)
            await self.ctx.cog.start_turn(self.ctx.channel)

        async def on_timeout(self):
            if self.task:
                self.task.cancel()
            
            if len(self.game['players']) >= 2:
                await self.game['message'].edit(embed=discord.Embed(
                    title="Rangkai Kata 🎲",
                    description=f"⏱️ **Game dimulai otomatis dengan {len(self.game['players'])} pemain!**",
                    color=discord.Color.green()
                ), view=None)
                await self.ctx.cog.start_turn(self.ctx.channel)
            else:
                await self.game['message'].edit(embed=discord.Embed(
                    title="Rangkai Kata 🎲",
                    description="❌ **Tidak cukup pemain. Fase join dibatalkan.**",
                    color=discord.Color.red()
                ), view=None)
                if self.ctx.channel.id in self.ctx.cog.games:
                    del self.ctx.cog.games[self.ctx.channel.id]

    @commands.command(name="satukata")
    async def start_game(self, ctx):
        if ctx.channel.id in self.games:
            await ctx.send("⚠️ Game sedang berlangsung di channel ini!")
            return
        
        game = {
            "players": [], 
            "turn": 0, 
            "kalimat": [pilih_kata_acak()],
            "turn_message": None, 
            "active": True,
            "blocks": 1,
            "current_task": None
        }
        self.games[ctx.channel.id] = game
        
        embed = discord.Embed(
            title="Rangkai Kata 🎲",
            description="Tekan tombol untuk bergabung!\n",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="Pemain yang Bergabung:",
            value="- Belum ada pemain.",
            inline=False
        )
        view = self.JoinView(ctx, game)
        game['message'] = await ctx.send(embed=embed, view=view)
        
    async def start_turn(self, channel):
        game = self.games[channel.id]
        
        while game["active"]:
            player = game['players'][game['turn']]
            
            if game.get("turn_message"):
                try:
                    await game["turn_message"].delete()
                except:
                    pass
            
            formatted_kalimat = ""
            for block in game['kalimat']:
                formatted_kalimat += f"```\n{block}\n```\n"
            
            embed = discord.Embed(
                title="🎲 Giliran Bermain",
                description=f"{player.mention}, tambahkan satu kata:",
                color=discord.Color.green()
            )
            embed.add_field(
                name="Coba rangkai sebuah cerita:",
                value=formatted_kalimat.strip(),
                inline=False
            )
            embed.set_footer(text="Ketik 'enter' untuk blok baru, 'pass' untuk lewati giliran")
            
            game["turn_message"] = await channel.send(embed=embed)

            def check(msg):
                if msg.channel != channel or not game["active"]:
                    return False
                
                content = msg.content.strip().lower()
                if content == 'v!stopsk':
                    return True
                
                if msg.author not in game['players']:
                    return False
                if msg.author != player:
                    asyncio.create_task(msg.delete())
                    asyncio.create_task(channel.send(
                        f"⚠️ {msg.author.mention}, bukan giliranmu!", 
                        delete_after=3
                    ))
                    return False
                                
                if content in ['pass', 'enter']:
                    return True
                
                if " " in content or not content.isalpha():
                    asyncio.create_task(msg.delete())
                    asyncio.create_task(channel.send(
                        f"⚠️ {player.mention}, hanya boleh satu kata dan harus berupa huruf!", 
                        delete_after=3
                    ))
                    return False
                return True

            try:
                if game.get("current_task"):
                    game["current_task"].cancel()
                
                game["current_task"] = self.bot.loop.create_task(
                    self.bot.wait_for("message", check=check, timeout=30)
                )
                msg = await game["current_task"]
                
                content = msg.content.strip().lower()
                
                if content == 'pass':
                    await channel.send(f"⏩ {player.mention} memilih untuk pass!")
                    game['turn'] = (game['turn'] + 1) % len(game['players'])
                    continue
                elif content == 'enter':
                    game['kalimat'].append("")
                    game['blocks'] += 1
                    await channel.send(f"📝 {player.mention} membuat blok baru!")
                    game['turn'] = (game['turn'] + 1) % len(game['players'])
                    continue
                elif content == 'v!stopsk':
                    continue
                
                if game['kalimat'][-1]:
                    game['kalimat'][-1] += " " + msg.content.strip()
                else:
                    game['kalimat'][-1] = msg.content.strip()
                
                game['turn'] = (game['turn'] + 1) % len(game['players'])
                
            except asyncio.TimeoutError:
                timeout_player = game['players'].pop(game['turn'])
                await channel.send(f"⏳ {timeout_player.mention} dihapus karena timeout!")
                
                if len(game['players']) < 2:
                    await channel.send("⚠️ Pemain kurang dari 2, game dihentikan!")
                    game["active"] = False
                    if channel.id in self.games:
                        del self.games[channel.id]
                    return
                
                game['turn'] = game['turn'] % len(game['players'])
            except asyncio.CancelledError:
                return

    @commands.command(name="stopsk")
    async def stop_game(self, ctx):
        if ctx.channel.id not in self.games:
            await ctx.send("⚠️ Tidak ada game yang sedang berlangsung di channel ini!")
            return
        
        game = self.games[ctx.channel.id]
        
        # Validasi: Hanya pemain pertama yang bisa stop game
        if len(game['players']) > 0 and ctx.author != game['players'][0]:
            await ctx.send(f"⚠️ Hanya {game['players'][0].mention} sebagai owner game yang bisa menghentikan game ini!", delete_after=5)
            return
        
        game["active"] = False
        
        if game.get("current_task"):
            game["current_task"].cancel()
        
        final_kalimat = ""
        total_kata = 0
        for block in game['kalimat']:
            final_kalimat += f"```\n{block}\n```\n"
            total_kata += len(block.split())
        
        embed = discord.Embed(
            title="🛑 Game Dihentikan",
            description=f"**{total_kata} kata** berhasil dirangkai dalam {game['blocks']} blok!",
            color=discord.Color.orange()
        )
        embed.add_field(
            name="Hasil Akhir:",
            value=final_kalimat.strip(),
            inline=False
        )
        
        await ctx.send(embed=embed)
        if ctx.channel.id in self.games:
            del self.games[ctx.channel.id]

async def setup(bot):
    await bot.add_cog(RangkaiKataGame(bot))