from aiogram.fsm.state import State, StatesGroup


class PlaywrightInputState(StatesGroup):
    """
    FSM states for Playwright-driven user input via the bot.

    WAITING_FOR_INPUT   – question sent to user, waiting for them to type
    CONFIRMING_INPUT    – user typed a reply, waiting for Confirm or Re-enter
    """

    WAITING_FOR_INPUT  = State()
    CONFIRMING_INPUT   = State()