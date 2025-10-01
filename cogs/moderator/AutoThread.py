import discord
import random
import logging
import asyncio

from discord.ext import commands
from utils.data.emot import emoji_thread
from services import economy
from services.dailyquest import DailyQuest
from utils.time import get_current_date

# from ..chatbot.helper.prompt import MOD_PROMPT, MOD_VISION_PROMPT
# from typing import Optional, List

RANDOM_EMOJI = random.choice(emoji_thread)

THREAD_CHANNEL_ID = [1371794854442438717,1371794817453129800, 1415981198710276167]

# THREAD_CHANNEL_ID = [1371794854442438717,1406382442423521430, 1406382442423521429]

#--------- Production
GUILD_ID = 1234390981470715954
MODERATION_CHANNEL_ID = 1371791820618469476
MODERATED_TARGET_ID = 712011923176030229

#--------- Testing
# GUILD_ID = 1406382441895035061
# MODERATION_CHANNEL_ID = 1275924936136855669

log = logging.getLogger(__name__)

TTL = 3600  # 1 jam

class AutoThread(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.dailyquest = DailyQuest(bot.redis)  # ✅ inject redis
        self.voice_lock = asyncio.Lock()  # untuk synchronisasi


    async def set_thread_message(self, message_id: int, thread_id: int):
        key = f"thread_message:{message_id}"
        await self.bot.redis.set(key, thread_id, ex=TTL)

    async def get_thread_message(self, message_id: int) -> str | None:
        key = f"thread_message:{message_id}"
        result = await self.bot.redis.get(key)
        if result:
            return result.decode()
        return None

    async def delete_thread_message(self, message_id: int):
        key = f"thread_message:{message_id}"
        await self.bot.redis.delete(key)

    async def exists_thread_message(self, message_id: int) -> bool:
        key = f"thread_message:{message_id}"
        return await self.bot.redis.exists(key) > 0
    
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot:
            return
        
        VOICE_CH_ID = {1371783709073735711,1374916800747147325}
        ANOTHER_WORLD = {1378722381199183895}
        
        # Guard: kalau tidak join channel baru (after None = keluar VC)
        if after.channel is None:
            return
        
        if after.channel.id not in VOICE_CH_ID and after.channel.id not in ANOTHER_WORLD:
            return

        async with self.voice_lock:
            guild_id = member.guild.id
            member_id = member.id
            username = member.name
            
            if after.channel.id in VOICE_CH_ID:
                date = get_current_date()
                await self.dailyquest.update_quest(guild_id,member_id,"create_voice_room", date)
                
            if after.channel.id in ANOTHER_WORLD:
                date = get_current_date()
                await self.dailyquest.update_quest(guild_id,member_id,"join_anotherworld", date)
        
    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread):
        if thread.parent and thread.parent.type == discord.ChannelType.forum:
            starter_message = await thread.fetch_message(thread.id)
            print(f"{starter_message} create a post")
            if starter_message:
                date = get_current_date()
                await self.dailyquest.update_quest(
                    thread.guild.id,
                    starter_message.author.id,
                    "open_discuss",  # samain field dengan default
                    date
                )


    @commands.Cog.listener()
    async def on_message(self, message):
        if not message.guild or message.author == self.bot.user:
            return    
        
        if message.guild.id != GUILD_ID:
            return
        
        if message.channel.id == MODERATION_CHANNEL_ID:
            if not message.embeds:
                try:
                    await message.delete()
                    log.info(f"Pesan tanpa embed dihapus: {message.id}")
                except discord.Forbidden:
                    log.warning(f"Gagal menghapus pesan {message.id}: izin ditolak.")                

        if message.channel.id in THREAD_CHANNEL_ID:
            if message.attachments:
                for attachment in message.attachments:
                    if attachment.content_type and (attachment.content_type.startswith("image/") or attachment.content_type.startswith("video/")):
                        # Buat thread otomatis
                        thread_name = f"Reply .. {message.author.display_name}"
                        thread = await message.create_thread(name=thread_name)
                        
                        await economy.earn_xp_balance(message.guild.id, message.author.id, str(message.author), 1200, 500, f"Posted something on {message.channel.name}", "credit")
                        
                        date = get_current_date()
                        field = f"post_on_{message.channel.name}"
                        await self.dailyquest.update_quest(message.guild.id, message.author.id, field, date)
                        
                        await message.add_reaction(RANDOM_EMOJI)
                        log.info(f"Thread dibuat untuk pesan dari {message.author} di {message.channel.name}.")

                        # Simpan mapping pesan dengan thread ke Redis
                        await self.set_thread_message(message.id, thread.id)

                        
                        return  # Tidak hapus pesan

            # Jika bukan media, hapus pesan
            if message.guild.me.guild_permissions.manage_messages:
                await message.delete()
                warning_msg = await message.channel.send(f"{message.author.mention}, hanya media yang diperbolehkan di channel ini..")
                await warning_msg.delete(delay=5)
            else:
                log.warning("Bot tidak memiliki izin 'Manage Messages' untuk menghapus pesan.")

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if message.channel.id not in THREAD_CHANNEL_ID:
            return

        thread_id = await self.get_thread_message(message.id)
        if thread_id:
            thread = message.guild.get_thread(int(thread_id))

            if not thread:
                try:
                    # Fetch langsung dari API kalau tidak ada di cache
                    fetched = await message.guild.fetch_channel(int(thread_id))
                    if isinstance(fetched, discord.Thread):
                        thread = fetched
                    else:
                        log.warning(f"Channel {thread_id} bukan thread.")
                        thread = None
                except discord.NotFound:
                    log.warning(f"Thread dengan ID {thread_id} tidak ditemukan (sudah dihapus?).")
                except discord.Forbidden:
                    log.warning(f"Bot tidak punya izin untuk fetch thread {thread_id}.")
                except discord.HTTPException as e:
                    logging.error(f"Gagal fetch thread {thread_id}: {e}")

            if thread:
                try:
                    await thread.delete()
                    log.info(f"Thread '{thread_id}' dihapus karena pesan utamanya dihapus.")
                except discord.Forbidden:
                    log.warning(f"Bot tidak punya izin untuk menghapus thread '{thread_id}'.")
                except discord.HTTPException as e:
                    logging.error(f"Gagal menghapus thread '{thread_id}': {e}")

            await self.delete_thread_message(message.id)


async def setup(bot):
    await bot.add_cog(AutoThread(bot))


            # texts: List[str] = []
            # for embed in message.embeds:
            #     if embed.description:
            #         texts.append(embed.description.strip())
            #     for field in embed.fields:
            #         if field.name:
            #             texts.append(field.name.strip())
            #         if field.value:
            #             texts.append(field.value.strip())
            # text_content = "\n".join([t for t in texts if t]).strip()

            # # 2. Kumpulkan URL gambar dari embed dan attachments
            # image_urls: List[str] = []
            # for embed in message.embeds:
            #     if embed.image and getattr(embed.image, "url", None):
            #         image_urls.append(embed.image.url)
            #     if embed.thumbnail and getattr(embed.thumbnail, "url", None):
            #         image_urls.append(embed.thumbnail.url)
            # for att in message.attachments:
            #     # Cek content_type jika tersedia
            #     if att.content_type:
            #         if att.content_type.startswith("image/"):
            #             image_urls.append(att.url)
            #     else:
            #         # fallback cek ekstensi
            #         fname = att.filename.lower()
            #         if fname.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")):
            #             image_urls.append(att.url)

            # # Flag hasil moderasi
            # text_safe = True
            # image_safe = True

            # # 3. Jika ada teks, lakukan moderasi teks
            # if text_content:
            #     log.info(f"[ CONFESS TEXT RECEIVED ] ID={message.id} CONTENT={text_content!r}")
            #     try:
            #         text_mod_response = await self.bot.ai.get_mod_response(
            #             classification="general",
            #             system_message=MOD_PROMPT,
            #             user_message=text_content
            #         )
            #     except Exception as e:
            #         log.warning(f"Gagal memanggil get_mod_response untuk pesan {message.id}: {e}")
            #         # Kebijakan: jika gagal panggil moderasi teks, diasumsikan aman atau sebaliknya?
            #         # Di sini diasumsikan aman (text_safe tetap True). Jika mau lebih strict, set text_safe=False.
            #         text_mod_response = None

            #     resp_text = str(text_mod_response or "").lower()
            #     # Jika respons mengandung keyword unsafe
            #     if any(keyword in resp_text for keyword in ("reject", "flag", "unsafe")):
            #         text_safe = False
            #         log.info(f"Moderasi teks menolak pesan ID={message.id}")
            #     else:
            #         log.info(f"Moderasi teks menganggap aman pesan ID={message.id}")
            # else:
            #     log.debug(f"Tidak ada teks di embed pesan ID={message.id}")

            # # 4. Jika ada gambar, lakukan moderasi gambar
            # if image_urls:

            #     for image_url in image_urls:
            #         log.info(f"[ CONFESS IMAGE RECEIVED ] ID={message.id} IMAGE_URL={image_url}")
            #         try:
            #             image_mod_response = await self.bot.ai.get_vision_mod_response(
            #                 image_url=image_url,
            #                 system_message=MOD_VISION_PROMPT
            #             )
            #         except Exception as e:
            #             log.warning(f"Gagal memanggil get_vision_mod_response untuk pesan {message.id}, image {image_url}: {e}")
            #             # Diasumsikan aman; jika ingin stricter, set image_safe=False
            #             image_mod_response = None

            #         if image_mod_response is None:
            #             log.info(f"Moderasi vision tidak mengembalikan respons untuk pesan {message.id}, image {image_url}. Diasumsikan aman.")
            #             continue

            #         resp_img_text = str(image_mod_response).lower()
            #         if any(keyword in resp_img_text for keyword in ("reject", "flag", "unsafe")):
            #             image_safe = False
            #             log.info(f"Moderasi gambar menolak pesan ID={message.id}, image {image_url}")
            #             # Jika satu image ditolak, tidak perlu cek image lain
            #             break
            #         else:
            #             log.info(f"Moderasi gambar menganggap aman pesan ID={message.id}, image {image_url}")
            # else:
            #     log.debug(f"Tidak ada gambar di embed/attachment pesan ID={message.id}")

            # if not text_content and not image_urls:
            #     return

            # # Jika salah satu unsafe
            # if not text_safe or not image_safe:
            #     # Hapus pesan
            #     try:
            #         await message.delete()
            #         log.info(f"Pesan ID={message.id} dihapus (text_safe={text_safe}, image_safe={image_safe})")
            #         # Kirim notifikasi sesuai alasan: bisa gabung pesan teks & gambar:
            #         alasan_parts = []
            #         if not text_safe:
            #             alasan_parts.append("teks mengandung konten tidak pantas")
            #         if not image_safe:
            #             alasan_parts.append("gambar mengandung konten tidak pantas")
            #         alasan = " dan ".join(alasan_parts)
            #         notif = f"Pesan dihapus\n-# {alasan.capitalize()}."
            #         await message.channel.send(notif, delete_after=30)
            #     except discord.Forbidden:
            #         log.warning(f"Gagal menghapus pesan {message.id}: izin ditolak.")
            #     return

            # # Jika di sini, semua yang ada (teks dan/atau gambar) aman
            # log.info(f"Pesan ID={message.id} dianggap aman sepenuhnya (text_safe={text_safe}, image_safe={image_safe})")
            # return
