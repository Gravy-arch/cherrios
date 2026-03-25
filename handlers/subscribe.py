"""
handlers/subscribe.py

Fully self-contained subscription handler.
All keyboards for the subscription flow live here — no edits to inline.py needed.

Flow
----
  [💳 Subscribe] (welcome screen)
      ↓
  Plan selection  →  [⚡ One-Time $9]  |  [📅 Monthly $X]
      ↓
  Currency selection  →  [₿ BTC]  |  [💵 USDT TRC-20]
      ↓
  Payment address message + [✅ I've Paid — Verify]
      ↓
  NOWPayments status check → DB update → confirmation
"""

import logging
from datetime import timezone

from aiogram import Router
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

import settings
from services.database import Database
from services.nowpayments import NowPaymentsClient, PaymentStatus
from states.subscription import SubscriptionFlow

router = Router()
logger = logging.getLogger(__name__)

# Shared client instance (stateless — safe to reuse)
nowpayments = NowPaymentsClient()

ONE_TIME_PRICE_USD: float = 9.00


# ── Callback data factories ────────────────────────────────────────────────────

class PlanCallback(CallbackData, prefix="plan"):
    plan_type: str                     # "one_time" | "monthly"


class CurrencyCallback(CallbackData, prefix="curr"):
    plan_type: str
    currency: str                      # "btc" | "usdttrc20"


class VerifyCallback(CallbackData, prefix="vrfy"):
    payment_id: str


# ── Local keyboards (subscribe flow only) ─────────────────────────────────────

def _plans_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"⚡ One-Time Use — ${ONE_TIME_PRICE_USD:.0f}",
        callback_data=PlanCallback(plan_type="one_time").pack(),
    )
    builder.button(
        text=f"📅 Monthly — ${settings.MONTHLY_PRICE_USD:.0f}/mo",
        callback_data=PlanCallback(plan_type="monthly").pack(),
    )
    builder.button(text="⬅️ Back", callback_data="back_to_start")
    builder.adjust(1)
    return builder.as_markup()


def _currency_keyboard(plan_type: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="₿  Pay with Bitcoin (BTC)",
        callback_data=CurrencyCallback(plan_type=plan_type, currency="btc").pack(),
    )
    builder.button(
        text="💵  Pay with USDT (TRC-20)",
        callback_data=CurrencyCallback(plan_type=plan_type, currency="usdttrc20").pack(),
    )
    builder.button(text="⬅️ Back", callback_data="subscribe_menu")
    builder.adjust(1)
    return builder.as_markup()


def _payment_keyboard(payment_id: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅  I've Paid — Verify Payment",
        callback_data=VerifyCallback(payment_id=payment_id).pack(),
    )
    builder.button(text="❌  Cancel", callback_data="back_to_start")
    builder.adjust(1)
    return builder.as_markup()


def _verified_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🏠  Back to Start", callback_data="back_to_start")
    builder.adjust(1)
    return builder.as_markup()


# ── Message copy ───────────────────────────────────────────────────────────────

_SUBSCRIBE_MENU = (
    "💳 <b>Choose Your Plan</b>\n\n"

    "⚡ <b>One-Time Use</b>  —  <b>${one_time:.0f}</b>\n"
    "Verify attendance for a <u>single meeting</u>. Your access is reset "
    "automatically once your attendance has been confirmed.\n"
    "Perfect if you only need the bot occasionally.\n\n"

    "📅 <b>Monthly</b>  —  <b>${monthly:.0f}/month</b>\n"
    "Unlimited attendance verifications for <u>30 days</u> from activation. "
    "Ideal if you attend meetings regularly.\n\n"

    "Select a plan below to continue."
)

_CHOOSE_CURRENCY = (
    "💱 <b>Choose Payment Currency</b>\n\n"
    "You selected: {plan_label}\n\n"
    "How would you like to pay?"
)

_PAYMENT_DETAILS = (
    "📋 <b>Payment Details</b>\n\n"
    "Plan: <b>{plan_label}</b>\n"
    "Amount: <b>{amount:.8f} {currency_upper}</b>  (~${price_usd:.2f} USD)\n\n"
    "Send <b>exactly</b> the amount above to:\n\n"
    "<code>{address}</code>\n\n"
    "⚠️ <i>Send only {currency_upper} to this address. "
    "Sending any other coin will result in permanent loss of funds.</i>\n\n"
    "Once you've made the transfer, tap <b>Verify Payment</b> below.\n"
    "<i>Confirmations may take a few minutes.</i>"
)


def _plan_label(plan_type: str) -> str:
    return "One-Time Use" if plan_type == "one_time" else "Monthly"


# ── Handlers ───────────────────────────────────────────────────────────────────

@router.callback_query(lambda c: c.data == "subscribe_menu")
async def subscribe_menu(callback: CallbackQuery, state: FSMContext) -> None:
    """Entry point — show plan selection."""
    await state.clear()
    await callback.message.edit_text(
        _SUBSCRIBE_MENU.format(
            one_time=ONE_TIME_PRICE_USD,
            monthly=settings.MONTHLY_PRICE_USD,
        ),
        reply_markup=_plans_keyboard(),
    )
    await callback.answer()


@router.callback_query(PlanCallback.filter())
async def plan_selected(
    callback: CallbackQuery,
    callback_data: PlanCallback,
    state: FSMContext,
) -> None:
    """User picked a plan — ask which crypto they want to pay with."""
    plan_type = callback_data.plan_type
    await state.update_data(plan_type=plan_type)
    await state.set_state(SubscriptionFlow.CHOOSING_CURRENCY)

    await callback.message.edit_text(
        _CHOOSE_CURRENCY.format(plan_label=_plan_label(plan_type)),
        reply_markup=_currency_keyboard(plan_type),
    )
    await callback.answer()


@router.callback_query(CurrencyCallback.filter())
async def currency_selected(
    callback: CallbackQuery,
    callback_data: CurrencyCallback,
    state: FSMContext,
    db: Database,
) -> None:
    """
    User picked a currency.
    1. Upsert the user in the DB.
    2. Call NOWPayments to create a payment.
    3. Save the pending subscription to the DB.
    4. Show the payment address.
    """
    plan_type = callback_data.plan_type
    currency  = callback_data.currency
    user      = callback.from_user

    price_usd = (
        ONE_TIME_PRICE_USD
        if plan_type == "one_time"
        else float(settings.MONTHLY_PRICE_USD)
    )

    # Acknowledge quickly so Telegram doesn't show the loading spinner forever
    await callback.answer("Creating your payment address…")
    await callback.message.edit_text("⏳ Generating your payment address, please wait…")

    # Ensure the user exists in the DB before writing the subscription FK
    await db.upsert_user(
        telegram_id=user.id,
        username=user.username,
        first_name=user.first_name or user.username or str(user.id),
    )

    try:
        payment = await nowpayments.create_payment(
            price_usd=price_usd,
            pay_currency=currency,
            telegram_user_id=user.id,
            plan_type=plan_type,
        )
    except Exception as exc:
        logger.exception("NOWPayments create_payment error: %s", exc)
        await callback.message.edit_text(
            "❌ <b>Payment gateway error.</b>\n\n"
            "Could not generate a payment address right now. "
            "Please try again in a few minutes.",
            reply_markup=_plans_keyboard(),
        )
        await state.clear()
        return

    # Persist pending subscription
    await db.create_subscription(
        telegram_id=user.id,
        plan_type=plan_type,
        payment_id=payment.payment_id,
        pay_address=payment.pay_address,
        pay_amount=payment.pay_amount,
        pay_currency=payment.pay_currency,
        price_usd=price_usd,
    )

    # Store payment_id in FSM so the verify handler can retrieve it
    await state.update_data(payment_id=payment.payment_id)
    await state.set_state(SubscriptionFlow.AWAITING_PAYMENT)

    currency_upper = payment.pay_currency.upper()
    if currency_upper == "USDTTRC20":
        currency_upper = "USDT (TRC-20)"

    await callback.message.edit_text(
        _PAYMENT_DETAILS.format(
            plan_label=_plan_label(plan_type),
            amount=payment.pay_amount,
            currency_upper=currency_upper,
            price_usd=price_usd,
            address=payment.pay_address,
        ),
        reply_markup=_payment_keyboard(payment.payment_id),
    )


@router.callback_query(VerifyCallback.filter())
async def verify_payment(
    callback: CallbackQuery,
    callback_data: VerifyCallback,
    state: FSMContext,
    db: Database,
) -> None:
    """
    User clicked 'I've Paid — Verify'.
    Check NOWPayments for the payment status and update the DB accordingly.
    """
    payment_id = callback_data.payment_id

    await callback.answer("Checking your payment…")
    await callback.message.edit_text(
        "🔍 <b>Verifying your payment…</b>\n\n"
        "<i>This usually takes a few seconds.</i>"
    )

    try:
        info = await nowpayments.get_payment(payment_id)
    except Exception as exc:
        logger.exception("NOWPayments get_payment error: %s", exc)
        # Restore the payment message so they can try again
        sub = await db.get_subscription_by_payment(payment_id)
        await callback.message.edit_text(
            "❌ <b>Could not reach the payment gateway.</b>\n\n"
            "Please try verifying again in a moment.",
            reply_markup=_payment_keyboard(payment_id) if sub else _verified_keyboard(),
        )
        return

    # ── Successful payment ─────────────────────────────────────────────────────
    if info.status.is_successful:
        subscription = await db.activate_subscription(payment_id)

        if not subscription:
            logger.error("activate_subscription returned None for payment_id=%s", payment_id)
            await callback.message.edit_text(
                "⚠️ Payment confirmed but subscription record not found. "
                "Please contact support with your payment ID:\n"
                f"<code>{payment_id}</code>",
                reply_markup=_verified_keyboard(),
            )
            await state.clear()
            return

        await state.clear()

        if subscription.plan_type == "one_time":
            expiry_note = "Valid for <b>one attendance verification</b>."
        else:
            expiry = subscription.expires_at
            expiry_str = (
                expiry.strftime("%B %d, %Y")
                if expiry else "30 days from now"
            )
            expiry_note = f"Your subscription is active until <b>{expiry_str}</b>."

        await callback.message.edit_text(
            "🎉 <b>Payment Confirmed!</b>\n\n"
            f"Plan: <b>{_plan_label(subscription.plan_type)}</b>\n"
            f"{expiry_note}\n\n"
            "You can now use <b>Begin / Attend</b> to verify your meeting attendance.",
            reply_markup=_verified_keyboard(),
        )
        return

    # ── Still pending ──────────────────────────────────────────────────────────
    if info.status.is_pending:
        await callback.message.edit_text(
            "⏳ <b>Payment Not Yet Confirmed</b>\n\n"
            f"Current status: <code>{info.status.value}</code>\n\n"
            "Your transaction has been received but is still waiting for "
            "blockchain confirmations. This can take a few minutes.\n\n"
            "Tap <b>Verify Payment</b> again once you see it confirmed "
            "on your end.",
            reply_markup=_payment_keyboard(payment_id),
        )
        return

    # ── Failed / expired / refunded ────────────────────────────────────────────
    await state.clear()
    await callback.message.edit_text(
        "❌ <b>Payment Failed or Expired</b>\n\n"
        f"Status: <code>{info.status.value}</code>\n\n"
        "The payment was not completed. You can start a new subscription "
        "from the main menu.",
        reply_markup=_verified_keyboard(),
    )