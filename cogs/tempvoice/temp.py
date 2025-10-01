import logging
import asyncio
import discord
from typing import Dict, Set, Optional, Any
from contextlib import asynccontextmanager

from discord.ext import commands
from discord import app_commands
from .database.db_manager import TempVoiceDatabaseMan as db
from .database.redis import RedisManager as redis

from utils.data.emot import (
    HIDE, HORIZONTAL, PUBLIC, EDIT, LIMIT, 
    PRIVATE, LONCENG, RANDOM
)

log = logging.getLogger(__name__)


class LimitChannelModal(discord.ui.Modal, title="Atur User Limit"):
    """Modal for setting user limit on voice channels."""
    
    def __init__(self, channel: discord.VoiceChannel):
        super().__init__()
        self.channel = channel
        self.limit = discord.ui.TextInput(
            label="Batas Pengguna",
            placeholder="Masukkan angka (0 untuk tanpa batas)",
            required=True,
            max_length=3  # Reasonable limit for voice channels
        )
        self.add_item(self.limit)

    async def on_submit(self, interaction: discord.Interaction):
        """Handle form submission."""
        try:
            limit_value = int(self.limit.value)
            if limit_value < 0 or limit_value > 99:  # Discord's max is 99
                await interaction.response.send_message(
                    "❌ Masukkan angka antara 0-99!", ephemeral=True
                )
                return

            await self.channel.edit(user_limit=limit_value)
            await interaction.response.send_message(
                f"✅ User limit diatur ke {limit_value}", ephemeral=True
            )
            log.info(f"User limit for {self.channel.name} changed to {limit_value}")
            
        except ValueError:
            await interaction.response.send_message(
                "❌ Masukkan angka yang valid!", ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Bot tidak memiliki izin!", ephemeral=True
            )
        except discord.HTTPException as e:
            log.error(f"HTTP error when editing channel limit: {e}")
            await interaction.response.send_message(
                "❌ Terjadi kesalahan, coba lagi nanti!", ephemeral=True
            )


class ChangeChannelNameModal(discord.ui.Modal, title="Ubah Nama Channel"):
    """Modal for changing voice channel name."""
    
    def __init__(self, channel: discord.VoiceChannel):
        super().__init__()
        self.channel = channel
        self.new_name = discord.ui.TextInput(
            label="Nama Baru",
            placeholder="Masukkan nama baru...",
            required=True,
            min_length=2,
            max_length=100
        )
        self.add_item(self.new_name)

    async def on_submit(self, interaction: discord.Interaction):
        """Handle form submission."""
        new_name = self.new_name.value.strip()
        
        try:
            await self.channel.edit(name=new_name)
            await interaction.response.send_message(
                f"✅ Nama diubah menjadi: {new_name}", ephemeral=True
            )
            log.info(f"Channel {self.channel.id} renamed to {new_name}")
            
        except discord.HTTPException as e:
            log.error(f"HTTP error when renaming channel: {e}")
            await interaction.response.send_message(
                f"❌ Gagal mengubah nama: {str(e)[:100]}", ephemeral=True
            )


class VoiceChannelConfigView(discord.ui.View):
    """View for voice channel configuration."""
    
    def __init__(self, channel: discord.VoiceChannel, owner_id: int, bot):
        super().__init__(timeout=None)
        self.channel = channel
        self.owner_id = owner_id
        self.bot = bot

        # Define select options
        options = [
            discord.SelectOption(
                label="Public", emoji=f"{PUBLIC}", value="public", 
                description="Atur channel jadi publik"
            ),
            discord.SelectOption(
                label="Private", emoji=f"{PRIVATE}", value="private", 
                description="Atur channel jadi privat"
            ),
            discord.SelectOption(
                label="Hide", emoji=f"{HIDE}", value="hide", 
                description="Sembunyikan channel"
            ),
            discord.SelectOption(
                label="Random Name", emoji=f"{RANDOM}", value="random", 
                description="Acak nama channel"
            ),
            discord.SelectOption(
                label="Limit", emoji=f"{LIMIT}", value="limit", 
                description="Atur batas user"
            ),
            discord.SelectOption(
                label="Rename", emoji=f"{EDIT}", value="rename", 
                description="Ubah nama channel"
            )
        ]
        
        select = discord.ui.Select(
            placeholder=" 🔧 Select Opsi...", 
            options=options,
            custom_id=f"vcfg_{channel.id}"
        )
        select.callback = self.select_action
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Check if user is authorized to use this view."""
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "❌ Hanya owner channel yang bisa menggunakan ini!", ephemeral=True
            )
            return False
        return True

    async def select_action(self, interaction: discord.Interaction):
        """Handle select menu interaction."""
        select = interaction.data.get('values', [])
        if not select:
            return
            
        choice = select[0]
        
        # Handle modals separately
        if choice == "limit":
            await interaction.response.send_modal(LimitChannelModal(self.channel))
            return
        elif choice == "rename":
            await interaction.response.send_modal(ChangeChannelNameModal(self.channel))
            return

        # Defer for other actions
        await interaction.response.defer(ephemeral=True)

        try:
            await self._handle_channel_action(choice, interaction)
        except Exception as e:
            log.error(f"Error in select_action {choice}: {e}", exc_info=True)
            await interaction.followup.send(
                "❌ Terjadi kesalahan saat menjalankan aksi.", ephemeral=True
            )

    async def _handle_channel_action(self, choice: str, interaction: discord.Interaction):
        """Handle channel configuration actions."""
        guild = interaction.guild
        key = f"yumna:temp_channels:{self.channel.id}"
        everyone = guild.default_role
        eo = self.channel.overwrites_for(everyone)

        if choice == "public":
            eo.view_channel = True
            eo.connect = True 
            eo.use_embedded_activities = True
            await self.bot.redis.hset(key, mapping={"status": "public"})
            
        elif choice == "private":
            eo.view_channel = True
            eo.connect = False
            eo.use_embedded_activities = True
            await self.bot.redis.hset(key, mapping={"status": "private"})
            
        elif choice == "hide":
            eo.view_channel = False
            await self.bot.redis.hset(key, mapping={"status": "hidden"})
            
        elif choice == "random":
            await self._handle_random_name(interaction, key)
            return

        # Apply overwrites for non-random actions
        await self.channel.set_permissions(everyone, overwrite=eo)
        
        # Ensure owner permissions
        owner = guild.get_member(self.owner_id)
        if owner:
            perm = discord.PermissionOverwrite(
                        view_channel=True, connect=True, speak=True,
                        mute_members=True, deafen_members=True,
                        move_members=True, manage_channels=True,
                        read_message_history=True, send_messages=True,
                        stream=True, use_application_commands=True,
                        send_voice_messages=True, use_embedded_activities=True
                    )            


            await self.channel.set_permissions(owner, overwrite=perm)

        await interaction.followup.send(
            f"✅ Berhasil\n-# Channel diubah menjadi '{choice}'!", ephemeral=True
        )

    async def _handle_random_name(self, interaction: discord.Interaction, key: str):
        """Handle random name generation with collision avoidance."""
        category = self.channel.category
        existing = {c.name for c in category.voice_channels} if category else set()

        # Try to get unique name with limited attempts
        for attempt in range(10):
            name = await db.get_random_name_ch()
            if not name or name not in existing:
                break
        else:
            await interaction.followup.send(
                "❌ Gagal menghasilkan nama unik setelah 10 percobaan.", 
                ephemeral=True
            )
            return

        # Use fallback if no name generated
        if not name:
            name = f"Channel-{self.channel.id % 1000}"

        await self.channel.edit(name=name)
        await self.bot.redis.hset(key, mapping={"name": name})
        await interaction.followup.send(
            f"✅ Nama channel diacak menjadi: **{name}**", ephemeral=True
        )


class VoiceTemp(commands.Cog):
    """Temporary voice channel management cog."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.temp_channels: Set[int] = set()
        self.temp_channel_views: Dict[int, VoiceChannelConfigView] = {}
        self.active_channels: Dict[int, int] = {}  # user_id -> channel_id
        self.channel_owners: Dict[int, int] = {}   # channel_id -> user_id
        self.channel_categories: Dict[int, str] = {}
        self.lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None
        
    async def cog_load(self):
        """Initialize the cog."""
        self._cleanup_task = asyncio.create_task(self._delayed_cleanup())

    async def cog_unload(self):
        """Clean up when cog is unloaded."""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            
        # Stop all active views
        for view in self.temp_channel_views.values():
            view.stop()
        self.temp_channel_views.clear()

    async def _delayed_cleanup(self):
        """Delayed cleanup after bot is ready."""
        try:
            await self.bot.wait_until_ready()
            await self.cleanup_temp_channels()
            log.info("[ VOICE TEMP ] --------------- [ START CLEANUP VOICE CHANNEL ]")
        except Exception as e:
            log.error(f"Error in delayed cleanup: {e}", exc_info=True)

    @asynccontextmanager
    async def _safe_lock(self):
        """Context manager for safe lock acquisition."""
        try:
            async with self.lock:
                yield
        except Exception as e:
            log.error(f"Error in lock context: {e}", exc_info=True)
            raise

    @commands.Cog.listener()
    async def on_voice_state_update(self, 
                                    member: discord.Member, 
                                    before: discord.VoiceState, 
                                    after: discord.VoiceState):
        """Handle voice state updates."""
        if member.bot:
            return
        
        before_id = before.channel.id if before.channel else None
        after_id  = after.channel.id  if after.channel  else None
        if before_id == after_id:
            return

        guild = member.guild
        
        try:
            settings = await self._get_guild_settings(guild.id)
            if not settings:
                return

            master_id = settings.get('master_voice_chid')
            if master_id is None:
                return

            # Handle master channel join
            if after.channel and after.channel.id == master_id:
                await self._on_master_join(member, after, guild, settings)
                
            # Handle temp channel leave
            if before.channel and before.channel.id in self.temp_channels:
                await self._on_temp_leave(member, before, guild)
                
        except Exception as e:
            log.error(f"Error in voice state update: {e}", exc_info=True)

    async def _get_guild_settings(self, guild_id: int) -> Optional[Dict[str, Any]]:
        """Get guild settings with caching."""
        settings = await redis.get_cache_guild_setting(self, guild_id)
        if not settings:
            settings = await db.get_guild_settings(guild_id)
            if settings:
                await redis.cache_guild_setting(
                    self,
                    guild_id=guild_id,
                    temp_voice=settings['master_voice_chid'],
                    category=settings['master_category_name']
                )
        return settings

    async def _on_master_join(self, member: discord.Member, after: discord.VoiceState, 
                            guild: discord.Guild, settings: Dict[str, Any]):
        """Handle user joining master voice channel."""
        async with self._safe_lock():
            # Check if user already has an active channel
            if member.id in self.active_channels:
                existing_channel = guild.get_channel(self.active_channels[member.id])
                if existing_channel:
                    try:
                        await member.move_to(existing_channel)
                        return
                    except discord.HTTPException:
                        # Channel might be deleted or user can't be moved
                        pass
                # Clean up stale reference
                self.active_channels.pop(member.id, None)

            try:
                new_channel = await self._create_temp_channel(member, after, settings)
                if new_channel:
                    await self._setup_temp_channel(new_channel, member, guild, settings)
                    
            except Exception as e:
                log.error(f"Error creating temp channel for {member}: {e}", exc_info=True)
                try:
                    await member.send(
                        "⚠️ Gagal membuat voice channel. Hubungi admin.\n"
                        "-# Mungkin masalah perizinan / bot tidak memiliki izin untuk mengatur voice channel"
                    )
                except discord.HTTPException:
                    pass

    async def _create_temp_channel(self, member: discord.Member, after: discord.VoiceState, 
                                 settings: Dict[str, Any]) -> Optional[discord.VoiceChannel]:
        """Create a new temporary voice channel."""
        category = after.channel.category
        name = await self._generate_channel_name(member, category)

        try:
            new_channel = await member.guild.create_voice_channel(
                name=name,
                category=category,
                overwrites=after.channel.overwrites,
                bitrate=min(after.channel.bitrate, member.guild.bitrate_limit),
                user_limit=after.channel.user_limit,
                reason=f"Temporary voice channel for {member}"
            )
            return new_channel
            
        except discord.HTTPException as e:
            log.error(f"Failed to create voice channel: {e}")
            return None

    async def _generate_channel_name(self, member: discord.Member, 
                                   category: Optional[discord.CategoryChannel]) -> str:
        """Generate a unique channel name."""
        existing_names = set()
        if category:
            existing_names = {c.name for c in category.voice_channels}

        # Try to get random name from database
        for _ in range(5):
            random_name = await db.get_random_name(member.guild.id)
            if random_name and random_name not in existing_names:
                return random_name

        # Fallback to member display name with disambiguation
        base_name = member.display_name[:50]  # Truncate long names
        name = base_name
        counter = 1
        
        while name in existing_names and counter < 100:
            name = f"{base_name} {counter}"
            counter += 1
            
        return name

    async def _setup_temp_channel(self, channel: discord.VoiceChannel, member: discord.Member,
                                guild: discord.Guild, settings: Dict[str, Any]):
        """Set up the temporary channel after creation."""
        # Update internal state
        self.temp_channels.add(channel.id)
        self.active_channels[member.id] = channel.id
        self.channel_owners[channel.id] = member.id
        self.channel_categories[channel.id] = settings.get('category', 'default')

        # Save to Redis
        await redis.save_temp_channel(
            self,
            channel_id=channel.id,
            owner_id=member.id,
            name=channel.name,
            category=self.channel_categories[channel.id]
        )

        # Set owner permissions
        perm = discord.PermissionOverwrite(
            view_channel=True, connect=True, speak=True,
            mute_members=True, deafen_members=True,
            move_members=True, manage_channels=True,
            read_message_history=True, send_messages=True,
            stream=True, use_application_commands=True,
            send_voice_messages=True, use_embedded_activities=True
        )
        await channel.set_permissions(member, overwrite=perm)
        
        # Move member to new channel
        try:
            await member.move_to(channel)
        except discord.HTTPException as e:
            log.warning(f"Failed to move {member} to {channel}: {e}")

        # Send control panel
        await self._send_panel(channel, member, guild)
        log.info(f"Temp channel created: {channel.name} ({channel.id})")

    async def _send_panel(self, channel: discord.VoiceChannel, member: discord.Member, 
                         guild: discord.Guild):
        """Send the control panel to the voice channel."""
        try:
            # Clean up old view if exists
            if channel.id in self.temp_channel_views:
                old_view = self.temp_channel_views.pop(channel.id)
                old_view.stop()

            view = VoiceChannelConfigView(channel, member.id, self.bot)
            self.temp_channel_views[channel.id] = view

            embed = discord.Embed(
                title=f"{LONCENG} **Voice Control Panel** {LONCENG}",
                description=f"Gunakan menu di bawah untuk mengatur channel ini sesuai kebutuhan.\n{HORIZONTAL}",
                color=discord.Color.blurple()
            )
                        
            embed.add_field(
                name=f"{PUBLIC} Public",
                value="Channel terbuka untuk semua orang",
                inline=False
            )
            embed.add_field(
                name=f"{PRIVATE} Private",
                value="Hanya bisa masuk jika diundang",
                inline=False
            )
            embed.add_field(
                name=f"{HIDE} Hide",
                value="Sembunyikan dari yang lain",
                inline=False
            )
            embed.add_field(
                name=f"{RANDOM} Random",
                value="Acak nama channel",
                inline=False
            )
            embed.add_field(
                name=f"{LIMIT} Limit",
                value="Atur batas user",
                inline=False
            )
            embed.add_field(
                name=f"{EDIT} Rename",
                value="Ganti nama channel",
                inline=False
            )

            embed.set_footer(text=f"• Owner: {member.display_name}")

            await channel.send(embed=embed, view=view)
            
        except discord.HTTPException as e:
            log.error(f"Failed to send control panel: {e}")

    async def _on_temp_leave(self, member: discord.Member, before: discord.VoiceState, 
                           guild: discord.Guild):
        """Handle user leaving temporary voice channel."""
        if not before.channel:
            return

        channel_id = before.channel.id
        
        try:
            # Handle permission cleanup for hidden channels
            overwrites = before.channel.overwrites_for(guild.default_role)
            if overwrites.view_channel is False:
                try:
                    await before.channel.set_permissions(member, overwrite=None)
                    await redis.delete_channel_override(self, channel_id, member.id)
                except discord.NotFound:
                    pass  # Channel already deleted
                except Exception as e:
                    log.error(f"Failed removing override for {member.id} in {channel_id}: {e}")

            # Check if channel should be deleted
            async with self._safe_lock():
                # Refresh channel object to get current state
                channel = guild.get_channel(channel_id)
                if not channel:
                    return

                current_members = [m for m in channel.members if not m.bot]
                
                if not current_members:
                    await self._cleanup_empty_channel(channel)
                    
        except Exception as e:
            log.error(f"Unexpected error in _on_temp_leave: {e}", exc_info=True)

    async def _cleanup_empty_channel(self, channel: discord.VoiceChannel):
        """Clean up empty temporary channel."""
        channel_id = channel.id
        
        try:
            # Stop and remove view
            if channel_id in self.temp_channel_views:
                view = self.temp_channel_views.pop(channel_id)
                view.stop()

            # Delete channel
            await channel.delete(reason="Empty temporary voice channel cleanup")
            log.info(f"Deleted empty temp channel {channel_id}")
            
        except discord.NotFound:
            pass  # Already deleted
        except Exception as e:
            log.error(f"Failed deleting channel {channel_id}: {e}")
        finally:
            # Clean up internal state regardless of deletion success
            self._cleanup_channel_state(channel_id)
            await redis.delete_channel(self, channel_id)

    def _cleanup_channel_state(self, channel_id: int):
        """Clean up internal state for a channel."""
        self.temp_channels.discard(channel_id)
        
        # Remove from active_channels (user -> channel mapping)
        self.active_channels = {
            user_id: ch_id for user_id, ch_id in self.active_channels.items() 
            if ch_id != channel_id
        }
        
        self.channel_owners.pop(channel_id, None)
        self.channel_categories.pop(channel_id, None)
        
        # Clean up view
        if channel_id in self.temp_channel_views:
            view = self.temp_channel_views.pop(channel_id)
            view.stop()

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        """Handle channel deletion events."""
        if not isinstance(channel, discord.VoiceChannel):
            return
            
        channel_id = channel.id
        async with self._safe_lock():
            self._cleanup_channel_state(channel_id)
        
        await redis.delete_channel(self, channel_id)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        """Handle member leaving guild."""
        async with self._safe_lock():
            self.active_channels.pop(member.id, None)

    @commands.command(name="clear_voice_cache")
    @commands.has_permissions(administrator=True)
    async def clear_cache(self, ctx: commands.Context):
        """Clear voice channel cache (admin only)."""
        try:
            await self.cleanup_temp_channels()
            await ctx.send("🧹 Redis cache cleared")
        except Exception as e:
            log.error(f"Error clearing cache: {e}")
            await ctx.send("❌ Error clearing cache")

    async def cleanup_temp_channels(self):
        """Clean up temporary channels on startup."""
        try:
            all_keys = await self._get_all_temp_channel_keys()
            
            for key in all_keys:
                await self._process_temp_channel_key(key)
                
        except Exception as e:
            log.error(f"Error in cleanup_temp_channels: {e}", exc_info=True)

    async def _get_all_temp_channel_keys(self) -> list:
        """Get all temporary channel keys from Redis."""
        cursor = 0
        all_keys = []

        while True:
            cursor, batch = await self.bot.redis.scan(
                cursor=cursor,
                match="yumna:temp_channels:*",
                count=100
            )
            all_keys.extend(batch)
            if cursor == 0:
                break
                
        return all_keys

    async def _process_temp_channel_key(self, raw_key):
        """Process a single temporary channel key during cleanup."""
        key = raw_key.decode() if isinstance(raw_key, bytes) else raw_key
        parts = key.split(":")
        
        # Validate key format
        if len(parts) != 3:
            await self.bot.redis.delete(key)
            return

        try:
            channel_id = int(parts[2])
        except ValueError:
            await self.bot.redis.delete(key)
            return

        channel = self.bot.get_channel(channel_id)
        if not channel:
            # Channel was deleted manually
            await self.bot.redis.delete(key)
            log.info(f"[ DELETE REDIS KEY ] ------ Unused key on redis [{channel_id}]")
            return

        # Get channel data from Redis
        data = await self.bot.redis.hgetall(key)
        owner_id = self._extract_owner_id(data)
        category_name = self._extract_category(data)

        # Re-register if channel has members
        if channel.members:
            await self._reregister_channel(channel_id, owner_id, category_name)
            return

        # Delete empty channel
        await self._delete_abandoned_channel(channel, key, channel_id, owner_id)

    def _extract_owner_id(self, data: dict) -> Optional[int]:
        """Extract owner ID from Redis data."""
        owner_bytes = data.get(b"owner_id")
        if owner_bytes:
            try:
                return int(owner_bytes.decode())
            except (ValueError, AttributeError):
                pass
        return None

    def _extract_category(self, data: dict) -> str:
        """Extract category from Redis data."""
        category_bytes = data.get(b"category")
        return category_bytes.decode() if category_bytes else "default"

    async def _reregister_channel(self, channel_id: int, owner_id: Optional[int], 
                                category_name: str):
        """Re-register a channel that still has members."""
        self.temp_channels.add(channel_id)

        if owner_id is not None:
            self.channel_owners[channel_id] = owner_id
            self.active_channels[owner_id] = channel_id

        self.channel_categories[channel_id] = category_name
        
        channel = self.bot.get_channel(channel_id)
        log.info(f"[ RE:REGISTERING ] {channel.name} ({channel_id}) for [{owner_id}]")

    async def _delete_abandoned_channel(self, channel: discord.VoiceChannel, key: str,
                                      channel_id: int, owner_id: Optional[int]):
        """Delete an abandoned temporary channel."""
        try:
            await channel.delete(reason="Bot restarted — cleaning up temp voice channels")
            await self.bot.redis.delete(key)
            
            # Clean up state
            self.temp_channels.discard(channel_id)
            if owner_id is not None:
                self.active_channels.pop(owner_id, None)
                self.channel_owners.pop(channel_id, None)
            self.channel_categories.pop(channel_id, None)

            log.info(f"[ TEMP VOICE DELETED ] ---- [{channel.name}] [({channel_id})]")
            
        except Exception as e:
            log.warning(f"Failed to delete temp channel {channel.name} ({channel_id}): {e}")
            

    @discord.app_commands.command(name="whitelist", description="Tambahkan member ke whitelist voice channel")
    async def voice_add(self, interaction: discord.Interaction, member: discord.Member):
        """Tambahkan member ke whitelist voice channel saat ini."""
        
        # Check apakah user ada di voice channel
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message(
                "❌ Kamu harus berada di voice channel untuk menggunakan command ini!", 
                ephemeral=True
            )
            return
        
        voice_channel = interaction.user.voice.channel
        
        # Check apakah ini temp channel dan user adalah owner
        if voice_channel.id not in self.temp_channels:
            await interaction.response.send_message(
                "❌ Command ini hanya bisa digunakan di temporary voice channel!", 
                ephemeral=True
            )
            return
        
        channel_owner = self.channel_owners.get(voice_channel.id)
        if channel_owner != interaction.user.id:
            await interaction.response.send_message(
                "❌ Hanya owner channel yang bisa menambahkan member ke whitelist!", 
                ephemeral=True
            )
            return
        
        # Check apakah member adalah bot
        if member.bot:
            await interaction.response.send_message(
                "❌ Tidak bisa menambahkan bot ke whitelist!", 
                ephemeral=True
            )
            return
        
        try:
            # Set permissions untuk member
            perms = discord.PermissionOverwrite(
                view_channel=True,
                connect=True,
                speak=True,
                read_message_history=True,
                send_messages=True,
                use_application_commands=True,
                stream=True,
                send_voice_messages=True,
                attach_files=True,
                use_embedded_activities=True
            )
            await voice_channel.set_permissions(member, overwrite=perms)
            
            # Simpan ke Redis
            key = f"yumna:temp_channels:{voice_channel.id}"
            await self.bot.redis.sadd(f"{key}:whitelist", member.id)
            
            await interaction.response.send_message(
                f"✅ **{member.display_name}** berhasil ditambahkan ke whitelist channel **{voice_channel.name}**!",
                ephemeral=True
            )
                
            log.info(f"Member {member.display_name} added to whitelist in channel {voice_channel.name} by {interaction.user.display_name}")
            
        except discord.HTTPException as e:
            await interaction.response.send_message(
                f"❌ Gagal menambahkan {member.display_name} ke whitelist: {str(e)[:100]}", 
                ephemeral=True
            )


async def setup(bot):
    """Set up the cog."""
    await bot.add_cog(VoiceTemp(bot))