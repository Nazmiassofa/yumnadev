
import logging

from core.db import db_connection, db_transaction
from datetime import datetime

log = logging.getLogger(__name__)

class VoiceCounterQuery:
    @staticmethod
    async def guild_count_option(guild_id: int, 
                                 option: bool):
        try:
            async with db_connection() as conn:
                query = """
                INSERT INTO voisa.guild_setting (guild_id, is_count_enabled)
                VALUES ($1, $2)
                ON CONFLICT (guild_id) DO UPDATE
                SET is_count_enabled = EXCLUDED.is_count_enabled;
                """
                await conn.execute(query, guild_id, option)
        except Exception as e:
            log.error(f"Error in guild_count_option: {e}", exc_info=True)

    @staticmethod
    async def user_count_option(guild_id: int, 
                                user_id: int, 
                                option: bool):
        try:
            async with db_connection() as conn:
                query = """
                INSERT INTO voisa.user_setting (guild_id, user_id, is_count_enabled)
                VALUES ($1,$2,$3)
                ON CONFLICT (guild_id,user_id) DO UPDATE
                SET is_count_enabled = EXCLUDED.is_count_enabled;
                """
                await conn.execute(query, guild_id, user_id, option)
        except Exception as e:
            log.error(f"Error in user_count_option: {e}", exc_info=True)

    @staticmethod
    async def validate_member_count(member_id: int, 
                                    guild_id: int) -> bool:
        try:
            async with db_transaction() as conn:
                await conn.execute("""
                    INSERT INTO voisa.guild_setting (guild_id, is_count_enabled)
                    VALUES ($1, TRUE)
                    ON CONFLICT (guild_id) DO NOTHING;
                """, guild_id)

                query = """
                    SELECT 
                        gs.is_count_enabled AS guild_enabled,
                        us.is_count_enabled AS user_enabled
                    FROM voisa.guild_setting gs
                    LEFT JOIN voisa.user_setting us 
                        ON gs.guild_id = us.guild_id AND us.user_id = $1
                    WHERE gs.guild_id = $2;
                """
                row = await conn.fetchrow(query, member_id, guild_id)

                if row is None:
                    return False  # Harusnya tidak terjadi karena sudah di-upsert

                if not row['guild_enabled']:
                    return False  # Guild menonaktifkan perhitungan

                if row['user_enabled'] is None:
                    return True  # Tidak ada pengaturan user, default-nya aktif
                return row['user_enabled']
        except Exception as e:
            log.error(f"Error in validate_member_count: {e}", exc_info=True)
            return False

    @staticmethod
    async def update_voice_duration(guild_id: int,
                                    member_id: int,
                                    count_date: datetime.date,
                                    username: str,
                                    duration: int
    ):
        try:
            async with db_connection() as conn:
                query = """
                INSERT INTO voisa.voice_counts
                    (guild_id, member_id, count_date, username, total_time, join_count, message_count)
                VALUES ($1, $2, $3, $4, $5, 0, 0)
                ON CONFLICT (guild_id, member_id, count_date)
                DO UPDATE SET
                    username    = EXCLUDED.username,
                    total_time  = voisa.voice_counts.total_time + EXCLUDED.total_time;
                """
                await conn.execute(query, guild_id, member_id, count_date, username, duration)
        except Exception as e:
            log.error(f"Error in update_voice_duration: {e}", exc_info=True)

    @staticmethod
    async def batch_update_voice_stats(data: list[tuple]):
        if not data:
            return
        
        try:
            async with db_connection() as conn:
                query = """
                INSERT INTO voisa.voice_counts
                    (guild_id, member_id, count_date, username, total_time, join_count)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (guild_id, member_id, count_date) DO UPDATE SET
                    username = EXCLUDED.username,
                    total_time = voisa.voice_counts.total_time + EXCLUDED.total_time,
                    join_count = voisa.voice_counts.join_count + EXCLUDED.join_count;
                """
                await conn.executemany(query, data)
        except Exception as e:
            log.error(f"Error in batch_update_voice_stats: {e}", exc_info=True)

    async def insert_voice_event(guild_id: int, 
                                user_id: int, 
                                channel_id: int, 
                                join_time: datetime, 
                                leave_time: datetime, 
                                duration: int):
        try:
            async with db_connection() as conn:
                query = """
                INSERT INTO voisa.voice_sessions 
                    (guild_id, user_id, channel_id, join_time, leave_time, duration)
                VALUES 
                    ($1, $2, $3, $4, $5, $6);
                """
                await conn.execute(query, guild_id, user_id, channel_id, join_time, leave_time, duration)
        except Exception as e:
            log.error(f"Error in insert_voice_event: {e}", exc_info=True)

class VoiceSummaryQuery:
    @staticmethod
    async def get_top_guilds(limit: int = 5):
        try:
            async with db_connection() as conn:
                query = """
                    SELECT 
                        guild_id,
                        username,
                        total_voice,
                        total_joins
                    FROM voisa.voice_leaderboard
                    ORDER BY total_voice DESC
                    LIMIT $1;
                """
                return await conn.fetch(query, limit)
        except Exception as e:
            log.error(f"Error in get_top_guilds: {e}", exc_info=True)
            return []

    @staticmethod        
    async def get_mydaily(user_id: int, 
                          guild_id: int, 
                          today):
        try:
            async with db_connection() as conn:
                date = today  # Tanggal Jakarta
                query = """
                    SELECT total_time FROM voisa.voice_counts
                    WHERE member_id = $1 AND count_date = $3 AND guild_id = $2;
                """
                return await conn.fetchrow(query, user_id, guild_id, date)
        except Exception as e:
            log.error(f"Error in get_mydaily: {e}", exc_info=True)
            return None
    
class StatisticSummaryQuery:
    @staticmethod
    async def get_user_voice_time(guild_id: int, member_id: int, start_date, end_date):
        try:
            async with db_connection() as conn:
                query = """
                    SELECT 
                        count_date,
                        SUM(total_time) AS total_voice_time
                    FROM voisa.voice_counts
                    WHERE guild_id = $1 
                    AND member_id = $2
                    AND count_date BETWEEN $3 AND $4
                    GROUP BY count_date
                    ORDER BY count_date;
                """
                return await conn.fetch(query, guild_id, member_id, start_date, end_date)
        except Exception as e:
            log.error(f"Error in get_user_voice_time: {e}", exc_info=True)
            return None

    @staticmethod
    async def get_voice_stats(guild_id: int, start_date, end_date):
        try:
            async with db_connection() as conn:
                query = """
                    SELECT count_date,
                        COUNT(*) AS total_users
                    FROM voisa.voice_counts
                    WHERE guild_id = $1 AND count_date BETWEEN $2 AND $3
                    GROUP BY count_date
                    ORDER BY count_date
                """
                return await conn.fetch(query, guild_id, start_date, end_date)
        except Exception as e:
            log.error(f"Error in get_voice_stats: {e}", exc_info=True)
            return None
            
    @staticmethod
    async def get_voice_stats_summary(guild_id: int, start_date, end_date):
        try:
            async with db_connection() as conn:
                query = """
                    WITH daily AS (
                        SELECT count_date, COUNT(*) AS total_users
                        FROM voisa.voice_counts
                        WHERE guild_id = $1 AND count_date BETWEEN $2 AND $3
                        GROUP BY count_date
                    )
                    SELECT
                        (SELECT SUM(total_users) FROM daily) AS sum,
                        (SELECT ROUND(AVG(total_users)) FROM daily) AS avg,
                        (SELECT total_users FROM daily ORDER BY total_users ASC LIMIT 1) AS min,
                        (SELECT count_date FROM daily ORDER BY total_users ASC LIMIT 1) AS min_date,
                        (SELECT total_users FROM daily ORDER BY total_users DESC LIMIT 1) AS max,
                        (SELECT count_date FROM daily ORDER BY total_users DESC LIMIT 1) AS max_date
                """
                return await conn.fetchrow(query, guild_id, start_date, end_date)
        except Exception as e:
            log.error(f"Error in get_voice_stats_summary: {e}", exc_info=True)
            return None
        
    @staticmethod
    async def get_voice_traffic(guild_id: int, start_date, end_date):
        try:
            async with db_connection() as conn:
                query = """
                    SELECT 
                        DATE(join_time AT TIME ZONE 'Asia/Jakarta') AS activity_date,
                        COUNT(*) AS total_traffic
                    FROM voisa.voice_sessions
                    WHERE guild_id = $1
                    AND join_time BETWEEN $2 AND $3
                    GROUP BY activity_date
                    ORDER BY activity_date;
                """
                return await conn.fetch(query, guild_id, start_date, end_date)
        except Exception as e:
            log.error(f"Error in get_voice_traffic: {e}", exc_info=True)
            return None
            
    @staticmethod
    async def get_voice_traffic_summary(guild_id: int, start_date, end_date):
        try:
            async with db_connection() as conn:
                query = """
                    WITH daily AS (
                        SELECT 
                            DATE(join_time AT TIME ZONE 'Asia/Jakarta') AS activity_date,
                            COUNT(*) AS total_traffic
                        FROM voisa.voice_sessions
                        WHERE guild_id = $1
                        AND join_time BETWEEN $2 AND $3
                        GROUP BY activity_date
                    )
                    SELECT
                        (SELECT SUM(total_traffic) FROM daily) AS sum,
                        (SELECT ROUND(AVG(total_traffic), 1) FROM daily) AS avg,
                        (SELECT total_traffic FROM daily ORDER BY total_traffic ASC LIMIT 1) AS min,
                        (SELECT activity_date FROM daily ORDER BY total_traffic ASC LIMIT 1) AS min_date,
                        (SELECT total_traffic FROM daily ORDER BY total_traffic DESC LIMIT 1) AS max,
                        (SELECT activity_date FROM daily ORDER BY total_traffic DESC LIMIT 1) AS max_date;
                """
                return await conn.fetchrow(query, guild_id, start_date, end_date)
        except Exception as e:
            log.error(f"Error in get_voice_traffic_summary: {e}", exc_info=True)
            return None

    @staticmethod
    async def get_top_friends(guild_id: int, user_id: int, start_date: datetime, end_date: datetime, limit: int = 4):
        try:
            async with db_connection() as conn:
                query = """
                    WITH target_sessions AS (
                        SELECT *
                        FROM voisa.voice_sessions
                        WHERE user_id = $2
                        AND guild_id = $1
                        AND join_time >= $3 AND join_time < $4
                    ),
                    overlapped_sessions AS (
                        SELECT 
                            o.user_id AS friend_id,
                            GREATEST(t.join_time, o.join_time) AS overlap_start,
                            LEAST(t.leave_time, o.leave_time) AS overlap_end,
                            EXTRACT(EPOCH FROM LEAST(t.leave_time, o.leave_time) - GREATEST(t.join_time, o.join_time))::INTEGER AS overlap_duration
                        FROM target_sessions t
                        JOIN voisa.voice_sessions o
                        ON t.channel_id = o.channel_id
                        AND t.user_id != o.user_id
                        AND o.guild_id = $1
                        AND o.join_time < t.leave_time
                        AND o.leave_time > t.join_time
                        AND o.join_time >= $3 AND o.join_time < $4
                    )
                    SELECT 
                        friend_id,
                        SUM(overlap_duration) AS total_overlap_seconds,
                        COUNT(*) AS sessions_together
                    FROM overlapped_sessions
                    GROUP BY friend_id
                    ORDER BY total_overlap_seconds DESC
                    LIMIT $5;
                """
                return await conn.fetch(query, guild_id, user_id, start_date, end_date, limit)
        except Exception as e:
            log.error(f"Error in get_top_friends: {e}", exc_info=True)
            return []
        
    @staticmethod
    async def get_total_time(guild_id: int, member_id: int, start_date: datetime, end_date: datetime):
        try:
            async with db_connection() as conn:
                query = """
                    SELECT SUM(total_time) AS total_time
                    FROM voisa.voice_counts
                    WHERE guild_id = $1
                    AND member_id = $2
                    AND count_date >= $3 AND count_date < $4
                """
                return await conn.fetch(query, guild_id, member_id, start_date, end_date)
        except Exception as e:
            log.error(f"Error in get_total_time: {e}", exc_info=True)
            return []

    @staticmethod
    async def get_user_time_summary(guild_id: int, member_id: int, start_date, end_date):
        try:
            async with db_connection() as conn:
                query = """
                    WITH daily AS (
                        SELECT 
                            count_date,
                            SUM(total_time) AS total_time_seconds
                        FROM voisa.voice_counts
                        WHERE guild_id   = $1
                          AND member_id  = $2
                          AND count_date BETWEEN $3 AND $4
                        GROUP BY count_date
                    )
                    SELECT
                        (SELECT SUM(total_time_seconds) FROM daily)         AS sum,
                        (SELECT ROUND(AVG(total_time_seconds), 1) FROM daily) AS avg,
                        (SELECT total_time_seconds FROM daily ORDER BY total_time_seconds ASC LIMIT 1) AS min,
                        (SELECT count_date FROM daily ORDER BY total_time_seconds ASC LIMIT 1) AS min_date,
                        (SELECT total_time_seconds FROM daily ORDER BY total_time_seconds DESC LIMIT 1) AS max,
                        (SELECT count_date FROM daily ORDER BY total_time_seconds DESC LIMIT 1) AS max_date
                """
                return await conn.fetchrow(query, guild_id, member_id, start_date, end_date)
        except Exception as e:
            log.error(f"Error in get_user_time_summary: {e}", exc_info=True)
            return None


    @staticmethod
    async def get_user_sessions_summary(guild_id: int, member_id: int, start_date, end_date):
        try:
            async with db_connection() as conn:
                query = """
                    WITH daily AS (
                        SELECT
                            DATE(join_time AT TIME ZONE 'Asia/Jakarta') AS session_date,
                            COUNT(*) AS session_count
                        FROM voisa.voice_sessions
                        WHERE guild_id   = $1
                          AND user_id    = $2
                          AND join_time BETWEEN $3 AND $4
                        GROUP BY session_date
                    )
                    SELECT
                        (SELECT SUM(session_count) FROM daily)         AS sum,
                        (SELECT ROUND(AVG(session_count), 1) FROM daily) AS avg,
                        (SELECT session_count FROM daily ORDER BY session_count ASC LIMIT 1) AS min,
                        (SELECT session_date FROM daily ORDER BY session_count ASC LIMIT 1)  AS min_date,
                        (SELECT session_count FROM daily ORDER BY session_count DESC LIMIT 1) AS max,
                        (SELECT session_date FROM daily ORDER BY session_count DESC LIMIT 1)  AS max_date
                """
                return await conn.fetchrow(query, guild_id, member_id, start_date, end_date)
        except Exception as e:
            log.error(f"Error in get_user_sessions_summary: {e}", exc_info=True)
            return None
        
    @staticmethod
    async def get_user_time_per_day(guild_id: int, member_id: int, start_date, end_date):
        try:
            async with db_connection() as conn:
                query = """
                    SELECT 
                        count_date,
                        SUM(total_time) AS total_time_seconds
                    FROM voisa.voice_counts
                    WHERE guild_id   = $1
                      AND member_id  = $2
                      AND count_date BETWEEN $3 AND $4
                    GROUP BY count_date
                    ORDER BY count_date;
                """
                return await conn.fetch(query, guild_id, member_id, start_date, end_date)
        except:
            return []

    @staticmethod
    async def get_user_sessions_per_day(guild_id: int, member_id: int, start_date, end_date):
        try:
            async with db_connection() as conn:
                query = """
                    SELECT
                        DATE(join_time AT TIME ZONE 'Asia/Jakarta') AS session_date,
                        COUNT(*) AS session_count
                    FROM voisa.voice_sessions
                    WHERE guild_id   = $1
                      AND user_id    = $2
                      AND join_time BETWEEN $3 AND $4
                    GROUP BY session_date
                    ORDER BY session_date;
                """
                return await conn.fetch(query, guild_id, member_id, start_date, end_date)
        except:
            return []

    @staticmethod
    async def get_user_sessions_per_day(guild_id: int, member_id: int, start_date, end_date):
        try:
            async with db_connection() as conn:
                query = """
                    SELECT
                        DATE(join_time AT TIME ZONE 'Asia/Jakarta') AS session_date,
                        COUNT(*) AS session_count
                    FROM voisa.voice_sessions
                    WHERE guild_id   = $1
                      AND user_id    = $2
                      AND join_time BETWEEN $3 AND $4
                    GROUP BY session_date
                    ORDER BY session_date;
                """
                return await conn.fetch(query, guild_id, member_id, start_date, end_date)
        except:
            return []
        
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
