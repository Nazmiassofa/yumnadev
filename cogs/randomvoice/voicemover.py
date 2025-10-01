# FILE: cogs/voice_mover.py
import random
import logging
import discord

from .helper.data import CH_ANONIM_TARGET
from discord import app_commands
from discord.ext import commands

log = logging.getLogger(__name__)

class VoiceMover(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.target_channels = CH_ANONIM_TARGET
        self.target_chids = list(CH_ANONIM_TARGET.values())
        self.channel_id_to_name = {v: k for k, v in CH_ANONIM_TARGET.items()}
        self.pairs = [
            ('TC1', 'TC2'),
            ('TC3', 'TC4'),
        ]
        self.max_channel = 1
        self.target_guild = self.bot.main_guild_id
        # self.target_guild = 1406382441895035061

    def _human_count(self, channel: discord.abc.GuildChannel) -> int:
        if channel is None:
            return 0
        return sum(1 for m in channel.members if not m.bot)

    def _get_channel_by_name(self, guild: discord.Guild, name: str):
        cid = self.target_channels.get(name)
        if cid is None:
            return None
        return guild.get_channel(cid)

    async def choose_target_channel(self, guild: discord.Guild) -> discord.abc.GuildChannel | None:
        """
        Pilih channel target sesuai logika pairing dan kapasitas.
        Kembalikan channel (discord.VoiceChannel) atau None jika tidak ada slot.
        """
        available_channels = {}
        total_humans = 0
        for name, cid in self.target_channels.items():
            ch = guild.get_channel(cid)
            if ch is None:
                continue
            human_count = self._human_count(ch)
            total_humans += human_count
            if human_count < self.max_channel:
                available_channels[name] = ch

        if not available_channels:
            return None

        # Jika semua kosong -> random
        if total_humans == 0:
            return random.choice(list(available_channels.values()))

        # Prioritas pasangan
        priority_candidates = []
        for a_name, b_name in self.pairs:
            a_ch = guild.get_channel(self.target_channels.get(a_name))
            b_ch = guild.get_channel(self.target_channels.get(b_name))
            a_count = self._human_count(a_ch) if a_ch else 0
            b_count = self._human_count(b_ch) if b_ch else 0

            if a_count > 0 and b_name in available_channels:
                priority_candidates.append(available_channels[b_name])
            elif b_count > 0 and a_name in available_channels:
                priority_candidates.append(available_channels[a_name])

        if priority_candidates:
            return random.choice(priority_candidates)

        # fallback random
        return random.choice(list(available_channels.values()))

    async def move_member_to_anonym(self, member: discord.Member) -> tuple[bool, str]:
        """
        Public helper: coba pindahkan `member` ke salah satu CH_ANONIM_TARGET mengikuti aturan.
        Mengatur permission sementara, memindahkan member, dan rollback jika gagal.
        Return: (success: bool, message: str)
        """
        guild = member.guild
        if guild is None or guild.id != self.target_guild:
            return False, "Cog VoiceMover tidak dikonfigurasi untuk guild ini."

        target_channel = await self.choose_target_channel(guild)
        if target_channel is None:
            return False, "Semua channel tujuan penuh."

        # set permission overwrite
        try:
            await target_channel.set_permissions(
                member,
                overwrite=discord.PermissionOverwrite(
                    view_channel=True,
                    connect=True,
                    speak=True,
                    stream=True,
                    send_messages=True,
                    read_message_history=False
                ),
                reason="Anonym - temporary access (move_member_to_anonym)"
            )
        except discord.Forbidden:
            return False, "Bot tidak memiliki izin untuk mengatur permission channel."
        except Exception as e:
            log.exception("Gagal memberikan permission overwrite: %s", e)
            return False, "Gagal memberikan izin (exception)."

        # pindahkan member
        try:
            await member.move_to(target_channel, reason="Anonym auto-move from VoiceStateUpdate")
        except Exception as e:
            log.exception("Gagal memindahkan member: %s", e)
            # rollback permission
            try:
                await target_channel.set_permissions(member, overwrite=None, reason="Rollback after failed move")
            except Exception:
                pass
            return False, f"Gagal memindahkan member: {e}"

        # sukses
        return True, f"Berhasil memindahkan ke {target_channel.name}"

    @app_commands.command(name="anonim", description="Pindah ke channel anonim.")
    async def anonym(self, interaction: discord.Interaction):
        member = interaction.user
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Perintah ini hanya bisa digunakan di server.", ephemeral=True)
            return

        if guild.id != self.target_guild:
            await interaction.response.send_message("Hanya bisa digunakan di server utama!", ephemeral=True)
            return

        if not isinstance(member, discord.Member) or member.voice is None or member.voice.channel is None:
            await interaction.response.send_message("Kamu harus berada di voice channel untuk menggunakan perintah ini.", ephemeral=True)
            return

        ok, msg = await self.move_member_to_anonym(member)
        if not ok:
            await interaction.response.send_message(f"❌ {msg}", ephemeral=True)
            return

        await interaction.response.send_message(f"✅ Anda telah dipindahkan. ({msg})", ephemeral=True)
        
        notif = self.bot.get_cog("RandomVoiceMover")
        if notif:
            try:
                await notif._send_notification(member.guild, member, "anonim_message")
                
            except Exception as e:
                log.error(f"[ VOICE MOVER ] ---- Error on send notification as : {e}")

async def setup(bot):
    await bot.add_cog(VoiceMover(bot))
