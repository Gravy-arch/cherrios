from aiogram.fsm.state import State, StatesGroup


class SubscriptionFlow(StatesGroup):
    """
    States for the subscription / payment flow.

    CHOOSING_CURRENCY  – plan selected, bot waiting for currency choice
    AWAITING_PAYMENT   – payment address sent, waiting for user to verify
    """

    CHOOSING_CURRENCY = State()
    AWAITING_PAYMENT = State()