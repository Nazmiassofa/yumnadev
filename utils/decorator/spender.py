from functools import wraps
from services import economy

import discord

FREE_USERS = {}  

def requires_balance(price: int, reason: str = None):
    def decorator(func):
        @wraps(func)
        async def wrapper(self, ctx, *args, **kwargs):
            user_id = ctx.author.id
            guild_id = ctx.guild.id 

            level = await economy.get_level(guild_id, user_id)

            discount = min(level, 10) * 0.01  
            discounted_price = int(price * (1 - discount))

            effective_price = 0 if user_id in FREE_USERS else discounted_price

            formatted_price = "{:,}".format(effective_price)

            if effective_price > 0:
                success = await economy.spend_balance(
                    ctx.guild.id, user_id, str(ctx.author),
                    effective_price, reason, "debit"
                )
                if not success:
                    embed = discord.Embed(
                        description=(
                            f"### Saldo tidak cukup!\n"
                            f"-# Kamu tidak memiliki cukup vcash untuk menggunakan command ini\n"
                            f"-# Price : `{formatted_price}` vcash"
                        )
                    )
                    embed.set_footer(text="you can earn vcash from voice activity")
                    return await ctx.send(embed=embed)

            return await func(self, ctx, *args, **kwargs)

        return wrapper
    return decorator
