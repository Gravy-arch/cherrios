"""
services/database.py

Async PostgreSQL service using asyncpg.
Call Database.connect() at startup and Database.close() on shutdown.
Pass the instance through aiogram's dispatcher workflow_data (see main.py).
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import asyncpg

import settings

logger = logging.getLogger(__name__)


# ── Tiny data containers (no ORM needed) ──────────────────────────────────────

class UserRecord:
    __slots__ = ("telegram_id", "username", "first_name", "created_at")

    def __init__(self, row: asyncpg.Record) -> None:
        self.telegram_id: int        = row["telegram_id"]
        self.username: Optional[str] = row["username"]
        self.first_name: str         = row["first_name"]
        self.created_at: datetime    = row["created_at"]


class SubscriptionRecord:
    __slots__ = (
        "id", "telegram_id", "plan_type", "status",
        "payment_id", "pay_address", "pay_amount", "pay_currency",
        "price_usd", "created_at", "activated_at", "expires_at", "used_at",
    )

    def __init__(self, row: asyncpg.Record) -> None:
        self.id: int                         = row["id"]
        self.telegram_id: int                = row["telegram_id"]
        self.plan_type: str                  = row["plan_type"]
        self.status: str                     = row["status"]
        self.payment_id: str                 = row["payment_id"]
        self.pay_address: str                = row["pay_address"]
        self.pay_amount: float               = float(row["pay_amount"])
        self.pay_currency: str               = row["pay_currency"]
        self.price_usd: float                = float(row["price_usd"])
        self.created_at: datetime            = row["created_at"]
        self.activated_at: Optional[datetime]= row["activated_at"]
        self.expires_at: Optional[datetime]  = row["expires_at"]
        self.used_at: Optional[datetime]     = row["used_at"]

    @property
    def is_active(self) -> bool:
        if self.status != "active":
            return False
        if self.plan_type == "monthly" and self.expires_at:
            return datetime.now(timezone.utc) < self.expires_at.replace(tzinfo=timezone.utc)
        return True  # one_time active means not yet used


# ── Database service ───────────────────────────────────────────────────────────

class Database:
    """
    Wraps an asyncpg connection pool.

    Usage in main.py
    ----------------
        db = Database()
        await db.connect()
        dp.workflow_data["db"] = db
        # ... run bot ...
        await db.close()
    """

    def __init__(self) -> None:
        self._pool: Optional[asyncpg.Pool] = None

    async def connect(self) -> None:
        self._pool = await asyncpg.create_pool(
            dsn=settings.DATABASE_URL,
            min_size=2,
            max_size=10,
        )
        logger.info("PostgreSQL pool established.")

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            logger.info("PostgreSQL pool closed.")

    # ── Helpers ────────────────────────────────────────────────────────────────

    @property
    def pool(self) -> asyncpg.Pool:
        if not self._pool:
            raise RuntimeError("Database.connect() has not been called yet.")
        return self._pool

    # ── Users ──────────────────────────────────────────────────────────────────

    async def upsert_user(
        self,
        telegram_id: int,
        username: Optional[str],
        first_name: str,
    ) -> None:
        """Insert or update a Telegram user record."""
        await self.pool.execute(
            """
            INSERT INTO users (telegram_id, username, first_name)
            VALUES ($1, $2, $3)
            ON CONFLICT (telegram_id) DO UPDATE
                SET username   = EXCLUDED.username,
                    first_name = EXCLUDED.first_name
            """,
            telegram_id, username, first_name,
        )

    # ── Subscriptions ──────────────────────────────────────────────────────────

    async def create_subscription(
        self,
        telegram_id: int,
        plan_type: str,
        payment_id: str,
        pay_address: str,
        pay_amount: float,
        pay_currency: str,
        price_usd: float,
    ) -> int:
        """
        Insert a pending subscription row.
        Returns the new subscription row id.
        """
        row = await self.pool.fetchrow(
            """
            INSERT INTO subscriptions
                (telegram_id, plan_type, status,
                 payment_id, pay_address, pay_amount, pay_currency, price_usd)
            VALUES ($1, $2, 'pending', $3, $4, $5, $6, $7)
            RETURNING id
            """,
            telegram_id, plan_type,
            payment_id, pay_address, pay_amount, pay_currency, price_usd,
        )
        return row["id"]

    async def activate_subscription(self, payment_id: str) -> Optional[SubscriptionRecord]:
        """
        Mark a subscription as active and set expiry for monthly plans.
        Returns the updated record, or None if not found.
        """
        now = datetime.now(timezone.utc)

        row = await self.pool.fetchrow(
            "SELECT * FROM subscriptions WHERE payment_id = $1", payment_id
        )
        if not row:
            return None

        plan_type = row["plan_type"]
        expires_at = now + timedelta(days=30) if plan_type == "monthly" else None

        updated = await self.pool.fetchrow(
            """
            UPDATE subscriptions
            SET status       = 'active',
                activated_at = $1,
                expires_at   = $2
            WHERE payment_id = $3
            RETURNING *
            """,
            now, expires_at, payment_id,
        )
        return SubscriptionRecord(updated)

    async def get_active_subscription(
        self, telegram_id: int
    ) -> Optional[SubscriptionRecord]:
        """
        Return the user's current active subscription if one exists.
        Handles monthly expiry check in SQL for efficiency.
        """
        row = await self.pool.fetchrow(
            """
            SELECT * FROM subscriptions
            WHERE telegram_id = $1
              AND status = 'active'
              AND (
                plan_type = 'one_time'                          -- active = not used yet
                OR (plan_type = 'monthly' AND expires_at > NOW())
              )
            ORDER BY created_at DESC
            LIMIT 1
            """,
            telegram_id,
        )
        return SubscriptionRecord(row) if row else None

    async def get_subscription_by_payment(
        self, payment_id: str
    ) -> Optional[SubscriptionRecord]:
        row = await self.pool.fetchrow(
            "SELECT * FROM subscriptions WHERE payment_id = $1", payment_id
        )
        return SubscriptionRecord(row) if row else None

    async def mark_one_time_used(self, subscription_id: int) -> None:
        """
        Called by the attendance flow after a one-time subscription
        has been consumed for a meeting verification.
        """
        await self.pool.execute(
            """
            UPDATE subscriptions
            SET status  = 'used',
                used_at = NOW()
            WHERE id = $1 AND plan_type = 'one_time'
            """,
            subscription_id,
        )

    async def expire_stale_monthly(self) -> int:
        """
        Housekeeping — marks expired monthly subscriptions as 'expired'.
        Returns the number of rows updated.
        Optionally call this on a schedule.
        """
        result = await self.pool.execute(
            """
            UPDATE subscriptions
            SET status = 'expired'
            WHERE plan_type = 'monthly'
              AND status    = 'active'
              AND expires_at < NOW()
            """
        )
        count = int(result.split()[-1])
        if count:
            logger.info("Expired %d monthly subscription(s).", count)
        return count

    # ── Meetings ───────────────────────────────────────────────────────────────

    async def create_meeting(
        self,
        telegram_id: int,
        name: str,
        link: str,
    ) -> str:
        """
        Insert a new meeting row with status 'pending'.
        Returns the UUID string of the new meeting.

        This UUID is the shared key for Playwright:
          Playwright queries: SELECT id FROM meetings WHERE telegram_id=$1 AND name=$2
          then saves screenshots to: screenshots/{meeting_id}/{timestamp}.png
        """
        row = await self.pool.fetchrow(
            """
            INSERT INTO meetings (telegram_id, name, link, status)
            VALUES ($1, $2, $3, 'pending')
            RETURNING id
            """,
            telegram_id, name, link,
        )
        return str(row["id"])

    async def get_meetings_for_user(self, telegram_id: int) -> list["MeetingRecord"]:
        """Return all meetings for a user, newest first."""
        rows = await self.pool.fetch(
            """
            SELECT * FROM meetings
            WHERE telegram_id = $1
            ORDER BY created_at DESC
            """,
            telegram_id,
        )
        return [MeetingRecord(r) for r in rows]

    async def get_meeting_by_id(self, meeting_id: str) -> Optional["MeetingRecord"]:
        row = await self.pool.fetchrow(
            "SELECT * FROM meetings WHERE id = $1", meeting_id
        )
        return MeetingRecord(row) if row else None

    async def get_screenshots_for_meeting(
        self, meeting_id: str
    ) -> list["ScreenshotRecord"]:
        """Return all screenshots for a meeting ordered by time taken."""
        rows = await self.pool.fetch(
            """
            SELECT * FROM screenshots
            WHERE meeting_id = $1
            ORDER BY taken_at ASC
            """,
            meeting_id,
        )
        return [ScreenshotRecord(r) for r in rows]

    # ── Playwright requests (bot ↔ Playwright message bus) ────────────────────

    async def create_playwright_request(
        self,
        session_id: str,
        telegram_id: int,
        question: str,
    ) -> str:
        """
        Playwright calls this to ask the user a question via the bot.
        Returns the request UUID so Playwright can poll for the answer.

        session_id — use the meeting UUID so the bot knows which session
                     this belongs to.
        """
        row = await self.pool.fetchrow(
            """
            INSERT INTO playwright_requests
                (session_id, telegram_id, question, status)
            VALUES ($1, $2, $3, 'pending')
            RETURNING id
            """,
            session_id, telegram_id, question,
        )
        return str(row["id"])

    async def get_pending_playwright_requests(
        self,
    ) -> list["PlaywrightRequestRecord"]:
        """
        Called by the bot's background polling task.
        Returns all requests that haven't been sent to the user yet.
        """
        rows = await self.pool.fetch(
            """
            SELECT * FROM playwright_requests
            WHERE status = 'pending'
            ORDER BY created_at ASC
            """
        )
        return [PlaywrightRequestRecord(r) for r in rows]

    async def mark_playwright_request_sent(self, request_id: str) -> None:
        """Bot calls this after it has forwarded the question to the user."""
        await self.pool.execute(
            """
            UPDATE playwright_requests
            SET status = 'sent', sent_at = NOW()
            WHERE id = $1
            """,
            request_id,
        )

    async def answer_playwright_request(
        self,
        request_id: str,
        answer: str,
    ) -> Optional["PlaywrightRequestRecord"]:
        """
        Bot calls this when the user replies.
        Returns the updated record so the bot can confirm to the user.
        """
        row = await self.pool.fetchrow(
            """
            UPDATE playwright_requests
            SET status     = 'answered',
                answer     = $1,
                answered_at = NOW()
            WHERE id = $2
            RETURNING *
            """,
            answer, request_id,
        )
        return PlaywrightRequestRecord(row) if row else None

    async def get_playwright_request_by_id(
        self, request_id: str
    ) -> Optional["PlaywrightRequestRecord"]:
        row = await self.pool.fetchrow(
            "SELECT * FROM playwright_requests WHERE id = $1", request_id
        )
        return PlaywrightRequestRecord(row) if row else None

    async def get_sent_request_for_user(
        self, telegram_id: int
    ) -> Optional["PlaywrightRequestRecord"]:
        """
        Returns the most recent 'sent' (awaiting user reply) request for a user.
        Used by the bot reply handler to match a user's free-text reply to an
        open Playwright question.
        """
        row = await self.pool.fetchrow(
            """
            SELECT * FROM playwright_requests
            WHERE telegram_id = $1
              AND status = 'sent'
            ORDER BY sent_at DESC
            LIMIT 1
            """,
            telegram_id,
        )
        return PlaywrightRequestRecord(row) if row else None


# ── Meeting & screenshot data containers ──────────────────────────────────────
# Defined after Database so they can be referenced in type hints above.

class MeetingRecord:
    __slots__ = (
        "id", "telegram_id", "name", "link",
        "status", "created_at", "completed_at",
    )

    def __init__(self, row: asyncpg.Record) -> None:
        self.id: str                          = str(row["id"])
        self.telegram_id: int                 = row["telegram_id"]
        self.name: str                        = row["name"]
        self.link: str                        = row["link"]
        self.status: str                      = row["status"]
        self.created_at: datetime             = row["created_at"]
        self.completed_at: Optional[datetime] = row["completed_at"]

    @property
    def status_emoji(self) -> str:
        return {
            "pending":     "🕐",
            "in_progress": "🔄",
            "completed":   "✅",
        }.get(self.status, "❓")


class ScreenshotRecord:
    __slots__ = ("id", "meeting_id", "storage_url", "taken_at")

    def __init__(self, row: asyncpg.Record) -> None:
        self.id: int          = row["id"]
        self.meeting_id: str  = str(row["meeting_id"])
        self.storage_url: str = row["storage_url"]
        self.taken_at: datetime = row["taken_at"]


class PlaywrightRequestRecord:
    __slots__ = (
        "id", "session_id", "telegram_id", "question",
        "answer", "status", "created_at", "sent_at", "answered_at",
    )

    def __init__(self, row: asyncpg.Record) -> None:
        self.id: str                          = str(row["id"])
        self.session_id: str                  = str(row["session_id"])
        self.telegram_id: int                 = row["telegram_id"]
        self.question: str                    = row["question"]
        self.answer: Optional[str]            = row["answer"]
        self.status: str                      = row["status"]
        self.created_at: datetime             = row["created_at"]
        self.sent_at: Optional[datetime]      = row["sent_at"]
        self.answered_at: Optional[datetime]  = row["answered_at"]