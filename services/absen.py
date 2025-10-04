
# services/absen.py

from datetime import date, datetime, timedelta
from typing import Optional, Dict, Any, Tuple, List
from repositories.absen import AbsenRepository
import logging

log = logging.getLogger(__name__)

class AbsenService:
    """Service untuk handle absen logic"""
    
    @staticmethod
    async def process_absen(
        guild_id: int,
        user_id: int,
        today: date
    ) -> Optional[Dict[str, Any]]:
        
        # Get current absen data
        current_data = await AbsenRepository.get_absen(guild_id, user_id)
        
        # First time absen
        if not current_data:
            result = await AbsenRepository.insert_absen(guild_id, user_id, today)
            log.info(f"[ ABSEN SYSTEM ] --- Create new data for id : {user_id} | gid: {guild_id}")
            return {
                "success": True,
                "streak": 1,
                "longest_streak": 1,
                "is_new_record": True,
                "total_absen": 1,
                "last_absen": today
            }
        
        # Check if already absen today
        last_absen_date = current_data['last_absen']
        if last_absen_date == today:
            return None
        
        # Calculate new streak (simple logic: yesterday = +1, else = reset to 1)
        current_streak = current_data['current_streak']
        longest_streak = current_data['longest_streak']
        
        yesterday = today - timedelta(days=1)
        
        if last_absen_date == yesterday:
            # Continue streak
            new_streak = current_streak + 1
        else:
            # Auto-reset streak
            new_streak = 1
            log.info(f"[ ABSEN SYSTEM ] reset data for id : {user_id} | last absen at : {last_absen_date})")
        
        # Update longest streak if needed
        new_longest = max(longest_streak, new_streak)
        is_new_record = new_streak > longest_streak
        
        # Update database
        result = await AbsenRepository.update_absen(
            guild_id, user_id, today, new_streak, new_longest
        )
        
        return {
            "success": True,
            "streak": new_streak,
            "longest_streak": new_longest,
            "is_new_record": is_new_record,
            "total_absen": result['total_absen'],
            "last_absen": today
        }
    
    @staticmethod
    async def get_user_absen_info(
        guild_id: int,
        user_id: int
    ) -> Dict[str, Any]:
        """
        Get informasi absen user
        
        Returns:
            Dict dengan absen info atau default values jika belum pernah absen
        """
        data = await AbsenRepository.get_absen(guild_id, user_id)
        
        if not data:
            return {
                "current_streak": 0,
                "longest_streak": 0,
                "total_absen": 0,
                "last_absen": None,
                "has_absen": False
            }
        
        data['has_absen'] = True
        return data
    
    @staticmethod
    async def check_can_absen(
        guild_id: int,
        user_id: int,
        today: date
    ) -> Tuple[bool, str]:
        """
        Check apakah user bisa absen hari ini
        
        Returns:
            Tuple (can_absen: bool, reason: str)
        """
        already_absen = await AbsenRepository.check_absen(guild_id, user_id, today)
        
        if already_absen:
            return False, "Kamu sudah absen hari ini!"
        
        return True, ""