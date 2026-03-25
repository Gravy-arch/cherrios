"""
services/nowpayments.py

Async wrapper around the NOWPayments REST API.
Docs: https://documenter.getpostman.com/view/7907941/2s93JqTRWN
"""

import logging
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import aiohttp

import settings

logger = logging.getLogger(__name__)

NOWPAYMENTS_BASE = "https://api.nowpayments.io/v1"


# ── Payment status ─────────────────────────────────────────────────────────────

class PaymentStatus(str, Enum):
    WAITING       = "waiting"
    CONFIRMING    = "confirming"
    CONFIRMED     = "confirmed"
    SENDING       = "sending"
    PARTIALLY_PAID = "partially_paid"
    FINISHED      = "finished"
    FAILED        = "failed"
    REFUNDED      = "refunded"
    EXPIRED       = "expired"

    @property
    def is_successful(self) -> bool:
        return self in {PaymentStatus.CONFIRMED, PaymentStatus.FINISHED}

    @property
    def is_pending(self) -> bool:
        return self in {
            PaymentStatus.WAITING,
            PaymentStatus.CONFIRMING,
            PaymentStatus.SENDING,
        }

    @property
    def is_failed(self) -> bool:
        return self in {
            PaymentStatus.FAILED,
            PaymentStatus.EXPIRED,
            PaymentStatus.REFUNDED,
        }


# ── Response models ────────────────────────────────────────────────────────────

@dataclass
class CreatedPayment:
    payment_id: str
    pay_address: str
    pay_amount: float
    pay_currency: str
    price_amount: float
    price_currency: str
    order_id: str
    status: str


@dataclass
class PaymentInfo:
    payment_id: str
    status: PaymentStatus
    pay_address: str
    pay_amount: float
    actually_paid: float
    pay_currency: str
    order_id: str


# ── Client ─────────────────────────────────────────────────────────────────────

class NowPaymentsClient:
    """Async NOWPayments client. One instance shared across the app."""

    def __init__(self) -> None:
        self._api_key = settings.NOWPAYMENTS_API_KEY
        self._headers = {
            "x-api-key": self._api_key,
            "Content-Type": "application/json",
        }

    async def create_payment(
        self,
        price_usd: float,
        pay_currency: str,
        telegram_user_id: int,
        plan_type: str,
    ) -> CreatedPayment:
        """
        Create a new crypto payment.

        Parameters
        ----------
        price_usd       : amount to charge in USD
        pay_currency    : crypto ticker, e.g. "btc" or "usdttrc20"
        telegram_user_id: used to build a unique order_id
        plan_type       : "one_time" or "monthly" (stored in order description)
        """
        order_id = f"{telegram_user_id}-{plan_type}-{uuid.uuid4().hex[:8]}"

        payload = {
            "price_amount": price_usd,
            "price_currency": "usd",
            "pay_currency": pay_currency,
            "order_id": order_id,
            "order_description": f"Attendance Bot — {plan_type.replace('_', ' ').title()} Plan",
            "is_fixed_rate": False,
            "is_fee_paid_by_user": False,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{NOWPAYMENTS_BASE}/payment",
                json=payload,
                headers=self._headers,
            ) as resp:
                if resp.status != 201:
                    body = await resp.text()
                    raise RuntimeError(
                        f"NOWPayments create_payment failed [{resp.status}]: {body}"
                    )
                data = await resp.json()

        logger.info(
            "Payment created: id=%s currency=%s address=%s",
            data["payment_id"], pay_currency, data["pay_address"],
        )

        return CreatedPayment(
            payment_id=str(data["payment_id"]),
            pay_address=data["pay_address"],
            pay_amount=float(data["pay_amount"]),
            pay_currency=data["pay_currency"],
            price_amount=float(data["price_amount"]),
            price_currency=data["price_currency"],
            order_id=data["order_id"],
            status=data["payment_status"],
        )

    async def get_payment(self, payment_id: str) -> PaymentInfo:
        """Fetch the current status of a payment by its ID."""
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{NOWPAYMENTS_BASE}/payment/{payment_id}",
                headers=self._headers,
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    raise RuntimeError(
                        f"NOWPayments get_payment failed [{resp.status}]: {body}"
                    )
                data = await resp.json()

        return PaymentInfo(
            payment_id=str(data["payment_id"]),
            status=PaymentStatus(data["payment_status"]),
            pay_address=data["pay_address"],
            pay_amount=float(data["pay_amount"]),
            actually_paid=float(data.get("actually_paid", 0)),
            pay_currency=data["pay_currency"],
            order_id=data["order_id"],
        )