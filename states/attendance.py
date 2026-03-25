from aiogram.fsm.state import State, StatesGroup


class AttendanceFlow(StatesGroup):
    """
    States for the full attendance / meeting flow.

    WAITING_FOR_NAME   – bot has asked the user to give this meeting a name
    WAITING_FOR_LINK   – bot has asked the user to paste a meeting URL
    WAITING_FOR_VIDEO  – URL validated; bot is waiting for the 10-second video
    PROCESSING_VIDEO   – video received and is being converted / processed
    """

    WAITING_FOR_NAME = State()
    WAITING_FOR_LINK = State()
    WAITING_FOR_VIDEO = State()
    PROCESSING_VIDEO = State()
