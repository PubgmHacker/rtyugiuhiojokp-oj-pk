import { useEffect, useState, useCallback } from "react";
import { Send, FlaskConical, ChevronLeft, ChevronRight, WifiOff, Megaphone } from "lucide-react";
import { createBroadcast, getBroadcasts, type AdminBroadcast } from "../../lib/admin";
import { Button, EmptyState, Skeleton } from "../ui";

/**
 * Рассылка через бота: написать сообщение всем пользователям с Telegram.
 *
 * API только ставит задачу, шлёт бот (~20 сообщений в секунду) и пишет
 * прогресс в ту же строку — пока что-то отправляется, список сам
 * перечитывается раз в три секунды.
 *
 * Кнопка «Себе (тест)» шлёт сообщение только автору: посмотреть его глазами
 * получателя ДО того, как оно уйдёт всей базе, — отменить запущенную
 * рассылку нельзя.
 */

/** Потолок Telegram. Бот экранирует < > & (parse_mode=HTML), экранирование
 *  удлиняет текст — меряем как API, по тому, что реально уйдёт. */
const ЛИМИТ = 4096;

const длинаВTelegram = (t: string) =>
  t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").length;

const СТАТУСЫ: Record<string, { label: string; tone: string }> = {
  queued: { label: "в очереди", tone: "bg-warn/20 text-warn" },
  running: { label: "отправляется", tone: "bg-info/20 text-info" },
  done: { label: "готово", tone: "bg-success/20 text-success" },
  error: { label: "ошибка", tone: "bg-danger/20 text-danger" },
};

const СЕГМЕНТЫ: Record<string, string> = {
  all: "всем",
  test: "тест — только себе",
};

export default function BroadcastPanel() {
  const [text, setText] = useState("");
  const [список, setСписок] = useState<AdminBroadcast[] | null>(null);
  const [сбойСписка, setСбойСписка] = useState(false);
  const [ошибкаФормы, setОшибкаФормы] = useState<string | null>(null);
  const [отправка, setОтправка] = useState<"all" | "test" | null>(null);
  const [page, setPage] = useState(1);

  const загрузить = useCallback(() => {
    setСбойСписка(false);
    setСписок(null);
    getBroadcasts(page)
      .then(setСписок)
      .catch(() => setСбойСписка(true));
  }, [page]);

  useEffect(загрузить, [загрузить]);

  // Пока бот шлёт, счётчики в строке растут — перечитываем список тихо,
  // без скелетона, чтобы страница не мигала
  useEffect(() => {
    const идёт = список?.some((b) => b.status === "queued" || b.status === "running");
    if (!идёт) return;
    const t = setInterval(() => {
      getBroadcasts(page).then(setСписок).catch(() => {});
    }, 3000);
    return () => clearInterval(t);
  }, [список, page]);

  const длина = длинаВTelegram(text);
  const пусто = !text.trim();

  const отправить = async (segment: "all" | "test") => {
    if (
      segment === "all" &&
      !confirm(
        "Отправить всем пользователям с Telegram? " +
          "Остановить рассылку после запуска нельзя."
      )
    )
      return;

    setОтправка(segment);
    setОшибкаФормы(null);
    try {
      await createBroadcast(text, segment);
      // После теста текст оставляем: человек смотрит сообщение у себя в
      // Telegram и следующим кликом шлёт его же всем
      if (segment === "all") setText("");
      if (page === 1) {
        getBroadcasts(1).then(setСписок).catch(() => {});
      } else {
        setPage(1);
      }
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail;
      setОшибкаФормы(detail || "Не получилось — попробуйте ещё раз");
    } finally {
      setОтправка(null);
    }
  };

  return (
    <div className="space-y-6">
      {/* Форма */}
      <div className="p-4 rounded-[var(--radius-tile)] bg-surface border border-hairline space-y-3">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={5}
          placeholder="Текст сообщения. Уйдёт как написан, без разметки."
          className="field w-full p-3 rounded-[var(--radius-control)] text-[14.5px] resize-y"
        />
        <div className="flex flex-wrap items-center gap-3">
          <span
            className={`text-[12.5px] ${
              длина > ЛИМИТ ? "text-danger font-semibold" : "text-text-faint"
            }`}
          >
            {длина} / {ЛИМИТ}
            {длина !== text.length && " (с учётом экранирования)"}
          </span>
          {ошибкаФормы && (
            <span className="text-[12.5px] text-danger">{ошибкаФормы}</span>
          )}
          <div className="ml-auto flex gap-2">
            <Button
              variant="secondary"
              size="sm"
              disabled={пусто || длина > ЛИМИТ || отправка !== null}
              loading={отправка === "test"}
              onClick={() => отправить("test")}
            >
              <FlaskConical size={15} />
              Себе (тест)
            </Button>
            <Button
              variant="primary"
              size="sm"
              disabled={пусто || длина > ЛИМИТ || отправка !== null}
              loading={отправка === "all"}
              onClick={() => отправить("all")}
            >
              <Send size={15} />
              Отправить всем
            </Button>
          </div>
        </div>
      </div>

      {/* История рассылок */}
      {сбойСписка ? (
        <EmptyState
          icon={WifiOff}
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
            <Skeleton key={i} className="h-20 rounded-[var(--radius-tile)]" />
          ))}
        </div>
      ) : список.length === 0 && page === 1 ? (
        <EmptyState
          icon={Megaphone}
          title="Рассылок ещё не было"
          description="Первое сообщение стоит отправить себе — кнопка «Себе (тест)»."
        />
      ) : (
        <>
          <div className="flex flex-col gap-2">
            {список.map((b) => {
              const статус = СТАТУСЫ[b.status] ?? {
                label: b.status,
                tone: "bg-surface-2 text-text-muted",
              };
              return (
                <div
                  key={b.id}
                  className="p-3 rounded-[var(--radius-tile)] bg-surface border border-hairline"
                >
                  <div className="flex items-center gap-2 flex-wrap">
                    <span
                      className={`px-2 py-0.5 rounded-full text-[12px] font-semibold ${статус.tone}`}
                    >
                      {статус.label}
                    </span>
                    <span className="text-[12.5px] text-text-muted">
                      {СЕГМЕНТЫ[b.segment] ?? b.segment}
                    </span>
                    <span className="ml-auto text-[12px] text-text-faint">
                      {b.created_by_name || b.created_by}
                      {b.created_at &&
                        ` · ${new Date(b.created_at).toLocaleString("ru")}`}
                    </span>
                  </div>
                  <p className="mt-1.5 text-[13.5px] whitespace-pre-wrap break-words line-clamp-3">
                    {b.text}
                  </p>
                  {/* У queued счётчиков ещё нет: получателей считает бот,
                      когда берёт задачу в работу */}
                  {b.status !== "queued" && (
                    <p className="mt-1 text-[12.5px] text-text-muted">
                      Доставлено {b.sent} из {b.total}
                      {b.failed > 0 && (
                        <span className="text-danger"> · не дошло {b.failed}</span>
                      )}
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
                disabled={список.length < 20}
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
