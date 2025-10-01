import discord

async def cooldown_embed(remaining: float) -> discord.Embed:
    embed = discord.Embed(
        title="Tunggu Sebentar!",
        description=f"Yumna lelah...\nCoba lagi dalam **{remaining:.1f} detik**.",
        color=discord.Color.orange()
    )
    return embed

async def daily_cooldown(remaining: float) -> discord.Embed:
    embed = discord.Embed(
        title="Tunggu!",
        description=f"Kamu sedang cooldown...\nCoba lagi dalam **{remaining:.1f} detik**.",
        color=discord.Color.orange()
    )
    return embed

#----------------- UNTUK BOT.PY
#----------------------------------------------------------------------------------
class EmbedBasicCommands:
    @staticmethod
    def NotFound(ctx):
        embed = discord.Embed(
            title="❌ Command Tidak Dikenali",
            description=f"{ctx.author.mention}, aku tidak mengerti apa yang kamu maksud.",
            color=discord.Color.red()
        )
        embed.set_footer(text="Coba ketik v!help untuk melihat daftar command yang tersedia")
        return embed

    @staticmethod
    def MissingArgument(ctx):
        embed = discord.Embed(
            title="⚠️ Argument Tidak Lengkap",
            description=f"{ctx.author.mention}, kurang argumen, kasih aku command yang lengkap.",
            color=discord.Color.orange()
        )
        embed.set_footer(text="Periksa kembali command yang kamu ketik")
        return embed

    @staticmethod
    def MissingPermission():
        embed = discord.Embed(
            title="⛔ Izin Tidak Cukup",
            description="Maaf, kamu tidak memiliki izin untuk perintah ini.",
            color=discord.Color.dark_red()
        )
        return embed

    @staticmethod
    def GenericError(ctx):
        embed = discord.Embed(
            title="❌ Terjadi Kesalahan",
            description=f"{ctx.author.mention}, maaf ada kesalahan.",
            color=discord.Color.red()
        )
        embed.set_footer(text="Silakan coba lagi nanti atau hubungi admin")
        return embed

#----------------- UNTUK VOICE INFO
#----------------------------------------------------------------------------------
class VoiceCommands:
    @staticmethod
    def NotCounted(ctx):
        embed = discord.Embed(
            title="⚠️ Aktifkan VoiceCounter",
            description=f"{ctx.author.mention}, maaf kamu tidak mengaktifkan VoiceCounter.",
            color=discord.Color.red()
        )
        embed.set_footer(text="Gunakan `v!countme on/off`")
        return embed