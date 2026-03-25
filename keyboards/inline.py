from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


# ── Welcome screen ────────────────────────────────────────────────────────────

def welcome_keyboard() -> InlineKeyboardMarkup:
    """Main keyboard shown with the /start message."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Begin / Attend", callback_data="begin_attendance")
    builder.button(text="📍 Track Meetings", callback_data="track_menu")
    builder.button(text="💳 Subscribe", callback_data="subscribe_menu")
    builder.button(text="ℹ️ About", callback_data="show_about")
    builder.adjust(1)
    return builder.as_markup()


def about_keyboard() -> InlineKeyboardMarkup:
    """Shown on the About screen — single back button."""
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Back", callback_data="back_to_start")
    builder.adjust(1)
    return builder.as_markup()


# ── Cancel / back ─────────────────────────────────────────────────────────────

def cancel_keyboard() -> InlineKeyboardMarkup:
    """Shown at every step so the user can abort."""
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Cancel", callback_data="cancel_flow")
    builder.adjust(1)
    return builder.as_markup()


# ── Retry helpers ─────────────────────────────────────────────────────────────

def retry_link_keyboard() -> InlineKeyboardMarkup:
    """Shown when the URL validation fails."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Try Again", callback_data="retry_link")
    builder.button(text="❌ Cancel", callback_data="cancel_flow")
    builder.adjust(1)
    return builder.as_markup()


def retry_video_keyboard() -> InlineKeyboardMarkup:
    """Shown when the uploaded file is not an accepted video."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Try Again", callback_data="retry_video")
    builder.button(text="❌ Cancel", callback_data="cancel_flow")
    builder.adjust(1)
    return builder.as_markup()


# ── Done screen ───────────────────────────────────────────────────────────────

def done_keyboard() -> InlineKeyboardMarkup:
    """Shown after successful processing."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🏠 Back to Start", callback_data="back_to_start")
    builder.adjust(1)
    return builder.as_markup()
