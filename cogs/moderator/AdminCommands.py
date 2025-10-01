import discord
import logging
import io

from discord.ext import commands
from discord import app_commands

logger = logging.getLogger(__name__)

grantuser = []
grantrole = []

class Admin(commands.Cog):
    """Cog berisi perintah-perintah khusus admin bot."""
    def __init__(self, bot):
        self.bot = bot
        
    # Fungsi ping (prefix command)
    @commands.command(name="ping")
    async def ping(self, ctx):
        """Cek apakah bot responsif (prefix command)."""
        logging.info(f"Perintah prefix 'ping' diterima dari {ctx.author} di {ctx.channel.name}.")
        await ctx.send("Pong!")
        
    @commands.hybrid_command(name="help", description="Tampilkan link bantuan dan dokumentasi")
    async def help(self, ctx: commands.Context):
        embed = discord.Embed(
            title="Bantuan",
            description=(
                "Klik tautan di bawah:\n\n"
                "[ Command guideline ](https://voisacommunity.online/yumna-guideline)\n"
                "[ Support Server ](https://voisacommunity.online/invite)\n"
                "[ Support Us ](https://saweria.co/voisadiscord)\n\n"
                "Web sedang dalam pemeliharaan, gabung komunitas untuk info lebih lanjut!"
            ),
            color=discord.Color.blue()
        )
        bot_avatar = self.bot.user.avatar.url if self.bot.user.avatar else None
        if bot_avatar:
            embed.set_thumbnail(url=bot_avatar)
        
        await ctx.send(embed=embed)        

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def send(self, ctx, channel_name_or_mention: str, *, message: str = None):
        """Mengirim pesan teks atau media ke channel tertentu menggunakan command prefix."""
        await self.send_message(ctx, channel_name_or_mention, message, ctx.message.attachments)

    @app_commands.command(name="send", description="Mengirim pesan teks atau media ke channel tertentu.")
    @commands.has_permissions(administrator=True)
    @app_commands.describe(channel="Channel tujuan", message="Pesan yang ingin dikirim", attachment="File yang ingin dikirim (opsional)")
    async def send_slash(self, interaction: discord.Interaction, channel: discord.TextChannel, message: str = None, attachment: discord.Attachment = None):
        """Mengirim pesan teks atau media ke channel tertentu menggunakan slash command."""
        await interaction.response.defer()  # Menunda respons agar bot tidak timeout saat upload file
        attachments = [attachment] if attachment else []
        await self.send_message(interaction, channel, message, attachments, is_slash=True)

    async def send_message(self, ctx_or_interaction, channel_name_or_mention, message, attachments, is_slash=False):
        """Fungsi utama untuk mengirim pesan."""
        try:
            # Jika dari slash command, channel sudah dalam bentuk TextChannel
            if isinstance(channel_name_or_mention, discord.TextChannel):
                channel = channel_name_or_mention
            else:
                # Coba dapatkan channel berdasarkan ID mention atau nama
                if channel_name_or_mention.startswith("<#") and channel_name_or_mention.endswith(">"):
                    channel_id = int(channel_name_or_mention[2:-1])
                    channel = self.bot.get_channel(channel_id)
                else:
                    channel = discord.utils.get(ctx_or_interaction.guild.channels, name=channel_name_or_mention)

            if channel is None:
                error_msg = f"Channel '{channel_name_or_mention}' tidak ditemukan."
                if is_slash:
                    await ctx_or_interaction.followup.send(error_msg, ephemeral=True)
                else:
                    await ctx_or_interaction.send(error_msg)
                return

            files = []
            # Jika ada attachment, download dan simpan sebagai file
            session = self.bot.http_session
            if attachments:
                for att in attachments:
                    async with session.get(att.url) as resp:
                        if resp.status == 200:
                            file_data = await resp.read()
                            files.append(discord.File(fp=io.BytesIO(file_data), filename=att.filename))

            # Kirim pesan dengan teks atau media
            if message and files:
                await channel.send(content=message, files=files)
            elif message:
                await channel.send(content=message)
            elif files:
                await channel.send(files=files)
            else:
                error_msg = "Harap sertakan pesan atau file untuk dikirim."
                if is_slash:
                    await ctx_or_interaction.followup.send(error_msg, ephemeral=True)
                else:
                    await ctx_or_interaction.send(error_msg)
                return

            success_msg = f"Pesan berhasil dikirim ke {channel.mention}."
            if is_slash:
                await ctx_or_interaction.followup.send(success_msg, ephemeral=True)
            else:
                await ctx_or_interaction.send(success_msg)

        except Exception as e:
            error_msg = f"Terjadi error saat mengirim pesan: {e}"
            if is_slash:
                await ctx_or_interaction.followup.send(error_msg, ephemeral=True)
            else:
                await ctx_or_interaction.send(error_msg)
            print(f"Error: {e}")

    @commands.command(name="botguilds")
    @commands.is_owner()
    async def botguilds(self, ctx):
        guilds = self.bot.guilds
        embed = discord.Embed(
            title="📋 Daftar Guild yang Diikuti Bot",
            description=f"Total: **{len(guilds)}** guilds",
            color=discord.Color.blue()
        )

        char_limit = 6000  # Discord embed total character limit (safe margin)
        current_chars = len(embed.title or "") + len(embed.description or "")
        fields_added = 0

        for guild in guilds:
            field_name = guild.name
            field_value = f"🆔 `{guild.id}`\n👥 Members: `{guild.member_count}`"
            field_len = len(field_name) + len(field_value)
            # +50 buffer for embed formatting
            if current_chars + field_len + 50 > char_limit:
                embed.add_field(
                    name="⚠️ Terpotong",
                    value="Daftar terlalu panjang, hanya sebagian guild yang ditampilkan.",
                    inline=False
                )
                break
            embed.add_field(
                name=field_name,
                value=field_value,
                inline=False
            )
            current_chars += field_len
            fields_added += 1

        await ctx.send(embed=embed)
        
# ------------------ Delete Message Function
#----------------------------------------------------------------------------------------------

    # Fungsi deleteimg (prefix command)
    @commands.command()
    @commands.has_permissions(administrator=True)
    async def hapusgambar(self, ctx, jumlah: int, channel_name: str = None):
        """Menghapus sejumlah pesan yang hanya berisi gambar dari saluran tertentu atau saluran tempat perintah dijalankan."""
        logging.info(f"Perintah 'deleteimg' dipanggil oleh {ctx.author}.")
        if ( ctx.author.guild_permissions.administrator or ctx.author.id in grantuser or any(role.id in grantrole for role in ctx.author.roles) ):
            target_channel = ctx.channel if channel_name is None else discord.utils.get(ctx.guild.channels, name=channel_name) or ctx.guild.get_channel(int(channel_name))

            if not target_channel:
                await ctx.send(f"Saluran dengan nama atau ID '{channel_name}' tidak ditemukan.", delete_after=5)
                return

            if not isinstance(target_channel, discord.TextChannel):
                await ctx.send(f"Saluran '{channel_name}' bukan saluran teks.", delete_after=5)
                return

            deleted_count = 0
            async for message in target_channel.history(limit=100):
                if deleted_count >= jumlah:
                    break
                if message.attachments and any(
                    attachment.filename.lower().endswith(('jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp'))
                    for attachment in message.attachments
                ):
                    await message.delete()
                    deleted_count += 1
            await ctx.send(f"{deleted_count} pesan gambar telah dihapus dari saluran {target_channel.mention}.", delete_after=5)
        else:
            await ctx.send("Kamu tidak punya izin untuk menggunakan perintah ini.", delete_after=5)

    # Fungsi delete (prefix command)
    @commands.command(name="delmsg", aliases=["hapus"])
    @commands.has_permissions(administrator=True)
    async def hapus(self, ctx, jumlah: int, channel_name: str = None):
        """Menghapus sejumlah pesan dari saluran tertentu atau saluran tempat perintah dijalankan."""
        target_channel = ctx.channel if channel_name is None else discord.utils.get(ctx.guild.channels, name=channel_name) or ctx.guild.get_channel(int(channel_name))

        if not target_channel:
            await ctx.send(f"Saluran dengan nama atau ID '{channel_name}' tidak ditemukan.", delete_after=5)
            return

        deleted = await target_channel.purge(limit=jumlah)
        await ctx.send(f"{len(deleted)} pesan telah dihapus dari saluran {target_channel.mention}.")

    # Fungsi reverse (prefix command)
    @commands.command(name="reversedel")
    @commands.has_permissions(administrator=True)
    async def reverse(self, ctx, jumlah: int, channel_name: str = None):
        """Menghapus sejumlah pesan paling lama di saluran tertentu atau saluran tempat perintah dijalankan."""
        logging.info(f"Perintah 'reverse' dipanggil oleh {ctx.author}.")

        if (
            ctx.author.guild_permissions.administrator
            or ctx.author.id in grantuser
            or any(role.id in grantrole for role in ctx.author.roles)
        ):
            target_channel = ctx.channel if channel_name is None else discord.utils.get(ctx.guild.channels, name=channel_name) or ctx.guild.get_channel(int(channel_name))

            if not target_channel:
                await ctx.send(f"Saluran dengan nama atau ID '{channel_name}' tidak ditemukan.", delete_after=5)
                return

            deleted_count = 0
            status_message = await ctx.send("\U0001F504 Menghapus pesan...")

            try:
                async for message in target_channel.history(limit=None, oldest_first=True):
                    if deleted_count >= jumlah:
                        break
                    try:
                        await message.delete()
                        deleted_count += 1
                    except discord.Forbidden:
                        logging.warning(f"Gagal menghapus pesan oleh {message.author}: Tidak ada izin.")
                        continue
                    except discord.HTTPException as e:
                        logging.warning(f"Gagal menghapus pesan: {e}")
                        continue

                    if deleted_count % 5 == 0:
                        await asyncio.sleep(2)  # Delay untuk menghindari rate limit

                await status_message.edit(content=f"\u2705 {deleted_count} pesan paling lama telah dihapus dari saluran {target_channel.mention}.")
            except discord.Forbidden:
                await status_message.edit(content="\u274C Bot tidak memiliki izin untuk mengakses riwayat pesan.")
            except discord.HTTPException as e:
                await status_message.edit(content=f"\u274C Terjadi kesalahan: {e}")
        else:
            await ctx.send("\u274C Kamu tidak punya izin untuk menggunakan perintah ini.", delete_after=5)

    # Fungsi hapuspesan (prefix command)
    @commands.command(name="delmsguser", aliases=["hapuspesan"])
    @commands.has_permissions(administrator=True)
    async def hapuspesan(self, ctx, member: discord.Member, jumlah: int, channel_name: str = None):
        """Menghapus sejumlah pesan dari pengguna tertentu berdasarkan user ID di saluran tertentu atau saluran tempat perintah dijalankan."""
        logging.info(f"Perintah 'hapuspesan' dipanggil oleh {ctx.author}.")
        if (
            ctx.author.guild_permissions.administrator
            or ctx.author.id in grantuser
            or any(role.id in grantrole for role in ctx.author.roles)
        ):
            target_channel = ctx.channel if channel_name is None else discord.utils.get(ctx.guild.channels, name=channel_name) or ctx.guild.get_channel(int(channel_name))

            if not target_channel:
                await ctx.send(f"Saluran dengan nama atau ID '{channel_name}' tidak ditemukan.", delete_after=5)
                return

            deleted_count = 0
            async for message in target_channel.history(limit=100):
                if deleted_count >= jumlah:
                    break
                if message.author.id == member.id:  # Identifikasi berdasarkan user ID
                    await message.delete()
                    deleted_count += 1
            await ctx.send(f"\u2705 {deleted_count} pesan dari {member.mention} telah dihapus dari saluran {target_channel.mention}.")
        else:
            await ctx.send("\u274C Kamu tidak punya izin untuk menggunakan perintah ini.", delete_after=5)

async def setup(bot):
    await bot.add_cog(Admin(bot))
