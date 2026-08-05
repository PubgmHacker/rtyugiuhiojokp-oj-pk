/**
 * Публикация ролика.
 *
 * Обложку снимаем здесь, в браузере: сервер видео не разбирает, а без
 * проверенного кадра публикация не пройдёт. Заодно это отсекает файлы, которые
 * браузер не умеет декодировать — такие всё равно не проиграются в ленте.
 */

import { useCallback, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Film, X } from "lucide-react";
import { uploadReel, type Reel } from "../lib/api";
import { CoverFailed, grabVideoCovers, videoDuration } from "../lib/videoCover";
import { haptic } from "../lib/haptics";
import { Button, Spinner } from "./ui";

/** Совпадает с MAX_VIDEO_BYTES в api/routers/reels.py. */
const MAX_BYTES = 50 * 1024 * 1024;
/** Дольше — уже не «короткое видео», а лента превращается в видеохостинг. */
const MAX_SECONDS = 60;
const MAX_CAPTION = 300;

export default function ReelUploader({
  open,
  onClose,
  onDone,
}: {
  open: boolean;
  onClose: () => void;
  onDone: (reel: Reel) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string>("");
  const [caption, setCaption] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLInputElement | null>(null);

  const reset = useCallback(() => {
    if (preview) URL.revokeObjectURL(preview);
    setFile(null);
    setPreview("");
    setCaption("");
    setError("");
    setBusy(false);
  }, [preview]);

  const pick = useCallback(
    async (picked: File) => {
      setError("");
      if (picked.size > MAX_BYTES) {
        setError(`Видео больше ${MAX_BYTES / (1024 * 1024)} МБ`);
        return;
      }

      const seconds = await videoDuration(picked);
      if (seconds > MAX_SECONDS) {
        setError(`Не длиннее ${MAX_SECONDS} секунд — сейчас ${Math.round(seconds)}`);
        return;
      }

      setFile(picked);
      setPreview(URL.createObjectURL(picked));
    },
    []
  );

  const publish = useCallback(async () => {
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const covers = await grabVideoCovers(file);
      const reel = await uploadReel(file, covers, caption.trim());
      haptic("success");
      onDone(reel);
      reset();
      onClose();
    } catch (e: any) {
      haptic("error");
      if (e instanceof CoverFailed) {
        setError(e.message);
      } else if (e?.response?.status === 429) {
        setError(e?.response?.data?.detail ?? "Слишком часто — попробуйте позже");
      } else if (e?.response?.status === 422) {
        setError(e?.response?.data?.detail ?? "Видео не прошло проверку");
      } else {
        setError(e?.response?.data?.detail ?? "Не удалось опубликовать");
      }
      setBusy(false);
    }
  }, [file, caption, onDone, onClose, reset]);

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={busy ? undefined : onClose}
            className="fixed inset-0 z-40 bg-black/70 backdrop-blur-sm"
          />
          <motion.div
            role="dialog"
            aria-label="Новый ролик"
            initial={{ y: "100%" }}
            animate={{ y: 0 }}
            exit={{ y: "100%" }}
            transition={{ type: "spring", stiffness: 380, damping: 36 }}
            className="fixed bottom-0 left-0 right-0 z-50 bg-bg-elevated
                       rounded-t-[var(--radius-sheet)] border-t border-hairline
                       px-5 pt-3 pb-7 safe-bottom max-h-[92dvh] overflow-y-auto no-scrollbar"
          >
            <div className="w-10 h-1 rounded-full bg-surface-3 mx-auto mb-5" />

            <div className="flex items-center justify-between mb-5">
              <h2 className="text-heading font-bold">Новый ролик</h2>
              <button
                aria-label="Закрыть"
                onClick={onClose}
                disabled={busy}
                className="tap-target flex items-center justify-center text-text-muted
                           disabled:opacity-40"
              >
                <X size={21} />
              </button>
            </div>

            <input
              ref={inputRef}
              type="file"
              accept="video/mp4,video/quicktime,video/webm"
              className="hidden"
              onChange={(e) => {
                const picked = e.target.files?.[0];
                if (picked) pick(picked);
                // Сбрасываем значение: иначе повторный выбор того же файла
                // не вызовет onChange
                e.target.value = "";
              }}
            />

            {preview ? (
              <video
                src={preview}
                controls
                playsInline
                className="w-full max-h-[46dvh] rounded-[var(--radius-tile)] bg-black mb-4"
              />
            ) : (
              <button
                onClick={() => inputRef.current?.click()}
                className="w-full aspect-[4/5] max-h-[46dvh] mb-4 flex flex-col items-center
                           justify-center gap-2.5 rounded-[var(--radius-tile)]
                           border border-dashed border-hairline bg-surface-2
                           text-text-muted active:scale-[0.99] transition-transform"
              >
                <Film size={28} />
                <span className="text-[14px]">Выбрать видео</span>
                <span className="text-[12px] text-text-faint">
                  до {MAX_SECONDS} секунд, до {MAX_BYTES / (1024 * 1024)} МБ
                </span>
              </button>
            )}

            <textarea
              value={caption}
              onChange={(e) => setCaption(e.target.value.slice(0, MAX_CAPTION))}
              rows={2}
              placeholder="Подпись — необязательно"
              aria-label="Подпись к ролику"
              className="w-full px-3.5 py-3 mb-1.5 rounded-[var(--radius-tile)]
                         bg-surface-2 border border-hairline text-[15px] resize-none
                         placeholder:text-text-muted focus:outline-none
                         focus:border-accent/60"
            />
            <p className="text-[12px] text-text-muted text-right mb-4">
              {caption.length} / {MAX_CAPTION}
            </p>

            {error && (
              <p
                role="alert"
                className="mb-3 px-3.5 py-2.5 rounded-[var(--radius-tile)]
                           bg-danger/12 border border-danger/30 text-danger text-[13px]"
              >
                {error}
              </p>
            )}

            <div className="flex gap-2.5">
              {preview && (
                <Button variant="secondary" size="lg" onClick={reset} disabled={busy}>
                  Другое
                </Button>
              )}
              <Button
                size="lg"
                fullWidth
                disabled={!file || busy}
                onClick={publish}
              >
                {busy ? <Spinner size={20} /> : "Опубликовать"}
              </Button>
            </div>

            <p className="text-[12px] text-text-faint mt-4 leading-snug">
              Первый кадр проходит проверку — на видео должно быть видно вас, без
              наготы и чужих фото.
            </p>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
