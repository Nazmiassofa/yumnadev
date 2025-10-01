from typing import Optional, List, Dict, Any

CACHE_TTL = 3600

def safe_int(val: str) -> Optional[int]:
    try:
        return int(val)
    except (ValueError, TypeError):
        return None

class RedisManager:
    
    @staticmethod
    async def cache_guild_setting(self, guild_id: int, temp_voice: Optional[int], category: str) -> bool:
        try:
            key = f"yumna:guild_settings:{guild_id}"
            mapping = {
                "category": category
            }
            if temp_voice is not None:
                mapping["master_voice_chid"] = str(temp_voice)

            await self.bot.redis.hset(key, mapping=mapping)
            await self.bot.redis.expire(key, CACHE_TTL)
            return True
        except Exception as e:
            return False

    @staticmethod
    async def get_cache_guild_setting(self, guild_id: int) -> Optional[Dict[str, Any]]:
        try:
            key = f"yumna:guild_settings:{guild_id}"
            data = await self.bot.redis.hgetall(key)
            if not data:
                return None

            master_channel_str = data.get(b"master_voice_chid", b"").decode()
            return {
                "master_voice_chid": safe_int(master_channel_str),
                "master_category_name": data.get(b"master_category_name", b"default").decode()
            }
        except Exception as e:
            return None
    
    @staticmethod    
    async def save_temp_channel(
        self,
        channel_id: int,
        owner_id: int,
        name: str,
        category: str = "default",
        status: str = "public"
    ) -> bool:
        try:
            key = f"yumna:temp_channels:{channel_id}"
            await self.bot.redis.hset(
                key,
                mapping={
                    "owner_id": str(owner_id),
                    "name": name,
                    "category": category,
                    "status": status
                }
            )
            return True
        except Exception as e:
            return False

    @staticmethod        
    async def delete_channel(self, channel_id: int) -> bool:
        try:
            key = f"yumna:temp_channels:{channel_id}"
            await self.bot.redis.delete(key)
            return True
        except Exception as e:
            print(f"Failed to delete temp voice redis key: {e}")
            return False
    
    @staticmethod
    async def clear_all_voice_cache(self) -> bool:
        try:
            keys = await self.bot.redis.keys("yumna:temp_channels:*")
            if keys:
                await self.bot.redis.delete(*keys)
            return True
        except Exception as e:
            print(f"Failed to clear voice cache : {e}")
            return False
    
    @staticmethod
    async def delete_channel_override(self, channel_id: int, member_id: int) -> bool:
        try:
            key = f"yumna:temp_channels:{channel_id}:overrides"
            await self.bot.redis.hdel(key, member_id)
            return True
        except Exception as e:
            print(f"Failed to delete override for channel {channel_id}: {e}")
            return False