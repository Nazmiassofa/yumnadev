

# REDIS_CONFIG = {
#     "host": "awake-gnat-29070.upstash.io",
#     "port": 6379,
#     "db": 0,
#     "password": "AXGOAAIjcDFhY2Q3ZGIzNWQ1OGM0YTU0YmMzYzgwMGE4ZDJmZDJmZnAxMA",  # Ganti jika ada password
#     "decode_responses": False  # Keep as False untuk handle bytes
# }


"""
Absen Migration Script - Redis to PostgreSQL
Standalone script untuk migrasi data absen dari Redis ke PostgreSQL

Usage:
    python migrate_absen.py

Requirements:
    pip install asyncpg redis asyncio
"""

import asyncio
import json
import logging
import sys
from datetime import datetime
from typing import Dict, Any
import asyncpg

# Import Redis connection dari project Anda
from core.redis import init_redis, close_redis
from config import DBconf

# ============================================================
# CONFIGURATION - EDIT SESUAI ENVIRONMENT ANDA
# ============================================================


POSTGRES_CONFIG = {
    "host": "aws-0-ap-southeast-1.pooler.supabase.com",
    "port": 5432,
    "database": "postgres",
    "user": "postgres.kleshmjkvovkhmziwgvl",
    "password": "Nizar133##"
}

# Redis key pattern
REDIS_KEY_PATTERN = "yumna:absen:*"

# Batch size untuk scan Redis
SCAN_BATCH_SIZE = 100

# ============================================================
# LOGGING SETUP
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('migration.log'),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ============================================================
# MIGRATION CLASS
# ============================================================

class AbsenMigration:
    def __init__(self, redis_client, db_pool):
        self.redis = redis_client
        self.db = db_pool
        self.stats = {
            "total_keys": 0,
            "migrated": 0,
            "skipped": 0,
            "errors": 0,
            "error_details": []
        }
    
    async def migrate(self):
        """Main migration function"""
        log.info("=" * 80)
        log.info("🚀 ABSEN MIGRATION - Redis to PostgreSQL")
        log.info("=" * 80)
        log.info(f"PostgreSQL: {POSTGRES_CONFIG['host']}:{POSTGRES_CONFIG['port']}/{POSTGRES_CONFIG['database']}")
        log.info(f"Pattern: {REDIS_KEY_PATTERN}")
        log.info("=" * 80)
        
        cursor = 0
        batch_num = 0
        
        while True:
            try:
                # Scan Redis keys
                cursor, keys = await self.redis.scan(
                    cursor=cursor,
                    match=REDIS_KEY_PATTERN,
                    count=SCAN_BATCH_SIZE
                )
                
                batch_num += 1
                self.stats["total_keys"] += len(keys)
                
                if keys:
                    log.info(f"\n📦 Batch #{batch_num}: Processing {len(keys)} keys...")
                    
                    # Process each key
                    for key in keys:
                        await self._migrate_single_key(key)
                    
                    # Show progress
                    self._show_progress()
                
                # Break if scan completed
                if cursor == 0:
                    break
                
            except Exception as e:
                log.error(f"❌ Error during scan: {e}")
                self.stats["errors"] += 1
                self.stats["error_details"].append(f"Scan error: {e}")
                break
        
        # Final summary
        self._show_summary()
        
        return self.stats
    
    async def _migrate_single_key(self, key):
        """Migrate single Redis key to PostgreSQL"""
        try:
            # Decode key if bytes (tapi dengan ssl=True seharusnya sudah string)
            key_str = key.decode('utf-8') if isinstance(key, bytes) else key
            
            # Parse key: yumna:absen:{guild_id}:{user_id}
            parts = key_str.split(':')
            
            if len(parts) != 4:
                log.warning(f"⚠️  Invalid key format: {key_str}")
                self.stats["skipped"] += 1
                return
            
            try:
                guild_id = int(parts[2])
                user_id = int(parts[3])
            except ValueError as e:
                log.warning(f"⚠️  Invalid ID in key {key_str}: {e}")
                self.stats["skipped"] += 1
                return
            
            # Get data from Redis
            raw_data = await self.redis.get(key)
            
            if not raw_data:
                log.warning(f"⚠️  No data for key: {key_str}")
                self.stats["skipped"] += 1
                return
            
            # Decode if bytes
            if isinstance(raw_data, (bytes, bytearray)):
                raw_data = raw_data.decode('utf-8')
            
            # Parse JSON
            try:
                data = json.loads(raw_data)
            except json.JSONDecodeError as e:
                log.error(f"❌ Invalid JSON for {key_str}: {e}")
                self.stats["errors"] += 1
                self.stats["error_details"].append(f"JSON error in {key_str}: {e}")
                return
            
            # Extract data
            last_date_str = data.get('last_date')
            streak = data.get('streak', 0)
            
            if not last_date_str:
                log.warning(f"⚠️  No last_date for {key_str}, skipping")
                self.stats["skipped"] += 1
                return
            
            # Parse date
            try:
                last_date = datetime.strptime(last_date_str, '%Y-%m-%d').date()
            except ValueError as e:
                log.error(f"❌ Invalid date format for {key_str}: {last_date_str} - {e}")
                self.stats["errors"] += 1
                self.stats["error_details"].append(f"Date parse error in {key_str}: {e}")
                return
            
            # Insert to PostgreSQL
            async with self.db.acquire() as conn:
                try:
                    await conn.execute("""
                        INSERT INTO voisa.members_absen 
                            (guild_id, user_id, current_streak, longest_streak, total_absen, last_absen)
                        VALUES 
                            ($1, $2, $3, $3, $3, $4)
                        ON CONFLICT (guild_id, user_id) 
                        DO UPDATE SET
                            current_streak = EXCLUDED.current_streak,
                            longest_streak = GREATEST(voisa.members_absen.longest_streak, EXCLUDED.longest_streak),
                            total_absen = GREATEST(voisa.members_absen.total_absen, EXCLUDED.total_absen),
                            last_absen = EXCLUDED.last_absen
                    """, guild_id, user_id, streak, last_date)
                    
                    log.info(f"✅ Guild:{guild_id} | User:{user_id} | Streak:{streak} | Date:{last_date}")
                    self.stats["migrated"] += 1
                    
                except asyncpg.exceptions.PostgresError as e:
                    log.error(f"❌ Database error for {key_str}: {e}")
                    self.stats["errors"] += 1
                    self.stats["error_details"].append(f"DB error in {key_str}: {e}")
            
        except Exception as e:
            log.error(f"❌ Unexpected error for key {key}: {e}")
            self.stats["errors"] += 1
            self.stats["error_details"].append(f"Unexpected error: {e}")
    
    def _show_progress(self):
        """Show current progress"""
        log.info(f"📊 Progress: {self.stats['total_keys']} keys | "
                f"✅ {self.stats['migrated']} migrated | "
                f"⚠️  {self.stats['skipped']} skipped | "
                f"❌ {self.stats['errors']} errors")
    
    def _show_summary(self):
        """Show final summary"""
        log.info("\n" + "=" * 80)
        log.info("✨ MIGRATION COMPLETED")
        log.info("=" * 80)
        log.info(f"📊 Total Keys Scanned    : {self.stats['total_keys']}")
        log.info(f"✅ Successfully Migrated : {self.stats['migrated']}")
        log.info(f"⚠️  Skipped (Invalid)    : {self.stats['skipped']}")
        log.info(f"❌ Errors                : {self.stats['errors']}")
        
        if self.stats['errors'] > 0 and self.stats['error_details']:
            log.info("\n❌ Error Details:")
            for i, error in enumerate(self.stats['error_details'][:10], 1):
                log.info(f"   {i}. {error}")
            if len(self.stats['error_details']) > 10:
                log.info(f"   ... and {len(self.stats['error_details']) - 10} more errors")
        
        log.info("=" * 80)
    
    async def verify(self):
        """Verify migration results"""
        log.info("\n" + "=" * 80)
        log.info("🔍 VERIFICATION")
        log.info("=" * 80)
        
        try:
            # Count Redis keys
            cursor = 0
            redis_count = 0
            
            while True:
                cursor, keys = await self.redis.scan(
                    cursor=cursor,
                    match=REDIS_KEY_PATTERN,
                    count=1000
                )
                redis_count += len(keys)
                if cursor == 0:
                    break
            
            # Count PostgreSQL rows
            async with self.db.acquire() as conn:
                db_count = await conn.fetchval("""
                    SELECT COUNT(*) FROM voisa.members_absen
                """)
                
                # Get top 10 streakers
                top_streakers = await conn.fetch("""
                    SELECT guild_id, user_id, current_streak, longest_streak, 
                           total_absen, last_absen
                    FROM voisa.members_absen
                    ORDER BY current_streak DESC, longest_streak DESC
                    LIMIT 10
                """)
                
                # Get statistics
                stats = await conn.fetchrow("""
                    SELECT 
                        AVG(current_streak)::NUMERIC(10,2) as avg_streak,
                        MAX(current_streak) as max_streak,
                        SUM(total_absen) as total_absens
                    FROM voisa.members_absen
                """)
            
            log.info(f"📊 Redis Keys         : {redis_count}")
            log.info(f"📊 PostgreSQL Rows    : {db_count}")
            log.info(f"📊 Difference         : {abs(redis_count - db_count)}")
            
            if redis_count == db_count:
                log.info("✅ Count matches perfectly!")
            else:
                log.warning(f"⚠️  Count mismatch: {abs(redis_count - db_count)} difference")
            
            log.info("\n📈 Statistics:")
            log.info(f"   Average Streak    : {stats['avg_streak']}")
            log.info(f"   Max Streak        : {stats['max_streak']}")
            log.info(f"   Total Absens      : {stats['total_absens']}")
            
            log.info("\n🏆 Top 10 Streakers:")
            for i, row in enumerate(top_streakers, 1):
                log.info(
                    f"   {i:2d}. Guild:{row['guild_id']} | User:{row['user_id']} | "
                    f"Current:{row['current_streak']:3d} | Longest:{row['longest_streak']:3d} | "
                    f"Total:{row['total_absen']:3d} | Last:{row['last_absen']}"
                )
            
            log.info("=" * 80)
            
            return {
                "redis_count": redis_count,
                "db_count": db_count,
                "match": redis_count == db_count,
                "stats": dict(stats)
            }
            
        except Exception as e:
            log.error(f"❌ Verification error: {e}")
            import traceback
            log.error(traceback.format_exc())
            return None


# ============================================================
# MAIN FUNCTION
# ============================================================

async def main():
    """Main entry point"""
    redis = None
    db_pool = None
    
    try:
        # Connect to Redis menggunakan init_redis() dari project
        log.info("🔌 Connecting to Redis...")
        redis = await init_redis()
        log.info("✅ Redis connected (using project config)")
        
        # Connect to PostgreSQL
        log.info("🔌 Connecting to PostgreSQL...")
        db_pool = await asyncpg.create_pool(
            host=POSTGRES_CONFIG['host'],
            port=POSTGRES_CONFIG['port'],
            database=POSTGRES_CONFIG['database'],
            user=POSTGRES_CONFIG['user'],
            password=POSTGRES_CONFIG['password'],
            min_size=2,
            max_size=10,
            command_timeout=60
        )
        
        # Test connection
        async with db_pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        log.info("✅ PostgreSQL connected and tested")
        
        # Run migration
        migrator = AbsenMigration(redis, db_pool)
        migration_result = await migrator.migrate()
        
        # Verify results
        verification_result = await migrator.verify()
        
        # Final message
        if migration_result['errors'] == 0 and verification_result and verification_result['match']:
            log.info("\n🎉 Migration completed successfully with no errors!")
        elif migration_result['errors'] > 0:
            log.warning(f"\n⚠️  Migration completed with {migration_result['errors']} errors. Check migration.log for details.")
        else:
            log.warning("\n⚠️  Migration completed but verification shows inconsistencies.")
        
        return {
            "migration": migration_result,
            "verification": verification_result
        }
        
    except asyncpg.exceptions.PostgresError as e:
        log.error(f"❌ PostgreSQL connection error: {e}")
        log.error("   Check PostgreSQL connection settings in config.py")
        raise
    except Exception as e:
        log.error(f"❌ Fatal error: {e}")
        import traceback
        log.error(traceback.format_exc())
        raise
        
    finally:
        # Cleanup
        if redis:
            log.info("🔌 Closing Redis connection...")
            try:
                await close_redis()
            except Exception as e:
                log.warning(f"Error closing Redis: {e}")
        
        if db_pool:
            log.info("🔌 Closing PostgreSQL connection...")
            try:
                await db_pool.close()
            except Exception as e:
                log.warning(f"Error closing PostgreSQL: {e}")
            log.info("✅ PostgreSQL closed")


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    print("""
╔════════════════════════════════════════════════════════════════╗
║                                                                ║
║           ABSEN MIGRATION - Redis to PostgreSQL               ║
║                                                                ║
║  ⚠️  WARNING: Make sure you have backed up your data!         ║
║                                                                ║
╚════════════════════════════════════════════════════════════════╝
    """)
    
    # Confirmation
    confirm = input("Continue with migration? (yes/no): ").strip().lower()
    
    if confirm not in ['yes', 'y']:
        print("❌ Migration cancelled.")
        sys.exit(0)
    
    print("\n🚀 Starting migration...\n")
    
    try:
        result = asyncio.run(main())
        print("\n✅ Script completed. Check migration.log for details.")
    except KeyboardInterrupt:
        print("\n\n⚠️  Migration interrupted by user.")
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        print("Check migration.log for details.")
        sys.exit(1)