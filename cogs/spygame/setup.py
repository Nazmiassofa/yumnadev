async def setup(bot):
    from .helper.spy import PickMeGame
    from .helper.vote_conf import Vote

    spy_cog = PickMeGame(bot)
    await bot.add_cog(spy_cog)
    await bot.add_cog(Vote(bot, spy_cog))
