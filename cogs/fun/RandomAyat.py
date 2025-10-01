import discord
import requests
import logging
from discord.ext import commands

log = logging.getLogger(__name__)

class AcakayatCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='acakayat')
    async def acakayat(self, ctx):
        try:
            async with ctx.typing():
                response = requests.get('https://api.myquran.com/v2/quran/ayat/acak')
                if response.status_code == 200:
                    data = response.json()
                    if data['status']:
                        ayat_data = data['data']['ayat']
                        surat_info = data['data']['info']['surat']
                        
                        embed = discord.Embed(
                            title=f"Surah {surat_info['nama']['ar']} ({surat_info['nama']['id']})",
                            description=f"Ayat {ayat_data['ayah']}\n\n{ayat_data['arab']}\n\n_{ayat_data['latin']}_\n\n**Artinya:** {ayat_data['text']}",
                            color=discord.Color.blue()
                        )
                        embed.set_footer(text=f"Surah {surat_info['id']} | Juz {ayat_data['juz']} | Halaman {ayat_data['page']}")
                        if ayat_data['audio']:
                            embed.add_field(name="Audio", value=f"[Klik untuk mendengarkan]({ayat_data['audio']})", inline=False)

                        await ctx.send(embed=embed)
                    else:
                        await ctx.send("Gagal mengambil data ayat.")
                else:
                    await ctx.send("Terjadi kesalahan saat menghubungi API.")
        except Exception as e:
            log.error(f"Error: {e}")
            await ctx.send("Terjadi kesalahan saat memproses permintaan.")
            
    @commands.command(name='acakdoa')
    async def acakdoa(self, ctx):
        """Command untuk mengambil doa secara acak dari API."""
        try:
            async with ctx.typing():  # Simulasi mengetik
                response = requests.get('https://api.myquran.com/v2/doa/acak')
                if response.status_code == 200:
                    data = response.json()
                    if data['status']:
                        doa_data = data['data']

                        embed = discord.Embed(
                            title=doa_data['judul'],
                            description=f"**Arab:** {doa_data['arab']}\n\n**Terjemahan:** {doa_data['indo']}",
                            color=discord.Color.green()
                        )
                        embed.set_footer(text=f"Sumber: {doa_data['source']}")
                        
                        await ctx.send(embed=embed)
                    else:
                        await ctx.send("Gagal mengambil data doa.")
                else:
                    await ctx.send("Terjadi kesalahan saat menghubungi API.")
        except Exception as e:
            log.error(f"Error: {e}")
            await ctx.send("Terjadi kesalahan saat memproses permintaan.")
            
    @commands.command(name='acakhadis')
    async def acakhadis(self, ctx):
        try:
            async with ctx.typing():  # Simulasi mengetik
                response = requests.get('https://api.myquran.com/v2/hadits/perawi/acak')
                if response.status_code == 200:
                    data = response.json()
                    if data['status']:
                        hadith_data = data['data']
                        perawi_info = data['info']['perawi']

                        embed = discord.Embed(
                            title=f"Hadis Riwayat {perawi_info['name']}",
                            description=f"**Nomor Hadis:** {hadith_data['number']}\n\n"
                                        f"**Teks Arab:** {hadith_data['arab']}\n\n"
                                        f"**Terjemahan:** {hadith_data['id']}",
                            color=discord.Color.orange()
                        )
                        embed.set_footer(text=f"Jumlah Hadis dalam {perawi_info['name']}: {perawi_info['total']}")
                        
                        await ctx.send(embed=embed)
                    else:
                        await ctx.send("Gagal mengambil data hadis.")
                else:
                    await ctx.send("Terjadi kesalahan saat menghubungi API.")
        except Exception as e:
            log.error(f"Error: {e}")
            await ctx.send("Terjadi kesalahan saat memproses permintaan.")

async def setup(bot):
    """Fungsi untuk menambahkan cog ke bot."""
    await bot.add_cog(AcakayatCommands(bot))
