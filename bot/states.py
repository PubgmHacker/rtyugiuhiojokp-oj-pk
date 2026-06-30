from aiogram.fsm.state import StatesGroup, State


class RegistrationStates(StatesGroup):
    """FSM для создания анкеты."""
    waiting_name = State()
    waiting_gender = State()
    waiting_age = State()
    waiting_city = State()
    waiting_bio = State()
    waiting_looking_for = State()
    waiting_photo = State()
    waiting_interests = State()


class DatingStates(StatesGroup):
    """FSM для просмотра анкет."""
    viewing_profile = State()


class ChatStates(StatesGroup):
    """FSM для чата с мэтчем."""
    in_chat = State()
    waiting_message = State()
