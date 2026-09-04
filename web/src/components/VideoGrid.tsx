import { useCallback, useId, useState } from "react";
import { Video, X, Plus } from "lucide-react";
import { uploadProfileVideo } from "../lib/api";
import { grabVideoCovers, CoverFailed } from "../lib/videoCover";
import { MAX_VIDEO_MB } from "../lib/profileOptions";
import { haptic } from "../lib/haptics";
import { Spinner } from "./ui";

/**
 * Видеоролики анкеты — дополнение к фото, показываются в карточке после них.
 *
 * Правила загрузки те же, что у роликов ленты (ReelUploader): сервер видео
 * не разбирает, кадры с разных таймкодов снимает браузер (grabVideoCovers),
 * и модерация смотрит на них — без кадров загрузки нет. «Главного» видео
 * нет: главным медиа анкеты остаётся первое фото.
 */

export interface VideoSlot {
  /** Свой идентификатор: индекс в массиве не годится, пока идёт загрузка. */
  id: string;
  url?: string;
  uploading?: boolean;
  error?: string;
}

let videoSeq = 0;

/** Состояние слотов и операции над ними: загрузка и удаление. */
export function useVideoSlots(initialUrls: string[]) {
  const [videos, setVideos] = useState<VideoSlot[]>(() =>
    // file_id из бота (не-URL) в вебе не проиграть — показываем и даём
    // удалять только настоящие ссылки; сервер их и так наружу не отдаёт
    initialUrls
      .filter((url) => /^https?:\/\//.test(url))
      .map((url) => ({ id: `vinit-${videoSeq++}`, url }))
  );

  const addVideo = useCallback(async (file: File) => {
    const id = `vup-${videoSeq++}`;

    if (file.size > MAX_VIDEO_MB * 1024 * 1024) {
      haptic("error");
      setVideos((v) => [
        ...v,
        { id, error: `Видео больше ${MAX_VIDEO_MB} МБ` },
      ]);
      return;
    }

    setVideos((v) => [...v, { id, uploading: true }]);
    try {
      const covers = await grabVideoCovers(file);
      const { url } = await uploadProfileVideo(file, covers);
      setVideos((v) => v.map((s) => (s.id === id ? { id, url } : s)));
      haptic("success");
    } catch (e: any) {
      const detail =
        e instanceof CoverFailed
          ? e.message
          : e?.response?.data?.detail ?? "Видео не подошло";
      setVideos((v) => v.map((s) => (s.id === id ? { id, error: detail } : s)));
      haptic("error");
    }
  }, []);

  const removeVideo = useCallback((id: string) => {
    haptic("light");
    setVideos((v) => v.filter((s) => s.id !== id));
  }, []);

  return { videos, addVideo, removeVideo };
}

export default function VideoGrid({
  videos,
  max,
  onPick,
  onRemove,
}: {
  videos: VideoSlot[];
  max: number;
  onPick: (f: File) => void;
  onRemove: (id: string) => void;
}) {
  // Четыре колонки при трёх слотах — не обрезанный ряд, а левый строй: ячейка
  // выходит ровно того же размера, что маленькая плитка фотосетки. Видео —
  // дополнение к фото, и на общем экране оно не должно быть крупнее того,
  // что дополняет; на сетке из трёх колонок получалось ровно наоборот.
  return (
    <div className="grid grid-cols-4 gap-2">
      {Array.from({ length: max }).map((_, i) => (
        <VideoTile
          key={videos[i]?.id ?? `vempty-${i}`}
          slot={videos[i]}
          onPick={onPick}
          onRemove={() => videos[i] && onRemove(videos[i].id)}
          next={i === videos.length}
        />
      ))}
    </div>
  );
}

function VideoTile({
  slot,
  onPick,
  onRemove,
  next,
}: {
  slot?: VideoSlot;
  onPick: (f: File) => void;
  onRemove: () => void;
  /** Ближайший свободный слот: ролик ляжет именно сюда. */
  next: boolean;
}) {
  const inputId = useId();

  const fileInput = (
    <input
      id={inputId}
      type="file"
      accept="video/mp4,video/quicktime,video/webm"
      className="hidden"
      onChange={(e) => {
        const f = e.target.files?.[0];
        if (!f) return;
        onPick(f);
        // Сбрасываем значение, иначе повторный выбор того же файла не сработает
        e.target.value = "";
      }}
    />
  );

  if (slot?.url) {
    return (
      <div className="relative aspect-[3/4] rounded-[var(--radius-tile)] overflow-hidden bg-surface-2">
        {/* preload=metadata достаточно для первого кадра-постера; звук и
            автоплей в сетке редактирования не нужны */}
        <video
          src={slot.url}
          muted
          playsInline
          preload="metadata"
          className="w-full h-full object-cover"
        />
        <span
          className="absolute bottom-1.5 left-1.5 w-6 h-6 rounded-full
                     bg-black/55 backdrop-blur-sm flex items-center justify-center"
        >
          <Video size={12} className="text-white" />
        </span>
        <button
          aria-label="Удалить видео"
          onClick={onRemove}
          className="absolute top-1.5 right-1.5 z-10 w-7 h-7 rounded-full
                     bg-black/60 backdrop-blur-sm flex items-center justify-center"
        >
          <X size={15} />
        </button>
      </div>
    );
  }

  if (slot?.uploading) {
    return (
      <div className="aspect-[3/4] rounded-[var(--radius-tile)] skeleton flex flex-col items-center justify-center gap-1.5">
        <Spinner size={20} />
        <span className="text-[10px] text-text-faint">Проверяем…</span>
      </div>
    );
  }

  if (slot?.error) {
    return (
      <label
        htmlFor={inputId}
        className="aspect-[3/4] rounded-[var(--radius-tile)] cursor-pointer
                   border border-danger/40 bg-danger/10 p-2
                   flex flex-col items-center justify-center text-center gap-1"
      >
        <X size={18} className="text-danger" />
        <span className="text-[10.5px] leading-tight text-danger">{slot.error}</span>
        {fileInput}
      </label>
    );
  }

  // Свободный слот остаётся живым, как и в фотосетке: загрузка всё равно идёт
  // в конец очереди, куда бы ни ткнули, а инертные ячейки читались заглушками.
  return (
    <label
      htmlFor={inputId}
      className={`aspect-[3/4] rounded-[var(--radius-tile)] bg-surface cursor-pointer
                  flex items-center justify-center transition-colors active:bg-surface-2 ${
                    next
                      ? "border border-dashed border-accent/45"
                      : "border border-hairline"
                  }`}
    >
      {next ? (
        <Video size={19} strokeWidth={2.1} aria-hidden="true" className="text-accent" />
      ) : (
        <Plus size={18} strokeWidth={2.2} aria-hidden="true" className="text-text-faint" />
      )}
      <span className="sr-only">Добавить видео</span>
      {fileInput}
    </label>
  );
}
