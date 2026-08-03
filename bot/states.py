from aiogram.fsm.state import StatesGroup, State


class RegistrationStates(StatesGroup):
    """Анкета за минимум шагов, как в «Дайвинчике»:
    имя → возраст → пол → кого ищем → город → фото → о себе.

    Интересы в боте намеренно не спрашиваем: это лишний шаг, на котором
    люди бросают регистрацию. Их можно добавить позже в мини-аппе.
    """

    waiting_name = State()
    waiting_age = State()
    waiting_gender = State()
    waiting_looking_for = State()
    waiting_city = State()
    waiting_photo = State()
    waiting_bio = State()


class DatingStates(StatesGroup):
    """Просмотр анкет."""

    viewing_profile = State()


class ChatStates(StatesGroup):
    """Переписка с мэтчем."""

    in_chat = State()
    waiting_message = State()


class DeleteStates(StatesGroup):
    """Удаление аккаунта — подтверждение в два шага."""

    confirming = State()
