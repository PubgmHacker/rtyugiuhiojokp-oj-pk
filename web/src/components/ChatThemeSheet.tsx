/**
 * Выбор темы переписки.
 *
 * Тема одна на пару и меняется у обоих: в этом её ценность и её риск.
 * Поэтому предупреждаем текстом заранее — узнать об изменении из чужого
 * чата хуже, чем прочитать строчку под заголовком.
 *
 * Свои цвета — уровень Plus. Пресеты применяем сразу, произвольный цвет —
 * по кнопке: подбор трёх цветов подряд иначе шлёт три запроса.
 */
import { useEffect, useState } from "react";
import { Check, Lock, RotateCcw } from "lucide-react";
import { Sheet } from "./Sheet";
import { Button, Spinner } from "./ui";
import { haptic } from "../lib/haptics";
import { readableOn } from "../lib/aura";
import {
  getChatThemePresets,
  recordSectionOpen,
  resetChatTheme,
  setChatTheme,
  type ChatTheme,
  type ChatThemePreset,
} from "../lib/api";

const PATTERNS: { key: string; label: string }[] = [
  { key: "none", label: "Без узора" },
  { key: "hearts", label: "Сердца" },
  { key: "dots", label: "Точки" },
  { key: "waves", label: "Волны" },
  { key: "stars", label: "Звёзды" },
  { key: "grid", label: "Сетка" },
];

interface Props {
  open: boolean;
  onClose: () => void;
  matchId: string;
  theme: ChatTheme | null;
  onApplied: (theme: ChatTheme) => void;
  onNeedPlus: () => void;
}

export function ChatThemeSheet({
  open,
  onClose,
  matchId,
  theme,
  onApplied,
  onNeedPlus,
}: Props) {
  const [presets, setPresets] = useState<ChatThemePreset[]>([]);
  const [customAllowed, setCustomAllowed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [попытка, setПопытка] = useState(0);

  const [mine, setMine] = useState("#ff2d6f");
  const [theirs, setTheirs] = useState("#1c1f28");
  const [bg, setBg] = useState("#080615");
  const [pattern, setPattern] = useState("none");

  // Панель смонтирована вместе с чатом, поэтому раздел считаем по показу.
  useEffect(() => {
    if (open) recordSectionOpen("chat_theme");
  }, [open]);

  // Каталог тянем при первом открытии, а не при монтировании чата: список
  // тем не нужен девяти из десяти открытых переписок.
  useEffect(() => {
    if (!open || presets.length) return;
    let живо = true;
    setLoading(true);
    setError(null);
    getChatThemePresets()
      .then((r) => {
        if (!живо) return;
        setPresets(r.presets);
        setCustomAllowed(r.custom_allowed);
      })
      .catch(() => живо && setError("Не удалось загрузить темы"))
      .finally(() => живо && setLoading(false));
    return () => {
      живо = false;
    };
  }, [open, presets.length, попытка]);

  // Ползунки цвета стартуют с того, что в чате сейчас — иначе первое
  // касание любого из трёх перекрашивает остальные два в наши значения.
  useEffect(() => {
    if (!open) return;
    setMine(theme?.bubble_mine_color || "#ff2d6f");
    setTheirs(theme?.bubble_theirs_color || "#1c1f28");
    setBg(theme?.background_color || "#080615");
    setPattern(theme?.pattern_key || "none");
  }, [open, theme]);

  const активный = (p: ChatThemePreset) =>
    theme?.bubble_mine_color === p.bubble_mine_color &&
    theme?.background_color === p.background_color &&
    (theme?.pattern_key || "none") === p.pattern_key;

  const применить = async (fn: () => Promise<ChatTheme>, tag: string) => {
    haptic("light");
    setBusy(tag);
    setError(null);
    try {
      onApplied(await fn());
    } catch (e: any) {
      if (e?.response?.status === 403) {
        setError(e.response.data?.detail || "Нужен уровень выше");
        onNeedPlus();
      } else {
        setError(e?.response?.data?.detail || "Не получилось применить тему");
      }
    } finally {
      setBusy(null);
    }
  };

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="Тема переписки"
      subtitle="Оформление общее — увидите оба"
    >
      {error && (
        <div className="mb-3 rounded-[10px] border border-danger/30 bg-danger/10 px-3 py-2 text-[13px] text-danger">
          {error}
        </div>
      )}

      {loading ? (
        <div className="grid h-32 place-items-center">
          <Spinner />
        </div>
      ) : !presets.length ? (
        // Каталог не доехал: пустая решётка выглядела бы как «тем нет».
        // Баннер выше объясняет причину, кнопка повторяет без закрытия шторки
        <div className="grid h-32 place-items-center">
          <Button variant="secondary" size="sm" onClick={() => setПопытка((x) => x + 1)}>
            Повторить
          </Button>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-3 gap-2.5">
            {presets.map((p) => (
              <button
                key={p.key}
                disabled={busy !== null}
                onClick={() =>
                  p.locked
                    ? onNeedPlus()
                    : применить(() => setChatTheme(matchId, { preset: p.key }), p.key)
                }
                className={`relative overflow-hidden rounded-[14px] border p-2 text-left transition-transform active:scale-[0.97] disabled:opacity-60 ${
                  активный(p) ? "border-accent" : "border-hairline"
                }`}
                style={{ background: p.background_color }}
              >
                {/* Предпросмотр строит настоящую форму пузырей: цветные
                    квадраты не дают понять, как это будет читаться. */}
                <div className="space-y-1.5 pb-2">
                  <div
                    className="ml-auto h-5 w-3/4 rounded-[8px] rounded-br-[3px]"
                    style={{ background: p.bubble_mine_color }}
                  />
                  <div
                    className="h-5 w-2/3 rounded-[8px] rounded-bl-[3px]"
                    style={{ background: p.bubble_theirs_color }}
                  />
                </div>

                <div className="flex items-center gap-1">
                  <span
                    className="truncate text-[11.5px] font-medium"
                    style={{ color: readableOn(p.background_color) }}
                  >
                    {p.name}
                  </span>
                  {p.locked && <Lock size={11} className="shrink-0 text-warn" />}
                  {активный(p) && (
                    <Check
                      size={13}
                      strokeWidth={3}
                      className="ml-auto shrink-0"
                      style={{ color: p.bubble_mine_color }}
                    />
                  )}
                </div>

                {busy === p.key && (
                  <div className="absolute inset-0 grid place-items-center bg-black/40">
                    <Spinner size={16} />
                  </div>
                )}
              </button>
            ))}
          </div>

          <div className="mt-5 border-t border-hairline pt-4">
            <div className="mb-3 flex items-center gap-2">
              <h3 className="text-[14px] font-semibold text-text">Свои цвета</h3>
              {!customAllowed && (
                <span className="rounded-full bg-warn/15 px-2 py-0.5 text-[11px] font-medium text-warn">
                  Plus
                </span>
              )}
            </div>

            <div className="space-y-2.5">
              {(
                [
                  ["Мои сообщения", mine, setMine],
                  ["Его сообщения", theirs, setTheirs],
                  ["Фон", bg, setBg],
                ] as const
              ).map(([label, value, set]) => (
                <label
                  key={label}
                  className="flex items-center justify-between gap-3 rounded-[10px] bg-surface-2 px-3 py-2.5"
                >
                  <span className="text-[14px] text-text-secondary">{label}</span>
                  <span className="flex items-center gap-2">
                    <span className="font-mono text-[12px] uppercase text-text-faint">
                      {value}
                    </span>
                    <input
                      type="color"
                      value={value}
                      disabled={!customAllowed}
                      onChange={(e) => set(e.target.value)}
                      className="h-7 w-9 cursor-pointer rounded-[6px] border border-hairline bg-transparent disabled:opacity-40"
                    />
                  </span>
                </label>
              ))}
            </div>

            <div className="no-scrollbar -mx-5 mt-3 flex gap-2 overflow-x-auto px-5">
              {PATTERNS.map((p) => (
                <button
                  key={p.key}
                  disabled={!customAllowed}
                  onClick={() => {
                    haptic("light");
                    setPattern(p.key);
                  }}
                  className={`shrink-0 rounded-full px-3 py-1.5 text-[12.5px] transition-colors disabled:opacity-40 ${
                    pattern === p.key
                      ? "bg-accent text-on-accent"
                      : "bg-surface-2 text-text-secondary"
                  }`}
                >
                  {p.label}
                </button>
              ))}
            </div>

            <Button
              fullWidth
              className="mt-3"
              loading={busy === "custom"}
              disabled={busy !== null}
              onClick={() =>
                customAllowed
                  ? применить(
                      () =>
                        setChatTheme(matchId, {
                          bubble_mine_color: mine,
                          bubble_theirs_color: theirs,
                          background_color: bg,
                          pattern_key: pattern,
                        }),
                      "custom",
                    )
                  : onNeedPlus()
              }
            >
              {customAllowed ? "Применить свои цвета" : "Открыть с Plus"}
            </Button>
          </div>

          <Button
            variant="ghost"
            fullWidth
            className="mt-2 mb-1"
            loading={busy === "reset"}
            disabled={busy !== null}
            onClick={() => применить(() => resetChatTheme(matchId), "reset")}
          >
            <RotateCcw size={15} className="mr-1.5" />
            Вернуть обычное оформление
          </Button>
        </>
      )}
    </Sheet>
  );
}
