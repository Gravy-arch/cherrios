"""
handlers/track.py

Fully self-contained meeting tracker handler.
All keyboards for the tracking flow live here.

Flow
────
  [📍 Track Meetings]  (welcome screen)
       ↓
  List of user's meetings as inline buttons  (name + status emoji)
       ↓  (click one)
  Meeting detail view: name, link, status, created date
       ↓
  [📸 Progress]  →  sends screenshots one by one as photo messages
                    (or tells user to check back if meeting is still pending)
  [⬅️ Back]     →  returns to meeting list
"""

import logging
from typing import Optional

from aiogram import Bot, Router
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, URLInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder

from services.database import Database, MeetingRecord

router = Router()
logger = logging.getLogger(__name__)

MAX_MEETINGS_SHOWN = 20     # cap the list so it doesn't overflow


# ── Callback data ──────────────────────────────────────────────────────────────

class MeetingDetailCallback(CallbackData, prefix="mtg"):
    meeting_id: str


class MeetingProgressCallback(CallbackData, prefix="mprog"):
    meeting_id: str


# ── Local keyboards ────────────────────────────────────────────────────────────

def _meetings_list_keyboard(meetings: list[MeetingRecord]) -> InlineKeyboardMarkup:
    """One button per meeting + a Back button."""
    builder = InlineKeyboardBuilder()
    for m in meetings:
        label = f"{m.status_emoji} {m.name}"
        builder.button(
            text=label,
            callback_data=MeetingDetailCallback(meeting_id=m.id).pack(),
        )
    builder.button(text="⬅️ Back", callback_data="back_to_start")
    builder.adjust(1)
    return builder.as_markup()


def _meeting_detail_keyboard(meeting_id: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="📸 Progress",
        callback_data=MeetingProgressCallback(meeting_id=meeting_id).pack(),
    )
    builder.button(text="⬅️ Back to Meetings", callback_data="track_menu")
    builder.adjust(1)
    return builder.as_markup()


def _back_to_meetings_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Back to Meetings", callback_data="track_menu")
    builder.adjust(1)
    return builder.as_markup()


# ── Message copy ───────────────────────────────────────────────────────────────

def _meeting_detail_text(m: MeetingRecord) -> str:
    status_label = {
        "pending":     "🕐 Pending — waiting for Playwright to start",
        "in_progress": "🔄 In Progress — meeting is being attended",
        "completed":   "✅ Completed — all screenshots saved",
    }.get(m.status, f"❓ {m.status}")

    created = m.created_at.strftime("%b %d, %Y %H:%M UTC")
    completed = (
        m.completed_at.strftime("%b %d, %Y %H:%M UTC")
        if m.completed_at else "—"
    )

    return (
        f"📋 <b>{m.name}</b>\n\n"
        f"🔗 <b>Link:</b> <code>{m.link}</code>\n"
        f"📊 <b>Status:</b> {status_label}\n"
        f"📅 <b>Started:</b> {created}\n"
        f"🏁 <b>Completed:</b> {completed}\n\n"
        f"<i>Meeting ID (for Playwright): <code>{m.id}</code></i>"
    )


# ── Handlers ───────────────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data == "track_menu")
async def track_menu(
    callback: CallbackQuery,
    db: Database,
) -> None:
    """Show the list of all meetings belonging to this user."""
    meetings = await db.get_meetings_for_user(callback.from_user.id)

    if not meetings:
        await callback.message.edit_text(
            "📭 <b>No meetings yet.</b>\n\n"
            "Complete an attendance flow using <b>Begin / Attend</b> and "
            "your meetings will appear here.",
            reply_markup=_back_to_meetings_keyboard(),
        )
        await callback.answer()
        return

    capped = meetings[:MAX_MEETINGS_SHOWN]
    footer = (
        f"\n<i>Showing {MAX_MEETINGS_SHOWN} most recent meetings.</i>"
        if len(meetings) > MAX_MEETINGS_SHOWN else ""
    )

    await callback.message.edit_text(
        f"📍 <b>Your Meetings</b>\n\n"
        f"Tap a meeting to see its details and screenshots.{footer}",
        reply_markup=_meetings_list_keyboard(capped),
    )
    await callback.answer()


@router.callback_query(MeetingDetailCallback.filter())
async def meeting_detail(
    callback: CallbackQuery,
    callback_data: MeetingDetailCallback,
    db: Database,
) -> None:
    """Show detail view for a single meeting."""
    meeting = await db.get_meeting_by_id(callback_data.meeting_id)

    if not meeting:
        await callback.answer("Meeting not found.", show_alert=True)
        return

    await callback.message.edit_text(
        _meeting_detail_text(meeting),
        reply_markup=_meeting_detail_keyboard(meeting.id),
    )
    await callback.answer()


@router.callback_query(MeetingProgressCallback.filter())
async def meeting_progress(
    callback: CallbackQuery,
    callback_data: MeetingProgressCallback,
    db: Database,
    bot: Bot,
) -> None:
    """
    Fetch screenshots for this meeting and send them as photo messages.

    Screenshot URLs come from the `screenshots` table, where Playwright
    stores them after uploading to Supabase Storage.

    Storage path convention (Playwright must follow this):
        screenshots/{meeting_id}/{unix_timestamp}.png

    Playwright inserts a row into `screenshots` for each file:
        INSERT INTO screenshots (meeting_id, storage_url) VALUES ($1, $2)
    """
    meeting = await db.get_meeting_by_id(callback_data.meeting_id)
    if not meeting:
        await callback.answer("Meeting not found.", show_alert=True)
        return

    await callback.answer()

    # ── Meeting not yet started ────────────────────────────────────────────────
    if meeting.status == "pending":
        await callback.message.edit_text(
            f"🕐 <b>{meeting.name}</b> hasn't started yet.\n\n"
            "Playwright hasn't begun attending this meeting. "
            "Check back later once the session is underway.",
            reply_markup=_meeting_detail_keyboard(meeting.id),
        )
        return

    # ── Fetch screenshots ──────────────────────────────────────────────────────
    screenshots = await db.get_screenshots_for_meeting(meeting.id)

    if not screenshots:
        status_hint = (
            "The meeting is still in progress — screenshots will appear "
            "here as Playwright captures them. Check back shortly."
            if meeting.status == "in_progress"
            else "No screenshots were saved for this meeting."
        )
        await callback.message.edit_text(
            f"📸 <b>No screenshots yet</b>\n\n{status_hint}",
            reply_markup=_meeting_detail_keyboard(meeting.id),
        )
        return

    # ── Send screenshots ───────────────────────────────────────────────────────
    # Edit the current message to show a summary header first
    in_progress_note = (
        "\n<i>⚠️ Meeting still in progress — more screenshots may arrive.</i>"
        if meeting.status == "in_progress" else ""
    )
    await callback.message.edit_text(
        f"📸 <b>{meeting.name} — {len(screenshots)} screenshot(s)</b>"
        f"{in_progress_note}\n\n"
        "<i>Sending photos below…</i>",
        reply_markup=_back_to_meetings_keyboard(),
    )

    # Send each screenshot as a separate photo message
    failed = 0
    for i, shot in enumerate(screenshots, start=1):
        taken = shot.taken_at.strftime("%H:%M:%S UTC")
        try:
            await bot.send_photo(
                chat_id=callback.from_user.id,
                photo=URLInputFile(shot.storage_url, filename=f"screenshot_{i}.png"),
                caption=f"📸 Screenshot {i}/{len(screenshots)}  •  {taken}",
            )
        except Exception as exc:
            logger.warning("Failed to send screenshot %s: %s", shot.storage_url, exc)
            failed += 1

    # Summary footer
    if failed:
        await bot.send_message(
            chat_id=callback.from_user.id,
            text=(
                f"⚠️ {failed} screenshot(s) could not be loaded "
                "(the file may have been removed from storage)."
            ),
        )
