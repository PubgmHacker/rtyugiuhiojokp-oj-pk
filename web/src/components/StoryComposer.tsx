/**
 * Публикация истории.
 *
 * Предпросмотр обязателен: кадр уходит на сутки без правок, и увидеть
 * его до отправки — единственная возможность передумать.
 *
 * Аудиторию спрашиваем прямо, а не прячем в настройки. «Всем» означает,
 * что фотографию увидят посторонние; выбор такого масштаба человек должен
 * делать сознательно, а не обнаруживать по факту.
 */
import { useEffect, useRef, useState } from "react";
import { Globe, Heart, ImagePlus } from "lucide-react";
import { Sheet } from "./Sheet";
import { Button } from "./ui";
import { haptic } from "../lib/haptics";
import { publishStory, type Story } from "../lib/api";

interface Props {
  open: boolean;
  onClose: () => void;
  onPublished: (story: Story) => void;
}

export function StoryComposer({ open, onClose, onPublished }: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [caption, setCaption] = useState("");
  const [audience, setAudience] = useState<"matches" | "everyone">("matches");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  // Ссылку на предпросмотр обязательно отзываем: каждый выбранный кадр
  // иначе остаётся в памяти вкладки до перезагрузки.
  useEffect(() => {
    if (!file) {
      setPreview(null);
      return;
    }
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  useEffect(() => {
    if (!open) {
      setFile(null);
      setCaption("");
      setAudience("matches");
      setError(null);
    }
  }, [open]);

  const выбрать = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    if (!f.type.startsWith("image/")) {
      setError("Нужна картинка");
      return;
    }
    if (f.size > 10 * 1024 * 1024) {
      setError("Файл больше 10 МБ — сожми или выбери другой");
      return;
    }
    setError(null);
    setFile(f);
    haptic("light");
  };

  const выложить = async () => {
    if (!file || saving) return;
    setSaving(true);
    setError(null);
    try {
      const story = await publishStory(file, caption, audience);
      haptic("medium");
      onPublished(story);
      onClose();
    } catch (e: any) {
      const код = e?.response?.status;
      setError(
        код === 422
          ? e.response.data?.detail || "Кадр не прошёл проверку"
          : код === 409
            ? e.response.data?.detail || "Лимит историй на сутки"
            : код === 503
              ? "Хранилище недоступно — попробуй позже"
              : "Не получилось выложить",
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="Новая история"
      subtitle="Исчезнет через 24 часа"
    >
      <input
        ref={fileRef}
        type="file"
        accept="image/*"
        onChange={выбрать}
        className="hidden"
      />

      {error && (
        <div className="mb-3 rounded-[10px] border border-danger/30 bg-danger/10 px-3 py-2 text-[13px] text-danger">
          {error}
        </div>
      )}

      {preview ? (
        <button
          onClick={() => fileRef.current?.click()}
          className="relative block w-full overflow-hidden rounded-[16px] border border-hairline"
          style={{ aspectRatio: "4 / 5" }}
        >
          <img src={preview} alt="" className="h-full w-full object-cover" />
          {caption && (
            <span className="absolute inset-x-0 bottom-0 bg-scrim px-4 pb-4 pt-8 text-left text-[15px] font-medium text-white">
              {caption}
            </span>
          )}
          <span className="absolute right-2 top-2 rounded-full bg-black/55 px-2.5 py-1 text-[12px] text-white backdrop-blur">
            Заменить
          </span>
        </button>
      ) : (
        <button
          onClick={() => fileRef.current?.click()}
          className="grid w-full place-items-center gap-2 rounded-[16px] border border-dashed border-hairline bg-surface py-14 text-text-muted transition-colors active:bg-surface-2"
        >
          <ImagePlus size={28} />
          <span className="text-[14px]">Выбрать кадр</span>
        </button>
      )}

      <input
        value={caption}
        onChange={(e) => setCaption(e.target.value)}
        maxLength={200}
        placeholder="Подпись — необязательно"
        className="mt-3 w-full rounded-[10px] border border-hairline bg-surface-2 px-3 py-2.5 text-[15px] text-text outline-none placeholder:text-text-faint focus:border-accent"
      />

      <div className="mt-3 grid grid-cols-2 gap-2">
        {(
          [
            ["matches", Heart, "Только пары", "Те, с кем совпало"],
            ["everyone", Globe, "Всем", "Ещё и кто откроет анкету"],
          ] as const
        ).map(([key, Icon, title, hint]) => (
          <button
            key={key}
            onClick={() => {
              haptic("light");
              setAudience(key);
            }}
            className={`rounded-[12px] border px-3 py-2.5 text-left transition-colors ${
              audience === key
                ? "border-accent bg-accent-dim"
                : "border-hairline bg-surface"
            }`}
          >
            <span className="flex items-center gap-1.5">
              <Icon size={15} className={audience === key ? "text-accent" : "text-text-muted"} />
              <span className="text-[14px] font-medium text-text">{title}</span>
            </span>
            <span className="mt-0.5 block text-[11.5px] leading-tight text-text-faint">
              {hint}
            </span>
          </button>
        ))}
      </div>

      <Button
        fullWidth
        className="mt-4 mb-1"
        loading={saving}
        disabled={!file}
        onClick={выложить}
      >
        Выложить
      </Button>
    </Sheet>
  );
}
