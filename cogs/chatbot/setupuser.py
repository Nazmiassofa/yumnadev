import discord
import logging

from typing import Callable, Awaitable
from utils.qdrant import store_memory
from .database.db import DataBaseManager as db
from discord.ext import commands
from discord import app_commands
from discord.ui import Modal, TextInput

log = logging.getLogger(__name__)

class PromptInputModal(Modal, title="Prompt Ai Yumna Bot"):
    def __init__(self, callback: Callable[[discord.Interaction, str, str], Awaitable[None]]):
        super().__init__()
        self.callback_func = callback

        self.server_info = TextInput(
            label="Informasi Tentang Server",
            style=discord.TextStyle.long,
            placeholder="Contoh: Server ini dibuat sejak 1998 ...",
            required=True,
            min_length=20,
            max_length=500
        )
        self.member_info = TextInput(
            label="Informasi Member",
            style=discord.TextStyle.long,
            placeholder="Contoh: Ini adalah list member dan kepribadiannya: 1. Jokowi ...",
            required=True,
            min_length=20,
            max_length=500
        )

        self.add_item(self.server_info)
        self.add_item(self.member_info)

    async def on_submit(self, interaction: discord.Interaction):
        server_info = self.server_info.value.strip()
        member_info = self.member_info.value.strip()

        # Validasi panjang manual
        if len(server_info) < 20 or len(server_info) > 1000:
            await interaction.response.send_message(
                "❌ `Informasi Server` harus antara 20–1000 karakter.", ephemeral=True
            )
            return

        if len(member_info) < 20 or len(member_info) > 1000:
            await interaction.response.send_message(
                "❌ `Informasi Member` harus antara 20–1000 karakter.", ephemeral=True
            )
            return

        await self.callback_func(interaction, server_info, member_info)

class PromptCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="set_prompt", description="Atur prompt khusus untuk server ini.")
    async def set_prompt(self, interaction: discord.Interaction):
        modal = PromptInputModal(callback=self.save_prompt)
        await interaction.response.send_modal(modal)

    async def save_prompt(self, interaction: discord.Interaction, server_info: str, member_info: str):
        try:
            guild_id = interaction.guild.id
            await db.upsert_guild_prompts(self, guild_id, server_info, member_info)
            await interaction.response.send_message(
                "✅ Prompt berhasil disimpan untuk server ini!", ephemeral=True
            )
        except ValueError as ve:
            await interaction.response.send_message(
                f"❌ {str(ve)}", ephemeral=True
            )
        except Exception as e:
            log.exception("Gagal menyimpan prompt:")
            await interaction.response.send_message(
                "❌ Gagal menyimpan prompt.", ephemeral=True
            )
            
    @commands.command(name="remember")
    async def remember(self, ctx: commands.Context, *, information: str):
        guild_id = str(ctx.guild.id)
        await ctx.typing()
        await store_memory(guild_id, information)
        await ctx.reply("✅ Okay. Yumna akan mengingatnya!.")
        
    @commands.command(name='remember_me')
    async def introduce(self, ctx, *, introduction: str):
        user_id = ctx.author.id
        username = f"{ctx.author.name}#{ctx.author.discriminator}"  # ctx.username tidak ada di discord.py

        try:
            await db.save_user_profile(self, user_id, username, introduction)
            await ctx.send("✅ Yumna akan mengingatmu!")
        except Exception as e:
            await ctx.send(f"❌ Gagal menyimpan profil: `{str(e)}`")

async def setup(bot: commands.Bot):
    await bot.add_cog(PromptCog(bot))
