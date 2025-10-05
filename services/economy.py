from repositories import economy as repo

### ------ Getter 
### ---------------------------------------------------
@staticmethod
async def get_user(guild_id: int, user_id: int, username: str):
    return await repo.get_user(guild_id, user_id, username)

@staticmethod
async def get_balance(guild_id: int, user_id: int):
    row = await repo.get_balance_row(guild_id, user_id)
    return row["balance"] if row and "balance" in row else 0

@staticmethod
async def get_level(guild_id: int, user_id: int):
    row = await repo.get_level(guild_id, user_id)
    return row["level"] if row and "level" in row else 0

@staticmethod
async def get_streaks(guild_id: int, user_id: int):
    row = await repo.get_streaks(guild_id, user_id)
    return {
        "current_streak": row["current_streak"] if row and "current_streak" in row else 0,
        "longest_streak": row["longest_streak"] if row and "longest_streak" in row else 0
    }

@staticmethod
async def get_user_transaction_history(guild_id: int, user_id: int, limit: int = 5, offset: int = 0):
    return await repo.get_user_transactions(guild_id, user_id, limit, offset)

### ------ Setter
### ---------------------------------------------------

@staticmethod
async def adjust_balance(guild_id: int,
                         user_id: int,
                         amount: int,
                         username: str | None = None,
                         reason: str = "adjust"):

    if username is None:
        username = "unknown"

    # tentukan tx_type otomatis
    tx_type = "credit" if amount > 0 else "debit" if amount < 0 else "neutral"

    # repo.adjust_balance signature: (guild_id, user_id, amount, username, reason, tx_type)
    res = await repo.adjust_balance(guild_id, user_id, amount, username=username, reason=reason, tx_type=tx_type)
    if not res:
        return None
    return res.get("balance")


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
    
    level = await get_level(guild_id, user_id)
    
    # hitung bonus berdasarkan level
    bonus_percent = min(level, 10)  # maksimal 10%
    bonus_balance = int(balance_gain * bonus_percent / 100)

    # total balance yang didapat
    total_balance = balance_gain + bonus_balance
    
    return await repo.earn_xp_balance(guild_id, user_id, username, xp_gain, total_balance, reason, tx_type)


### ------ Validator 
### ---------------------------------------------------
@staticmethod
async def validate_voice(guild_id: int,
                         user_id: int,
                         date: str):
    
    return await repo.validate_voice(guild_id, user_id, date)

@staticmethod
async def get_voice_time(guild_id: int,
                         user_id: int,
                         date: str):
    
    return await repo.get_voice_time(guild_id, user_id, date)

@staticmethod
async def get_voice_session(guild_id: int, user_id: int) -> int:
    return await repo.get_voice_overlap_count(guild_id, user_id)


### ------ Spender 
### ---------------------------------------------------
@staticmethod
async def transfer_balance(guild_id: int, 
                           sender_id: int, 
                           sender_username: str,
                           target_id: int,
                           target_username: str,
                           amount: int):
    return await repo.transfer_balance(guild_id, sender_id, sender_username, 
                        target_id, target_username, amount)
    
@staticmethod
async def spend_balance(guild_id: int,
                        user_id: int, 
                        username: str, 
                        price: int = 0, 
                        reason: str = "command_usage", 
                        tx_type: str = "debit"):
    return await repo.spend_balance(guild_id, user_id, username, price, reason, tx_type)


