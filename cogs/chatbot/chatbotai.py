import discord
import logging
import asyncio
import json
import os

from discord.ext import commands
from .database.db import DataBaseManager as db
from .database.redis import RedisManager as redis
from utils.qdrant import search_memories

from utils.decorator.spender import requires_balance
from utils.views.embed import cooldown_embed
from utils.time import (get_current_date,
                        get_current_time)

from .helper.function import (load_prompt_blocks,
                                     compute_file_hash,
                                     get_server_time,
                                     bersihkan_think,
                                     animate_thinking,
                                     validate_input)


from .helper.prompt import (VALID_CLASSIFICATION,
                         TAG_PROMPT)

logger = logging.getLogger(__name__)

file_path = os.path.join(os.path.dirname(__file__), "helper/prompt_blocks.md")
system_messages = load_prompt_blocks(file_path)

clasify_prompt = system_messages.get("classify_prompt", "")

class ChatbotCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Handle message for ai custom prefix"""
        try:
            
            if message.guild is None:
                return      
        
            if message.guild.id != self.bot.main_guild_id:
                return
            
            else:
                # Check if it's a master channel
                if hasattr(self.bot, 'ChannelManager'):
                    is_master = await self.bot.ChannelManager.is_master_channel(
                        message.guild.id, message.channel.id
                    )
                    if not is_master:
                        return

                prefixes = ("ask ", "? ", ". ")
                for prefix in prefixes:
                    if message.content.lower().startswith(prefix):
                        ctx = await self.bot.get_context(message)
                        question = message.content[len(prefix):].strip()
                        if question:
                            await chatbot_cog.ask_command(ctx, question=question)
                        return

                # Handle advanced processing
                await self.advance_process(message, message.guild.id)
                
        except Exception as e:
            logger.error(f"[ CHATBOT ] --------------- Error in chatbot handling: {e}")
        
    async def classify_message(self, user_id: str, user_message: str) -> str:
        try:
            # Panggil AI internal langsung, tanpa HTTP request
            response = await self.bot.ai.get_classify_response(
                user_id=user_id,
                system_message=system_messages.get("classify", ""),
                user_message=user_message,
                user_prompt=clasify_prompt
            )
            
            # Normalisasi hasil klasifikasi
            classification = response.lower().strip()
            logger.info(f"[ AI CLASSIFICATION ] ----- : {classification}")
            return classification if classification in VALID_CLASSIFICATION else "general"

        except Exception as e:
            logger.error(f"[Classify Error] {e}", exc_info=True)
            return "general"
        
        
    async def send_to_appropriate_api(self, classification: str, user_id: str, guild_id: int, question: str) -> str:
        classification = classification.lower().strip()
        if classification not in VALID_CLASSIFICATION:
            classification = "general"

        if classification == "jadwal_shalat":
            shalat_cog = self.bot.get_cog('GetJadwalShalat')
            if not shalat_cog:
                raise Exception("Cog GetJadwalShalat tidak ditemukan di bot.")

            try:
                jadwal_req = await shalat_cog.extract_jadwal_request(question)
                
                if not jadwal_req.kota or jadwal_req.kota.lower() in ['tidak disebutkan', 'tidak ada']:
                    logger.warning(f"Pertanyaan tidak menyebutkan kota, fallback ke general: {question}")
                    classification = "general"
                else:
                    data_jadwal = await shalat_cog.get_jadwal_shalat(
                        jadwal_req.kota,
                        jadwal_req.tanggal
                    )

                    today = get_current_date()
                    time = get_current_time()
                    json_jadwal = json.dumps(data_jadwal, ensure_ascii=False)

                    system_message = (
                        f"current date information: {today}\n"
                        f"this is a filtered data about user's request:\n{json_jadwal}\n\n"
                        "Summarize the data above and provide what the user needs."
                        "Respond in Indonesian, casually, informatively, and focus on the user's request."
                        "don't say greeting. just response about the question"
                    )

                    return await self.bot.ai.get_chat_response(
                        classification="jadwal_shalat",
                        user_id=user_id,
                        system_message=f"time-info: {time}\n\n{system_message}",
                        user_message=question,
                    )

            except ValueError as e:
                if "tidak ditemukan" in str(e):
                    logger.warning(f"Kota tidak valid, fallback ke general: {str(e)}")
                    classification = "general"
                else:
                    logger.error(f"Error handling jadwal shalat: {e}", exc_info=True)
                    return f"Maaf, terjadi kesalahan saat memproses jadwal shalat: {str(e)}"
            except Exception as e:
                logger.error(f"Error handling jadwal shalat: {e}", exc_info=True)
                return f"Maaf, terjadi kesalahan saat memproses jadwal shalat: {str(e)}"
        
        system_message = await db.get_system_prompt(self, guild_id, classification)
        user_profile = await db.get_user_profiles(self, int(user_id))
        current_time = get_server_time()

        info = None
        if classification in ("server_info", "member_info"):
            memories = await search_memories(question, str(guild_id))
            info = "\n".join(memories) if memories else None

        return await self.bot.ai.get_chat_response(
            classification=classification,
            user_id=user_id,
            system_message=f"time-info: {current_time}\n\n{system_message}",
            user_message=question,
            user_info=user_profile.get("user_info") if user_profile else None,
            additional_info=info
        )
                
    async def advance_process(self, message, guild_id):
        user_id = message.author.id
        
        if self.bot.user in message.mentions:
            await self.handle_bot_mention(message)
            return  

        if not await redis.is_ai_mode_on(self.bot, message.channel.id, message.author.id):
            return

        cooldown_time = await redis.ai_cooldown(self.bot, guild_id, user_id, cooldown_seconds=7)
        if cooldown_time > 0:
            embed = await cooldown_embed(cooldown_time)
            await message.channel.send(embed=embed, delete_after=5)
            return

        await self.process_ai_message(message, guild_id)
        
    async def handle_bot_mention(self, message):
        
        bot_mention = f"<@{self.bot.user.id}>"
        ctx = await self.bot.get_context(message)

        messages = []
        async for msg in message.channel.history(limit=10):
            if msg.id == message.id:
                continue
                    
            if msg.author.bot:
                if msg.author.id != self.bot.user.id:
                    continue
                role = "assistant"
            else:
                role = "user"

            if not msg.content.strip():
                continue

            clean_content = msg.content.replace(bot_mention, "@Yumna")
            author_name = getattr(msg.author, "display_name", None) or msg.author.name

            messages.append({
                "role": role,
                "content": f"{author_name}: {clean_content.strip()}"
            })

            if len(messages) >= 8:
                break

        messages.reverse()
        channel_context = "\n".join([m["content"] for m in messages])

        system_message = TAG_PROMPT
        user_name = getattr(message.author, "display_name", None) or message.author.name
        user_message = f"{user_name}: {message.content.replace(bot_mention, '@Yumna').strip()}"

        response = await self.bot.ai.get_channel_context_response(
            classification="general",
            system_message=system_message,
            channel_context=channel_context,
            user_message=user_message
        )

        await ctx.send(response)

    async def process_ai_message(self, message, guild_id):
        user_id = message.author.id
        content = message.content
        attachments = message.attachments
        ctx = await self.bot.get_context(message)

            
    # === IMAGE PROCESSING ===
        if attachments and any(att.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')) for att in attachments):
            image_urls = [att.url for att in attachments if att.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp'))]
            
            combined_content = f"{content}\n\n[Gambar terkait]:\n" + "\n".join(image_urls)
            await redis.save_message(self.bot, user_id, "user", combined_content)
            response_text = await self.bot.ai.vision_image(guild_id, user_id, ctx, user_prompt=content)

            if response_text:
                return response_text
            else:
                logger.info("[ FALLBACK TO GENERAL ] --------- Failed to Analyze Image")
                return await self.send_to_appropriate_api("general", ctx.author.id, ctx.guild.id, content)

        # === AUDIO ===
        audio = next((a for a in attachments if a.filename.lower().endswith((".mp3", ".wav", ".m4a", ".ogg"))), None)
        if audio:
            processing_msg = await message.channel.send("_Processing Audio_...")
            temp_fn = f"tmp_{audio.filename}"
            await audio.save(temp_fn)

            file_hash = await compute_file_hash(temp_fn)
            user_message = await self.bot.ai.speech_to_text(temp_fn, audio.filename)
            
            if not user_message:
                logging.error("[ ERROR TRANSCRIBE TEXT ] --------- [ error ]")
                return await message.channel.send(f"Maaf sepertinya yumna sedang sibuk..")

            os.remove(temp_fn)

            classification = await self.classify_message(user_id, user_message)
            ai_out = await self.send_to_appropriate_api(classification, str(user_id), guild_id, user_message)

            if isinstance(ai_out, list):
                return

            audio_bytes = await self.bot.tts._text_to_speech(ai_out if isinstance(ai_out, str) else str(ai_out))
            
            if not audio_bytes:
                await processing_msg.edit(content="Maaf saat ini server sedang sibuk..\nFallback ke generative text ~")
                response = await self.send_to_appropriate_api("general", ctx.author.id, ctx.guild.id, user_message)
                await asyncio.sleep(2)
                await processing_msg.edit(content=f"{response}")

                return

            out_fn = f"out_{file_hash}.mp3"
            with open(out_fn, "wb") as f:
                f.write(audio_bytes)

            await message.channel.send(file=discord.File(out_fn, filename="response.mp3"))
            os.remove(out_fn)
            return

        # === TEXT ===
        if len(content) > 360:
            await message.channel.send("Pesan terlalu panjang. Yumna bisa pusing!")
            return

        try:
            async with message.channel.typing():
                thinking_msg = await message.channel.send("_Processing_")
                stop_event = asyncio.Event()
                anim_task = asyncio.create_task(animate_thinking(thinking_msg, stop_event))

                try:
                    classification = await self.classify_message(user_id, content)
                    logger.info(f"Question classified as: {classification}")

                    response = await self.send_to_appropriate_api(classification, user_id, guild_id, content)
                    response = bersihkan_think(response)

                    stop_event.set()
                    await anim_task

                    if len(response) > 2000:
                        parts = [response[i:i + 2000] for i in range(0, len(response), 2000)]
                        await thinking_msg.edit(content=parts[0])
                        for part in parts[1:]:
                            await message.channel.send(part)
                    else:
                        await thinking_msg.edit(content=response)

                except Exception as e:
                    stop_event.set()
                    await anim_task
                    await thinking_msg.edit(content=f"⚠️ Error: {str(e)}")
                    logger.error(f"Error processing AI message: {str(e)}", exc_info=True)

        except Exception as e:
            logger.error(f"Error in AI mode: {str(e)}", exc_info=True)
            await message.channel.send("⚠️ Terjadi kesalahan saat memproses pesan ini.")

    @commands.command()
    async def on_ai(self, ctx):
        if ctx.guild.id != self.bot.main_guild_id:
            return
        
        master_channel_id = await redis.get_master_channel_cache(self.bot, ctx.guild.id)
        
        if master_channel_id is None:
            master_channel_id = await db.get_master_channel(self, ctx.guild.id)
            if master_channel_id:
                await redis.save_master_channel_cache(self.bot, ctx.guild.id, master_channel_id)        
        
        if master_channel_id is None:
            await ctx.reply(
                "Hubungi admin untuk mengaktifkan mode AI.\n"
                "-# Mode ini hanya bisa digunakan untuk channel utama Yumna\n"
                "-# atau gunakan command `/set_yumna_channel` untuk mengatur channel utama"
            )
            return
        
        if ctx.channel.id != master_channel_id:
            await ctx.reply(f"Hanya bisa digunakan di <#{master_channel_id}>")
            return
        
        await redis.set_ai_mode(self.bot, ctx.channel.id, ctx.author.id, True)
        
        embed = discord.Embed(
            title="Yumna Ai Bot Aktif",
            description="Aku akan mendengarkan percakapanmu di channel ini.",
            color=discord.Color.red()
        )
        
        if self.bot.user.avatar:
            embed.set_thumbnail(url=self.bot.user.avatar.url)

        await ctx.send(embed=embed)
        
    @commands.command()
    async def off_ai(self, ctx):
        if ctx.guild.id != self.bot.main_guild_id:
            return        

        if  await redis.is_ai_mode_on(self.bot, ctx.channel.id, ctx.author.id):
            await redis.set_ai_mode(self.bot, ctx.channel.id, status=False)
            
            embed = discord.Embed(
                title="Yumna Bot Nonaktif",
                description="Aku berhenti mendengarkan percakapanmu di channel ini.",
                color=discord.Color.red()
            )
            if self.bot.user.avatar:
                embed.set_thumbnail(url=self.bot.user.avatar.url)
            await ctx.send(embed=embed)
        else:
            embed = discord.Embed(
                title="❌ Akses Ditolak",
                description="Yumna sedang tidak mendengarkanmu!",
                color=discord.Color.orange()
            )
            embed.set_footer(text="Hanya user yang mengaktifkan bisa mematikan mode ini")
            await ctx.send(embed=embed, delete_after=5)

    @commands.command(name="ask")
    @requires_balance(200, "askcommand_usage")
    async def ask_command(self, ctx, *, question: str):        
        guild_id_str = str(ctx.guild.id)       # ⬅️ ubah jadi string

        user_id = ctx.author.id  # <-- deklarasi user_id di sini
        guild_id = ctx.guild.id

        cooldown_time = await redis.ai_cooldown(self.bot, guild_id, user_id, cooldown_seconds=4)
                
        if cooldown_time > 0:
            embed = await cooldown_embed(cooldown_time)
            await ctx.send(embed=embed)
            return

        if ctx.message.attachments and any(att.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')) for att in ctx.message.attachments):
            image_urls = [att.url for att in ctx.message.attachments if att.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp'))]
            content = f"{question}\n\n[Gambar terkait]:\n" + "\n".join(image_urls)
            await redis.save_message(self.bot, user_id, "user", content)
            response_text =  await self.bot.ai.vision_image(guild_id, user_id, ctx, user_prompt=question)
            if response_text:
                return response_text
            else:
                logger.info("[ FALLBACK TO GENERAL ] --------- Failed to Analyze Image")
                return await self.send_to_appropriate_api("general", ctx.author.id, guild_id, question)
            
        # 2. Validasi input
        question = validate_input(question, max_length=360)
        if not question:
            return await ctx.send("input tidak valid")
    
        # 3. Kirim pesan "berpikir" sebagai reply
        thinking_msg = await ctx.reply("_Processing_")
    
        try:
            # 4. Klasifikasi
            classification = await self.classify_message(ctx.author.id, question)
            logger.info(f"Permintaan dari: {ctx.author.display_name} (Server: {ctx.guild.name} | ID: {ctx.guild.id}) | Classification : {classification}")
    
            # 5. Panggil API yang sesuai
            response = await self.send_to_appropriate_api(classification, ctx.author.id, guild_id, question)
    
            # 7a. Kalau response adalah dict (generate image) → kirim embed + file
            if isinstance(response, list) and all(isinstance(url, str) and url.startswith("http") for url in response):
                # Ini berarti response adalah list URL gambar
                for url in response:
                    embed = discord.Embed(title="🖼️ Gambar AI", color=discord.Color.blue())
                    embed.set_image(url=url)
                    await thinking_msg.channel.send(embed=embed)
                # await thinking_msg.delete()
                content = f"Gambar telah dikirim: {', '.join(response)}"
                await redis.save_message1(self.bot, user_id, "assistant", content)
                await redis.save_message(self.bot, user_id, "assistant", content)
                try:
                    await thinking_msg.delete()
                except discord.NotFound:
                    pass  # Pesan sudah dihapus
                
                return

            # 7b. Kalau string → bersihkan & kirim teks
            if isinstance(response, str):
                cleaned = bersihkan_think(response)
                if len(cleaned) > 2000:
                    parts = [cleaned[i:i+2000] for i in range(0, len(cleaned), 2000)]
                    await thinking_msg.edit(content=parts[0])
                    for part in parts[1:]:
                        await ctx.reply(part, mention_author=True)
                else:
                    await thinking_msg.edit(content=cleaned)
                return
    
            # 7c. Fallback kalau bukan dict atau str
            await thinking_msg.edit(content="✅ Permintaan selesai, tetapi tidak ada konten untuk ditampilkan.")
            
        except Exception as e:
            await thinking_msg.edit(content=f"Maaf server sedang sibuk!")
            logger.error("Error di ask_command:", exc_info=True)
            raise
        
    @commands.command()
    async def reset(self, ctx):
        user_id = ctx.author.id
        await redis.delete_conversation(self.bot, user_id)
        await ctx.send("🧹 Riwayat percakapanmu telah dihapus dari sistem.")

async def setup(bot):
    """Setup cog"""
    await bot.add_cog(ChatbotCog(bot))
