    
from typing import List, Any, Dict
import json

MESSAGE_LIMIT = 6
MESSAGE_LIMIT2 = 3

class RedisManager:
    @staticmethod
    async def get_master_channel_cache(bot, guild_id: int) -> int | None:
        key = f"voisa:master_channel_ai:{guild_id}"
        data = await bot.redis.get(key)
        if data:
            try:
                return int(data)
            except ValueError:
                return None
        return None

    @staticmethod
    async def ai_cooldown(bot, guild_id: int, user_id: int, cooldown_seconds: int) -> float:
        key = f"ai_cooldown:{guild_id}:{user_id}"
        ttl = await bot.redis.ttl(key)

        if ttl > 0:
            return ttl

        await bot.redis.set(key, "1", ex=cooldown_seconds)
        return 0

    @staticmethod
    async def is_ai_mode_on(bot, channel_id, user_id=None) -> bool:
        key = f"voisa:ai_mode:{channel_id}"
        data = await bot.redis.get(key)
        if not data:
            return False
        try:
            ai_data = json.loads(data)
            if user_id is not None:
                return ai_data.get("user_id") == user_id
            return True
        except json.JSONDecodeError:
            return False

    @staticmethod
    async def set_ai_mode(bot, channel_id, user_id=None, status=True, ttl=600):
        key = f"voisa:ai_mode:{channel_id}"
        if status:
            data = json.dumps({"status": "on", "user_id": user_id})
            await bot.redis.setex(key, ttl, data)
        else:
            await bot.redis.delete(key)

    @staticmethod
    async def delete_conversation(bot, user_id: str):
        key = f"chat:conversation:{user_id}"
        await bot.redis.delete(key)

    @staticmethod
    async def save_message(bot, user_id: str, role: str, content: str, ttl: int = 360):
        key = f"chat:conversation:{user_id}"
        message = {"role": role, "content": content}
        await bot.redis.rpush(key, json.dumps(message))
        await bot.redis.expire(key, ttl)

    @staticmethod
    async def save_message1(bot, user_id: str, role: str, content: str, ttl: int = 360):
        key = f"voisa_clasify:conversation:{user_id}"
        message = {"role": role, "content": content}
        await bot.redis.expire(key, ttl)
        await bot.redis.rpush(key, json.dumps(message))

    @staticmethod
    async def trim_conversation(bot, user_id: str) -> None:
        key = f"chat:conversation:{user_id}"
        length = await bot.redis.llen(key)
        if length > MESSAGE_LIMIT:
            await bot.redis.ltrim(key, -MESSAGE_LIMIT, -1)

    @staticmethod
    async def get_conversation_history(bot, user_id: str) -> List[Dict[str, Any]]:
        key = f"chat:conversation:{user_id}"
        messages = await bot.redis.lrange(key, 0, -1)
        return [json.loads(m.decode('utf-8')) for m in messages] if messages else []
    
    #redis baru
    @staticmethod
    async def save_master_channel_cache(bot, guild_id: int, channel_id: int, ttl: int = 3600) -> None:
        key = f"voisa:master_channel_ai:{guild_id}"
        await bot.redis.set(key, str(channel_id), ex=ttl)