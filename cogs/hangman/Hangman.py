import asyncio
import logging
import random
import discord
import time

from collections import defaultdict

from core.db import db_connection

from discord.ext import commands
from discord import Embed, ui, ButtonStyle, Interaction
from .database.db import DataBaseManager as db
from utils.data.emot import (JOIN,
                             START,
                             WINNER,
                             PRIZE,
                             WRONG,
                             CORRECT,
                             SKULL,
                             SKULLHEART,
                             PLANNER,
                             TIMEOUT,
                             REDHEART,
                             POINT,
                             CHAT,
                             DICE,
                             PROGRESS,
                             WARNING,
                             LEFTSWIPE,
                             RIGHTSWIPE,
                             WHITELINE,
                             YELLOWCROWN)


logger = logging.getLogger(__name__)

class GameModeView(ui.View):
    def __init__(self, cog, ctx):
        super().__init__(timeout=30)
        self.cog = cog
        self.ctx = ctx
        self.selected_mode = None

    @ui.button(label="Normal", style=ButtonStyle.primary, custom_id="normal_mode", emoji="🎯")
    async def normal_mode_button(self, interaction: Interaction, button: ui.Button):
        if interaction.user != self.ctx.author:
            return await interaction.response.send_message(f"{WARNING} Hanya yang memulai game yang dapat memilih mode.", ephemeral=True)
        
        self.selected_mode = "normal"
        self.stop()
        await interaction.response.edit_message(view=None)

    @ui.button(label="Last Heart", style=ButtonStyle.secondary, custom_id="last_heart_mode", emoji="💔")
    async def last_heart_mode_button(self, interaction: Interaction, button: ui.Button):
        if interaction.user != self.ctx.author:
            return await interaction.response.send_message(f"{WARNING} Hanya yang memulai game yang dapat memilih mode.", ephemeral=True)
        
        self.selected_mode = "last_heart"
        self.stop()
        await interaction.response.edit_message(view=None)

class JoinView(ui.View):
    def __init__(self, cog, ctx, game_mode):
        super().__init__(timeout=60)
        self.cog = cog
        self.ctx = ctx
        self.game_mode = game_mode
        self.message = None
        self.lock = asyncio.Lock()  # Add lock for concurrent access


    @ui.button(label="Join", style=ButtonStyle.secondary, custom_id="hangman_join", emoji=f"{JOIN}")
    async def join_button(self, interaction: Interaction, button: ui.Button):
        async with self.lock:
            game = self.cog.games.get(self.ctx.channel.id)
            user = interaction.user
            
            if not game or game['phase'] != 'join':
                return await interaction.response.send_message("❗ Tidak ada fase join aktif.", ephemeral=True)

            if user.id in game['players']:
                return await interaction.response.send_message(f"{WARNING} Kamu sudah bergabung dalam game ini.", ephemeral=True)
            
            if len(game['players']) >= 5:
                return await interaction.response.send_message("❗ Slot pemain sudah penuh (maksimal 5 pemain).", ephemeral=True)

            game['players'][user.id] = {'member': user, 'health': 5, 'points': 0, 'correct_guesses': 0, 'wrong_guesses': 0}
            
            # Update embed
            embed = self.message.embeds[0]
            names = [p['member'].display_name for p in game['players'].values()]
            embed.description = (
                f"{SKULL} **Pemain yang bergabung:**\n"
                + "\n".join(f"`{i+1}.` {n}" for i, n in enumerate(names))
                + f"\n\n{PLANNER} **Pemain**: {len(names)}/5"
            )
            embed.color = 0x3498db if len(names) < 5 else 0x2ecc71
            await interaction.response.edit_message(embed=embed, view=self)

    @ui.button(label="Start Game", style=ButtonStyle.success, custom_id="hangman_start", emoji=f"{START}")
    async def start_button(self, interaction: Interaction, button: ui.Button):
        async with self.lock:
            game = self.cog.games.get(self.ctx.channel.id)
            if not game or game['phase'] != 'join':
                return await interaction.response.send_message("❗ Tidak ada fase join aktif.", ephemeral=True)
            
            if interaction.user != game['host']:
                return await interaction.response.send_message(f"{WARNING} Hanya host yang dapat memulai game.", ephemeral=True)
            
            if len(game['players']) < 1:
                return await interaction.response.send_message(f"{WARNING} Minimal 1 pemain untuk memulai game.", ephemeral=True)

            game['phase'] = 'starting'
            self.stop()
            
            # Show starting message with countdown
            embed = Embed(
                title=f"{START} Game Dimulai!",
                description="Mempersiapkan game hangman...",
                color=0xf39c12
            )
            await interaction.response.edit_message(embed=embed, view=None)
            
            # Small delay for better UX
            await asyncio.sleep(1)
            await self.cog._begin_game(self.ctx, game)

    @ui.button(label="Cancel", style=ButtonStyle.danger, custom_id="hangman_cancel", emoji="❌")
    async def cancel_button(self, interaction: Interaction, button: ui.Button):
        async with self.lock:
            game = self.cog.games.get(self.ctx.channel.id)
            if not game or game['phase'] != 'join':
                return await interaction.response.send_message("❗ Game sudah tidak aktif.", ephemeral=True)
            
            if interaction.user != game['host']:
                return await interaction.response.send_message(f"{WARNING} Hanya host yang dapat membatalkan game.", ephemeral=True)
            
            del self.cog.games[self.ctx.channel.id]
            self.stop()
            
            embed = Embed(
                title="❌ Game Dibatalkan",
                description="Game hangman telah dibatalkan oleh host.",
                color=0xe74c3c
            )
            await interaction.response.edit_message(embed=embed, view=None)

class HangmanCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.games: dict[int, dict] = {}
        self.locks = defaultdict(asyncio.Lock)  # Add lock for game state access
        self.timeout_tasks = {}  # Track timeout tasks for each game
        
    def _cancel_timeout_task(self, channel_id):
        """Cancel existing timeout task for a channel"""
        if channel_id in self.timeout_tasks:
            task = self.timeout_tasks[channel_id]
            if not task.done():
                task.cancel()
            del self.timeout_tasks[channel_id]
    
    def _start_game_timeout(self, channel_id, timeout_seconds=180):
        """Start or restart the game timeout (default 3 minutes)"""
        # Cancel any existing timeout
        self._cancel_timeout_task(channel_id)
        
        # Start new timeout task
        self.timeout_tasks[channel_id] = asyncio.create_task(
            self._handle_game_timeout(channel_id, timeout_seconds)
        )
    
    async def _handle_game_timeout(self, channel_id, timeout_seconds):
        """Handle game timeout after specified seconds of inactivity"""
        try:
            await asyncio.sleep(timeout_seconds)
            
            # Check if game still exists and is in play phase
            async with self.locks[channel_id]:
                game = self.games.get(channel_id)
                if not game or game['phase'] != 'play':
                    return
                
                # Get channel object
                channel = self.bot.get_channel(channel_id)
                if not channel:
                    return
                
                # Kill all players and end game
                for player in game['players'].values():
                    player['health'] = 0
                
                # Send timeout notification
                embed = Embed(
                    title=f"{TIMEOUT} Game Timeout!",
                    description=(
                        f"⏰ Game hangman dihentikan karena tidak ada aktivitas selama 3 menit.\n\n"
                        f"{CHAT} **Kata**: `{game['word'].upper()}`\n"
                        f"💡 **Petunjuk**: {game['clue']}"
                    ),
                    color=0x95a5a6
                )
                
                if game['mode'] == 'last_heart':
                    embed.add_field(
                        name=f"{PLANNER} Round", 
                        value=f"Timeout di round {game['round_number']}", 
                        inline=True
                    )
                
                embed.set_footer(text="Semua pemain kehilangan nyawa karena timeout.")
                await channel.send(embed=embed)
                
                # End game
                await self._end_game(channel, game, reason="timeout")
                
        except asyncio.CancelledError:
            # Timeout was cancelled (normal behavior when game activity occurs)
            pass
        except Exception as e:
            logger.error(f"Error in game timeout handler: {e}")
        
    @commands.hybrid_command(name="hangman_rank", aliases=["hm_rank"], description="Lihat leaderboard Hangman di server ini.")
    async def hangman_leaderboard(self, ctx, start_index: int = 0):
        """Menampilkan leaderboard Hangman (bisa via prefix atau slash)."""
        guild_name = ctx.guild.id
        user_name = ctx.author.display_name

        query = (
            "SELECT user_id, total_points, games_played "
            "FROM voisa.hangman "
            "WHERE guild_id = $1 "
            "ORDER BY total_points DESC "
            "LIMIT $2 OFFSET $3;"
        )

        def formatter(embed, idx, row):
            user_id, total_points, games_played = row
            points_str = f"{total_points:,}".replace(",", ".")
            member = ctx.guild.get_member(user_id)
            username = member.display_name if member else f"Unknown User ({user_id})"
            atrib = YELLOWCROWN if idx == 1 else ""
            embed.add_field(
                name=f"**{idx}. {username}** {atrib}",
                value=f"> Total Poin: **{points_str}**\n"
                      f"> Games Played: **{games_played}**\n",
                inline=False
            )

        await self.paginate_hangman_leaderboard(ctx, query, [ctx.guild.id], formatter)
        logger.info(f"[ COMMAND CALL ] -- [ hm_rank ] ---- From {user_name} on guild [ {guild_name} ]")
        
    async def paginate_hangman_leaderboard(self, ctx, query, params, formatter):
        DATA_PER_PAGE = 10  # Jumlah data per halaman
        
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

                embed = discord.Embed(color=discord.Color.purple())
                embed.description = f"{WHITELINE}"
                embed.set_thumbnail(url=ctx.guild.icon.url if ctx.guild.icon else None)
                embed.set_footer(text=f"{ctx.guild.name} | Leaderboard Hangman")
                embed.set_author(name=f"|  {(start // DATA_PER_PAGE) + 1}  |  Hangman Leaderboard")

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

    @commands.hybrid_command(name="hangman", aliases=["hm"], description="Mulai bermain game hangman.")
    async def start_join(self, ctx: commands.Context):
        """Memulai game Hangman baru dengan fase join menggunakan tombol UI."""
        cid = ctx.channel.id
        user_name = ctx.author.display_name
        guild_name = ctx.guild.name
        
        logger.info(f"[ COMMAND CALL ] -- [ hangman ] ---- From {user_name} on guild [ {guild_name} ]")

        
        async with self.locks[cid]:
            if cid in self.games:
                return await ctx.send("❗ Sudah ada game Hangman aktif di channel ini. \n-# Tunggu hingga selesai atau minta host untuk membatalkan.")

            # Mode selection first
            embed = Embed(
                title=f"{START} Hangman",
                description=(
                    "🎯 **Normal**: Game berakhir ketika kata tertebak atau hanya 1 pemain tersisa\n\n"
                    "💔 **Last Heart**: Game berlanjut dengan kata baru sampai kehilangan semua hati"
                ),
                color=0x9b59b6
            )
            embed.set_footer(text=f"Dipilih oleh: {ctx.author.display_name} | Timeout: 30 detik")

            mode_view = GameModeView(self, ctx)
            mode_message = await ctx.send(embed=embed, view=mode_view)

            await mode_view.wait()
            if not mode_view.selected_mode:
                embed = Embed(
                    title=f"{TIMEOUT} Waktu Habis",
                    description="Pemilihan mode dibatalkan karena tidak ada respons.",
                    color=0x95a5a6
                )
                await mode_message.edit(embed=embed, view=None)
                return

            # Setup game state
            self.games[cid] = {
                'host': ctx.author,
                'phase': 'join',
                'mode': mode_view.selected_mode,
                'word': None,
                'clue': None,
                'display': None,
                'letters_left': 0,
                'players': {},
                'eliminated_players': {},  # Add eliminated players storage
                'guessed': set(),
                'is_solo': False,
                'round_number': 1,
                'wrong_guess_count': 0,  # Track consecutive wrong guesses
                'last_activity': time.time()  # Track last activity for timeout
            }
            
            mode_emoji = "🎯" if mode_view.selected_mode == "normal" else "💔"
            mode_name = "Normal Mode" if mode_view.selected_mode == "normal" else "Last Heart Mode"
            
            embed = Embed(
                title=f"{START} Hangman - Join Phase", 
                color=0x3498db
            )
            embed.add_field(
                name=f"{PLANNER} Aturan Game", 
                value=(
                    "• Tebak huruf satu per satu atau langsung tebak kata\n"
                    "• Setiap salah tebak mengurangi 1 nyawa\n"
                    "• Setiap benar menebak huruf +1 poin\n"
                    "• Menebak kata lengkap +3 poin\n"
                    f"⏰ Game akan timeout setelah 3 menit tanpa aktivitas"
                ), 
                inline=False
            )
            embed.set_footer(text=f"Host: {ctx.author.display_name} | Timeout: 60 detik")

            view = JoinView(self, ctx, mode_view.selected_mode)
            message = await ctx.send(embed=embed, view=view)
            view.message = message

            # Timeout handler
            await view.wait()
            game = self.games.get(cid)
            if game and game['phase'] == 'join':
                embed = Embed(
                    title=f"{TIMEOUT} Waktu Habis", 
                    description="Fase join telah berakhir. Game dibatalkan.",
                    color=0x95a5a6
                )
                await message.edit(embed=embed, view=None)
                del self.games[cid]

    async def _begin_game(self, ctx: commands.Context, game: dict):
        cid = ctx.channel.id
        word, clue = await db.getter_word()
        if not word:
            embed = Embed(
                title="❌ Error",
                description="Gagal mengambil kata dari database. Game dibatalkan.",
                color=0xe74c3c
            )
            await ctx.send(embed=embed)
            if cid in self.games:
                del self.games[cid]
            return
        
        # Handle clue kosong
        if not clue or clue.strip() == "":
            clue = "🤔 Tidak ada petunjuk tersedia"

        word = word.lower().strip()
        
        # Handle special characters like apostrophes
        display = []
        for char in word:
            if char.isalpha():
                display.append('_')
            elif char == "'":
                display.append("'")  # Show apostrophes
            else:
                display.append(char)
                
        letters_left = len(set(char for char in word if char.isalpha()))
        
        # Determine if solo game
        is_solo = len(game['players']) == 1
        game['is_solo'] = is_solo
        
        # Beri petunjuk huruf acak untuk kata panjang
        revealed_count = 0
        if len(word) > 6:
            # Dapatkan semua index huruf yang bisa di-reveal (bukan spasi/simbol)
            revealable_indices = [i for i, char in enumerate(word) if char.isalpha()]
            
            # Tentukan jumlah huruf yang akan di-reveal
            num_to_reveal = 1 if len(word) <= 8 else 2
            
            # Pilih huruf acak (jika ada yang bisa direveal)
            if revealable_indices and num_to_reveal > 0:
                num_to_reveal = min(num_to_reveal, len(revealable_indices))
                random_indices = random.sample(revealable_indices, num_to_reveal)
                
                revealed_letters = set()
                for idx in random_indices:
                    letter = word[idx]
                    if letter not in revealed_letters:
                        revealed_letters.add(letter)
                        # Reveal all instances of this letter
                        for i, char in enumerate(word):
                            if char == letter:
                                display[i] = letter
                        letters_left -= 1
                        revealed_count += 1
        
        game.update({
            'phase': 'play',
            'word': word,
            'clue': clue,
            'display': display,
            'letters_left': letters_left,
            'guessed': set(),
            'wrong_guess_count': 0,
            'last_activity': time.time()
        })

        # Start game timeout
        self._start_game_timeout(cid)

        # Create game start embed
        mode_emoji = "🎯" if game['mode'] == "normal" else "💔"
        mode_name = "Normal" if game['mode'] == "normal" else "Last Heart"
        
        embed = Embed(title=f"{START} Hangman Dimulai!", color=0x2ecc71)
        embed.add_field(name="💡 Petunjuk", value=f"`{clue}`", inline=False)
        
        if revealed_count > 0:
            embed.add_field(
                name="🎁 Bonus", 
                value=f"Diberikan {revealed_count} huruf sebagai bantuan!", 
                inline=False
            )
        
        embed.add_field(
            name=f"{CHAT} Kata", 
            value=f"```{' '.join(display)}```", 
            inline=False
        )
        
        # Player info
        players_info = []
        for p in game['players'].values():
            health_display = f"{REDHEART}" * p['health']
            players_info.append(f"• **{p['member'].display_name}** | {health_display} | {POINT} {p['points']}")
        
        embed.add_field(name=f"{DICE} Pemain", value="\n".join(players_info), inline=False)
        
        game_mode_display = f"{mode_emoji} **{mode_name}**"
        if not is_solo:
            game_mode_display += f" ({len(game['players'])} pemain)"
        embed.add_field(name=f"{POINT} Mode Game", value=game_mode_display, inline=False)
        
        embed.add_field(
            name=f"{PLANNER} Round", 
            value=f"Round **{game['round_number']}**", 
            inline=True
        )
        
        embed.set_footer(text="💭 Ketik 1 huruf untuk menebak huruf, atau ketik kata lengkap untuk menebak seluruh kata! | ⏰ Timeout: 3 menit")
        await ctx.send(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return
            
        cid = message.channel.id
        
        game = self.games.get(cid)
        
        # Skip if no active game or not in play phase
        if not game or game.get('phase') != 'play':
            return        

        async with self.locks[cid]:
            content = message.content.strip().lower()
            player = game['players'].get(message.author.id)
            
            # Skip if not a registered player
            if not player:
                return

            # Validate input
            if not content or not content.replace(' ', '').isalpha():
                return

            # Update last activity and restart timeout
            game['last_activity'] = time.time()
            self._start_game_timeout(cid)

            # Handle word guess (more than 1 character)
            if len(content.replace(' ', '')) > 1:
                if content == game['word']:
                    player['points'] += 3
                    player['correct_guesses'] += 1
                    game['wrong_guess_count'] = 0  # Reset wrong guess counter
                    await message.add_reaction(f"{PRIZE}")
                    
                    success_msg = (
                        f"✨ **{message.author.display_name}** menebak kata dengan benar!\n-# **+3 poin!** Total: **{player['points']}** poin"
                    )
                    await message.channel.send(success_msg)
                    
                    # Handle word completion based on game mode
                    if game['mode'] == 'normal':
                        await self._end_game(message.channel, game, reason="word_guessed")
                    else:  # last_heart mode
                        await self._handle_last_heart_word_completion(message.channel, game)
                else:
                    player['health'] -= 1
                    player['wrong_guesses'] += 1
                    game['wrong_guess_count'] += 1
                    await message.add_reaction(f"{WRONG}")
                    
                    wrong_msg = (
                        f"{WRONG} **{message.author.display_name}** salah menebak kata!\n-# Sisa nyawa: **{player['health']}/5**"
                    )
                    await message.channel.send(wrong_msg)
                    await self._check_player_elimination(message.channel, message.author.id, game)
                    
                    # Check if need status update after 3 wrong guesses
                    if game['wrong_guess_count'] >= 3:
                        await self._update_game_status(message.channel, game)
                        game['wrong_guess_count'] = 0
                return

            # Handle single letter guess
            if len(content) == 1 and content.isalpha():
                letter = content
                
                if letter in game['guessed']:
                    await message.channel.send(
                        f"{WARNING} **{message.author.display_name}**, huruf `{letter.upper()}` sudah pernah ditebak!", 
                        delete_after=5
                    )
                    return
                    
                game['guessed'].add(letter)
                
                if letter in game['word']:
                    # Update display for correct guess
                    correct_positions = []
                    for idx, char in enumerate(game['word']):
                        if char == letter and game['display'][idx] == '_':
                            game['display'][idx] = letter
                            correct_positions.append(idx + 1)
                    
                    if correct_positions:
                        player['points'] += 1
                        player['correct_guesses'] += 1
                        game['wrong_guess_count'] = 0  # Reset wrong guess counter
                        await message.add_reaction(f"{CORRECT}")
                        
                        correct_msg = (
                            f"{CORRECT} **{message.author.display_name}** benar!\n-# **+1 poin!** Total: **{player['points']}** poin"
                        )
                        await message.channel.send(correct_msg)
                        
                        # Check if word is completed
                        if '_' not in ''.join(game['display']):
                            completion_msg = f"{PRIZE} **Selamat! Semua huruf berhasil ditebak!**"
                            await message.channel.send(completion_msg)
                            
                            if game['mode'] == 'normal':
                                await self._end_game(message.channel, game, reason="word_completed")
                            else:  # last_heart mode
                                await self._handle_last_heart_word_completion(message.channel, game)
                            return
                        
                        # Only update status after correct guess (as requested)
                        await self._update_game_status(message.channel, game)
                else:
                    player['health'] -= 1
                    player['wrong_guesses'] += 1
                    game['wrong_guess_count'] += 1
                    await message.add_reaction(f"{WRONG}")
                                    
                    wrong_msg = (
                        f"{WRONG} **{message.author.display_name}** salah! Huruf `{letter.upper()}` tidak ada.\n-# Sisa nyawa: **{player['health']}/5**"
                    )
                    await message.channel.send(wrong_msg)
                    await self._check_player_elimination(message.channel, message.author.id, game)
                    
                    # Check if need status update after 3 wrong guesses
                    if game['wrong_guess_count'] >= 3:
                        await self._update_game_status(message.channel, game)
                        game['wrong_guess_count'] = 0

    async def _handle_last_heart_word_completion(self, channel, game):
        """Handle word completion in last heart mode"""
        # Check if any players still have lives
        alive_players = [p for p in game['players'].values() if p['health'] > 0]
        
        if len(alive_players) == 0:
            # All players are dead - game ends
            await self._end_game(channel, game, reason="all_eliminated")
            return
        
        # Continue to next round since players still have lives
        next_word_embed = Embed(
            title=f"Menyiapkan ronde selanjutnya!",
            description=(
                f"{CHAT} **Kata sebelumnya**: `{game['word'].upper()}`\n\n"
                f"Pemain masih hidup: **{len(alive_players)}** orang"
            ),
            color=0xe67e22
        )
        
        # Show current survivors
        survivors_info = []
        for p in alive_players:
            health_display = f"{REDHEART}" * p['health']
            survivors_info.append(f"• **{p['member'].display_name}** | {health_display} | {POINT} {p['points']}")
        
        next_word_embed.add_field(
            name=f"{SKULL} Survivors", 
            value="\n".join(survivors_info), 
            inline=False
        )
        
        await channel.send(embed=next_word_embed)
        
        # Small delay
        await asyncio.sleep(1)
        
        # Start new round
        await self._start_new_round(channel, game)

    async def _start_new_round(self, channel, game):
        """Start a new round in last heart mode"""
        cid = channel.id
        
        # Get new word
        word, clue = await db.getter_word()
        if not word:
            embed = Embed(
                title="❌ Error",
                description="Gagal mengambil kata baru. Game dihentikan.",
                color=0xe74c3c
            )
            await channel.send(embed=embed)
            del self.games[cid]
            return
        
        # Handle clue kosong
        if not clue or clue.strip() == "":
            clue = "🤔 Tidak ada petunjuk tersedia"
        
        word = word.lower().strip()
        
        # Handle special characters
        display = []
        for char in word:
            if char.isalpha():
                display.append('_')
            elif char == "'":
                display.append("'")  # Show apostrophes
            else:
                display.append(char)
                
        letters_left = len(set(char for char in word if char.isalpha()))
        
        # Increment round number
        game['round_number'] += 1
        
        # Reset game state for new round
        game.update({
            'word': word,
            'clue': clue,
            'display': display,
            'letters_left': letters_left,
            'guessed': set(),
            'wrong_guess_count': 0,
            'last_activity': time.time()
        })
        
        # Restart timeout for new round
        self._start_game_timeout(cid)
        
        # Beri petunjuk huruf acak untuk kata panjang
        revealed_count = 0
        if len(word) > 6:
            revealable_indices = [i for i, char in enumerate(word) if char.isalpha()]
            num_to_reveal = 1 if len(word) <= 8 else 2
            
            if revealable_indices and num_to_reveal > 0:
                num_to_reveal = min(num_to_reveal, len(revealable_indices))
                random_indices = random.sample(revealable_indices, num_to_reveal)
                
                revealed_letters = set()
                for idx in random_indices:
                    letter = word[idx]
                    if letter not in revealed_letters:
                        revealed_letters.add(letter)
                        for i, char in enumerate(word):
                            if char == letter:
                                display[i] = letter
                        letters_left -= 1
                        revealed_count += 1
        
        # Create new round embed
        embed = Embed(
            title=f"💔 Last Heart Mode - Round {game['round_number']}",
            color=0x9b59b6
        )
        embed.add_field(name="💡 Petunjuk", value=f"`{clue}`", inline=False)
        
        if revealed_count > 0:
            embed.add_field(
                name="🎁 Bonus", 
                value=f"Diberikan {revealed_count} huruf sebagai bantuan!", 
                inline=False
            )
        
        embed.add_field(
            name=f"{CHAT} Kata Baru", 
            value=f"```{' '.join(display)}```", 
            inline=False
        )
        
        # Player status (only alive players)
        players_info = []
        for p in game['players'].values():
            if p['health'] > 0:  # Only show alive players
                health_display = f"{REDHEART}" * p['health']
                players_info.append(f"• **{p['member'].display_name}** | {health_display} | {POINT} {p['points']}")
        
        # Prevent embed overflow
        players_text = "\n".join(players_info)
        if len(players_text) > 900:
            players_text = players_text[:900] + "\n..."
        
        embed.add_field(name=f"{DICE} Pemain Tersisa", value=players_text, inline=False)
        embed.set_footer(text="💭 Lanjutkan menebak! Bertahan sampai akhir untuk menang! | ⏰ Timeout: 3 menit")
        
        await channel.send(embed=embed)

    async def _update_game_status(self, channel, game):
        """Update game status - called after correct guesses or every 3 wrong guesses"""
        embed = Embed(title=f"Status Game", color=0xf39c12)
        embed.add_field(name="💡 Petunjuk", value=f"`{game['clue']}`", inline=False)
        
        # Prevent long word display overflow
        word_display = ' '.join(game['display'])
        if len(word_display) > 100:
            word_display = word_display[:97] + "..."
        embed.add_field(name=f"{CHAT} Kata", value=f"```{word_display}```", inline=False)
        
        # Player status
        players_info = []
        for player in game['players'].values():
            if player['health'] > 0:  # Only show alive players
                health_hearts = f"{REDHEART}" * player['health']
                health_broken = f"{SKULLHEART}" * (5 - player['health'])
                health_display = health_hearts + health_broken
                
                players_info.append(
                    f"• **{player['member'].display_name}** | {health_display} | {POINT} {player['points']}"
                )
        
        # Prevent embed overflow
        players_text = "\n".join(players_info)
        if len(players_text) > 900:
            players_text = players_text[:900] + "\n..."
            
        embed.add_field(name=f"{SKULL} Status Pemain", value=players_text, inline=False)
        
        # Guessed letters with better formatting
        if game['guessed']:
            guessed_sorted = sorted(list(game['guessed']))
            guessed_display = ' '.join([f"`{letter.upper()}`" for letter in guessed_sorted])
            if len(guessed_display) > 500:
                guessed_display = guessed_display[:490] + "..."
        else:
            guessed_display = "_Belum ada huruf yang ditebak_"
            
        embed.add_field(name="🔤 Huruf yang Sudah Ditebak", value=guessed_display, inline=False)
        
        # Progress info
        total_letters = len([c for c in game['word'] if c.isalpha()])
        revealed_letters = len([c for c in game['display'] if c.isalpha()])
        progress = f"{revealed_letters}/{total_letters} huruf terungkap"
        
        embed.add_field(name=f"{PROGRESS} Progress", value=progress, inline=True)
        
        mode_emoji = "🎯" if game['mode'] == "normal" else "💔"
        mode_name = "Normal" if game['mode'] == "normal" else "Last Heart"
        game_mode = f"{mode_emoji} {mode_name}"
        if not game['is_solo']:
            alive_count = len([p for p in game['players'].values() if p['health'] > 0])
            game_mode += f" ({alive_count} hidup)"
        embed.add_field(name=f"{START} Mode", value=game_mode, inline=True)
        
        if game['mode'] == 'last_heart':
            embed.add_field(name=f"{PLANNER} Round", value=f"Round {game['round_number']}", inline=True)
        
        embed.set_footer(text="💭 Terus tebak huruf atau langsung tebak kata! | ⏰ Timeout: 3 menit")
        await channel.send(embed=embed)

    async def _check_player_elimination(self, channel, user_id, game):
        """Check if player should be eliminated and handle game end conditions"""
        player = game['players'].get(user_id)
        if not player:
            return
            
        if player['health'] <= 0:
            # Move player to eliminated list
            eliminated_player = game['players'].pop(user_id)
            game['eliminated_players'][user_id] = eliminated_player
            
            elimination_embed = Embed(
                title=f"{SKULL} Player Eliminated!",
                description=f"**{eliminated_player['member'].display_name}** kehabisan nyawa dan tereliminasi!",
                color=0xe74c3c
            )
            elimination_embed.add_field(
                name=f"{PLANNER} Statistik Final", 
                value=f"Poin: **{eliminated_player['points']}** | Tebakan Benar: **{eliminated_player['correct_guesses']}**",
                inline=False
            )
            await channel.send(embed=elimination_embed)
            
            remaining_players = len([p for p in game['players'].values() if p['health'] > 0])
            
            if remaining_players == 0:
                await channel.send(f"**Semua pemain telah tereliminasi!**")
                await self._end_game(channel, game, reason="all_eliminated")
            elif remaining_players == 1 and not game['is_solo']:
                if game['mode'] == 'normal':
                    last_player = next(p for p in game['players'].values() if p['health'] > 0)
                    await channel.send(f"{PRIZE} **{last_player['member'].display_name}** adalah pemain terakhir yang tersisa!")
                    await self._end_game(channel, game, reason="last_survivor")
                # In last_heart mode, game continues until word is completed
            
    async def _end_game(self, channel, game, reason="completed"):
        """End the game with appropriate message based on reason"""
        cid = channel.id
        if cid not in self.games:
            return

        # Cancel timeout task
        self._cancel_timeout_task(cid)

        # Save points to database before ending
        await self._save_player_stats(channel, game)

        # Create end game embed based on reason
        if reason == "timeout":
            embed = Embed(
                title=f"{TIMEOUT} GAME TIMEOUT!",
                description=(
                    f"⏰ **Game dihentikan karena tidak ada aktivitas selama 3 menit.**\n\n"
                    f"{CHAT} **Kata**: `{game['word'].upper()}`\n"
                    f"💡 **Petunjuk**: {game['clue']}"
                ),
                color=0x95a5a6
            )
            if game['mode'] == 'last_heart':
                embed.add_field(name=f"{PLANNER} Round", value=f"Timeout di round {game['round_number']}", inline=True)

        elif reason == "word_guessed":
            if game['players']:
                # Find who guessed the word (highest points or most recent action)
                winner = max(game['players'].values(), key=lambda p: (p['points'], p['correct_guesses']))
                embed = Embed(
                    title=f"KATA BERHASIL DITEBAK!",
                    description=(
                        f"{PRIZE} **{winner['member'].mention}** memenangkan game!\n"
                        f"{POINT} **Poin**: {winner['points']}\n"
                        f"{CORRECT} **Tebakan Benar**: {winner['correct_guesses']}\n\n"
                        f"{CHAT} **Kata**: `{game['word'].upper()}`"
                    ),
                    color=0x2ecc71
                )
            else:
                embed = Embed(
                    title=f"{PRIZE} GAME SELESAI",
                    description=f"{CHAT} **Kata**: `{game['word'].upper()}`",
                    color=0x3498db
                )
        
        elif reason == "word_completed":
            if game['players']:
                winner = max(game['players'].values(), key=lambda p: (p['points'], p['correct_guesses']))
                embed = Embed(
                    title=f"{PRIZE} SEMUA HURUF TERKUAK!",
                    description=(
                        f"{PRIZE} **{winner['member'].mention}** memenangkan game!\n"
                        f"{POINT} **Poin**: {winner['points']}\n"
                        f"{CORRECT} **Tebakan Benar**: {winner['correct_guesses']}\n\n"
                        f"{CHAT} **Kata**: `{game['word'].upper()}`"
                    ),
                    color=0x2ecc71
                )
            else:
                embed = Embed(
                    title=f"{PRIZE} SEMUA HURUF TERKUAK!",
                    description=f"{CHAT} **Kata**: `{game['word'].upper()}`",
                    color=0x3498db
                )
        
        elif reason == "last_survivor":
            winner = next(p for p in game['players'].values() if p['health'] > 0)
            embed = Embed(
                title=f"{PRIZE} PEMENANG - SURVIVOR TERAKHIR!",
                description=(
                    f"{WINNER} **{winner['member'].mention}** bertahan hingga akhir!\n"
                    f"{POINT} **Poin**: {winner['points']}\n"
                    f"{CORRECT} **Tebakan Benar**: {winner['correct_guesses']}\n\n"
                    f"{CHAT} **Kata**: `{game['word'].upper()}`"
                ),
                color=0xf1c40f
            )

        elif reason == "all_eliminated":
            embed = Embed(
                title=f"{SKULL} GAME OVER !",
                description=(
                    f"💀 **Semua pemain telah tereliminasi!**\n\n"
                    f"{CHAT} **Kata terakhir**: `{game['word'].upper()}`\n"
                    f"{PLANNER} **Total Rounds**: {game['round_number']}\n\n"
                    # f"🏆 **Pemenang**: Player dengan poin tertinggi!"
                ),
                color=0xe74c3c
            )
        
        else:  # Default completion
            if game['players']:
                winner = max(game['players'].values(), key=lambda p: (p['points'], p['correct_guesses']))
                embed = Embed(
                    title=f"{PRIZE} PEMENANG!",
                    description=(
                        f"{PRIZE} **{winner['member'].mention}** memenangkan game!\n"
                        f"{POINT} **Poin**: {winner['points']}\n"
                        f"{CORRECT} **Tebakan Benar**: {winner['correct_guesses']}\n\n"
                        f"{CHAT} **Kata**: `{game['word'].upper()}`"
                    ),
                    color=0x2ecc71
                )
            else:
                embed = Embed(
                    title=f"{PRIZE} GAME SELESAI",
                    description=f"{CHAT} **Kata**: `{game['word'].upper()}`",
                    color=0x3498db
                )

        # Add final scoreboard if multiple players
        all_players = {**game['players'], **game['eliminated_players']}
        if len(all_players) > 1:
            scoreboard = []
            sorted_players = sorted(all_players.values(), key=lambda p: (p['points'], p['correct_guesses']), reverse=True)
            
            for i, player in enumerate(sorted_players, 1):
                medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
                health_status = f"({player['health']}❤️)" if player['health'] > 0 else "(💀)"
                scoreboard.append(
                    f"{medal} **{player['member'].display_name}** - {player['points']} poin ({player['correct_guesses']} benar) {health_status}"
                )
            
            # Prevent scoreboard overflow
            scoreboard_text = "\n".join(scoreboard)
            if len(scoreboard_text) > 1000:
                scoreboard_text = scoreboard_text[:990] + "\n..."
            
            embed.add_field(name="🏅 Scoreboard Final", value=scoreboard_text, inline=False)

        # Add game statistics
        total_guesses = len(game['guessed'])
        mode_name = "Normal" if game['mode'] == "normal" else "Last Heart"
        stats_text = f"Total huruf ditebak: {total_guesses}\nMode: {mode_name}"
        if game['mode'] == 'last_heart':
            stats_text += f"\nRounds dimainkan: {game['round_number']}"
        
        embed.add_field(
            name=f"{PLANNER} Statistik Game", 
            value=stats_text, 
            inline=True
        )

        embed.set_footer(text="ketik v!hm_rank untuk melihat leaderboard guild.")
        await channel.send(embed=embed)

        # Cleanup
        del self.games[cid]

    async def _save_player_stats(self, channel, game):
        """Save player statistics to database"""
        try:
            guild_id = channel.guild.id
            for user_id, player_data in {**game['players'], **game['eliminated_players']}.items():
                # Dummy database update - replace with actual implementation
                points_to_add = player_data['points']
                
                # This is a placeholder for the actual database update
                # You'll need to implement the actual upsert logic
                await self._upsert_player_leaderboard(
                    user_id=user_id,
                    guild_id=guild_id,
                    points_to_add=points_to_add,
                    games_played=1,
                    correct_guesses=player_data['correct_guesses'],
                    wrong_guesses=player_data['wrong_guesses']
                )
                
            logger.info(f"Saved stats for {len(game['players']) + len(game['eliminated_players'])} players in guild {guild_id}")
        except Exception as e:
            logger.error(f"Failed to save player stats: {e}")

    async def _upsert_player_leaderboard(self, user_id: int, guild_id: int, points_to_add: int, 
                                       games_played: int, correct_guesses: int, wrong_guesses: int):
        """Upsert player statistics to leaderboard table"""
        try:
            # This is a dummy implementation
            # Replace with actual database connection and query
            async with db_connection() as conn:
                if not conn:
                    logger.error("Failed to connect to database for leaderboard update.")
                    return
                
                # Upsert query (you'll need to create this table first)
                await conn.execute("""
                    INSERT INTO voisa.hangman 
                    (user_id, guild_id, total_points, games_played, total_correct_guesses, total_wrong_guesses, last_played)
                    VALUES ($1, $2, $3, $4, $5, $6, NOW())
                    ON CONFLICT (user_id, guild_id)
                    DO UPDATE SET
                        total_points = voisa.hangman.total_points + EXCLUDED.total_points,
                        games_played = voisa.hangman.games_played + EXCLUDED.games_played,
                        total_correct_guesses = voisa.hangman.total_correct_guesses + EXCLUDED.total_correct_guesses,
                        total_wrong_guesses = voisa.hangman.total_wrong_guesses + EXCLUDED.total_wrong_guesses,
                        last_played = EXCLUDED.last_played
                """, user_id, guild_id, points_to_add, games_played, correct_guesses, wrong_guesses)
                
        except Exception as e:
            logger.error(f"Error upserting player leaderboard data: {e}")

    @commands.command(name="hstop", aliases=["hangman_stop"])
    async def force_stop_game(self, ctx: commands.Context):
        """Force stop hangman game (only for host or admin)"""
        cid = ctx.channel.id
        user_name = ctx.author.display_name
        guild_name = ctx.guild.name
        
        logger.info(f"[ COMMAND CALL ] -- [ hstop ] ---- From {user_name} on guild [ {guild_name} ]")
        
        async with self.locks[cid]:
            game = self.games.get(cid)
            
            if not game:
                return await ctx.send("❗ Tidak ada game Hangman aktif di channel ini.")
            
            # Check permissions
            is_host = ctx.author == game['host']
            is_admin = ctx.author.guild_permissions.manage_messages
            
            if not (is_host or is_admin):
                return await ctx.send(f"{WARNING} Hanya host game atau admin yang dapat menghentikan game.")
            
            # Cancel timeout task
            self._cancel_timeout_task(cid)
            
            # Save stats before stopping
            await self._save_player_stats(ctx.channel, game)
            
            mode_name = "Normal" if game['mode'] == "normal" else "Last Heart"
            embed = Embed(
                title="⛔ Game Dihentikan",
                description=(
                    f"Game hangman ({mode_name} Mode) dihentikan oleh {ctx.author.mention}.\n\n"
                    f"{CHAT} **Kata**: `{game['word'].upper()}`"
                ),
                color=0x95a5a6
            )
            
            if game['mode'] == 'last_heart':
                embed.add_field(name=f"{PLANNER} Round", value=f"Dihentikan di round {game['round_number']}", inline=True)
            
            await ctx.send(embed=embed)
            del self.games[cid]

async def setup(bot: commands.Bot):
    await bot.add_cog(HangmanCog(bot))