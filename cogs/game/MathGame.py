import discord
from discord.ext import commands
import random
import asyncio
from typing import Dict, Optional, Any, List
import logging

from utils.decorator.channel import check_master_channel

log = logging.getLogger(__name__)
# Toggle debug display of hidden numbers (set False when not debugging)
DEBUG_SHOW_HIDDEN = False

class MathGameView(discord.ui.View):
    def __init__(self, cog, channel):
        super().__init__(timeout=300)  # 5 minutes untuk auto-start UI (tetap)
        self.cog = cog
        self.channel = channel
        self.difficulty = "easy"
        self.players = set()
        self.game_started = False

    def update_embed(self):
        difficulty_colors = {
            "easy": 0x00ff00,
            "medium": 0xffaa00,
            "hard": 0xff6600,
            "extreme": 0xff0000
        }

        embed = discord.Embed(
            title="Math Game",
            description=f"**Mode:** {self.difficulty.title()}\n"
                        f"**Players:** {len(self.players)}\n\n",
            color=difficulty_colors.get(self.difficulty, 0x00ff00)
        )

        if self.players:
            player_list = []
            for i, player_id in enumerate(list(self.players)[:10], 1):
                player_list.append(f"{i}. <@{player_id}>")
            embed.add_field(
                name="Joined:",
                value="\n".join(player_list) if player_list else "None",
                inline=False
            )

        difficulty_info = {
            "easy": "Numbers: 1-100 | Operations: (+, -, ×)",
            "medium": "Numbers: 100-1000 | Operations: (+, -, ×, ÷)",
            "hard": "Numbers: 1-100 | Operations: (+, -) | 4 numbers (3 ops)",
            "extreme": "Numbers: 1-100 | Operations: (+, -) | 5 numbers (4 ops) dengan beberapa angka hilang"
        }

        embed.add_field(
            name="Mode Info:",
            value=difficulty_info[self.difficulty],
            inline=False
        )

        embed.set_footer(text="Game will auto-start in 5 minutes or when Start Game is pressed")
        return embed

    async def on_timeout(self):
        """Handle view timeout - auto-start game if players exist"""
        try:
            if not self.game_started and len(self.players) >= 1:
                # Auto-start the game
                self.game_started = True
                
                # Create session game dan simpan aktif
                game = self.cog.GameSession(self.channel, self.difficulty)
                for player_id in self.players:
                    game.add_player(player_id)
                self.cog.active_games[self.channel.id] = game

                embed = discord.Embed(
                    title="Game Auto-Started!",
                    description=f"**Mode:** {self.difficulty.title()}\n"
                                f"**Players:** {len(self.players)}\n\n"
                                f"Get ready for the first question...",
                    color=0x00ff00
                )

                # Try to find the original message to edit it
                # This might fail if the message was deleted, but we'll try
                try:
                    # We need to find a way to get the original message
                    # Since we don't store it, we'll send a new message
                    await self.channel.send(embed=embed)
                except Exception as e:
                    log.error(f"Failed to send auto-start message: {e}")

                # Start the game
                await asyncio.sleep(1)
                await self.cog.send_question(game)
        except Exception as e:
            log.error(f"Error in view timeout: {e}")

    @discord.ui.button(label='', style=discord.ButtonStyle.green, emoji='➕')
    async def join_game(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.game_started:
            await interaction.response.send_message("❌ Game already started!", ephemeral=True)
            return

        if interaction.user.id in self.players:
            await interaction.response.send_message("❌ You're already in the game!", ephemeral=True)
            return

        self.players.add(interaction.user.id)
        embed = self.update_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label='', style=discord.ButtonStyle.danger, emoji='➖')
    async def leave_game(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.game_started:
            await interaction.response.send_message("❌ Game already started!", ephemeral=True)
            return

        if interaction.user.id not in self.players:
            await interaction.response.send_message("❌ You're not in the game!", ephemeral=True)
            return

        self.players.remove(interaction.user.id)
        embed = self.update_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label='Easy', style=discord.ButtonStyle.success, emoji='🟢')
    async def toggle_difficulty(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.game_started:
            await interaction.response.send_message("❌ Cannot change difficulty after game started!", ephemeral=True)
            return

        difficulty_cycle = ["easy", "medium", "hard", "extreme"]
        current_index = difficulty_cycle.index(self.difficulty)
        next_index = (current_index + 1) % len(difficulty_cycle)
        self.difficulty = difficulty_cycle[next_index]

        difficulty_info = {
            "easy": ("Easy", discord.ButtonStyle.success, "🟢"),
            "medium": ("Medium", discord.ButtonStyle.secondary, "🟠"),
            "hard": ("Hard", discord.ButtonStyle.primary, "🔵"),
            "extreme": ("Extreme", discord.ButtonStyle.danger, "🔴")
        }

        label, style, emoji = difficulty_info[self.difficulty]
        button.label = label
        button.style = style
        button.emoji = emoji

        embed = self.update_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label='Start', style=discord.ButtonStyle.success)
    async def start_game(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.game_started:
            await interaction.response.send_message("❌ Game already started!", ephemeral=True)
            return

        if len(self.players) < 1:
            await interaction.response.send_message("❌ Need at least 1 player to start!", ephemeral=True)
            return

        self.game_started = True

        # Buat session game dan simpan aktif
        game = self.cog.GameSession(self.channel, self.difficulty)
        for player_id in self.players:
            game.add_player(player_id)
        self.cog.active_games[self.channel.id] = game

        embed = discord.Embed(
            title="Game Started!",
            description=f"**Mode:** {self.difficulty.title()}\n"
                        f"**Players:** {len(self.players)}\n\n"
                        f"Get ready for the first question...",
            color=0x00ff00
        )

        # EDIT pesan interaksi: kirim embed baru DAN hapus view (view=None) supaya tombol menghilang
        await interaction.response.edit_message(embed=embed, view=None)

        # Hentikan view agar tidak menerima interaction lagi dan dibersihkan
        try:
            self.stop()
        except Exception:
            log.exception("Failed to stop MathGameView")

        # Beri jeda singkat lalu mulai soal pertama
        await asyncio.sleep(1)
        await self.cog.send_question(game)

    @discord.ui.button(label='Cancel', style=discord.ButtonStyle.danger)
    async def cancel_game(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.game_started:
            await interaction.response.send_message("❌ Cannot cancel after game started!", ephemeral=True)
            return

        embed = discord.Embed(
            title="❌ Game Cancelled",
            description="The math game has been cancelled.",
            color=0xff0000
        )

        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

class MathGame(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # store active games by channel id
        self.active_games: Dict[int, 'GameSession'] = {}
        # store the last question message object per channel for fast edit/reaction
        self.question_messages: Dict[int, discord.Message] = {}

    class GameSession:
        def __init__(self, channel, difficulty):
            self.channel = channel
            self.difficulty = difficulty
            self.players: Dict[int, int] = {}  # user_id -> points
            self.current_question: Optional[str] = None
            self.current_answer: Optional[Any] = None  # int or metadata dict(for extreme)
            self.game_active = True
            self.waiting_for_answer = False
            self.win_threshold = 10
            self.question_number = 0
            self.lock = asyncio.Lock()
            # event used to reset timeout when someone answers correctly
            self.answer_event: asyncio.Event = asyncio.Event()
            # persistent timeout manager task (one per game)
            self.timeout_manager_task: Optional[asyncio.Task] = None

        def add_player(self, user_id: int):
            if user_id not in self.players:
                self.players[user_id] = 0
                return True
            return False

        def add_point(self, user_id: int):
            if user_id in self.players:
                self.players[user_id] += 1
                return self.players[user_id]
            return 0

        def get_leaderboard(self):
            return sorted(self.players.items(), key=lambda x: x[1], reverse=True)

        def check_winner(self):
            for user_id, points in self.players.items():
                if points >= self.win_threshold:
                    return user_id
            return None

    def _evaluate_tokens_left_to_right(self, tokens: List[str]) -> int:
        if not tokens:
            return 0
        
        res = int(tokens[0])
        for i in range(1, len(tokens), 2):
            if i + 1 >= len(tokens):
                break
            op = tokens[i]
            n = int(tokens[i+1])
            if op == "+":
                res += n
            elif op == "-":
                res -= n
        return res

    def generate_math_problem(self, difficulty: str):
        # Use only + and - for hard/extreme; other modes keep previous behavior
        if difficulty == "easy":
            num1 = random.randint(1, 100)
            num2 = random.randint(1, 100)
            op = random.choice(["+", "-", "*"])

            if op == "+":
                answer = num1 + num2
            elif op == "-":
                if num1 < num2:
                    num1, num2 = num2, num1
                answer = num1 - num2
            else:  # multiplication
                num1 = random.randint(1, 20)
                num2 = random.randint(1, 20)
                answer = num1 * num2

            question = f"{num1} {op} {num2} = ?"
            return question, int(round(answer))

        elif difficulty == "medium":
            num1 = random.randint(100, 500)
            num2 = random.randint(100, 500)
            op = random.choice(["+", "-", "*", "/"])

            if op == "+":
                answer = num1 + num2
            elif op == "-":
                if num1 < num2:
                    num1, num2 = num2, num1
                answer = num1 - num2
            elif op == "*":
                num1 = random.randint(100, 200)
                num2 = random.randint(2, 10)
                answer = num1 * num2
            else:  # division - ensure clean division
                divisor = random.randint(2, 20)
                answer = random.randint(50, 200)
                num1 = answer * divisor
                num2 = divisor
                # Make sure division is clean
                answer = num1 // num2

            question = f"{num1} {op} {num2} = ?"
            return question, int(round(answer))

        elif difficulty == "hard":
            # Perubahan: range 1-100, 4 angka, operasinya random banyak tapi tanpa * or /
            nums = [random.randint(1, 100) for _ in range(4)]
            ops = [random.choice(["+", "-"]) for _ in range(3)]
            # build tokens like ['12','+','5','-','3','+','88']
            tokens = []
            for i in range(4):
                tokens.append(str(nums[i]))
                if i < 3:
                    tokens.append(ops[i])

            # compute result (left-to-right)
            result = self._evaluate_tokens_left_to_right(tokens)

            question = " ".join(tokens) + " = ?"
            return question, result

        else:  # extreme (Opsi 2: accept any numbers that satisfy equation)
            # Perubahan: range 1-100, 5 angka, ops only +/-
            nums = [random.randint(1, 100) for _ in range(5)]
            ops = [random.choice(["+", "-"]) for _ in range(4)]
            # tokens positions: 0(num),1(op),2(num),3(op),4(num),5(op),6(num),7(op),8(num)
            tokens = []
            for i in range(5):
                tokens.append(str(nums[i]))
                if i < 4:
                    tokens.append(ops[i])

            # compute final answer left-to-right
            final = self._evaluate_tokens_left_to_right(tokens)

            # choose random NUMBER positions to hide (1 to 3 numbers)
            number_positions = [0, 2, 4, 6, 8]  # indices of numbers in tokens
            hide_num_count = random.randint(1, 3)
            hide_number_positions = sorted(random.sample(number_positions, hide_num_count))

            display_tokens = []
            hidden_numbers = []
            for idx, tok in enumerate(tokens):
                if idx in hide_number_positions:
                    display_tokens.append("...")
                    hidden_numbers.append(tok)  # store only numbers (strings)
                else:
                    display_tokens.append(tok)

            # Create display like "10 ... 9 + 89 ... - 100 = <final>"
            question = " ".join(display_tokens) + f" = {final}"
            # Metadata for game.current_answer
            metadata = {
                "hidden_numbers": hidden_numbers,         # original hidden numbers (for debug)
                "hidden_positions": hide_number_positions,# [indices]
                "tokens": tokens,                         # full token list (strings)
                "final": final                            # integer result
            }
            # log for debugging
            log.info(f"[ MathGame:EXTREME ] Hidden numbers: {hidden_numbers}  (positions: {hide_number_positions})")
            # Instruction for user clarifying expected format
            return question, metadata

    @commands.command(name="math")
    @check_master_channel()
    async def create_math_game(self, ctx):
        if ctx.channel.id in self.active_games:
            await ctx.send("❌ A game is already active in this channel! Wait for it to finish.")
            return
        
        guild_name = ctx.guild.name
        username = ctx.author.display_name
        
        log.info(f"[ COMMAND CALL ] --------- [ Math ] -- From {guild_name} | {username}")

        view = MathGameView(self, ctx.channel)
        view.players.add(ctx.author.id)  # Auto-add command user

        embed = view.update_embed()
        await ctx.send(embed=embed, view=view)

    async def send_question(self, game: 'GameSession'):
        # If game already stopped, do nothing
        if not game.game_active:
            return

        game.question_number += 1
        question, answer = self.generate_math_problem(game.difficulty)
        game.current_question = question
        game.current_answer = answer
        game.waiting_for_answer = True

        # Reset the answer_event so timeout manager starts waiting again
        try:
            game.answer_event.clear()
        except Exception:
            game.answer_event = asyncio.Event()

        difficulty_colors = {
            "easy": 0x00ff00,
            "medium": 0xffaa00,
            "hard": 0xff6600,
            "extreme": 0xff0000
        }

        # Show question in bold/large style as requested
        embed = discord.Embed(
            title=f"Question #{game.question_number} ({game.difficulty.title()})",
            description=f"## {question}",
            color=difficulty_colors.get(game.difficulty, 0x00ff00)
        )

        # If debugging, print hidden numbers in embed (and already logged in generate_math_problem)
        if game.difficulty == "extreme" and DEBUG_SHOW_HIDDEN:
            try:
                # Show original hidden numbers (may be useful during dev). It's safe because DEBUG_SHOW_HIDDEN controls it.
                hidden = game.current_answer.get("hidden_numbers") if isinstance(game.current_answer, dict) else str(game.current_answer)
                embed.add_field(name="DEBUG Hidden Numbers", value=str(hidden), inline=False)
            except Exception:
                log.exception("Failed to add DEBUG field for hidden numbers")

        # Show current leaderboard
        leaderboard = game.get_leaderboard()
        if leaderboard:
            leaderboard_text = ""
            for i, (user_id, points) in enumerate(leaderboard[:5]):
                leaderboard_text += f"<@{user_id}>: **{points}**/{game.win_threshold} pts\n"
            embed.add_field(name="Scores:", value=leaderboard_text, inline=False)

        if game.difficulty == "extreme":
            embed.set_footer(text="Ketik hanya ANGKA yang hilang (dari kiri), dipisah spasi. Contoh: 10 5")
        else:
            embed.set_footer(text="Jawaban benar pertama +1 point.")

        # Delete previous question message if exists (we store message object)
        if game.channel.id in self.question_messages:
            try:
                old_msg = self.question_messages[game.channel.id]
                await old_msg.delete()
            except discord.NotFound:
                pass  # Message was already deleted
            except Exception as e:
                log.error(f"Failed to delete previous question message: {e}")

        # Send new question and store message object for quick edits/reactions
        try:
            message = await game.channel.send(embed=embed)
            self.question_messages[game.channel.id] = message
        except Exception as e:
            log.error(f"Failed to send question: {e}")
            return

        # Start the persistent timeout manager task if not running
        if not game.timeout_manager_task or game.timeout_manager_task.done():
            game.timeout_manager_task = asyncio.create_task(self._timeout_manager(game, 300))

    async def _timeout_manager(self, game: 'GameSession', timeout_seconds: int):
        """
        Persistent manager: waits for answer_event or timeout.
        If timeout occurs and still waiting, end the whole game (per user request).
        """
        try:
            while game.game_active:
                try:
                    await asyncio.wait_for(game.answer_event.wait(), timeout_seconds)
                    game.answer_event.clear()
                    continue
                except asyncio.TimeoutError:
                    async with game.lock:
                        if not game.waiting_for_answer or not game.game_active:
                            continue

                        game.waiting_for_answer = False

                        try:
                            msg = self.question_messages.get(game.channel.id)
                            if msg:
                                try:
                                    await msg.add_reaction("⌛")
                                except Exception:
                                    pass

                                embed = discord.Embed(
                                    title=f"Question #{game.question_number} ({game.difficulty.title()})",
                                    description=f"## {game.current_question}",
                                    color=0xffaa00
                                )

                                leaderboard = game.get_leaderboard()
                                if leaderboard:
                                    leaderboard_text = ""
                                    for i, (user_id, points) in enumerate(leaderboard[:5], 1):
                                        leaderboard_text += f"{i}. <@{user_id}>: **{points}**/{game.win_threshold} pts\n"
                                    embed.add_field(name="Leaderboard:", value=leaderboard_text, inline=False)

                                embed.add_field(
                                    name="Timed out:",
                                    value="No one answered within 5 minutes. The game has been ended and cleared.",
                                    inline=False
                                )
                                embed.set_footer(text="Use !math to start a new game.")
                                await msg.edit(embed=embed)
                        except Exception as e:
                            log.error(f"Failed to mark question as timed out: {e}")

                    # End the game completely (don't send next question)
                    try:
                        await self.end_game(game, winner_id=None, timed_out=True)
                    except Exception as e:
                        log.error(f"Error while ending game after timeout: {e}")
                    return
        except asyncio.CancelledError:
            return
        except Exception as e:
            log.error(f"Unexpected error in timeout_manager: {e}")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        channel_id = message.channel.id
        if channel_id not in self.active_games:
            return

        game = self.active_games[channel_id]

        if not game.waiting_for_answer or message.author.id not in game.players:
            return

        # Use lock to avoid race conditions
        async with game.lock:
            if not game.waiting_for_answer:
                return

            # If extreme mode, accept ANY numbers that after substitution make the expression equal final
            if game.difficulty == "extreme":
                user_content = " ".join(message.content.strip().split())  # normalize spaces
                if not user_content:
                    return

                # Basic allowed chars: digits, spaces, + and - sign for negative numbers (we accept ints)
                if any(ch not in "0123456789 -+" for ch in user_content):
                    return

                # parse submitted numbers
                parts = user_content.split()
                # game.current_answer is metadata dict
                if not isinstance(game.current_answer, dict):
                    # defensive fallback: ignore
                    return

                meta = game.current_answer
                hide_positions = meta["hidden_positions"]
                tokens = list(meta["tokens"])  # copy
                final = int(meta["final"])

                # require same count as hidden
                if len(parts) != len(hide_positions):
                    return

                # ---- NEW VALIDATION: parse ints, disallow 0 and duplicates ----
                try:
                    # Parse to ints (allow negative)
                    user_nums_int = [int(p) for p in parts]
                except ValueError:
                    return

                # Disallow any zero
                if any(n == 0 for n in user_nums_int):
                    try:
                        await message.add_reaction("❌")
                    except Exception:
                        pass
                    return

                # Disallow duplicates within this single answer
                if len(set(user_nums_int)) != len(user_nums_int):
                    try:
                        await message.add_reaction("❌")
                    except Exception:
                        pass
                    return
                # ------------------------------------------------------------

                # substitute into tokens copy (store as strings)
                for pos, val in zip(hide_positions, user_nums_int):
                    tokens[pos] = str(val)

                # evaluate left-to-right
                try:
                    calc = self._evaluate_tokens_left_to_right(tokens)
                except Exception:
                    return

                if calc != final:
                    return  # wrong

            else:
                # numerical modes
                try:
                    user_answer = int(round(float(message.content.strip())))
                except ValueError:
                    return  # ignore non-numeric messages silently
                except Exception as e:
                    log.error(f"Error parsing answer: {e}")
                    return

                if user_answer != game.current_answer:
                    return  # wrong answer

            # Correct answer
            game.waiting_for_answer = False

            # Signal timeout manager to reset (do NOT cancel it)
            try:
                game.answer_event.set()
            except Exception as e:
                log.error(f"Error setting answer event: {e}")

            points = game.add_point(message.author.id)

            # Update the question message quickly (we have the message object)
            try:
                q_msg = self.question_messages.get(channel_id)
                if q_msg:
                    try:
                        await q_msg.add_reaction("✅")
                    except Exception:
                        pass

                    difficulty_colors = {
                        "easy": 0x00ff00,
                        "medium": 0xffaa00,
                        "hard": 0xff6600,
                        "extreme": 0xff0000
                    }

                    embed = discord.Embed(
                        title=f"Question #{game.question_number} ({game.difficulty.title()})",
                        description=f"## {game.current_question}",
                        color=difficulty_colors.get(game.difficulty, 0x00ff00)
                    )

                    # show debug hidden numbers after solved (if enabled)
                    if game.difficulty == "extreme" and DEBUG_SHOW_HIDDEN:
                        try:
                            hidden = game.current_answer.get("hidden_numbers") if isinstance(game.current_answer, dict) else str(game.current_answer)
                            embed.add_field(name="DEBUG Hidden Numbers", value=str(hidden), inline=False)
                        except Exception:
                            pass

                    leaderboard = game.get_leaderboard()
                    if leaderboard:
                        leaderboard_text = ""
                        for i, (user_id, point_count) in enumerate(leaderboard[:5], 1):
                            leaderboard_text += f"{i}. <@{user_id}>: **{point_count}**/{game.win_threshold} pts\n"
                        embed.add_field(name="Leaderboard:", value=leaderboard_text, inline=False)

                    embed.add_field(
                        name="Solved by:",
                        value=f"{message.author.mention} — +1 point (total {points}/{game.win_threshold})",
                        inline=False
                    )
                    embed.set_footer(text="Type your answer as specified in the question! First correct answer wins 1 point.")
                    await q_msg.edit(embed=embed)
            except Exception as e:
                log.error(f"Failed to update question message after correct answer: {e}")

            # Check winner
            winner = game.check_winner()
            if winner:
                await asyncio.sleep(0.3)
                await self.end_game(game, winner_id=winner)
                return

            # Small delay then send next question (manager will also be waiting/reset via event)
            await asyncio.sleep(0.3)
            await self.send_question(game)


    async def end_game(self, game: 'GameSession', winner_id: Optional[int] = None, timed_out: bool = False):
        """
        Ends the game, sends final embed.
        If winner_id is None and timed_out==True -> ended because of timeout.
        """
        # Mark inactive first to prevent other coroutines from continuing the game
        game.game_active = False
        game.waiting_for_answer = False

        # Cancel timeout manager if it's a different task (if it's the same current task, skip)
        try:
            t = game.timeout_manager_task
            current = asyncio.current_task()
            if t and not t.done() and t is not current:
                t.cancel()
        except Exception as e:
            log.error(f"Error canceling timeout manager task: {e}")

        leaderboard = game.get_leaderboard()

        if timed_out and winner_id is None:
            title = "⏰ Game Timed Out"
            description = "Math game dihentikan karena tidak ada respon dalam 5 menit!"
            color = 0xff5555
        elif winner_id:
            title = "🏆 GAME OVER!"
            description = f"🏆 **WINNER:** <@{winner_id}> with {game.players.get(winner_id, 0)} points!"
            color = 0xffd700
        else:
            title = "GAME ENDED"
            description = "The game has been ended."
            color = 0xcccccc

        embed = discord.Embed(
            title=title,
            description=description,
            color=color
        )

        if leaderboard:
            leaderboard_text = ""
            for i, (user_id, points) in enumerate(leaderboard, 1):
                leaderboard_text += f"{i}. <@{user_id}>: **{points}** points\n"
            embed.add_field(name="🏆 Final Rankings:", value=leaderboard_text, inline=False)

        embed.add_field(
            name="Game Stats:",
            value=f"**Mode:** {game.difficulty.title()}\n"
                  f"**Questions:** {game.question_number}\n"
                  f"**Players:** {len(game.players)}",
            inline=False
        )

        if timed_out:
            embed.set_footer(text="Game ended due to inactivity. Use !math to start a new game.")
        else:
            embed.set_footer(text="Thanks for playing! Use !math to start a new game.")

        # Delete question message if exists
        if game.channel.id in self.question_messages:
            try:
                q_msg = self.question_messages[game.channel.id]
                await q_msg.delete()
            except discord.NotFound:
                pass  # Message was already deleted
            except Exception as e:
                log.error(f"Error deleting question message: {e}")
            finally:
                del self.question_messages[game.channel.id]

        try:
            await game.channel.send(embed=embed)
        except Exception as e:
            log.error(f"Error sending game over message: {e}")

        # Remove from active games
        if game.channel.id in self.active_games:
            del self.active_games[game.channel.id]


async def setup(bot):
    await bot.add_cog(MathGame(bot))