import discord
from discord.ext import commands
import logging
import asyncio

ITEMS_PER_PAGE = 10
BLACKLISTED_USERS = []

log = logging.getLogger(__name__)

class TriggerPaginator(discord.ui.View):
    def __init__(self, pages, user):
        super().__init__()
        self.pages = pages
        self.user = user
        self.current_page = 0

    async def update_message(self, interaction):
        embed = self.pages[self.current_page]
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="⬅️", style=discord.ButtonStyle.primary, disabled=True)
    async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.user:
            await interaction.response.send_message("Anda tidak dapat mengontrol navigasi ini!", ephemeral=True)
            return
        self.current_page -= 1
        if self.current_page == 0:
            self.previous_page.disabled = True
        self.next_page.disabled = False
        await self.update_message(interaction)

    @discord.ui.button(label="➡️", style=discord.ButtonStyle.primary, disabled=False)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.user:
            await interaction.response.send_message("Anda tidak dapat mengontrol navigasi ini!", ephemeral=True)
            return
        self.current_page += 1
        if self.current_page == len(self.pages) - 1:
            self.next_page.disabled = True
        self.previous_page.disabled = False
        await self.update_message(interaction)

class TriggerCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _key(self, guild_id: int) -> str:
        return f"triggers:guild:{guild_id}"

    async def get_server_triggers(self, guild_id: int) -> dict:
        """Fetch all triggers for a guild from Redis."""
        key = self._key(guild_id)
        data = await self.bot.redis.hgetall(key)
        # Redis returns bytes -> convert to str
        triggers = {k.decode(): v.decode() for k, v in data.items()}
        return triggers

    async def update_server_triggers(self, guild_id: int, triggers: dict):
        """Overwrite triggers for a guild in Redis."""
        key = self._key(guild_id)
        # Start transaction: remove old hash and set new
        async with self.bot.redis.pipeline() as pipe:
            pipe.delete(key)
            if triggers:
                await pipe.hset(key, mapping=triggers)
            await pipe.execute()

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return

        is_active = await self.bot.ChannelManager.is_active_channel(
            message.guild.id, message.channel.id
        )
        if not is_active:
            return

        guild_id = message.guild.id
        triggers = await self.get_server_triggers(guild_id)
        
        if not triggers:
            return

        content = message.content.lower()

        for trigger, response in triggers.items():
            if content == trigger.lower():
                async with message.channel.typing():  
                    try:
                        formatted = response.format(message=message)
                        await message.channel.send(formatted)
                    except KeyError:
                        await message.channel.send(response)
                    except Exception as e:
                        log.error(f"Error on trigger '{trigger}' in guild {message.guild.name}: {e}")
                break

    @commands.command(name="tambah", aliases=["addtrigger"])
    async def tambah(self, ctx, trigger: str, *, response: str):
        if not ctx.guild:
            return await ctx.send("Perintah ini hanya bisa digunakan di server!")
        if not trigger or not response:
            return await ctx.send("Trigger dan response tidak boleh kosong!")
        if len(trigger) > 100 or len(response) > 1000:
            return await ctx.send("Trigger maksimal 100 karakter, response maksimal 1000 karakter!")

        guild_id = ctx.guild.id
        triggers = await self.get_server_triggers(guild_id)
        if trigger.lower() in (t.lower() for t in triggers):
            return await ctx.send(f"Trigger '{trigger}' sudah ada!")

        triggers[trigger] = response
        await self.update_server_triggers(guild_id, triggers)

        msg = await ctx.send(f"Trigger '{trigger}' berhasil ditambahkan!")
        await asyncio.sleep(2)
        try:
            await ctx.message.delete()
            await msg.delete()
        except discord.Forbidden:
            pass
        except discord.HTTPException:
            pass

    @commands.command(name="apus", aliases=["deltrigger"])
    async def apus(self, ctx, *, trigger: str):
        if not ctx.guild:
            return await ctx.send("Perintah ini hanya bisa digunakan di server!")
        if ctx.author.id in BLACKLISTED_USERS:
            log.warning(f"Blocked user {ctx.author} tried to delete trigger.")
            return await ctx.send("Anda tidak diizinkan untuk menggunakan perintah ini.")

        guild_id = ctx.guild.id
        triggers = await self.get_server_triggers(guild_id)
        found = next((t for t in triggers if t.lower() == trigger.lower()), None)
        if not found:
            return await ctx.send(f"Trigger '{trigger}' tidak ditemukan!")

        del triggers[found]
        await self.update_server_triggers(guild_id, triggers)
        await ctx.send(f"Trigger '{found}' berhasil dihapus!")

    @commands.command(name="resettrigger")
    @commands.has_permissions(administrator=True)
    async def resettrigger(self, ctx):
        if not ctx.guild:
            return await ctx.send("Perintah ini hanya bisa digunakan di server!")

        guild_id = ctx.guild.id
        await self.update_server_triggers(guild_id, {})
        await ctx.send("Semua trigger di server ini telah direset!")
        log.info(f"All triggers reset in guild {ctx.guild.name} by {ctx.author}")

    @commands.command(name="daftar", aliases=["listtrigger"])
    async def daftar(self, ctx):
        if not ctx.guild:
            return await ctx.send("Perintah ini hanya bisa digunakan di server!")

        guild_id = ctx.guild.id
        triggers = await self.get_server_triggers(guild_id)
        if not triggers:
            embed = discord.Embed(title="Daftar Trigger", description="Tidak ada trigger yang tersedia saat ini!",
                                  color=discord.Color.red())
            embed.set_footer(text=ctx.guild.name)
            return await ctx.send(embed=embed)

        pages = []
        current_page, length = [], 0
        for idx, (key, value) in enumerate(triggers.items(), 1):
            if 'http://' in value.lower() or 'https://' in value.lower():
                first_url = value.splitlines()[0].strip()
                disp = f"[link_{key}]({first_url})"
                if '\n' in value:
                    disp += f" (+{value.count('\n')} link lainnya)"
            else:
                disp = value

            item = f"**{idx}.** `{key}`: {disp}\n"
            if length + len(item) > 1024 or len(current_page) >= ITEMS_PER_PAGE:
                embed = discord.Embed(title="Daftar Trigger", color=discord.Color.blue())
                embed.add_field(name=f"Total Trigger: {len(triggers)}", value=''.join(current_page), inline=False)
                embed.set_footer(text=ctx.guild.name)
                pages.append(embed)
                current_page, length = [], 0

            current_page.append(item)
            length += len(item)

        if current_page:
            embed = discord.Embed(title="Daftar Trigger", color=discord.Color.blue())
            embed.add_field(name=f"Total Trigger: {len(triggers)}", value=''.join(current_page), inline=False)
            embed.set_footer(text=f"Diminta oleh {ctx.author.display_name}", icon_url=ctx.author.avatar.url)
            pages.append(embed)

        if len(pages) == 1:
            await ctx.send(embed=pages[0])
        else:
            view = TriggerPaginator(pages, ctx.author)
            await ctx.send(embed=pages[0], view=view)
        log.info(f"Trigger list requested by {ctx.author} in {ctx.guild.name}")

async def setup(bot):
    await bot.add_cog(TriggerCommands(bot))
