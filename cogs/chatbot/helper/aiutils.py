import logging
import json

from typing import Optional, List, Dict, Any

from redis import ResponseError
from .prompt import VISION_PROMPT
from .function import bersihkan_think
from ..database.redis import RedisManager as redis
from instructor import patch
from openai import AsyncOpenAI
from config import API
from pydantic import BaseModel


logger = logging.getLogger(__name__)

CLASSIFY_LIMIT = 3

def build_system_message1(system_message, user_prompt=None):
    sys_parts = [system_message.strip()]
    
    system_messages = [{"role": "system", "content": "\n\n".join(sys_parts)}]
    
    if user_prompt and user_prompt.strip():
        system_messages.append({"role": "system", "content": user_prompt.strip()})
    
    return system_messages

class ModelConfig(BaseModel):
    model_name: str
    temperature: float = 0.7
    max_tokens: int = 1000
    frequency_penalty: float = 1.0

class GroqUtils:
    _instance = None
    MESSAGE_LIMIT = 8
    MODEL_MAPPING = {
        "general": ModelConfig(model_name="moonshotai/kimi-k2-instruct", temperature=0.6),
        "jadwal_shalat": ModelConfig(model_name="meta-llama/llama-4-scout-17b-16e-instruct", temperature=0.7),
        "owner_info": ModelConfig(model_name="moonshotai/kimi-k2-instruct"),
        "server_info": ModelConfig(model_name="llama-3.3-70b-versatile"),
        "member_info": ModelConfig(model_name="openai/gpt-oss-120b", temperature=0.6),
        "reasoning": ModelConfig(model_name="openai/gpt-oss-120b", temperature=0.5),
        "latest_info": ModelConfig(model_name="compound-beta", temperature=0.6)
    }

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(GroqUtils, cls).__new__(cls)
            cls._instance.client = patch(AsyncOpenAI(
                base_url="https://api.groq.com/openai/v1",
                api_key=API.GROQ_KEY
            ))
        return cls._instance
    
    def set_bot(self, bot):
        """Inject bot instance sekali saja"""
        self.bot = bot
    
    def get_model_config(self, classification: str) -> ModelConfig:
        return self.MODEL_MAPPING.get(classification.lower(), self.MODEL_MAPPING["general"])


    async def save_message1(self, user_id, role, content,ttl=120):
        """Simpan pesan ke Redis."""
        key = f"voisa_clasify:conversation:{user_id}"
        message = {"role": role, "content": content}
        await self.bot.redis.expire(key, ttl)
        await self.bot.redis.rpush(key, json.dumps(message))
        await self.trim_conversation1(user_id)
    
    async def trim_conversation1(self, user_id):
        """Pangkas riwayat percakapan agar tidak melebihi batas."""
        key = f"voisa_clasify:conversation:{user_id}"
        length = await self.bot.redis.llen(key)
        if length > CLASSIFY_LIMIT:
            await self.bot.redis.ltrim(key, -CLASSIFY_LIMIT, -1)

    async def get_conversation_history1(self, user_id):
        """Dapatkan riwayat percakapan dari Redis."""
        key = f"voisa_clasify:conversation:{user_id}"
        messages = await self.bot.redis.lrange(key, 0, -1)
        return [json.loads(m) for m in messages] if messages else []
    
    async def get_classify_response(
        self,
        user_id: str,
        system_message: str,
        user_message: str,
        user_prompt: Optional[str] = None
    ):

        conversation_history = await self.get_conversation_history1(user_id)
        
        # Bangun pesan sistem menggunakan fungsi terpisah
        conversation = build_system_message1(system_message, user_prompt)
        
        # Tambahkan riwayat percakapan (hingga MESSAGE_LIMIT pesan terakhir)
        if conversation_history:
            keep_messages = min(len(conversation_history), CLASSIFY_LIMIT)
            conversation.extend(conversation_history[-keep_messages:])
        
        # Tambahkan pesan pengguna saat ini
        conversation.append({"role": "user", "content": user_message.strip()})
        
        # Daftar model yang akan digunakan
        models = [
            "meta-llama/llama-4-maverick-17b-128e-instruct"
        ]
        
            # Iterasi melalui model-model yang tersedia
        for model in models:
            try:
                await self.save_message1(user_id, "user", user_message)
            except Exception as e:
                print(f"[WARN] Redis save user failed, continuing anyway: {e}")
            try:
                
                # Panggil API Groq untuk mendapatkan respon
                response =  await self.client.chat.completions.create(
                    messages=conversation,
                    model=model,
                    temperature=0.4,
                    max_tokens=200,
                    frequency_penalty=0,
                    top_p=0.7,
                )
                content = response.choices[0].message.content
                try:
                    await self.save_message1(user_id, "assistant", content)
                except Exception as e:
                    print(f"[WARN] Redis save assistant failed: {e}")
                                
                return content
            except Exception as e:
                print(f"[ERROR - {model}]: {e}")


    async def get_chat_response(
        self,
        classification: str,
        user_id: str,
        system_message: str,
        user_message: str,
        user_info: Optional[str] = None,
        additional_info: Optional[str] = None,
        fallback_models: Optional[List[str]] = None
    ) -> str:
        """Get chat response with model selection based on classification"""
            
        if not isinstance(system_message, str) or not system_message.strip():
            system_message = "Identify your self as yumna.Fun and helpful assistant bot"
        
        # Validasi user_message
        if not isinstance(user_message, str) or not user_message.strip():
            raise ValueError("Pesan pengguna tidak boleh kosong")
        
        model_config = self.get_model_config(classification)
        
        # Get existing conversation history
        conversation_history = await redis.get_conversation_history(self.bot, user_id)
        
        # Build conversation
        conversation = []
        
        # System message parts
        sys_parts = [system_message.strip()]
        
        conversation.append({
            "role": "system",
            "content": "\n\n".join(sys_parts)
        })
        
        if user_info and (user_info := user_info.strip()):
            conversation.append({
                "role": "system",
                "content": f"{user_info}"
            })
        
        if additional_info:
            if not isinstance(additional_info, str):
                additional_info = "\n".join(additional_info)
            additional_info = additional_info.strip()
            if additional_info:
                conversation.append({"role": "system", "content": f"this is some relevan information:\n{additional_info}"})
        
        if conversation_history:
            recent_history = conversation_history[-self.MESSAGE_LIMIT:]
            conversation.extend(recent_history)
            
        conversation.append({
            "role": "user",
            "content": user_message.strip()
        })
        
        # Prepare fallback models if needed
        models_to_try = [model_config.model_name]
        if fallback_models:
            models_to_try.extend(fallback_models)
        
        for model in models_to_try:
            try:
                logger.info(f"Using model: {model} for classification: {classification}")
                
                response = await self.client.chat.completions.create(
                    messages=conversation,
                    model=model,
                    temperature=model_config.temperature,
                    max_tokens=model_config.max_tokens,
                    frequency_penalty=model_config.frequency_penalty,
                )
                
                content = response.choices[0].message.content
                cleaned_content = bersihkan_think(content)
                
                await redis.save_message(self.bot, user_id, "user", user_message.strip())
                await redis.save_message(self.bot, user_id, "assistant", cleaned_content)
                
                return cleaned_content
            except Exception as e:
                logger.warning(f"Failed with model {model}, trying fallback. Error: {str(e)}")
                continue
        
        return "❌ Maaf, terjadi kesalahan saat memproses permintaan Anda."


    async def get_channel_context_response(
        self,
        classification: str,
        system_message: str,
        channel_context: str,
        user_message: str,
        fallback_models: Optional[List[str]] = None
    ) -> str:
        """Get chat response purely based on channel context, without Redis history or user profiles."""

        if not isinstance(system_message, str) or not system_message.strip():
            system_message = "You are Yumna, a fun and helpful assistant bot."

        if not isinstance(user_message, str) or not user_message.strip():
            raise ValueError("Pesan pengguna tidak boleh kosong")

        model_config = self.get_model_config(classification)

        conversation = []

        # System prompt
        conversation.append({
            "role": "system",
            "content": system_message.strip()
        })

        # Channel context (8 latest messages as one block)
        if channel_context and channel_context.strip():
            conversation.append({
                "role": "system",
                "content": f"Here are the latest messages in the discord channel:\n{channel_context.strip()}"
            })

        # User message
        conversation.append({
            "role": "user",
            "content": user_message.strip()
        })

        models_to_try = [model_config.model_name]
        if fallback_models:
            models_to_try.extend(fallback_models)

        for model in models_to_try:
            try:
                logger.info(f"Using model: {model} for classification: {classification}")

                response = await self.client.chat.completions.create(
                    messages=conversation,
                    model=model,
                    temperature=model_config.temperature,
                    max_tokens=model_config.max_tokens,
                    frequency_penalty=model_config.frequency_penalty,
                )

                content = response.choices[0].message.content
                cleaned_content = bersihkan_think(content)

                return cleaned_content
            except Exception as e:
                logger.warning(f"Failed with model {model}, trying fallback. Error: {str(e)}")
                continue

        return "❌ Maaf, terjadi kesalahan saat memproses permintaan Anda."

    async def extract_structured_data(
        self,
        classification: str,
        system_prompt: str,
        user_message: str,
        response_model: Any,
        fallback_models: Optional[List[str]] = None
    ) -> Any:
        """Extract structured data with model selection"""
        model_config = self.get_model_config(classification)
        
        models_to_try = [model_config.model_name]
        if fallback_models:
            models_to_try.extend(fallback_models)
        
        for model in models_to_try:
            try:
                logger.info(f"Using model: {model} for structured extraction")
                
                response = await self.client.chat.completions.create(
                    model=model,
                    response_model=response_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message}
                    ],
                    temperature=model_config.temperature,
                    max_tokens=model_config.max_tokens,
                )
                return response
            except Exception as e:
                logger.warning(f"Failed with model {model}, trying fallback. Error: {str(e)}")
                continue
        
        raise Exception("All models failed for structured extraction")
    
    async def speech_to_text(self, path: str, filename: str) -> str:
        with open(path, "rb") as f:
            transcription = await self.client.audio.transcriptions.create(
                file=(filename, f.read()),
                model="whisper-large-v3-turbo",
                language="id",
                response_format="json"
            )
        return transcription.text
    
    async def vision_image(self, guild_id: int, user_id: int, ctx, *, user_prompt: str = None) -> Optional[str]:
        if not ctx.message.attachments:
            await ctx.send("Silakan lampirkan gambar untuk dianalisis.")
            return None

        image_url = ctx.message.attachments[0].url
        prompt = f"{VISION_PROMPT}\n\nTambahan: {user_prompt}" if user_prompt else VISION_PROMPT

        try:
            async with ctx.typing(): 
                completion = await self.client.chat.completions.create(
                    model="meta-llama/llama-4-maverick-17b-128e-instruct",
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {"type": "image_url", "image_url": {"url": image_url}},
                            ],
                        }
                    ],
                    temperature=0.7,
                    max_completion_tokens=1024,
                    top_p=1,
                    stream=False,
                )

                response_text = completion.choices[0].message.content

            for i in range(0, len(response_text), 2000):
                await ctx.send(response_text[i:i+2000])
               
            await redis.save_message1(self.bot, user_id, "assistant", response_text)
            await redis.save_message(self.bot, user_id, "assistant", response_text)
            return response_text  # ✅ penting untuk digunakan di tempat lain

        except Exception as e:
            await ctx.send(f"❌ Terjadi kesalahan: {str(e)}")
            return None
        
    async def get_vision_mod_response(self, image_url: str, *, system_message: Optional[str] = None) -> Optional[str]:
        # Validasi image_url
        if not isinstance(image_url, str) or not image_url.strip():
            logger.warning("get_mod_vision_response dipanggil tanpa image_url valid.")
            return None

        messages_payload = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": system_message},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }
        ]

        try:
            # Pemanggilan ke API chat completion model vision-capable
            completion = await self.client.chat.completions.create(
                model="meta-llama/llama-4-maverick-17b-128e-instruct",
                messages=messages_payload,
                temperature=0.7,
                max_completion_tokens=1024, 
                top_p=1,
                stream=False,
            )
            # Ambil response
            choices = getattr(completion, "choices", None)
            if not choices:
                logger.warning("get_mod_vision_response: Tidak ada choices di response.")
                return None
            message_obj = choices[0].message if hasattr(choices[0], "message") else None
            response_text = getattr(message_obj, "content", None)
            if not isinstance(response_text, str):
                logger.warning("get_mod_vision_response: content tidak tersedia atau bukan string.")
                return None

            return response_text

        except Exception as e:
            logger.warning(f"Exception di get_mod_vision_response untuk URL {image_url}: {e}")
            return None

    async def get_mod_response(
        self,
        classification: str,
        system_message: str,
        user_message: str,
        fallback_models: Optional[List[str]] = None
    ) -> str:
        """Get chat response with model selection based on classification"""
        
        model_config = self.get_model_config(classification)
                
        conversation = [
            {"role": "system", "content": system_message.strip()},
            {"role": "user", "content": user_message.strip()}
        ]
        
        # Prepare fallback models if needed
        models_to_try = [model_config.model_name]
        if fallback_models:
            models_to_try.extend(fallback_models)
        
        for model in models_to_try:
            try:
                logger.info(f"Using model: {model} for classification: {classification}")
                
                response = await self.client.chat.completions.create(
                    messages=conversation,
                    model=model,
                    temperature=model_config.temperature,
                    max_tokens=model_config.max_tokens,
                    frequency_penalty=model_config.frequency_penalty,
                )
                
                content = response.choices[0].message.content
                cleaned_content = bersihkan_think(content)
                
                return cleaned_content
            except Exception as e:
                logger.warning(f"Failed with model {model}, trying fallback. Error: {str(e)}")
                continue
        
        return "❌ Maaf, terjadi kesalahan saat memproses permintaan Anda."


# Singleton instance
groq_utils = GroqUtils()
