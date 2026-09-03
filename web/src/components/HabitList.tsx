/**
 * Список задач дня. Общий для панели в чате и экрана /habits.
 *
 * Отметку показываем до ответа сервера и откатываем при ошибке: галочка,
 * ждущая сеть, ощущается как незакрытая задача, и человек жмёт второй раз
 * — получая двойной зачёт.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { Check, Plus, Trash2, Undo2, Sprout } from "lucide-react";
import { Button, EmptyState, LoadError, Skeleton } from "./ui";
import { haptic } from "../lib/haptics";
import {
  checkHabit,
  createHabit,
  deleteHabit,
  getHabits,
  uncheckHabit,
  type Habit,
} from "../lib/api";
import { assertList } from "../lib/payload";

//: Что предлагаем на пустом экране. Своя формулировка работает лучше
//: нашей, но с чистого листа человек не пишет ничего — а с примера пишет.
const ПОДСКАЗКИ = [
  "Выпить воды",
  "Прогулка 20 минут",
  "Прочитать 10 страниц",
  "Написать первым",
  "Зарядка",
];

export function HabitList({ compact = false }: { compact?: boolean }) {
  const [habits, setHabits] = useState<Habit[]>([]);
  const [limit, setLimit] = useState(12);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);
  // Сбой загрузки — отдельно от error: плашка error живёт над списком, а при
  // несуществующем списке ветка «План дня пуст» с подсказками — ложь
  const [сбойЗагрузки, setСбойЗагрузки] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const загрузить = useCallback(async () => {
    setLoading(true);
    setСбойЗагрузки(false);
    try {
      const r = await getHabits();
      setHabits(assertList<Habit>(r.habits, "habits"));
      setLimit(r.limit);
      setError(null);
    } catch {
      setСбойЗагрузки(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    загрузить();
  }, [загрузить]);

  useEffect(() => {
    if (adding) inputRef.current?.focus();
  }, [adding]);

  /** Подменить одну задачу в списке, не перетягивая весь список. */
  const заменить = (h: Habit) =>
    setHabits((prev) => prev.map((x) => (x.id === h.id ? h : x)));

  const отметить = async (h: Habit) => {
    haptic(h.done_today ? "light" : "medium");
    const было = h;
    const счёт = h.done_today ? Math.max(0, h.today_count - 1) : h.today_count + 1;
    заменить({ ...h, today_count: счёт, done_today: счёт >= h.target_per_day });

    try {
      заменить(h.done_today ? await uncheckHabit(h.id) : await checkHabit(h.id));
    } catch {
      заменить(было);
      setError("Отметка не сохранилась");
    }
  };

  const удалить = async (h: Habit) => {
    haptic("medium");
    const было = habits;
    setHabits((prev) => prev.filter((x) => x.id !== h.id));
    try {
      await deleteHabit(h.id);
    } catch {
      setHabits(было);
      setError("Не удалось удалить задачу");
    }
  };

  const добавить = async (готовое?: string) => {
    const текст = (готовое ?? name).trim();
    if (!текст || saving) return;
    setSaving(true);
    setError(null);
    try {
      const h = await createHabit(текст);
      // Сервер отдаёт существующую при совпадении имени — поэтому не
      // append, а слияние: иначе дубль появится в списке, но не в базе.
      setHabits((prev) =>
        prev.some((x) => x.id === h.id) ? prev.map((x) => (x.id === h.id ? h : x)) : [...prev, h],
      );
      setName("");
      setAdding(false);
      haptic("medium");
    } catch (e: any) {
      setError(
        e?.response?.status === 409
          ? `Больше ${limit} задач за раз не ведём`
          : "Не получилось добавить задачу",
      );
    } finally {
      setSaving(false);
    }
  };

  const сделано = habits.filter((h) => h.done_today).length;
  const место = habits.length < limit;

  if (loading) {
    return (
      <div className="space-y-2">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-14 rounded-[12px]" />
        ))}
      </div>
    );
  }

  if (сбойЗагрузки) {
    return <LoadError onRetry={загрузить} />;
  }

  return (
    <div>
      {habits.length > 0 && (
        <div className="mb-3">
          <div className="mb-1.5 flex items-baseline justify-between">
            <span className="text-[13px] text-text-muted">Сегодня</span>
            <span className="text-[13px] font-semibold text-text">
              {сделано} из {habits.length}
            </span>
          </div>
          {/* Полоска, а не цифры: прогресс дня читается взглядом, а не
              чтением, и это единственная причина, по которой её видно. */}
          <div className="h-1.5 overflow-hidden rounded-full bg-surface-2">
            <div
              className="h-full rounded-full bg-accent transition-[width] duration-300"
              style={{
                width: habits.length ? `${(сделано / habits.length) * 100}%` : "0%",
              }}
            />
          </div>
        </div>
      )}

      {error && (
        <div className="mb-2.5 rounded-[10px] border border-danger/30 bg-danger/10 px-3 py-2 text-[13px] text-danger">
          {error}
        </div>
      )}

      {habits.length === 0 ? (
        <div className={compact ? "py-2" : "py-6"}>
          <EmptyState
            icon={Sprout}
            title="План дня пуст"
            description="Отметки сбрасываются в полночь. Начни с чего-нибудь простого."
          />
          <div className="mt-3 flex flex-wrap justify-center gap-2">
            {ПОДСКАЗКИ.map((п) => (
              <button
                key={п}
                disabled={saving}
                onClick={() => добавить(п)}
                className="chip px-3 py-1.5 text-[13px] text-text-secondary transition-transform active:scale-95 disabled:opacity-50"
              >
                {п}
              </button>
            ))}
          </div>
        </div>
      ) : (
        <ul className="space-y-2">
          {habits.map((h) => (
            <li
              key={h.id}
              className="flex items-center gap-3 rounded-[12px] border border-hairline bg-surface px-3 py-2.5"
            >
              <button
                onClick={() => отметить(h)}
                aria-label={h.done_today ? "Снять отметку" : "Отметить сделано"}
                className={`tap-target grid h-9 w-9 shrink-0 place-items-center rounded-full border transition-all active:scale-90 ${
                  h.done_today
                    ? "border-transparent bg-accent text-white"
                    : "border-hairline bg-surface-2 text-text-faint"
                }`}
              >
                {h.done_today ? (
                  <Check size={18} strokeWidth={3} />
                ) : (
                  <Check size={18} strokeWidth={2.2} />
                )}
              </button>

              <div className="min-w-0 flex-1">
                <p
                  className={`truncate text-[15px] leading-tight ${
                    h.done_today ? "text-text-muted line-through" : "text-text"
                  }`}
                >
                  {h.name}
                </p>
                {h.target_per_day > 1 && (
                  <p className="mt-0.5 text-[12px] text-text-faint">
                    {h.today_count} / {h.target_per_day} за день
                  </p>
                )}
              </div>

              {h.today_count > 0 && (
                <button
                  onClick={() => отметить({ ...h, done_today: true })}
                  aria-label="Отменить последнюю отметку"
                  className="tap-target grid h-8 w-8 shrink-0 place-items-center rounded-full text-text-faint transition-colors active:bg-surface-2"
                >
                  <Undo2 size={16} />
                </button>
              )}

              <button
                onClick={() => удалить(h)}
                aria-label="Удалить задачу"
                className="tap-target grid h-8 w-8 shrink-0 place-items-center rounded-full text-text-faint transition-colors active:bg-surface-2 active:text-danger"
              >
                <Trash2 size={16} />
              </button>
            </li>
          ))}
        </ul>
      )}

      {adding ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            добавить();
          }}
          className="mt-2.5 flex gap-2"
        >
          <input
            ref={inputRef}
            value={name}
            onChange={(e) => setName(e.target.value)}
            onBlur={() => !name.trim() && setAdding(false)}
            maxLength={100}
            placeholder="Что сделать сегодня?"
            className="field min-w-0 flex-1 rounded-[10px] px-3 py-2.5 text-[15px]"
          />
          <Button type="submit" loading={saving} disabled={!name.trim()}>
            Добавить
          </Button>
        </form>
      ) : (
        место && (
          <button
            onClick={() => {
              haptic("light");
              setAdding(true);
            }}
            className="mt-2.5 flex w-full items-center justify-center gap-1.5 rounded-[12px] border border-dashed border-hairline py-3 text-[14px] text-text-muted transition-colors active:bg-surface-2"
          >
            <Plus size={16} />
            Новая задача
          </button>
        )
      )}

      {!место && (
        <p className="mt-2.5 text-center text-[12.5px] text-text-faint">
          Максимум {limit} задач — план дня должен читаться, а не листаться
        </p>
      )}
    </div>
  );
}
