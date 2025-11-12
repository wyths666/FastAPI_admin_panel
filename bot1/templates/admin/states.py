from aiogram.fsm.state import StatesGroup, State

class AdminMailingState(StatesGroup):
    waiting_message_to_mailing = State()

class ProductStates(StatesGroup):
    waiting_product_name = State()
    waiting_product_description = State()
    waiting_product_image = State()
    waiting_edit_product_choice = State()
    waiting_edit_name = State()
    waiting_edit_description = State()
    waiting_edit_image = State()