# cogs/word_chain.py
import logging
import discord
from discord.ext import commands
import asyncio
import random
from typing import Dict, List, Optional, Set, Tuple
from utils.decorator.channel import check_master_channel

from .function.helper import DBHandler  # gunakan helper Anda

logger = logging.getLogger(__name__)

class WordChainGame:
    def __init__(self, channel_id: int, host_id: int):
        self.channel_id: int = channel_id
        self.host_id: int = host_id
        self.players: List[int] = []  # User IDs
        self.scores: Dict[int, int] = {}  # user_id: score
        self.passes: Dict[int, int] = {}  # user_id: pass_count
        self.rolls: Dict[int, int] = {}  # user_id: roll_count
        self.used_words: Set[str] = set()  # Track used words
        self.current_player_index: int = 0
        self.current_word: str = ""
        self.current_suffix: str = ""
        self.current_suffixes: List[str] = []  # Multiple suffixes for English mode
        self.is_active: bool = False
        self.is_joining: bool = True
        self.join_message: Optional[discord.Message] = None
        self.game_message: Optional[discord.Message] = None
        self.turn_timeout_task: Optional[asyncio.Task] = None
        self.join_timeout_task: Optional[asyncio.Task] = None
        self.lang: str = "indo"  # default: 'indo' or 'eng'

    def cleanup(self):
        """Clean up all tasks and references (best-effort)."""
        try:
            if self.turn_timeout_task and not self.turn_timeout_task.done():
                self.turn_timeout_task.cancel()
        except Exception:
            pass

        try:
            if self.join_timeout_task and not self.join_timeout_task.done():
                self.join_timeout_task.cancel()
        except Exception:
            pass

        self.players.clear()
        self.scores.clear()
        self.passes.clear()
        self.rolls.clear()
        self.used_words.clear()
        self.current_suffixes.clear()
        self.join_message = None
        self.game_message = None
        self.turn_timeout_task = None
        self.join_timeout_task = None


class JoinGameView(discord.ui.View):
    def __init__(self, cog, game: WordChainGame):
        super().__init__(timeout=120)
        self.cog = cog
        self.game = game

    @discord.ui.button(label="", style=discord.ButtonStyle.green, emoji="➕")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id == self.cog.bot.user.id:
            await interaction.response.defer()
            return

        lock = self.cog.get_lock(self.game.channel_id)
        send_already = False
        send_full = False
        embed = None
        async with lock:
            if interaction.user.id in self.game.players:
                send_already = True
            elif len(self.game.players) >= 10:
                send_full = True
            else:
                self.game.players.append(interaction.user.id)
                self.game.scores[interaction.user.id] = 0
                self.game.passes[interaction.user.id] = 0
                self.game.rolls[interaction.user.id] = 0
                embed = self.cog.create_join_embed(self.game)

        if send_already:
            await interaction.response.send_message("Kamu sudah bergabung!", ephemeral=True)
            return
        if send_full:
            await interaction.response.send_message("Game sudah penuh!", ephemeral=True)
            return

        try:
            # try to edit original message; if fails, send followup
            await interaction.response.edit_message(embed=embed, view=self)
        except Exception:
            try:
                await interaction.followup.send(embed=embed)
            except Exception:
                logger.exception("Failed to update join message after join_button")

    @discord.ui.button(label="Start", style=discord.ButtonStyle.primary)
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.game.host_id:
            await interaction.response.send_message("Hanya host yang bisa memulai game!", ephemeral=True)
            return

        async with self.cog.get_lock(self.game.channel_id):
            players_count = len(self.game.players)
        if players_count < 1:
            await interaction.response.send_message("Minimal 1 pemain untuk memulai!", ephemeral=True)
            return

        await self.cog.start_game(self.game, interaction)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.game.host_id:
            await interaction.response.send_message("Hanya host yang bisa membatalkan game!", ephemeral=True)
            return

        await self.cog.cancel_game(self.game, interaction)

    @discord.ui.button(label="mode", style=discord.ButtonStyle.secondary, custom_id="mode_eng")
    async def mode_eng(self, interaction: discord.Interaction, button: discord.ui.Button):
        lock = self.cog.get_lock(self.game.channel_id)
        async with lock:
            # toggle mode
            self.game.lang = "indo" if self.game.lang == "eng" else "eng"
            embed = self.cog.create_join_embed(self.game)

        try:
            await interaction.response.edit_message(embed=embed, view=self)
        except Exception:
            try:
                await interaction.followup.send(embed=embed)
            except Exception:
                logger.exception("Failed to update join message after toggling mode")

    async def on_timeout(self):
        # FIX: Check if game is still in joining phase before sending timeout message
        async with self.cog.get_lock(self.game.channel_id):
            if self.game.is_joining:
                still_joining = True
            else:
                still_joining = False
        
        if still_joining:
            channel = self.cog.bot.get_channel(self.game.channel_id)
            if channel:
                try:
                    await channel.send("⏰ Waktu bergabung habis! Game dibatalkan.")
                except Exception:
                    logger.exception("Failed to send join timeout message")
            await self.cog.cleanup_game(self.game.channel_id)


class WordChainCog(commands.Cog):
    TURN_TIMEOUT_SECONDS = 30

    def __init__(self, bot):
        self.bot = bot
        self.games: Dict[int, WordChainGame] = {}  # channel_id: game
        self.message_locks: Dict[int, asyncio.Lock] = {}  # channel_id: lock

    def get_lock(self, channel_id: int) -> asyncio.Lock:
        if channel_id not in self.message_locks:
            self.message_locks[channel_id] = asyncio.Lock()
        return self.message_locks[channel_id]

    async def _join_timeout_handler(self, game: WordChainGame, timeout: int = 120):
        """Background task to cancel game when join phase times out."""
        try:
            await asyncio.sleep(timeout)
            # FIX: Check if game is still in joining phase before taking action
            async with self.get_lock(game.channel_id):
                if game.is_joining:
                    still_joining = True
                else:
                    still_joining = False
            
            if still_joining:
                channel = self.bot.get_channel(game.channel_id)
                if channel:
                    try:
                        await channel.send("⏰ Waktu bergabung habis! Game dibatalkan.")
                    except Exception:
                        logger.exception("Failed to send join timeout message from handler")
                await self.cleanup_game(game.channel_id)
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Error in join timeout handler for %s", game.channel_id)

    async def cleanup_game(self, channel_id: int):
        """
        Robust cleanup:
         - safe to call from anywhere
         - avoid deadlock by not acquiring lock if it's currently locked
         - always attempt to remove dict entries
        """
        game = self.games.get(channel_id)
        lock = self.message_locks.get(channel_id)

        try:
            if lock and not lock.locked():
                async with lock:
                    if game:
                        try:
                            game.is_active = False
                            game.is_joining = False  # FIX: Also set joining to False during cleanup
                        except Exception:
                            pass
                        try:
                            if game.turn_timeout_task and not game.turn_timeout_task.done():
                                game.turn_timeout_task.cancel()
                        except Exception:
                            pass
                        try:
                            if game.join_timeout_task and not game.join_timeout_task.done():
                                game.join_timeout_task.cancel()
                        except Exception:
                            pass
                        try:
                            game.cleanup()
                        except Exception:
                            logger.exception("Error during game.cleanup()")
            else:
                if game:
                    try:
                        game.is_active = False
                        game.is_joining = False  # FIX: Also set joining to False during cleanup
                    except Exception:
                        pass
                    try:
                        if game.turn_timeout_task and not game.turn_timeout_task.done():
                            game.turn_timeout_task.cancel()
                    except Exception:
                        pass
                    try:
                        if game.join_timeout_task and not game.join_timeout_task.done():
                            game.join_timeout_task.cancel()
                    except Exception:
                        pass
                    try:
                        game.cleanup()
                    except Exception:
                        logger.exception("Error during game.cleanup() (no-lock path)")
        except Exception:
            logger.exception("Unexpected error in cleanup_game for %s", channel_id)

        try:
            if channel_id in self.games:
                del self.games[channel_id]
        except Exception:
            logger.exception("Error deleting game entry for %s", channel_id)

        try:
            if channel_id in self.message_locks:
                del self.message_locks[channel_id]
        except Exception:
            logger.exception("Error deleting lock entry for %s", channel_id)

    async def cancel_game(self, game: WordChainGame, interaction: discord.Interaction):
        embed = discord.Embed(
            title="❌ Game Dibatalkan",
            description="Game telah dibatalkan oleh host.",
            color=0xff0000
        )
        try:
            await interaction.response.edit_message(embed=embed, view=None)
        except Exception:
            try:
                await interaction.followup.send(embed=embed)
            except Exception:
                logger.exception("Failed to notify cancel_game")
        await self.cleanup_game(game.channel_id)

    # Helpers
    def get_suffix(self, word: str, lang: str = "indo") -> str:
        w = word.lower().strip()
        if len(w) >= 2:
            return w[-2:]
        return w

    def get_suffixes(self, word: str) -> List[str]:
        w = word.lower().strip()
        suffixes: List[str] = []
        if len(w) >= 3:
            suffixes.append(w[-3:])
        if len(w) >= 2:
            suffixes.append(w[-2:])
        if len(w) >= 1:
            suffixes.append(w[-1:])
        return suffixes

    def is_valid_word_format(self, word: str, lang: str = "indo") -> bool:
        if not isinstance(word, str) or not word:
            return False
        if lang == "indo":
            # allow alphabetic and hyphen, disallow spaces
            return all(c.isalpha() or c == '-' for c in word) and ' ' not in word
        else:
            return word.isalpha() and ' ' not in word

    # DB wrappers
    async def get_random_word(self, lang: str = "indo") -> Optional[str]:
        try:
            return await DBHandler.get_random_word(lang=lang)
        except Exception as e:
            logger.exception("Error getting random word: %s", e)
            return None

    async def validate_word(self, word: str, lang: str = "indo") -> bool:
        try:
            return await DBHandler.validate_word(word, lang=lang)
        except Exception as e:
            logger.exception("Error validating word: %s", e)
            return False

    async def get_bot_word(self, game_snapshot) -> Optional[str]:
        try:
            lang = game_snapshot["lang"]
            if lang == "eng" and game_snapshot.get("current_suffixes"):
                for suffix in game_snapshot.get("current_suffixes", []):
                    used_words_list = list(game_snapshot.get("used_words", []))
                    word = await DBHandler.get_bot_word(suffix, used_words_list, lang=lang)
                    if word:
                        return word
                return None
            else:
                prefix = game_snapshot.get("current_suffix", "").lower()
                used_words_list = list(game_snapshot.get("used_words", []))
                return await DBHandler.get_bot_word(prefix, used_words_list, lang=lang)
        except Exception as e:
            logger.exception("Error fetching bot word: %s", e)
            return None

    # Embed builders (robust)
    def create_join_embed(self, game: WordChainGame) -> discord.Embed:
        mode_display = "🇮🇩 Indonesia" if game.lang == "indo" else "🇺🇸 English"
        embed = discord.Embed(
            title="Sambung Kata",
            description=f"**Mode: {mode_display}**\n\nKlik tombol **Join** untuk bergabung!\nHost dapat menekan **Start** untuk memulai game.",
            color=0x00ff00
        )
        if game.players:
            player_mentions = [f"<@{player_id}>" for player_id in game.players]
            embed.add_field(name=f"Pemain ({len(game.players)}/10)", value="\n".join(player_mentions), inline=False)
        else:
            embed.add_field(name="Pemain (0/10)", value="Belum ada pemain", inline=False)
        embed.add_field(name="Host", value=f"<@{game.host_id}>", inline=True)
        if game.lang == "indo":
            embed.add_field(name="Aturan",
                            value="• Hanya huruf alfabet\n• Tidak boleh mengandung spasi\n• Awalan: 2 huruf terakhir",
                            inline=False)
        else:
            embed.add_field(name="Aturan",
                            value="• Hanya huruf alfabet\n• Tidak boleh spasi atau tanda baca\n• Awalan: 3, 2, atau 1 huruf terakhir",
                            inline=False)
        embed.set_footer(text="Waktu bergabung: 2 menit")
        return embed

    def create_game_embed(self, game_snapshot_like) -> discord.Embed:
        """
        Robust embed builder: accepts either a WordChainGame instance OR a snapshot dict.
        """
        def _get(field, default=None):
            try:
                return getattr(game_snapshot_like, field)
            except Exception:
                try:
                    return game_snapshot_like.get(field, default)  # type: ignore[attr-defined]
                except Exception:
                    return default

        embed = discord.Embed(title="Sambung Kata", color=0xff9900)
        current_word = _get("current_word", "") or ""
        lang = _get("lang", "indo") or "indo"

        if current_word:
            embed.add_field(name="Kata :", value=f"```{current_word}```", inline=False)
            if lang == "eng":
                suffixes = _get("current_suffixes", []) or []
                if suffixes:
                    suffixes_text = " / ".join([f"`{suffix}`" for suffix in suffixes])
                    embed.add_field(name="Lanjutkan dengan awalan :", value=suffixes_text, inline=False)
            else:
                cur_suffix = _get("current_suffix", "") or ""
                embed.add_field(name="Lanjutkan dengan awalan :", value=f"`{cur_suffix}`", inline=False)
        else:
            # show expected suffix even if no current word
            if lang == "eng":
                suffixes = _get("current_suffixes", []) or []
                if suffixes:
                    suffixes_text = " / ".join([f"`{suffix}`" for suffix in suffixes])
                    embed.add_field(name="Lanjutkan dengan awalan :", value=suffixes_text, inline=False)
            else:
                cur_suffix = _get("current_suffix", "") or ""
                if cur_suffix:
                    embed.add_field(name="Lanjutkan dengan awalan :", value=f"`{cur_suffix}`", inline=False)

        players = _get("players", []) or []
        current_idx = _get("current_player_index", 0) or 0
        if players:
            if current_idx >= len(players):
                current_idx = 0
            current_player = players[current_idx]
            embed.add_field(name="Giliran", value=f"<@{current_player}>", inline=True)

        scores = _get("scores", {}) or {}
        if scores and players:
            score_text = []
            for player_id in players:
                if player_id in scores:
                    score_text.append(f"<@{player_id}>: {scores[player_id]} poin")
            if score_text:
                embed.add_field(name="Skor", value="\n".join(score_text), inline=False)

        used_words = _get("used_words", set()) or set()
        if used_words:
            embed.add_field(name="Kata digunakan :", value=f"{len(used_words)} kata", inline=True)

        mode_display = "🇮🇩 Indonesia" if (lang == "indo") else "🇺🇸 English"
        embed.set_footer(text=f"Ketik 'pass' untuk skip atau 'roll' untuk kata baru | {mode_display}")
        return embed

    # Main game logic
    async def handle_bot_turn(self, game: WordChainGame):
        # snapshot and quick checks
        async with self.get_lock(game.channel_id):
            if not game.is_active:
                return
            snapshot = {
                "lang": game.lang,
                "current_suffix": game.current_suffix,
                "current_suffixes": list(game.current_suffixes),
                "used_words": set(game.used_words),
            }

        channel = self.bot.get_channel(game.channel_id)
        processing_msg = None
        try:
            if channel:
                processing_msg = await channel.send("_Processing..._")
        except Exception:
            processing_msg = None

        # small delay to simulate thinking and to allow deletion of processing_msg safely
        await asyncio.sleep(1)
        bot_word = await self.get_bot_word(snapshot)

        if bot_word:
            async with self.get_lock(game.channel_id):
                if not game.is_active:
                    try:
                        if processing_msg:
                            await processing_msg.delete()
                    except Exception:
                        pass
                    return
                if bot_word in game.used_words:
                    bot_word = None
                else:
                    game.current_word = bot_word
                    if game.lang == "eng":
                        game.current_suffixes = self.get_suffixes(bot_word)
                        game.current_suffix = game.current_suffixes[0] if game.current_suffixes else ""
                    else:
                        game.current_suffix = self.get_suffix(bot_word, game.lang)
                        game.current_suffixes = []
                    game.used_words.add(bot_word)
                    game.scores[self.bot.user.id] = game.scores.get(self.bot.user.id, 0) + len(bot_word)
                    if game.players:
                        game.current_player_index = (game.current_player_index + 1) % len(game.players)

            try:
                if processing_msg:
                    await processing_msg.edit(content=f"{bot_word}")
                else:
                    if channel:
                        await channel.send(bot_word)
            except Exception:
                logger.exception("Failed to post bot word")

            await self.update_game_message(game)

            async with self.get_lock(game.channel_id):
                next_is_bot = (game.players and game.current_player_index < len(game.players) and game.players[game.current_player_index] == self.bot.user.id)
            if next_is_bot:
                # schedule next bot turn without deep recursion
                asyncio.create_task(self.handle_bot_turn(game))
            else:
                await self.start_turn_timeout(game)
            return

        # bot couldn't find word
        async with self.get_lock(game.channel_id):
            current_rolls = game.rolls.get(self.bot.user.id, 0)

        try:
            if processing_msg:
                await processing_msg.delete()
        except Exception:
            pass

        if current_rolls < 2:
            await self.handle_roll(game, self.bot.user.id, is_bot=True)
            return

        async with self.get_lock(game.channel_id):
            current_passes = game.passes.get(self.bot.user.id, 0)

        if current_passes >= 3:
            try:
                if channel:
                    await channel.send(f"<@{self.bot.user.id}> sudah menggunakan seluruh `pass!`")
            except Exception:
                logger.exception("Failed to notify bot out of passes")
            asyncio.create_task(self.eliminate_player(game, self.bot.user.id, "kehabisan `pass`"))
            return

        # increment pass and advance turn
        async with self.get_lock(game.channel_id):
            game.passes[self.bot.user.id] = current_passes + 1
            if game.players:
                game.current_player_index = (game.current_player_index + 1) % len(game.players)

        try:
            if channel:
                await channel.send(f"<@{self.bot.user.id}> pass! ({current_passes + 1}/3)")
        except Exception:
            logger.exception("Failed to post bot pass")

        await self.update_game_message(game)

        async with self.get_lock(game.channel_id):
            next_is_bot = (game.players and game.current_player_index < len(game.players) and game.players[game.current_player_index] == self.bot.user.id)

        if next_is_bot:
            asyncio.create_task(self.handle_bot_turn(game))
        else:
            await self.start_turn_timeout(game)

    async def handle_roll(self, game: WordChainGame, player_id: int, is_bot: bool = False):
        """
        roll changes the current word and consumes a roll, BUT DOES NOT advance the turn.
        The player who rolled keeps the same turn.
        """
        lock = self.get_lock(game.channel_id)

        async with lock:
            current_rolls = game.rolls.get(player_id, 0)
            too_many = current_rolls >= 2

        channel = self.bot.get_channel(game.channel_id)
        if too_many:
            if channel:
                try:
                    if is_bot:
                        await channel.send(f"<@{self.bot.user.id}> sudah menggunakan seluruh `roll!`")
                    else:
                        await channel.send(f"<@{player_id}> sudah menggunakan seluruh `roll!`")
                except Exception:
                    logger.exception("Failed to notify too many rolls")
            return

        new_word = await self.get_random_word(lang=game.lang)
        if not new_word:
            logger.warning("No random word returned for roll")
            return

        async with lock:
            if not game.is_active:
                return
            game.current_word = new_word
            if game.lang == "eng":
                game.current_suffixes = self.get_suffixes(new_word)
                game.current_suffix = game.current_suffixes[0] if game.current_suffixes else ""
            else:
                game.current_suffix = self.get_suffix(new_word, game.lang)
                game.current_suffixes = []
            game.used_words.add(new_word)
            game.rolls[player_id] = game.rolls.get(player_id, 0) + 1

            try:
                if game.turn_timeout_task and not game.turn_timeout_task.done():
                    game.turn_timeout_task.cancel()
            except Exception:
                pass

            # FIX: Add bounds checking for current_player_index
            if game.current_player_index >= len(game.players):
                game.current_player_index = 0
            current_player_is_bot = (game.players and game.current_player_index < len(game.players) and game.players[game.current_player_index] == self.bot.user.id)

        if channel:
            try:
                if is_bot:
                    await channel.send(f"🎲 <@{self.bot.user.id}> roll! Kata baru: **{new_word}** ({game.rolls.get(player_id)}/2)")
                else:
                    await channel.send(f"🎲 <@{player_id}> roll! Kata baru: **{new_word}** ({game.rolls.get(player_id)}/2)")
            except Exception:
                logger.exception("Failed to announce roll")

        await self.update_game_message(game)

        if current_player_is_bot:
            asyncio.create_task(self.handle_bot_turn(game))
        else:
            await self.start_turn_timeout(game)

    async def update_game_message(self, game: WordChainGame):
        lock = self.get_lock(game.channel_id)

        async with lock:
            old_msg = game.game_message
            # FIX: Add bounds checking
            if game.current_player_index >= len(game.players):
                game.current_player_index = 0
                
            snapshot = {
                "current_word": game.current_word,
                "current_suffix": game.current_suffix,
                "current_suffixes": list(game.current_suffixes),
                "players": list(game.players),
                "current_player_index": game.current_player_index,
                "scores": dict(game.scores),
                "used_words": set(game.used_words),
                "lang": game.lang,
            }
            game.game_message = None

        try:
            if old_msg:
                try:
                    await old_msg.delete()
                except Exception:
                    pass
        except Exception:
            logger.exception("Error deleting old game message")

        channel = self.bot.get_channel(game.channel_id)
        if channel:
            embed = self.create_game_embed(snapshot)
            try:
                new_msg = await channel.send(embed=embed)
            except Exception:
                logger.exception("Failed to send new game message")
                new_msg = None
            async with lock:
                game.game_message = new_msg

    async def start_game(self, game: WordChainGame, interaction: discord.Interaction):
        """
        Start game: avoid awaiting while holding lock.
        Steps:
          - mark joining->False and maybe add bot as player under lock
          - release lock, get starting_word (DB)
          - re-acquire lock, set starting_word and index
          - outside lock: send/edit messages and collect original response as game_message, then set it under lock
        """
        lock = self.get_lock(game.channel_id)
        # initial mutate under lock
        async with lock:
            game.is_joining = False  # FIX: This is the main bug fix - set is_joining to False FIRST
            game.is_active = True
            try:
                if game.join_timeout_task and not game.join_timeout_task.done():
                    game.join_timeout_task.cancel()
            except Exception:
                pass

            if len(game.players) == 1:
                # add bot to make at least 2 players (human + bot)
                game.players.append(self.bot.user.id)
                game.scores[self.bot.user.id] = 0
                game.passes[self.bot.user.id] = 0
                game.rolls[self.bot.user.id] = 0

            # snapshot lang for DB call
            lang_snapshot = game.lang

        # DB call outside lock
        starting_word = await self.get_random_word(lang=lang_snapshot)
        if not starting_word:
            try:
                await interaction.response.send_message("Error: Tidak bisa mendapatkan kata dari database!", ephemeral=True)
            except Exception:
                logger.exception("Failed to notify DB error on start_game")
            await self.cleanup_game(game.channel_id)
            return

        # apply starting word under lock
        async with lock:
            game.current_word = starting_word
            if game.lang == "eng":
                game.current_suffixes = self.get_suffixes(starting_word)
                game.current_suffix = game.current_suffixes[0] if game.current_suffixes else ""
            else:
                game.current_suffix = self.get_suffix(starting_word, game.lang)
                game.current_suffixes = []
            game.used_words.add(starting_word)
            game.current_player_index = random.randint(0, len(game.players) - 1)

            embed = self.create_game_embed(game)

        try:
            await interaction.response.edit_message(embed=embed, view=None)
        except Exception:
            try:
                await interaction.followup.send(embed=embed)
            except Exception:
                logger.exception("Failed to announce game start")

        # try to capture original response as game_message; set under lock
        new_msg = None
        try:
            new_msg = await interaction.original_response()
        except Exception:
            channel = self.bot.get_channel(game.channel_id)
            if channel:
                try:
                    new_msg = await channel.send(embed=embed)
                except Exception:
                    new_msg = None

        async with lock:
            if new_msg:
                game.game_message = new_msg

        async with lock:
            # FIX: Add bounds checking
            if game.current_player_index >= len(game.players):
                game.current_player_index = 0
            next_is_bot = (game.players and game.current_player_index < len(game.players) and game.players[game.current_player_index] == self.bot.user.id)
        if next_is_bot:
            asyncio.create_task(self.handle_bot_turn(game))
        else:
            await self.start_turn_timeout(game)

    async def start_turn_timeout(self, game: WordChainGame):
        lock = self.get_lock(game.channel_id)
        async with lock:
            try:
                if game.turn_timeout_task and not game.turn_timeout_task.done():
                    game.turn_timeout_task.cancel()
            except Exception:
                pass

            # FIX: Add bounds checking
            if not game.players or game.current_player_index >= len(game.players):
                if game.players:
                    game.current_player_index = 0
                else:
                    return

            expected_player_id = game.players[game.current_player_index]
            # schedule handler
            game.turn_timeout_task = asyncio.create_task(self.turn_timeout_handler(game, expected_player_id))

    async def turn_timeout_handler(self, game: WordChainGame, expected_player_id: int):
        try:
            await asyncio.sleep(self.TURN_TIMEOUT_SECONDS)
            async with self.get_lock(game.channel_id):
                if not game.is_active:
                    return
                # FIX: Add bounds checking
                if game.current_player_index >= len(game.players):
                    game.current_player_index = 0
                still_has_turn = (
                    game.players
                    and expected_player_id in game.players
                    and game.current_player_index < len(game.players)
                    and game.players[game.current_player_index] == expected_player_id
                )
            if still_has_turn:
                asyncio.create_task(self.eliminate_player(game, expected_player_id, "waktu habis"))
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Error in turn_timeout_handler")

    async def eliminate_player(self, game: WordChainGame, player_id: int, reason: str):
        """
        Eliminate a player: acquire lock internally (callers should use create_task if holding lock).
        Do minimal state changes under lock, perform I/O outside lock.
        """
        lock = self.get_lock(game.channel_id)
        # prepare info
        notify_text = None
        proceed_endgame = False

        async with lock:
            if player_id not in game.players:
                return
            # cancel turn timeout safely
            try:
                if game.turn_timeout_task and not game.turn_timeout_task.done():
                    game.turn_timeout_task.cancel()
            except Exception:
                pass

            try:
                eliminated_index = game.players.index(player_id)
            except ValueError:
                return

            # remove player
            game.players.remove(player_id)

            # adjust current_player_index
            if eliminated_index < game.current_player_index:
                game.current_player_index = max(0, game.current_player_index - 1)
            elif eliminated_index == game.current_player_index:
                if game.current_player_index >= len(game.players):
                    game.current_player_index = 0

            # prepare notification text
            if player_id == self.bot.user.id:
                notify_text = f"<@{self.bot.user.id}> dieliminasi karena **{reason}**!"
            else:
                notify_text = f"<@{player_id}> dieliminasi karena **{reason}**!"

            # check end conditions and mark flag
            human_players = [p for p in game.players if p != self.bot.user.id]
            if len(human_players) == 0 or len(game.players) <= 1:
                proceed_endgame = True

        # notify outside lock
        channel = self.bot.get_channel(game.channel_id)
        if channel and notify_text:
            try:
                await channel.send(notify_text)
            except Exception:
                logger.exception("Failed to send elimination notice")

        if proceed_endgame:
            # small delay, then end_game (end_game handles cleanup)
            await asyncio.sleep(0.6)
            await self.end_game(game)
            return

        # otherwise continue game
        await self.update_game_message(game)

        async with lock:
            # FIX: Add bounds checking
            if game.current_player_index >= len(game.players):
                game.current_player_index = 0
            next_is_bot = (game.players and game.current_player_index < len(game.players) and game.players[game.current_player_index] == self.bot.user.id)

        if next_is_bot:
            asyncio.create_task(self.handle_bot_turn(game))
        else:
            await self.start_turn_timeout(game)

    async def end_game(self, game: WordChainGame):
        """
        End the game and show results:
         - capture state under lock (no awaits inside lock)
         - perform DB updates & sending outside lock
         - always call cleanup_game at the end
        """
        cleanup_channel_id = game.channel_id
        db_updates: List[Tuple[int, int, int, bool]] = []
        embed = None
        winner_id = None
        try:
            async with self.get_lock(game.channel_id):
                # mark inactive & cancel timeout
                game.is_active = False
                try:
                    if game.turn_timeout_task and not game.turn_timeout_task.done():
                        game.turn_timeout_task.cancel()
                except Exception:
                    pass

                channel = self.bot.get_channel(game.channel_id)

                human_players = [p for p in game.players if p != self.bot.user.id]
                if len(human_players) == 0:
                    winner_id = self.bot.user.id
                elif game.players:
                    winner_id = game.players[0]
                else:
                    if game.scores:
                        winner_id = max(game.scores.items(), key=lambda x: x[1])[0]

                guild_id = channel.guild.id if channel and hasattr(channel, 'guild') and channel.guild else 0
                for player_id in list(game.scores.keys()):
                    if player_id != self.bot.user.id:
                        points_earned = game.scores.get(player_id, 0)
                        is_winner = (player_id == winner_id)
                        db_updates.append((player_id, guild_id, points_earned, is_winner))

                embed = discord.Embed(title="🏆 Game Selesai!", color=0xffd700)
                if winner_id and winner_id in game.scores:
                    winner_score = game.scores.get(winner_id, 0)
                    if winner_id == self.bot.user.id:
                        embed.description = f"Pemenang: <@{self.bot.user.id}>\nSkor: {winner_score} poin"
                    else:
                        embed.description = f"Pemenang: <@{winner_id}>\nSkor: {winner_score} poin"
                else:
                    embed.description = "Tidak ada pemenang!"
                    embed.color = 0x808080

                if len(game.scores) > 0:
                    sorted_scores = sorted(game.scores.items(), key=lambda x: x[1], reverse=True)
                    score_text = []
                    for i, (player_id, score) in enumerate(sorted_scores[:10], 1):
                        score_text.append(f"{i}. <@{player_id}>: {score} poin")
                    embed.add_field(name="Papan Skor", value="\n".join(score_text), inline=False)

                embed.add_field(name="Total Kata Terpakai", value=f"{len(game.used_words)}", inline=True)
        except Exception:
            logger.exception("Unexpected error in end_game (snapshot)")

        # DB updates outside lock
        for (player_id, guild_id, points_earned, is_winner) in db_updates:
            try:
                await DBHandler.update_player_stats(player_id, guild_id, points_earned, is_winner)
            except Exception:
                logger.exception("Error updating stats for %s", player_id)

        # send embed outside lock
        try:
            channel = self.bot.get_channel(cleanup_channel_id)
            if channel and embed:
                await channel.send(embed=embed)
                logger.info("Game ended in channel %s, winner: %s", cleanup_channel_id, winner_id)
        except Exception:
            logger.exception("Error sending end game message")

        try:
            await asyncio.sleep(0.6)
        except Exception:
            pass

        try:
            await self.cleanup_game(cleanup_channel_id)
        except Exception:
            logger.exception("Error calling cleanup_game in finally for %s", cleanup_channel_id)

    def word_starts_with_any_suffix(self, word: str, suffixes: List[str]) -> bool:
        word_lower = word.lower()
        return any(word_lower.startswith(suffix.lower()) for suffix in suffixes)

    # Commands & listeners
    @commands.hybrid_command(name="sambungkata", aliases=["sk"], description="Mulai permainan Sambung Kata")
    @check_master_channel()
    async def word_chain(self, ctx: commands.Context):
        channel_id = ctx.channel.id
        if channel_id in self.games:
            await ctx.send("Sudah ada game yang sedang berlangsung di channel ini!")
            return

        game = WordChainGame(channel_id, ctx.author.id)
        self.games[channel_id] = game

        embed = self.create_join_embed(game)
        view = JoinGameView(self, game)

        try:
            message = await ctx.send(embed=embed, view=view)
            game.join_message = message
            # start join timeout handler task
            game.join_timeout_task = asyncio.create_task(self._join_timeout_handler(game, timeout=120))
        except Exception:
            logger.exception("Error sending join message")
            await self.cleanup_game(channel_id)
            await ctx.send("Terjadi error saat membuat game!")
            return

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # ignore bots and DMs
        if message.author.bot:
            return
        if isinstance(message.channel, discord.DMChannel):
            return

        channel_id = message.channel.id
        if channel_id not in self.games:
            return

        game = self.games[channel_id]
        if not game.is_active:
            return

        try:
            await self._handle_game_message(message, game)
        except Exception:
            logger.exception("Error handling game message")

    async def _handle_game_message(self, message: discord.Message, game: WordChainGame):
        lock = self.get_lock(game.channel_id)
        async with lock:
            if not game.players:
                return
            # FIX: Add bounds checking
            if game.current_player_index >= len(game.players):
                game.current_player_index = 0
            expected_player_id = game.players[game.current_player_index]

        if message.author.id != expected_player_id:
            return

        content = message.content.lower().strip()
        if not content:
            return
        channel = message.channel

        # PASS
        if content == "pass":
            player_id = message.author.id
            async with lock:
                current_passes = game.passes.get(player_id, 0)
                if current_passes >= 3:
                    to_eliminate = True
                else:
                    to_eliminate = False
                    game.passes[player_id] = current_passes + 1
                    if game.players:
                        game.current_player_index = (game.current_player_index + 1) % len(game.players)

            if to_eliminate:
                try:
                    await channel.send(f"<@{player_id}> sudah menggunakan semua pass!")
                except Exception:
                    logger.exception("Failed to notify pass exhausted")
                asyncio.create_task(self.eliminate_player(game, player_id, "kehabisan pass"))
                return

            try:
                await channel.send(f"<@{player_id}> pass! ({current_passes + 1}/3)")
            except Exception:
                logger.exception("Failed to announce pass")

            await self.update_game_message(game)

            async with lock:
                # FIX: Add bounds checking
                if game.current_player_index >= len(game.players):
                    game.current_player_index = 0
                next_is_bot = (game.players and game.current_player_index < len(game.players) and game.players[game.current_player_index] == self.bot.user.id)

            if next_is_bot:
                asyncio.create_task(self.handle_bot_turn(game))
            else:
                await self.start_turn_timeout(game)
            return

        # ROLL
        if content == "roll":
            await self.handle_roll(game, message.author.id)
            return

        # word validation & updates
        if not self.is_valid_word_format(content, game.lang):
            try:
                await channel.send("Format kata tidak valid sesuai aturan!")
            except Exception:
                pass
            return

        async with lock:
            if content in game.used_words:
                already_used = True
            else:
                already_used = False
            curr_suffixes = list(game.current_suffixes)
            curr_suffix = game.current_suffix

        if already_used:
            try:
                await channel.send(f"'{content}' sudah digunakan!")
            except Exception:
                pass
            return

        if game.lang == "eng" and curr_suffixes:
            if not self.word_starts_with_any_suffix(content, curr_suffixes):
                suffixes_text = " / ".join([f"`{suffix}`" for suffix in curr_suffixes])
                try:
                    await channel.send(f"Harus dimulai dengan {suffixes_text}!")
                except Exception:
                    pass
                return
        else:
            if curr_suffix and not content.startswith(curr_suffix.lower()):
                try:
                    await channel.send(f"Harus dimulai dengan `{curr_suffix}`!")
                except Exception:
                    pass
                return

        is_valid = await self.validate_word(content, lang=game.lang)
        if not is_valid:
            try:
                await channel.send("Kata tidak ditemukan!")
            except Exception:
                pass
            return

        async with lock:
            # FIX: Add bounds checking and ensure it's still the author's turn
            if not game.players or game.current_player_index >= len(game.players):
                return
            if game.players[game.current_player_index] != message.author.id:
                return
            try:
                if game.turn_timeout_task and not game.turn_timeout_task.done():
                    game.turn_timeout_task.cancel()
            except Exception:
                pass

            game.current_word = content
            if game.lang == "eng":
                game.current_suffixes = self.get_suffixes(content)
                game.current_suffix = game.current_suffixes[0] if game.current_suffixes else ""
            else:
                game.current_suffix = self.get_suffix(content, game.lang)
                game.current_suffixes = []
            game.used_words.add(content)

            player_id = message.author.id
            game.scores[player_id] = game.scores.get(player_id, 0) + len(content)

            if game.players:
                game.current_player_index = (game.current_player_index + 1) % len(game.players)

        await self.update_game_message(game)

        async with lock:
            # FIX: Add bounds checking
            if game.current_player_index >= len(game.players):
                game.current_player_index = 0
            next_is_bot = (game.players and game.current_player_index < len(game.players) and game.players[game.current_player_index] == self.bot.user.id)

        if next_is_bot:
            asyncio.create_task(self.handle_bot_turn(game))
        else:
            await self.start_turn_timeout(game)

    def cog_unload(self):
        for channel_id in list(self.games.keys()):
            # schedule cleanup tasks
            try:
                asyncio.create_task(self.cleanup_game(channel_id))
            except Exception:
                logger.exception("Failed scheduling cleanup in cog_unload for %s", channel_id)


async def setup(bot):
    await bot.add_cog(WordChainCog(bot))