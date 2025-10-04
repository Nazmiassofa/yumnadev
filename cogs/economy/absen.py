# cogs/economy/absen.py

import discord
from utils.data.emot import GREENCHECKLIST, FIRE

from discord.ext import commands
from services.absen import AbsenService
from utils.time import get_current_date_uptime
from utils.decorator.channel import check_master_channel
from services import economy

class MembersAbsen(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="absen")
    @check_master_channel()
    async def _absen(self, ctx):
        guild_id = ctx.guild.id
        user_id = ctx.author.id
        username = str(ctx.author)
        
        xp_gain = 1200
        balance_gain = 1500
        
        # Get today's date
        today_dt = get_current_date_uptime()
        try:
            # normalisasi ke date
            today_date = today_dt.date()
        except Exception:
            today_date = today_dt
        
        # Validate voice time (existing logic)
        ok, total_time = await economy.validate_voice(guild_id, user_id, today_date)
        if not ok:
            embed = discord.Embed(
                description=f"### Voice time tidak cukup!\nyou need to join voice activity first\n-# voice time : {total_time} seconds",
                color=discord.Color.red()
            )
            return await ctx.reply(embed=embed)
        
        # Process absen dengan service
        result = await AbsenService.process_absen(guild_id, user_id, today_date)
        
        # Check if already absen today
        if result is None:
            embed = discord.Embed(
                description="❌ Kamu sudah absen hari ini!"
            )
            return await ctx.reply(embed=embed)
        
        # Get streak dari result
        streak = result['streak']
        
        # Update economy (existing logic)
        economy_result = await economy.earn_xp_balance(
            guild_id, user_id, username, xp_gain, balance_gain, "daily check-in", "credit"
        )
        
        # Build embed (sama seperti logic lama)
        embed = discord.Embed(color=discord.Color.green())
        
        if economy_result["new_level"] > economy_result["old_level"]:
            embed.description = (
                f"{GREENCHECKLIST} **Daily Check-in**\n"
                f"## `Streak {streak} hari!`{FIRE}{FIRE}\n"
                f"```Selamat kamu berhasil mencapai lv.{economy_result['new_level']}```"
            )
        else:
            embed.description = (
                f"{GREENCHECKLIST} **Daily Check-in**\n"
                f"## `Streak {streak} hari!`{FIRE}{FIRE}\n"
                f"-# You earn `{xp_gain}` xp & `{balance_gain}` vcash"
            )

        await ctx.reply(embed=embed)
 
        
async def setup(bot):
    await bot.add_cog(MembersAbsen(bot))
