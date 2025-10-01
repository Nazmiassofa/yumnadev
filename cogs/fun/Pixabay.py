import discord
import aiohttp
import asyncio
import random
import logging
from typing import Optional, List

from discord.ext import commands
from discord import app_commands
from config import API

log = logging.getLogger(__name__)

BASE_URL = "https://pixabay.com/api/"

class PixabayCog(commands.Cog):
    """Cog untuk mencari gambar dari Pixabay API"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._session: Optional[aiohttp.ClientSession] = None
        
    async def cog_load(self) -> None:
        """Called when the cog is loaded"""
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            headers={'User-Agent': 'Discord Bot Pixabay Search'}
        )
        
    async def cog_unload(self) -> None:
        """Called when the cog is unloaded"""
        if self._session and not self._session.closed:
            await self._session.close()
        log.info(f"{self.__class__.__name__} unloaded")
    
    @property
    def session(self) -> aiohttp.ClientSession:
        """Get the HTTP session, create if not exists"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
                headers={'User-Agent': 'Discord Bot Pixabay Search'}
            )
        return self._session
    
    async def _fetch_images(self, params: dict) -> Optional[dict]:
        """Fetch images from Pixabay API"""
        try:
            async with self.session.get(BASE_URL, params=params) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    log.warning(f"Pixabay API returned status {response.status}")
                    return None
        except asyncio.TimeoutError:
            log.error("Timeout when connecting to Pixabay API")
            return None
        except aiohttp.ClientError as e:
            log.error(f"HTTP client error: {e}")
            return None
        except Exception as e:
            log.error(f"Unexpected error when fetching images: {e}")
            return None
    
    def _create_embed(self, hit: dict, query: str) -> discord.Embed:
        """Create embed for a single image result"""
        embed = discord.Embed(
            title=f"🔍 Hasil pencarian: {query}",
            color=discord.Color.random(),
            url=hit.get("pageURL", "")
        )
        
        # Set image
        image_url = hit.get("largeImageURL") or hit.get("webformatURL")
        if image_url:
            embed.set_image(url=image_url)
        
        # Add image info
        user = hit.get("user", "Unknown")
        likes = hit.get("likes", 0)
        views = hit.get("views", 0)
        downloads = hit.get("downloads", 0)
        tags = hit.get("tags", "")
        
        embed.add_field(
            name="📊 Statistik",
            value=f"👤 **{user}**\n💖 {likes:,} likes\n👁️ {views:,} views\n⬇️ {downloads:,} downloads",
            inline=True
        )
        
        if tags:
            # Limit tags to prevent embed overflow
            tag_list = tags.split(", ")[:5]
            embed.add_field(
                name="🏷️ Tags",
                value=", ".join(f"`{tag}`" for tag in tag_list),
                inline=True
            )
        
        embed.set_footer(
            text="Pixabay • Klik judul untuk melihat halaman asli",
            icon_url="https://pixabay.com/favicon.ico"
        )
        
        return embed
    
    @app_commands.command(name="pixabay", description="Cari gambar dari Pixabay")
    @app_commands.describe(
        query="Kata kunci pencarian gambar",
        lang="Bahasa hasil pencarian (default: Indonesia)", 
        image_type="Tipe gambar yang dicari (default: Semua)",
        safe_search="Aktifkan safe search untuk konten yang aman",
        amount="Jumlah gambar yang ditampilkan (1-5, default: 3)"
    )
    @app_commands.choices(
        image_type=[
            app_commands.Choice(name="Semua", value="all"),
            app_commands.Choice(name="Foto", value="photo"),
            app_commands.Choice(name="Ilustrasi", value="illustration"),
            app_commands.Choice(name="Vector", value="vector"),
        ],
        lang=[
            app_commands.Choice(name="Indonesia", value="id"),
            app_commands.Choice(name="English", value="en"),
            app_commands.Choice(name="Japanese", value="ja"),
            app_commands.Choice(name="Spanish", value="es"),
            app_commands.Choice(name="French", value="fr"),
            app_commands.Choice(name="German", value="de"),
            app_commands.Choice(name="Chinese", value="zh"),
        ]
    )
    async def pixabay_search(
        self,
        interaction: discord.Interaction,
        query: str,
        lang: Optional[app_commands.Choice[str]] = None,
        image_type: Optional[app_commands.Choice[str]] = None,
        safe_search: Optional[bool] = True,
        amount: Optional[int] = 3
    ) -> None:
        """Mencari gambar di Pixabay dengan parameter yang ditentukan"""
        
        # Validate inputs
        if not query.strip():
            await interaction.response.send_message(
                "❌ **Error:** Query pencarian tidak boleh kosong!", 
                ephemeral=True
            )
            return
            
        if amount is not None and (amount < 1 or amount > 5):
            await interaction.response.send_message(
                "❌ **Error:** Jumlah gambar harus antara 1-5!", 
                ephemeral=True
            )
            return
        
        # Defer response for longer processing
        await interaction.response.defer()
        
        # Prepare API parameters
        params = {
            "key": API.PIXABAY_KEY,
            "q": query.strip(),
            "lang": lang.value if lang else "id",
            "image_type": image_type.value if image_type else "all",
            "safesearch": "true" if safe_search else "false",
            "per_page": min(200, max(20, amount * 10)),  # Get more results for better randomization
            "min_width": 640,  # Ensure decent quality
            "min_height": 480,
            "order": "popular"  # Get popular images first
        }
        
        try:
            # Fetch images from API
            data = await self._fetch_images(params)
            
            if data is None:
                await interaction.followup.send(
                    "⚠️ **Error:** Gagal mengakses API Pixabay. Silakan coba lagi nanti.",
                    ephemeral=True
                )
                return
            
            hits = data.get("hits", [])
            total_hits = data.get("totalHits", 0)
            
            if not hits:
                await interaction.followup.send(
                    f"❌ **Tidak ada hasil** untuk pencarian: `{query}`\n"
                    f"💡 **Saran:** Coba gunakan kata kunci yang berbeda atau dalam bahasa Inggris."
                )
                return
            
            # Select random images from results
            final_amount = min(len(hits), amount or 3)
            selected_hits = random.sample(hits, final_amount)
            
            # Create embeds
            embeds: List[discord.Embed] = []
            for hit in selected_hits:
                embed = self._create_embed(hit, query)
                embeds.append(embed)
            
            # Create summary embed as first embed
            summary_embed = discord.Embed(
                title="🎨 Pixabay Search Results",
                description=f"Menampilkan **{final_amount}** dari **{total_hits:,}** hasil untuk: `{query}`",
                color=discord.Color.green()
            )
            
            # Add search parameters info
            search_info = []
            if lang:
                search_info.append(f"🌐 Bahasa: {lang.name}")
            if image_type:
                search_info.append(f"🖼️ Tipe: {image_type.name}")
            search_info.append(f"🔒 Safe Search: {'Aktif' if safe_search else 'Nonaktif'}")
            
            summary_embed.add_field(
                name="⚙️ Parameter Pencarian",
                value="\n".join(search_info),
                inline=False
            )
            
            # Insert summary at beginning
            embeds.insert(0, summary_embed)
            
            # Send results
            await interaction.followup.send(embeds=embeds)
            
            log.info(f"Pixabay search completed: query='{query}', results={final_amount}, user={interaction.user.id}")
            
        except Exception as e:
            log.error(f"Unexpected error in pixabay_search: {e}", exc_info=True)
            await interaction.followup.send(
                "🔧 **Error:** Terjadi kesalahan sistem. Silakan coba lagi nanti.",
                ephemeral=True
            )

    @pixabay_search.error
    async def pixabay_search_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        """Error handler for pixabay_search command"""
        log.error(f"Command error in pixabay_search: {error}", exc_info=True)
        
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "❌ **Error:** Terjadi kesalahan saat memproses perintah.",
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                "❌ **Error:** Terjadi kesalahan saat memproses perintah.",
                ephemeral=True
            )

async def setup(bot: commands.Bot) -> None:
    """Setup function to add the cog to the bot"""
    await bot.add_cog(PixabayCog(bot))