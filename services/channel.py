from core import db

class TextChannelDB: 
    async def insert_master_channel(guild_id: int, channel_id: int):
        query = """
            INSERT INTO voisa.guild_setting (guild_id, master_text_chid)
            VALUES ($1, $2)
            ON CONFLICT (guild_id)
            DO UPDATE SET master_text_chid = EXCLUDED.master_text_chid
        """
        await db.execute(query, guild_id, channel_id)
        return True
            
    async def get_master_channel(guild_id: int) -> int | None:
        query = """
            SELECT master_text_chid
            FROM voisa.guild_setting
            WHERE guild_id = $1 
        """
        row = await db.fetchrow(query, guild_id)
        return int(row["master_text_chid"]) if row and row["master_text_chid"] else None
        
    async def insert_second_channel(guild_id: int, 
                                    channel_id: int):
        
        query = """
            INSERT INTO voisa.guild_setting (guild_id, second_text_chid)
            VALUES ($1, $2)
            ON CONFLICT (guild_id)
            DO UPDATE SET second_text_chid = EXCLUDED.second_text_chid
        """
        await db.execute(query, guild_id, channel_id)
        return True
            

    async def get_second_channel(self,
                                    guild_id: int) -> int | None:
        query = """
            SELECT second_text_chid
            FROM voisa.guild_setting
            WHERE guild_id = $1 
        """
        row = await db.fetchrow(query, guild_id)
        return int(row["second_text_chid"]) if row and row["second_text_chid"] else None

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
