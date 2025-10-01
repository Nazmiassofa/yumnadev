
class TopMemberCoolDown:
    @staticmethod
    async def dailyinfo_cooldown(self, guild_id: int, user_id: int, cooldown_seconds: int) -> float:
        key = f"dailyinfo_cooldown:{guild_id}:{user_id}"
        ttl = await self.bot.redis.ttl(key)

        if ttl > 0:
            return ttl  # masih cooldown, kembalikan sisa waktu

        await self.bot.redis.set(key, "1", ex=cooldown_seconds)
        return 0  # tidak dalam cooldown
    
    @staticmethod
    async def dailyrank_cooldown(self, guild_id: int, user_id: int, cooldown_seconds: int) -> float:
        key = f"dailyrank_cooldown:{guild_id}:{user_id}"
        ttl = await self.bot.redis.ttl(key)

        if ttl > 0:
            return ttl  # masih cooldown, kembalikan sisa waktu

        await self.bot.redis.set(key, "1", ex=cooldown_seconds)
        return 0  # tidak dalam cooldown
    
    @staticmethod
    async def top_global_cooldown(self, guild_id: int, user_id: int, cooldown_seconds: int) -> float:
        key = f"topguild_cooldown:{guild_id}:{user_id}"
        ttl = await self.bot.redis.ttl(key)

        if ttl > 0:
            return ttl  # masih cooldown, kembalikan sisa waktu

        await self.bot.redis.set(key, "1", ex=cooldown_seconds)
        return 0  # tidak dalam cooldown
    
class VoiceCount:
    @staticmethod
    async def _voice_count_cooldown(self, guild_id: int, user_id: int, cooldown_seconds: int) -> float:
        key = f"voicecount_cooldown:{guild_id}:{user_id}"
        ttl = await self.bot.redis.ttl(key)

        if ttl > 0:
            return ttl  # masih cooldown, kembalikan sisa waktu

        await self.bot.redis.set(key, "1", ex=cooldown_seconds)
        return 0  # tidak dalam cooldown
    
    @staticmethod
    async def _guild_count_cooldown(self, guild_id: int, user_id: int, cooldown_seconds: int) -> float:
        key = f"guildcount_cooldown:{guild_id}:{user_id}"
        ttl = await self.bot.redis.ttl(key)

        if ttl > 0:
            return ttl  # masih cooldown, kembalikan sisa waktu

        await self.bot.redis.set(key, "1", ex=cooldown_seconds)
        return 0  # tidak dalam cooldown
    
class StatistikRedis:
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
    
    #save master   
    @staticmethod
    async def save_master_channel_cache(bot, guild_id: int, channel_id: int, ttl: int = 3600) -> None:
        key = f"voisa:master_channel_ai:{guild_id}"
        await bot.redis.set(key, str(channel_id), ex=ttl)
        
    @staticmethod
    async def statistik_cooldown(self, guild_id: int, user_id: int, cooldown_seconds: int) -> float:
        key = f"topguild_cooldown:{guild_id}:{user_id}"
        ttl = await self.bot.redis.ttl(key)

        if ttl > 0:
            return ttl  # masih cooldown, kembalikan sisa waktu

        await self.bot.redis.set(key, "1", ex=cooldown_seconds)
        return 0  # tidak dalam cooldown
