import discord
from discord.ext import commands
import requests
import asyncio
from config import API

api_key = API.STARRYAI_KEY
base_url = "https://api.starryai.com/creations/"


class ImageGeneratorCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
    async def _generate_image_internal(self, user_id: int, prompt: str):
        """Fungsi internal untuk generate gambar tanpa ctx."""
        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "X-API-Key": api_key
        }

        payload = {
            "model": "anime_vintage",
            "aspectRatio": "landscape",
            "highResolution": False,
            "images": 1,  # Buat 1 gambar dulu
            "steps": 40,
            "initialImageMode": "color",
            "initialImageStrength": 59,
            "prompt": prompt
        }

        try:
            # Kirim request untuk membuat gambar
            response = requests.post(base_url, json=payload, headers=headers)
            data = response.json()

            if "id" in data and data["id"]:
                creation_id = data["id"]

                # Tunggu hingga gambar selesai diproses
                images = await self.check_image_status(creation_id, headers)

                if images:
                    image_urls = [img["url"] for img in images if img.get("url")]
                    return image_urls
                else:
                    raise Exception("Gambar tidak tersedia setelah waktu tunggu.")
            else:
                raise Exception("Gagal membuat gambar: " + str(data))

        except Exception as e:
            raise Exception(f"❌ Terjadi kesalahan: {str(e)}")

    async def check_image_status(self, creation_id, headers):
        """Polling untuk mengecek status gambar hingga selesai."""
        for _ in range(40): 
            await asyncio.sleep(10)  # Tunggu 10 detik sebelum cek lagi

            response = requests.get(f"{base_url}{creation_id}", headers=headers)
            data = response.json()

            if data.get("status") == "completed":
                return data.get("images", [])  # Kembalikan daftar gambar jika selesai

        return None  # Jika setelah 100 detik masih belum selesai

    @commands.command(name="generate")
    async def generate_image(self, ctx, *, prompt: str):
        try:
            headers = {
                "accept": "application/json",
                "content-type": "application/json",
                "X-API-Key": api_key
            }

            payload = {
                "model": "cinematic",
                "aspectRatio": "landscape",
                "highResolution": False,
                "images": 1,  # Buat 1 gambar dulu
                "steps": 40,
                "initialImageMode": "color",
                "initialImageStrength": 59,
                "prompt": prompt
            }

            async with ctx.typing():
                # Kirim request untuk membuat gambar
                response = requests.post(base_url, json=payload, headers=headers)
                data = response.json()

                if "id" in data and data["id"]:
                    creation_id = data["id"]

                    await ctx.send(f"Sedang diproses ... Harap tunggu.")

                    # Tunggu hingga gambar selesai diproses
                    images = await self.check_image_status(creation_id, headers)

                    if images:
                        for img in images:
                            if img.get("url"):
                                embed = discord.Embed(title="Hasil Gambar", description="")
                                embed.set_image(url=img["url"])
                                await ctx.send(embed=embed)
                            else:
                                await ctx.send(f"⚠️ URL gambar tidak valid: `{img}`")
                    else:
                        await ctx.send(f"❌ Gambar tidak tersedia setelah waktu tunggu.")

                else:
                    await ctx.reply(f"Sepertinya server sedang sibuk...")

        except Exception as e:
            await ctx.send(f"❌ Terjadi kesalahan: {str(e)}")

async def setup(bot):
    await bot.add_cog(ImageGeneratorCog(bot))