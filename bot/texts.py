from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone

from services.plans import имя_уровня_для


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
        "Это <b>Симп</b> — знакомства без лишней суеты.\n\n"
        "Заполним анкету за пару минут, а дальше — только те, кто вам "
        "подходит. Понравитесь друг другу — откроется чат.\n\n"
        "Поехали?"
    )


def menu_text(name: str = "", is_ready: bool = False) -> str:
    if is_ready:
        body = "Анкета готова — можно смотреть людей 👀"
    else:
        body = "Анкета ещё не заполнена. Давайте это исправим 👇"
    return f"<b>Симп</b> 💕\n\n{body}"


# ── Регистрация ─────────────────────────────────────────────────

def reg_step(step: str) -> str:
    steps = {
        "name": "Как вас зовут?\n\n<i>Напишите имя, которое увидят другие.</i>",
        "age": (
            "Сколько вам лет?\n\n"
            "<i>Напишите числом. Сервис с 16 лет.</i>"
        ),
        "gender": "Ваш пол?",
        "looking_for": "Кого вам показывать?",
        "goal": (
            "Что вы ищете?\n\n"
            "<i>Так мы покажем вас тем, кто хочет того же.</i>"
        ),
        "relation_type": (
            "С кем? 🙂\n\n"
            "<i>Друзья, подруги или партнёр — уточняет цель знакомства, "
            "но это отдельный вопрос.</i>"
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
    "Симп — сервис с 16 лет. "
    "Возвращайтесь, когда подрастёте 🙏"
)
REG_AGE_TOO_OLD = "Кажется, здесь опечатка. Укажите возраст от 16 до 99."
REG_NAME_TOO_SHORT = "Слишком коротко. Напишите имя хотя бы из двух букв."
REG_NAME_REJECTED = "Такое имя не подходит: {reason}\n\nПопробуйте другое."

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

# Тип связи («с кем») — отдельная ось от цели («зачем»), значения обязаны
# совпадать с web/src/lib/profileOptions.ts (RELATION_TYPES) и
# keyboards.reg_relation_type_kb.
RELATION_TYPE_LABELS = {
    "friends": "Друзья",
    "girlfriends": "Подруги",
    "partner": "Партнёр",
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


#: Наклейку из коллекции в боте не показать картинкой — карточка там
#: текстовая, а сами наклейки это SVG для веба. Поэтому рядом с именем
#: ставится значок: сам факт «человек что-то собрал» виден и здесь.
ЗНАЧОК_НАКЛЕЙКИ = "✦"


def profile_card(profile: dict) -> str:
    """Компактная карточка: имя, возраст, город, о себе — как в «Дайвинчике»."""
    line = f"<b>{_esc(profile.get('display_name', 'Без имени'))}</b>"
    if profile.get("sticker"):
        line += f" {ЗНАЧОК_НАКЛЕЙКИ}"
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
    relation_type = profile.get("relation_type")
    if relation_type:
        facts.append(_esc(RELATION_TYPE_LABELS.get(relation_type, relation_type)))
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


def no_more_profiles(с_приложением: bool = True) -> str:
    # Настроек поиска (возраст, дистанция, нишевые фильтры) в самом боте нет —
    # они живут в мини-аппе. Текст не должен обещать то, чего нет в этом
    # интерфейсе; кнопка на мини-апп идёт рядом (см. keyboards.no_more_profiles_kb).
    #
    # `с_приложением=False` — когда открыть мини-апп нечем (SITE_URL без HTTPS
    # и петлёй, config.mini_app_openable). Кнопки в этой клавиатуре тогда нет, и
    # звать «откройте приложение» некуда: это выглядело бы поломкой кнопки.
    if not с_приложением:
        return (
            "На сегодня анкеты закончились 🌅\n\n"
            "Заходите позже — за день в вашем городе появляются новые люди."
        )
    return (
        "На сегодня анкеты закончились 🌅\n\n"
        "Заходите позже — или откройте приложение и расширьте настройки "
        "поиска, чтобы видеть больше людей."
    )


def chat_header(partner_name: str) -> str:
    return f"💬 Чат с <b>{_esc(partner_name)}</b>\n\n"


# ── Суточные лимиты бесплатного уровня ──────────────────────────
#
# Один разговор на оба лимита: «на сегодня всё, дальше по подписке или до
# возврата слота». Тексты держим здесь, а не в хендлерах, потому что то же
# самое показывает мини-апп (web/src/components/LimitSheet.tsx) — расхождение
# читается как обман ровно там, где человек решает платить.


def когда_слот(reset_at: datetime | None) -> str:
    """«сегодня в 21:40» / «завтра в 09:15» — как в шторке мини-аппа.

    Окно скользящее, поэтому «завтра в полночь» было бы неправдой: слот
    возвращается через сутки после того, как был потрачен.

    Время показываем в МСК: часового пояса человека у бота нет, а UTC в
    сообщении читается как ошибка. Зона названа прямо, чтобы «в 09:15» не
    оказалось чужими девятью утра.
    """
    if reset_at is None:
        return "в течение суток"
    if reset_at.tzinfo is None:
        reset_at = reset_at.replace(tzinfo=timezone.utc)

    мск = timezone(timedelta(hours=3))
    когда = reset_at.astimezone(мск)
    сейчас = datetime.now(мск)
    время = когда.strftime("%H:%M")

    if когда.date() == сейчас.date():
        return f"сегодня в {время} МСК"
    if когда.date() == (сейчас + timedelta(days=1)).date():
        return f"завтра в {время} МСК"
    return f"{когда.day} {_МЕСЯЦЫ[когда.month]} в {время} МСК"


_МЕСЯЦЫ = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля", 5: "мая", 6: "июня",
    7: "июля", 8: "августа", 9: "сентября", 10: "октября", 11: "ноября",
    12: "декабря",
}


def падеж(n: int, one: str, few: str, many: str) -> str:
    """Русское согласование числа: 1 лайк, 2 лайка, 5 лайков.

    «10 лайк(ов)» в платящем экране выглядит как недоделка, а лимиты
    печатаются числами из `services/plans.py` — значит, любые.
    """
    mod10, mod100 = n % 10, n % 100
    if mod10 == 1 and mod100 != 11:
        return one
    if 2 <= mod10 <= 4 and not 12 <= mod100 <= 14:
        return few
    return many


def likes_left(left: int) -> str:
    """Хвост «осталось N лайков» под карточкой анкеты.

    Показываем остаток, а не только факт исчерпания: человек должен увидеть,
    что лимит существует, до того как упрётся в него — иначе первый отказ
    читается как поломка бота.
    """
    if left <= 3:
        return f"⚡ Осталось {left} {падеж(left, 'лайк', 'лайка', 'лайков')} на сегодня"
    return f"Осталось {left} {падеж(left, 'лайк', 'лайка', 'лайков')} на сегодня"


def likes_limit_reached(limit: int, reset_at: datetime | None) -> str:
    return (
        "💔 <b>Лайки на сегодня закончились</b>\n\n"
        f"На бесплатном уровне — {limit} "
        f"{падеж(limit, 'лайк', 'лайка', 'лайков')} в сутки.\n"
        f"Следующий вернётся {когда_слот(reset_at)}.\n\n"
        "Смотреть анкеты можно дальше: 👎 лимит не тратит.\n\n"
        "С подпиской лайки без ограничений — и видно, кто лайкнул вас."
    )


def match_limit_reached(limit: int, reset_at: datetime | None) -> str:
    return (
        "🔒 <b>Этот мэтч пока закрыт</b>\n\n"
        f"На бесплатном уровне открыто {limit} "
        f"{падеж(limit, 'мэтч', 'мэтча', 'мэтчей')} в сутки.\n"
        f"Следующий слот вернётся {когда_слот(reset_at)}.\n\n"
        "Уже открытые чаты остаются доступны — читайте и отвечайте без "
        "ограничений.\n\n"
        "С подпиской открыты все мэтчи сразу."
    )


def match_locked_notification(limit: int, reset_at: datetime | None) -> str:
    """Пуш о новом мэтче, когда суточные открытия исчерпаны.

    Имени и фото здесь нет сознательно: закрытый мэтч — это «есть кто-то», а
    не «вот кто». Иначе пуш выдавал бы даром именно то, что скрывает список
    (см. database/connection.get_user_matches).
    """
    return (
        "💕 <b>У вас новый мэтч!</b>\n\n"
        f"Но суточные открытия закончились — на бесплатном уровне их {limit}.\n"
        f"Слот вернётся {когда_слот(reset_at)}.\n\n"
        "С подпиской чат откроется прямо сейчас."
    )


MATCH_LOCKED_SHORT = "🔒 Мэтч закрыт суточным лимитом"
LIKES_LIMIT_SHORT = "💔 Лайки на сегодня закончились"


# ── Меню и служебные сообщения ──────────────────────────────────

HELP = (
    "<b>Как это работает</b>\n\n"
    "Заполняете анкету, смотрите людей, ставите ❤️ или 👎. "
    "Если симпатия взаимна — открывается чат.\n\n"
    "<b>Команды</b>\n"
    "/start — запустить бота\n"
    "/menu — главное меню\n"
    "/profile — моя анкета\n"
    "/premium — подписка и её возможности\n"
    "/invite — пригласить друзей и получить буст анкеты\n"
    "/link — код для входа в приложение на iPhone\n"
    "/pause — скрыть анкету из поиска\n"
    "/resume — вернуть анкету в поиск\n"
    "/cancel — отменить текущее действие\n"
    "/delete — удалить аккаунт\n"
    "/help — эта справка\n\n"
    "Что-то не так? Напишите на support@simp.app"
)

LINK_CODE = (
    "📱 <b>Код для входа в приложение</b>\n\n"
    "<code>{code}</code>\n\n"
    "Введите его на экране входа в приложении «Симп».\n"
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
    "Если считаете это ошибкой — напишите на support@simp.app"
)
ERROR_GENERIC = "Что-то сломалось на нашей стороне 😔 Попробуйте ещё раз через минуту."

# ── Онбординг как у Mimolet: язык → политика → рассылки ─────────

ONBOARDING_LOCALE_FALLBACK = "en"
ONBOARDING_LOCALES = ("ru", "en", "uz", "es", "tr", "id", "zh")


def resolve_locale(code: str | None) -> str:
    raw = (code or "ru").strip().lower()
    if raw in ONBOARDING_LOCALES:
        return raw
    return ONBOARDING_LOCALE_FALLBACK


def onboarding_choose_language() -> str:
    """До выбора языка Mimolet всегда пишет по-русски."""
    return "Выберите язык"


def onboarding_continue_label(locale: str = "ru") -> str:
    labels = {
        "ru": "✅ Продолжить",
        "en": "✅ Continue",
        "uz": "✅ Davom etish",
        "es": "✅ Continuar",
        "tr": "✅ Devam",
        "id": "✅ Lanjutkan",
        "zh": "✅ 继续",
    }
    return labels.get(resolve_locale(locale), labels["en"])


def onboarding_start_label(locale: str = "ru") -> str:
    labels = {
        "ru": "Начать",
        "en": "Start",
        "uz": "Boshlash",
        "es": "Empezar",
        "tr": "Başla",
        "id": "Mulai",
        "zh": "开始",
    }
    return labels.get(resolve_locale(locale), labels["en"])


def onboarding_stale_tap(locale: str = "ru") -> str:
    """Ответ на кнопку старта, нажатую посреди другого сценария.

    Кнопки под старыми сообщениями в Telegram остаются нажимаемыми навсегда:
    первое сообщение /start с «Продолжить» лежит в переписке и через месяц.
    Тап по нему посреди заполнения анкеты раньше уводил человека обратно в
    онбординг и сбрасывал всё введённое, поэтому такие тапы обработчики
    онбординга больше не получают. Подтвердить тап всё равно обязательно —
    без ответа на callback у человека висят часики до таймаута Telegram.
    """
    labels = {
        "ru": "Это кнопка из старого сообщения. Продолжайте здесь 👇",
        "en": "That button is from an old message. Carry on here 👇",
        "uz": "Bu tugma eski xabardan. Shu yerda davom etaylik 👇",
        "es": "Ese botón es de un mensaje antiguo. Sigamos aquí 👇",
        "tr": "Bu düğme eski bir mesajdan. Buradan devam edelim 👇",
        "id": "Tombol itu dari pesan lama. Lanjutkan di sini 👇",
        "zh": "这是旧消息里的按钮。请在这里继续 👇",
    }
    return labels.get(resolve_locale(locale), labels["en"])


def onboarding_consent(locale: str, privacy_url: str, terms_url: str) -> str:
    """Текст согласия. Ссылки — настоящие URL политики и оферты."""
    loc = resolve_locale(locale)
    privacy = f'<a href="{html.escape(privacy_url, quote=True)}">{{label}}</a>'
    terms = f'<a href="{html.escape(terms_url, quote=True)}">{{label}}</a>'
    templates = {
        "ru": (
            "Нажимая кнопку \"✅ Продолжить\" вы подтверждаете согласие с нашей "
            + privacy.format(label="политикой конфиденциальности")
            + " и "
            + terms.format(label="пользовательским соглашением")
            + "."
        ),
        "en": (
            "By tapping \"✅ Continue\" you confirm that you agree to our "
            + privacy.format(label="privacy policy")
            + " and "
            + terms.format(label="user agreement")
            + "."
        ),
        "uz": (
            "\"✅ Davom etish\" tugmasini bosib, siz bizning "
            + privacy.format(label="maxfiylik siyosatimiz")
            + " va "
            + terms.format(label="foydalanuvchi shartnomamiz")
            + " bilan rozilik bildirganingizni tasdiqlaysiz."
        ),
        "es": (
            "Al pulsar \"✅ Continuar\" confirmas que aceptas nuestra "
            + privacy.format(label="política de privacidad")
            + " y el "
            + terms.format(label="acuerdo de usuario")
            + "."
        ),
        "tr": (
            "\"✅ Devam\" düğmesine basarak "
            + privacy.format(label="gizlilik politikamızı")
            + " ve "
            + terms.format(label="kullanıcı sözleşmemizi")
            + " kabul ettiğinizi onaylarsınız."
        ),
        "id": (
            "Dengan menekan tombol \"✅ Lanjutkan\" Anda mengonfirmasi persetujuan dengan "
            + privacy.format(label="kebijakan privasi")
            + " dan "
            + terms.format(label="perjanjian pengguna")
            + " kami."
        ),
        "zh": (
            "点击\"✅ 继续\"即表示您同意我们的"
            + privacy.format(label="隐私政策")
            + "和"
            + terms.format(label="用户协议")
            + "。"
        ),
    }
    return templates.get(loc, templates["en"])


def onboarding_broadcast_style(locale: str = "ru") -> str:
    """Рассылка про субкультуру. Ритм Mimolet, голос Симпа — без поэзии.

    В нерусских локалях марка латиницей: кириллическое «Симп» в английской
    или китайской строке читается как сбой кодировки, а не как название.
    """
    texts = {
        "ru": (
            "🖤 В Симпе можно указать субкультуру или стиль: гот, эмо, "
            "скейтер, гранж, альт, аниме и не только.\n"
            "😉 Это помогает быстрее находить людей, которым близка твоя эстетика.\n"
            "🔥 Если анкеты еще нет, нажми «Начать»."
        ),
        "en": (
            "🖤 In Simp you can set your subculture or style: goth, emo, "
            "skater, grunge, alt, anime and more.\n"
            "😉 That helps you find people who share your aesthetic faster.\n"
            "🔥 If you don't have a profile yet, tap “Start”."
        ),
        "uz": (
            "🖤 Simp’da subkultura yoki uslubni belgilash mumkin: got, emo, "
            "skeyter, granj, alt, anime va boshqalar.\n"
            "😉 Bu o‘z estetikangizga yaqin odamlarni tezroq topishga yordam beradi.\n"
            "🔥 Anketa hali yo‘q bo‘lsa, «Boshlash» ni bosing."
        ),
        "es": (
            "🖤 En Simp puedes indicar tu subcultura o estilo: gótico, emo, "
            "skater, grunge, alt, anime y más.\n"
            "😉 Así encuentras antes a gente con tu misma estética.\n"
            "🔥 Si aún no tienes perfil, pulsa «Empezar»."
        ),
        "tr": (
            "🖤 Simp’te alt kültür veya stilini belirtebilirsin: goth, emo, "
            "skater, grunge, alt, anime ve daha fazlası.\n"
            "😉 Estetiğine yakın insanları daha hızlı bulmana yardım eder.\n"
            "🔥 Profilin yoksa «Başla»ya dokun."
        ),
        "id": (
            "🖤 Di Simp kamu bisa memilih subkultur atau gaya: goth, emo, "
            "skater, grunge, alt, anime, dan lainnya.\n"
            "😉 Ini membantu menemukan orang dengan estetika yang sama lebih cepat.\n"
            "🔥 Jika belum ada profil, ketuk «Mulai»."
        ),
        "zh": (
            "🖤 在 Simp 可以标注亚文化或风格：哥特、emo、滑板、grunge、alt、动漫等等。\n"
            "😉 这样能更快找到审美相近的人。\n"
            "🔥 还没有资料的话，点「开始」。"
        ),
    }
    return texts.get(resolve_locale(locale), texts["en"])


def onboarding_broadcast_email(locale: str = "ru") -> str:
    """Вторая рассылка Mimolet: почта, чтобы анкета не пропала с Telegram."""
    texts = {
        "ru": (
            "🔐 <b>Сохраните доступ к своей анкете</b>\n\n"
            "Если вы зарегистрировались через Telegram, добавьте почту в меню «Профиль».\n\n"
            "🎛 Тогда вы сможете входить и через бота, и через приложение.\n"
            "🛡 Анкета останется доступна по почте, даже если пропадёт Telegram.\n"
            "⏱ Это займёт всего 30 секунд.\n\n"
            "Откройте меню «Профиль» и добавьте почту 📧"
        ),
        "en": (
            "🔐 <b>Save access to your profile</b>\n\n"
            "If you signed up via Telegram, add an email in the Profile menu.\n\n"
            "🎛 You’ll be able to sign in through the bot and the app.\n"
            "🛡 The profile stays reachable by email even if Telegram is gone.\n"
            "⏱ It takes about 30 seconds.\n\n"
            "Open Profile and add an email 📧"
        ),
        "uz": (
            "🔐 <b>Anketangizga kirishni saqlab qoling</b>\n\n"
            "Telegram orqali ro‘yxatdan o‘tgan bo‘lsangiz, «Profil» menyusida pochta qo‘shing.\n\n"
            "🎛 Unda bot va ilova orqali kira olasiz.\n"
            "🛡 Telegram yo‘qolsa ham, anketa pochta orqali ochiladi.\n"
            "⏱ Bu atigi 30 soniya.\n\n"
            "«Profil» menyusini oching va pochta qo‘shing 📧"
        ),
        "es": (
            "🔐 <b>Guarda el acceso a tu perfil</b>\n\n"
            "Si te registraste por Telegram, añade un correo en el menú Perfil.\n\n"
            "🎛 Podrás entrar por el bot y por la app.\n"
            "🛡 El perfil seguirá accesible por correo aunque pierdas Telegram.\n"
            "⏱ Tarda unos 30 segundos.\n\n"
            "Abre Perfil y añade un correo 📧"
        ),
        "tr": (
            "🔐 <b>Profiline erişimi kaydet</b>\n\n"
            "Telegram ile kayıt olduysan Profil menüsüne e-posta ekle.\n\n"
            "🎛 Hem bottan hem uygulamadan girebilirsin.\n"
            "🛡 Telegram gitse bile profil e-posta ile açılır.\n"
            "⏱ Yaklaşık 30 saniye sürer.\n\n"
            "Profil menüsünü aç ve e-posta ekle 📧"
        ),
        "id": (
            "🔐 <b>Simpan akses ke profilmu</b>\n\n"
            "Jika daftar lewat Telegram, tambahkan email di menu Profil.\n\n"
            "🎛 Kamu bisa masuk lewat bot dan aplikasi.\n"
            "🛡 Profil tetap bisa diakses lewat email jika Telegram hilang.\n"
            "⏱ Hanya sekitar 30 detik.\n\n"
            "Buka menu Profil dan tambahkan email 📧"
        ),
        "zh": (
            "🔐 <b>保存资料的访问方式</b>\n\n"
            "如果是通过 Telegram 注册的，请在「资料」菜单里加上邮箱。\n\n"
            "🎛 之后可以用机器人，也可以用 App 登录。\n"
            "🛡 即使丢掉 Telegram，也能用邮箱打开资料。\n"
            "⏱ 大概 30 秒。\n\n"
            "打开「资料」并添加邮箱 📧"
        ),
    }
    return texts.get(resolve_locale(locale), texts["en"])

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

# Кто именно лайкнул — платный гейт. Про сам лайк сообщаем: иначе человек не
# знает, что у него есть входящие, и покупать ему нечего.
#
# Имя уровня берём из таблицы возможностей, а не пишем словом: гейт живёт в
# FEATURE_MIN_TIER, и с переносом фичи выше текст рекламировал бы уровень, на
# котором её уже нет.
LIKE_LOCKED = (
    "💌 Вы кому-то понравились!\n\n"
    f"<i>Кто это — видно в {имя_уровня_для('see_who_liked')}. "
    "Там же откроются все входящие лайки.</i>"
)
