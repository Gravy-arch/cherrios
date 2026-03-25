from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from keyboards.inline import about_keyboard, welcome_keyboard

router = Router()

# ── Message copy ───────────────────────────────────────────────────────────────

WELCOME_TEXT = (
    "👋 <b>Hello! Welcome to the Attendance Bot.</b>\n\n"
    "This bot lets you confirm your presence at an online meeting in two "
    "quick steps:\n\n"
    "  <b>1.</b> 🔗 Paste your meeting link\n"
    "  <b>2.</b> 🎥 Upload a short 10-second focus video\n\n"
    "That's it — we take care of the rest.\n\n"
    "Tap <b>Begin / Attend</b> when you're ready, or read more about how "
    "this works in <b>About</b>."
)

ABOUT_TEXT = (
    "ℹ️ <b>About This Bot</b>\n\n"
    "<b>What does it do?</b>\n"
    "The Attendance Bot verifies that you are present and engaged at your "
    "online meeting. It collects a meeting link and a short video of you, "
    "then converts the video into a standardised Y4M format for further "
    "processing by our attendance system.\n\n"
    "<b>How it works</b>\n"
    "  <b>1.</b> You tap <i>Begin / Attend</i>.\n"
    "  <b>2.</b> You paste the URL of your meeting (Google Meet, Zoom, Teams, "
    "etc.).\n"
    "  <b>3.</b> You record and upload a <b>~10-second video</b> of yourself, "
    "clearly facing the camera in good lighting.\n"
    "  <b>4.</b> The bot validates and converts the video automatically — "
    "you'll get a confirmation once it's done.\n\n"
    "<b>Privacy</b>\n"
    "Your video is processed solely to verify attendance and is not shared "
    "with any third party.\n\n"
    "<b>Need help?</b>\n"
    "If you run into any issues, contact your meeting organiser or system "
    "administrator."
)


# ── Handlers ───────────────────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    """Handle /start — clear any previous state and show the welcome screen."""
    await state.clear()
    await message.answer(WELCOME_TEXT, reply_markup=welcome_keyboard())


@router.callback_query(lambda c: c.data == "back_to_start")
async def back_to_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Return to the welcome screen from anywhere in the flow."""
    await state.clear()
    await callback.message.edit_text(WELCOME_TEXT, reply_markup=welcome_keyboard())
    await callback.answer()


@router.callback_query(lambda c: c.data == "show_about")
async def show_about(callback: CallbackQuery) -> None:
    """Show the About screen when the user taps the ℹ️ About button."""
    await callback.message.edit_text(ABOUT_TEXT, reply_markup=about_keyboard())
    await callback.answer()