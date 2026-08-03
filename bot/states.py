from aiogram.fsm.state import StatesGroup, State


class RegistrationStates(StatesGroup):
    """FSM для создания анкеты.

    Порядок шагов — минимум трения (Davinchik-style):
    имя → возраст → пол → кого ищем → город → фото → био (необязательно).
    """
    waiting_name = State()
    waiting_age = State()
    waiting_gender = State()
    waiting_looking_for = State()
    waiting_city = State()
    waiting_photo = State()
    waiting_bio = State()


class DatingStates(StatesGroup):
    """FSM для просмотра анкет."""
    viewing_profile = State()


class ChatStates(StatesGroup):
    """FSM для чата с мэтчем."""
    in_chat = State()
    waiting_message = State()
