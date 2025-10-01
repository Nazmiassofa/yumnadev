from core import db
from utils.helper.economy import get_level_from_xp

### ------ Fetcher 
### ---------------------------------------------------

@staticmethod
async def get_user(guild_id: int, user_id: int, username: str):
    return await db.fetchrow(
        """
        INSERT INTO voisa.members (guild_id, user_id, username, balance, xp, level, last_active)
        VALUES ($1, $2, $3, 25000, 0, 0, NOW())
        ON CONFLICT (guild_id, user_id) DO UPDATE SET username=EXCLUDED.username
        RETURNING *
        """,
        guild_id, user_id, username
    )

@staticmethod
async def get_balance_row(guild_id: int, user_id: int):
    return await db.fetchrow("SELECT balance FROM voisa.members WHERE guild_id = $1 AND user_id = $2", guild_id, user_id)

@staticmethod
async def get_level(guild_id: int, user_id: int):
    return await db.fetchrow("SELECT level FROM voisa.members WHERE guild_id = $1 AND user_id = $2", guild_id, user_id)

@staticmethod
async def get_user_transactions(guild_id: int, user_id: int, limit: int = 5, offset: int = 0):
    """Ambil transaction history untuk user tertentu"""
    query = (
        "SELECT id, username, amount, balance_before, balance_after, reason, tx_type, created_at "
        "FROM voisa.transactions "
        "WHERE guild_id = $1 AND user_id = $2 "
        "ORDER BY created_at DESC LIMIT $3 OFFSET $4;"
    )
    return await db.fetch(query, guild_id, user_id, limit, offset)

### ------ Earner 
### ---------------------------------------------------
@staticmethod
async def earn_xp_balance(guild_id: int,
                          user_id: int,
                          username: str,
                          xp_gain: int ,
                          balance_gain: int,
                          reason: str,
                          tx_type: str):
    
    member = await get_user(guild_id, user_id, username)

    old_level = member.get("level", 0) if member else 0
    new_xp = (member.get("xp", 0) if member else 0) + xp_gain
    old_balance = (member.get("balance", 0) if member else 0)
    new_balance = old_balance + balance_gain

    new_level = get_level_from_xp(new_xp)

    await db.execute(
        """
        UPDATE voisa.members
        SET xp=$1, balance=$2, level=$3, last_active=NOW(), username=$6
        WHERE guild_id=$4 AND user_id=$5
        """,
        new_xp, new_balance, new_level, guild_id, user_id, username
    )
    
    await log_transaction(guild_id, user_id, username, balance_gain, old_balance, new_balance, reason, tx_type)
    
    return {
        "xp": new_xp,
        "balance": new_balance,
        "old_level": old_level,
        "new_level": new_level
    }

### ------ Validator 
### ---------------------------------------------------
@staticmethod
async def validate_voice(guild_id, user_id, date) -> tuple[bool, int]:
    """Cek apakah user join voice minimal 5 menit"""
    row = await db.fetchrow(
        """
        SELECT total_time
        FROM voisa.voice_counts
        WHERE guild_id=$1 AND member_id=$2 AND count_date=$3
        """, guild_id, user_id, date
    )
    if not row:
        return False, 0
    return row["total_time"] >= 300, row["total_time"]

@staticmethod
async def get_voice_time(guild_id, user_id, date):
    row = await db.fetchrow(
        """
        SELECT total_time
        FROM voisa.voice_counts
        WHERE guild_id=$1 AND member_id=$2 AND count_date=$3
        """, guild_id, user_id, date
    )
    if not row:
        return 0
    return row["total_time"]

@staticmethod
async def get_voice_overlap_count(guild_id: int, user_id: int) -> int:
    row = await db.fetchval(
        """
        WITH overlap_users AS (
            SELECT DISTINCT s2.user_id
            FROM voisa.voice_sessions s1
            JOIN voisa.voice_sessions s2
              ON s1.guild_id = s2.guild_id
             AND s1.channel_id = s2.channel_id
             AND s1.user_id <> s2.user_id
             AND s1.join_time < s2.leave_time
             AND s1.leave_time > s2.join_time
            WHERE s1.guild_id = $1
              AND s1.user_id = $2
              AND DATE(s1.join_time) = CURRENT_DATE
              AND s1.channel_id NOT IN (1371783709073735711, 1374916800747147325, 1378722381199183895)
        )
        SELECT COUNT(*) AS total_people
        FROM overlap_users
        """,
        guild_id, user_id
    )
    return row or 0




### ------ Spender
### ---------------------------------------------------
@staticmethod
async def spend_balance(guild_id: int,
                        user_id: int, 
                        username: str, 
                        price: int = 0, 
                        reason: str = "command_usage", 
                        tx_type: str = "debit"):

    async with db.transaction() as conn:
        await conn.execute(
            """
            INSERT INTO voisa.members
            (guild_id, user_id, username, balance, xp, level, last_active)
            VALUES ($1, $2, $3, 25000, 0, 0, NOW())
            ON CONFLICT (guild_id, user_id) DO NOTHING
            """,
            guild_id, user_id, username
        )

        upd = await conn.fetchrow(
            """
            UPDATE voisa.members
            SET balance = balance - $1,
                last_active = NOW(),
                username = $4
            WHERE guild_id = $2 AND user_id = $3 AND balance >= $1
            RETURNING balance
            """,
            price, guild_id, user_id, username
        )

        if not upd:
            return None

        balance_after = upd["balance"]
        balance_before = balance_after + price
        
        tx = await log_transaction(guild_id, user_id, username, -abs(price), balance_before, balance_after, reason, tx_type)

        return {"balance": balance_after, "tx_id": tx["id"]}

@staticmethod
async def log_transaction(
    guild_id: int,
    user_id: int,
    username: str,
    amount: int,
    balance_before: int,
    balance_after: int,
    reason: str,
    tx_type: str
):
    return await db.fetchrow(
        """
        INSERT INTO voisa.transactions
        (guild_id, user_id, username, amount, balance_before, balance_after, reason, tx_type)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
        RETURNING id
        """,
        guild_id, user_id, username, amount, balance_before, balance_after, reason, tx_type
    )
    
@staticmethod
async def transfer_balance(guild_id: int, sender_id: int, sender_username: str, 
                        target_id: int, target_username: str, amount: int):
    """Transfer balance dengan biaya admin 50%"""

    if amount <= 0:
        return None

    fee = int(amount * 0.50)
    total_deduction = amount + fee

    async with db.transaction() as conn:
        # Pastikan kedua akun ada (default balance 20000)
        await conn.execute(
            """
            INSERT INTO voisa.members (guild_id, user_id, username, balance, xp, level, last_active)
            VALUES ($1, $2, $3, 20000, 0, 0, NOW())
            ON CONFLICT (guild_id, user_id) DO NOTHING
            """,
            guild_id, sender_id, sender_username
        )
        await conn.execute(
            """
            INSERT INTO voisa.members (guild_id, user_id, username, balance, xp, level, last_active)
            VALUES ($1, $2, $3, 20000, 0, 0, NOW())
            ON CONFLICT (guild_id, user_id) DO NOTHING
            """,
            guild_id, target_id, target_username
        )

        # Ambil dan kunci baris untuk menghindari race condition
        sender_row = await conn.fetchrow(
            "SELECT balance FROM voisa.members WHERE guild_id=$1 AND user_id=$2 FOR UPDATE",
            guild_id, sender_id
        )
        target_row = await conn.fetchrow(
            "SELECT balance FROM voisa.members WHERE guild_id=$1 AND user_id=$2 FOR UPDATE",
            guild_id, target_id
        )

        if not sender_row or not target_row:
            return None

        if sender_row["balance"] < total_deduction:
            return None

        new_sender_balance = sender_row["balance"] - total_deduction
        new_target_balance = target_row["balance"] + amount

        # Update balances
        await conn.execute(
            "UPDATE voisa.members SET balance=$1, last_active=NOW() WHERE guild_id=$2 AND user_id=$3",
            new_sender_balance, guild_id, sender_id
        )
        await conn.execute(
            "UPDATE voisa.members SET balance=$1, last_active=NOW() WHERE guild_id=$2 AND user_id=$3",
            new_target_balance, guild_id, target_id
        )

        sender_tx = await log_transaction(
            guild_id, sender_id, sender_username,
            -abs(total_deduction),
            sender_row["balance"], new_sender_balance,
            f"transfer {amount} to {target_username} + fee {fee}",
            "transfer"
        )

        target_tx = await log_transaction(
            guild_id, target_id, target_username,
            amount,
            target_row["balance"], new_target_balance,
            f"receive from {sender_username}",
            "transfer"
        )
        
        return {
            "sender_balance": new_sender_balance,
            "target_balance": new_target_balance,
            "amount": amount,
            "fee": fee,
            "sender_tx_id": sender_tx["id"],
            "target_tx_id": target_tx["id"]
        }


### ------ Setter
### ---------------------------------------------------
@staticmethod
async def adjust_balance(
    guild_id: int,
    user_id: int,
    amount: int,
    username: str,
    reason: str = "adjust",
    tx_type: str = "credit"
):

    if amount == 0:
        # nothing to do
        return {"balance": (await get_balance_row(guild_id, user_id))["balance"]} if await get_balance_row(guild_id, user_id) else None

    async with db.transaction() as conn:
        # Pastikan member ada (default balance 20000)
        await conn.execute(
            """
            INSERT INTO voisa.members
            (guild_id, user_id, username, balance, xp, level, last_active)
            VALUES ($1, $2, $3, 20000, 0, 0, NOW())
            ON CONFLICT (guild_id, user_id) DO NOTHING
            """,
            guild_id, user_id, username
        )

        # Ambil & kunci baris member untuk menghindari race condition
        row = await conn.fetchrow(
            "SELECT balance FROM voisa.members WHERE guild_id = $1 AND user_id = $2 FOR UPDATE",
            guild_id, user_id
        )

        if not row:
            return None

        balance_before = row["balance"]
        balance_after = balance_before + amount  # amount can be negative

        # Jika debit dan saldo tidak cukup -> batal
        if amount < 0 and balance_before < abs(amount):
            return None

        # Update balance
        await conn.execute(
            """
            UPDATE voisa.members
            SET balance = $1,
                last_active = NOW(),
                username = $4
            WHERE guild_id = $2 AND user_id = $3
            """,
            balance_after, guild_id, user_id, username
        )
        
        tx = await log_transaction(guild_id, user_id, username, amount, balance_before, balance_after, reason, tx_type)

        return {"balance": balance_after, "tx_id": tx["id"]}

