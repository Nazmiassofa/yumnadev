import discord

from utils.logger import logging
from ...database.db_manager import TempVoiceDatabaseMan as db
from utils.data.emot import (HIDE,
                       PUBLIC,
                       EDIT,
                       LIMIT,
                       PRIVATE,
                       RANDOM)

class LimitChannelModal(discord.ui.Modal, title="Atur User Limit"):
    limit = discord.ui.TextInput(
        label="Batas Pengguna",
        placeholder="Masukkan angka (0 untuk tanpa batas)",
        required=True
    )

    def __init__(self, channel: discord.VoiceChannel):
        super().__init__()
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction):
        try:
            limit_value = int(self.limit.value)
            if limit_value < 0:
                raise ValueError
            await self.channel.edit(user_limit=limit_value)
            await interaction.response.send_message(
                f"✅ User limit diatur ke {limit_value}", ephemeral=True
            )
            logging.info(f"User limit {self.channel.name} diubah ke {limit_value}")
        except ValueError:
            await interaction.response.send_message(
                "❌ Masukkan angka yang valid!", ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Bot tidak memiliki izin!", ephemeral=True
            )

class ChangeChannelNameModal(discord.ui.Modal, title="Ubah Nama Channel"):
    new_name = discord.ui.TextInput(
        label="Nama Baru",
        placeholder="Masukkan nama baru...",
        required=True
    )

    def __init__(self, channel: discord.VoiceChannel):
        super().__init__()
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction):
        new_name = self.new_name.value.strip()
        if len(new_name) < 2 or len(new_name) > 100:
            await interaction.response.send_message(
                "❌ Nama harus 2-100 karakter!", ephemeral=True
            )
            return
        try:
            await self.channel.edit(name=new_name)
            await interaction.response.send_message(
                f"✅ Nama diubah menjadi: {new_name}", ephemeral=True
            )
            logging.info(f"Nama channel {self.channel.name} diubah ke {new_name}")
        except discord.HTTPException as e:
            await interaction.response.send_message(
                f"❌ Gagal mengubah nama: {e}", ephemeral=True
            )

class VoiceChannelConfigView(discord.ui.View):
    def __init__(self, channel: discord.VoiceChannel, owner_id: int, bot):
        super().__init__(timeout=None)
        self.channel = channel
        self.owner_id = owner_id
        self.bot = bot  # Tambahkan ini


        # Define select options
        options = [
            discord.SelectOption(label="Public", emoji=f"{PUBLIC}", value="public", description="Atur channel jadi publik"),
            discord.SelectOption(label="Private", emoji=f"{PRIVATE}", value="private", description="Atur channel jadi privat"),
            discord.SelectOption(label="Hide", emoji=f"{HIDE}", value="hide", description="Sembunyikan channel"),
            discord.SelectOption(label="Random Name", emoji=f"{RANDOM}", value="random", description="Acak nama channel"),
            discord.SelectOption(label="Limit", emoji=f"{LIMIT}", value="limit", description="Atur batas user"),
            discord.SelectOption(label="Rename", emoji=f"{EDIT}", value="rename", description="Ubah nama channel")
        ]
        # Create select and bind callback via lambda to include select param
        select = discord.ui.Select(
            placeholder=" 🔧 Select Opsi...", options=options,
            custom_id=f"vcfg_{channel.id}"
        )
        select.callback = lambda interaction, s=select: self.select_action(interaction, s)
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "❌ Hanya owner channel yang bisa menggunakan ini!", ephemeral=True
            )
            return False
        return True

    async def select_action(self, interaction: discord.Interaction, select: discord.ui.Select):
        choice = select.values[0]        
        if choice not in ["limit", "rename"]:
            await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        key = f"yumna:temp_channels:{self.channel.id}"
        try:
            # Prepare everyone overwrite
            everyone = guild.default_role
            eo = self.channel.overwrites_for(everyone)

            if choice == "public":
                eo.view_channel = True; eo.connect = True; eo.use_embedded_activities = True
                await self.bot.redis.hset(key, mapping={"status": "public"})
            elif choice == "private":
                eo.view_channel = True; eo.connect = False; eo.use_embedded_activities = True
                await self.bot.redis.hset(key, mapping={"status": "private"})
            elif choice == "hide":
                eo.view_channel = False
                await self.bot.redis.hset(key, mapping={"status": "hidden"})            
            elif choice == "random":
                category = self.channel.category
                existing = {c.name for c in category.voice_channels} if category else set()

                # Ambil nama acak dari database
                name = await db.get_random_name_ch(self.bot)

                # Cegah duplikat nama di dalam kategori
                attempt = 0
                original_name = name
                while name in existing and attempt < 10:
                    name = await db.get_random_name_ch(self.bot)
                    attempt += 1

                if name in existing:
                    return await interaction.followup.send("❌ Gagal menghasilkan nama unik setelah 10 percobaan.", ephemeral=True)

                # Ubah nama channel
                await self.channel.edit(name=name)
                await self.bot.redis.hset(key, mapping={"name": name})

                return await interaction.followup.send(f"✅ Nama channel diacak menjadi: **{name}**", ephemeral=True)            
            elif choice == "limit":
                return await interaction.response.send_modal(LimitChannelModal(self.channel))
            elif choice == "rename":
                return await interaction.response.send_modal(ChangeChannelNameModal(self.channel))

            # Apply overwrite for everyone
            await self.channel.set_permissions(everyone, overwrite=eo)
            # Ensure owner perms
            owner = guild.get_member(self.owner_id)
            if owner:
                perms = discord.PermissionOverwrite(
                    view_channel=True, connect=True, speak=True,
                    mute_members=True, deafen_members=True,
                    move_members=True, manage_channels=True,
                    use_embedded_activities=True
                )
                await self.channel.set_permissions(owner, overwrite=perms)

            await interaction.followup.send(f"✅ Berhasil\n-# Channel diubah menjadi '{choice}'!", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("❌ Bot tidak memiliki izin!", ephemeral=True)
        except Exception as e:
            logging.error(f"Error in select_action {choice}: {e}")
            await interaction.followup.send("❌ Terjadi kesalahan saat menjalankan aksi.", ephemeral=True)