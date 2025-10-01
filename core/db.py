import asyncpg
import logging

from contextlib import asynccontextmanager
from config import DBconf

pool: asyncpg.Pool | None = None

async def init_db_pool():
    global pool
    try:
        if pool is None:
            pool = await asyncpg.create_pool(
                user=DBconf.DB_USER,
                password=DBconf.DB_PASSWORD,
                database=DBconf.DB_NAME,
                host=DBconf.DB_HOST,
                port=5432,
                min_size=1,
                max_size=20,
                ssl='require',
            )
            logging.info("[ DB ] -------------------- Connection pool created")
        return pool
    except Exception as e:
        logging.error(f"❌ Gagal membuat database connection pool: {e}")
        return None

async def fetch(query: str, *args):
    async with pool.acquire() as conn:
        return await conn.fetch(query, *args)

async def fetchrow(query: str, *args):
    async with pool.acquire() as conn:
        return await conn.fetchrow(query, *args)
    
async def fetchval(query: str, *args):
    async with pool.acquire() as conn:
        return await conn.fetchval(query, *args)

async def execute(query: str, *args):
    async with pool.acquire() as conn:
        return await conn.execute(query, *args)

@asynccontextmanager
async def db_transaction():
    async with pool.acquire() as conn:
        async with conn.transaction():
            yield conn

@asynccontextmanager
async def transaction():
    async with pool.acquire() as conn:
        async with conn.transaction():
            yield conn
            
@asynccontextmanager
async def db_connection():
    async with pool.acquire() as conn:
        yield conn

async def close_pool():
    global pool
    if pool:
        await pool.close()
        pool = None
        logging.info("[ DB ] -------------------- Connection pool closed")
