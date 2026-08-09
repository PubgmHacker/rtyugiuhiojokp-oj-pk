/**
 * Витрина тарифов: уровень, срок, покупка.
 *
 * Цены приходят с сервера (`/iap/plans`) — держать их в клиенте значило бы
 * однажды показать одну цену, а списать другую.
 *
 * Покупать можно только в нативной сборке: Apple запрещает вести к внешней
 * оплате из приложения (Guideline 3.1.1). В вебе и в Telegram Mini App ведём
 * в бота, где работают Stars и CryptoBot.
 */

import { useCallback, useEffect, useState } from "react";
import { Check, Crown, Gem, RotateCcw, Sparkles } from "lucide-react";
import { getMyProfile, getPlans, type PlanOut, type PlansOut } from "../lib/api";
import { haptic } from "../lib/haptics";
import { isNative, openExternal } from "../lib/native";
import {
  isPurchaseAvailable,
  purchasePremium,
  restorePurchases,
} from "../lib/iap";
import { useStore } from "../lib/store";
import { Button, Card, ScreenHeader, Skeleton, Spinner } from "../components/ui";

const BOT_USERNAME = import.meta.env.VITE_BOT_USERNAME || "souldawn_dating_bot";

/** Уровни в порядке старшинства; бесплатный в витрине покупать нечего.
 *
 *  Порядок и состав должны совпадать с `TIER_ORDER` в api/services/plans.py.
 *  Сами уровни приходят с сервера — здесь только порядок показа. */
const PAID_TIERS = ["plus", "ultra", "aurora"] as const;

export default function Plans() {
  const { user, setUser } = useStore();
  const [data, setData] = useState<PlansOut | null>(null);
  const [tier, setTier] = useState<string>("plus");
  const [canBuy, setCanBuy] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState("");

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        const plans = await getPlans();
        if (cancelled) return;
        setData(plans);
        // Уже подписанному показываем его уровень, а не младший. Проверяем по
        // списку, а не сравнением с "ultra": пока здесь стояло одно имя, Aurora
        // открывалась на вкладке Plus — верхний тариф выглядел как «не куплен».
        if ((PAID_TIERS as readonly string[]).includes(plans.current_tier)) {
          setTier(plans.current_tier);
        }
      } catch {
        if (!cancelled) setMessage("Не удалось загрузить тарифы");
      }
      if (isNative()) {
        const available = await isPurchaseAvailable();
        if (!cancelled) setCanBuy(available);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  const handle = useCallback(
    async (action: () => Promise<any>, key: string) => {
      haptic("light");
      setBusy(key);
      setMessage("");
      const result = await action();
      setBusy(null);

      if (result.status === "success") {
        haptic("success");
        // Уровень изменился — перечитываем профиль: от него зависят гейты.
        // Обнулять пользователя нельзя, это выбросило бы на онбординг
        try {
          setUser(await getMyProfile());
          setData(await getPlans());
        } catch {
          /* профиль подтянется при следующем открытии */
        }
        setMessage("Готово! Подписка активна");
        return;
      }
      if (result.status === "cancelled") return;
      if (result.status === "pending") {
        setMessage("Покупка ожидает подтверждения — доступ откроется автоматически");
        return;
      }
      haptic("warning");
      setMessage(result.message);
    },
    [setUser]
  );

  if (!data) {
    return (
      <div className="pb-4">
        <ScreenHeader title="Подписка" />
        <div className="px-4 flex flex-col gap-3">
          <Skeleton className="h-12 rounded-full" />
          <Skeleton className="h-40 rounded-[var(--radius-tile)]" />
          <Skeleton className="h-40 rounded-[var(--radius-tile)]" />
        </div>
      </div>
    );
  }

  const shown = data.tiers.find((t) => t.tier === tier);
  const current = data.current_tier;

  return (
    <div className="pb-6">
      <ScreenHeader title="Подписка" />

      <div className="px-4">
        {current !== "free" && (
          <p className="mb-4 px-3.5 py-2.5 rounded-[var(--radius-tile)]
                        bg-success/12 border border-success/30 text-[13px]">
            У вас активен{" "}
            <span className="font-bold">
              {data.tiers.find((t) => t.tier === current)?.name ?? current}
            </span>
          </p>
        )}

        {/* Переключатель уровней */}
        <div className="flex p-1 mb-5 rounded-full bg-surface-2 border border-hairline">
          {PAID_TIERS.map((t) => {
            const info = data.tiers.find((x) => x.tier === t);
            if (!info) return null;
            const active = tier === t;
            return (
              <button
                key={t}
                onClick={() => {
                  haptic("select");
                  setTier(t);
                }}
                aria-pressed={active}
                className={`flex-1 py-2.5 rounded-full text-[15px] font-bold
                            transition-colors ${
                              active
                                ? "bg-dawn text-white"
                                : "text-text-secondary"
                            }`}
              >
                {info.name}
              </button>
            );
          })}
        </div>

        {shown && (
          <>
            <Card className="p-4 mb-5">
              <div className="flex items-center gap-2.5 mb-3">
                <TierIcon tier={shown.tier} />
                <span className="font-bold text-[16px]">
                  Souldawn {shown.name}
                </span>
              </div>

              <ul className="flex flex-col gap-2">
                {shown.perks.map((perk) => (
                  <li key={perk} className="flex items-start gap-2.5 text-[14.5px]">
                    <Check size={16} className="text-success shrink-0 mt-0.5" />
                    {perk}
                  </li>
                ))}
              </ul>
            </Card>

            <div className="flex flex-col gap-2.5 mb-4">
              {shown.plans.map((plan) => (
                <PlanRow
                  key={plan.code}
                  plan={plan}
                  monthly={shown.plans.find((p) => p.months === 1)?.price_rub}
                  busy={busy === plan.code}
                  disabled={busy !== null}
                  onBuy={() => {
                    if (!isNative()) {
                      haptic("light");
                      openExternal(
                        `https://t.me/${BOT_USERNAME}?start=premium`
                      );
                      return;
                    }
                    if (!canBuy || !plan.appstore_id) {
                      setMessage("Покупка в приложении сейчас недоступна");
                      return;
                    }
                    handle(
                      () => purchasePremium(plan.appstore_id, user?.id ?? ""),
                      plan.code
                    );
                  }}
                />
              ))}
            </div>

            {/* Обязательный пункт для ревью: сменивший устройство должен
                вернуть оплаченное без повторной оплаты */}
            {isNative() && canBuy && (
              <Button
                variant="secondary"
                size="md"
                fullWidth
                disabled={busy !== null}
                onClick={() => handle(restorePurchases, "restore")}
              >
                {busy === "restore" ? (
                  <Spinner size={16} />
                ) : (
                  <>
                    <RotateCcw size={16} />
                    Восстановить покупки
                  </>
                )}
              </Button>
            )}
          </>
        )}

        {message && (
          <p className="text-caption text-text-muted mt-4 text-center">{message}</p>
        )}

        <p className="text-[12px] text-text-faint mt-5 leading-snug">
          Подписка продлевается автоматически, отменить можно в настройках
          {isNative() ? " Apple ID" : " бота"} в любой момент.
        </p>
      </div>
    </div>
  );
}

/* ── Значок уровня ──────────────────────────────────────────── */

/** Раньше значок выбирался условием «Ultra или иначе Plus»: с появлением
 *  третьего уровня Aurora молча получила бы чужой значок. Незнакомому уровню
 *  даём нейтральный, а не значок соседа. */
function TierIcon({ tier }: { tier: string }) {
  if (tier === "aurora") return <Gem size={18} className="text-accent" />;
  if (tier === "ultra") return <Crown size={18} className="text-accent" />;
  return <Sparkles size={18} className="text-accent" />;
}

/* ── Строка тарифа ──────────────────────────────────────────── */

function PlanRow({
  plan,
  monthly,
  busy,
  disabled,
  onBuy,
}: {
  plan: PlanOut;
  /** Цена месячного варианта — база для расчёта выгоды. */
  monthly?: number;
  busy: boolean;
  disabled: boolean;
  onBuy: () => void;
}) {
  // Выгоду показываем явно: без неё «2590 ₽» читается просто как «дороже»
  const saving =
    monthly && plan.months > 1
      ? Math.round(100 - (plan.price_per_month * 100) / monthly)
      : 0;

  return (
    <button
      onClick={onBuy}
      disabled={disabled}
      className="w-full flex items-center gap-3 px-4 py-3.5 text-left
                 rounded-[var(--radius-tile)] bg-surface-2 border border-hairline
                 disabled:opacity-50 active:scale-[0.99] transition-transform"
    >
      <div className="flex-1 min-w-0">
        <p className="font-bold text-[15px]">{plan.title}</p>
        <p className="text-caption text-text-muted">
          {plan.price_per_month} ₽ в месяц
          {/* Цена за день — на длинных сроках она и продаёт: «4 ₽ в день»
              читается как мелочь, а «1290 ₽» как крупная трата. У месячного
              плана не показываем: там это не выгода, а лишний шум */}
          {plan.months > 1 && ` · ${plan.price_per_day} ₽ в день`}
        </p>
      </div>

      {saving > 0 && (
        <span className="px-2 py-0.5 rounded-full bg-success/15 text-success
                         text-[12px] font-bold shrink-0">
          −{saving}%
        </span>
      )}

      <span className="font-bold text-[16px] shrink-0">
        {busy ? <Spinner size={16} /> : `${plan.price_rub} ₽`}
      </span>
    </button>
  );
}
