# utils/db_operations.py
import logging
from typing import Optional, List, Dict, Any
from core.db import db_connection

class TempVoiceDatabaseMan:
    @staticmethod
    async def set_guild_voice_settings(guild_id: int, 
                                       master_voice_chid: int, 
                                       category: str = "ilmu") -> bool:
        async with db_connection() as conn:
            try:
                query = """
                INSERT INTO voisa.guild_setting (guild_id, master_voice_chid, master_category_name)
                VALUES ($1, $2, $3)
                ON CONFLICT (guild_id)
                DO UPDATE SET master_voice_chid = $2, master_category_name = $3
                """
                await conn.execute(query, guild_id, master_voice_chid, category)
                return True
            except Exception as e:
                logging.error(f"❌ Gagal menyimpan voice settings untuk guild {guild_id}: {e}")
                return False
    
    @staticmethod
    async def get_guild_settings(guild_id: int) -> Dict[str, Any]:
        async with db_connection() as conn:
            try:
                query = """
                SELECT master_category_name, master_voice_chid 
                FROM voisa.guild_setting 
                WHERE guild_id = $1
                """
                record = await conn.fetchrow(query, guild_id)
                return {
                    'master_category_name': record['master_category_name'] if record else 'default',
                    'master_voice_chid': record['master_voice_chid'] if record else None
                }
            except Exception as e:
                logging.error(f"Failed to get guild settings: {e}")
                return {'master_category_name': 'default', 'master_voice_chid': None}

    @staticmethod
    async def get_random_name(guild_id: int) -> Optional[str]:
        async with db_connection() as conn:
            try:
                query = """
                SELECT name
                FROM random_channels_name
                WHERE category = (
                  SELECT master_category_name
                  FROM voisa.guild_setting
                  WHERE guild_id = $1
                )
                ORDER BY RANDOM()
                LIMIT 1
                """
                name: Optional[str] = await conn.fetchval(query, guild_id)
                return name  # bisa None kalau tidak ada
            except Exception as e:
                logging.error(f"[DB] get_random_name error: {e}")
                return None
    
    @staticmethod
    async def get_random_name_ch() -> Optional[str]:
        async with db_connection() as conn:
            try:
                query = """
                SELECT name from random_channels_name
                ORDER BY RANDOM() LIMIT 1
                """
                name: Optional[str] = await conn.fetchval(query)
                return name
            except Exception as e:
                logging.error(f"[DB] get_random_name_ch error: {e}")
                return None
                
    @staticmethod
    async def validate_category(category: str) -> bool:
        async with db_connection() as conn:
            try:
                query = """
                SELECT EXISTS(
                    SELECT 1 FROM random_channels_name 
                    WHERE category = $1 
                    LIMIT 1
                )
                """
                return await conn.fetchval(query, category)
            except Exception as e:
                logging.error(f"Category validation failed: {e}")
                return False

    @staticmethod
    async def get_available_categories() -> List[str]:
        async with db_connection() as conn:
            try:
                query = "SELECT DISTINCT category FROM random_channels_name"
                records = await conn.fetch(query)
                return [r['category'] for r in records]
            except Exception as e:
                logging.error(f"Failed to get categories: {e}")
                return []

    @staticmethod
    async def count_master_channels(guild_id: int) -> int:
        async with db_connection() as conn:
            try:
                query = """
                    SELECT COUNT(master_voice_chid) FROM voisa.guild_setting
                    WHERE guild_id = $1
                """
                result = await conn.fetchval(query, guild_id)
                return result or 0
            except Exception as e:
                logging.error(f"Failed to count master channels for guild {guild_id}: {e}")
                return 0

    @staticmethod
    async def is_premium_guild(guild_id: int) -> bool:
        async with db_connection() as conn:
            try:
                query = """
                    SELECT 1 FROM premium_guilds
                    WHERE guild_id = $1
                    AND (premium_until IS NULL OR premium_until > NOW())
                    LIMIT 1
                """
                result = await conn.fetchrow(query, guild_id)
                return result is not None
            except Exception as e:
                logging.error(f"Failed to check premium status for guild {guild_id}: {e}")
                return False

    @staticmethod
    async def get_all_master_channels(guild_id: int) -> List[Dict[str, Any]]:
        async with db_connection() as conn:
            try:
                query = """
                    SELECT master_voice_chid, master_category_name
                    FROM voisa.guild_setting
                    WHERE guild_id = $1
                """
                rows = await conn.fetch(query, guild_id)
                return [dict(r) for r in rows]
            except Exception as e:
                logging.error(f"Failed to get master channels for guild {guild_id}: {e}")
                return []

    @staticmethod
    async def delete_guild_settings(guild_id: int) -> bool:
        async with db_connection() as conn:
            try:
                query = """
                UPDATE voisa.guild_setting
                SET master_voice_chid = NULL, master_category_name = NULL
                where guild_id = $1"""
                await conn.execute(query, guild_id)
                return True
            except Exception as e:
                logging.error(f"Failed to delete guild settings for guild_id {guild_id}: {e}")
                return False