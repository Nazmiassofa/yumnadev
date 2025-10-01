from core.db import db_connection

class TextChannelQuery:
    @staticmethod
    async def insert_master_channel(guild_id: int, 
                                    channel_id: int):
        
        async with db_connection() as conn:
            query = """
                INSERT INTO voisa.guild_setting (guild_id, master_text_chid)
                VALUES ($1, $2)
                ON CONFLICT (guild_id)
                DO UPDATE SET master_text_chid = EXCLUDED.master_text_chid
            """
            await conn.execute(query, guild_id, channel_id)
            return True
            
    @staticmethod
    async def get_master_channel(guild_id: int) -> int | None:
        async with db_connection() as conn:
            query = """
                SELECT master_text_chid
                FROM voisa.guild_setting
                WHERE guild_id = $1 
            """
            row = await conn.fetchrow(query, guild_id)
            return int(row["master_text_chid"]) if row and row["master_text_chid"] else None
        
    @staticmethod
    async def insert_second_channel(guild_id: int, 
                                    channel_id: int):
        
        async with db_connection() as conn:
            query = """
                INSERT INTO voisa.guild_setting (guild_id, second_text_chid)
                VALUES ($1, $2)
                ON CONFLICT (guild_id)
                DO UPDATE SET second_text_chid = EXCLUDED.second_text_chid
            """
            await conn.execute(query, guild_id, channel_id)
            return True
            
    @staticmethod
    async def get_second_channel(guild_id: int) -> int | None:
        async with db_connection() as conn:
            query = """
                SELECT second_text_chid
                FROM voisa.guild_setting
                WHERE guild_id = $1 
            """
            row = await conn.fetchrow(query, guild_id)
            return int(row["second_text_chid"]) if row and row["second_text_chid"] else None
