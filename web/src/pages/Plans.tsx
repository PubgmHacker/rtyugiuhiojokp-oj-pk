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
import { Check, Crown, Gem, Gift, RotateCcw, Sparkles } from "lucide-react";
import {
  activatePromo,
  getMyProfile,
  getPlans,
  redeemGift,
  type PlanOut,
  type PlansOut,
} from "../lib/api";
import { assertList } from "../lib/payload";
import { haptic } from "../lib/haptics";
import { isNative, openExternal } from "../lib/native";
import {
  isPurchaseAvailable,
  loadProducts,
  purchaseGift,
  purchasePremium,
  restorePurchases,
} from "../lib/iap";
import { useStore } from "../lib/store";
import { Button, Card, LoadError, ScreenHeader, Skeleton, Spinner } from "../components/ui";

const BOT_USERNAME = import.meta.env.VITE_BOT_USERNAME || "simpmatchbot";

/** Уровни в порядке старшинства; бесплатный в витрине покупать нечего.
 *
 *  Порядок и состав должны совпадать с `TIER_ORDER` в api/services/plans.py.
 *  Сами уровни приходят с сервера — здесь только порядок показа. */
const PAID_TIERS = ["plus", "ultra", "aurora"] as const;

/** Рубли по-русски: запятая в дробной части и неразрывный разряд тысяч.
 *
 *  Сервер отдаёт цену за день числом (16.6), и в JSX она печаталась «16.6 ₽» —
 *  точка в дробях читается как опечатка ровно там, где человек решает
 *  платить. Округляем до десятой: вторая цифра после запятой в цене за день
 *  не значит ничего. */
function рубли(n: number): string {
  return n.toLocaleString("ru-RU", { maximumFractionDigits: 1 });
}

export default function Plans() {
  const { user, setUser } = useStore();
  const [data, setData] = useState<PlansOut | null>(null);
  const [tier, setTier] = useState<string>("plus");
  const [canBuy, setCanBuy] = useState(false);
  // Цены App Store по id товара: в нативной сборке показывать надо цену,
  // которую назовёт Apple в валюте региона покупателя, — рубль с сервера
  // там и не спишется, и ревью не пройдёт (Guideline 3.1.1)
  const [storePrices, setStorePrices] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  // Подарок: переключаем режим, а не верим гейту в каждой строке плана
  // — иначе выбрав «подарок» человек не поймёт, что он уже работает, и какой
  // тариф выбран тому, кому он окажется.
  const [gifting, setGifting] = useState(false);
  const [giftCode, setGiftCode] = useState<string | null>(null);
  // Сбой первой загрузки — не message: message рендерится только внутри
  // загруженной витрины, и скелетоны висели бы вечно. Счётчик перезапускает
  // эффект загрузки кнопкой «Повторить».
  const [сбой, setСбой] = useState(false);
  const [попытка, setПопытка] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setСбой(false);

    (async () => {
      try {
        const plans = await getPlans();
        if (cancelled) return;
        assertList(plans.tiers, "iap/plans.tiers");
        setData(plans);
        // Уже подписанному показываем его уровень, а не младший. Проверяем по
        // списку, а не сравнением с "ultra": пока здесь стояло одно имя, Aurora
        // открывалась на вкладке Plus — верхний тариф выглядел как «не куплен».
        if ((PAID_TIERS as readonly string[]).includes(plans.current_tier)) {
          setTier(plans.current_tier);
        }
      } catch {
        if (!cancelled) setСбой(true);
      }
      if (isNative()) {
        const available = await isPurchaseAvailable();
        if (!cancelled) setCanBuy(available);
        if (available) {
          const products = await loadProducts();
          if (!cancelled) {
            setStorePrices(
              Object.fromEntries(products.map((p) => [p.id, p.price]))
            );
          }
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [попытка]);

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
        if (result.giftCode) setGiftCode(result.giftCode);
        setMessage(
          result.giftCode ? "Подарок оформлен — код ниже" : "Готово! Подписка активна"
        );
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
        {сбой ? (
          <LoadError onRetry={() => setПопытка((x) => x + 1)} />
        ) : (
          <div className="px-4 flex flex-col gap-3">
            <Skeleton className="h-12 rounded-full" />
            <Skeleton className="h-40 rounded-[var(--radius-tile)]" />
            <Skeleton className="h-40 rounded-[var(--radius-tile)]" />
          </div>
        )}
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

        {/* Подарок: показываем подарочный код после успешной покупки,
            причём тот самый, что сервер вернул. */}
        {giftCode && (
          <div className="mb-4 p-4 rounded-[var(--radius-tile)] bg-success/12 border border-success/30">
            <p className="font-semibold text-success text-[13px] mb-1">
              Подарочный код для пересылки:
            </p>
            <p className="font-mono text-[17px] tracking-wider break-all">
              {giftCode}
            </p>
            <p className="text-[11.5px] text-text-muted mt-1.5">
              Отправьте его тому, кому хотите подарить Premium
            </p>
          </div>
        )}

        {/* Переключатель уровней */}
        <div className="flex p-1 mb-5 chip">
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
                        ? "bg-accent text-white shadow"
                        : "text-text-secondary"
                    }`}
                  >
                    {info.name}
                  </button>
                );
              })}
            </div>

            {/* Подарок: двухрежимный переключатель в шапке, чтобы человек видел
                его до того, как встанет на тариф. Не в каждой строке плана —
                там он мешает читать цены. */}
            <div className="mb-4 flex items-center justify-between px-1">
              <p className="text-[13px] text-text-muted flex-1 pr-3">
                В подарок — другу, мэтчу, любимому человеку
              </p>
              <button
                onClick={() => {
                  haptic("light");
                  setGifting((v) => !v);
                }}
                aria-pressed={gifting}
                className={`shrink-0 w-10 h-6 rounded-full transition-colors
                           ${gifting ? "bg-accent" : "bg-surface-2"}`}
              >
                <span
                  className={`block w-4 h-4 rounded-full bg-white transition-transform
                             mx-1 ${gifting ? "translate-x-4" : ""}`}
                />
              </button>
            </div>

        {shown && (
          <>
            <Card className="p-4 mb-5">
              <div className="flex items-center gap-2.5 mb-3">
                <TierIcon tier={shown.tier} />
                <span className="font-bold text-[16px]">
                  Симп {shown.name}
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

            {/* Варианты срока — одна стеклянная карта со строками, как стек
                настроек: разделители только между строками, без своих рамок */}
            <div className="glass rounded-[20px] overflow-hidden mb-4">
              {shown.plans.map((plan) => (
                <PlanRow
                  key={plan.code}
                  plan={plan}
                  monthly={shown.plans.find((p) => p.months === 1)?.price_rub}
                  storePrice={
                    canBuy ? storePrices[plan.appstore_id] : undefined
                  }
                  busy={busy === plan.code}
                  disabled={busy !== null}
                  onBuy={() => {
                    // Подарок и покупка себе проходят через один и тот же
                    // товар App Store, но через разные проверки чека:
                    // подарок не начисляет подписку, а выпускает код.
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
                      gifting
                        ? () => purchaseGift(plan.appstore_id, user?.id ?? "")
                        : () => purchasePremium(plan.appstore_id, user?.id ?? ""),
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

        {/* Промокод: из поста, рассылки или от поддержки. Активация — здесь,
            а не в боте: человек уже смотрит на тарифы, уводить его в чат
            ради восьми знаков незачем. */}
        <PromoField
          onActivated={async () => {
            haptic("success");
            // Уровень изменился — перечитываем профиль и витрину: от них
            // зависят гейты и плашка «у вас активен»
            try {
              setUser(await getMyProfile());
              setData(await getPlans());
            } catch {
              /* профиль подтянется при следующем открытии */
            }
          }}
        />

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

/* ── Промокод и подарочный код ──────────────────────────────── */

function PromoField({ onActivated }: { onActivated: () => Promise<void> }) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);

  const submit = async () => {
    const trimmed = code.trim();
    if (!trimmed || busy) return;
    haptic("light");
    setBusy(true);
    setNote(null);
    try {
      const res = await activatePromo(trimmed);
      setCode("");
      setNote({
        ok: true,
        text: `Промокод принят — подписка активна до ${res.expires_at.slice(0, 10)}`,
      });
      await onActivated();
    } catch (e: any) {
      // Поле одно на оба вида кодов: человеку всё равно, из поста его код
      // или от друга. 404 от промо — пробуем ввод как подарочный код, и
      // только двойной промах показывает «нет такого». Каскад тот же, что
      // в боте (bot/handlers/premium.py::promo_code_received).
      if (e?.response?.status === 404) {
        try {
          const gift = await redeemGift(trimmed);
          setCode("");
          setNote({
            ok: true,
            text: `Подарок принят — подписка активна до ${gift.expires_at.slice(0, 10)}`,
          });
          await onActivated();
          return;
        } catch (g: any) {
          haptic("warning");
          setNote({
            ok: false,
            text:
              g?.response?.status === 404
                ? "Такого кода нет — ни промокода, ни подарочного"
                : g?.response?.data?.detail ?? "Не получилось активировать код",
          });
          return;
        }
      }
      haptic("warning");
      // Текст отказа пишет сервер: «уже активировали», «истёк»
      setNote({
        ok: false,
        text: e?.response?.data?.detail ?? "Не получилось активировать промокод",
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-5">
      <p className="text-[13px] text-text-muted mb-2 flex items-center gap-1.5">
        <Gift size={14} className="shrink-0" />
        Есть промокод или подарочный код?
      </p>
      <div className="flex gap-2">
        <input
          value={code}
          onChange={(e) => setCode(e.target.value.toUpperCase())}
          onKeyDown={(e) => {
            if (e.key === "Enter") submit();
          }}
          placeholder="ПРОМОКОД"
          autoCapitalize="characters"
          autoCorrect="off"
          spellCheck={false}
          enterKeyHint="go"
          className="field flex-1 min-w-0 px-3.5 py-2.5 rounded-[var(--radius-tile)] font-mono tracking-wider text-[15px]"
        />
        <Button size="md" disabled={!code.trim() || busy} onClick={submit}>
          {busy ? <Spinner size={16} /> : "Активировать"}
        </Button>
      </div>
      {note && (
        <p
          className={`text-caption mt-2 ${
            note.ok ? "text-success" : "text-danger"
          }`}
          role="status"
        >
          {note.text}
        </p>
      )}
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
  storePrice,
  busy,
  disabled,
  onBuy,
}: {
  plan: PlanOut;
  /** Цена месячного варианта — база для расчёта выгоды. */
  monthly?: number;
  /** Цена App Store в валюте региона покупателя — в нативной сборке
      списывается именно она, и показывать рубли там нельзя: человек видел
      бы одну цену, а платил другую (Guideline 3.1.1). */
  storePrice?: string;
  busy: boolean;
  disabled: boolean;
  onBuy: () => void;
}) {
  // Выгоду показываем явно: без неё «2590 ₽» читается просто как «дороже».
  // Пропорции уровней в App Store повторяют рублёвые, поэтому процент
  // считается по ценам сервера и для нативной сборки.
  const saving =
    monthly && plan.months > 1
      ? Math.round(100 - (plan.price_per_month * 100) / monthly)
      : 0;

  return (
    <button
      onClick={onBuy}
      disabled={disabled}
      className="w-full flex items-center gap-3 px-4 py-3.5 text-left
                 border-t border-[color:var(--glass-divider)] first:border-t-0
                 disabled:opacity-50 active:bg-[color:var(--glass-divider)]
                 transition-colors"
    >
      <div className="flex-1 min-w-0">
        <p className="font-bold text-[15px]">{plan.title}</p>
        {/* С ценой App Store рублёвую раскладку не показываем совсем:
            разложить чужую валюту «в месяц и в день» без парсинга её формата
            нельзя, а срок и так в заголовке, выгода — в бейдже */}
        {/* Цена за день — на длинных сроках она и продаёт: «4 ₽ в день»
            читается как мелочь, а «1290 ₽» как крупная трата. У месячного
            плана раскладки нет совсем: «499 ₽ в месяц» под заголовком
            «1 месяц» повторяло и срок, и то же самое число из колонки цены
            справа — строка не сообщала ничего. Неразрывный пробел перед «₽» —
            чтобы перенос не оставлял строку «17» и строку «₽ в день» */}
        {!storePrice && plan.months > 1 && (
          <p className="text-caption text-text-muted">
            {`${рубли(plan.price_per_month)}\u00A0₽ в месяц`}
            {` · ${рубли(plan.price_per_day)}\u00A0₽ в день`}
          </p>
        )}
      </div>

      {/* Цена и выгода — одной колонкой справа, а не двумя ячейками в строке.
          На 320 px бейдж между текстом и ценой отбирал у названия 61 px, и
          «Aurora на 12 мес.» ломалось на две строки, а раскладка — на три
          (замер: названию нужно 130 px, раскладке 165, оставалось 123).
          Колонка возвращает эти пиксели тексту: под него уходит 184 px,
          обе строки влезают целиком, а цена и процент читаются вместе —
          именно их и сравнивают между сроками */}
      <div className="shrink-0 flex flex-col items-end gap-0.5">
        <span className="font-bold text-[16px]">
          {busy ? <Spinner size={16} /> : (storePrice ?? `${рубли(plan.price_rub)}\u00A0₽`)}
        </span>
        {saving > 0 && (
          <span className="px-2 py-0.5 rounded-full bg-success/15 text-success
                           text-[12px] font-bold">
            −{saving}%
          </span>
        )}
      </div>
    </button>
  );
}
