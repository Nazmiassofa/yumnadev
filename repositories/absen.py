# repositories/absen.py

from datetime import date, datetime, timedelta
from typing import Optional, Dict, Any, List
from core import db
import logging

log = logging.getLogger(__name__)


class AbsenRepository:
    """Repository untuk manage absen data"""
    
    @staticmethod
    async def get_absen(guild_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        row = await db.fetchrow(
            """
            SELECT 
                guild_id,
                user_id,
                current_streak,
                longest_streak,
                total_absen,
                last_absen
            FROM voisa.members_absen 
            WHERE guild_id = $1 AND user_id = $2
            """,
            guild_id, user_id
        )
        
        return dict(row) if row else None
    
    @staticmethod
    async def check_absen(guild_id: int, user_id: int, today: date) -> bool:
        row = await db.fetchrow(
            """
            SELECT 1 FROM voisa.members_absen
            WHERE guild_id = $1 
              AND user_id = $2 
              AND last_absen = $3
            """,
            guild_id, user_id, today
        )
        
        return row is not None
    
    @staticmethod
    async def insert_absen(
        guild_id: int, 
        user_id: int, 
        today: date
    ) -> Dict[str, Any]:
        row = await db.fetchrow(
            """
            INSERT INTO voisa.members_absen 
                (guild_id, user_id, current_streak, longest_streak, total_absen, last_absen)
            VALUES ($1, $2, 1, 1, 1, $3)
            RETURNING 
                guild_id, user_id, current_streak, longest_streak, 
                total_absen, last_absen
            """,
            guild_id, user_id, today
        )
        
        return dict(row)
    
    @staticmethod
    async def update_absen(
        guild_id: int,
        user_id: int,
        today: date,
        new_streak: int,
        new_longest: int
    ) -> Dict[str, Any]:
        row = await db.fetchrow(
            """
            UPDATE voisa.members_absen
            SET 
                current_streak = $3,
                longest_streak = $4,
                total_absen = total_absen + 1,
                last_absen = $5
            WHERE guild_id = $1 AND user_id = $2
            RETURNING 
                guild_id, user_id, current_streak, longest_streak, 
                total_absen, last_absen
            """,
            guild_id, user_id, new_streak, new_longest, today
        )
        
        return dict(row)