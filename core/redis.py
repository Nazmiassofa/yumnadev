import logging
from redis.asyncio import Redis
from config import DBconf

log = logging.getLogger(__name__)
redis: Redis | None = None

async def init_redis() -> Redis:
    global redis
    try:
        redis = Redis(
            host=DBconf.REDIS_HOST,
            port=6379,
            password=DBconf.REDIS_PASSWORD,
            ssl=True  # biar string, bukan bytes
        )
        # test connection
        await redis.ping()
        log.info("[ REDIS ] --------- Connection established")
        return redis
    except Exception as e:
        log.error(f"[ REDIS ] Failed to connect: {e}")
        raise

async def close_redis():
    global redis
    if redis:
        await redis.close()
        log.info("[ REDIS ] Connection closed")
