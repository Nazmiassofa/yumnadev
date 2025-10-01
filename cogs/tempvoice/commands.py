import discord
import logging
from discord.ext import commands

log = logging.getLogger(__name__)

class VoiceChannelCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def get_voice_temp_cog(self):
        return self.bot.get_cog("VoiceTemp")

    async def get_user_channel(self, ctx):
        if ctx.author.voice is None or ctx.author.voice.channel is None:
            return None

        voice_temp = self.get_voice_temp_cog()
        if voice_temp is None:
            await ctx.send("Fitur channel temporary belum diaktifkan.")
            return None

        channel_id = voice_temp.active_channels.get(ctx.author.id)
        if channel_id is None:
            await ctx.send("Kamu belum memiliki voice channel temporary.")
            return None

        channel = ctx.guild.get_channel(channel_id)
        if channel is None:
            await ctx.send("Channel temporary kamu tidak ditemukan.")
            return None

        # Pastikan user adalah pemilik channel
        if voice_temp.channel_owners.get(channel.id) != ctx.author.id:
            await ctx.send("Kamu bukan pemilik dari channel temporary ini.")
            return None

        return channel

    @commands.command(name="limit")
    async def limit_channel(self, ctx, limit: int):
        """Mengubah batas jumlah user di channel menjadi <limit>."""
        channel = await self.get_user_channel(ctx)
        if channel is None:
            return

        try:
            await channel.edit(user_limit=limit)
            await ctx.send(f"User limit channel telah diubah menjadi {limit}.")
            log.info(f"{ctx.author.display_name} mengubah limit {channel.name} ke {limit}")
        except Exception as e:
            log.error(f"Gagal mengubah limit channel: {e}")
            await ctx.send("Gagal mengubah user limit channel.")

    @commands.command(name="private")
    async def make_private(self, ctx):
        """Mengubah channel menjadi private (hanya pemilik yang bisa mengakses)."""
        channel = await self.get_user_channel(ctx)
        if channel is None:
            return

        try:
            overwrites = channel.overwrites
            default_role = ctx.guild.default_role

            # Set @everyone agar tidak dapat connect dan melihat channel
            current_overwrite = overwrites.get(default_role, discord.PermissionOverwrite())
            current_overwrite.connect = False
            current_overwrite.view_channel = False
            overwrites[default_role] = current_overwrite

            # Pastikan pemilik memiliki akses penuh
            owner_overwrite = overwrites.get(ctx.author, discord.PermissionOverwrite())
            owner_overwrite.connect = True
            owner_overwrite.view_channel = True
            overwrites[ctx.author] = owner_overwrite

            await channel.edit(overwrites=overwrites)
            await ctx.send("Channel telah diubah menjadi private.")
            log.info(f"{ctx.author.display_name} mengubah {channel.name} menjadi private")
        except Exception as e:
            log.error(f"Gagal mengubah channel menjadi private: {e}")
            await ctx.send("Gagal mengubah channel menjadi private.")

    @commands.command(name="public")
    async def make_public(self, ctx):
        """Mengubah channel menjadi public (dapat diakses oleh semua)."""
        channel = await self.get_user_channel(ctx)
        if channel is None:
            return

        try:
            overwrites = channel.overwrites
            default_role = ctx.guild.default_role

            # Izinkan @everyone untuk connect dan melihat channel
            current_overwrite = overwrites.get(default_role, discord.PermissionOverwrite())
            current_overwrite.connect = True
            current_overwrite.view_channel = True
            overwrites[default_role] = current_overwrite

            await channel.edit(overwrites=overwrites)
            await ctx.send("Channel telah diubah menjadi public.")
            log.info(f"{ctx.author.display_name} mengubah {channel.name} menjadi public")
        except Exception as e:
            log.error(f"Gagal mengubah channel menjadi public: {e}")
            await ctx.send("Gagal mengubah channel menjadi public.")

    @commands.command(name="hide")
    async def hide_channel(self, ctx):
        """Menyembunyikan channel dari @everyone."""
        channel = await self.get_user_channel(ctx)
        if channel is None:
            return

        try:
            overwrites = channel.overwrites
            default_role = ctx.guild.default_role

            # Atur @everyone agar tidak bisa melihat dan connect ke channel
            current_overwrite = overwrites.get(default_role, discord.PermissionOverwrite())
            current_overwrite.view_channel = False
            current_overwrite.connect = False
            overwrites[default_role] = current_overwrite

            await channel.edit(overwrites=overwrites)
            await ctx.send("Channel telah disembunyikan.")
            log.info(f"{ctx.author.display_name} menyembunyikan channel {channel.name}")
        except Exception as e:
            log.error(f"Gagal menyembunyikan channel: {e}")
            await ctx.send("Gagal menyembunyikan channel.")

    @commands.command(name="rename")
    async def rename_channel(self, ctx, *, new_name: str):
        """Mengubah nama channel."""
        channel = await self.get_user_channel(ctx)
        if channel is None:
            return

        try:
            await channel.edit(name=new_name)
            await ctx.send(f"Nama channel telah diubah menjadi **{new_name}**.")
            log.info(f"{ctx.author.display_name} mengubah nama channel {channel.name} menjadi {new_name}")
        except Exception as e:
            log.error(f"Gagal mengubah nama channel: {e}")
            await ctx.send("Gagal mengubah nama channel.")

    @commands.command(name="transfer")
    async def transfer_ownership(self, ctx, new_owner: discord.Member):
        """Mengoper kepemilikan channel ke member lain."""
        channel = await self.get_user_channel(ctx)
        if channel is None:
            return

        # Pastikan new_owner ada di channel
        if new_owner not in channel.members:
            await ctx.send(f"{new_owner.display_name} tidak berada di channel ini.")
            return

        try:
            voice_temp = self.get_voice_temp_cog()
            if voice_temp is None:
                await ctx.send("Fitur channel temporary belum diaktifkan.")
                return

            # Update data kepemilikan
            voice_temp.channel_owners[channel.id] = new_owner.id
            voice_temp.active_channels[ctx.author.id] = None
            voice_temp.active_channels[new_owner.id] = channel.id

            # Berikan permission ke new_owner
            overwrites = channel.overwrites
            new_owner_overwrite = overwrites.get(new_owner, discord.PermissionOverwrite())
            new_owner_overwrite.connect = True
            new_owner_overwrite.view_channel = True
            new_owner_overwrite.manage_channels = True
            overwrites[new_owner] = new_owner_overwrite

            await channel.edit(overwrites=overwrites)
            await ctx.send(f"Kepemilikan channel telah dialihkan ke {new_owner.display_name}.")
            log.info(f"{ctx.author.display_name} mengalihkan kepemilikan {channel.name} ke {new_owner.display_name}")
        except Exception as e:
            log.error(f"Gagal mengalihkan kepemilikan channel: {e}")
            await ctx.send("Gagal mengalihkan kepemilikan channel.")
            
    @commands.command(name="claim")
    async def claim_channel(self, ctx):
        """Claim ownership of a temporary voice channel jika owner asli tidak hadir."""
        # 0. Pastikan fitur channel temporary aktif
        voice_temp = self.get_voice_temp_cog()
        if voice_temp is None:
            await ctx.send("Fitur channel temporary belum diaktifkan.")
            return

        # 1. Pastikan user sedang di voice channel
        voice_state = ctx.author.voice
        if not voice_state or not voice_state.channel:
            await ctx.send("Kamu harus berada di voice channel untuk klaim ownership.")
            return

        channel = voice_state.channel

        # 2. Pastikan ini channel temporary yang bot kelola
        if channel.id not in voice_temp.channel_owners:
            await ctx.send("Channel ini bukan channel temporary yang bisa diklaim.")
            return

        old_owner_id = voice_temp.channel_owners[channel.id]

        # 3. Cek apakah owner asli masih ada di channel
        if any(member.id == old_owner_id for member in channel.members):
            old_owner = ctx.guild.get_member(old_owner_id)
            name = old_owner.display_name if old_owner else str(old_owner_id)
            await ctx.send(f"Owner saat ini ({name}) masih berada di channel. Klaim dibatalkan.")
            return

        # 4. Alihkan ownership
        try:
            # Hapus active channel owner lama
            voice_temp.active_channels.pop(old_owner_id, None)
            # Set owner baru
            voice_temp.channel_owners[channel.id] = ctx.author.id
            voice_temp.active_channels[ctx.author.id] = channel.id

            # Update permission overwrites
            overwrites = channel.overwrites.copy()

            # Remove manage_channels dari old owner
            old_member = ctx.guild.get_member(old_owner_id)
            if old_member and old_member in overwrites:
                ow = overwrites[old_member]
                ow.manage_channels = False
                overwrites[old_member] = ow

            # Beri permission manage ke claimer
            new_ow = overwrites.get(ctx.author, discord.PermissionOverwrite())
            new_ow.connect = True
            new_ow.view_channel = True
            new_ow.manage_channels = True
            overwrites[ctx.author] = new_ow

            await channel.edit(overwrites=overwrites)
            await ctx.send(f"Kamu sekarang menjadi owner channel **{channel.name}**.")
            log.info(f"{ctx.author.display_name} telah mengklaim ownership {channel.name}.")
        except Exception as e:
            log.error(f"Gagal klaim ownership channel: {e}")
            await ctx.send("Terjadi kesalahan saat mencoba klaim channel.")

    @commands.command(name="kick")
    async def disconnect_member(self, ctx, member: discord.Member):
        """Memutuskan koneksi member dari channel."""
        channel = await self.get_user_channel(ctx)
        if channel is None:
            return

        # Pastikan member ada di channel
        if member not in channel.members:
            await ctx.send(f"{member.display_name} tidak berada di channel ini.")
            return

        try:
            await member.move_to(None)
            await ctx.send(f"{member.display_name} telah dikeluarkan dari channel.")
            log.info(f"{ctx.author.display_name} mengeluarkan {member.display_name} dari {channel.name}")
        except Exception as e:
            log.error(f"Gagal memutuskan member dari channel: {e}")
            await ctx.send("Gagal memutuskan member dari channel.")

async def setup(bot):
    await bot.add_cog(VoiceChannelCommands(bot))
