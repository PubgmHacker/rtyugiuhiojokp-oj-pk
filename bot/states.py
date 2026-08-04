from aiogram.fsm.state import StatesGroup, State


class RegistrationStates(StatesGroup):
    """Анкета за минимум шагов, как в «Дайвинчике»:
    имя → возраст → пол → кого ищем → цель → город → фото → о себе.

    Интересы, рост и субкультуру в боте намеренно не спрашиваем: это лишние
    шаги, на которых люди бросают регистрацию. Они заполняются в мини-аппе.
    Цель знакомства — исключение: один тап, а подбор она меняет сильно.
    """

    waiting_name = State()
    waiting_age = State()
    waiting_gender = State()
    waiting_looking_for = State()
    waiting_goal = State()
    waiting_city = State()
    waiting_photo = State()
    waiting_bio = State()


class DatingStates(StatesGroup):
    """Просмотр анкет."""

    viewing_profile = State()
    # Ввод пары слов, которые уйдут вместе с лайком: получатель увидит их
    # до мэтча, поэтому это отдельный шаг, а не сообщение в чат
    waiting_like_message = State()


class ChatStates(StatesGroup):
    """Переписка с мэтчем."""

    in_chat = State()
    waiting_message = State()


class DeleteStates(StatesGroup):
    """Удаление аккаунта — подтверждение в два шага."""

    confirming = State()
