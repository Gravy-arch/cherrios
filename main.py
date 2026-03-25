import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder

import settings
from handlers import start, meeting, video, subscribe, track, playwright_input
from services.database import Database
from states.playwright_input import PlaywrightInputState

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

PLAYWRIGHT_POLL_INTERVAL: float = 2.0


async def playwright_request_poller(
    bot: Bot,
    db: Database,
    storage: RedisStorage,
) -> None:
    """
    Background task — runs for the lifetime of the bot.

    Every PLAYWRIGHT_POLL_INTERVAL seconds it checks for playwright_requests
    rows with status='pending' and for each one:

      1. Sends the question to the Telegram user as a message with a
         Cancel button.
      2. Sets the user's FSM state to PlaywrightInputState.WAITING_FOR_INPUT
         and stores {request_id, question, session_id} in FSM data.
      3. Marks the DB row as 'sent'.

    The user's reply is then caught by the FSM handler in
    handlers/playwright_input.py — not a generic catch-all — so it's
    scoped exactly to that open question.
    """
    logger.info("Playwright request poller started.")

    # Build the cancel keyboard once — same for every question
    cancel_builder = InlineKeyboardBuilder()
    cancel_builder.button(text="❌ Cancel Session", callback_data="cancel_playwright_input")
    cancel_kb = cancel_builder.as_markup()

    while True:
        try:
            pending = await db.get_pending_playwright_requests()
            for req in pending:
                try:
                    # 1. Send question to user
                    await bot.send_message(
                        chat_id=req.telegram_id,
                        text=(
                            "🤖 <b>Your session needs input:</b>\n\n"
                            f"<i>{req.question}</i>\n\n"
                            "Please type your reply and send it here.\n"
                            "<b>Your reply will be passed directly to the session.</b>"
                        ),
                        parse_mode="HTML",
                        reply_markup=cancel_kb,
                    )

                    # 2. Set FSM state for this user so their next message
                    #    is routed to the PlaywrightInputState handler
                    key = StorageKey(
                        bot_id=bot.id,
                        chat_id=req.telegram_id,
                        user_id=req.telegram_id,
                    )
                    fsm = FSMContext(storage=storage, key=key)
                    await fsm.set_state(PlaywrightInputState.WAITING_FOR_INPUT)
                    await fsm.update_data(
                        request_id=req.id,
                        question=req.question,
                        session_id=req.session_id,
                    )

                    # 3. Mark sent so we don't dispatch it again
                    await db.mark_playwright_request_sent(req.id)

                    logger.info(
                        "Forwarded playwright_request %s to user %d, FSM state set.",
                        req.id, req.telegram_id,
                    )

                except Exception as exc:
                    logger.exception(
                        "Failed to forward request %s: %s", req.id, exc
                    )

        except Exception as exc:
            logger.exception("Playwright poller error: %s", exc)

        await asyncio.sleep(PLAYWRIGHT_POLL_INTERVAL)


async def main() -> None:
    storage = RedisStorage.from_url(settings.REDIS_URL)

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dp = Dispatcher(storage=storage)

    # ── Database ───────────────────────────────────────────────────────────────
    db = Database()
    await db.connect()
    dp.workflow_data["db"] = db

    # ── Routers ────────────────────────────────────────────────────────────────
    # playwright_input registered before the bare catch-all would have been,
    # but after all specific flows — FSM filter makes it safe at any position.
    dp.include_router(start.router)
    dp.include_router(meeting.router)
    dp.include_router(video.router)
    dp.include_router(subscribe.router)
    dp.include_router(track.router)
    dp.include_router(playwright_input.router)

    logger.info("Bot is starting…")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        asyncio.create_task(playwright_request_poller(bot, db, storage))
        await dp.start_polling(bot)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())


if __name__ == "__main__":
    asyncio.run(main())