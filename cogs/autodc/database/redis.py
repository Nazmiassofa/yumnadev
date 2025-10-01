class TextChannelRedis: 
    @staticmethod
    async def get_master_channel_cache(self, guild_id: int) -> int | None:
        key = f"voisa:master_channel_ai:{guild_id}"
        data = await self.bot.redis.get(key)
        if data:
            try:
                return int(data)
            except ValueError:
                return None
        return None

    @staticmethod
    async def save_master_channel_cache(self, guild_id: int, channel_id: int):
        key = f"voisa:master_channel_ai:{guild_id}"
        await self.bot.redis.set(key, int(channel_id))
        
    @staticmethod
    async def get_second_channel_cache(self, guild_id: int) -> int | None:
        key = f"voisa:second_channel:{guild_id}"
        data = await self.bot.redis.get(key)
        if data:
            try:
                return int(data)
            except ValueError:
                return None
        return None
    
    @staticmethod
    async def save_second_channel_cache(self, guild_id: int, channel_id: int) -> None:
        key = f"voisa:second_channel:{guild_id}"
        await self.bot.redis.set(key, str(channel_id))
        
    @staticmethod
    async def disable_channel_cache(self, guild_id: int):
        key = f"voisa:disabled_channels:{guild_id}"
        await self.bot.redis.set(key, ",".join(str(cid) for cid in disabled))
        
    @staticmethod
    async def enable_channel_cache(self, guild_id: int, channel_id: int):
        key = f"voisa:disabled_channels:{guild_id}"
        await self.bot.redis.delete(key)

class MasterChannelRedis:
    @staticmethod
    async def get_master_channel_cache(self, guild_id: int) -> int | None:
        key = f"voisa:master_channel_ai:{guild_id}"
        data = await self.bot.redis.get(key)
        if data:
            try:
                return int(data)
            except ValueError:
                return None
        return None
    
    @staticmethod
    async def save_master_channel_cache(self, guild_id: int, channel_id: int, ttl: int = 3600) -> None:
        key = f"voisa:master_channel_ai:{guild_id}"
        await self.bot.redis.set(key, str(channel_id), ex=ttl)