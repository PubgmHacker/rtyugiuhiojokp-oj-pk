import { useCallback, useId, useState } from "react";
import { Camera, X, Star } from "lucide-react";
import { uploadPhoto } from "../lib/api";
import { haptic } from "../lib/haptics";
import { Spinner } from "./ui";

/**
 * Сетка фотографий анкеты — общая для онбординга и точечного редактирования.
 *
 * Жила внутри Onboarding.tsx; вынесена, когда появился экран «Редактирование
 * анкеты»: правила здесь неочевидные (свой id слота на время загрузки,
 * HEIC→JPEG в браузере, «главное» переносом в начало), и две копии этих
 * правил разошлись бы на первом же фиксе.
 */

export interface PhotoSlot {
  /** Свой идентификатор: индекс в массиве не годится, пока идёт загрузка. */
  id: string;
  url?: string;
  uploading?: boolean;
  error?: string;
}

let photoSeq = 0;

/** Состояние слотов и операции над ними: загрузка, удаление, «главное». */
export function usePhotoSlots(initialUrls: string[]) {
  const [photos, setPhotos] = useState<PhotoSlot[]>(() =>
    initialUrls.map((url) => ({ id: `init-${photoSeq++}`, url }))
  );

  const addPhoto = useCallback(async (file: File) => {
    const id = `up-${photoSeq++}`;
    setPhotos((p) => [...p, { id, uploading: true }]);
    try {
      const { url } = await uploadPhoto(file);
      setPhotos((p) => p.map((s) => (s.id === id ? { id, url } : s)));
      haptic("success");
    } catch (e: any) {
      const detail = e?.response?.data?.detail ?? "Фото не подошло";
      setPhotos((p) => p.map((s) => (s.id === id ? { id, error: detail } : s)));
      haptic("error");
    }
  }, []);

  const removePhoto = useCallback((id: string) => {
    haptic("light");
    setPhotos((p) => p.filter((s) => s.id !== id));
  }, []);

  /** Сделать фото главным — переносом в начало списка.
   *
   *  Порядок массива и есть порядок показа: `photos[0]` — то, что видно на
   *  карточке в деке, в лайках, в чатах и в «Гостях». До этой кнопки главным
   *  было то фото, которое загрузили первым, и поменять его можно было
   *  единственным способом: удалить всё, что стоит перед нужным, и залить
   *  заново — вместе с повторной AI-проверкой каждого снимка. Для самого
   *  решающего поля анкеты (по нему и свайпают) это абсурдная цена.
   *
   *  Только вверх, без произвольного перетаскивания: жест drag конфликтует со
   *  свайпом шагов онбординга, а «главное» — единственный порядок, который
   *  человеку правда важен. Остальные фото сдвигаются, сохраняя свой порядок. */
  const makePrimary = useCallback((id: string) => {
    setPhotos((p) => {
      const i = p.findIndex((s) => s.id === id);
      // Уже главное или ещё грузится — двигать нечего
      if (i <= 0 || !p[i].url) return p;
      haptic("success");
      const next = [...p];
      const [фото] = next.splice(i, 1);
      next.unshift(фото);
      return next;
    });
  }, []);

  /** Вернуть слоты к списку загруженных url — «начать заново». */
  const reset = useCallback((urls: string[]) => {
    setPhotos(urls.map((url) => ({ id: `init-${photoSeq++}`, url })));
  }, []);

  return { photos, addPhoto, removePhoto, makePrimary, reset };
}

export default function PhotoGrid({
  photos,
  max,
  onPick,
  onRemove,
  onMakePrimary,
}: {
  photos: PhotoSlot[];
  max: number;
  onPick: (f: File) => void;
  onRemove: (id: string) => void;
  onMakePrimary: (id: string) => void;
}) {
  return (
    <div className="grid grid-cols-3 gap-2.5">
      {Array.from({ length: max }).map((_, i) => (
        <PhotoTile
          key={photos[i]?.id ?? `empty-${i}`}
          slot={photos[i]}
          isPrimary={i === 0}
          onPick={onPick}
          onRemove={() => photos[i] && onRemove(photos[i].id)}
          onMakePrimary={() => photos[i] && onMakePrimary(photos[i].id)}
          disabled={i > photos.length}
        />
      ))}
    </div>
  );
}

function PhotoTile({
  slot,
  isPrimary,
  onPick,
  onRemove,
  onMakePrimary,
  disabled,
}: {
  slot?: PhotoSlot;
  isPrimary: boolean;
  onPick: (f: File) => void;
  onRemove: () => void;
  onMakePrimary: () => void;
  disabled: boolean;
}) {
  const inputId = useId();

  const fileInput = (
    <input
      id={inputId}
      type="file"
      accept="image/*"
      className="hidden"
      disabled={disabled}
      onChange={(e) => {
        const f = e.target.files?.[0];
        if (!f) return;

        // HEIC/HEIF с iPhone: Pillow в API без libheif их не открывает,
        // а <input accept="image/*"> их отдаёт как есть. Конвертируем в JPEG
        // прямо в браузере через canvas — иначе загрузка обязательно упадёт
        // с "Файл не является изображением".
        const isHeic =
          /image\/(heic|heif)/i.test(f.type) ||
          /\.(heic|heif)$/i.test(f.name);

        if (isHeic) {
          const img = new Image();
          img.onload = () => {
            const canvas = document.createElement("canvas");
            canvas.width = img.naturalWidth;
            canvas.height = img.naturalHeight;
            canvas.getContext("2d")?.drawImage(img, 0, 0);
            canvas.toBlob(
              (blob) => {
                URL.revokeObjectURL(img.src);
                if (!blob) {
                  console.error("HEIC→JPEG: toBlob вернул null");
                  return;
                }
                onPick(new File([blob], f.name.replace(/\.(heic|heif)$/i, ".jpg"), {
                  type: "image/jpeg",
                }));
              },
              "image/jpeg",
              0.92,
            );
          };
          img.onerror = () => {
            URL.revokeObjectURL(img.src);
            console.error("HEIC не удалось прочитать в браузере");
          };
          img.src = URL.createObjectURL(f);
          // Сбрасываем значение, иначе повторный выбор того же файла не сработает
          e.target.value = "";
          return;
        }

        onPick(f);
        // Сбрасываем значение, иначе повторный выбор того же файла не сработает
        e.target.value = "";
      }}
    />
  );

  if (slot?.url) {
    return (
      <div className="relative aspect-[3/4] rounded-[var(--radius-tile)] overflow-hidden bg-surface-2">
        <img src={slot.url} alt="" className="w-full h-full object-cover" />
        {isPrimary ? (
          <span
            className="absolute top-1.5 left-1.5 px-2 py-0.5 rounded-full
                       bg-accent text-[10px] font-bold text-white
                       flex items-center gap-1"
          >
            <Star size={9} fill="currentColor" />
            Главное
          </span>
        ) : (
          /* Тап по самой плитке, а не по маленькой звёздочке: цель во весь
             снимок промахнуться невозможно, а всё, что можно сделать с не
             главным фото, кроме удаления, — как раз повысить его */
          <button
            onClick={onMakePrimary}
            aria-label="Сделать главным фото"
            className="absolute inset-0 flex items-end justify-start p-1.5
                       active:bg-black/25 transition-colors"
          >
            <span
              className="px-2 py-0.5 rounded-full bg-black/55 backdrop-blur-sm
                         text-[10px] font-semibold text-white
                         flex items-center gap-1"
            >
              <Star size={9} />
              Главным
            </span>
          </button>
        )}
        <button
          aria-label="Удалить фото"
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
      <div className="aspect-[3/4] rounded-[var(--radius-tile)] skeleton flex items-center justify-center">
        <Spinner size={20} />
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

  return (
    <label
      htmlFor={inputId}
      aria-disabled={disabled}
      className={`aspect-[3/4] rounded-[var(--radius-tile)] border border-dashed
                  border-hairline bg-surface flex items-center justify-center
                  ${disabled ? "opacity-35 pointer-events-none" : "cursor-pointer"}`}
    >
      <Camera size={22} className="text-text-faint" />
      {fileInput}
    </label>
  );
}
