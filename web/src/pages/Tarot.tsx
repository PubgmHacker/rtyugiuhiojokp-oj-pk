/**
 * Раздел Таро — четыре расклада поверх карты дня.
 *
 * Один экран с выбором расклада, а не четыре отдельных страницы: переключение
 * вкладкой дешевле для навигации, чем каждый раз возвращаться в «Ещё».
 *
 * Расклад детерминирован на сервере (см. api/services/tarot_spreads.py) —
 * кнопка «обновить» здесь не нужна и не появится: карты не меняются до
 * следующих суток, поэтому запрашиваем расклад один раз при выборе вкладки.
 *
 * Акцент один на экран — тёплый accent на активной вкладке и в интерпретации,
 * карты рядом нейтральные: разноцветная подсветка на каждой карте отвлекает
 * от текста, который и есть повод для разговора.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import { isAxiosError } from "axios";
import { Crown, Lock, Sparkles } from "lucide-react";
import {
  getTarotDay,
  getTarotPair,
  getTarotRelationship,
  getTarotThree,
  type TarotSpread,
  type TarotSpreadType,
} from "../lib/api";
import { assertList } from "../lib/payload";
import { haptic } from "../lib/haptics";
import { useSectionOpen } from "../lib/useSectionOpen";
import { Button, Card, LoadError, ScreenHeader, Skeleton } from "../components/ui";

const TABS: { type: TarotSpreadType; label: string }[] = [
  { type: "day", label: "Карта дня" },
  { type: "three", label: "Три карты" },
  { type: "relationship", label: "Отношения" },
  { type: "pair", label: "Он и я" },
];

/** Карта дня бесплатна, остальные расклады — по подписке (см. серверный гейт
 *  `tarot_spreads` в api/routers/tarot.py). */
const GATED: Record<TarotSpreadType, boolean> = {
  day: false,
  three: true,
  relationship: true,
  pair: true,
};

/** Достаёт текст отказа из 403: имя нужного тарифа приходит с сервера, чтобы
 *  оно не было зашито в клиенте вторым местом. Не 403 — вернём null. */
function readLock(e: unknown): string | null {
  if (isAxiosError(e) && e.response?.status === 403) {
    const detail = (e.response.data as { detail?: string } | undefined)?.detail;
    return detail || "Развёрнутые расклады доступны по подписке";
  }
  return null;
}

export default function Tarot() {
  useSectionOpen("tarot");
  const [tab, setTab] = useState<TarotSpreadType>("day");
  const [nameA, setNameA] = useState("");
  const [nameB, setNameB] = useState("");
  const [spread, setSpread] = useState<TarotSpread | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  // Про доступ к разворотам узнаём из ответа карты дня (`spreads_open`), а не
  // отдельной пробой закрытого расклада: проба стоила лишнего запроса и, что
  // хуже, роняла карту дня — ответ пробы менял состояние, эффект перезапускался
  // и грузил день второй раз, а карточка успевала мигнуть скелетоном.
  // Замерено: было 2 запроса `/tarot/day` + 1 `/tarot/three` на одно открытие.
  const [spreadsOpen, setSpreadsOpen] = useState<boolean | null>(null);
  const [lockMsg, setLockMsg] = useState("Развёрнутые расклады доступны по подписке");

  // Что уже загрузили: без этой отметки эффект, зависящий от `spreadsOpen`,
  // повторял запрос сразу после того, как доступ выяснился.
  const загружено = useRef<TarotSpreadType | null>(null);

  // «Он и я» просит два имени, поэтому расклад запрашивается по кнопке, а
  // не сразу при переключении вкладки — иначе на пустых именах прилетела бы
  // ошибка валидации до того, как человек успел их ввести.
  const load = useCallback(async (type: TarotSpreadType) => {
    setLoading(true);
    setError("");
    try {
      let result: TarotSpread;
      if (type === "day") result = await getTarotDay();
      else if (type === "three") result = await getTarotThree();
      else if (type === "relationship") result = await getTarotRelationship();
      else result = await getTarotPair(nameA, nameB);
      assertList(result.cards, "tarot.cards");
      setSpread(result);
      // Карта дня бесплатна и приходит всем — из неё же узнаём, открыты ли
      // развороты. У остальных раскладов ответ вообще не придёт, если заперто.
      if (result.spreads_open !== undefined) setSpreadsOpen(result.spreads_open);
      if (result.required_tier_name)
        setLockMsg(`Расклады доступны на ${result.required_tier_name}`);
    } catch (e) {
      // 403 — не ошибка, а апселл: показываем замок с именем тарифа с сервера.
      const lock = readLock(e);
      if (lock) {
        setSpreadsOpen(false);
        setLockMsg(lock);
      } else {
        setError("Не удалось получить расклад");
      }
    } finally {
      setLoading(false);
    }
    // Имена в зависимостях, чтобы load не запомнил их первоначальные пустые
    // значения (со старым `[]` getTarotPair всегда слал ""). Лишних запросов
    // это не даёт: эффект ниже выходит рано и для pair, и по `загружено`.
  }, [nameA, nameB]);

  const locked = GATED[tab] && spreadsOpen === false;

  // Смена вкладки — единственный повод очистить экран. Раньше очистка жила в
  // том же эффекте, что и загрузка, а он перезапускался ещё и когда выяснялся
  // доступ: уже показанная карта дня стиралась.
  useEffect(() => {
    setSpread(null);
    setError("");
    загружено.current = null;
  }, [tab]);

  useEffect(() => {
    if (tab === "pair") return; // ждёт двух имён и кнопки
    // Заперто — расклад не грузим: покажем апселл
    if (GATED[tab] && spreadsOpen === false) return;
    // Про доступ ещё не знаем (карта дня не ответила) — платную вкладку не
    // дёргаем, иначе получим 403 там, где через миг был бы обычный замок
    if (GATED[tab] && spreadsOpen === null) return;
    if (загружено.current === tab) return; // уже грузили — не повторяем
    загружено.current = tab;
    load(tab);
  }, [tab, load, spreadsOpen]);

  return (
    <div className="pb-6">
      <ScreenHeader title="Таро" />

      {/* Полоса прокручивается: на 320px четыре вкладки в ряд не помещаются,
          а перенос на вторую строку съедал бы экран у всех остальных.
          `no-scrollbar` убирает системную полосу — в мини-аппе она выглядит
          как брак вёрстки. Края растворяются маской, чтобы обрезанная вкладка
          читалась как «дальше есть ещё», а не как ошибка. */}
      <div
        className="px-4 pt-2 pb-1 flex gap-2 overflow-x-auto no-scrollbar"
        style={{
          maskImage:
            "linear-gradient(to right, transparent 0, #000 12px, #000 calc(100% - 20px), transparent 100%)",
          WebkitMaskImage:
            "linear-gradient(to right, transparent 0, #000 12px, #000 calc(100% - 20px), transparent 100%)",
        }}
      >
        {TABS.map((t) => (
          <button
            key={t.type}
            onClick={() => {
              haptic("select");
              setTab(t.type);
            }}
            className={`shrink-0 inline-flex items-center gap-1.5 px-3.5 py-2 rounded-full text-[13.5px] font-semibold transition-colors ${
              tab === t.type
                ? "bg-accent text-on-accent"
                : "bg-surface-2 text-text-secondary border border-hairline"
            }`}
          >
            {t.label}
            {GATED[t.type] && spreadsOpen === false && (
              <Lock
                size={12}
                className={tab === t.type ? "opacity-80" : "text-text-muted"}
              />
            )}
          </button>
        ))}
      </div>

      <div className="px-4 pt-3">
        {locked ? (
          <TarotLock message={lockMsg} />
        ) : (
          <>
        {tab === "pair" && (
          <Card className="p-4 mb-3">
            <p className="text-caption text-text-muted mb-2">
              Введите два имени — расклад один на пару имён и на сегодня
            </p>
            <div className="flex flex-col gap-2 mb-3">
              <input
                value={nameA}
                onChange={(e) => setNameA(e.target.value)}
                placeholder="Ваше имя"
                maxLength={60}
                className="field px-3.5 py-2.5 rounded-[var(--radius-tile)] text-[15px]"
              />
              <input
                value={nameB}
                onChange={(e) => setNameB(e.target.value)}
                placeholder="Имя партнёра"
                maxLength={60}
                className="field px-3.5 py-2.5 rounded-[var(--radius-tile)] text-[15px]"
              />
            </div>
            <Button
              size="md"
              fullWidth
              disabled={!nameA.trim() || !nameB.trim() || loading}
              onClick={() => load("pair")}
            >
              Разложить карты
            </Button>
          </Card>
        )}

        {loading && (
          <div className="flex flex-col gap-2">
            <Skeleton className="h-24" />
            <Skeleton className="h-16" />
          </div>
        )}

        {error &&
          !loading &&
          (tab === "pair" ? (
            // У «Он и я» кнопка повтора уже есть — «Разложить карты» выше
            <p role="alert" className="text-[13px] text-danger mb-2">
              {error}
            </p>
          ) : (
            <LoadError
              title="Не удалось получить расклад"
              onRetry={() => load(tab)}
            />
          ))}

        {!loading && spread && (
          <motion.div
            key={`${spread.spread}:${spread.title}`}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.2 }}
          >
            <h2 className="text-caption text-text-muted mb-2 px-1">
              {spread.title}
            </h2>
            <div className="glass rounded-[20px] overflow-hidden mb-3">
              {spread.cards.map((card, i) => (
                <div
                  key={i}
                  className="flex items-center gap-3 px-4 py-3
                             border-t border-[color:var(--glass-divider)] first:border-t-0"
                >
                  <Sparkles size={17} className="text-accent shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-[14.5px] font-semibold">
                      {card.position}: {card.name}
                    </p>
                    <p className="text-caption text-text-muted">{card.meaning}</p>
                  </div>
                </div>
              ))}
            </div>

            <Card className="p-4 mb-2">
              <p className="text-caption font-semibold text-accent mb-1.5">
                Толкование
              </p>
              <p className="text-[14.5px] leading-relaxed">
                {spread.interpretation}
              </p>
            </Card>

            <p className="text-[11.5px] text-text-faint px-1">
              {spread.disclaimer}
            </p>
          </motion.div>
        )}
          </>
        )}
      </div>
    </div>
  );
}

/* ── Замок платного раздела ─────────────────────────────────── */

/** Апселл вместо ошибки: имя тарифа в тексте приходит с сервера (см.
 *  `readLock`), здесь его не дублируем. Ведём на витрину тарифов — там покупка.
 *  Стиль совпадает с крючком лички (DirectMessageSheet), чтобы платные места
 *  читались одинаково по всему приложению. */
function TarotLock({ message }: { message: string }) {
  return (
    <Card className="p-5 flex flex-col items-center text-center">
      <div className="w-11 h-11 rounded-full bg-accent/15 flex items-center justify-center mb-3">
        <Crown size={20} className="text-accent" />
      </div>
      <p className="text-[15px] font-semibold mb-1">Расклады по подписке</p>
      <p className="text-[13px] text-text-muted mb-4 leading-snug">{message}</p>
      <Link
        to="/plans"
        onClick={() => haptic("light")}
        className="flex items-center justify-center gap-2 w-full h-12 px-6
                   rounded-[var(--radius-control)] bg-accent text-on-accent
                   text-[15px] font-semibold shadow-[var(--shadow-control)]"
      >
        Открыть тарифы
      </Link>
    </Card>
  );
}
