"""Продукты App Store не расходятся с тарифной линейкой.

Расхождение здесь не ловится ни типами, ни тестами API: `.storekit` читает
только Xcode, а настоящие продукты — только App Store Connect. Пока линейка
переезжала с одного «Premium» на девять продуктов, файл симулятора остался со
старыми `...premium.monthly/.yearly`, и локальная проверка покупки поднимала
товары, которых сервер уже не знает.

Единственный источник правды — `services/plans.PLANS`; сам файл собирается из
неё, а эти тесты стерегут, чтобы его правкой руками не рассинхронизировали.
"""

# ════════════════════════════════════════════════════════════════
#  Витрина StoreKit и линейка тарифов — один и тот же набор
# ════════════════════════════════════════════════════════════════

def test_storekit_повторяет_линейку_один_в_один():
    """Файл симулятора покупок держит ровно те продукты, что в линейке.

    Пока в `.storekit` лежали `...premium.monthly/.yearly`, а линейка
    перешла на девять продуктов plus/ultra/aurora, локальная проверка покупки
    поднимала товары, которых на сервере уже нет: `plan_for_appstore_id`
    вернул бы None, и чек не зачёлся бы вовсе. Расхождение видно только на
    живом устройстве, поэтому сверяем здесь.
    """
    import json
    from pathlib import Path

    from services.plans import PLANS

    путь = Path(__file__).resolve().parents[2] / "web/ios/App/Simp.storekit"
    документ = json.loads(путь.read_text(encoding="utf-8"))

    в_файле = {
        подписка["productID"]
        for группа in документ["subscriptionGroups"]
        for подписка in группа["subscriptions"]
    }
    в_линейке = {p.appstore_id for p in PLANS if p.appstore_id}

    assert в_файле == в_линейке, (
        f"лишние в StoreKit: {sorted(в_файле - в_линейке)}; "
        f"нет в StoreKit: {sorted(в_линейке - в_файле)}"
    )


def test_переход_на_старший_уровень_считается_повышением():
    """`groupNumber` внутри группы: 1 — старший уровень.

    Apple по этому числу решает, менять ли подписку немедленно (повышение)
    или в конце оплаченного периода (понижение). Поставь Aurora номер больше
    Plus — и покупка верхнего уровня ждала бы конца месяца, хотя деньги
    списаны сразу; на сервере `activate_premium` уровень при этом уже поднял
    бы. Порядок в файле должен совпадать с `TIER_ORDER`.
    """
    import json
    from pathlib import Path

    from services.plans import PLANS_BY_APPSTORE_ID, tier_rank

    путь = Path(__file__).resolve().parents[2] / "web/ios/App/Simp.storekit"
    документ = json.loads(путь.read_text(encoding="utf-8"))

    номера: dict[str, set[int]] = {}
    for группа in документ["subscriptionGroups"]:
        for подписка in группа["subscriptions"]:
            план = PLANS_BY_APPSTORE_ID[подписка["productID"]]
            номера.setdefault(план.tier, set()).add(подписка["groupNumber"])

    for уровень, значения in номера.items():
        assert len(значения) == 1, (
            f"{уровень}: разные groupNumber у сроков одного уровня — {значения}"
        )

    по_старшинству = sorted(номера, key=tier_rank, reverse=True)
    номер = [next(iter(номера[t])) for t in по_старшинству]
    assert номер == sorted(номер), (
        f"старший уровень должен иметь меньший groupNumber: {list(zip(по_старшинству, номер))}"
    )


def test_цена_и_название_в_storekit_взяты_из_линейки():
    """Витрина симулятора не расходится с тем, что мы обещаем в мини-аппе."""
    import json
    from pathlib import Path

    from services.plans import PLANS_BY_APPSTORE_ID

    путь = Path(__file__).resolve().parents[2] / "web/ios/App/Simp.storekit"
    документ = json.loads(путь.read_text(encoding="utf-8"))

    for группа in документ["subscriptionGroups"]:
        for подписка in группа["subscriptions"]:
            план = PLANS_BY_APPSTORE_ID[подписка["productID"]]
            assert подписка["displayPrice"] == str(план.price_rub), (
                f"{план.code}: цена в StoreKit {подписка['displayPrice']}, "
                f"в линейке {план.price_rub}"
            )
            имя = подписка["localizations"][0]["displayName"]
            assert имя == план.title, f"{план.code}: «{имя}» вместо «{план.title}»"
