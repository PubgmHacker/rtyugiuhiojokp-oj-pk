import { useCallback, useId, useState } from "react";
import { Camera, X, Star, Plus } from "lucide-react";
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
  // Главное фото занимает столько места, сколько весит в продукте: по нему
  // свайпают в деке, оно стоит в лайках, чатах и «Гостях». Ведущая плитка 2×2
  // в сетке из четырёх колонок, четыре маленьких ровно закрывают оставшиеся
  // ячейки двух рядов — сетка сходится без дырки в конце (3×2 при пяти слотах
  // всегда оставляла шестую ячейку пустой) и становится на ~78 px короче.
  // Раскладка сходится, только когда остаток делится на четыре: 5, 9, 13.
  const ведущая = (max - 1) % 4 === 0;

  return (
    <div className={ведущая ? "grid grid-cols-4 gap-2" : "grid grid-cols-3 gap-2.5"}>
      {Array.from({ length: max }).map((_, i) => (
        <PhotoTile
          key={photos[i]?.id ?? `empty-${i}`}
          slot={photos[i]}
          isPrimary={i === 0}
          lead={ведущая && i === 0}
          onPick={onPick}
          onRemove={() => photos[i] && onRemove(photos[i].id)}
          onMakePrimary={() => photos[i] && onMakePrimary(photos[i].id)}
          next={i === photos.length}
        />
      ))}
    </div>
  );
}

function PhotoTile({
  slot,
  isPrimary,
  lead,
  onPick,
  onRemove,
  onMakePrimary,
  next,
}: {
  slot?: PhotoSlot;
  isPrimary: boolean;
  /** Ведущая ячейка 2×2 — только под главное фото. */
  lead: boolean;
  onPick: (f: File) => void;
  onRemove: () => void;
  onMakePrimary: () => void;
  /** Ближайший свободный слот: снимок ляжет именно сюда. */
  next: boolean;
}) {
  const inputId = useId();
  // Высоту двух рядов ведущей плитке задают соседние маленькие: свой
  // aspect-ratio здесь дал бы вторую, спорящую с ними меру.
  const рамка = lead ? "col-span-2 row-span-2" : "aspect-[3/4]";

  const fileInput = (
    <input
      id={inputId}
      type="file"
      accept="image/*"
      className="hidden"
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
      <div className={`relative ${рамка} rounded-[var(--radius-tile)] overflow-hidden bg-surface-2`}>
        <img src={slot.url} alt="" className="w-full h-full object-cover" />
        {isPrimary ? (
          <span
            className={`absolute top-2 left-2 rounded-full bg-accent font-bold
                        text-white flex items-center gap-1 ${
                          lead ? "px-2.5 py-1 text-[11.5px]" : "px-2 py-0.5 text-[10px]"
                        }`}
          >
            <Star size={lead ? 11 : 9} fill="currentColor" />
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
            {/* На маленькой плитке подпись шире самой плитки и лезет
                на соседнюю колонку — там остаётся один значок, слово
                живёт только на крупной ячейке */}
            <span
              className={`rounded-full bg-black/55 backdrop-blur-sm text-white
                          font-semibold flex items-center ${
                            lead
                              ? "gap-1 px-2 py-0.5 text-[10px]"
                              : "w-6 h-6 justify-center"
                          }`}
            >
              <Star size={lead ? 9 : 12} />
              {lead ? "Главным" : null}
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
      <div className={`${рамка} rounded-[var(--radius-tile)] skeleton flex items-center justify-center`}>
        <Spinner size={20} />
      </div>
    );
  }

  if (slot?.error) {
    return (
      <label
        htmlFor={inputId}
        className={`${рамка} rounded-[var(--radius-tile)] cursor-pointer
                    border border-danger/40 bg-danger/10 p-2
                    flex flex-col items-center justify-center text-center gap-1`}
      >
        <X size={18} className="text-danger" />
        <span className="text-[10.5px] leading-tight text-danger">{slot.error}</span>
        {fileInput}
      </label>
    );
  }

  // Свободный слот — это приглашение, а не выключенный прямоугольник. Раньше
  // всё, что дальше очереди, стояло инертным (`pointer-events-none`, без
  // значка): из пяти ячеек четыре читались как заглушки, и экран выглядел
  // наполовину сломанным. Загрузка всё равно идёт в конец списка, куда бы ни
  // ткнули, — значит и вести себя все свободные ячейки должны одинаково.
  // Пунктир и акцент остаются у ближайшей: она показывает, куда ляжет снимок.
  return (
    <label
      htmlFor={inputId}
      className={`${рамка} rounded-[var(--radius-tile)] bg-surface cursor-pointer
                  flex flex-col items-center justify-center gap-2
                  transition-colors active:bg-surface-2 ${
                    next
                      ? "border border-dashed border-accent/45"
                      : "border border-hairline"
                  }`}
    >
      {lead ? (
        <>
          <span aria-hidden="true" className="nav-tile tile-accent">
            <Camera size={19} strokeWidth={2.1} />
          </span>
          <span className="text-caption text-text-muted">Главное фото</span>
        </>
      ) : (
        <>
          <Plus
            size={20}
            strokeWidth={2.2}
            aria-hidden="true"
            className={next ? "text-accent" : "text-text-faint"}
          />
          <span className="sr-only">Добавить фото</span>
        </>
      )}
      {fileInput}
    </label>
  );
}
