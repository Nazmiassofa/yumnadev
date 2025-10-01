import discord
from discord.ext import commands
from discord.ui import Button, View, Modal, TextInput
from io import BytesIO
import json
import os
import asyncio
import logging
from typing import Dict, Any, Optional
import aiohttp

ALLOWED_ROLE_ID = [1249926441840148492, 1365467389621436499]
ALLOWED_GUILD_ID = 1234390981470715954  # Ganti dengan ID guild A kamu
DATA_FILE = "utils/data/roles.json"

class RoleCreationModal(Modal, title="Buat Role Custom"):
    def __init__(self, cog, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cog = cog
        
        self.role_name = TextInput(
            label="Nama Role",
            placeholder="Masukkan nama role yang diinginkan",
            max_length=100
        )
        
        self.role_color = TextInput(
            label="Warna Role (Hex)",
            placeholder="Contoh: #FF0000 untuk merah",
            max_length=7,
            required=False
        )
        
        self.add_item(self.role_name)
        self.add_item(self.role_color)

    async def on_submit(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        
        # Setup timeout callback
        async def timeout_callback():
            await asyncio.sleep(120)  # Tunggu 2 menit
            
            # Cek jika user masih dalam pending
            if user_id in self.cog.pending_creations:
                try:
                    # Kirim notifikasi timeout
                    channel = self.cog.bot.get_channel(self.cog.pending_creations[user_id]['channel_id'])
                    if channel:
                        await channel.send(
                            f"⏰ <@{user_id}> Waktu upload gambar telah habis! "
                            "Gunakan command `/myrole` lagi untuk memulai ulang.",
                            delete_after=15
                        )
                except Exception as e:
                    logging.error(f"Failed to send timeout notification: {e}")
                finally:
                    # Bersihkan data
                    if user_id in self.cog.pending_creations:
                        del self.cog.pending_creations[user_id]

        # Simpan data + timeout task
        self.cog.pending_creations[user_id] = {
            'name': self.role_name.value,
            'color': self.role_color.value,
            'channel_id': interaction.channel.id,
            'timeout_task': asyncio.create_task(timeout_callback())  # Simpan task reference
        }
        
        await interaction.response.send_message(
            "🖼️ Silahkan unggah gambar untuk icon role dalam **2 menit**:\n"
            "• Format: PNG/JPG/GIF\n"
            "• Maksimal 512KB\n"
            "• ketik `skipimg` untuk membuat role tanpa icon\n"
            f"Ketik `cancel` di {interaction.channel.mention} untuk membatalkan",
            ephemeral=True
        )
        self.stop()
        
class RoleCreatorView(View):
    def __init__(self, cog, original_message=None):
        super().__init__(timeout=180)
        self.cog = cog
        self.original_message = original_message
    
    async def cleanup(self, interaction: discord.Interaction):
        """Clean up the original message and view"""
        try:
            if self.original_message:
                await self.original_message.delete()
        except discord.NotFound:
            pass
        self.stop()
    
    @discord.ui.button(label="Buat Role", style=discord.ButtonStyle.primary, emoji="🛠️")
    async def create_role(self, interaction: discord.Interaction, button: Button):
        if str(interaction.user.id) in self.cog.user_roles:
            await interaction.response.send_message(
                "Kamu sudah memiliki role custom! Hapus role lama terlebih dahulu.",
                ephemeral=True
            )
            return
        
        if not any(role.id in ALLOWED_ROLE_ID for role in interaction.user.roles):
            await interaction.response.send_message(
                "Kamu tidak memiliki izin untuk membuat role custom!",
                ephemeral=True
            )
            return
        
        modal = RoleCreationModal(self.cog)
        await interaction.response.send_modal(modal)
        await self.cleanup(interaction)
        
    @discord.ui.button(label="Hapus Role", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def delete_role(self, interaction: discord.Interaction, button: Button):
        user_id = str(interaction.user.id)

        if interaction.guild.id != ALLOWED_GUILD_ID:
            await interaction.response.send_message("❌ Tidak tersedia di server ini.", ephemeral=True)
            return

        if user_id not in self.cog.user_roles:
            await interaction.response.send_message(
                "Kamu tidak memiliki role custom untuk dihapus!",
                ephemeral=True
            )
            return

        role_id = self.cog.user_roles[user_id]
        role = interaction.guild.get_role(role_id)

        confirm_view = View(timeout=60)
        yes_button = Button(label="Ya, Hapus", style=discord.ButtonStyle.danger)
        no_button = Button(label="Nggak ah males", style=discord.ButtonStyle.secondary)

        async def yes_callback(confirm_interaction: discord.Interaction):
            await confirm_interaction.response.defer()

            # Disable tombol
            yes_button.disabled = True
            no_button.disabled = True
            # Tidak perlu edit view ke message yang tidak dikenal

            try:
                if role and (role in confirm_interaction.user.roles):
                    await confirm_interaction.user.remove_roles(role)

                if role:
                    try:
                        await role.delete(reason=f"Role dihapus oleh {interaction.user}")
                    except discord.NotFound:
                        pass

                del self.cog.user_roles[user_id]
                self.cog.save_data()

                await confirm_interaction.followup.send(
                    "✅ Role berhasil dihapus dari server dan data!",
                    ephemeral=True
                )
            except Exception as e:
                await confirm_interaction.followup.send(
                    f"❌ Error: {str(e)}",
                    ephemeral=True
                )
            finally:
                confirm_view.stop()
                await self.cleanup(interaction)

        async def no_callback(confirm_interaction: discord.Interaction):
            await confirm_interaction.response.send_message(
                "Penghapusan role dibatalkan.",
                ephemeral=True
            )
            confirm_view.stop()

        yes_button.callback = yes_callback
        no_button.callback = no_callback

        confirm_view.add_item(yes_button)
        confirm_view.add_item(no_button)

        await interaction.response.send_message(
            f"⚠️ Apakah kamu yakin ingin menghapus role {'`' + role.name + '`' if role else 'ini'}?",
            view=confirm_view,
            ephemeral=True
        )


class RoleCreator(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.user_roles: Dict[str, int] = self.load_data()
        self.pending_creations: Dict[int, Dict[str, Any]] = {}
        self.target_role_id = 1249926441840148492
        self.session = aiohttp.ClientSession()
    
    def __del__(self):
        asyncio.create_task(self.session.close())
            
    @commands.Cog.listener()
    async def on_ready(self):
        self.pending_creations.clear()
        
    async def cleanup_pending_creation(self, user_id: int):
        """Bersihkan data pending setelah timeout"""
        if user_id in self.pending_creations:
            del self.pending_creations[user_id]
            logging.info(f"Cleaned up pending creation for user {user_id} (timeout)")
    
    def load_data(self) -> Dict[str, int]:
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r") as f:
                    return json.load(f)
            except json.JSONDecodeError:
                return {}
        return {}
    
    def save_data(self):
        with open(DATA_FILE, "w") as f:
            json.dump(self.user_roles, f, indent=4)
    
    async def _raw_api_position_update(self, guild_id: int, role_id: int, position: int) -> bool:
        """Update role position directly through Discord API"""
        try:
            async with self.session.patch(
                f"https://discord.com/api/v9/guilds/{guild_id}/roles/{role_id}",
                headers={
                    "Authorization": f"Bot {self.bot.http.token}",
                    "Content-Type": "application/json"
                },
                json={"position": position}
            ) as resp:
                if resp.status == 200:
                    return True
                error = await resp.json()
                raise discord.HTTPException(resp, error.get("message", "Unknown error"))
        except Exception as e:
            logging.error(f"API Position Update Error: {str(e)}")
            return False
    
    async def _ensure_role_position(self, role: discord.Role, target_role: discord.Role) -> bool:
        """Hybrid approach with ultimate reliability"""
        MAX_ATTEMPTS = 6
        desired_pos = target_role.position + 1
        
        for attempt in range(MAX_ATTEMPTS):
            try:
                # Progressive delay (3, 6, 9, 12, 15, 18 detik)
                await asyncio.sleep(3 * (attempt + 1))
                
                # Force refresh roles
                await role.guild.fetch_roles()
                
                # Get fresh instances
                updated_target = role.guild.get_role(target_role.id)
                updated_role = role.guild.get_role(role.id)
                
                if not updated_target or not updated_role:
                    raise ValueError("Role objects missing after refresh")

                # Recalculate desired position
                desired_pos = updated_target.position + 1
                bot_top_pos = role.guild.me.top_role.position
                
                # Validate position
                if desired_pos >= bot_top_pos:
                    desired_pos = bot_top_pos - 1
                
                if desired_pos <= updated_target.position:
                    raise ValueError(f"Invalid position: {desired_pos}")

                # Check if already correct
                if updated_role.position == desired_pos:
                    return True

                # Attempt strategy
                if attempt < 3:
                    # Standard library method
                    await updated_role.edit(position=desired_pos)
                else:
                    # Direct API fallback
                    api_success = await self._raw_api_position_update(
                        role.guild.id,
                        role.id,
                        desired_pos
                    )
                    if not api_success:
                        continue

                # Final verification
                await asyncio.sleep(2)
                await role.guild.fetch_roles()
                final_role = role.guild.get_role(role.id)
                
                if final_role.position == desired_pos:
                    return True
                    
                logging.warning(f"Position mismatch: Expected {desired_pos}, Got {final_role.position}")

            except discord.HTTPException as e:
                logging.error(f"Attempt {attempt+1} failed: {str(e)}")
                if e.status == 429:
                    retry_after = max(getattr(e, 'retry_after', 5.0), 10.0)
                    await asyncio.sleep(retry_after)
            except Exception as e:
                logging.error(f"Unexpected error: {str(e)}")
                await asyncio.sleep(5)
        
        logging.critical(f"Role positioning failed after {MAX_ATTEMPTS} attempts")
        return False

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.content.lower() == 'cancel' and message.author.id in self.pending_creations:
            del self.pending_creations[message.author.id]
            await message.reply("❌ Proses pembuatan role dibatalkan", delete_after=10)
            return
 
        if message.content.lower() == 'skipimg' and message.author.id in self.pending_creations:
            creation_data = self.pending_creations.get(message.author.id)
            if not creation_data or message.channel.id != creation_data['channel_id']:
                return
                
            try:
                # Process color
                color = discord.Color.default()
                if creation_data['color']:
                    try:
                        hex_color = creation_data['color'].lstrip('#')
                        if len(hex_color) == 3:  # Convert #RGB to #RRGGBB
                            hex_color = ''.join([c*2 for c in hex_color])
                        color = discord.Color(int(hex_color, 16))
                    except ValueError:
                        await message.channel.send("⚠ Format warna tidak valid, menggunakan default", delete_after=5)

                # Create role without icon
                role = await message.guild.create_role(
                    name=creation_data['name'][:100],
                    color=color,
                    reason=f"Custom role untuk {message.author} (tanpa icon)"
                )
                
                # Assign role
                await message.author.add_roles(role)

                # Position role
                target_role = message.guild.get_role(self.target_role_id)
                if target_role:
                    success = await self._ensure_role_position(role, target_role)
                    if not success:
                        await message.channel.send(
                            "⚠ Role berhasil dibuat tetapi posisi belum tepat (akan diperbaiki otomatis)",
                            delete_after=15
                        )

                # Save data
                self.user_roles[str(message.author.id)] = role.id
                self.save_data()
                
                # Send confirmation
                await message.add_reaction("✅")
                await message.channel.send(
                    f"✅ Role {role.mention} berhasil dibuat tanpa icon!",
                    delete_after=15
                )
                
            except Exception as e:
                await message.channel.send(f"❌ Gagal membuat role: {str(e)}", delete_after=15)
                logging.error(f"Role creation error: {str(e)}", exc_info=True)
            finally:
                self.pending_creations.pop(message.author.id, None)
                await asyncio.sleep(3)
                try:
                    await message.delete()
                except:
                    pass
            return

        if message.author.bot or not message.attachments:
            return
            
        if message.author.id not in self.pending_creations:
            return
            
        creation_data = self.pending_creations.get(message.author.id)
        if not creation_data or message.channel.id != creation_data['channel_id']:
            return
        
        if not message.attachments[0].content_type.startswith("image/"):
            try:
                await message.delete()
                await message.channel.send("❌ File harus berupa gambar (PNG/JPG/GIF)", delete_after=5)
            except:
                pass
            return

        try:
            # Validate image
            if message.attachments[0].size > 512 * 1024:
                raise ValueError("Ukuran gambar terlalu besar (maks 256KB)")
            
            image_bytes = await message.attachments[0].read()
            
            # Process color
            color = discord.Color.default()
            if creation_data['color']:
                try:
                    hex_color = creation_data['color'].lstrip('#')
                    if len(hex_color) == 3:  # Convert #RGB to #RRGGBB
                        hex_color = ''.join([c*2 for c in hex_color])
                    color = discord.Color(int(hex_color, 16))
                except ValueError:
                    await message.channel.send("⚠ Format warna tidak valid, menggunakan default", delete_after=5)

            # Create role
            role = await message.guild.create_role(
                name=creation_data['name'][:100],
                color=color,
                reason=f"Custom role untuk {message.author}"
            )
            
            # Assign role first (most important)
            await message.author.add_roles(role)
            
            # Set icon (non-critical)
            try:
                await role.edit(display_icon=image_bytes)
            except Exception as e:
                logging.warning(f"Failed to set role icon: {e}")
                await message.channel.send("⚠ Role dibuat tapi gagal set icon", delete_after=10)

            # Position role
            target_role = message.guild.get_role(self.target_role_id)
            if target_role:
                success = await self._ensure_role_position(role, target_role)
                if not success:
                    await message.channel.send(
                        "⚠ Role berhasil dibuat tetapi posisi belum tepat (akan diperbaiki otomatis)",
                        delete_after=15
                    )

            # Save data
            self.user_roles[str(message.author.id)] = role.id
            self.save_data()
            self.pending_creations.pop(message.author.id, None)
            
            # Send confirmation
            success_msg = await message.channel.send(
                f"✅ Role {role.mention} berhasil dibuat!",
                delete_after=15
            )
            
            # Cleanup
            await asyncio.sleep(5)
            try:
                await message.delete()
            except:
                pass

        except Exception as e:
            logging.error(f"Role creation error: {str(e)}", exc_info=True)
            error_msg = f"❌ Gagal membuat role: {str(e)}"
            if isinstance(e, discord.Forbidden):
                error_msg += "\n⚠ Bot membutuhkan izin 'Manage Roles' dan posisi yang cukup"
            
            await message.channel.send(error_msg, delete_after=15)
            self.pending_creations.pop(message.author.id, None)
                
    @commands.command(name="myrole", aliased=["role","createrole"])
    @commands.guild_only()
    async def myrole_command(self, ctx: commands.Context):

        if ctx.guild.id != ALLOWED_GUILD_ID:
            await ctx.send("❌ Command ini hanya tersedia di server tertentu.\n-# Kunjungi support server untuk bantuan.")
            return
        
        embed = discord.Embed(
            title="Booster Role",
            description="-# Kelola role custom pribadi Kamu",
            color=discord.Color.blue()
        )
        
        embed.add_field(
            name="Buat Role Baru",
            value="-# Membuat role dengan nama, warna, dan icon pilihanmu",
            inline=False
        )
        
        embed.add_field(
            name="Hapus Role",
            value="-# Menghapus role custom milikmu",
            inline=False
        )
        
        message = await ctx.send(embed=embed)
        view = RoleCreatorView(self, original_message=message)
        await message.edit(view=view)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Handle when member loses allowed role"""
        try:
            user_id = str(after.id)
            
            # Skip if user doesn't have a custom role
            if user_id not in self.user_roles:
                return

            # Check if member had allowed role before but not anymore
            before_has_role = any(role.id in ALLOWED_ROLE_ID for role in before.roles)
            after_has_role = any(role.id in ALLOWED_ROLE_ID for role in after.roles)
            
            if before_has_role and not after_has_role:
                # Get the custom role
                custom_role_id = self.user_roles[user_id]
                custom_role = after.guild.get_role(custom_role_id)
                
                # If role doesn't exist, clean up data
                if not custom_role:
                    del self.user_roles[user_id]
                    self.save_data()
                    return

                # Check bot permissions
                if after.guild.me.top_role.position <= custom_role.position:
                    logging.warning(f"Bot can't manage role {custom_role.name} (position too high)")
                    return

                # Delete the role
                try:
                    await custom_role.delete(reason="Member lost required role privileges")
                    logging.info(f"Deleted custom role {custom_role.name} for {after}")
                    
                    # Clean up data
                    del self.user_roles[user_id]
                    self.save_data()
                    
                    # Notify user
                    try:
                        await after.send(
                            f"Custom role `{custom_role.name}` telah dihapus.\n"
                            "Kamu tidak lagi memiliki izin untuk membuat custom role."
                        )
                    except discord.HTTPException:
                        pass
                        
                except discord.Forbidden:
                    logging.error(f"Missing permissions to delete role {custom_role.name}")
                except Exception as e:
                    logging.error(f"Error deleting role: {str(e)}")

        except Exception as e:
            logging.error(f"Error in on_member_update: {str(e)}", exc_info=True)


async def setup(bot):
    await bot.add_cog(RoleCreator(bot))
