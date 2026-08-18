/**
 * Жалоба и блокировка из любого места, где виден чужой профиль.
 *
 * App Store (Guideline 1.2, UGC) требует, чтобы report и block были
 * доступны с каждой поверхности, где пользователь встречает незнакомца, —
 * не только из чата. Один лист на все поверхности: дека, мэтчи, лайки.
 *
 * Подтверждение блокировки — своя встроенная ступень, а не window.confirm:
 * в Telegram WebView нативный confirm подавлен и действие молча не срабатывало.
 */
import { useEffect, useState } from "react";
import { Ban, Flag } from "lucide-react";
import { Sheet } from "./Sheet";
import { Button } from "./ui";
import { REPORT_REASONS } from "../lib/profileOptions";
import { reportUser, blockUser } from "../lib/api";
import { haptic } from "../lib/haptics";

interface SafetySheetProps {
  open: boolean;
  onClose: () => void;
  /** Кого. */
  userId: string;
  name: string;
  /** Откуда пришла жалоба — уходит модератору в description. */
  origin: string;
  /** Что случится после (убрать карточку из деки, уйти из чата и т.п.). */
  onDone?: (action: "report" | "block") => void;
}

export default function SafetySheet({
  open,
  onClose,
  userId,
  name,
  origin,
  onDone,
}: SafetySheetProps) {
  const [step, setStep] = useState<"menu" | "block">("menu");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);

  // Каждый показ начинается с меню, а не с того, где закрыли прошлый раз
  useEffect(() => {
    if (open) {
      setStep("menu");
      setBusy(false);
      setError(false);
    }
  }, [open]);

  const report = async (reason: string) => {
    if (busy) return;
    setBusy(true);
    setError(false);
    try {
      await reportUser(userId, reason, origin);
      haptic("success");
      onClose();
      onDone?.("report");
    } catch {
      haptic("error");
      setError(true);
      setBusy(false);
    }
  };

  const block = async () => {
    if (busy) return;
    setBusy(true);
    setError(false);
    try {
      await blockUser(userId);
      haptic("success");
      onClose();
      onDone?.("block");
    } catch {
      haptic("error");
      setError(true);
      setBusy(false);
    }
  };

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title={step === "menu" ? `Пожаловаться на ${name}` : `Заблокировать ${name}?`}
      subtitle={
        step === "menu"
          ? "Жалоба уйдёт модератору, анкета исчезнет из показа"
          : "Вы больше не увидите друг друга и не сможете связаться. Отменить можно в настройках профиля."
      }
    >
      {error && (
        <p className="mb-3 text-[13.5px] text-danger">
          Не получилось отправить — проверьте связь и попробуйте ещё раз.
        </p>
      )}

      {step === "menu" ? (
        <div className="flex flex-col gap-1.5 pb-3">
          {REPORT_REASONS.map((r) => (
            <button
              key={r.value}
              disabled={busy}
              onClick={() => report(r.value)}
              className="w-full px-4 py-3 rounded-[var(--radius-tile)] text-left
                         bg-surface-2 border border-hairline text-[15px]
                         active:bg-surface transition-colors disabled:opacity-50"
            >
              <span className="inline-flex items-center gap-2.5">
                <Flag size={15} className="text-warn shrink-0" />
                {r.label}
              </span>
            </button>
          ))}
          <button
            disabled={busy}
            onClick={() => setStep("block")}
            className="w-full px-4 py-3 mt-1 rounded-[var(--radius-tile)] text-left
                       bg-surface-2 border border-hairline text-[15px] text-danger
                       active:bg-surface transition-colors disabled:opacity-50"
          >
            <span className="inline-flex items-center gap-2.5">
              <Ban size={15} className="shrink-0" />
              Заблокировать без жалобы
            </span>
          </button>
        </div>
      ) : (
        <div className="flex flex-col gap-2 pb-3">
          <Button variant="danger" size="lg" fullWidth disabled={busy} onClick={block}>
            <Ban size={17} />
            Заблокировать
          </Button>
          <Button variant="secondary" size="lg" fullWidth disabled={busy} onClick={() => setStep("menu")}>
            Назад
          </Button>
        </div>
      )}
    </Sheet>
  );
}
