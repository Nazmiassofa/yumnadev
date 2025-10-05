import discord
import json
import logging
import asyncio

from discord.ext import commands
from utils.helper.economy import xp_for_level

from utils.decorator.spender import requires_balance

from utils.time import get_current_date_uptime
from services import economy

from utils.data.emot import (LEFTSWIPE,
                             RIGHTSWIPE,
                             WHITELINE
                             )

log = logging.getLogger(__name__)

class Economy(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="profile")
    async def get_all_stats(self, ctx: commands.Context):
        guild_id = ctx.guild.id
        user = ctx.author
        user_id = user.id
        username = str(user)

        stats = await economy.get_user(guild_id, user_id, username)
        streak = await economy.get_streaks(guild_id, user_id)

        if user.avatar:
            avatar_url = user.avatar.url
        elif ctx.guild.icon:
            avatar_url = ctx.guild.icon.url
        else:
            avatar_url = ctx.author.default_avatar.url

        current_level = stats["level"]
        current_xp = stats["xp"]

        xp_next_level = xp_for_level(current_level + 1)

        progress = current_xp
        needed = xp_next_level
        percentage = progress / needed if needed > 0 else 1

        bar_length = 20
        filled = int(bar_length * percentage)
        bar = "█" * filled + "░" * (bar_length - filled)

        embed = discord.Embed(
            title=f"{user.display_name}'s Info",
            color=discord.Color.blurple()
        )
        embed.set_thumbnail(url=avatar_url)

        embed.description = (
            f"> Level : {stats['level']}\n"
            f"> {bar}\n> -# {progress}/{needed} XP\n\n"
            
            f"> Stats :\n"
            f"> - vcash boost +{stats['level']}%\n"
            f"> - reduce usage +{stats['level']}%\n\n"

            f"> Streaks :\n"
            f"> - Current Streak: {streak['current_streak'], 0} \n"
            f"> - Longest Streak: {streak['longest_streak'], 0} \n"
        )

        await ctx.send(embed=embed)

        
    @commands.command(name="cash")
    async def get_cash_member(self, ctx: commands.Context):
        guild_id = ctx.guild.id
        user_id = ctx.author.id
        username = str(ctx.author)

        balance = await economy.get_balance(guild_id, user_id)
        
        formatted_balance = "{:,}".format(balance)

        embed = discord.Embed(
            description=(
                f"### **Cash Info**\n"
                f"> ### Balance : `{formatted_balance}` vcash\n"
                f"-# You can earn vcash from voice activity"
                ),
            color=discord.Color.blurple()
        )

        avatar = getattr(ctx.author, "display_avatar", None)
        avatar_url = avatar.url if avatar else (ctx.guild.icon.url if ctx.guild.icon else None)
        if avatar_url:
            embed.set_thumbnail(url=avatar_url)

        await ctx.reply(embed=embed)


    @commands.command(name="sendcash", aliases=["tf"])
    async def transfer_vcash(self, ctx: commands.Context, target: discord.Member = None, amount: int = None):
        guild_id = ctx.guild.id
        sender_id = ctx.author.id
        sender_username = str(ctx.author)
        
        if target is None:
            return await ctx.send(embed=discord.Embed(description="Mention user yang ingin kamu transfer!", color=discord.Color.red()))

        if amount is None:
            return await ctx.send(embed=discord.Embed(description="Masukkan jumlah yang ingin ditransfer!", color=discord.Color.red()))

        if target.bot:
            return await ctx.send(embed=discord.Embed(description="Tidak bisa transfer ke bot!", color=discord.Color.red()))

        if target.id == sender_id:
            return await ctx.send(embed=discord.Embed(description="Tidak bisa transfer ke diri sendiri!", color=discord.Color.red()))

        if amount < 1000:
            return await ctx.send(embed=discord.Embed(description=f"Minimal transfer 1000!", color=discord.Color.red()))

        result = await economy.transfer_balance(
            guild_id, sender_id, sender_username, target.id, str(target), amount
        )

        if result is None:
            return await ctx.reply(embed=discord.Embed(description="Saldo tidak cukup!\n-# biaya admin 50%", color=discord.Color.red()))

        amount_formatted = f"{result['amount']:,}"
        fee_formatted = f"{result['fee']:,}"

        embed = discord.Embed(
            title="💸 Transfer Berhasil",
            description=(
                f"**Jumlah Dikirim:** `{amount_formatted}` vcash\n"
                f"-# **Berhasil transfer ke → {target.mention}**"
            ),
            color=discord.Color.green()
        )
        embed.set_footer(text=f"tax {fee_formatted} (50%)")

        await ctx.reply(embed=embed)
        
    @commands.hybrid_command(name="transactions", aliases=["tx", "history"])
    async def transactions(self, ctx: commands.Context):
        guild_id = ctx.guild.id
        user_id = ctx.author.id
        guild_name = ctx.guild.name
        user_name = ctx.author.display_name
        
        log.info(f"[ COMMAND CALL ] ---- Command [ transactions ] dipanggil : {guild_name} | {user_name}")
        
        def formatter(embed, idx, row):
            try:
                username = row['username']
                amount = row['amount']
                balance_before = row['balance_before']
                balance_after = row['balance_after']
                reason = row['reason']
                tx_type = row['tx_type']
                created_at = row['created_at']
                
                amount_str = f"+{amount:,}" if amount > 0 else f"{amount:,}"
                formatted_date = created_at.strftime("%d/%m/%Y %H:%M")
                
                embed.add_field(
                    name=f"**{formatted_date}**",
                    value=(
                        f"> **{tx_type.title()}**: {reason}\n"
                        f"> **Amount**: **{amount_str}**\n"
                        f"> **Balance**: {balance_before:,} → **{balance_after:,}**"
                    ),
                    inline=False
                )
            except Exception as e:
                log.error(f"Error formatting transaction row: {e}, Row: {row}")
                embed.add_field(
                    name="**Error**",
                    value=f"Error displaying transaction data: {str(e)}",
                    inline=False
                )
        
        await self.paginate_user_transactions(ctx, guild_id, user_id, formatter, user_name)

    async def paginate_user_transactions(self, ctx, guild_id, user_id, formatter, user_name=None):
        """Pagination untuk user transactions dengan service layer"""
        
        DATA_PER_PAGE = 5
        
        left_str = "◀️"
        right_str = "▶️"

        start = 0
        message = None

        while True:
            results = await economy.get_user_transaction_history(guild_id, user_id, DATA_PER_PAGE, start)

            if not results:
                if start == 0:
                    await ctx.send("Tidak ada data transaksi yang ditemukan")
                else:
                    await ctx.send("Tidak ada data untuk halaman selanjutnya")
                break

            embed = discord.Embed(color=discord.Color.blue())
            embed.description = f"{WHITELINE}"
            embed.set_thumbnail(url=ctx.guild.icon.url if ctx.guild.icon else None)
            embed.set_footer(text=f"{ctx.guild.name}")
            # tampilkan username jika ada
            title_user = f" — {user_name}" if user_name else ""
            embed.set_author(name=f"|  {(start // DATA_PER_PAGE) + 1}  |  Trx History{title_user}")

            for idx, row in enumerate(results, start=start + 1):
                formatter(embed, idx, row)

            if not message:
                message = await ctx.send(embed=embed)
                try:
                    await message.add_reaction(left_str)
                    await message.add_reaction(right_str)
                except Exception as e:
                    log.info(f"[ REACTION ERROR ] ------- {e}")
                    return
            else:
                await message.edit(embed=embed)

            def check(reaction, user):
                return (
                    reaction.message.id == message.id
                    and user == ctx.author
                    and str(reaction.emoji) in [left_str, right_str]
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
                try:
                    await reaction.remove(user)
                except Exception:
                    await message.remove_reaction(reaction.emoji, user)
            except Exception:
                pass

            if str(reaction.emoji) == right_str:
                start += DATA_PER_PAGE
            elif str(reaction.emoji) == left_str:
                start = max(0, start - DATA_PER_PAGE)

        
async def setup(bot):
    await bot.add_cog(Economy(bot))
