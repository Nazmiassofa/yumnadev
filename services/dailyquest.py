# services/dailyquest.py

class DailyQuest:
    def __init__(self, redis):
        self.redis = redis

    def _key(self, guild_id: int, user_id: int, date: str) -> str:
        return f"dailyquest:{guild_id}:{user_id}:{date}"

    async def get_quest(self, guild_id: int, user_id: int, date: str):
        key = self._key(guild_id, user_id, date)
        data = await self.redis.hgetall(key)
        if not data:
            return {"open_discuss": 0,
                    "post_on_ᴠᴏɪꜱᴀ-ꜰᴇᴇᴅꜱ": 0,
                    "post_on_ᴠᴏɪꜱᴀ-ᴍᴇᴍᴇ": 0,
                    "post_on_ᴠᴏɪꜱᴀ-ꜰᴏᴏᴅꜱ": 0,
                    "create_voice_room": 0,
                    "join_anotherworld": 0
                    }
        return {k.decode(): int(v) for k, v in data.items()}

    async def update_quest(self, guild_id: int, user_id: int, field: str, date: str):
        key = self._key(guild_id, user_id, date)
        await self.redis.hincrby(key, field, 1)
        if not await self.redis.ttl(key) > 0:  # set expire sekali saja
            await self.redis.expire(key, 86400)
        return await self.get_quest(guild_id, user_id, date)
