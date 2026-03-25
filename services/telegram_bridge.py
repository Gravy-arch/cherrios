"""
services/telegram_bridge.py  (lives inside the Playwright project, not the bot)

Drop-in class that gives your Playwright Executor four capabilities:

  1. ask_user(question)              — send a question to the Telegram user and
                                       block until they reply (via the bot).

  2. send_screenshot(path)           — send a screenshot directly to the user
                                       via Telegram Bot API (instant, no DB).

  3. send_message(text)              — send a plain text message to the user.

  4. save_progress_screenshot(path)  — upload a screenshot to Supabase Storage
                                       AND insert a row into the screenshots table
                                       so it appears in the user's /track → 📸 Progress view.

─────────────────────────────────────────────────────────────────────────────
HOW IT WORKS
─────────────────────────────────────────────────────────────────────────────

         Playwright                Supabase DB               Bot
         ──────────                ───────────               ───

ask_user()  ───INSERT──►  playwright_requests (pending)
                                    │
                          ◄─poll every 2s─── background task in main.py
                                    │
                          bot sends question to user
                          UPDATE status → 'sent'
                                    │
                                 user replies + confirms
                                    │
                          bot handler updates row
                          UPDATE status → 'answered', answer = '...'
                                    │
            ◄──poll detects 'answered'───
            returns answer string


send_screenshot() / send_message()
         Playwright  ──────────────────── Telegram Bot API ──► user
         (direct HTTP, no DB, instant)


save_progress_screenshot()
         Playwright  ──► Supabase Storage (upload PNG)
                    ──► screenshots table (INSERT public URL)
                                    │
                          user taps 📸 Progress in bot
                          bot reads screenshots rows ──► sends photos

─────────────────────────────────────────────────────────────────────────────
USAGE
─────────────────────────────────────────────────────────────────────────────

    from services.telegram_bridge import TelegramBridge

    async with TelegramBridge(
        telegram_id=TELEGRAM_USER_ID,
        session_id=MEETING_UUID,
        db_url=DATABASE_URL,
        bot_token=BOT_TOKEN,
        supabase_url=SUPABASE_URL,           # needed for save_progress_screenshot
        supabase_key=SUPABASE_SERVICE_KEY,   # needed for save_progress_screenshot
        supabase_bucket="screenshots",       # your bucket name
    ) as bridge:
        executor = Executor(memory, bridge=bridge)

        # Ask user a question (blocks until they confirm in Telegram)
        username = await bridge.ask_user("Enter your student username:")

        # Send instant progress shot to the user
        await bridge.send_screenshot("page.png", caption="Logged in ✅")

        # Save screenshot to Supabase so it appears in /track → 📸 Progress
        await bridge.save_progress_screenshot("page.png", caption="Logged in ✅")

        # Plain status message
        await bridge.send_message("⏳ Navigating to quiz page…")
"""

import asyncio
import logging
import time
from pathlib import Path
from typing import Optional

import aiohttp
import asyncpg

logger = logging.getLogger(__name__)

POLL_INTERVAL: float   = 2.0
DEFAULT_TIMEOUT: float = 300.0   # 5 minutes


class TelegramBridge:
    """
    Async bridge between your Playwright Executor and the Telegram user.

    supabase_url / supabase_key / supabase_bucket are optional — only
    needed if you call save_progress_screenshot().
    """

    def __init__(
        self,
        telegram_id: int,
        session_id: str,
        db_url: str,
        bot_token: str,
        supabase_url: Optional[str] = None,
        supabase_key: Optional[str] = None,
        supabase_bucket: str = "screenshots",
    ) -> None:
        self.telegram_id      = telegram_id
        self.session_id       = session_id
        self._db_url          = db_url
        self._bot_token       = bot_token
        self._supabase_url    = supabase_url
        self._supabase_key    = supabase_key
        self._supabase_bucket = supabase_bucket
        self._conn: Optional[asyncpg.Connection] = None

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Open a direct asyncpg connection to Supabase Postgres."""
        self._conn = await asyncpg.connect(self._db_url)
        logger.info("TelegramBridge connected to DB (session=%s)", self.session_id)

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            logger.info("TelegramBridge DB connection closed.")

    # ── Ask user a question and wait for their reply ───────────────────────────

    async def ask_user(
        self,
        question: str,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> str:
        """
        Insert a question into playwright_requests, then poll until the bot
        has relayed it to the user and the user has replied.

        Returns the user's answer as a string.
        Raises TimeoutError if no answer arrives within `timeout` seconds.
        """
        if not self._conn:
            raise RuntimeError("call connect() first")

        # Insert the question row
        row = await self._conn.fetchrow(
            """
            INSERT INTO playwright_requests
                (session_id, telegram_id, question, status)
            VALUES ($1, $2, $3, 'pending')
            RETURNING id
            """,
            self.session_id, self.telegram_id, question,
        )
        request_id = str(row["id"])
        logger.info("Inserted playwright_request id=%s question=%r", request_id, question)

        # Poll until answered or timeout
        elapsed = 0.0
        while elapsed < timeout:
            await asyncio.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL

            result = await self._conn.fetchrow(
                "SELECT status, answer FROM playwright_requests WHERE id = $1",
                request_id,
            )

            if result and result["status"] == "answered" and result["answer"] is not None:
                logger.info("Got answer for request %s: %r", request_id, result["answer"])
                return result["answer"]

            if result and result["status"] == "timed_out":
                raise TimeoutError(
                    f"User did not respond to: {question!r}"
                )

        # Mark as timed out so the bot stops waiting too
        await self._conn.execute(
            "UPDATE playwright_requests SET status = 'timed_out' WHERE id = $1",
            request_id,
        )
        raise TimeoutError(
            f"No reply from user within {timeout}s for question: {question!r}"
        )

    # ── Send a screenshot directly to the user ─────────────────────────────────

    async def send_screenshot(
        self,
        image_path: str,
        caption: str = "📸 Progress screenshot",
    ) -> None:
        """
        Send a screenshot image directly to the Telegram user.
        Reads the file from disk and posts it to the Bot API.
        No DB involved — this is instant.
        """
        path = Path(image_path)
        if not path.exists():
            logger.warning("send_screenshot: file not found: %s", image_path)
            return

        url = f"https://api.telegram.org/bot{self._bot_token}/sendPhoto"

        async with aiohttp.ClientSession() as session:
            with open(path, "rb") as f:
                form = aiohttp.FormData()
                form.add_field("chat_id", str(self.telegram_id))
                form.add_field("caption", caption)
                form.add_field(
                    "photo", f,
                    filename=path.name,
                    content_type="image/png",
                )
                async with session.post(url, data=form) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.error(
                            "send_screenshot failed [%d]: %s", resp.status, body
                        )
                    else:
                        logger.info("Screenshot sent to user %d", self.telegram_id)

    # ── Send a plain text message to the user ──────────────────────────────────

    async def send_message(self, text: str) -> None:
        """
        Send a plain text message directly to the Telegram user via Bot API.
        Supports HTML formatting (bold, italic, code etc.).
        No DB involved — instant.
        """
        url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
        payload = {
            "chat_id": self.telegram_id,
            "text": text,
            "parse_mode": "HTML",
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    logger.error(
                        "send_message failed [%d]: %s", resp.status, body
                    )

    # ── Save screenshot to Supabase Storage + screenshots table ──────────────────

    async def save_progress_screenshot(
        self,
        image_path: str,
        caption: str = "",
    ) -> Optional[str]:
        """
        Upload a screenshot to Supabase Storage and insert a row into the
        `screenshots` table so it appears in the user's /track → 📸 Progress
        view inside the bot.

        Also sends the screenshot instantly to the user via Telegram so they
        see it in real time — same as send_screenshot().

        Parameters
        ----------
        image_path : path to the PNG/JPG file on disk
        caption    : optional caption shown in Telegram and stored implicitly
                     via the filename timestamp

        Returns the public Supabase Storage URL, or None on failure.

        Requires supabase_url, supabase_key, and supabase_bucket to be set
        in the constructor.
        """
        if not self._supabase_url or not self._supabase_key:
            logger.error(
                "save_progress_screenshot: supabase_url and supabase_key "
                "must be provided in the TelegramBridge constructor."
            )
            return None

        if not self._conn:
            raise RuntimeError("call connect() first")

        path = Path(image_path)
        if not path.exists():
            logger.warning("save_progress_screenshot: file not found: %s", image_path)
            return None

        # ── 1. Upload to Supabase Storage ──────────────────────────────────────
        ts           = int(time.time() * 1000)
        storage_path = f"screenshots/{self.session_id}/{ts}.png"
        upload_url   = (
            f"{self._supabase_url.rstrip('/')}"
            f"/storage/v1/object/{self._supabase_bucket}/{storage_path}"
        )
        public_url   = (
            f"{self._supabase_url.rstrip('/')}"
            f"/storage/v1/object/public/{self._supabase_bucket}/{storage_path}"
        )

        image_bytes = path.read_bytes()

        async with aiohttp.ClientSession() as session:
            async with session.post(
                upload_url,
                data=image_bytes,
                headers={
                    "Authorization":  f"Bearer {self._supabase_key}",
                    "Content-Type":   "image/png",
                    "x-upsert":       "true",   # overwrite if same timestamp
                },
            ) as resp:
                if resp.status not in (200, 201):
                    body = await resp.text()
                    logger.error(
                        "Supabase Storage upload failed [%d]: %s", resp.status, body
                    )
                    return None

        logger.info("Screenshot uploaded to Supabase: %s", public_url)

        # ── 2. Insert row into screenshots table ───────────────────────────────
        await self._conn.execute(
            """
            INSERT INTO screenshots (meeting_id, storage_url)
            VALUES ($1, $2)
            """,
            self.session_id, public_url,
        )

        # ── 3. Also send instantly to user via Telegram ────────────────────────
        tg_caption = caption or "📸 Progress screenshot"
        await self.send_screenshot(image_path, caption=tg_caption)

        return public_url

    # ── Context manager support ────────────────────────────────────────────────

    async def __aenter__(self) -> "TelegramBridge":
        await self.connect()
        return self

    async def __aexit__(self, *_) -> None:
        await self.close()