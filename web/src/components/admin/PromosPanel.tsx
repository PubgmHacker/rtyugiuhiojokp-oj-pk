import { useEffect, useState, useCallback } from "react";
import {
  TicketPercent, Copy, Check, ChevronLeft, ChevronRight,
} from "lucide-react";
import {
  createPromo, getPromos, setPromoActive, type AdminPromo,
} from "../../lib/admin";
import { Button, EmptyState, Skeleton, Toggle } from "../ui";

/**
 * Промокоды на подписку: выпустить, посмотреть, выключить.
 *
 * Код — не секрет: он уходит в посты и рекламу, поэтому показывается
 * открыто и копируется в один клик. Ограничивают его лимит активаций,
 * срок годности и выключатель — выключенный код перестаёт приниматься
 * сразу, но история активаций остаётся (удаления нет намеренно).
 */

const ТАРИФЫ: { id: string; label: string }[] = [
  { id: "plus", label: "Plus" },
  { id: "ultra", label: "Ultra" },
  { id: "aurora", label: "Aurora" },
];

const ЦВЕТ_ТАРИФА: Record<string, string> = {
  plus: "bg-info/20 text-info",
  ultra: "bg-warn/20 text-warn",
  aurora: "bg-accent/20 text-accent",
};

const НА_СТРАНИЦЕ = 50;

const дата = (iso: string) => new Date(iso).toLocaleString("ru");

/** Поля ввода в форме — одинаковая рамка, как textarea в рассылке. */
const ПОЛЕ =
  "field p-2.5 rounded-[var(--radius-control)] text-[14px]";

export default function PromosPanel() {
  // Форма выпуска. Тариф/дни/лимит после выпуска не сбрасываются:
  // пачку одинаковых кодов выпускают подряд, меняя только комментарий.
  const [tier, setTier] = useState("plus");
  const [days, setDays] = useState("7");
  const [maxUses, setMaxUses] = useState("1");
  const [code, setCode] = useState("");
  const [expires, setExpires] = useState("");
  const [comment, setComment] = useState("");
  const [выпуск, setВыпуск] = useState(false);
  const [ошибкаФормы, setОшибкаФормы] = useState<string | null>(null);
  const [свежий, setСвежий] = useState<AdminPromo | null>(null);

  const [список, setСписок] = useState<AdminPromo[] | null>(null);
  const [сбойСписка, setСбойСписка] = useState(false);
  const [page, setPage] = useState(1);
  const [скопирован, setСкопирован] = useState<string | null>(null);
  const [переключаю, setПереключаю] = useState<string | null>(null);

  const загрузить = useCallback(() => {
    setСбойСписка(false);
    setСписок(null);
    getPromos(page, НА_СТРАНИЦЕ)
      .then(setСписок)
      .catch(() => setСбойСписка(true));
  }, [page]);

  useEffect(загрузить, [загрузить]);

  const скопировать = async (p: AdminPromo) => {
    try {
      await navigator.clipboard.writeText(p.code);
      setСкопирован(p.id);
      setTimeout(() => setСкопирован(null), 2000);
    } catch {
      // Буфер обмена недоступен вне https — показываем код текстом
      window.prompt("Скопируйте код:", p.code);
    }
  };

  const выпустить = async () => {
    setВыпуск(true);
    setОшибкаФормы(null);
    setСвежий(null);
    try {
      const создан = await createPromo({
        tier,
        days: Number(days),
        max_uses: Number(maxUses),
        code: code.trim() || undefined,
        // datetime-local отдаёт локальное время без зоны — дошлём зону,
        // иначе сервер прочитает его как UTC и срок сместится
        expires_at: expires ? new Date(expires).toISOString() : null,
        comment: comment.trim() || undefined,
      });
      setСвежий(создан);
      setCode("");
      setComment("");
      if (page === 1) {
        getPromos(1, НА_СТРАНИЦЕ).then(setСписок).catch(() => {});
      } else {
        setPage(1);
      }
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail;
      setОшибкаФормы(detail || "Не получилось — попробуйте ещё раз");
    } finally {
      setВыпуск(false);
    }
  };

  const переключить = async (p: AdminPromo) => {
    setПереключаю(p.id);
    try {
      const новый = await setPromoActive(p.id, !p.is_active);
      setСписок((с) => с?.map((x) => (x.id === новый.id ? новый : x)) ?? с);
    } catch {
      // Список не трогаем — тумблер остался как был, это и есть правда
    } finally {
      setПереключаю(null);
    }
  };

  const дниЧисло = Number(days);
  const лимитЧисло = Number(maxUses);
  const дниЛадно = Number.isInteger(дниЧисло) && дниЧисло >= 1 && дниЧисло <= 3650;
  const лимитЛадно =
    Number.isInteger(лимитЧисло) && лимитЧисло >= 0 && лимитЧисло <= 1_000_000;

  return (
    <div className="space-y-6">
      {/* Форма выпуска */}
      <div className="p-4 rounded-[var(--radius-tile)] bg-surface border border-hairline space-y-3">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <label className="flex flex-col gap-1 text-[12.5px] text-text-muted">
            Тариф
            <select
              value={tier}
              onChange={(e) => setTier(e.target.value)}
              className={ПОЛЕ}
            >
              {ТАРИФЫ.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-[12.5px] text-text-muted">
            Дней подписки
            <input
              type="number"
              min={1}
              max={3650}
              value={days}
              onChange={(e) => setDays(e.target.value)}
              className={ПОЛЕ}
            />
          </label>
          <label className="flex flex-col gap-1 text-[12.5px] text-text-muted">
            Лимит активаций
            <input
              type="number"
              min={0}
              max={1000000}
              value={maxUses}
              onChange={(e) => setMaxUses(e.target.value)}
              placeholder="0 — без лимита"
              className={ПОЛЕ}
            />
          </label>
          <label className="flex flex-col gap-1 text-[12.5px] text-text-muted">
            Годен до (пусто — бессрочно)
            <input
              type="datetime-local"
              value={expires}
              onChange={(e) => setExpires(e.target.value)}
              className={ПОЛЕ}
            />
          </label>
          <label className="flex flex-col gap-1 text-[12.5px] text-text-muted col-span-2">
            Свой код (пусто — сгенерируется)
            <input
              type="text"
              value={code}
              onChange={(e) => setCode(e.target.value.toUpperCase())}
              placeholder="Например LAUNCH2026"
              maxLength={32}
              className={`${ПОЛЕ} font-mono tracking-wider`}
            />
          </label>
          <label className="flex flex-col gap-1 text-[12.5px] text-text-muted col-span-2">
            Комментарий (виден только админам)
            <input
              type="text"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="Для какой акции выпущен"
              maxLength={200}
              className={ПОЛЕ}
            />
          </label>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {ошибкаФормы && (
            <span className="text-[12.5px] text-danger">{ошибкаФормы}</span>
          )}
          {!ошибкаФормы && (!дниЛадно || !лимитЛадно) && (
            <span className="text-[12.5px] text-text-faint">
              Дни 1–3650, лимит 0–1 000 000
            </span>
          )}
          <div className="ml-auto">
            <Button
              variant="primary"
              size="sm"
              disabled={!дниЛадно || !лимитЛадно || выпуск}
              loading={выпуск}
              onClick={выпустить}
            >
              <TicketPercent size={15} />
              Выпустить
            </Button>
          </div>
        </div>

        {/* Только что выпущенный код — крупно, чтобы сразу забрать в акцию */}
        {свежий && (
          <div className="flex items-center gap-3 p-3 rounded-[var(--radius-control)] bg-success/10 border border-success/30">
            <span className="font-mono text-[17px] font-bold tracking-[0.15em] break-all">
              {свежий.code}
            </span>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => скопировать(свежий)}
            >
              {скопирован === свежий.id ? <Check size={15} /> : <Copy size={15} />}
              {скопирован === свежий.id ? "Скопирован" : "Скопировать"}
            </Button>
          </div>
        )}
      </div>

      {/* Список выпущенных */}
      {сбойСписка ? (
        <EmptyState
          emoji="📡"
          title="Не удалось загрузить"
          description="Проверьте соединение и попробуйте снова."
          action={
            <Button variant="secondary" size="md" onClick={загрузить}>
              Повторить
            </Button>
          }
        />
      ) : !список ? (
        <div className="flex flex-col gap-2">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-16 rounded-[var(--radius-tile)]" />
          ))}
        </div>
      ) : список.length === 0 && page === 1 ? (
        <EmptyState
          emoji="🎁"
          title="Промокодов ещё нет"
          description="Выпустите первый в форме выше — код можно раздать в посте или рекламе."
        />
      ) : (
        <>
          <div className="flex flex-col gap-2">
            {список.map((p) => {
              const исчерпан = p.max_uses > 0 && p.used_count >= p.max_uses;
              const истёк =
                !!p.expires_at && new Date(p.expires_at).getTime() < Date.now();
              return (
                <div
                  key={p.id}
                  className="p-3 rounded-[var(--radius-tile)] bg-surface border border-hairline"
                >
                  <div className="flex items-center gap-2 flex-wrap">
                    <button
                      onClick={() => скопировать(p)}
                      title="Скопировать код"
                      className="inline-flex items-center gap-1.5 font-mono text-[14.5px] font-bold tracking-[0.12em] hover:text-accent transition-colors"
                    >
                      {p.code}
                      {скопирован === p.id ? (
                        <Check size={13} className="text-success" />
                      ) : (
                        <Copy size={13} className="text-text-faint" />
                      )}
                    </button>
                    <span
                      className={`px-2 py-0.5 rounded-full text-[12px] font-semibold ${
                        ЦВЕТ_ТАРИФА[p.tier] ?? "bg-surface-2 text-text-muted"
                      }`}
                    >
                      {ТАРИФЫ.find((t) => t.id === p.tier)?.label ?? p.tier}
                    </span>
                    <span className="text-[12.5px] text-text-muted">
                      {p.days} дн.
                    </span>
                    {истёк && (
                      <span className="px-2 py-0.5 rounded-full text-[12px] font-semibold bg-danger/20 text-danger">
                        истёк
                      </span>
                    )}
                    {исчерпан && !истёк && (
                      <span className="px-2 py-0.5 rounded-full text-[12px] font-semibold bg-warn/20 text-warn">
                        исчерпан
                      </span>
                    )}
                    <button
                      onClick={() => переключить(p)}
                      disabled={переключаю === p.id}
                      title={p.is_active ? "Выключить код" : "Включить код"}
                      className="ml-auto disabled:opacity-50"
                    >
                      <Toggle on={p.is_active} />
                    </button>
                  </div>
                  <p className="mt-1 text-[12.5px] text-text-muted">
                    Активаций: {p.used_count}
                    {p.max_uses > 0 ? ` из ${p.max_uses}` : " (без лимита)"}
                    {p.expires_at && ` · годен до ${дата(p.expires_at)}`}
                    {p.created_at && ` · выпущен ${дата(p.created_at)}`}
                  </p>
                  {p.comment && (
                    <p className="mt-0.5 text-[12.5px] text-text-faint break-words">
                      {p.comment}
                    </p>
                  )}
                </div>
              );
            })}
          </div>

          <div className="flex items-center justify-between">
            <span className="text-xs text-text-muted">Страница {page}</span>
            <div className="flex gap-2">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setPage(Math.max(1, page - 1))}
                disabled={page <= 1}
              >
                <ChevronLeft size={15} />
                Назад
              </Button>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setPage(page + 1)}
                disabled={список.length < НА_СТРАНИЦЕ}
              >
                Вперёд
                <ChevronRight size={15} />
              </Button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
