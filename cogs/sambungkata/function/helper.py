# function/db_helper.py
import random
from typing import Optional, Sequence, List
from core.db import db_connection


class DBHandler:
    """
    Static helper methods to interact with DB. Uses the same db_connection context manager
    as before. Table selection is controlled by language via _table_for_lang.
    """

    ALLOWED_TABLES = {"dictionary", "english_dictionary"}

    @staticmethod
    def _table_for_lang(lang: str) -> str:
        """
        Map lang key to actual table name. Default to 'dictionary' for unknown.
        """
        if lang == "eng":
            return "english_dictionary"
        # default / indo
        return "dictionary"

    @staticmethod
    async def _detect_id_column(conn, table: str) -> Optional[str]:
        """
        Detect whether the table uses 'id' or '_id' as the primary id column.
        Returns 'id', '_id', or None if neither present.
        """
        # Note: table name is validated before calling this (ALLOWED_TABLES)
        rows = await conn.fetch(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = $1
              AND column_name IN ('id', '_id')
            """,
            table
        )
        cols = {r["column_name"] for r in rows}
        if "id" in cols:
            return "id"
        if "_id" in cols:
            return "_id"
        return None

    @staticmethod
    async def _get_valid_word_condition(lang: str) -> str:
        """
        Return WHERE condition for valid words based on language.
        """
        if lang == "indo":
            # Indonesian: allow hyphens but no spaces
            return "word NOT LIKE '% %'"
        else:
            # English: only alphabetic characters, no spaces or hyphens
            return "word NOT LIKE '% %' AND word NOT LIKE '%-%'"

    @staticmethod
    async def get_random_word(lang: str = "indo", max_attempts: int = 60) -> Optional[str]:
        """
        Return a random word by picking random ids in Python.
        Uses table based on lang ('indo' -> 'dictionary', 'eng' -> 'english_dictionary').
        Optimized to use random ID selection instead of database RANDOM().
        """
        table = DBHandler._table_for_lang(lang)
        if table not in DBHandler.ALLOWED_TABLES:
            table = "dictionary"

        valid_condition = await DBHandler._get_valid_word_condition(lang)

        async with db_connection() as conn:
            try:
                id_col = await DBHandler._detect_id_column(conn, table)
                if not id_col:
                    # If no id column, fallback to random selection
                    fallback = await conn.fetchrow(
                        f"SELECT word FROM {table} WHERE {valid_condition} ORDER BY RANDOM() LIMIT 1"
                    )
                    if fallback:
                        w = fallback["word"].lower().strip()
                        return w if DBHandler._is_word_valid_format(w, lang) else None
                    return None

                # Get min and max ID for better range selection
                range_row = await conn.fetchrow(f"SELECT MIN({id_col}) as min_id, MAX({id_col}) as max_id FROM {table}")
                if not range_row or not range_row["max_id"]:
                    return None
                
                min_id = range_row["min_id"] or 1
                max_id = range_row["max_id"]

                # Try random ID picks within actual range
                for _ in range(max_attempts):
                    rand_id = random.randint(min_id, max_id)
                    row = await conn.fetchrow(
                        f"SELECT word FROM {table} WHERE {id_col} = $1 AND {valid_condition} LIMIT 1",
                        rand_id
                    )
                    if row:
                        w = row["word"].lower().strip()
                        if DBHandler._is_word_valid_format(w, lang):
                            return w

                # Fallback: select any single random word that meets criteria
                fallback = await conn.fetchrow(
                    f"SELECT word FROM {table} WHERE {valid_condition} ORDER BY RANDOM() LIMIT 1"
                )
                if fallback:
                    w = fallback["word"].lower().strip()
                    return w if DBHandler._is_word_valid_format(w, lang) else None
                return None
            except Exception as e:
                print(f"[DBHandler.get_random_word] DB error: {e}")
                return None

    @staticmethod
    def _is_word_valid_format(word: str, lang: str) -> bool:
        """Check if word format is valid for the language"""
        if not word:
            return False
        
        if lang == "indo":
            # Indonesian: allow letters and hyphens, but no spaces
            return all(c.isalpha() or c == '-' for c in word) and ' ' not in word
        else:
            # English: only letters, no spaces or hyphens
            return word.isalpha() and ' ' not in word

    @staticmethod
    async def validate_word(word: str, lang: str = "indo") -> bool:
        """
        Validate that a given word exists in table for the language and has valid format.
        """
        table = DBHandler._table_for_lang(lang)
        if table not in DBHandler.ALLOWED_TABLES:
            table = "dictionary"

        clean = word.lower().strip()
        
        # Check format first
        if not DBHandler._is_word_valid_format(clean, lang):
            return False

        valid_condition = await DBHandler._get_valid_word_condition(lang)

        async with db_connection() as conn:
            try:
                row = await conn.fetchrow(
                    f"SELECT 1 FROM {table} WHERE LOWER(word) = $1 AND {valid_condition} LIMIT 1",
                    clean
                )
                return row is not None
            except Exception as e:
                print(f"[DBHandler.validate_word] DB error: {e}")
                return False

    @staticmethod
    async def get_bot_word(prefix: str, used_words: Sequence[str], lang: str = "indo", max_attempts: int = 100) -> Optional[str]:
        """
        Attempt to find a word that starts with prefix using python-random-by-id approach first,
        avoiding used_words and invalid formats. If not found, fallback to ORDER BY RANDOM().
        Optimized for better performance with ID-based random selection.
        """
        table = DBHandler._table_for_lang(lang)
        if table not in DBHandler.ALLOWED_TABLES:
            table = "dictionary"

        prefix = prefix.lower()
        used_lower = {w.lower() for w in used_words} if used_words else set()
        valid_condition = await DBHandler._get_valid_word_condition(lang)

        async with db_connection() as conn:
            try:
                id_col = await DBHandler._detect_id_column(conn, table)
                
                if id_col:
                    # Get ID range for words starting with prefix
                    range_row = await conn.fetchrow(
                        f"""SELECT MIN({id_col}) as min_id, MAX({id_col}) as max_id 
                            FROM {table} 
                            WHERE LOWER(word) LIKE $1 AND {valid_condition}""",
                        f"{prefix}%"
                    )
                    
                    if range_row and range_row["max_id"]:
                        min_id = range_row["min_id"] or 1
                        max_id = range_row["max_id"]
                        
                        # Try random ID picks within range that have matching prefix
                        for _ in range(max_attempts):
                            rand_id = random.randint(min_id, max_id)
                            row = await conn.fetchrow(
                                f"""SELECT word FROM {table} 
                                    WHERE {id_col} = $1 AND LOWER(word) LIKE $2 AND {valid_condition} 
                                    LIMIT 1""",
                                rand_id, f"{prefix}%"
                            )
                            if not row:
                                continue
                            w = row["word"].lower().strip()
                            if not DBHandler._is_word_valid_format(w, lang):
                                continue
                            if w in used_lower:
                                continue
                            return w

                # Fallback to direct random query with optimized approach
                if used_lower and len(used_lower) < 1000:  # Only use NOT IN for reasonable sizes
                    # Build placeholder list for NOT IN
                    placeholders = ",".join([f"${i+2}" for i in range(len(used_lower))])
                    params = [f"{prefix}%"] + list(used_lower)
                    query = (
                        f"""SELECT word FROM {table} 
                            WHERE LOWER(word) LIKE $1 AND {valid_condition} 
                            AND LOWER(word) NOT IN ({placeholders}) 
                            ORDER BY RANDOM() LIMIT 1"""
                    )
                    row = await conn.fetchrow(query, *params)
                else:
                    # For large used_words sets, just get random and check in Python
                    rows = await conn.fetch(
                        f"""SELECT word FROM {table} 
                            WHERE LOWER(word) LIKE $1 AND {valid_condition} 
                            ORDER BY RANDOM() LIMIT 50""",
                        f"{prefix}%"
                    )
                    
                    # Filter out used words in Python
                    for row in rows:
                        w = row["word"].lower().strip()
                        if DBHandler._is_word_valid_format(w, lang) and w not in used_lower:
                            return w
                    row = None

                if row:
                    w = row["word"].lower().strip()
                    return w if DBHandler._is_word_valid_format(w, lang) else None

                return None
            except Exception as e:
                print(f"[DBHandler.get_bot_word] DB error: {e}")
                return None

    # Tambahkan ke db_helper.py dalam class DBHandler

    @staticmethod
    async def update_player_stats(user_id: int, guild_id: int, points_earned: int, is_winner: bool = False):
        """
        Update player statistics in voisa.sambungkata table.
        Creates new record if doesn't exist, updates existing one otherwise.
        """
        async with db_connection() as conn:
            try:
                # Use UPSERT (INSERT ... ON CONFLICT) for atomic operation
                await conn.execute(
                    """
                    INSERT INTO voisa.sambungkata (user_id, guild_id, total_points, total_wins, games_played)
                    VALUES ($1, $2, $3, $4, 1)
                    ON CONFLICT (user_id, guild_id)
                    DO UPDATE SET
                        total_points = voisa.sambungkata.total_points + $3,
                        total_wins = voisa.sambungkata.total_wins + $4,
                        games_played = voisa.sambungkata.games_played + 1
                    """,
                    user_id, guild_id, points_earned, 1 if is_winner else 0
                )
            except Exception as e:
                print(f"[DBHandler.update_player_stats] DB error: {e}")

    @staticmethod
    async def get_player_stats(user_id: int, guild_id: int) -> Optional[dict]:
        """
        Get player statistics for specific user in specific guild.
        Returns dict with stats or None if not found.
        """
        async with db_connection() as conn:
            try:
                row = await conn.fetchrow(
                    """
                    SELECT total_points, total_wins, games_played
                    FROM voisa.sambungkata
                    WHERE user_id = $1 AND guild_id = $2
                    """,
                    user_id, guild_id
                )
                if row:
                    return {
                        "total_points": row["total_points"],
                        "total_wins": row["total_wins"],
                        "games_played": row["games_played"]
                    }
                return None
            except Exception as e:
                print(f"[DBHandler.get_player_stats] DB error: {e}")
                return None

    @staticmethod
    async def get_leaderboard(guild_id: int, limit: int = 5, sort_by: str = "points") -> List[dict]:
        """
        Get leaderboard for specific guild.
        sort_by can be 'points', 'wins', or 'games'
        """
        async with db_connection() as conn:
            try:
                if sort_by == "wins":
                    order_column = "total_wins"
                elif sort_by == "games":
                    order_column = "games_played"
                else:
                    order_column = "total_points"
                
                rows = await conn.fetch(
                    f"""
                    SELECT user_id, total_points, total_wins, games_played
                    FROM voisa.sambungkata
                    WHERE guild_id = $1
                    ORDER BY {order_column} DESC
                    LIMIT $2
                    """,
                    guild_id, limit
                )
                
                return [
                    {
                        "user_id": row["user_id"],
                        "total_points": row["total_points"],
                        "total_wins": row["total_wins"],
                        "games_played": row["games_played"]
                    }
                    for row in rows
                ]
            except Exception as e:
                print(f"[DBHandler.get_leaderboard] DB error: {e}")
                return []