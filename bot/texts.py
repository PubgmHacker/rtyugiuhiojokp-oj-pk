from __future__ import annotations

import html
from datetime import datetime


def _esc(value) -> str:
    """Экранирует пользовательский контент для parse_mode=HTML."""
    return html.escape(str(value or ""), quote=False)


#: То же экранирование для хендлеров: они тоже вставляют пользовательский
#: текст в разметку, и своя копия html.escape там разъехалась бы с этой.
escape = _esc


def welcome(name: str = "") -> str:
    hour = datetime.now().hour
    if hour < 6:
        greet = "Доброй ночи"
    elif hour < 12:
        greet = "Доброе утро"
    elif hour < 18:
        greet = "Добрый день"
    else:
        greet = "Добрый вечер"

    return (
        f"{greet}{', ' + _esc(name) if name else ''}! 💕\n\n"
        "Это <b>Souldawn</b> — знакомства без лишней суеты.\n\n"
        "Заполним анкету за пару минут, а дальше — только те, кто вам "
        "подходит. Понравитесь друг другу — откроется чат.\n\n"
        "Поехали?"
    )


def menu_text(name: str = "", is_ready: bool = False) -> str:
    if is_ready:
        body = "Анкета готова — можно смотреть людей 👀"
    else:
        body = "Анкета ещё не заполнена. Давайте это исправим 👇"
    return f"<b>Souldawn</b> 💕\n\n{body}"


# ── Регистрация ─────────────────────────────────────────────────

def reg_step(step: str) -> str:
    steps = {
        "name": "Как вас зовут?\n\n<i>Напишите имя, которое увидят другие.</i>",
        "age": (
            "Сколько вам лет?\n\n"
            "<i>Напишите числом. Сервис только для тех, кому есть 18.</i>"
        ),
        "gender": "Ваш пол?",
        "looking_for": "Кого вам показывать?",
        "goal": (
            "Что вы ищете?\n\n"
            "<i>Так мы покажем вас тем, кто хочет того же.</i>"
        ),
        "city": (
            "Из какого вы города?\n\n"
            "<i>Напишите название или отправьте геопозицию — "
            "так покажем людей поблизости.</i>"
        ),
        "photo": (
            "Пришлите фото 📸\n\n"
            "<i>Одно обязательно, можно до шести. "
            "Первое станет главным в анкете.</i>"
        ),
        "bio": (
            "Пара слов о себе ✍️\n\n"
            "<i>Что угодно: чем занимаетесь, что любите, кого ищете. "
            "С этого людям проще начать разговор.</i>"
        ),
    }
    return steps.get(step, "Продолжаем…")


REG_AGE_INVALID = (
    "Не понял возраст 🤔 Напишите, пожалуйста, числом — например, <b>25</b>."
)
REG_AGE_TOO_YOUNG = (
    "Souldawn — сервис для тех, кому уже есть 18. "
    "Возвращайтесь, когда подрастёте 🙏"
)
REG_AGE_TOO_OLD = "Кажется, здесь опечатка. Укажите возраст от 18 до 99."
REG_NAME_TOO_SHORT = "Слишком коротко. Напишите имя хотя бы из двух букв."

REG_EXPECT_TEXT = "Здесь нужен текст 🙂 Напишите ответ сообщением."
REG_EXPECT_PHOTO = "Пришлите, пожалуйста, именно фото 📸"
REG_EXPECT_BUTTON = "Выберите вариант кнопкой ниже 👇"

REG_PHOTO_ADDED = "Фото добавлено ({count}/6). Пришлите ещё или нажмите «Готово»."
REG_PHOTO_LIMIT = "Шесть фото — максимум. Идём дальше 👇"
REG_PHOTO_NEED_ONE = "Нужно хотя бы одно фото — без него анкету почти не смотрят."
REG_PHOTO_REJECTED = "Это фото не подходит: {reason}\n\nПришлите, пожалуйста, другое."
REG_BIO_REJECTED = "Такой текст не подходит: {reason}\n\nПопробуйте иначе."

REG_DONE = (
    "Готово, анкета создана! ✨\n\n"
    "Теперь смотрите людей и ставьте ❤️ тем, кто понравился. "
    "Если симпатия взаимна — откроется чат."
)


# Подписи нишевых полей. Значения обязаны совпадать с
# web/src/lib/profileOptions.ts и keyboards.reg_goal_kb, иначе в боте и в
# мини-аппе один и тот же человек будет выглядеть по-разному.
GOAL_LABELS = {
    "relationship": "Отношения",
    "friendship": "Дружба",
    "chat": "Общение",
    "dates": "Свидания",
}

SUBCULTURE_LABELS = {
    "alt": "Альт",
    "anime": "Аниме",
    "goth": "Гот",
    "grunge": "Гранж",
    "kpop": "K-pop",
    "metal": "Металл",
    "punk": "Панк",
    "rap": "Рэп",
    "skate": "Скейт",
    "gamer": "Гейминг",
    "casual": "Кэжуал",
    "emo": "Эмо",
}


def profile_card(profile: dict) -> str:
    """Компактная карточка: имя, возраст, город, о себе — как в «Дайвинчике»."""
    line = f"<b>{_esc(profile.get('display_name', 'Без имени'))}</b>"
    if profile.get("age"):
        line += f", {profile['age']}"

    # Город, рост и цель — одной строкой через «·», как на карточке в мини-аппе
    facts = []
    if profile.get("city"):
        facts.append(_esc(profile["city"]))
    if profile.get("height_cm"):
        facts.append(f"{profile['height_cm']} см")
    goal = profile.get("goal")
    if goal:
        facts.append(_esc(GOAL_LABELS.get(goal, goal)))
    subculture = profile.get("subculture")
    if subculture:
        facts.append(_esc(SUBCULTURE_LABELS.get(subculture, subculture)))
    if profile.get("mbti"):
        facts.append(_esc(profile["mbti"]))
    if facts:
        line += " — " + " · ".join(facts)

    if profile.get("bio"):
        line += f"\n\n{_esc(profile['bio'])}"

    interests = profile.get("interests")
    if isinstance(interests, list) and interests:
        line += "\n\n" + " ".join("#" + _esc(i) for i in interests[:5])

    return line


def match_notification(
    partner: dict, score: int | None = None, reason: str | None = None
) -> str:
    name = _esc(partner.get("display_name", "этим человеком"))
    text = "💕 <b>Взаимно!</b>\n\n"
    text += f"Вы понравились друг другу с <b>{name}</b>"
    if partner.get("age"):
        text += f", {partner['age']}"
    text += ".\n\n"

    if score and reason:
        text += f"Совместимость {score}% — <i>{_esc(reason)}</i>\n\n"

    text += "Напишите первым 💬"
    return text


def no_more_profiles() -> str:
    return (
        "На сегодня анкеты закончились 🌅\n\n"
        "Заходите позже — или расширьте настройки поиска, "
        "чтобы видеть больше людей."
    )


def chat_header(partner_name: str) -> str:
    return f"💬 Чат с <b>{_esc(partner_name)}</b>\n\n"


# ── Меню и служебные сообщения ──────────────────────────────────

HELP = (
    "<b>Как это работает</b>\n\n"
    "Заполняете анкету, смотрите людей, ставите ❤️ или 👎. "
    "Если симпатия взаимна — открывается чат.\n\n"
    "<b>Команды</b>\n"
    "/start — главное меню\n"
    "/profile — моя анкета\n"
    "/premium — подписка и её возможности\n"
    "/invite — пригласить друзей и получить буст анкеты\n"
    "/link — код для входа в приложение на iPhone\n"
    "/pause — скрыть анкету из поиска\n"
    "/resume — вернуть анкету в поиск\n"
    "/delete — удалить аккаунт\n"
    "/help — эта справка\n\n"
    "Что-то не так? Напишите на support@souldawn.app"
)

LINK_CODE = (
    "📱 <b>Код для входа в приложение</b>\n\n"
    "<code>{code}</code>\n\n"
    "Введите его на экране входа в приложении Souldawn.\n"
    "Код действует 10 минут и работает один раз.\n\n"
    "⚠️ Никому не передавайте код — по нему входят в ваш аккаунт."
)

LINK_UNAVAILABLE = (
    "Не удалось выдать код, попробуйте через минуту.\n\n"
    "Пока можно пользоваться ботом и веб-версией."
)

PAUSED = (
    "Анкета скрыта из поиска 💤\n\n"
    "Вас больше не показывают другим. Мэтчи и переписка сохранились.\n"
    "Вернуть показ — /resume"
)
RESUMED = "Анкета снова в поиске ✨ Удачных знакомств!"

DELETE_CONFIRM = (
    "⚠️ <b>Удалить аккаунт?</b>\n\n"
    "Будут безвозвратно удалены анкета, фотографии, мэтчи и вся переписка. "
    "Отменить это будет нельзя.\n\n"
    "Если уверены — напишите <b>УДАЛИТЬ</b> заглавными буквами.\n"
    "Передумали — нажмите «Отмена»."
)
DELETE_CANCELLED = "Ничего не удалено, всё на месте 🙂"
DELETE_DONE = (
    "Аккаунт удалён. Спасибо, что были с нами 🌅\n\n"
    "Если захотите вернуться — просто напишите /start."
)
DELETE_WRONG_WORD = (
    "Не совпало. Чтобы удалить аккаунт, напишите <b>УДАЛИТЬ</b> "
    "заглавными буквами, или нажмите «Отмена»."
)

CANCELLED = "Отменил. Что дальше?"
BANNED = (
    "Доступ к сервису закрыт из-за нарушения правил.\n\n"
    "Если считаете это ошибкой — напишите на support@souldawn.app"
)
ERROR_GENERIC = "Что-то сломалось на нашей стороне 😔 Попробуйте ещё раз через минуту."
TOO_FAST = "Слишком быстро 🙂 Секунду…"
REPORT_SENT = (
    "Жалоба отправлена, анкета больше не появится ✅\n\n"
    "Модераторы разберутся. Спасибо, что помогаете."
)
BLOCK_DONE = (
    "Пользователь заблокирован 🚫\n\n"
    "Вы больше не увидите друг друга, и связаться он не сможет.\n"
    "Снять блокировку можно в приложении: Профиль → Заблокированные."
)
NEED_PROFILE = "Сначала заполним анкету — это быстро 👇"


LIKE_MESSAGE_ASK = (
    "💌 Что написать?\n\n"
    "<i>Пара слов уйдёт вместе с лайком — их увидят до взаимности. "
    "До 200 символов.</i>"
)
LIKE_MESSAGE_TOO_LONG = "Слишком длинно — уложитесь в 200 символов."
LIKE_MESSAGE_SENT = "💌 Лайк с сообщением отправлен!"
LIKE_MESSAGE_REJECTED = "Сообщение не прошло проверку: {reason}"
