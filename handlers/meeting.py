from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from keyboards.inline import cancel_keyboard, retry_link_keyboard, welcome_keyboard
from states.attendance import AttendanceFlow
from utils.validators import is_valid_meeting_url, normalise_url

router = Router()

# ── Message copy ───────────────────────────────────────────────────────────────

ASK_NAME_TEXT = (
    "🏷 <b>Step 1 of 3 — Meeting Name</b>\n\n"
    "Give this meeting a short name so you can track it later.\n\n"
    "<i>Examples: Daily Standup, Client Demo, Sprint Review</i>\n\n"
    "This name will appear in your <b>Track</b> list."
)

NAME_TOO_SHORT_TEXT = (
    "⚠️ Name is too short. Please use at least 2 characters."
)

NAME_TOO_LONG_TEXT = (
    "⚠️ Name is too long. Please keep it under 100 characters."
)

ASK_LINK_TEXT = (
    "🔗 <b>Step 2 of 3 — Meeting Link</b>\n\n"
    "Please paste your meeting link below.\n"
    "<i>Example: https://meet.google.com/abc-xyz-def</i>"
)

INVALID_LINK_TEXT = (
    "⚠️ <b>Invalid URL</b>\n\n"
    "That doesn't look like a valid meeting link.\n"
    "Please make sure it starts with <code>http://</code> or "
    "<code>https://</code> and has a proper domain.\n\n"
    "Would you like to try again?"
)


# ── Entry point ────────────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data == "begin_attendance")
async def begin_attendance(callback: CallbackQuery, state: FSMContext) -> None:
    """User clicked 'Begin / Attend' — first ask for a meeting name."""
    await state.set_state(AttendanceFlow.WAITING_FOR_NAME)
    await callback.message.edit_text(ASK_NAME_TEXT, reply_markup=cancel_keyboard())
    await callback.answer()


# ── Receive meeting name ───────────────────────────────────────────────────────

@router.message(AttendanceFlow.WAITING_FOR_NAME)
async def receive_meeting_name(message: Message, state: FSMContext) -> None:
    """Validate the name and advance to the link step."""
    name = (message.text or "").strip()

    if len(name) < 2:
        await message.answer(NAME_TOO_SHORT_TEXT, reply_markup=cancel_keyboard())
        return

    if len(name) > 100:
        await message.answer(NAME_TOO_LONG_TEXT, reply_markup=cancel_keyboard())
        return

    await state.update_data(meeting_name=name)
    await state.set_state(AttendanceFlow.WAITING_FOR_LINK)

    await message.answer(
        f"✅ <b>Meeting name set:</b> <i>{name}</i>\n\n" + ASK_LINK_TEXT,
        reply_markup=cancel_keyboard(),
    )


# ── Retry link shortcut ────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data == "retry_link")
async def retry_link(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AttendanceFlow.WAITING_FOR_LINK)
    await callback.message.edit_text(ASK_LINK_TEXT, reply_markup=cancel_keyboard())
    await callback.answer()


# ── Receive & validate the link ────────────────────────────────────────────────

@router.message(AttendanceFlow.WAITING_FOR_LINK)
async def receive_meeting_link(message: Message, state: FSMContext) -> None:
    """Validate the pasted URL and advance the flow or ask to retry."""
    user_input = (message.text or "").strip()

    if not is_valid_meeting_url(user_input):
        await message.answer(INVALID_LINK_TEXT, reply_markup=retry_link_keyboard())
        return

    clean_url = normalise_url(user_input)
    await state.update_data(meeting_url=clean_url)
    await state.set_state(AttendanceFlow.WAITING_FOR_VIDEO)

    await message.answer(
        f"✅ <b>Link accepted!</b>\n"
        f"<code>{clean_url}</code>\n\n"
        "🎥 <b>Step 3 of 3 — Focus Video</b>\n\n"
        "Please upload a <b>10-second video</b> of yourself, clearly visible "
        "and focused on the camera.\n\n"
        "<i>Tip: Record in good lighting for best results.</i>",
        reply_markup=cancel_keyboard(),
    )


# ── Cancel ─────────────────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data == "cancel_flow")
async def cancel_flow(callback: CallbackQuery, state: FSMContext) -> None:
    """Abort the flow and return the user to the welcome screen."""
    await state.clear()
    await callback.message.edit_text(
        "❌ <b>Cancelled.</b>\n\nNo worries! Press <b>Begin / Attend</b> whenever you're ready.",
        reply_markup=welcome_keyboard(),
    )
    await callback.answer("Flow cancelled.")
