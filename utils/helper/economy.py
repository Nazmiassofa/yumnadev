# utils/helper/economy.py

def xp_for_level(level: int, base_xp: int = 5000, power: float = 1.5) -> int:
    """Hitung XP minimum untuk level tertentu berdasarkan kurva eksponensial"""
    return int(base_xp * (level ** power))

def get_level_from_xp(xp: int, base_xp: int = 5000, power: float = 1.5) -> int:
    """Dari total XP, tentukan level saat ini"""
    level = 0
    while xp >= xp_for_level(level + 1, base_xp, power):
        level += 1
    return level