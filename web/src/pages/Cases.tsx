/**
 * Кейсы — оформление анкеты, а не расходники.
 *
 * Три кейса, у каждого свой набор наклеек: «Керопи», «Star Rail», «Хеллоуин».
 * Из кейса выпадает наклейка его набора — сначала те, которых ещё нет, — а с
 * небольшим шансом обложка анкеты. Ничего сгораемого: раньше отсюда падали
 * суперлайки и минуты буста, их тратили и забывали, и повода вернуться к
 * кейсу не оставалось. Наклейка остаётся навсегда и ложится значком на фото
 * в анкете — как оформление профиля в Discord. Поэтому кейс стал витриной
 * внешнего вида, а не лотереей полезностей.
 *
 * Шансы редкостей показаны на каждой плитке. Скрытые шансы — ровно то, за что
 * гача-механики и не любят, а честные превращают кейс из ловушки в понятный
 * бонус.
 */

import { useCallback, useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Check, Gift, Lock, Sparkles } from "lucide-react";
import { Link } from "react-router-dom";
import {
  getCaseState,
  openCase,
  selectDecor,
  selectSticker,
  type CaseDef,
  type CaseOpenResult,
  type CaseState,
} from "../lib/api";
import { decorPreviewShadow } from "../lib/decor";
import { haptic } from "../lib/haptics";
import { useSectionOpen } from "../lib/useSectionOpen";
import { Button, Card, LoadError, ScreenHeader, Skeleton, Spinner } from "../components/ui";
import StickerCollection, { РедкостьПодпись } from "../components/StickerCollection";
import DecorPicker from "../components/DecorPicker";

/** От ценного к частому: так шансы читаются как «что искать», а не как список. */
const ПОРЯДОК_РЕДКОСТЕЙ = ["legend", "epic", "rare", "common"];
const ИМЯ_РЕДКОСТИ: Record<string, string> = {
  common: "обычные",
  rare: "редкие",
  epic: "эпические",
  legend: "легендарные",
};

interface Выигрыш {
  кейс: CaseDef | null;
  result: CaseOpenResult;
}

export default function Cases() {
  // Кисточка на лице анкеты ведёт сюда с #decor: докручиваем до обложек,
  // когда витрина уже смонтирована
  useEffect(() => {
    if (window.location.hash !== "#decor") return;
    const t = window.setTimeout(() => {
      document.getElementById("decor")?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 350);
    return () => window.clearTimeout(t);
  }, []);
  useSectionOpen("cases");
  const [state, setState] = useState<CaseState | null>(null);
  //: Код открываемого кейса. Один за раз: попытки общие, и две плитки
  //: одновременно означали бы гонку за последнюю попытку.
  const [busy, setBusy] = useState<string | null>(null);
  const [won, setWon] = useState<Выигрыш | null>(null);
  const [надеваю, setНадеваю] = useState(false);
  const [надето, setНадето] = useState(false);
  const [error, setError] = useState("");
  const [сбой, setСбой] = useState(false);
  //: Растёт после каждого дропа — коллекция ниже перечитывается без
  //: перемонтирования. Обложки отдельно: их витрина грузится сама и редко.
  const [версия, setВерсия] = useState(0);
  const [версияОбложек, setВерсияОбложек] = useState(0);

  const загрузить = useCallback(() => {
    setСбой(false);
    setState(null);
    getCaseState()
      // Кривой ответ (прокси отдала HTML с кодом 200, поле потерялось) — тот же
      // экран сбоя с повтором, а не падение рендера на `cases.map`
      .then((s) => (Array.isArray(s?.cases) && Array.isArray(s?.rewards) ? setState(s) : setСбой(true)))
      // Ошибка первой загрузки раньше писалась в error, который рендерится
      // только внутри загруженного экрана — скелетоны висели вечно
      .catch(() => setСбой(true));
  }, []);

  useEffect(загрузить, [загрузить]);

  const open = useCallback(
    async (код: string) => {
      if (busy) return;
      setBusy(код);
      setError("");
      setWon(null);
      setНадето(false);
      try {
        const result = await openCase(код);
        haptic("success");
        const кодКейса = result.case || код;
        setWon({ кейс: state?.cases.find((к) => к.code === кодКейса) ?? null, result });
        setState((cur) =>
          cur
            ? {
                ...cur,
                left: result.left,
                per_month: result.per_month,
                resets_at: result.resets_at ?? cur.resets_at,
                // Прогресс плитки растёт сразу, не дожидаясь перечитывания:
                // новая наклейка набора — плюс один к собранному
                cases: cur.cases.map((к) =>
                  к.code === кодКейса && result.reward.sticker && !result.duplicate
                    ? { ...к, owned: Math.min(к.total, к.owned + 1) }
                    : к
                ),
              }
            : cur
        );
        setВерсия((v) => v + 1);
        if (result.reward.decor) setВерсияОбложек((v) => v + 1);
      } catch (e: any) {
        haptic("error");
        setError(e?.response?.data?.detail ?? "Не удалось открыть кейс");
      } finally {
        setBusy(null);
      }
    },
    [busy, state]
  );

  /** Надеть выпавшее сразу, не ища его в коллекции: дроп → анкета в один тап. */
  const надеть = useCallback(async () => {
    if (!won || надеваю || надето) return;
    const { sticker, decor } = won.result.reward;
    if (!sticker && !decor) return;
    setНадеваю(true);
    setError("");
    try {
      if (sticker) await selectSticker(sticker.code);
      else if (decor) await selectDecor(decor.code);
      haptic("success");
      setНадето(true);
      setВерсия((v) => v + 1);
      if (decor) setВерсияОбложек((v) => v + 1);
    } catch (e: any) {
      haptic("error");
      setError(e?.response?.data?.detail ?? "Не удалось надеть");
    } finally {
      setНадеваю(false);
    }
  }, [won, надеваю, надето]);

  if (!state) {
    return (
      <div>
        <ScreenHeader title="Кейсы" />
        {сбой ? (
          <LoadError onRetry={загрузить} />
        ) : (
          <div className="px-4 pt-4 flex flex-col gap-3">
            <Skeleton className="h-20 rounded-[var(--radius-tile)]" />
            <Skeleton className="h-44 rounded-[var(--radius-card)]" />
            <Skeleton className="h-44 rounded-[var(--radius-card)]" />
            <Skeleton className="h-44 rounded-[var(--radius-card)]" />
          </div>
        )}
      </div>
    );
  }

  const платно = state.per_month === 0;
  // Доля обложки — единственное, что не зависит от набора: она общая на все
  // кейсы. Показываем её последним чипом на самой плитке, а не отдельной
  // таблицей внизу: две таблицы процентов на одном экране человек пытается
  // перемножить, и обе оказываются про разное.
  const доляОбложки =
    state.rewards.find((r) => r.code === "decor")?.chance_percent ?? 0;
  const награда = won?.result.reward;
  const можноНадеть = Boolean(награда?.sticker || награда?.decor);

  return (
    <div className="pb-6">
      <ScreenHeader title="Кейсы" />

      <div className="px-4 pt-3">
        {/* ── Попытки: одна квота на все кейсы ─────────────────────── */}
        <Card className="p-4 mb-4">
          <div className="flex items-center gap-3">
            <motion.div
              animate={busy ? { rotate: [0, -8, 8, -8, 0] } : { rotate: 0 }}
              transition={{ duration: 0.5, repeat: busy ? Infinity : 0 }}
              className="inline-flex items-center justify-center w-12 h-12 shrink-0
                         rounded-full bg-accent/15"
            >
              <Gift size={22} className="text-accent" />
            </motion.div>
            <div className="flex-1 min-w-0">
              <p className="text-[17px] font-extrabold leading-tight">
                Попыток: {state.left}
              </p>
              <p className="text-caption text-text-muted">
                {платно
                  ? `Попытки даются с подпиской${state.required_tier_name ? ` ${state.required_tier_name}` : ""}`
                  : `${state.per_month} ${plural(state.per_month, "попытка", "попытки", "попыток")} в месяц на вашем уровне, общие на все кейсы` +
                    (state.left === 0 && state.resets_at
                      ? ` · обновятся ${когда(state.resets_at)}`
                      : "")}
              </p>
            </div>
          </div>

          {платно && (
            <Link to="/plans" onClick={() => haptic("light")} className="block mt-3">
              <Button size="md" fullWidth>
                Оформить подписку
              </Button>
            </Link>
          )}
        </Card>

        {/* ── Выигрыш: на месте, без модалки, с кнопкой «Надеть» ───── */}
        <AnimatePresence mode="wait">
          {won && награда ? (
            <motion.div
              key={`${награда.code}-${награда.sticker?.code ?? награда.decor?.code ?? ""}`}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              role="status"
              className="mb-4 px-4 py-3 rounded-[var(--radius-tile)]
                         bg-success/12 border border-success/30"
            >
              <div className="flex items-center gap-3">
                {награда.sticker ? (
                  <motion.img
                    initial={{ scale: 0.5, rotate: -18 }}
                    animate={{ scale: 1, rotate: -6 }}
                    transition={{ type: "spring", stiffness: 340, damping: 16 }}
                    src={награда.sticker.image}
                    alt=""
                    className="w-16 h-16 shrink-0 object-contain
                               drop-shadow-[0_3px_8px_rgba(0,0,0,.45)]"
                  />
                ) : награда.decor ? (
                  <motion.div
                    aria-hidden="true"
                    initial={{ scale: 0.6 }}
                    animate={{ scale: 1 }}
                    transition={{ type: "spring", stiffness: 340, damping: 16 }}
                    className="w-12 h-16 shrink-0 rounded-[10px]"
                    style={{
                      background: "var(--gradient-placeholder)",
                      boxShadow: decorPreviewShadow(награда.decor.code),
                    }}
                  />
                ) : null}
                <div className="min-w-0 flex-1">
                  <p className="text-[15px] font-bold">
                    Выпало: {награда.sticker?.title ?? награда.decor?.title ?? награда.title}
                  </p>
                  <p className="text-caption text-text-muted">
                    {won.кейс ? `Кейс «${won.кейс.title}» · ` : ""}
                    {награда.sticker ? (
                      won.result.duplicate ? (
                        "такая уже есть — повтор отмечен в коллекции"
                      ) : (
                        <>
                          новая в коллекции ·{" "}
                          <РедкостьПодпись
                            rarity={награда.sticker.rarity}
                            title={награда.sticker.rarity_title}
                          />
                        </>
                      )
                    ) : награда.decor ? (
                      won.result.duplicate ? (
                        "такая обложка уже есть"
                      ) : (
                        <>
                          обложка анкеты ·{" "}
                          <РедкостьПодпись
                            rarity={награда.decor.rarity}
                            title={награда.decor.rarity_title}
                          />
                        </>
                      )
                    ) : null}
                  </p>
                </div>
                {можноНадеть && (
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={надеваю || надето}
                    onClick={надеть}
                    className="shrink-0"
                  >
                    {надеваю ? (
                      <Spinner size={16} />
                    ) : надето ? (
                      <span className="inline-flex items-center gap-1">
                        <Check size={14} strokeWidth={3} />
                        Надето
                      </span>
                    ) : (
                      "Надеть"
                    )}
                  </Button>
                )}
              </div>
            </motion.div>
          ) : null}
        </AnimatePresence>

        {error && (
          <p role="alert" className="mb-4 px-1 text-[13px] text-danger">
            {error}
          </p>
        )}

        {/* ── Витрина кейсов ────────────────────────────────────────── */}
        <div className="flex flex-col gap-3">
          {state.cases.map((к) => (
            <ПлиткаКейса
              key={к.code}
              кейс={к}
              обложка={доляОбложки}
              открываю={busy === к.code}
              заблокировано={busy !== null || state.left === 0}
              платно={платно}
              onOpen={() => open(к.code)}
            />
          ))}
        </div>

      </div>

      {/* Коллекция под витриной: сначала «что можно выиграть», потом
          «что уже собрано» — в этом порядке человек и думает */}
      <div className="mt-6">
        <StickerCollection версия={версия} />
      </div>

      {/* Обложка — награда за коллекцию, поэтому строго под ней */}
      <div className="mt-2 px-4">
        <DecorPicker key={версияОбложек} />
      </div>
    </div>
  );
}

function ПлиткаКейса({
  кейс,
  обложка,
  открываю,
  заблокировано,
  платно,
  onOpen,
}: {
  кейс: CaseDef;
  /** Доля открытий, дающих обложку анкеты, в процентах. Общая на все кейсы,
      поэтому приходит с экрана, а не из плитки. */
  обложка: number;
  открываю: boolean;
  заблокировано: boolean;
  платно: boolean;
  onOpen: () => void;
}) {
  const собрано = кейс.total > 0 && кейс.owned >= кейс.total;
  //: Цвет свечения приходит с сервера. Новый кейс не должен требовать
  //: выкладки клиента, а неверный цвет — ломать плитку: CSS просто
  //: проигнорирует невалидный градиент, и останется ровное стекло.
  //: Инлайновый backgroundImage замещает блик стекла свечением кейса,
  //: заливка, блюр и обводка остаются от glass.
  const акцент = /^#[0-9a-f]{6}$/i.test(кейс.accent) ? кейс.accent : "";
  const шансы = ПОРЯДОК_РЕДКОСТЕЙ.filter(
    (r) => кейс.rarity_chances?.[r] != null,
  ).map((r) => [r, кейс.rarity_chances[r]] as const);

  return (
    <section
      aria-label={`Кейс «${кейс.title}»`}
      className="relative overflow-hidden rounded-[var(--radius-card)] glass p-4"
      style={
        акцент
          ? {
              backgroundImage: `radial-gradient(120% 90% at 100% 0%, ${акцент}33, transparent 62%)`,
              boxShadow: `inset 0 0 0 1px ${акцент}2e`,
            }
          : undefined
      }
    >
      <div className="flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <p className="text-[17px] font-extrabold leading-tight">{кейс.title}</p>
          <p className="text-[12.5px] text-text-muted mt-0.5">{кейс.hint}</p>
          <p className="mt-1.5 text-[12px] text-text-muted tabular-nums">
            {собрано
              ? "Набор собран — дальше выпадают обложки, потом повторы"
              : `Собрано ${кейс.owned} из ${кейс.total}`}
          </p>
        </div>

        {/* Веер персонажей — самые ценные из набора: приманка честная,
            именно они и выпадают, только реже */}
        {кейс.preview.length > 0 && (
          <div className="flex -space-x-3 shrink-0 pt-0.5" aria-hidden="true">
            {кейс.preview.slice(0, 4).map((src, i) => (
              <img
                key={src}
                src={src}
                alt=""
                loading="lazy"
                className="w-11 h-11 object-contain drop-shadow-[0_2px_6px_rgba(0,0,0,.45)]"
                style={{ transform: `rotate(${(i - 1.5) * 8}deg)` }}
              />
            ))}
          </div>
        )}
      </div>

      {/* Шкала набора: у плитки должно быть своё число, а не только общее
          «что выпадает» внизу страницы. Заполнение красим акцентом кейса —
          тем же, что и его свечение. */}
      {кейс.total > 0 && (
        <div
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={кейс.total}
          aria-valuenow={кейс.owned}
          aria-label={`Собрано ${кейс.owned} из ${кейс.total}`}
          className="mt-2.5 h-[5px] rounded-full bg-surface-3 overflow-hidden"
        >
          <div
            className="h-full rounded-full transition-[width] duration-500"
            style={{
              width: `${Math.min(100, Math.round((кейс.owned / кейс.total) * 100))}%`,
              background: акцент || "var(--color-accent)",
            }}
          />
        </div>
      )}

      {/* Доли редкостей — у каждого набора свои: сервер нормирует веса по
          фактическому составу, и в наборе без легендарных строки легендарных
          не будет. Одной таблицей на страницу это не сводится.

          Проценты абсолютные и в сумме с обложкой дают 100: это полный ответ
          на «что мне выпадет из этого кейса», а не половина ответа, которую
          пришлось бы домножать на вторую половину с другого конца экрана. */}
      {шансы.length > 0 && (
        <div className="mt-2.5 flex flex-wrap gap-1.5">
          {шансы.map(([r, доля]) => (
            <span
              key={r}
              className="px-2 py-0.5 chip text-[11px] font-semibold tabular-nums"
            >
              <РедкостьПодпись rarity={r} title={ИМЯ_РЕДКОСТИ[r] ?? r} /> · {доля}%
            </span>
          ))}
          {обложка > 0 && (
            <span className="px-2 py-0.5 chip text-[11px] font-semibold tabular-nums">
              {/* Обложка — не редкость, а другой предмет, поэтому набрана не
                  цветом редкости, а обычными чернилами с искрой: text-warn
                  здесь читался как ещё одна «легендарная» — у легенды ровно
                  этот же токен. */}
              <span className="inline-flex items-center gap-1 text-text">
                <Sparkles size={10} strokeWidth={2.5} className="text-accent" />
                обложка
              </span>{" "}
              · {обложка}%
            </span>
          )}
        </div>
      )}

      {платно ? (
        <p className="mt-3 flex items-center gap-1.5 text-[12.5px] text-text-muted">
          <Lock size={13} className="shrink-0" />
          Открывается с подпиской
        </p>
      ) : (
        <Button
          /* Собранный набор больше ничего не обещает — дальше только обложки
             и повторы. Кричать главным акцентом ему уже не за что. */
          variant={собрано ? "secondary" : "primary"}
          size="md"
          fullWidth
          className="mt-3"
          disabled={заблокировано}
          onClick={onOpen}
          aria-label={`Открыть кейс «${кейс.title}»`}
        >
          {открываю ? (
            <Spinner size={20} />
          ) : заблокировано && !открываю ? (
            "Попытки закончились"
          ) : (
            "Открыть"
          )}
        </Button>
      )}
    </section>
  );
}

function plural(n: number, one: string, few: string, many: string): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return one;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
  return many;
}

/** «1 сентября» — дата без года и времени: квота обновляется в начале месяца.
 *
 *  Показываем только когда попытки кончились: до этого дата отвлекает от
 *  кнопки, а после — единственное, что человек хочет знать. */
function когда(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "в начале месяца";
  return d.toLocaleDateString("ru-RU", { day: "numeric", month: "long" });
}
