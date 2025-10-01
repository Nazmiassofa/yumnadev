from functools import wraps
from discord.ext import commands

def check_master_channel():
    def decorator(func):
        @wraps(func)
        async def wrapper(self, ctx: commands.Context, *args, **kwargs):
            bot = self.bot
            guild = ctx.guild
            if not guild:
                # allow in DMs (or change behavior if you prefer to block)
                return await func(self, ctx, *args, **kwargs)

            guild_id = guild.id
            channel_id = ctx.channel.id
            author = ctx.author

            # roles that can bypass the channel check
            allowed_roles = {
                1365467389621436499,  # voisaretired
                1249926441840148492,  # serverbooster
                1392501494770569307,  # donatur
            }

            # role bypass
            if allowed_roles:
                user_role_ids = {r.id for r in author.roles}
                if allowed_roles.intersection(user_role_ids):
                    return await func(self, ctx, *args, **kwargs)

            try:
                is_master = await self.bot.ChannelManager.is_master_channel(guild_id, channel_id)
            except Exception as e:
                # if something fails while checking, fail closed (deny) and log if you want
                try:
                    # optional: log to bot logger if available
                    bot.logger.error(f"Error while checking master channel: {e}")
                except Exception:
                    pass
                await ctx.reply("⚠️ Terjadi kesalahan saat memeriksa channel utama.")
                return

            if not is_master:
                # show configured master/second channel if available (best-effort)
                master_id = self.bot.ChannelManager.master_channels_ai.get(guild_id)
                second_id = self.bot.ChannelManager.second_channels.get(guild_id)
                hint = []
                if master_id:
                    hint.append(f"<#{master_id}>")
                if second_id:
                    hint.append(f"<#{second_id}>")
                hint_text = " atau ".join(hint) if hint else "channel utama"
                await ctx.reply(
                    f"Hanya bisa digunakan di {hint_text}.\n-# Role access permission tidak cukup, hubungi admin."
                )
                return

            return await func(self, ctx, *args, **kwargs)

        return wrapper
    return decorator
