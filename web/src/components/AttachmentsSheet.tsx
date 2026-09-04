/**
 * Витрина вложений переписки: сколько и чего переслали друг другу.
 *
 * Зачем вообще. К третьей неделе переписки фотография, которую человек
 * присылал, лежит в тысяче сообщений выше, и найти её прокруткой нельзя. В
 * топовых мессенджерах это решено одинаково — отдельный экран «медиа,
 * голосовые, ссылки» с счётчиками. Здесь то же, но с двумя нашими правками.
 *
 * ПЕРВАЯ: плитка кружка сохраняет свою фигуру. У нас видеокружок бывает
 * сердцем и звездой, и превращать его в грид одинаковых квадратов —
 * выбрасывать то, что человек выбирал руками.
 *
 * ВТОРАЯ: строка голосового рисует ту же волну, что в пузыре сообщения.
 * Иначе список голосовых — двадцать неразличимых строк «0:14, вы»: узнать в
 * нём нужное невозможно, а форма волны узнаётся сразу.
 *
 * Тап по любой строке ведёт К СООБЩЕНИЮ, а не открывает файл: вложение почти
 * всегда ищут ради разговора вокруг него. Открыть ссылку наружу — отдельная
 * кнопка справа, чтобы тап по строке никогда не выбрасывал из приложения.
 */
import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { ExternalLink, Film, Image as ImageIcon, Mic, Play } from "lucide-react";
import { Sheet } from "./Sheet";
import { Button, Spinner } from "./ui";
import { haptic } from "../lib/haptics";
import { noteMaskStyle } from "../lib/noteShapes";
import { useЯзык, форматДаты, форматМесяца, type Язык } from "../lib/i18n";
import {
  getChatAttachments,
  type ChatAttachment,
  type ChatAttachments,
} from "../lib/api";

type Вкладка = "media" | "voice" | "link";

/** «2:07» — у кружка и голосового длительность главный ориентир в списке. */
function ммсс(секунд: number | null): string {
  const всего = Math.max(0, Math.round(секунд ?? 0));
  return `${Math.floor(всего / 60)}:${String(всего % 60).padStart(2, "0")}`;
}

/** «3 голосовых», но «1 голосовое»: счётчик с чужим числом читается как брак. */
function склонение(n: number, одно: string, два: string, много: string): string {
  const сто = n % 100;
  if (сто >= 11 && сто <= 14) return много;
  const один = n % 10;
  if (один === 1) return одно;
  if (один >= 2 && один <= 4) return два;
  return много;
}

/**
 * Цвет плитки домена. Фавиконки намеренно не тянем: это запрос к чужому
 * серверу прямо со страницы переписки, то есть наводка на то, какие ссылки
 * человек хранит. Хеш даёт стабильный оттенок — t.me всегда одного цвета, и
 * список читается как список сайтов, а не как двадцать серых квадратов.
 */
function тонДомена(host: string): string {
  let h = 0x811c9dc5;
  for (const символ of host || "?") {
    h ^= символ.codePointAt(0) ?? 0;
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return `hsl(${h % 360} 44% 38%)`;
}

interface Группа {
  ключ: string;
  подпись: string;
  элементы: ChatAttachment[];
}

/**
 * Разбивка по месяцам. Сервер отдаёт список от новых к старым, поэтому
 * достаточно склеивать подряд идущие — сортировать заново нечего.
 */
function погруппам(список: ChatAttachment[], язык: Язык): Группа[] {
  const этотГод = new Date().getFullYear();
  const итог: Группа[] = [];
  for (const вложение of список) {
    const дата = вложение.created_at ? new Date(вложение.created_at) : null;
    const ключ = дата ? `${дата.getFullYear()}-${дата.getMonth()}` : "без-даты";
    const последняя = итог[итог.length - 1];
    if (последняя && последняя.ключ === ключ) {
      последняя.элементы.push(вложение);
      continue;
    }
    итог.push({
      ключ,
      подпись: дата ? форматМесяца(дата, язык, дата.getFullYear() !== этотГод) : "",
      элементы: [вложение],
    });
  }
  return итог;
}

const ПОЛОС = 32;
const РОВНАЯ_ВОЛНА = "3454645354634536454635463545";

/** Та же строка цифр, что в пузыре сообщения, только 32 полосы вместо сорока. */
function МиниВолна({ цифры }: { цифры: string }) {
  const полосы = useMemo(() => {
    const исходник = (цифры || "").replace(/\D/g, "") || РОВНАЯ_ВОЛНА;
    return Array.from({ length: ПОЛОС }, (_, i) => {
      const от = Math.floor((i * исходник.length) / ПОЛОС);
      const до = Math.max(от + 1, Math.floor(((i + 1) * исходник.length) / ПОЛОС));
      let пик = 0;
      for (let j = от; j < до && j < исходник.length; j += 1) {
        пик = Math.max(пик, Number(исходник[j]) || 0);
      }
      return пик;
    });
  }, [цифры]);

  return (
    <span aria-hidden className="flex h-[22px] items-end gap-[2px]">
      {полосы.map((пик, i) => (
        <span
          key={i}
          className="flex-1 rounded-full bg-accent/45"
          style={{ height: `${20 + пик * 8.8}%` }}
        />
      ))}
    </span>
  );
}

function ЗаголовокМесяца({ подпись }: { подпись: string }) {
  if (!подпись) return null;
  return (
    <h3 className="px-1 pb-2 pt-3 text-[12.5px] font-semibold uppercase tracking-[0.06em] text-text-faint first:pt-0">
      {подпись}
    </h3>
  );
}

function МедиаПлитка({
  вложение,
  прыгнуть,
}: {
  вложение: ChatAttachment;
  прыгнуть: (messageId: string) => void;
}) {
  const кружок = вложение.kind === "video_note";
  const ролик = вложение.kind === "reel";
  const название = кружок ? "видеокружок" : ролик ? "ролик" : "фото";

  return (
    <button
      type="button"
      aria-label={`Перейти к сообщению: ${название}`}
      onClick={() => {
        haptic("light");
        прыгнуть(вложение.message_id);
      }}
      className="relative aspect-square overflow-hidden rounded-[var(--radius-tile)] border border-hairline
                 bg-surface-2 transition-transform active:scale-[0.97]
                 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
    >
      {вложение.poster ? (
        кружок ? (
          // Маска фигуры — тот же модуль, что рисует кружок в переписке.
          <span className="absolute inset-[7%] block" style={noteMaskStyle(вложение.shape)}>
            <img
              src={вложение.poster}
              alt=""
              loading="lazy"
              decoding="async"
              className="h-full w-full object-cover"
            />
          </span>
        ) : (
          <img
            src={вложение.poster}
            alt=""
            loading="lazy"
            decoding="async"
            className="absolute inset-0 h-full w-full object-cover"
          />
        )
      ) : (
        <span className="absolute inset-0 grid place-items-center text-text-faint">
          {кружок ? <Play size={18} /> : ролик ? <Film size={18} /> : <ImageIcon size={18} />}
        </span>
      )}

      {ролик && (
        <span className="absolute bottom-1.5 left-1.5 grid h-5 w-5 place-items-center rounded-full bg-black/55 text-white backdrop-blur-[2px]">
          <Film size={11} />
        </span>
      )}
      {(кружок || ролик) && вложение.duration ? (
        <span className="absolute bottom-1.5 right-1.5 rounded-full bg-black/55 px-1.5 py-[3px] text-[10px] font-semibold leading-none tabular-nums text-white backdrop-blur-[2px]">
          {ммсс(вложение.duration)}
        </span>
      ) : null}
    </button>
  );
}

function ГолосоваяСтрока({
  вложение,
  собеседник,
  язык,
  прыгнуть,
}: {
  вложение: ChatAttachment;
  собеседник: string;
  язык: Язык;
  прыгнуть: (messageId: string) => void;
}) {
  const дата = вложение.created_at ? new Date(вложение.created_at) : null;

  return (
    <button
      type="button"
      aria-label={`Перейти к голосовому ${ммсс(вложение.duration)}`}
      onClick={() => {
        haptic("light");
        прыгнуть(вложение.message_id);
      }}
      className="flex w-full items-center gap-3 rounded-[var(--radius-tile)] px-1.5 py-2.5 text-left
                 transition-colors active:bg-surface-2
                 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
    >
      <span className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-accent-dim text-accent">
        <Mic size={17} />
      </span>
      <span className="min-w-0 flex-1">
        <МиниВолна цифры={вложение.waveform} />
        <span className="mt-1.5 flex items-center gap-1.5 text-[11.5px] text-text-muted">
          <span className="font-semibold tabular-nums text-text-secondary">
            {ммсс(вложение.duration)}
          </span>
          <span aria-hidden>·</span>
          <span className="truncate">{вложение.from_me ? "вы" : собеседник}</span>
          {дата && (
            <>
              <span aria-hidden>·</span>
              <span className="shrink-0">{форматДаты(дата, язык)}</span>
            </>
          )}
        </span>
      </span>
    </button>
  );
}

function СсылочнаяСтрока({
  вложение,
  прыгнуть,
}: {
  вложение: ChatAttachment;
  прыгнуть: (messageId: string) => void;
}) {
  const домен = вложение.host || "ссылка";
  // Схему и www сервер уже снял; здесь убираем хвостовой слеш, из-за которого
  // короткая ссылка выглядит обрезанной.
  const адрес = вложение.url.replace(/^https?:\/\//i, "").replace(/\/$/, "");

  return (
    <div className="flex items-center gap-1">
      <button
        type="button"
        aria-label={`Перейти к сообщению со ссылкой ${домен}`}
        onClick={() => {
          haptic("light");
          прыгнуть(вложение.message_id);
        }}
        className="flex min-w-0 flex-1 items-center gap-3 rounded-[var(--radius-tile)] px-1.5 py-2.5 text-left
                   transition-colors active:bg-surface-2
                   focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        <span
          aria-hidden
          className="grid h-11 w-11 shrink-0 place-items-center rounded-[13px] text-[17px] font-bold uppercase text-white"
          style={{ background: тонДомена(вложение.host) }}
        >
          {домен.slice(0, 1)}
        </span>
        <span className="min-w-0">
          <span className="block truncate text-[14.5px] font-medium text-text">{домен}</span>
          <span className="block truncate text-[11.5px] text-text-muted">{адрес}</span>
        </span>
      </button>
      <a
        href={вложение.url}
        target="_blank"
        rel="noopener noreferrer nofollow"
        aria-label={`Открыть ${домен} в браузере`}
        onClick={() => haptic("light")}
        className="tap-target grid h-11 w-11 shrink-0 place-items-center rounded-full text-text-muted
                   transition-colors active:bg-surface-2
                   focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        <ExternalLink size={16} />
      </a>
    </div>
  );
}

interface Props {
  open: boolean;
  onClose: () => void;
  matchId: string;
  /** Имя собеседника — подпись «кто отправил» в строках голосовых. */
  partnerName: string;
  /** Прокрутка переписки к сообщению. Лист закрывает вызывающий экран. */
  onJump: (messageId: string) => void;
}

export function AttachmentsSheet({ open, onClose, matchId, partnerName, onJump }: Props) {
  const язык = useЯзык();
  const [данные, setДанные] = useState<ChatAttachments | null>(null);
  const [загрузка, setЗагрузка] = useState(false);
  const [ошибка, setОшибка] = useState(false);
  const [попытка, setПопытка] = useState(0);
  const [вкладка, setВкладка] = useState<Вкладка>("media");

  // Данные чужой переписки не показываем ни кадра: чат мог смениться, пока
  // лист был закрыт.
  useEffect(() => {
    setДанные(null);
  }, [matchId]);

  // Перечитываем на каждое открытие: за время разговора список успевает
  // вырасти, а кэш здесь сэкономил бы один запрос ценой устаревшей витрины.
  useEffect(() => {
    if (!open) return;
    let жив = true;
    setЗагрузка(true);
    setОшибка(false);
    getChatAttachments(matchId)
      .then((ответ) => {
        if (жив) setДанные(ответ);
      })
      .catch(() => {
        if (жив) setОшибка(true);
      })
      .finally(() => {
        if (жив) setЗагрузка(false);
      });
    return () => {
      жив = false;
    };
  }, [open, matchId, попытка]);

  const медиаВсего = данные ? данные.photos + данные.reels + данные.video_notes : 0;

  // Пустые вкладки не рисуем вовсе: вкладка с нулём — тупик, в который
  // человек обязательно ткнёт. Так же ведут себя топовые мессенджеры.
  const вкладки = useMemo(
    () =>
      (
        [
          { key: "media" as const, label: "Медиа", count: медиаВсего },
          { key: "voice" as const, label: "Голосовые", count: данные?.voices ?? 0 },
          { key: "link" as const, label: "Ссылки", count: данные?.links ?? 0 },
        ] satisfies { key: Вкладка; label: string; count: number }[]
      ).filter((в) => в.count > 0),
    [данные, медиаВсего],
  );

  const активная: Вкладка = вкладки.some((в) => в.key === вкладка)
    ? вкладка
    : (вкладки[0]?.key ?? "media");
  const индекс = Math.max(
    0,
    вкладки.findIndex((в) => в.key === активная),
  );

  const сводка = useMemo(() => {
    if (!данные) return undefined;
    const части: string[] = [];
    if (данные.photos) части.push(`${данные.photos} фото`);
    if (данные.reels) {
      части.push(`${данные.reels} ${склонение(данные.reels, "ролик", "ролика", "роликов")}`);
    }
    if (данные.video_notes) {
      части.push(
        `${данные.video_notes} ${склонение(данные.video_notes, "кружок", "кружка", "кружков")}`,
      );
    }
    if (данные.voices) {
      части.push(
        `${данные.voices} ${склонение(данные.voices, "голосовое", "голосовых", "голосовых")}`,
      );
    }
    if (данные.links) {
      части.push(`${данные.links} ${склонение(данные.links, "ссылка", "ссылки", "ссылок")}`);
    }
    return части.length
      ? части.join(" · ")
      : "Здесь появятся фото, кружки, голосовые и ссылки из переписки";
  }, [данные]);

  const список = данные
    ? активная === "media"
      ? данные.media
      : активная === "voice"
        ? данные.voice
        : данные.link
    : [];
  const группы = useMemo(() => погруппам(список, язык), [список, язык]);

  const прыгнуть = (messageId: string) => {
    onClose();
    onJump(messageId);
  };

  const всегоПоВкладке = данные
    ? активная === "media"
      ? медиаВсего
      : активная === "voice"
        ? данные.voices
        : данные.links
    : 0;

  return (
    <Sheet open={open} onClose={onClose} title="Вложения" subtitle={сводка} maxHeight="88vh">
      {загрузка && !данные ? (
        <div className="grid min-h-[220px] place-items-center text-accent">
          <Spinner size={26} />
        </div>
      ) : ошибка && !данные ? (
        <div className="grid min-h-[220px] place-items-center px-6 text-center">
          <div>
            <p className="text-[14px] text-text-muted">Не удалось загрузить вложения</p>
            <Button
              variant="secondary"
              size="sm"
              className="mt-3"
              onClick={() => setПопытка((п) => п + 1)}
            >
              Повторить
            </Button>
          </div>
        </div>
      ) : !данные || вкладки.length === 0 ? (
        <div className="grid min-h-[220px] place-items-center px-6 pb-4 text-center">
          <div>
            <span className="mx-auto mb-3 grid h-14 w-14 place-items-center rounded-full bg-surface-2 text-text-faint">
              <ImageIcon size={22} />
            </span>
            <p className="text-[14.5px] font-medium text-text">Вложений пока нет</p>
            <p className="mt-1 text-[12.5px] leading-snug text-text-muted">
              Фото, кружки, голосовые и ссылки из этой переписки соберутся здесь сами.
            </p>
          </div>
        </div>
      ) : (
        <>
          {/* Полоса вкладок липнет к верху: в гриде на сто плиток она иначе
              уезжает вверх и переключаться приходится прокруткой обратно. */}
          <div className="sticky top-0 z-10 -mx-5 mb-1 bg-bg-elevated px-5">
            <div role="tablist" aria-label="Вид вложений" className="relative flex border-b border-hairline">
              {вкладки.map((в) => (
                <button
                  key={в.key}
                  type="button"
                  role="tab"
                  aria-selected={в.key === активная}
                  onClick={() => {
                    haptic("select");
                    setВкладка(в.key);
                  }}
                  className={`flex-1 pb-2.5 pt-1 text-[13.5px] font-medium transition-colors
                              focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent
                              ${в.key === активная ? "text-text" : "text-text-muted"}`}
                >
                  {в.label}
                  <span className="ml-1.5 text-[12px] tabular-nums opacity-70">{в.count}</span>
                </button>
              ))}
              <motion.span
                aria-hidden
                className="absolute bottom-0 left-0 h-[2px] rounded-full bg-accent"
                style={{ width: `${100 / вкладки.length}%` }}
                animate={{ x: `${индекс * 100}%` }}
                transition={{ type: "spring", stiffness: 420, damping: 34 }}
              />
            </div>
          </div>

          <div role="tabpanel" aria-label={вкладки[индекс]?.label ?? "Вложения"} className="pb-3">
            {активная === "voice" && данные.voice_seconds > 0 && (
              <p className="px-1.5 pt-1 text-[12px] text-text-muted">
                Всего{" "}
                {данные.voice_seconds < 60
                  ? `${данные.voice_seconds} с`
                  : `${Math.round(данные.voice_seconds / 60)} мин`}{" "}
                записи
              </p>
            )}

            {список.length === 0 ? (
              <p className="py-12 text-center text-[13px] text-text-muted">
                Эти вложения больше недоступны
              </p>
            ) : (
              группы.map((группа) => (
                <section key={группа.ключ}>
                  <ЗаголовокМесяца подпись={группа.подпись} />
                  {активная === "media" ? (
                    <div className="grid grid-cols-3 gap-1.5">
                      {группа.элементы.map((вложение) => (
                        <МедиаПлитка
                          key={`${вложение.message_id}:${вложение.url}`}
                          вложение={вложение}
                          прыгнуть={прыгнуть}
                        />
                      ))}
                    </div>
                  ) : активная === "voice" ? (
                    <div className="divide-y divide-hairline">
                      {группа.элементы.map((вложение) => (
                        <ГолосоваяСтрока
                          key={вложение.message_id}
                          вложение={вложение}
                          собеседник={partnerName}
                          язык={язык}
                          прыгнуть={прыгнуть}
                        />
                      ))}
                    </div>
                  ) : (
                    <div className="divide-y divide-hairline">
                      {группа.элементы.map((вложение) => (
                        <СсылочнаяСтрока
                          key={`${вложение.message_id}:${вложение.url}`}
                          вложение={вложение}
                          прыгнуть={прыгнуть}
                        />
                      ))}
                    </div>
                  )}
                </section>
              ))
            )}

            {/* Счётчик сверху считает всю переписку, а список — страницу.
                Молчать о разнице нельзя: человек решит, что остальное пропало. */}
            {всегоПоВкладке > список.length && список.length > 0 && (
              <p className="pt-3 text-center text-[11.5px] leading-snug text-text-faint">
                Показаны последние {список.length} — остальное осталось в переписке
              </p>
            )}
          </div>
        </>
      )}
    </Sheet>
  );
}
