from aiogram.fsm.state import StatesGroup, State

class AdminMailingState(StatesGroup):
    waiting_message_to_mailing = State()
