"""
settings.py — Central configuration for the Attendance Bot.

Fill in the values below and you're good to go.
No .env file required (though you can still use one via python-dotenv if you prefer).
"""

# ── Bot ────────────────────────────────────────────────────────────────────────

# Your bot token from @BotFather on Telegram
BOT_TOKEN: str = "8762699868:AAEM9M9NP2BxmGALWeqD81xJbN4vnNvFxH0"

# ── Redis ──────────────────────────────────────────────────────────────────────

# Redis connection URL used for FSM state storage.
# Examples:
#   Local:      "redis://localhost:6379"
#   With auth:  "redis://:yourpassword@localhost:6379"
#   Remote:     "redis://your.redis.host:6379/0"
REDIS_URL: str = "redis://default:KfXVzpDKMQmL7Iihbz4WziwO5YtMrxgB@redis-18906.crce214.us-east-1-3.ec2.cloud.redislabs.com:18906"

# ── PostgreSQL ─────────────────────────────────────────────────────────────────

# asyncpg DSN — fill in your credentials.
# Format: postgresql://user:password@host:port/dbname
DATABASE_URL: str = "postgresql://postgres.iuduvwtkofdyeklwkdzy:0wv6y01dmpQTRsKS@aws-1-eu-central-1.pooler.supabase.com:5432/postgres"

# ── NOWPayments ────────────────────────────────────────────────────────────────

# API key from your NOWPayments dashboard → https://nowpayments.io
NOWPAYMENTS_API_KEY: str = "YOUR_NOWPAYMENTS_API_KEY_HERE"

# ── Supabase Storage (screenshot storage) ─────────────────────────────────────

# From your Supabase project → Settings → API
# Dashboard: https://app.supabase.com
SUPABASE_URL: str = "https://iuduvwtkofdyeklwkdzy.supabase.co"
SUPABASE_SERVICE_KEY: str = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Iml1ZHV2d3Rrb2ZkeWVrbHdrZHp5Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3NDM4Mzg4OCwiZXhwIjoyMDg5OTU5ODg4fQ.3jnGShn3QaVCz9xQ46g68Pl0oFXh0ox3vypiWnA_4Cs"

# The storage bucket name you created in Supabase → Storage
# Bucket should be public so the bot can send URLs directly to Telegram.
SUPABASE_BUCKET: str = "screenshots"

# ── Subscription pricing ───────────────────────────────────────────────────────

# One-time plan is hardcoded at $9 in handlers/subscribe.py.
# Monthly price is fully configurable here — change it any time, no code edits needed.
MONTHLY_PRICE_USD: float = 19.00

# ── Media storage ──────────────────────────────────────────────────────────────

# Directory where converted .y4m video files will be saved.
# The folder is created automatically if it doesn't exist.
MEDIA_DIR: str = "media"
