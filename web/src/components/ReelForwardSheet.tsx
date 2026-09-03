/**
 * Куда переслать ролик: конкретному мэтчу или в общий чат.
 *
 * Наружу не делимся: в Telegram Mini App ссылку всё равно откроют внутри
 * Telegram, а вне него она бесполезна. Смысл репоста здесь в другом — показать
 * человеку, с которым уже говоришь, или закинуть в комнату по теме.
 *
 * Список получателей строится из мэтчей и комнат, а не из поиска людей: иначе
 * через пересыл можно было бы написать тому, с кем мэтч уже разорван.
 */

import { useCallback, useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Send, Users, X } from "lucide-react";
import {
  forwardReel,
  getMatches,
  getRooms,
  type MatchResponse,
  type Reel,
  type Room,
} from "../lib/api";
import { haptic } from "../lib/haptics";
import { Button, LoadError, Skeleton, Spinner } from "./ui";

const MAX_LEN = 500;

/** Отменённый запрос — не ошибка: иначе на закрытии шторки мелькает «некому». */
const отменён = (e: any) =>
  e?.code === "ERR_CANCELED" || e?.name === "CanceledError";

type Target = { kind: "match"; id: string } | { kind: "room"; id: string };

export default function ReelForwardSheet({
  reel,
  onClose,
  onSent,
}: {
  reel: Reel | null;
  onClose: () => void;
  /** Сообщение об успехе показывает лента: шторка к этому моменту закрыта. */
  onSent: (куда: string) => void;
}) {
  const [matches, setMatches] = useState<MatchResponse[] | null>(null);
  const [rooms, setRooms] = useState<Room[] | null>(null);
  const [target, setTarget] = useState<Target | null>(null);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  // Сбои списков раздельные: если упал только один, показываем второй —
  // возможность переслать хоть куда-то лучше отказа целиком
  const [сбойМэтчей, setСбойМэтчей] = useState(false);
  const [сбойКомнат, setСбойКомнат] = useState(false);
  const [попытка, setПопытка] = useState(0);

  useEffect(() => {
    if (!reel) return;
    setTarget(null);
    setText("");
    setError("");
    setMatches(null);
    setRooms(null);
    setСбойМэтчей(false);
    setСбойКомнат(false);

    // Отменяем по закрытию: шторку часто закрывают до ответа сети, и ответ
    // пришёл бы уже в размонтированный компонент
    const прервать = new AbortController();
    getMatches(прервать.signal)
      .then(setMatches)
      // Пустой список не подставляем — «переслать некому» при упавшей сети
      // читалось бы как «у вас нет мэтчей», а это неправда
      .catch((e) => отменён(e) || setСбойМэтчей(true));
    getRooms(прервать.signal)
      .then(setRooms)
      .catch((e) => отменён(e) || setСбойКомнат(true));
    return () => прервать.abort();
  }, [reel, попытка]);

  const send = useCallback(async () => {
    if (!reel || !target || sending) return;
    setSending(true);
    setError("");
    try {
      await forwardReel(
        reel.id,
        target.kind === "match" ? { matchId: target.id } : { roomId: target.id },
        text.trim()
      );
      haptic("success");
      const имя =
        target.kind === "match"
          ? matches?.find((m) => m.id === target.id)?.partner.display_name ??
            "собеседнику"
          : rooms?.find((r) => r.id === target.id)?.title ?? "в комнату";
      onClose();
      onSent(имя);
    } catch (e: any) {
      haptic("error");
      setError(e?.response?.data?.detail ?? "Не удалось переслать");
    } finally {
      setSending(false);
    }
  }, [reel, target, text, sending, matches, rooms, onClose, onSent]);

  // Список «готов», когда ответил или упал; пустота честная только без сбоев
  const мэтчиГотовы = matches !== null || сбойМэтчей;
  const комнатыГотовы = rooms !== null || сбойКомнат;
  const всёГотово = мэтчиГотовы && комнатыГотовы;
  const сбой = сбойМэтчей || сбойКомнат;
  const естьЧтоПоказать = !!matches?.length || !!rooms?.length;
  const показыватьНечего = всёГотово && !естьЧтоПоказать;
  const пусто = показыватьНечего && !сбой;

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
            aria-label="Кому переслать видео"
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
                <h2 className="text-heading font-bold">Переслать видео</h2>
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
              {!всёГотово ? (
                <div className="flex flex-col gap-2.5 pt-2">
                  {[0, 1, 2].map((i) => (
                    <Skeleton key={i} className="h-14 rounded-[var(--radius-tile)]" />
                  ))}
                </div>
              ) : показыватьНечего && сбой ? (
                <LoadError onRetry={() => setПопытка((x) => x + 1)} />
              ) : пусто ? (
                <p className="text-center text-[14px] text-text-muted py-10">
                  Переслать пока некому: нет ни мэтчей, ни комнат. Поставьте лайк
                  или зайдите в общий чат — оттуда и начнётся разговор.
                </p>
              ) : (
                <>
                  {!!matches?.length && (
                    <>
                      <p className="text-caption text-text-muted mt-2 mb-2">Личные чаты</p>
                      <div className="flex flex-col gap-1.5 mb-4">
                        {matches.map((m) => (
                          <Recipient
                            key={m.id}
                            title={m.partner.display_name || "Без имени"}
                            photo={m.partner.photos?.[0]}
                            selected={target?.kind === "match" && target.id === m.id}
                            onPick={() => {
                              haptic("light");
                              setTarget({ kind: "match", id: m.id });
                            }}
                          />
                        ))}
                      </div>
                    </>
                  )}

                  {!!rooms?.length && (
                    <>
                      <p className="text-caption text-text-muted mb-2">Комнаты</p>
                      <div className="flex flex-col gap-1.5 pb-2">
                        {rooms.map((r) => (
                          <Recipient
                            key={r.id}
                            title={r.title}
                            subtitle={
                              r.messages_today > 0
                                ? `${r.messages_today} сообщений за сутки`
                                : "пока тихо"
                            }
                            selected={target?.kind === "room" && target.id === r.id}
                            onPick={() => {
                              haptic("light");
                              setTarget({ kind: "room", id: r.id });
                            }}
                          />
                        ))}
                      </div>
                    </>
                  )}

                  {/* Один из списков упал, но второй есть: говорим об этом
                      мелко, не пряча живых получателей за общим отказом */}
                  {сбой && (
                    <p className="text-caption text-text-muted pb-3">
                      {сбойМэтчей
                        ? "Личные чаты не загрузились — показаны только комнаты."
                        : "Комнаты не загрузились — показаны только личные чаты."}
                    </p>
                  )}
                </>
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

            {!показыватьНечего && (
              <div className="shrink-0 px-4 pb-3 pt-2 border-t border-hairline/60">
                <div className="flex items-end gap-2">
                  <textarea
                    value={text}
                    onChange={(e) => setText(e.target.value.slice(0, MAX_LEN))}
                    rows={1}
                    placeholder="Добавить сообщение (необязательно)"
                    aria-label="Сообщение к видео"
                    className="field flex-1 px-3.5 py-2.5 rounded-[var(--radius-tile)] resize-none text-[15px] max-h-24"
                  />
                  <Button
                    size="lg"
                    onClick={send}
                    disabled={!target || sending}
                    aria-label="Переслать"
                  >
                    {sending ? <Spinner size={17} /> : <Send size={18} />}
                    Переслать
                  </Button>
                </div>
              </div>
            )}
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}

function Recipient({
  title,
  subtitle,
  photo,
  selected,
  onPick,
}: {
  title: string;
  subtitle?: string;
  photo?: string;
  selected: boolean;
  onPick: () => void;
}) {
  return (
    <button
      onClick={onPick}
      aria-pressed={selected}
      className={`w-full flex items-center gap-3 px-3.5 py-2.5 text-left
                  rounded-[var(--radius-tile)] border transition-colors
                  ${
                    selected
                      ? "bg-accent/12 border-accent/50"
                      : "bg-surface-2 border-hairline active:bg-surface"
                  }`}
    >
      {photo ? (
        <img
          src={photo}
          alt=""
          loading="lazy"
          className="w-9 h-9 rounded-full object-cover shrink-0"
        />
      ) : (
        <span
          className="w-9 h-9 rounded-full shrink-0 flex items-center justify-center
                     text-text-muted"
          style={{ background: "var(--gradient-placeholder)" }}
        >
          <Users size={16} />
        </span>
      )}
      <span className="min-w-0">
        <span className="block text-[15px] font-semibold truncate">{title}</span>
        {subtitle && (
          <span className="block text-[12.5px] text-text-muted truncate">
            {subtitle}
          </span>
        )}
      </span>
    </button>
  );
}
