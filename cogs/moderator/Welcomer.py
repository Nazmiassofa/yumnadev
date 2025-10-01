import discord
import logging

from discord.ext import commands
from core.db import db_connection

from cogs.voice.helper.pil import create_welcome_card

log = logging.getLogger(__name__)

class DatabaseManager:
    @staticmethod
    async def delete_guild_data(guild_id: int):
        try:
            # Asumsi db_connection adalah context manager yang mengembalikan koneksi asyncpg
            async with db_connection() as conn:  # Perhatikan: tidak perlu 'self' di sini
                query = """
                DELETE FROM voisa.guild_setting
                WHERE guild_id = $1
                """
                result = await conn.execute(query, guild_id)
                
                # Cek apakah ada baris yang terhapus
                if result == "DELETE 0":
                    log.info(f"[ INFO ] Tidak ada data guild dengan ID {guild_id} yang ditemukan untuk dihapus.")
                else:
                    log.info(f"[ DELETED ] Data guild dengan ID {guild_id} berhasil dihapus beserta data terkait.")
                    
        except Exception as e:
            log.info(f"[Error] Gagal menghapus data guild {guild_id}: {e}")
            raise  # Re-raise jika ingin error ditangani di luar

    @staticmethod
    async def insert_guild_data(guild_id: int, guild_name: str) -> bool:
        try:
            async with db_connection() as conn:
                query = """
                    INSERT INTO voisa.guild_setting (guild_id, guild_name)
                    VALUES ($1, $2)
                    ON CONFLICT (guild_id)
                    DO UPDATE SET guild_name = EXCLUDED.guild_name;
                """
                await conn.execute(query, guild_id, guild_name)
            return True
        except Exception as e:
            # Bisa juga logging biar tau error-nya
            log.info(f"[DB ERROR] gagal insert/upsert guild {guild_id}: {e}")
            return False

class Welcomer(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member):
        channel_id = 1371790587900199003  # Ganti dengan ID channel tujuan
        channel = member.guild.get_channel(channel_id)

        if channel is not None:
            try:
                # Buat welcome card
                welcome_card = create_welcome_card(member.name, member.display_avatar.url)

                # Kirim pesan beserta gambar
                await channel.send(
                    content=f"Selamat datang diperkemahan kami, {member.mention} ",
                    file=discord.File(welcome_card, "welcome.png")
                )
            except Exception as e:
                log.error(f"Error sending welcome message: {e}")
                await channel.send("Terjadi error saat menyambut member baru.")
        else:
            log.warning("Channel tidak ditemukan.")
            
    # @commands.Cog.listener()
    # async def on_member_remove(self, member: discord.Member):
            
    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        try:
            log.info(f"Bot join guild: {guild.name} (ID: {guild.id})")
            await DatabaseManager.insert_guild_data(guild.id, guild.name)
        except Exception as e:
            log.error(f"Failed to insert guild data for {guild.name} (ID: {guild.id}): {e}")

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild):
        try:
            log.info(f"Bot removed from guild: {guild.name} (ID: {guild.id})")
            await DatabaseManager.delete_guild_data(guild.id)
        except Exception as e:
            log.error(f"Failed to delete guild data for {guild.name} (ID: {guild.id}): {e}")


async def setup(bot):
    await bot.add_cog(Welcomer(bot))
