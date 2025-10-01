import discord

from discord import app_commands
from discord.ext import commands
from discord.ui import View, Select, Modal, TextInput
from .database.db_manager import TempVoiceDatabaseMan as db
from .database.redis import RedisManager as redis

from utils.data.emot import (NEW,
                       DELETE)

class VoiceSetupModal(Modal, title='Setup Master Voice Channel'):
    channel_name = TextInput(
        label="Nama Voice Channel",
        placeholder="Contoh: Master 1",
        max_length=100
    )
    category_random = TextInput(
        label="Kategori Random",
        placeholder="Contoh: ilmu",
        max_length=32,
        default="ilmu"
    )

    def __init__(self, handler):
        super().__init__()
        self.handler = handler

    async def on_submit(self, interaction: discord.Interaction):
        name = self.channel_name.value.strip()
        cat_random = self.category_random.value.strip()
        
        if not cat_random.replace("_", "").isalnum():
            await interaction.response.send_message(
                "⚠️ Nama kategori random hanya boleh mengandung huruf, angka, atau underscore",
                ephemeral=True
            )
            return
        
        try:
            await interaction.response.defer(ephemeral=True)
            await self.handler.create_master_channel(interaction, name, cat_random)
        except Exception as e:
            await interaction.followup.send(
                f"❌ Terjadi error: {str(e)}",
                ephemeral=True
            )

class VoiceSetupView(View):
    def __init__(self, cog):
        super().__init__(timeout=360)
        self.cog = cog

    @discord.ui.select(
        custom_id="voice_setup_select",
        placeholder="🔧 Opsi setup...",
        min_values=1,
        max_values=1,
        options=[
            discord.SelectOption(label="- Create Master", value="create", emoji=f"{NEW}"),
            discord.SelectOption(label="- Delete Master", value="delete", emoji=f"{DELETE}")
        ]
    )
    async def select_callback(self, interaction: discord.Interaction, select: Select):
        try:
            if select.values[0] == "create":
                await interaction.response.send_modal(VoiceSetupModal(self.cog))
            else:
                await interaction.response.defer(ephemeral=True)
                await self.cog.delete_master_channel(interaction)
        except Exception as e:
            await interaction.followup.send(
                f"❌ Error: {str(e)}",
                ephemeral=True
            )

class VoiceCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # db = DatabaseManager(
            
    async def send_response(self, interaction: discord.Interaction, content=None, *, embed=None, ephemeral=False):
        """Universal method to send responses safely"""
        try:
            if interaction.response.is_done():
                await interaction.followup.send(content=content, embed=embed, ephemeral=ephemeral)
            else:
                await interaction.response.send_message(content=content, embed=embed, ephemeral=ephemeral)
        except Exception as e:
            try:
                await interaction.channel.send(
                    content=f"{interaction.user.mention} {content if content else ''}",
                    embed=embed
                )
            except Exception:
                self.bot.logger.error(f"Failed to send message: {str(e)}")

    @app_commands.command(name="setupvoice", description="Control panel untuk setup voice master")
    @app_commands.checks.has_permissions(administrator=True)
    async def setupvoice(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Setup Voice Master",
            description=(
                "Pilih opsi di bawah untuk membuat atau menghapus master voice channel.\n\n"
                f"{NEW} • **Create Master**: Buat voice channel baru sebagai master.\n"
                f"{DELETE}• **Delete Master**: Hapus voice channel master yang sudah ada."
            ),
            color=discord.Color.blurple()
        )
        await interaction.response.send_message(embed=embed, view=VoiceSetupView(self), ephemeral=True)

    async def create_master_channel(self, interaction: discord.Interaction, channel_name: str, category_random: str):
        try:
            guild = interaction.guild
            existing = await db.count_master_channels(guild.id)
            is_prem = await db.is_premium_guild(guild.id)
            limit = 3 if is_prem else 1
            
            if existing >= limit:
                settings = await db.get_all_master_channels(guild.id)
                em = discord.Embed(
                    title="Daftar Master Channels:",
                    description=f"Guild ini telah mencapai limit.\n Limit : {limit}",
                    color=discord.Color.orange()
                )
                for item in settings:
                    cid = item['master_voice_chid']
                    ch = guild.get_channel(cid)
                    em.add_field(name=f"{ch.name if ch else cid}", value=f"ID: `{cid}`", inline=False)
                return await self.send_response(interaction, embed=em, ephemeral=True)

            category_name = "----[ Yumna Voice ]"
            category = discord.utils.get(guild.categories, name=category_name)
            if not category:
                category = await guild.create_category(category_name)
            
            channel = await guild.create_voice_channel(
                channel_name,
                category=category,
                reason=f"Master channel random: {category_random}"
            )

            ok = await db.set_guild_voice_settings(guild.id, channel.id, category_random)
            if not ok:
                await channel.delete()
                if not category.channels:
                    await category.delete()
                return await self.send_response(
                    interaction,
                    "❌ Gagal menyimpan. Coba lagi.",
                    ephemeral=True
                )
                
            await redis.cache_guild_setting(self, guild.id, channel.id, category_random)
            
            em = discord.Embed(title="🎉 Master Channel Dibuat!", color=discord.Color.green())
            em.add_field(name="Channel", value=channel.mention)
            em.add_field(name="Kategori Random", value=f"`{category_random}`")
            await self.send_response(interaction, embed=em, ephemeral=True)

        except Exception as e:
            await self.send_response(
                interaction,
                f"❌ Error saat membuat channel: {str(e)}",
                ephemeral=True
            )
            if 'category' in locals() and not category.channels:
                await category.delete()

    async def delete_master_channel(self, interaction: discord.Interaction):
        try:
            guild = interaction.guild
            settings = await db.get_guild_settings(guild.id)
            mid = settings.get('master_voice_chid')
            
            if not mid:
                return await self.send_response(
                    interaction,
                    "⚠️ Tidak ada master channel.",
                    ephemeral=True
                )
                
            deleted = await db.delete_guild_settings(guild.id)
            if not deleted:
                return await self.send_response(
                    interaction,
                    "❌ Gagal menghapus pengaturan.",
                    ephemeral=True
                )
            
            try:
                await self.bot.redis.delete(f"yumna:guild_settings:{guild.id}")
            except Exception as e:
                self.bot.logger.error(f"Redis error: {str(e)}")
                
            channel = guild.get_channel(mid)
            if channel:
                try:
                    await channel.delete(reason="Master dihapus via setupvoice")
                except discord.HTTPException as e:
                    return await self.send_response(
                        interaction,
                        f"⚠️ Gagal menghapus channel: {e}",
                        ephemeral=True
                    )
                    
            await self.send_response(
                interaction,
                "✅ Master channel berhasil dihapus.",
                ephemeral=True
            )

        except Exception as e:
            await self.send_response(
                interaction,
                f"❌ Error saat menghapus channel: {str(e)}",
                ephemeral=True
            )

async def setup(bot):
    await bot.add_cog(VoiceCog(bot))