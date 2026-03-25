"""
handlers/playwright_input.py

Handles user replies to questions Playwright has asked via the bot.

Full flow per question
──────────────────────
  Playwright:  await bridge.ask_user("Enter your student ID:")
                   ↓  inserts playwright_requests row (status: pending)

  Poller (main.py):
                   ↓  sends question to user
                   ↓  FSM → WAITING_FOR_INPUT  {request_id, question, session_id}
                   ↓  marks row 'sent'

  User types reply:
                   ↓  receive_playwright_answer() catches it
                   ↓  FSM → CONFIRMING_INPUT  {+ draft_answer}
                   ↓  bot shows draft + [✅ Confirm] [✏️ Re-enter] [❌ Cancel]

  User taps Confirm:
                   ↓  confirm_playwright_answer() writes answer to DB
                   ↓  FSM cleared
                   ↓  Playwright's ask_user() returns the answer string

  User taps Re-enter:
                   ↓  FSM → WAITING_FOR_INPUT (draft cleared, question re-shown)
                   ↓  user types again from scratch

  User taps Cancel:
                   ↓  DB row marked 'timed_out'
                   ↓  FSM cleared
                   ↓  Playwright raises TimeoutError and stops
"""

import logging

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from services.database import Database
from states.playwright_input import PlaywrightInputState

router = Router()
logger = logging.getLogger(__name__)


# ── Keyboards ──────────────────────────────────────────────────────────────────

def _waiting_keyboard() -> InlineKeyboardMarkup:
    """Shown with every Playwright question so the user can cancel."""
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Cancel Session", callback_data="pwt_cancel")
    builder.adjust(1)
    return builder.as_markup()


def _confirmation_keyboard() -> InlineKeyboardMarkup:
    """Shown after the user types a reply — Confirm, Re-enter, or Cancel."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Confirm",    callback_data="pwt_confirm")
    builder.button(text="✏️ Re-enter",  callback_data="pwt_reenter")
    builder.button(text="❌ Cancel",    callback_data="pwt_cancel")
    builder.adjust(2, 1)   # Confirm + Re-enter on row 1, Cancel on row 2
    return builder.as_markup()


def _answered_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🏠 Back to Start", callback_data="back_to_start")
    builder.adjust(1)
    return builder.as_markup()


# ── Helper ─────────────────────────────────────────────────────────────────────

def _question_prompt(question: str) -> str:
    return (
        "🤖 <b>Your session needs input:</b>\n\n"
        f"<i>{question}</i>\n\n"
        "Please type your reply and send it here."
    )


# ── Step 1: user types their reply → move to confirmation ─────────────────────

@router.message(PlaywrightInputState.WAITING_FOR_INPUT)
async def receive_playwright_answer(
    message: Message,
    state: FSMContext,
) -> None:
    """
    User typed something while WAITING_FOR_INPUT.
    Store it as a draft and ask them to confirm before committing.
    """
    draft = (message.text or "").strip()
    if not draft:
        await message.answer(
            "⚠️ Please send a text reply.",
            reply_markup=_waiting_keyboard(),
        )
        return

    data = await state.get_data()
    question: str = data["question"]

    # Store draft and advance to confirmation state
    await state.update_data(draft_answer=draft)
    await state.set_state(PlaywrightInputState.CONFIRMING_INPUT)

    await message.answer(
        f"📝 <b>Please confirm your reply:</b>\n\n"
        f"<b>Question:</b> <i>{question}</i>\n"
        f"<b>Your answer:</b> <code>{draft}</code>\n\n"
        "Is this correct?",
        reply_markup=_confirmation_keyboard(),
    )


# ── Step 2a: user confirms → write to DB ──────────────────────────────────────

@router.callback_query(
    lambda c: c.data == "pwt_confirm",
    PlaywrightInputState.CONFIRMING_INPUT,
)
async def confirm_playwright_answer(
    callback: CallbackQuery,
    state: FSMContext,
    db: Database,
) -> None:
    """User confirmed their draft — write the answer to the DB."""
    data = await state.get_data()
    request_id: str  = data["request_id"]
    question: str    = data["question"]
    draft_answer: str = data["draft_answer"]

    updated = await db.answer_playwright_request(
        request_id=request_id,
        answer=draft_answer,
    )

    if not updated:
        await state.clear()
        await callback.message.edit_text(
            "⚠️ The session that asked this question is no longer active.\n"
            "Your reply was not recorded.",
            reply_markup=_answered_keyboard(),
        )
        await callback.answer()
        return

    await state.clear()

    logger.info(
        "Playwright request %s confirmed by user %d: %r",
        request_id, callback.from_user.id, draft_answer,
    )

    await callback.message.edit_text(
        "✅ <b>Reply confirmed and sent!</b>\n\n"
        f"<b>Question:</b> <i>{question}</i>\n"
        f"<b>Answer:</b> <code>{draft_answer}</code>\n\n"
        "The session will continue automatically. "
        "You'll be notified if another input is needed.",
    )
    await callback.answer("Confirmed ✅")


# ── Step 2b: user wants to re-enter → back to WAITING_FOR_INPUT ───────────────

@router.callback_query(
    lambda c: c.data == "pwt_reenter",
    PlaywrightInputState.CONFIRMING_INPUT,
)
async def reenter_playwright_answer(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """User tapped Re-enter — wipe the draft and let them type again."""
    data = await state.get_data()
    question: str = data["question"]

    # Clear the draft but keep request_id, question, session_id
    await state.update_data(draft_answer=None)
    await state.set_state(PlaywrightInputState.WAITING_FOR_INPUT)

    await callback.message.edit_text(
        f"✏️ <b>Let's try again.</b>\n\n"
        + _question_prompt(question),
        reply_markup=_waiting_keyboard(),
    )
    await callback.answer()


# ── Cancel — works from both states ───────────────────────────────────────────

@router.callback_query(
    lambda c: c.data == "pwt_cancel",
    PlaywrightInputState.WAITING_FOR_INPUT,
)
@router.callback_query(
    lambda c: c.data == "pwt_cancel",
    PlaywrightInputState.CONFIRMING_INPUT,
)
async def cancel_playwright_input(
    callback: CallbackQuery,
    state: FSMContext,
    db: Database,
) -> None:
    """
    User cancelled — mark the request timed_out so Playwright raises
    TimeoutError and can shut down the session gracefully.
    """
    data = await state.get_data()
    request_id: str = data.get("request_id", "")
    question: str   = data.get("question", "")

    if request_id:
        await db.pool.execute(
            "UPDATE playwright_requests SET status = 'timed_out' WHERE id = $1",
            request_id,
        )
        logger.info(
            "Playwright request %s cancelled by user %d",
            request_id, callback.from_user.id,
        )

    await state.clear()
    await callback.message.edit_text(
        "❌ <b>Session input cancelled.</b>\n\n"
        f"The pending question was:\n<i>{question}</i>\n\n"
        "The automated session has been notified and will stop.",
        reply_markup=_answered_keyboard(),
    )
    await callback.answer()