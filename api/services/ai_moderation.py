from __future__ import annotations

import asyncio
import base64
import json
import logging

from config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

#: Столько ждём ответа Zhipu. Без таймаута зависший запрос держит поток из
#: пула `to_thread` неограниченно долго: воркер один, пул общий, и несколько
#: таких запросов упираются в него — вместе с модерацией встают загрузки фото.
#: В боте этот таймаут был с самого начала (bot/services/moderation.py), в API
#: его забыли.
_AI_TIMEOUT = 12.0

#: Вердикт «проверка фото не состоялась». У текста при сбое AI остаётся
#: словарный фильтр, у фото замены нет: пропускать снимки ровно тогда, когда
#: фильтр лежит, — значит впускать порнографию и чужие фото без единой
#: проверки. Поэтому в проде фото без модерации отклоняется (fail-closed),
#: а роутеры по флагу `unavailable` отвечают 503 «попробуйте позже», а не
#: 422 «фото нарушает правила» — виноват сервис, не снимок. `blocked=True` —
#: чтобы код, не знающий про флаг, по умолчанию НЕ пропустил фото.
UNAVAILABLE: dict = {
    "safe": False,
    "blocked": True,
    "unavailable": True,
    "reason": "moderation unavailable",
}

# Lazy import zhipuai — may not be installed in dev
_zhipu_client = None


def _get_zhipu_client():
    global _zhipu_client
    if _zhipu_client is None and settings.ZHIPU_API_KEY:
        try:
            from zhipuai import ZhipuAI
            # Таймаут в самом SDK, а не только в asyncio.wait_for снаружи:
            # wait_for отпускает ожидающего, но синхронный вызов продолжает
            # ВИСЕТЬ в потоке executor до сетевого таймаута httpx — без этой
            # цифры зависший Zhipu постепенно съедал бы весь пул потоков.
            _zhipu_client = ZhipuAI(api_key=settings.ZHIPU_API_KEY, timeout=15.0)
        except ImportError:
            logger.warning("zhipuai package not installed")
    return _zhipu_client


def image_moderation_available() -> bool:
    """Работает ли проверка фото.

    Отдельная функция, потому что у текста и у фото разная цена отказа: текст
    без AI фильтруется по словарю, а фото — не фильтруется НИКАК. Для дейтинга
    это открытая дверь, и знать об этом нужно до инцидента, а не после.
    """
    return _get_zhipu_client() is not None


#: Категории блокировок текста. От категории зависит наказание
#: (services/enforcement.py: TEXT_STRIKE_RULES и лестница банов), поэтому
#: множество закрытое — незнакомая строка от модели не должна попадать в
#: правила напрямую.
#:
#: * "ad" — реклама и увод аудитории: ссылки, юзернеймы, промо каналов,
#:   продажа товаров/услуг, вербовка. Самая частая и самая осознанная —
#:   порог жёсткий (3), и рекламный текст автоудаляется из анкеты.
#: * "heavy" — то, за что банят почти сразу: наркотики, интим за деньги,
#:   скам-схемы, угрозы, всё про несовершеннолетних.
#: * "text" — остальные нарушения: оскорбления, харассмент, явная эротика.
#:   Сюда же нормализуется blocked-вердикт без категории (старый формат,
#:   незнакомая строка) — «text» самый мягкий, ошибочная классификация
#:   не должна ужесточать наказание.
TEXT_CATEGORIES = ("ad", "heavy", "text")


def _normalize_text_verdict(raw: dict) -> dict:
    """Привести вердикт текста к контракту {safe, blocked, category, reason}.

    Модель может вернуть что угодно: без category, с выдуманной категорией,
    с blocked-строкой вместо bool. Вызывающие ветвятся по blocked и передают
    category в правила страйков — оба поля обязаны быть предсказуемыми.
    """
    blocked = bool(raw.get("blocked"))
    category = raw.get("category") if blocked else ""
    if blocked and category not in TEXT_CATEGORIES:
        category = "text"
    return {
        "safe": not blocked,
        "blocked": blocked,
        "category": category or "",
        "reason": raw.get("reason", "") or "",
    }


async def moderate_text(text: str) -> dict:
    """Проверить текст через GLM-5.2 на нарушение правил.

    Returns: {"safe": bool, "blocked": bool, "category": str, "reason": str}

    category — из TEXT_CATEGORIES при blocked, "" при safe. По ней
    enforcement решает, когда предупреждать, а когда банить.
    """
    if not text or not text.strip():
        return {"safe": True, "blocked": False, "category": "", "reason": ""}

    client = _get_zhipu_client()
    if not client:
        # Fallback: simple keyword filter
        return _keyword_filter(text)

    try:
        # to_thread обязателен: SDK Zhipu синхронный, и прямой вызов
        # блокирует единственный event loop — на время запроса встаёт весь
        # сервер, включая чужие чаты и деку
        response = await asyncio.wait_for(
            asyncio.to_thread(
                client.chat.completions.create,
                model="glm-4-flash",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a content moderation AI for a dating app. "
                            "Analyze the following text and respond with JSON only:\n"
                            '{"safe": true/false, "blocked": true/false, '
                            '"category": "ad"/"heavy"/"text"/"", "reason": "brief explanation"}\n'
                            "When blocked, set category:\n"
                            '- "ad": advertising or audience funneling — external links, '
                            "usernames/handles (@name, t.me/..., wa.me/...), channel or group "
                            "invites, selling goods/services, promo codes, job/recruiting spam.\n"
                            '- "heavy": drugs, paid sexual services or escort, fraud/scam '
                            "schemes, threats of violence, anything sexualizing minors.\n"
                            '- "text": harassment, insults, hate speech, explicit sexual text, '
                            "other rule violations.\n"
                            'When safe, category is "".\n'
                            "Allow: normal dating bios, compliments, greetings."
                        ),
                    },
                    {"role": "user", "content": text},
                ],
                temperature=0.1,
                max_tokens=200,
            ),
            timeout=_AI_TIMEOUT,
        )
        content = response.choices[0].message.content.strip()
        # Try to parse JSON from response
        try:
            return _normalize_text_verdict(json.loads(content))
        except json.JSONDecodeError:
            # Extract JSON from possible markdown
            if "{" in content and "}" in content:
                start = content.index("{")
                end = content.rindex("}") + 1
                return _normalize_text_verdict(json.loads(content[start:end]))
            # Ответ модели не разобрать — вердикта нет, работает словарь
            return _keyword_filter(text)
    except Exception as e:
        logger.error(f"AI moderation error: {e}")
        from services.alerting import capture_exception
        capture_exception(e)
        # Раньше здесь возвращалось безусловное safe — сбой AI отключал
        # даже словарный фильтр, хотя он для этого случая и существует
        return _keyword_filter(text)


def _normalize_image_verdict(raw: dict) -> dict:
    """Привести вердикт фото к контракту {safe, blocked, category, reason}.

    У фото category бывает только "ad" (реклама В КАДРЕ: юзернеймы, ссылки,
    QR-коды, промо) или "" — за неё роутеры вешают тот же страйк, что за
    рекламный текст. Прочие блокировки фото (нудити, оружие) остаются с
    пустой категорией: это отказ без страйка. Нормализация в "text", как у
    текстового вердикта, здесь запрещена — фото-модель ошибается чаще, и
    каждый её блок превращался бы в шаг к бану.
    """
    blocked = bool(raw.get("blocked"))
    category = raw.get("category") if blocked else ""
    return {
        "safe": not blocked,
        "blocked": blocked,
        "category": "ad" if category == "ad" else "",
        "reason": raw.get("reason", "") or "",
    }


async def moderate_image(image_bytes: bytes) -> dict:
    """Проверить фото через GLM-5.2 multimodal.

    Returns: {"safe": bool, "blocked": bool, "category": str, "reason": str}
    (+ "unavailable": True, когда проверка не состоялась — см. UNAVAILABLE).

    category == "ad" — на снимке реклама: наложенный текст с юзернеймами и
    ссылками, QR-коды, промо чужих сервисов. Роутеры считают за это тот же
    страйк, что за рекламный текст (enforcement.TEXT_STRIKE_RULES["ad"]).

    Прод без работающего AI фото НЕ пропускает: fail-closed. В DEBUG —
    пропускает, локальный стенд обязан работать без внешних ключей.
    """
    client = _get_zhipu_client()
    if not client:
        if settings.DEBUG:
            logger.warning("Модерация фото не настроена — фото пропущено (DEBUG)")
            return {"safe": True, "blocked": False, "reason": "AI not configured"}
        # Молчаливый пропуск всех фото в дейтинге обнаруживается по жалобе,
        # а не по логам — поэтому отказ, громко
        logger.error(
            "Модерация фото недоступна (нет ZHIPU_API_KEY) — загрузка отклонена (fail-closed)"
        )
        return dict(UNAVAILABLE)

    try:
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        # Тот же to_thread: разбор фото у модели дольше текста, и блокировка
        # loop здесь заметнее всего
        response = await asyncio.wait_for(
            asyncio.to_thread(
                client.chat.completions.create,
                model="glm-4v-flash",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a content moderation AI for a dating app. "
                            "Analyze the image. Respond with JSON only:\n"
                            '{"safe": true/false, "blocked": true/false, '
                            '"category": "ad"/"", "reason": "brief explanation"}\n'
                            "Block: nudity, sexual content, violence, weapons, drugs.\n"
                            'Also block with category "ad": advertising in the image — '
                            "overlaid or clearly readable usernames/handles (@name, "
                            "t.me/..., wa.me/...), links, QR codes, phone numbers, "
                            "promo of channels/services, watermarks of other apps, "
                            "price lists or sales pitches.\n"
                            'For any other block, category is "". When safe, category is "".\n'
                            "Allow: selfies, portraits, lifestyle photos, pets, travel. "
                            "Incidental background text (street signs, book covers, "
                            "clothing brands) is NOT advertising."
                        ),
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                            {"type": "text", "text": "Analyze this image for dating app content policy."},
                        ],
                    },
                ],
                temperature=0.1,
                max_tokens=200,
            ),
            timeout=_AI_TIMEOUT,
        )
        content = response.choices[0].message.content.strip()
        try:
            return _normalize_image_verdict(json.loads(content))
        except json.JSONDecodeError:
            if "{" in content and "}" in content:
                start = content.index("{")
                end = content.rindex("}") + 1
                return _normalize_image_verdict(json.loads(content[start:end]))
            # Модель ответила, но вердикт не разобрать — проверки не было
            if settings.DEBUG:
                return {"safe": True, "blocked": False, "reason": "Parse error"}
            logger.error("Модерация фото: вердикт не разобран — загрузка отклонена (fail-closed)")
            return dict(UNAVAILABLE)
    except Exception as e:
        logger.error(f"AI image moderation error: {e}")
        from services.alerting import capture_exception
        capture_exception(e)
        if settings.DEBUG:
            return {"safe": True, "blocked": False, "reason": "AI unavailable"}
        return dict(UNAVAILABLE)


#: Живой проверке даём больше времени, чем модерации одного фото: в запросе
#: четыре изображения (три кадра + фото анкеты), и модель разбирает их дольше.
_LIVENESS_TIMEOUT = 25.0

#: Вердикт «проверка личности не состоялась». Та же доктрина, что UNAVAILABLE
#: у фото: без вердикта галочка не выдаётся, а роутер отвечает 503 «попробуйте
#: позже» — попытка при этом не сжигается (строка остаётся issued).
LIVENESS_UNAVAILABLE: dict = {
    "live": False,
    "real_face": False,
    "poses_match": False,
    "same_person": False,
    "matches_profile": False,
    "unavailable": True,
    "reason": "verification unavailable",
}


async def verify_liveness(
    frames: list[bytes], reference: bytes, poses: list[str]
) -> dict:
    """Живая проверка: кадры с поворотами головы против фото анкеты.

    `frames` — кадры в порядке заданных поз, `reference` — первое фото анкеты,
    `poses` — коды поз задания (см. ПОЗЫ в routers/verification.py).

    Returns: {"live": bool, "real_face": bool, "poses_match": bool,
              "same_person": bool, "matches_profile": bool, "reason": str}
    (+ "unavailable": True, когда проверка не состоялась).

    `real_face` — отдельная ось против нейросетевых подделок: live ловит
    съёмку экрана и статичные фото, real_face — сгенерированные и
    подменённые лица (face swap, дипфейк-фильтры поверх живого видео).

    Кадры живут только в памяти этого вызова: биометрию не пишем ни в R2,
    ни в журнал — наружу уходит только вердикт.

    Fail-closed, как у модерации фото: нет вердикта — нет галочки. В DEBUG
    проверка проходит без ключа, локальный стенд обязан работать.
    """
    client = _get_zhipu_client()
    if not client:
        if settings.DEBUG:
            logger.warning("Живая проверка не настроена — засчитана (DEBUG)")
            return {
                "live": True, "real_face": True, "poses_match": True,
                "same_person": True, "matches_profile": True,
                "reason": "AI not configured (DEBUG)",
            }
        logger.error(
            "Живая проверка недоступна (нет ZHIPU_API_KEY) — галочка не выдана (fail-closed)"
        )
        return dict(LIVENESS_UNAVAILABLE)

    try:
        content: list[dict] = []
        for кадр in frames:
            b64 = base64.b64encode(кадр).decode("utf-8")
            content.append(
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
            )
        b64 = base64.b64encode(reference).decode("utf-8")
        content.append(
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
        )
        content.append({
            "type": "text",
            "text": (
                f"Verify this liveness check. The user was asked to perform these "
                f"head poses in order: {', '.join(poses)}. The last image is the "
                f"reference profile photo."
            ),
        })

        response = await asyncio.wait_for(
            asyncio.to_thread(
                client.chat.completions.create,
                model="glm-4v-flash",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are an identity verification AI for a dating app. "
                            "You receive several selfie frames captured live in sequence, "
                            "followed by ONE reference profile photo (always the last image). "
                            "Respond with JSON only:\n"
                            '{"live": true/false, "real_face": true/false, '
                            '"poses_match": true/false, "same_person": true/false, '
                            '"matches_profile": true/false, "reason": "brief explanation"}\n'
                            "live=false if the frames look like a photo of a screen, a printed "
                            "photo, an identical image repeated, or anything other than a real "
                            "person filmed by a camera.\n"
                            "real_face=false if the face looks AI-generated, face-swapped or "
                            "deepfaked. Look for: blending seams or color mismatch where the "
                            "face meets hair, ears or neck; skin texture that is unnaturally "
                            "smooth or plastic while ears/neck/hands look normal; lighting on "
                            "the face inconsistent with the scene; warping, smearing or "
                            "flickering artifacts around the hairline, glasses or face outline "
                            "— especially in the turned-head frames where face swaps degrade; "
                            "facial identity or geometry subtly drifting between frames; "
                            "malformed teeth, asymmetric pupils or garbled background near the "
                            "head edges. A real unedited selfie has sensor noise, pores and "
                            "imperfections — their total absence is a red flag. Judge across "
                            "ALL frames together, not each in isolation.\n"
                            "poses_match=false if the head poses do not follow the requested "
                            "sequence. Frames come from a front-facing camera and may be "
                            "mirrored — do not fail left/right poses for mirroring alone.\n"
                            "same_person=false if the frames show different people.\n"
                            "matches_profile=false if the person in the frames is clearly not "
                            "the person in the reference photo. Allow for lighting, angle, "
                            "hairstyle and age differences typical for the same person."
                        ),
                    },
                    {"role": "user", "content": content},
                ],
                temperature=0.1,
                max_tokens=250,
            ),
            timeout=_LIVENESS_TIMEOUT,
        )
        текст = response.choices[0].message.content.strip()
        try:
            return json.loads(текст)
        except json.JSONDecodeError:
            if "{" in текст and "}" in текст:
                start = текст.index("{")
                end = текст.rindex("}") + 1
                return json.loads(текст[start:end])
            if settings.DEBUG:
                return {
                    "live": True, "real_face": True, "poses_match": True,
                    "same_person": True, "matches_profile": True,
                    "reason": "Parse error (DEBUG)",
                }
            logger.error("Живая проверка: вердикт не разобран — галочка не выдана (fail-closed)")
            return dict(LIVENESS_UNAVAILABLE)
    except Exception as e:
        logger.error(f"AI liveness error: {e}")
        from services.alerting import capture_exception
        capture_exception(e)
        if settings.DEBUG:
            return {
                "live": True, "real_face": True, "poses_match": True,
                "same_person": True, "matches_profile": True,
                "reason": "AI unavailable (DEBUG)",
            }
        return dict(LIVENESS_UNAVAILABLE)


#: Вердикт «сверка лица не состоялась» — для провайдерского режима, где
#: живость уже подтвердил Sumsub, а наша часть — только совпадение с анкетой.
FACE_MATCH_UNAVAILABLE: dict = {
    "matches_profile": False,
    "unavailable": True,
    "reason": "face match unavailable",
}


async def verify_face_match(selfie: bytes, reference: bytes) -> dict:
    """Селфи из проверки против фото анкеты: один и тот же человек?

    Нужна провайдерскому режиму (Sumsub): провайдер подтверждает, что перед
    камерой живой человек без подмены лица, но НЕ знает, чьи фото стоят в
    анкете. Галочка обязана значить «в анкете — он же», поэтому совпадение
    сверяем сами. Оба изображения живут только в памяти вызова.

    Returns: {"matches_profile": bool, "reason": str}
    (+ "unavailable": True, когда сверка не состоялась). Fail-closed,
    в DEBUG проходит без ключа — как verify_liveness.
    """
    client = _get_zhipu_client()
    if not client:
        if settings.DEBUG:
            logger.warning("Сверка лица не настроена — засчитана (DEBUG)")
            return {"matches_profile": True, "reason": "AI not configured (DEBUG)"}
        logger.error(
            "Сверка лица недоступна (нет ZHIPU_API_KEY) — галочка не выдана (fail-closed)"
        )
        return dict(FACE_MATCH_UNAVAILABLE)

    try:
        content: list[dict] = []
        for изображение in (selfie, reference):
            b64 = base64.b64encode(изображение).decode("utf-8")
            content.append(
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
            )
        content.append({
            "type": "text",
            "text": (
                "The first image is a live verification selfie, the second is "
                "the profile photo. Is it the same person?"
            ),
        })

        response = await asyncio.wait_for(
            asyncio.to_thread(
                client.chat.completions.create,
                model="glm-4v-flash",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are an identity verification AI for a dating app. "
                            "You receive TWO images: a live verification selfie and a "
                            "profile photo. Respond with JSON only:\n"
                            '{"matches_profile": true/false, "reason": "brief explanation"}\n'
                            "matches_profile=false if the person in the selfie is clearly "
                            "not the person in the profile photo. Allow for lighting, "
                            "angle, hairstyle, makeup and age differences typical for the "
                            "same person."
                        ),
                    },
                    {"role": "user", "content": content},
                ],
                temperature=0.1,
                max_tokens=150,
            ),
            timeout=_AI_TIMEOUT,
        )
        текст = response.choices[0].message.content.strip()
        try:
            return json.loads(текст)
        except json.JSONDecodeError:
            if "{" in текст and "}" in текст:
                start = текст.index("{")
                end = текст.rindex("}") + 1
                return json.loads(текст[start:end])
            if settings.DEBUG:
                return {"matches_profile": True, "reason": "Parse error (DEBUG)"}
            logger.error("Сверка лица: вердикт не разобран — галочка не выдана (fail-closed)")
            return dict(FACE_MATCH_UNAVAILABLE)
    except Exception as e:
        logger.error(f"AI face match error: {e}")
        from services.alerting import capture_exception
        capture_exception(e)
        if settings.DEBUG:
            return {"matches_profile": True, "reason": "AI unavailable (DEBUG)"}
        return dict(FACE_MATCH_UNAVAILABLE)


#: Вердикт «гейт фото анкеты не состоялся». Та же доктрина fail-closed:
#: без вердикта фото в анкету не попадает, роутер отвечает 503.
PHOTO_GATE_UNAVAILABLE: dict = {
    "face": False,
    "authentic": False,
    "unavailable": True,
    "reason": "photo gate unavailable",
}


async def verify_profile_photo(image_bytes: bytes) -> dict:
    """Жёсткий гейт фото анкеты: на снимке — реальный человек, а не подмена.

    Модерация (`moderate_image`) отвечает на вопрос «нет ли запрещённого», а
    этот гейт — на вопрос «есть ли здесь живой человек»: кот, чёрный фон,
    пейзаж или мем проходят модерацию как «безопасные», но анкете с ними
    в общей выдаче делать нечего.

    Returns: {"face": bool, "authentic": bool, "reason": str}
    (+ "unavailable": True, когда проверка не состоялась).

    * `face` — на фото ЕСТЬ настоящее человеческое лицо, различимое глазом
      (животные, предметы, тёмные кадры, спины и силуэты — false);
    * `authentic` — снимок похож на собственную фотографию, а не на скачанную
      картинку: скриншоты с элементами интерфейса, пересъёмка экрана,
      водяные знаки и логотипы фотостоков, узнаваемые знаменитости,
      сгенерированные лица и рисованные аватары — false.

    Достоверно доказать «скачано из интернета» по одним пикселям нельзя —
    ловятся суррогаты (вотермарки, UI, знаменитости, следы генерации), а
    строгую гарантию «в анкете тот, кто ей владеет» даёт связка живой
    проверки и опорного фото (routers/verification.py, routers/profiles.py).

    Fail-closed, в DEBUG проходит без ключа — как остальные проверки фото.
    """
    client = _get_zhipu_client()
    if not client:
        if settings.DEBUG:
            logger.warning("Гейт фото анкеты не настроен — фото пропущено (DEBUG)")
            return {"face": True, "authentic": True, "reason": "AI not configured (DEBUG)"}
        logger.error(
            "Гейт фото анкеты недоступен (нет ZHIPU_API_KEY) — фото отклонено (fail-closed)"
        )
        return dict(PHOTO_GATE_UNAVAILABLE)

    try:
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        response = await asyncio.wait_for(
            asyncio.to_thread(
                client.chat.completions.create,
                model="glm-4v-flash",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a strict profile photo gate for a dating app. "
                            "Every profile photo must show the real person who owns "
                            "the profile. Respond with JSON only:\n"
                            '{"face": true/false, "authentic": true/false, '
                            '"reason": "brief explanation"}\n'
                            "face=true ONLY if the image clearly shows a real human "
                            "face, recognizable enough to identify the person. "
                            "face=false for: animals, objects, landscapes, memes, "
                            "black/solid backgrounds, text images, cartoons, body "
                            "parts without a face, backs of heads, silhouettes, or "
                            "faces too small/dark/blurry to recognize.\n"
                            "authentic=false if the photo looks downloaded or fake "
                            "rather than the user's own: a screenshot with UI "
                            "elements (status bars, buttons, watermarks, captions), "
                            "a photo of a screen or printed page, a stock photo or "
                            "magazine scan, a recognizable celebrity or public "
                            "figure, an AI-generated face, a drawing or heavily "
                            "filtered/beautified image where the real face is not "
                            "recognizable.\n"
                            "Ordinary selfies and portraits taken with a phone are "
                            "both face=true and authentic=true, including group "
                            "photos where at least one face is clearly visible."
                        ),
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                            {"type": "text", "text": "Gate this dating profile photo."},
                        ],
                    },
                ],
                temperature=0.1,
                max_tokens=200,
            ),
            timeout=_AI_TIMEOUT,
        )
        текст = response.choices[0].message.content.strip()
        try:
            return json.loads(текст)
        except json.JSONDecodeError:
            if "{" in текст and "}" in текст:
                start = текст.index("{")
                end = текст.rindex("}") + 1
                return json.loads(текст[start:end])
            if settings.DEBUG:
                return {"face": True, "authentic": True, "reason": "Parse error (DEBUG)"}
            logger.error("Гейт фото анкеты: вердикт не разобран — фото отклонено (fail-closed)")
            return dict(PHOTO_GATE_UNAVAILABLE)
    except Exception as e:
        logger.error(f"AI photo gate error: {e}")
        from services.alerting import capture_exception
        capture_exception(e)
        if settings.DEBUG:
            return {"face": True, "authentic": True, "reason": "AI unavailable (DEBUG)"}
        return dict(PHOTO_GATE_UNAVAILABLE)


#: Вердикт «проверка присутствия человека на фото не состоялась».
PERSON_MATCH_UNAVAILABLE: dict = {
    "present": False,
    "unavailable": True,
    "reason": "person match unavailable",
}


async def verify_person_in_photo(person: bytes, photo: bytes) -> dict:
    """Есть ли человек с опорного фото на другом снимке анкеты.

    Нужна в двух местах: при верификации остальные фото анкеты сверяются с
    первым (иначе галочку получала бы анкета, где первым стоит своё фото, а
    дальше — чужие), и при добавлении фото в подтверждённую анкету — новые
    снимки сверяются с опорным (routers/profiles.py).

    Вопрос — «присутствует ли», а не «портрет ли»: на фото из анкеты человек
    может быть в компании, и это нормально. false — только когда владельца
    на снимке нет вовсе.

    Returns: {"present": bool, "reason": str}
    (+ "unavailable": True, когда сверка не состоялась). Fail-closed,
    в DEBUG проходит без ключа. Оба изображения живут только в памяти вызова.
    """
    client = _get_zhipu_client()
    if not client:
        if settings.DEBUG:
            logger.warning("Сверка присутствия не настроена — засчитана (DEBUG)")
            return {"present": True, "reason": "AI not configured (DEBUG)"}
        logger.error(
            "Сверка присутствия недоступна (нет ZHIPU_API_KEY) — фото отклонено (fail-closed)"
        )
        return dict(PERSON_MATCH_UNAVAILABLE)

    try:
        content: list[dict] = []
        for изображение in (person, photo):
            b64 = base64.b64encode(изображение).decode("utf-8")
            content.append(
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
            )
        content.append({
            "type": "text",
            "text": (
                "The first image shows the verified profile owner. Does this "
                "person appear in the second image?"
            ),
        })

        response = await asyncio.wait_for(
            asyncio.to_thread(
                client.chat.completions.create,
                model="glm-4v-flash",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are an identity verification AI for a dating app. "
                            "You receive TWO images: the first shows the verified "
                            "owner of a profile, the second is a photo the owner "
                            "wants in that profile. Respond with JSON only:\n"
                            '{"present": true/false, "reason": "brief explanation"}\n'
                            "present=true if the person from the first image appears "
                            "in the second image — alone or among other people. "
                            "Allow for lighting, angle, hairstyle, makeup, glasses "
                            "and age differences typical for the same person.\n"
                            "present=false ONLY if the person from the first image "
                            "is clearly absent from the second image (it shows only "
                            "other people, or no identifiable people at all)."
                        ),
                    },
                    {"role": "user", "content": content},
                ],
                temperature=0.1,
                max_tokens=150,
            ),
            timeout=_AI_TIMEOUT,
        )
        текст = response.choices[0].message.content.strip()
        try:
            return json.loads(текст)
        except json.JSONDecodeError:
            if "{" in текст and "}" in текст:
                start = текст.index("{")
                end = текст.rindex("}") + 1
                return json.loads(текст[start:end])
            if settings.DEBUG:
                return {"present": True, "reason": "Parse error (DEBUG)"}
            logger.error("Сверка присутствия: вердикт не разобран — фото отклонено (fail-closed)")
            return dict(PERSON_MATCH_UNAVAILABLE)
    except Exception as e:
        logger.error(f"AI person match error: {e}")
        from services.alerting import capture_exception
        capture_exception(e)
        if settings.DEBUG:
            return {"present": True, "reason": "AI unavailable (DEBUG)"}
        return dict(PERSON_MATCH_UNAVAILABLE)


#: Словарь запасного фильтра, по категориям (см. TEXT_CATEGORIES).
#: «самоубийств» — сознательно "text", а не "heavy": за словом чаще кризис,
#: чем нарушение, и человеку в кризисе быстрый бан — худший из ответов.
_KEYWORD_CATEGORIES = {
    "heavy": (
        "escort", "проститут", "секс за деньги", "наркотик", "оружие", "убить",
    ),
    "text": ("самоубийств",),
    # Только однозначные маркеры увода аудитории: словарь работает вслепую,
    # без контекста, и «инста»/«телега»/@ здесь ловили бы обычную речь.
    "ad": (
        "t.me/", "telegram.me/", "http://", "https://", "www.",
        "wa.me/", "промокод", "подпишись на",
    ),
}


def _keyword_filter(text: str) -> dict:
    """Simple fallback keyword filter when AI is unavailable."""
    text_lower = text.lower()
    for category, words in _KEYWORD_CATEGORIES.items():
        for word in words:
            if word in text_lower:
                return {
                    "safe": False,
                    "blocked": True,
                    "category": category,
                    "reason": f"Prohibited content: {word}",
                }
    return {"safe": True, "blocked": False, "category": "", "reason": ""}


async def log_moderation(
    user_id: str,
    content_type: str,
    content: str,
    verdict: dict,
) -> None:
    """Записать вердикт модерации в журнал для админки.

    Журнал — единственный способ разобрать спорную блокировку постфактум,
    поэтому пишем и безопасные проверки тоже.

    Пишем в СВОЕЙ сессии, а не в сессии запроса: при блокировке роутер бросает
    HTTPException, зависимость делает rollback — и запись о самом интересном
    случае исчезла бы вместе с ним. Сбой записи журнала не должен ломать
    сценарий: пользователь не виноват, что журнал недоступен.

    Сессия — из журнального пула (log_session_factory), не из общего:
    вторая сессия из общего пула при удерживаемой первой самоблокирует
    пул под залпом — все соединения розданы, и каждый обработчик ждёт
    второе соединение, которое никто не отдаст.
    """
    from database.connection import log_session_factory
    from models.models import AiModerationLog

    result = "blocked" if verdict.get("blocked") else ("safe" if verdict.get("safe", True) else "warning")
    try:
        async with log_session_factory()() as session:
            session.add(
                AiModerationLog(
                    user_id=user_id,
                    content_type=content_type,
                    # Длинные тексты режем: журналу нужен повод, а не весь контент
                    content=(content or "")[:2000],
                    result=result,
                    action="none",
                    # Категория нужна страйкам (enforcement.text_strike_count
                    # считает нарушения по ней), у фото-вердиктов её нет — ""
                    category=verdict.get("category", "") or "",
                    reason=verdict.get("reason", "") or "",
                )
            )
            await session.commit()
    except Exception as e:
        logger.error(f"Не удалось записать лог модерации: {e}")
