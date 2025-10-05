# repositories/shop.py

from core import db

class ShopRepository:
    def __init__(self, db):
        self.db = db

    async def clear_today_shop(self, date):
        await self.db.execute("DELETE FROM voisa.shop_items WHERE date=$1", date)

    async def insert_shop_item(self, date, item):
        await self.db.execute(
            """
            INSERT INTO voisa.shop_items
            (day, item_name, effect_type, value, price, duration, stock)
            VALUES ($1,$2,$3,$4,$5,$6,$7)
            """,
            date,
            item["item_name"],
            item["effect_type"],
            item["value"],
            item["price"],
            item.get("duration"),
            item["stock"],
        )

    async def get_today_items(self, date):
        return await self.db.fetch(
            "SELECT * FROM voisa.shop_items WHERE date=$1 ORDER BY id ASC", date
        )

    async def reduce_stock(self, item_id):
        await self.db.execute(
            "UPDATE voisa.shop_items SET stock = stock - 1 WHERE id = $1", item_id
        )

    async def add_to_inventory(self, guild_id, user_id, item, expires_at=None):
        await self.db.execute(
            """
            INSERT INTO voisa.user_inventory
            (guild_id, user_id, item_name, effect_type, value, duration, expires_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7)
            """,
            guild_id,
            user_id,
            item["item_name"],
            item["effect_type"],
            item["value"],
            item.get("duration"),
            expires_at,
        )
