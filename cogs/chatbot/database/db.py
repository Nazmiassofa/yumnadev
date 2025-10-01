#cogs/chatbot/database/db.py

import logging
import json

from core.db import db_connection

from ..helper.prompt import VALID_CLASSIFICATION, DEFAULT_SYSTEM_PROMPTS

logger = logging.getLogger(__name__)

class DataBaseManager:
    @staticmethod
    async def save_user_profile(self, user_id: int, username: str, introduction: str):
        async with db_connection() as conn:
            if not conn:
                raise Exception("Gagal terhubung ke database.")
            try:
                upsert_query = """
                    INSERT INTO voisa.user_profiles (user_id, username, user_info)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (user_id) DO UPDATE
                    SET username = EXCLUDED.username,
                        user_info = EXCLUDED.user_info
                """
                await conn.execute(upsert_query, user_id, username, introduction)
            except Exception as e:
                logger.error(f"Error set user profile")

            
    @staticmethod
    async def get_system_prompt(self, guild_id: int, classification: str) -> str:
        if classification not in VALID_CLASSIFICATION:
            classification = "general"
        
        cache_key = f"system_prompt:{guild_id}:{classification}"
        cached_prompt = await self.bot.redis.get(cache_key)
        if cached_prompt:
            return cached_prompt.decode('utf-8')  # pastikan decode ke string

        async with db_connection() as conn:
            try:
                query = f"SELECT {classification} FROM voisa.main_prompt WHERE guild_id = $1"
                row = await conn.fetchrow(query, guild_id)
                if row and row.get(classification):
                    prompt = row[classification]
                    await self.bot.redis.set(cache_key, prompt, ex=600)  # cache 5 menit
                    return prompt
                
                default_prompt = DEFAULT_SYSTEM_PROMPTS.get(classification, "")
                await self.bot.redis.set(cache_key, default_prompt, ex=600)
                return default_prompt

            except Exception as e:
                logger.error(f"Database error for guild {guild_id}, classification {classification}: {str(e)}", exc_info=True)
                return DEFAULT_SYSTEM_PROMPTS.get(classification, "")
                       
    @staticmethod
    async def get_user_profiles(self, user_id: int):
        cache_key = f"user_profile:{user_id}"
        cached_data = await self.bot.redis.get(cache_key)
        if cached_data:
            return json.loads(cached_data)

        async with db_connection() as conn:
            if not conn:
                logger.error("Database connection failed")
                return None

            try:
                query = """
                    SELECT user_id, username, user_info
                    FROM voisa.user_profiles
                    WHERE user_id = $1
                """
                result = await conn.fetchrow(query, user_id)

                if result:
                    user_profile = {
                        "user_id": result["user_id"],
                        "username": result["username"],
                        "user_info": result["user_info"]
                    }
                    await self.bot.redis.set(cache_key, json.dumps(user_profile), ex=120)
                    return user_profile
                return None
            except Exception as e:
                logger.error(f"Database error for user {user_id}: {str(e)}", exc_info=True)
                return None
            
    @staticmethod
    async def upsert_guild_prompts(self, guild_id: int, server_info: str, member_info: str):
        async with db_connection() as conn:
            try:
                query = """
                INSERT INTO voisa.main_prompt (guild_id, server_info, member_info)
                VALUES ($1, $2, $3)
                ON CONFLICT (guild_id)
                DO UPDATE SET server_info = EXCLUDED.server_info,
                            member_info = EXCLUDED.member_info;
                """
                await conn.execute(query, guild_id, server_info, member_info)
            except Exception as e:
                logger.error(f"Database error while set guild prompt : {guild_id}")
                
    @staticmethod
    async def get_master_channel(self,
                                 guild_id: int) -> int | None:
        async with db_connection() as conn:
            query = """
                SELECT master_text_chid
                FROM voisa.guild_setting
                WHERE guild_id = $1 
            """
            row = await conn.fetchrow(query, guild_id)
            return int(row["master_text_chid"]) if row and row["master_text_chid"] else None
