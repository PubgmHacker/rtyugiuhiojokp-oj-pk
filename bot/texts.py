from __future__ import annotations

from datetime import datetime


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
        f"{greet}{', ' + name if name else ''}! 💕\n\n"
        "Добро пожаловать в **Souldawn Dating** — сервис знакомств нового поколения.\n\n"
        "🔮 **AI-совместимость** — наша нейросеть подбирает идеальные мэтчи\n"
        "💬 **Реал-тайм чат** — общайся мгновенно\n"
        "📱 **3 платформы** — Telegram, Web и iOS\n\n"
        "Нажми кнопку ниже, чтобы начать!"
    )


def profile_card(profile: dict) -> str:
    parts = []
    if profile.get("display_name"):
        parts.append(f"👤 **{profile['display_name']}")
    if profile.get("age"):
        parts.append(f"{profile['age']}")
    if parts:
        parts[0] = parts[0] + "**" if not parts[0].endswith("**") else parts[0]

    line = f"👤 **{profile.get('display_name', 'Без имени')}**"
    if profile.get("age"):
        line += f", {profile['age']}"
    if profile.get("city"):
        line += f"\n📍 {profile['city']}"

    if profile.get("bio"):
        line += f"\n\n💬 _{profile['bio']}_"
    if profile.get("interests"):
        interests = profile["interests"]
        if isinstance(interests, list) and interests:
            line += f"\n\n🎯 {', '.join(f'#{i}' for i in interests[:5])}"
    if profile.get("ai_bio"):
        line += f"\n\n✨ _{profile['ai_bio']}_"

    return line


def match_notification(partner: dict, score: int | None = None, reason: str | None = None) -> str:
    text = f"🎉 **НОВЫЙ МЭТЧ!**\n\n"
    text += f"👤 **{partner.get('display_name', 'Без имени')}**"
    if partner.get("age"):
        text += f", {partner['age']}"
    text += "\n\n"

    if score and reason:
        text += f"🔮 **Совместимость: {score}/100**\n_{reason}_\n\n"

    text += "Начните общение прямо сейчас! 💬"
    return text


def no_more_profiles() -> str:
    return (
        "😔 Анкет пока нет. Попробуйте позже или расширьте настройки поиска!\n\n"
        "Совет: добавьте фото и описание — так вас будут видеть чаще."
    )


def reg_step(step: str) -> str:
    steps = {
        "name": "📝 Введите ваше имя (или отправьте текущее):",
        "gender": "👤 Выберите пол:",
        "age": "🎂 Укажите ваш возраст (18-99):",
        "city": "📍 Введите ваш город:",
        "bio": "✍️ Расскажите о себе (до 500 символов):",
        "looking_for": "💕 Кого вы ищете?",
        "photo": "📸 Отправьте фото (до 6 шт). Или /skip",
        "interests": "🎯 Перечислите ваши интересы через запятую:",
    }
    return steps.get(step, "Продолжайте...")


def menu_text(name: str = "", is_verified: bool = False) -> str:
    status = "✅ Анкета заполнена" if is_verified else "⚠️ Заполните анкету"
    return (
        f"**SOULDAWN DATING** 💕\n\n"
        f"{status}\n\n"
        "Выберите действие:"
    )


def chat_header(partner_name: str) -> str:
    return f"💬 Чат с **{partner_name}**\n_Отправьте сообщение или отправьте фото_\n\n"
