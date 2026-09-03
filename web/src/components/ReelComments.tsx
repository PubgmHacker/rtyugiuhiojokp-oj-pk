/**
 * Комментарии под роликом.
 *
 * Здесь ролики и превращаются в знакомства: написать под видео проще, чем
 * первым в личку, и разговор начинается сам. Без этого лента остаётся
 * просмотром — самое сильное впечатление никуда не ведёт.
 *
 * Шторка, а не отдельный экран: уходя со страницы, человек терял бы место в
 * ленте и не возвращался к ролику.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Flag, Send, Trash2, X } from "lucide-react";
import {
  addReelComment,
  deleteReelComment,
  getReelComments,
  reportReelComment,
  type Reel,
  type ReelComment,
} from "../lib/api";
import { haptic } from "../lib/haptics";
import { letterAvatarStyle } from "../lib/aura";
import ReportReasonSheet from "./ReportReasonSheet";
import { LoadError, Skeleton, Spinner } from "./ui";

const MAX_LEN = 300;

export default function ReelComments({
  reel,
  onClose,
  onCountChange,
}: {
  reel: Reel | null;
  onClose: () => void;
  /** Счётчик на карточке должен меняться сразу, без перезагрузки ленты. */
  onCountChange: (reelId: string, delta: number) => void;
}) {
  const [comments, setComments] = useState<ReelComment[] | null>(null);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [reportFor, setReportFor] = useState<ReelComment | null>(null);
  const [сбой, setСбой] = useState(false);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  const загрузить = useCallback(() => {
    if (!reel) return;
    setComments(null);
    setСбой(false);
    getReelComments(reel.id)
      .then(setComments)
      // Пустой список не подставляем: «Пока никто не написал» при упавшей
      // сети — ложь, к тому же под живым роликом с ненулевым счётчиком
      .catch(() => setСбой(true));
  }, [reel]);

  useEffect(() => {
    if (!reel) return;
    setError("");
    setNotice("");
    setReportFor(null);
    загрузить();
  }, [reel, загрузить]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [comments?.length]);

  const send = useCallback(async () => {
    const trimmed = text.trim();
    if (!reel || !trimmed || sending) return;
    setSending(true);
    setError("");
    try {
      const comment = await addReelComment(reel.id, trimmed);
      setComments((cur) => [...(cur ?? []), comment]);
      onCountChange(reel.id, 1);
      setText("");
      haptic("success");
    } catch (e: any) {
      haptic("error");
      setError(e?.response?.data?.detail ?? "Не удалось отправить");
    } finally {
      setSending(false);
    }
  }, [reel, text, sending, onCountChange]);

  const remove = useCallback(
    async (comment: ReelComment) => {
      if (!reel) return;
      haptic("light");
      try {
        await deleteReelComment(reel.id, comment.id);
        setComments((cur) => (cur ?? []).filter((c) => c.id !== comment.id));
        onCountChange(reel.id, -1);
      } catch {
        haptic("error");
        setError("Не удалось удалить");
      }
    },
    [reel, onCountChange]
  );

  const пожаловаться = useCallback(
    async (reason: string) => {
      const comment = reportFor;
      setReportFor(null);
      if (!reel || !comment) return;
      setError("");
      try {
        await reportReelComment(reel.id, comment.id, reason);
        haptic("success");
        setNotice("Жалоба отправлена — модератор разберётся");
      } catch (e: any) {
        haptic("error");
        setError(e?.response?.data?.detail ?? "Не удалось отправить жалобу");
      }
    },
    [reel, reportFor]
  );

  return (
    <AnimatePresence>
      {reel && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 z-40 bg-black/60"
          />
          <motion.div
            role="dialog"
            aria-label="Комментарии"
            initial={{ y: "100%" }}
            animate={{ y: 0 }}
            exit={{ y: "100%" }}
            transition={{ type: "spring", stiffness: 380, damping: 36 }}
            className="fixed bottom-0 left-0 right-0 z-50 flex flex-col
                       bg-bg-elevated rounded-t-[var(--radius-sheet)]
                       border-t border-hairline h-[72dvh] safe-bottom"
          >
            <div className="shrink-0 px-5 pt-3 pb-2">
              <div className="w-10 h-1 rounded-full bg-surface-3 mx-auto mb-4" />
              <div className="flex items-center justify-between">
                <h2 className="text-heading font-bold">
                  Комментарии
                  {reel.comments_count > 0 && (
                    <span className="ml-1.5 text-text-muted font-medium">
                      {reel.comments_count}
                    </span>
                  )}
                </h2>
                <button
                  aria-label="Закрыть"
                  onClick={onClose}
                  className="tap-target flex items-center justify-center text-text-muted"
                >
                  <X size={21} />
                </button>
              </div>
            </div>

            <div className="flex-1 overflow-y-auto px-5 no-scrollbar">
              {!comments ? (
                сбой ? (
                  <LoadError onRetry={загрузить} />
                ) : (
                  <div className="flex flex-col gap-2.5 pt-2">
                    {[0, 1, 2].map((i) => (
                      <Skeleton key={i} className="h-12 rounded-[var(--radius-tile)]" />
                    ))}
                  </div>
                )
              ) : !comments.length ? (
                <p className="text-center text-[14px] text-text-muted py-10">
                  Пока никто не написал. Скажите что-нибудь — это заметят.
                </p>
              ) : (
                <div className="flex flex-col gap-3.5 py-2">
                  {comments.map((c) => (
                    <div key={c.id} className="flex gap-2.5">
                      {c.author_photo ? (
                        <img
                          src={c.author_photo}
                          alt=""
                          loading="lazy"
                          className="w-8 h-8 rounded-full object-cover shrink-0"
                        />
                      ) : (
                        <span
                          className="w-8 h-8 rounded-full shrink-0 flex items-center
                                     justify-center text-[12px] font-bold"
                          style={letterAvatarStyle(c.author_id)}
                        >
                          {c.author_name?.[0]?.toUpperCase() ?? "?"}
                        </span>
                      )}

                      <div className="flex-1 min-w-0">
                        <p className="text-[13px] font-semibold text-accent mb-0.5">
                          {c.author_name || "Без имени"}
                        </p>
                        <p className="text-[14.5px] leading-snug break-words selectable">
                          {c.text}
                        </p>
                      </div>

                      {/* Удалить может автор комментария и владелец ролика:
                          под своим видео человек должен убрать грубость сам,
                          не дожидаясь модератора. Остальным — жалоба: чужой
                          комментарий публичен, и зритель должен иметь способ
                          сообщить о нарушении (App Store, Guideline 1.2) */}
                      {c.is_mine || reel.is_mine ? (
                        <button
                          aria-label="Удалить комментарий"
                          onClick={() => remove(c)}
                          className="shrink-0 text-text-faint active:scale-90 transition-transform"
                        >
                          <Trash2 size={15} />
                        </button>
                      ) : (
                        <button
                          aria-label="Пожаловаться на комментарий"
                          onClick={() => {
                            haptic("light");
                            setReportFor(c);
                          }}
                          className="shrink-0 text-text-faint active:scale-90 transition-transform"
                        >
                          <Flag size={15} />
                        </button>
                      )}
                    </div>
                  ))}
                  <div ref={bottomRef} />
                </div>
              )}
            </div>

            {error && (
              <p
                role="alert"
                className="mx-5 mb-2 px-3.5 py-2 rounded-[var(--radius-tile)]
                           bg-danger/12 border border-danger/30 text-danger text-[13px]"
              >
                {error}
              </p>
            )}

            {notice && (
              <p
                role="status"
                className="mx-5 mb-2 px-3.5 py-2 rounded-[var(--radius-tile)]
                           bg-surface-2 border border-hairline text-text-secondary text-[13px]"
              >
                {notice}
              </p>
            )}

            <div className="shrink-0 px-4 pb-3 pt-2 border-t border-hairline/60">
              <div className="flex items-end gap-2">
                <textarea
                  value={text}
                  onChange={(e) => setText(e.target.value.slice(0, MAX_LEN))}
                  rows={1}
                  placeholder="Написать комментарий"
                  aria-label="Текст комментария"
                  className="field flex-1 px-3.5 py-2.5 rounded-[var(--radius-tile)] resize-none text-[15px] max-h-24"
                />
                <button
                  aria-label="Отправить"
                  onClick={send}
                  disabled={!text.trim() || sending}
                  className="w-11 h-11 rounded-full bg-accent text-white shrink-0
                             flex items-center justify-center
                             disabled:opacity-30 active:scale-95 transition-transform"
                >
                  {sending ? <Spinner size={17} /> : <Send size={18} />}
                </button>
              </div>
            </div>
          </motion.div>

          <ReportReasonSheet
            open={reportFor !== null}
            title="Пожаловаться на комментарий"
            subtitle="Модератор прочитает его. Три жалобы снимают комментарий с показа сразу."
            onClose={() => setReportFor(null)}
            onPick={пожаловаться}
          />
        </>
      )}
    </AnimatePresence>
  );
}
