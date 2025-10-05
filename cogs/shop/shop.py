import discord
from discord.ext import commands, tasks
from datetime import datetime, time
from utils.time_utils import JAKARTA_TZ

class ShopCog(commands.Cog):
    def __init__(self, bot, shop_service):
        self.bot = bot
        self.shop_service = shop_service
        self.daily_refresh.start()

    def cog_unload(self):
        self.daily_refresh.cancel()

    @tasks.loop(minutes=1)
    async def daily_refresh(self):
        """Auto refresh shop at 7AM GMT+7."""
        now = datetime.now(JAKARTA_TZ)
        if now.hour == 7 and now.minute == 0:
            await self.shop_service.generate_daily_shop()
            print(f"[SHOP] Refreshed for {now.date()}")

    @daily_refresh.before_loop
    async def before_refresh(self):
        await self.bot.wait_until_ready()

    #view shop
    @commands.command(name="shop")
    async def shop(self, ctx):
        items = await self.shop_service.get_today_shop()
        if not items:
            return await ctx.send("🛒 The shop is empty right now.")

        embed = discord.Embed(
            title="🛍️ Daily Shop",
            description="Resets every day at **7 AM GMT+7**",
            color=discord.Color.gold(),
            timestamp=datetime.now(JAKARTA_TZ),
        )

        for i, item in enumerate(items, 1):
            duration_text = f"⏱️ Duration: {item['duration']}" if item["duration"] else ""
            embed.add_field(
                name=f"{i}. {item['item_name']}",
                value=f"💰 {item['price']} vcash | 📦 Stock: {item['stock']}\n{duration_text}",
                inline=False,
            )

        await ctx.send(embed=embed)

    # buy item from shop
    @commands.command(name="buy")
    async def buy(self, ctx, number: int):
        success, message = await self.shop_service.buy_item(
            ctx.guild.id, ctx.author.id, str(ctx.author), number
        )
        await ctx.send(message)


async def setup(bot):
    from repositories.shop_repo import ShopRepository
    from services.shop_service import ShopService

    repo = ShopRepository(bot.db)
    service = ShopService(repo, bot.economy)

    await bot.add_cog(ShopCog(bot, service))
