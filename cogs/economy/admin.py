# cogs/economy/admin.py

import discord

from discord.ext import commands
from services import economy

class EconomyAdmin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
    @commands.is_owner()
    @commands.command(name="addcash")
    async def addcash(self, ctx: commands.Context, member: discord.Member = None, amount: int = None):
        """Tambah saldo ke member (owner only)"""
        if member is None or amount is None:
            return await ctx.reply("❌ Format: `!addcash @user jumlah`")

        # panggil service adjust_balance dengan amount positif
        new_balance = await economy.adjust_balance(ctx.guild.id, member.id, abs(int(amount)), username=str(ctx.author), reason="Dikasih admin")
        if new_balance is None:
            return await ctx.reply("User tidak ditemukan")

        await ctx.reply(
            embed=discord.Embed(
                title="💰 Saldo Ditambahkan",
                description=f"Berhasil menambahkan `{amount:,}` vcash ke {member.mention}\n",
                color=discord.Color.green()
            )
        )

    @commands.is_owner()
    @commands.command(name="denda")
    async def denda(self, ctx: commands.Context, member: discord.Member = None, amount: int = None):
        """Kurangi saldo member (owner only)"""
        if member is None or amount is None:
            return await ctx.reply("❌ Format: `!denda @user jumlah`")

        # panggil service adjust_balance dengan amount negatif (debit)
        new_balance = await economy.adjust_balance(ctx.guild.id, member.id, -abs(int(amount)), username=str(ctx.author), reason="Didenda admin")
        if new_balance is None:
            return await ctx.reply("User tidak ditemukan atau saldo tidak mencukupi")

        await ctx.reply(
            embed=discord.Embed(
                title="💰 Saldo Dikurangi",
                description=f"Berhasil mengurangi `{amount:,}` vcash - {member.mention}\n",
                color=discord.Color.green()
            )
        )
        
async def setup(bot):
    await bot.add_cog(EconomyAdmin(bot))
