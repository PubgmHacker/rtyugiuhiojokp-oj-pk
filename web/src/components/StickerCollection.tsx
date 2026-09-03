import { useEffect, useState, useCallback } from "react";
import { WifiOff } from "lucide-react";
import { motion } from "framer-motion";
import { getStickers, selectSticker, type Sticker, type StickerCollection } from "../lib/api";
import { haptic } from "../lib/haptics";
import { Button, EmptyState, Skeleton } from "./ui";

/**
 * Коллекция наклеек: что уже выпало и что осталось собрать.
 *
 * Показываем ВСЕ наклейки, а не только свои: пустые ячейки — половина смысла
 * коллекции. Без них не видно ни что собирать, ни сколько осталось, и кейс
 * снова превращается в раздачу расходников.
 *
 * Группируем по наборам — набор и есть кейс, из которого наклейка выпадает.
 * Плоская сетка из четырёх десятков персонажей не отвечала на главный
 * вопрос «какой кейс открывать дальше»; по наборам он читается сам.
 *
 * Одну можно поставить в анкету — её увидят другие. Именно одну: витрина
 * достижений отвлекает от человека, а на карточку смотрят ради него.
 */

const ЦВЕТ_РЕДКОСТИ: Record<string, string> = {
  common: "text-text-muted",
  rare: "text-info",
  epic: "text-[var(--color-flame-start)]",
  legend: "text-warn",
};

interface Группа {
  code: string;
  title: string;
  owned: number;
  total: number;
  stickers: Sticker[];
}

/**
 * Разложить коллекцию по наборам в порядке витрины. Наклейка без известного
 * набора не теряется — уходит в хвост отдельной группой: старый клиент с
 * новым сервером не должен «терять» выпавшее.
 */
export function группировать(данные: StickerCollection): Группа[] {
  const наборы = данные.sets ?? [];
  if (наборы.length === 0) {
    return [
      {
        code: "",
        title: "",
        owned: данные.owned,
        total: данные.total,
        stickers: данные.stickers,
      },
    ];
  }
  const известные = new Set(наборы.map((s) => s.code));
  const группы: Группа[] = наборы.map((s) => {
    const свои = данные.stickers.filter((н) => н.set === s.code);
    return {
      code: s.code,
      title: s.title,
      owned: свои.filter((н) => н.owned > 0).length,
      total: свои.length,
      stickers: свои,
    };
  });
  const прочие = данные.stickers.filter((н) => !известные.has(н.set));
  if (прочие.length > 0) {
    группы.push({
      code: "other",
      title: "Другие",
      owned: прочие.filter((н) => н.owned > 0).length,
      total: прочие.length,
      stickers: прочие,
    });
  }
  return группы.filter((г) => г.stickers.length > 0);
}

export default function StickerCollection_({
  onClose,
  версия = 0,
}: {
  onClose?: () => void;
  /** Растёт после каждого открытого кейса — коллекция перечитывается без перемонтирования. */
  версия?: number;
}) {
  const [данные, setДанные] = useState<StickerCollection | null>(null);
  const [сбой, setСбой] = useState(false);
  const [занято, setЗанято] = useState(false);

  const загрузить = useCallback(() => {
    setСбой(false);
    getStickers()
      .then(setДанные)
      .catch(() => setСбой(true));
  }, []);

  useEffect(загрузить, [загрузить, версия]);

  const выбрать = async (н: Sticker) => {
    if (!н.owned || занято) return;
    setЗанято(true);
    haptic("light");
    try {
      // Повторный тап по выбранной снимает выбор — иначе от наклейки
      // невозможно отказаться, не выбрав другую
      const код = данные?.selected === н.code ? "" : н.code;
      setДанные(await selectSticker(код));
    } catch {
      haptic("error");
    } finally {
      setЗанято(false);
    }
  };

  if (сбой) {
    return (
      <EmptyState
        icon={WifiOff}
        title="Не удалось загрузить"
        description="Проверьте соединение и попробуйте снова."
        action={
          <Button variant="secondary" size="md" onClick={загрузить}>
            Повторить
          </Button>
        }
      />
    );
  }

  if (!данные) {
    return (
      <div className="grid grid-cols-4 gap-3 px-4 py-4">
        {Array.from({ length: 12 }, (_, i) => (
          <Skeleton key={i} className="aspect-square rounded-full" />
        ))}
      </div>
    );
  }

  const группы = группировать(данные);

  return (
    <div className="px-4 pb-6">
      <div className="flex items-baseline justify-between mb-1 pt-1">
        <p className="text-[15px] font-bold">Коллекция</p>
        <p className="text-[13px] text-text-muted tabular-nums">
          {данные.owned} из {данные.total}
        </p>
      </div>
      <p className="text-[12.5px] text-text-muted mb-4 leading-relaxed">
        Наклейки выпадают из кейсов. Одну можно поставить в анкету — она
        ляжет значком на фото, и её увидят другие.
      </p>

      {группы.map((г) => (
        <section key={г.code || "all"} className="mb-5 last:mb-0">
          {г.title && (
            <div className="flex items-baseline justify-between mb-2 px-0.5">
              <p className="text-[13px] font-bold">{г.title}</p>
              <p className="text-[12px] text-text-muted tabular-nums">
                {г.owned} из {г.total}
              </p>
            </div>
          )}
          <div className="grid grid-cols-4 gap-3">
            {г.stickers.map((н) => {
              const выбрана = данные.selected === н.code;
              return (
                <button
                  key={н.code}
                  onClick={() => выбрать(н)}
                  disabled={!н.owned}
                  aria-label={
                    н.owned
                      ? `${н.title}, ${н.rarity_title}`
                      : `${н.title} — ещё не выпала`
                  }
                  aria-pressed={выбрана}
                  className={`relative aspect-square rounded-full transition-transform
                              ${н.owned ? "active:scale-95" : "cursor-default"}
                              ${выбрана ? "ring-2 ring-accent ring-offset-2 ring-offset-bg" : ""}`}
                >
                  <img
                    src={н.image}
                    alt=""
                    loading="lazy"
                    className={`w-full h-full object-contain ${
                      // Не выпавшие показываем силуэтом: полностью скрыть их
                      // значило бы не показать, что собирать
                      н.owned ? "" : "opacity-25 grayscale"
                    }`}
                  />
                  {н.owned > 1 && (
                    <span
                      className="absolute -bottom-0.5 -right-0.5 min-w-[18px] h-[18px] px-1
                                 rounded-full bg-surface-3 border border-hairline
                                 text-[10px] font-bold flex items-center justify-center"
                    >
                      ×{н.owned}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </section>
      ))}

      {данные.selected && (
        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="mt-4 text-[12.5px] text-text-muted text-center"
        >
          Нажмите на выбранную ещё раз, чтобы снять её с анкеты.
        </motion.p>
      )}

      {данные.owned === 0 && (
        <p className="mt-5 text-[13px] text-text-muted text-center leading-relaxed">
          Пока пусто. Наклейки выпадают из кейсов — они доступны в Plus.
        </p>
      )}

      {onClose && (
        <Button variant="secondary" size="md" fullWidth className="mt-5" onClick={onClose}>
          Закрыть
        </Button>
      )}
    </div>
  );
}

/** Легенда редкостей — чтобы цвет подписи что-то значил. */
export function РедкостьПодпись({ rarity, title }: { rarity: string; title: string }) {
  return <span className={ЦВЕТ_РЕДКОСТИ[rarity] ?? "text-text-muted"}>{title}</span>;
}
