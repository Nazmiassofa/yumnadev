import discord
import asyncio
import logging
import random

from discord.ext import commands
from discord import app_commands
from typing import Optional, List, Dict, Set, Tuple
from .helper.data import (
                          GUILD_TARGET,
                          CH_ANONIM_TARGET,
                          CH_TARGET,
                          CH_TRIGGER,
                          CH_NOTIF,
                          CH_CATEGORY,
                          ALLOWED_ROLES,
                          BOY,
                          GIRL)

log = logging.getLogger(__name__)

class RandomVoiceMover(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.trigger_vcid = CH_TRIGGER
        self.target_gid = GUILD_TARGET
        self.notification_chid = CH_NOTIF
        self.category_chid = CH_CATEGORY
        self.category_anonim = 1409061694914953236
        self.allowed_roled = ALLOWED_ROLES
        self.target_channels = CH_TARGET
        self.target_channels_anonim = CH_ANONIM_TARGET

        self.max_channel_users = 2
        self.last_message_id: Optional[int] = None
        self.boy_id = BOY
        self.girl_id = GIRL
        self.queue = []
        self.available_channels = {}
        self.preferred_channels = {}
        self.usage_dict = {}
        self.queue_lock = asyncio.Lock()

    async def cog_load(self):
        asyncio.create_task(self.loaded_cog())
        
    async def cog_unload(self):
        await self._permission_cleanup()
    
    async def loaded_cog(self):
        await self.bot.wait_until_ready()
        await self._permission_cleanup()
        log.info("[ CLEANING ALL ROLE ] --------- Load All Role Settings.")
        
    async def check_limit(self, user_id: int) -> tuple[bool, str]:
        key = f"anotherworld:limit:{user_id}"

        if await self.bot.redis.exists(key):
            ttl = await self.bot.redis.ttl(key)
            return False, f"Kamu sudah mencapai batas maksimal (2x).\n-# Tunggu {ttl//3600} jam {ttl%3600//60} menit lagi."

        return True, ""
        
    async def add_usage(self, user_id: int):
        count = self.usage_dict.get(user_id, 0) + 1

        if count >= 2:
            # push ke redis, reset memory
            await self.bot.redis.setex(f"anotherworld:limit:{user_id}", 4*3600, "blocked")
            self.usage_dict.pop(user_id, None)
        else:
            self.usage_dict[user_id] = count
            
    async def _notify_user_limit(self, member: discord.Member, msg: str):
        """Try to DM the user the limit message. If DM fails, log and try best-effort fallback (no visible channel spam)."""
        try:
            await member.send(msg)
        except discord.Forbidden:
            # Couldn't DM user (privacy settings). Log and try to fallback to notification channel (quietly).
            log.warning(f"[ LIMIT NOTIFY ] Cannot DM {member.display_name} (Forbidden).")
            return
                
    @app_commands.command(name="anotherworld", description="Pindah ke channel another-world.")
    async def anotherworld(self, interaction: discord.Interaction):

        try:
            guild = interaction.guild
        
            if guild is None:
                await interaction.response.send_message("Perintah ini hanya bisa digunakan di server.", ephemeral=True)
                return

            if guild.id != self.target_gid:
                await interaction.response.send_message("Perintah ini hanya berlaku di server utama yumna.", ephemeral=True)
                return

            # Resolve member dari guild
            member = guild.get_member(interaction.user.id) or await guild.fetch_member(interaction.user.id)
            if member is None:
                await interaction.response.send_message("Tidak dapat menemukan member Anda di server ini.", ephemeral=True)
                return

            if member.bot:
                await interaction.response.send_message("Bot tidak dapat menggunakan perintah ini.", ephemeral=True)
                return

            if not member.voice or not member.voice.channel:
                await interaction.response.send_message(
                    "Anda harus berada di voice channel terlebih dahulu.\n-# Silakan bergabung ke channel terlebih dahulu!",
                    ephemeral=True
                )
                return
            
            ok, msg = await self.check_limit(interaction.user.id)
            if not ok:
                await interaction.response.send_message(msg, ephemeral=True)
                return

            # Defer karena proses bisa memakan waktu -> kirim acknowledgement ephemeral segera
            await interaction.response.defer(ephemeral=True)

            # Tambah antrean (hindari duplikat)
            async with self.queue_lock:
                if member in self.queue:
                    await interaction.followup.send("Anda sudah berada di antrean pemindahan. Mohon tunggu proses.", ephemeral=True)
                    return

                self.queue.append(member)
                log.info(f"[ COMMAND CALL ] {member.display_name} ditambahkan ke antrean via slash [ another-world ]")

            try:
                await self.process_queue()
                await interaction.followup.send("✅ Anda berhasil dipindahkan ke channel **another-world**.", ephemeral=True)
                if not any(role.id in self.allowed_roled for role in member.roles):
                    try:
                        await self.add_usage(interaction.user.id)
                    except Exception as e:
                        log.error(f"[ VOICE LISTENER ] Failed to add usage for {member.display_name}: {e}", exc_info=True)
                else:
                    log.debug(f"[ VOICE LISTENER ] {member.display_name} memiliki allowed role, skip add_usage")
            except Exception as e:
                log.error(f"[ VOICE LISTENER ] Error processing queue after {member.display_name} join: {e}", exc_info=True)



        except discord.Forbidden:
            log.warning("[ COMMAND ] Tidak punya izin untuk merespon atau memindahkan member.", exc_info=True)
            try:
                # jika sudah deferred, gunakan followup; kalau belum, gunakan response
                if interaction.response.is_done():
                    await interaction.followup.send("Bot tidak punya izin yang diperlukan (send messages / move members / manage roles).", ephemeral=True)
                else:
                    await interaction.response.send_message("Bot tidak punya izin yang diperlukan (send messages / move members / manage roles).", ephemeral=True)
            except Exception:
                pass
        except Exception as e:
            log.error(f"[ COMMAND ] Error in another-world slash command: {e}", exc_info=True)
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(f"Terdapat error saat memproses perintah: {e}", ephemeral=True)
                else:
                    await interaction.response.send_message(f"Terdapat error saat memproses perintah: {e}", ephemeral=True)
            except Exception:
                pass

    # Helper function to format gender summary
    def _format_gender_summary(self, boys: int, girls: int, special: int) -> str:
        """Format gender summary for notification"""
        parts = []
        
        if boys > 0:
            parts.append(f"Boys: {boys}")
        if girls > 0:
            parts.append(f"Girls: {girls}")
        if special > 0:
            parts.append(f"Unknown: {special}")
        
        if not parts:
            return "No members"
        
        return " | ".join(parts)
    
    # Updated _send_notification function with member tracking and gender display
    async def _send_notification(self, guild: discord.Guild, member: discord.Member, event_type: str):
        try:
            channel = guild.get_channel(self.notification_chid)
            if not channel:
                log.debug(
                    f"[ VOICE MOVER ] Notification channel {self.notification_chid} not found"
                )
                return

            # Get current stats
            total_members, total_boys, total_girls, total_special = self._count_members_in_category(guild)
            # total_anonim, total_boys_diff, total_girls_diff, total_special_diff = self._count_members_in_anonim(guild)
            
            # Determine member's gender for display
            member_gender = self._get_member_gender(member)
            
            # Create gender summary
            gender_summary = self._format_gender_summary(total_boys, total_girls, total_special)
            # gender_anonim = self._format_gender_summary(total_boys_diff, total_girls_diff, total_special_diff)
            
            message_content = (
                f"**Theres someone with role ({member_gender}) has {event_type}**\n"
                f"> Total: {total_members} users\n"
                f"> {gender_summary}\n\n"
                f"https://discord.com/channels/{self.target_gid}/{self.trigger_vcid}"
            )
            
            message_anonim = (
                f"**Theres someone in anonymous voice**\n"
                f"> Total: {total_members} users\n"
                f"> {gender_summary}\n\n"
                f"join them with /anonim slash command."
                f"https://discord.com/channels/{self.target_gid}/{self.trigger_vcid}"
            )

            if event_type == "joined":
                if self.last_message_id:
                    try:
                        message = await channel.fetch_message(self.last_message_id)
                        await message.delete()
                    except Exception as e:
                        log.debug(
                            f"[ VOICE MOVER ] Could not delete old message: {e}"
                        )

                msg = await channel.send(message_content)
                self.last_message_id = msg.id
                return
            
            if event_type == "anonim_message":
                if self.last_message_id:
                    try:
                        message = await channel.fetch_message(self.last_message_id)
                        await message.delete()
                    except Exception as e:
                        log.debug(
                            f"[ VOICE MOVER ] Could not delete old message: {e}"
                        )

                msg = await channel.send(message_anonim)
                self.last_message_id = msg.id
                return

            if event_type == "left":
                if not self.last_message_id:
                    log.warning("[ VOICE MOVER ] --- Could not found old message")
                    return

                try:
                    message = await channel.fetch_message(self.last_message_id)
                    await message.edit(content=message_content)
                except Exception as e:
                    log.debug(
                        f"[ VOICE MOVER ] Could not edit old message: {e}"
                    )
                    return
                                
        except discord.Forbidden:
            log.warning("[ VOICE MOVER ] No permission to send notification")

        except Exception as e:
            log.error(f"[ VOICE MOVER ] Failed to send notification: {e}")

    # Updated _count_members_in_category function with gender counting
    def _count_members_in_category(self, guild: discord.Guild) -> Tuple[int, int, int, int]:
        """Count total members and their genders in category"""
        category = guild.get_channel(self.category_chid)
        if not category or not isinstance(category, discord.CategoryChannel):
            log.warning(f"[VOICE MOVER] Category {self.category_chid} not found")
            return 0, 0, 0, 0

        total_boys = 0
        total_girls = 0
        total_special = 0
        total_members = 0
        
        for channel in category.channels:
            if isinstance(channel, discord.VoiceChannel):
                boys, girls, special = self._count_gender_in_channel(channel)
                total_boys += boys
                total_girls += girls
                total_special += special
                total_members += (boys + girls + special)
        
        return total_members, total_boys, total_girls, total_special  
    
    def _count_members_in_anonim(self, guild: discord.Guild) -> Tuple[int, int, int, int]:
        """Count total members and their genders in category"""
        category = guild.get_channel(self.category_anonim)
        if not category or not isinstance(category, discord.CategoryChannel):
            log.warning(f"[VOICE MOVER] Category {self.category_chid} not found")
            return 0, 0, 0, 0

        total_boys_diff = 0
        total_girls_diff = 0
        total_special_diff = 0
        total_anonim = 0
        
        for channel in category.channels:
            if isinstance(channel, discord.VoiceChannel):
                boys, girls, special = self._count_gender_in_channel(channel)
                total_boys_diff += boys
                total_girls_diff += girls
                total_special_diff += special
                total_anonim += (boys + girls + special)
        
        return total_anonim, total_boys_diff, total_girls_diff, total_special_diff  
    
    
    # ------ PERMISSION ACCESS REMOVER
    #-------------------------------------------------------------------------
    async def _permission_remover(self, member: discord.Member, channel_id: int) -> bool:
        """Remove per-member channel overwrite for the given channel_id (restore defaults).
        Returns True on success, False otherwise.
        """
        try:
            channel = member.guild.get_channel(channel_id) or self.bot.get_channel(channel_id)
            if not channel:
                log.warning(f"[ PERM REMOVER ] Channel {channel_id} not found")
                return False

            # Remove per-member overwrite entirely.
            await channel.set_permissions(member, overwrite=None)
            log.info(f"[ PERM REMOVER ] Removed permission overwrite for {member.display_name} on channel {channel.id}")
            return True

        except discord.Forbidden:
            log.warning(f"[ PERM REMOVER ] No permission to remove channel overwrites for {member.display_name}")
            return False
        except Exception as e:
            log.error(f"[ PERM REMOVER ] Failed to remove permissions for {member.display_name}: {e}", exc_info=True)
            return False

    # ------ PERMISSION ACCESS GIVER
    #-------------------------------------------------------------------------
    async def _give_permission_access(self, member: discord.Member, tc_key: str) -> bool:
        """Set per-member channel permission overwrite for a target voice channel.
        Returns True on success, False otherwise.
        Permissions given: view_channel, connect, speak, stream, send_messages, read_message_history.
        """
        try:
            if tc_key not in self.target_channels:
                log.warning(f"[ PERM GIVER ] TC key {tc_key} not found in target_channels")
                return False

            channel_id = self.target_channels[tc_key]
            channel = member.guild.get_channel(channel_id) or self.bot.get_channel(channel_id)
            if not channel:
                log.warning(f"[ PERM GIVER ] Channel {channel_id} not found")
                return False

            # All channels are voice_channel per your note, but we include send_messages/read_history
            # as requested (these fields are valid PermissionOverwrite attributes even if not
            # meaningful for voice — harmless to set).
            overwrite = discord.PermissionOverwrite(
                view_channel=True,
                connect=True,
                speak=True,
                stream=True,
                send_messages=True,
                read_message_history=False
            )

            await channel.set_permissions(member, overwrite=overwrite)
            log.info(f"[ PERM GIVER ] Set permission overwrite for {member.display_name} on channel {channel.id}")
            return True

        except discord.Forbidden:
            log.warning(f"[ PERM GIVER ] No permission to set channel overwrites for {member.display_name}")
            return False
        except Exception as e:
            log.error(f"[ PERM GIVER ] Failed to set permissions for {member.display_name}: {e}", exc_info=True)
            return False


    # ------ GET AVAILABLE CHANNELS
    #-------------------------------------------------------------------------
    def _get_available_channels(self, guild: discord.Guild) -> Dict[str, int]:
        """Get available channels by tracking target_channels slot"""
        available = {}
        
        for tc_key, channel_id in self.target_channels.items():
            channel = guild.get_channel(channel_id)
            if not channel or not isinstance(channel, discord.VoiceChannel):
                continue
            
            # Count non-bot members
            member_count = len([m for m in channel.members if not m.bot])
            if member_count < self.max_channel_users:
                available[tc_key] = self.max_channel_users - member_count
                
        return available

    def _get_preferred_channel(self, guild: discord.Guild, boy_count: int, girl_count: int, special_count: int = 0) -> Optional[str]:
        """Get preferred channel while avoiding channels with special cases (unless we're placing special cases)"""
        available = self._get_available_channels(guild)
        
        if not available:
            log.info("[ PREFERRED CHANNEL ] No available channels")
            return None
        
        # For special cases, prioritize empty channels ONLY
        if special_count > 0:
            empty_channels = []
            for tc_key, slots in available.items():
                channel_id = self.target_channels[tc_key]
                channel = guild.get_channel(channel_id)
                if not channel:
                    continue
                
                current_members = [m for m in channel.members if not m.bot]
                if len(current_members) == 0 and slots >= special_count:
                    empty_channels.append(tc_key)
            
            if empty_channels:
                log.info(f"[ PREFERRED CHANNEL ] Found {len(empty_channels)} empty channels for special cases")
                return random.choice(empty_channels)
            else:
                log.warning("[ PREFERRED CHANNEL ] No empty channels available for special cases")
                return None  # STRICT: Special cases ONLY go to empty channels
        
        # For normal members (boys/girls), AVOID channels with special cases
        valid_channels = []
        
        for tc_key, slots in available.items():
            channel_id = self.target_channels[tc_key]
            channel = guild.get_channel(channel_id)
            if not channel:
                continue
            
            # CRITICAL: Skip channels that contain special cases
            if self._has_special_case_in_channel(channel):
                log.debug(f"[ PREFERRED CHANNEL ] Skipping {tc_key} - contains special case member(s)")
                continue
            
            # Use accurate counting (excludes special cases)
            current_boys, current_girls, current_special = self._count_gender_in_channel(channel)
            current_total = current_boys + current_girls  # Don't count special cases
            
            # Check if we can add the requested combination
            total_to_add = boy_count + girl_count
            if current_total + total_to_add > self.max_channel_users:
                continue
            
            if current_total == 0:
                # Empty channel (no boys/girls, might have special cases but we already filtered those out)
                valid_channels.append(tc_key)
            elif current_total == 1:
                # One normal person in channel - apply mixed gender rules
                if current_boys == 1 and girl_count > 0 and boy_count == 0:
                    # Has boy, adding girl(s) - good
                    valid_channels.append(tc_key)
                elif current_girls == 1 and boy_count > 0 and girl_count == 0:
                    # Has girl, adding boy(s) - good
                    valid_channels.append(tc_key)
                elif current_boys == 1 and boy_count > 0 and girl_count == 0:
                    # Has boy, adding more boys - allow
                    valid_channels.append(tc_key)
                elif current_girls == 1 and girl_count > 0 and boy_count == 0:
                    # Has girl, adding more girls - allow
                    valid_channels.append(tc_key)
        
        if not valid_channels:
            log.debug("[ PREFERRED CHANNEL ] No valid channels for normal members (avoiding special case channels)")
            return None
        
        # Prioritize mixed gender outcomes
        mixed_priority_channels = []
        for tc_key in valid_channels:
            channel_id = self.target_channels[tc_key]
            channel = guild.get_channel(channel_id)
            if not channel:
                continue
            
            current_boys, current_girls, _ = self._count_gender_in_channel(channel)
            final_boys = current_boys + boy_count
            final_girls = current_girls + girl_count
            
            if final_boys > 0 and final_girls > 0:
                mixed_priority_channels.append(tc_key)
        
        # Return mixed gender channel if available, otherwise any valid channel
        target_list = mixed_priority_channels if mixed_priority_channels else valid_channels
        selected = random.choice(target_list)
        
        log.debug(f"[ PREFERRED CHANNEL ] Selected {selected} for normal members (boy:{boy_count}, girl:{girl_count})")
        return selected
    
    def _has_special_case_in_channel(self, channel: discord.VoiceChannel) -> bool:
        """Check if channel contains any special case members"""
        for member in channel.members:
            if member.bot:
                continue
            if self._is_special_case(member):
                return True
        return False

    def _count_gender_in_channel(self, channel: discord.VoiceChannel) -> Tuple[int, int, int]:
        """Count boys, girls, and special cases in channel (excluding bots)"""
        boys = 0
        girls = 0
        special_cases = 0
        
        for member in channel.members:
            if member.bot:
                continue
                
            if self._is_special_case(member):
                special_cases += 1
            elif self._is_boy(member):
                boys += 1
            elif self._is_girl(member):
                girls += 1
        
        return boys, girls, special_cases

    def _is_special_case(self, member: discord.Member) -> bool:
        """Check if member is a special case (dual role or no role)"""
        is_boy = self._is_boy(member)
        is_girl = self._is_girl(member)
        return (is_boy and is_girl) or (not is_boy and not is_girl)

    def _is_boy(self, member: discord.Member) -> bool:
        """Check if member has boy role"""
        return any(role.id == self.boy_id for role in member.roles)
    
    def _is_girl(self, member: discord.Member) -> bool:
        """Check if member has girl role"""
        return any(role.id == self.girl_id for role in member.roles)

    def _classify_members_enhanced(self, members: List[discord.Member]) -> Tuple[List[discord.Member], List[discord.Member], List[discord.Member]]:
        """Classify members into boys, girls, and special cases (dual role or no role)"""
        boys = []
        girls = []
        special_cases = []
        
        for member in members:
            is_boy = self._is_boy(member)
            is_girl = self._is_girl(member)
            
            if is_boy and is_girl:
                # Dual role - treat as special case
                special_cases.append(member)
            elif not is_boy and not is_girl:
                # No gender role - treat as special case
                special_cases.append(member)
            elif is_boy:
                boys.append(member)
            elif is_girl:
                girls.append(member)

        return boys, girls, special_cases

    # Helper function to get member gender display
    def _get_member_gender(self, member: discord.Member) -> str:
        """Get display string for member's gender"""
        is_boy = self._is_boy(member)
        is_girl = self._is_girl(member)
        
        if is_boy and is_girl:
            return "Double gender"
        elif is_boy:
            return "Boy"
        elif is_girl:
            return "Girl"
        else:
            return "No Role"

    # ------ STATE VOICE LISTENER
    #-------------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot:  # Skip bots
            return
        
        # Only process events from target guild
        if member.guild.id != self.target_gid:
            return
        
        # Only process if channel actually changed
        before_channel_id = before.channel.id if before.channel else None
        after_channel_id = after.channel.id if after.channel else None
        
        if before_channel_id == after_channel_id:
            return
        
        # Member leaves from target_channels
        if before_channel_id and (before_channel_id in self.target_channels.values() or before_channel_id in self.target_channels_anonim.values()):
            await self._permission_remover(member, before_channel_id)
            log.info(f"[ VOICE LISTENER ] {member.display_name} left target channel {before_channel_id}")
            
            # Updated notification call with member info
            await self._send_notification(member.guild, member, "left")
        
        # Member joins trigger channel -> apply same limit behavior as /anotherworld
        if after_channel_id == self.trigger_vcid:
            try:
                ok, msg = await self.check_limit(member.id)
            except Exception as e:
                log.error(f"[ VOICE LISTENER ] Error checking limit for {member.display_name}: {e}", exc_info=True)
                ok, msg = True, ""

            if not ok:
                # Try to fallback via VoiceMover cog, prefer to move user to anonym if possible.
                mover = self.bot.get_cog('VoiceMover')
                if mover:
                    try:
                        moved_ok = await mover.move_member_to_anonym(member)
                    except Exception as e:
                        log.error(f"[ VOICE LISTENER ] Error calling VoiceMover.move_member_to_anonym: {e}", exc_info=True)
                        moved_ok,  f"Exception: {e}"

                    if moved_ok:
                        # Successful auto-move: notify user with mover message + reason (limit)
                        user_dm = (
                            f"Another-World limit (2x / 4 hours).\n"
                            f"-# Dipindahkan sementara ke anonymous-voice."
                        )
                        try:
                            await self._notify_user_limit(member, user_dm)
                            await self._send_notification(member.guild, member, "anonim_message") 
                        except Exception:
                            log.debug("[ VOICE LISTENER ] Gagal mengirim DM notifikasi pindah (silently ignore).")
                        log.info(f"[ VOICE LISTENER ] {member.display_name} auto-moved to anonym channel")
                        return

                    # mover exists but failed -> use mover message as reason for fallback notify
                    fallback_msg = (
                        f"Another-World limit (2x / 4 hours).\n"
                        f"-# Gagal memindahkan ke-anotherworld."
                    )
                    log.warning(f"[ VOICE LISTENER ] move_member_to_anonym returned failure")

                    # Try graceful fallback: disconnect the user (like original logic)
                    try:
                        await member.move_to(None, reason="anotherworld usage limit reached (mover fallback)")
                    except discord.Forbidden:
                        log.warning(f"[ VOICE LISTENER ] No permission to disconnect {member.display_name}")
                    except Exception as e:
                        log.error(f"[ VOICE LISTENER ] Failed to disconnect {member.display_name}: {e}", exc_info=True)

                    # Notify user about the failure + limit (DM or quiet admin channel)
                    try:
                        await self._notify_user_limit(member, fallback_msg)
                    except Exception as e:
                        log.debug(f"[ VOICE LISTENER ] Failed to notify {member.display_name} about fallback: {e}")
                    return

                # If no mover cog available: original behavior (disconnect + notify using check_limit msg)
                try:
                    await member.move_to(None, reason="anotherworld usage limit reached")
                except discord.Forbidden:
                    log.warning(f"[ VOICE LISTENER ] No permission to disconnect {member.display_name}")
                except Exception as e:
                    log.error(f"[ VOICE LISTENER ] Failed to disconnect {member.display_name}: {e}", exc_info=True)

                # Notify user about the limit (same message as slash)
                try:
                    await self._notify_user_limit(member, msg)
                except Exception as e:
                    log.debug(f"[ VOICE LISTENER ] Failed to notify {member.display_name} about limit: {e}")
                return


            async with self.queue_lock:
                if member in self.queue:
                    log.debug(f"[ VOICE LISTENER ] {member.display_name} already in queue")
                    return
                self.queue.append(member)
                log.info(f"[ VOICE LISTENER ] {member.display_name} added to queue via voice trigger")

            # Attempt to process queue and then record usage (mirror slash behavior)
            try:
                await self.process_queue()
                if not any(role.id in self.allowed_roled for role in member.roles):
                    try:
                        await self.add_usage(member.id)
                    except Exception as e:
                        log.error(f"[ VOICE LISTENER ] Failed to add usage for {member.display_name}: {e}", exc_info=True)
                else:
                    log.debug(f"[ VOICE LISTENER ] {member.display_name} memiliki allowed role, skip add_usage")
            except Exception as e:
                log.error(f"[ VOICE LISTENER ] Error processing queue after {member.display_name} join: {e}", exc_info=True)

    async def process_queue(self):
        """Process queue with strict separation between special cases and normal members"""
        async with self.queue_lock:
            if len(self.queue) == 0:
                log.debug("[ QUEUE ] No members in queue")
                return
            
            guild = self.bot.get_guild(self.target_gid)
            if not guild:
                log.error("[ QUEUE ] Target guild not found")
                return
            
            processed = []
            
            while len(self.queue) > 0:
                available = self._get_available_channels(guild)
                if not available:
                    log.warning("[ QUEUE ] No available channels, stopping processing")
                    break
                
                # Enhanced classification
                boys, girls, special_cases = self._classify_members_enhanced(self.queue)
                
                log.debug(f"[ QUEUE ] Current queue - Boys: {len(boys)}, Girls: {len(girls)}, Special: {len(special_cases)}")
                
                members_to_move = []
                boy_count = girl_count = special_count = 0
                
                # PHASE 1: STRICT - Handle special cases ONLY to empty channels
                if len(special_cases) > 0:
                    # Try single special case first
                    members_to_move = [special_cases[0]]
                    special_count = 1
                    
                    # Try pair if we have 2+ special cases
                    if len(special_cases) >= 2:
                        members_to_move = [special_cases[0], special_cases[1]]
                        special_count = 2
                    
                    tc_key = self._get_preferred_channel(guild, 0, 0, special_count)
                    if tc_key:
                        success = await self._move_members_to_channel(members_to_move, tc_key, guild)
                        if success:
                            for member in members_to_move:
                                if member in self.queue:
                                    self.queue.remove(member)
                            processed.extend(members_to_move)
                            log.debug(f"[ QUEUE ] Successfully moved {len(members_to_move)} special case(s) to empty channel {tc_key}")
                            continue
                        else:
                            log.warning("[ QUEUE ] Failed to move special cases")
                            break
                    else:
                        log.warning("[ QUEUE ] No empty channels available for special cases - they will wait in queue")
                        # Don't break - continue with normal members, special cases will wait
                
                # PHASE 2: Handle normal members (boys/girls) - AVOID special case channels
                members_to_move = []
                if len(boys) >= 1 and len(girls) >= 1:
                    # Mixed gender pair - ideal
                    members_to_move = [boys[0], girls[0]]
                    boy_count, girl_count = 1, 1
                elif len(boys) >= 2:
                    # Two boys
                    members_to_move = [boys[0], boys[1]]
                    boy_count, girl_count = 2, 0
                elif len(girls) >= 2:
                    # Two girls
                    members_to_move = [girls[0], girls[1]]
                    boy_count, girl_count = 0, 2
                elif len(boys) == 1:
                    # Single boy
                    members_to_move = [boys[0]]
                    boy_count, girl_count = 1, 0
                elif len(girls) == 1:
                    # Single girl
                    members_to_move = [girls[0]]
                    boy_count, girl_count = 0, 1
                
                if not members_to_move:
                    if len(special_cases) > 0:
                        log.debug("[ QUEUE ] Only special cases remaining, but no empty channels available")
                    else:
                        log.warning("[ QUEUE ] No valid combinations found")
                    break
                
                # Get channel for normal members (will avoid special case channels)
                tc_key = self._get_preferred_channel(guild, boy_count, girl_count, 0)
                if not tc_key:
                    log.debug("[ QUEUE ] No valid channels for normal members (all clean channels may be full)")
                    break
                
                # Move normal members
                success = await self._move_members_to_channel(members_to_move, tc_key, guild)
                if success:
                    for member in members_to_move:
                        if member in self.queue:
                            self.queue.remove(member)
                    processed.extend(members_to_move)
                    log.info(f"[ QUEUE ] Successfully moved {len(members_to_move)} normal member(s) to {tc_key}")
                else:
                    log.debug("[ QUEUE ] Failed to move normal members, stopping processing")
                    break
            
            # Report any remaining special cases
            remaining_special = [m for m in self.queue if self._is_special_case(m)]
            if remaining_special:
                log.debug(f"[ QUEUE ] {len(remaining_special)} special case member(s) remain in queue (no empty channels)")
            
            # Updated notification call - send notification for the first processed member as representative
            if processed:
                await asyncio.sleep(1)
                await self._send_notification(guild, processed[0], "joined")

    async def _move_members_to_channel(self, members: List[discord.Member], tc_key: str, guild: discord.Guild) -> bool:
        """Move members to target channel and give them appropriate roles"""
        try:
            channel_id = self.target_channels[tc_key]
            target_channel = guild.get_channel(channel_id)
            
            if not target_channel or not isinstance(target_channel, discord.VoiceChannel):
                log.error(f"[ MOVE MEMBERS ] Target channel {channel_id} not found")
                return False
            
            # Check if channel has space
            current_count = len([m for m in target_channel.members if not m.bot])
            if current_count + len(members) > self.max_channel_users:
                log.debug(f"[ MOVE MEMBERS ] Channel {tc_key} would exceed capacity")
                return False
            
            # Give roles first, then move
            success_count = 0
            for member in members:
                # Give role access
                role_given = await self._give_permission_access(member, tc_key)
                if not role_given:
                    log.debug(f"[ MOVE MEMBERS ] Failed to give role to {member.display_name}")
                    continue
                
                await asyncio.sleep(0.5)
                
                # Move member
                try:
                    if member.voice and member.voice.channel:
                        await member.move_to(target_channel)
                        success_count += 1
                        log.info(f"[ MOVE MEMBERS ] Moved {member.display_name} to {tc_key}")
                    else:
                        log.warning(f"[ MOVE MEMBERS ] {member.display_name} not in voice channel")
                except discord.HTTPException as e:
                    log.error(f"[ MOVE MEMBERS ] Failed to move {member.display_name}: {e}")
                except Exception as e:
                    log.error(f"[ MOVE MEMBERS ] Unexpected error moving {member.display_name}: {e}")
            
            return success_count > 0
            
        except Exception as e:
            log.error(f"[ MOVE MEMBERS ] Failed to move members to {tc_key}: {e}")
            return False
        

# ------ PERMISSION CLEANUP PROCESSING 
#-------------------------------------------------------------------------   
    async def _permission_cleanup(self):
        guild = self.bot.get_guild(self.target_gid)
        if guild is None:
            log.warning("[ PERM CLEANUP ] Target guild not found")
            return

        try:
            # Phase 1: Collect all members currently inside target voice channels
            target_member_ids: Set[int] = set()
            for tc_key, channel_id in self.target_channels.items():
                channel = guild.get_channel(channel_id)
                if not isinstance(channel, discord.VoiceChannel):
                    continue

                for member in channel.members:
                    if not member.bot:
                        target_member_ids.add(member.id)

            log.debug(f"[ PERM CLEANUP ] Found {len(target_member_ids)} members currently in target channels")

            # Phase 2: Prepare cleanup tasks (remove per-member overwrites if member not present)
            cleanup_tasks = []
            for tc_key, channel_id in self.target_channels.items():
                channel = guild.get_channel(channel_id)
                if not isinstance(channel, discord.VoiceChannel):
                    continue

                # `.overwrites` is a mapping of target(Role|Member) -> PermissionOverwrite
                try:
                    overwrites_items = list(channel.overwrites.items())
                except Exception:
                    # fallback: if attribute unavailable, skip channel
                    log.debug(f"[ PERM CLEANUP ] Could not read overwrites for channel {channel_id}")
                    continue

                for target, overwrite in overwrites_items:
                    # Only consider per-member overwrites (not role overwrites)
                    if isinstance(target, discord.Member):
                        member = target
                        if member.bot:
                            continue
                        if member.id not in target_member_ids:
                            # schedule removal
                            cleanup_tasks.append(self._safe_remove_overwrite(channel, member))

            # Phase 3: Execute removals concurrently
            if cleanup_tasks:
                results = await asyncio.gather(*cleanup_tasks, return_exceptions=True)
                success_count = sum(1 for r in results if r is True)
                log.debug(f"[ PERM CLEANUP ] Completed. Successfully removed {success_count} overwrites")
            else:
                log.debug("[ PERM CLEANUP ] No per-member overwrites to remove")

        except Exception as e:
            log.error(f"[ PERM CLEANUP ] Unexpected error: {str(e)}")
            raise

    async def _safe_remove_overwrite(self, channel: discord.abc.GuildChannel, member: discord.Member) -> bool:
        """Helper: remove per-member overwrite from a specific channel, safely."""
        try:
            await channel.set_permissions(member, overwrite=None)
            log.debug(f"[ PERM CLEANUP ] Removed overwrite for {member.display_name} on {channel.id}")
            return True
        except discord.Forbidden:
            log.warning(f"[ PERM CLEANUP ] No permission to remove overwrite for {member.display_name} on {channel.id}")
        except Exception as e:
            log.error(f"[ PERM CLEANUP ] Failed to remove overwrite for {member.display_name} on {channel.id}: {e}")
        return False
    
    def _debug_channel_state(self, guild: discord.Guild):
        """Debug function to log current state of all target channels"""
        log.debug("[ DEBUG ] Current channel states:")
        for tc_key, channel_id in self.target_channels.items():
            channel = guild.get_channel(channel_id)
            if not channel:
                continue
                
            boys, girls, special = self._count_gender_in_channel(channel)
            has_special = self._has_special_case_in_channel(channel)
            
            log.debug(f"  {tc_key}: Boys={boys}, Girls={girls}, Special={special}, HasSpecial={has_special}")    

    @commands.command(name='cleanup', hidden=True)
    @commands.is_owner()
    async def _cleanup_command(self, ctx):
        message = await ctx.reply("Clean another-world cache...")
        try:
            await self._permission_cleanup()
            await message.edit(content="-# ✅ Hapus cache selesai!\n")
        except Exception as e:
            await message.edit(content=f"-# Gagal membersihkan role: {str(e)}")
            raise

    @commands.command(name='debug_another', hidden=True)
    @commands.is_owner()
    async def _debug_channels_command(self, ctx):
        """Debug command to show channel states"""
        guild = self.bot.get_guild(self.target_gid)
        if not guild:
            await ctx.reply("Target guild not found")
            return
            
        self._debug_channel_state(guild)
        await ctx.reply("Channel states logged to console")

async def setup(bot):
    await bot.add_cog(RandomVoiceMover(bot))