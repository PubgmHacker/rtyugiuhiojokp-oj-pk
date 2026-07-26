from __future__ import annotations

import html
from datetime import datetime


def _esc(value) -> str:
    """Экранирует пользовательский контент для parse_mode=HTML."""
    return html.escape(str(value or ""), quote=False)


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
        "Добро пожаловать в <b>Souldawn Dating</b> — сервис знакомств нового поколения.\n\n"
        "🔮 <b>AI-совместимость</b> — наша нейросеть подбирает идеальные мэтчи\n"
        "💬 <b>Реал-тайм чат</b> — общайся мгновенно\n"
        "📱 <b>3 платформы</b> — Telegram, Web и iOS\n\n"
        "Нажми кнопку ниже, чтобы начать!"
    )


def profile_card(profile: dict) -> str:
    line = f"👤 <b>{_esc(profile.get('display_name', 'Без имени'))}</b>"
    if profile.get("age"):
        line += f", {profile['age']}"
    if profile.get("city"):
        line += f"\n📍 {_esc(profile['city'])}"

    if profile.get("bio"):
        line += f"\n\n💬 <i>{_esc(profile['bio'])}</i>"
    if profile.get("interests"):
        interests = profile["interests"]
        if isinstance(interests, list) and interests:
            line += f"\n\n🎯 {', '.join('#' + _esc(i) for i in interests[:5])}"
    if profile.get("ai_bio"):
        line += f"\n\n✨ <i>{_esc(profile['ai_bio'])}</i>"

    return line


def match_notification(partner: dict, score: int | None = None, reason: str | None = None) -> str:
    text = "🎉 <b>НОВЫЙ МЭТЧ!</b>\n\n"
    text += f"👤 <b>{_esc(partner.get('display_name', 'Без имени'))}</b>"
    if partner.get("age"):
        text += f", {partner['age']}"
    text += "\n\n"

    if score and reason:
        text += f"🔮 <b>Совместимость: {score}/100</b>\n<i>{_esc(reason)}</i>\n\n"

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
        "<b>SOULDAWN DATING</b> 💕\n\n"
        f"{status}\n\n"
        "Выберите действие:"
    )


def chat_header(partner_name: str) -> str:
    return (
        f"💬 Чат с <b>{_esc(partner_name)}</b>\n"
        "<i>Отправьте сообщение или откройте чат в Web App</i>\n\n"
    )
