import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Link } from "react-router-dom";
import { Crown } from "lucide-react";
import { getDirectQuota, sendDirectMessage, type DirectQuota } from "../lib/api";
import { haptic } from "../lib/haptics";
import { Button } from "./ui";

/** Столько же, сколько принимает сервер (DirectMessageRequest.text). */
const MAX_DIRECT_TEXT = 2000;

/** Минимум, нужный шторке — подходит и DeckProfile, и UserProfile. */
export interface DirectTarget {
  id: string;
  display_name: string;
}

/**
 * Шторка «написать без взаимного лайка» — платный крючок (аналог «Мимолёта»
 * у конкурента). Открывается кнопкой на карточке деки или на странице лайков.
 * Гейт честный: если тариф не позволяет или лимит на сегодня исчерпан,
 * показываем предложение повысить тариф, а не скрытую блокировку.
 */
export default function DirectMessageSheet({
  profile,
  onClose,
  onSent,
}: {
  profile: DirectTarget | null;
  onClose: () => void;
  onSent?: () => void;
}) {
  const [quota, setQuota] = useState<DirectQuota | null>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!profile) return;
    setText("");
    setError(null);
    getDirectQuota()
      .then(setQuota)
      .catch(() => setQuota({ left: 0, total: 0, allowed: false }));
  }, [profile]);

  const trimmed = text.trim();
  const gated = quota !== null && (!quota.allowed || quota.left <= 0);

  const send = async () => {
    if (!profile || !trimmed || busy) return;
    setBusy(true);
    setError(null);
    try {
      await sendDirectMessage(profile.id, trimmed);
      haptic("success");
      onSent?.();
      onClose();
    } catch (e: any) {
      haptic("error");
      setError(e?.response?.data?.detail ?? "Не удалось отправить письмо");
    } finally {
      setBusy(false);
    }
  };

  return (
    <AnimatePresence>
      {profile && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm"
          />
          <motion.div
            role="dialog"
            aria-label="Написать без взаимного лайка"
            initial={{ y: "100%" }}
            animate={{ y: 0 }}
            exit={{ y: "100%" }}
            transition={{ type: "spring", stiffness: 380, damping: 36 }}
            className="fixed bottom-0 left-0 right-0 z-50 bg-bg-elevated
                       rounded-t-[var(--radius-sheet)] border-t border-hairline
                       px-5 pt-3 pb-7 safe-bottom"
          >
            <div className="w-10 h-1 rounded-full bg-surface-3 mx-auto mb-5" />

            <h2 className="text-heading font-bold mb-1.5">
              Написать {profile.display_name} без лайка
            </h2>
            <p className="text-caption text-text-muted mb-4">
              Письмо придёт до того, как человек вас лайкнёт. До ответа можно
              отправить только одно.
            </p>

            {gated ? (
              <Link
                to="/plans"
                onClick={() => haptic("light")}
                className="flex items-center gap-3 px-4 py-3 mb-4
                           rounded-[var(--radius-tile)] border border-accent/25 bg-accent/8"
              >
                <Crown size={18} className="text-accent shrink-0" />
                <span className="flex-1 text-[14px] leading-snug">
                  {quota && !quota.allowed
                    ? "Личка без взаимного лайка доступна на Plus и выше"
                    : "Письма без взаимности на сегодня закончились — больше на старшем тарифе"}
                </span>
              </Link>
            ) : (
              <>
                <textarea
                  value={text}
                  onChange={(e) => setText(e.target.value.slice(0, MAX_DIRECT_TEXT))}
                  rows={4}
                  autoFocus
                  placeholder="Первое сообщение — от него зависит, ответят ли"
                  aria-label="Текст письма"
                  className="w-full px-3.5 py-3 mb-1.5 rounded-[var(--radius-tile)]
                             bg-surface-2 border border-hairline text-[15px] resize-none
                             placeholder:text-text-muted focus:outline-none
                             focus:border-accent/60"
                />
                <p className="text-[12px] text-text-muted text-right mb-1">
                  {text.length} / {MAX_DIRECT_TEXT}
                </p>
                {quota && (
                  <p className="text-[12.5px] text-text-muted mb-4">
                    Осталось сегодня: {quota.left} из {quota.total}
                  </p>
                )}
              </>
            )}

            {error && (
              <p className="text-[13px] text-danger mb-3">{error}</p>
            )}

            <div className="flex gap-2.5">
              <Button variant="secondary" size="lg" onClick={onClose}>
                Отмена
              </Button>
              {!gated && (
                <Button
                  size="lg"
                  fullWidth
                  loading={busy}
                  disabled={!trimmed}
                  onClick={send}
                >
                  Отправить письмо
                </Button>
              )}
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
