# services/shop.py

import random
from datetime import datetime, timedelta
from utils.time_utils import JAKARTA_TZ
from repositories.shop import ShopRepository

BASE_POOL = [
    {"item_name": "1500 vcash top-up", "effect_type": "vcash_add", "value": 1500, "price": 1000},
    {"item_name": "5% cashback on yum commands (1d)", "effect_type": "cashback", "value": 5, "price": 2000, "duration": timedelta(days=1)},
    {"item_name": "10% cashback on yum commands (1d)", "effect_type": "cashback", "value": 10, "price": 3000, "duration": timedelta(days=1)},
    {"item_name": "1000 discount on yum command (1 use)", "effect_type": "discount", "value": 1000, "price": 2000},
    {"item_name": "1500 discount on yum command (1 use)", "effect_type": "discount", "value": 1500, "price": 1200},
    {"item_name": "2000 vcash top-up", "effect_type": "vcash_add", "value": 2000, "price": 1600},
]

class ShopService:
    def __init__(self, shop_repo, economy_service):
        self.repo = shop_repo
        self.economy = economy_service

    async def generate_daily_shop(self):
        """Generates the daily shop (called at 7AM GMT+7)."""
        today = datetime.now(JAKARTA_TZ).date()
        await self.repo.clear_today_shop(today)

        items = random.sample(BASE_POOL, k=min(5, len(BASE_POOL)))
        for item in items:
            item["stock"] = random.randint(1, 5)
            await self.repo.insert_shop_item(today, item)

    async def get_today_shop(self):
        today = datetime.now(JAKARTA_TZ).date()
        return await self.repo.get_today_items(today)

    async def buy_item(self, guild_id, user_id, username, item_index):
        """Handles buying logic — deducts vcash, updates DB, returns result msg."""
        today = datetime.now(JAKARTA_TZ).date()
        items = await self.repo.get_today_items(today)
        if not items:
            return False, "🛒 The shop is empty right now."

        if item_index < 1 or item_index > len(items):
            return False, "❌ Invalid item number."

        item = items[item_index - 1]
        if item["stock"] <= 0:
            return False, "❌ That item is out of stock."

        # Deduct balance
        ok = await self.economy.deduct_balance(guild_id, user_id, username, item["price"])
        if not ok:
            return False, "❌ Not enough vcash to buy this item."

        # Update stock
        await self.repo.reduce_stock(item["id"])

        # Expiry handling
        expires_at = None
        if item["duration"]:
            expires_at = datetime.now(JAKARTA_TZ) + item["duration"]

        # Add to inventory
        await self.repo.add_to_inventory(guild_id, user_id, item, expires_at)

        # Handle instant vcash item
        if item["effect_type"] == "vcash_add":
            await self.economy.add_vcash(guild_id, user_id, item["value"])
            return True, f"✅ You bought **{item['item_name']}** and got **+{item['value']} vcash!**"

        return True, f"✅ You bought **{item['item_name']}** for **{item['price']} vcash!**"
