import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

from aiogram import Bot, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

import settings
from keyboards.inline import done_keyboard, retry_video_keyboard
from services.video_processor import process_video
from states.attendance import AttendanceFlow

logger = logging.getLogger(__name__)
router = Router()

# Telegram video duration tolerance (seconds).
# We allow a ±3 s window around the 10-second target.
MIN_DURATION = 7
MAX_DURATION = 13


# ── Retry shortcut ─────────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data == "retry_video")
async def retry_video(callback: CallbackQuery, state: FSMContext) -> None:
    """Let the user upload a different video without restarting the whole flow."""
    await state.set_state(AttendanceFlow.WAITING_FOR_VIDEO)
    await callback.message.edit_text(
        "🎥 Please upload your <b>10-second focus video</b> again.",
        reply_markup=None,
    )
    await callback.answer()


# ── Receive the video ──────────────────────────────────────────────────────────

@router.message(AttendanceFlow.WAITING_FOR_VIDEO)
async def receive_video(message: Message, state: FSMContext, bot: Bot, db=None) -> None:
    """
    Accept the video, run basic duration checks, then hand off to the
    conversion service.
    """
    # ── 1. Make sure the user actually sent a video ────────────────────────────
    video = message.video or message.document

    if not video:
        await message.answer(
            "⚠️ Please send a <b>video file</b>, not a photo or document.",
            reply_markup=retry_video_keyboard(),
        )
        return

    # If it came as a document, reject non-video MIME types
    if message.document and not (
        message.document.mime_type or ""
    ).startswith("video/"):
        await message.answer(
            "⚠️ The file you sent doesn't appear to be a video.\n"
            "Please send an actual video clip.",
            reply_markup=retry_video_keyboard(),
        )
        return

    # ── 2. Duration check ──────────────────────────────────────────────────────
    duration: int = getattr(video, "duration", 0) or 0
    if duration and not (MIN_DURATION <= duration <= MAX_DURATION):
        await message.answer(
            f"⏱ <b>Video too {'short' if duration < MIN_DURATION else 'long'}.</b>\n\n"
            f"We need a <b>~10-second</b> clip "
            f"(between {MIN_DURATION}s and {MAX_DURATION}s).\n"
            f"Your video is <b>{duration}s</b>.\n\n"
            "Please record again and try once more.",
            reply_markup=retry_video_keyboard(),
        )
        return

    # ── 3. Acknowledge receipt and move to processing state ────────────────────
    await state.set_state(AttendanceFlow.PROCESSING_VIDEO)
    processing_msg = await message.answer(
        "⏳ <b>Video received!</b>\nConverting to Y4M format, please wait…"
    )

    # ── 4. Download the file ───────────────────────────────────────────────────
    file_id = video.file_id
    file = await bot.get_file(file_id)

    # Use a temp dir so we always clean up
    with tempfile.TemporaryDirectory() as tmpdir:
        raw_ext = Path(file.file_path or "video.mp4").suffix or ".mp4"
        raw_path = os.path.join(tmpdir, f"input{raw_ext}")

        await bot.download_file(file.file_path, destination=raw_path)
        logger.info("Downloaded video → %s (%d bytes)", raw_path, os.path.getsize(raw_path))

        # ── 5. Convert using the pre-defined function ──────────────────────────
        try:
            y4m_path = await process_video(raw_path, settings.MEDIA_DIR)
        except Exception as exc:
            logger.exception("Video conversion failed: %s", exc)
            await processing_msg.edit_text(
                "❌ <b>Conversion failed.</b>\n\n"
                "There was a problem processing your video. "
                "Please try uploading it again.",
                reply_markup=retry_video_keyboard(),
            )
            await state.set_state(AttendanceFlow.WAITING_FOR_VIDEO)
            return

    # ── 6. Retrieve stored state data ──────────────────────────────────────────
    data = await state.get_data()
    meeting_url  = data.get("meeting_url", "N/A")
    meeting_name = data.get("meeting_name", "Unnamed Meeting")

    # ── 7. Save meeting record to PostgreSQL ───────────────────────────────────
    meeting_id: Optional[str] = None
    try:
        if db:
            await db.upsert_user(
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name or str(message.from_user.id),
            )
            meeting_id = await db.create_meeting(
                telegram_id=message.from_user.id,
                name=meeting_name,
                link=meeting_url,
            )
    except Exception as exc:
        logger.exception("Failed to save meeting to DB: %s", exc)
        # Non-fatal — attendance still recorded locally

    # ── 8. All done ────────────────────────────────────────────────────────────
    await state.clear()
    await processing_msg.edit_text(
        "✅ <b>Attendance recorded successfully!</b>\n\n"
        f"🏷 <b>Meeting:</b> {meeting_name}\n"
        f"🔗 <b>Link:</b> <code>{meeting_url}</code>\n"
        f"🎬 <b>Video saved as:</b> <code>{Path(y4m_path).name}</code>\n\n"
        "Your attendance has been submitted. See you at the meeting! 🎉\n"
        "<i>You can track this meeting's progress from the main menu.</i>",
        reply_markup=done_keyboard(),
    )


# ── Guard: catch non-video messages in the wrong state ────────────────────────

@router.message(AttendanceFlow.PROCESSING_VIDEO)
async def already_processing(message: Message) -> None:
    """Politely ignore messages sent while conversion is running."""
    await message.answer(
        "⏳ Still processing your video… please hang tight!"
    )
