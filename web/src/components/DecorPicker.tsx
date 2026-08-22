/**
 * Витрина рамок. Живёт под коллекцией наклеек: рамка выпадает из того же
 * кейса, и цель должна быть видна там, где виден прогресс.
 *
 * Ещё не выпавшие рамки показываем приглушёнными, с замком и редкостью.
 * Скрывать их — терять весь смысл: рамка мотивирует, только если о ней
 * известно заранее. Прогресса у рамок нет сознательно — это не награда за
 * счётчик, а лимитированный дроп, и полоска «12 из 15» тут врала бы.
 */

import { useCallback, useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Check, Lock } from "lucide-react";
import { getDecor, selectDecor, type DecorCollection, type DecorItem } from "../lib/api";
import { decorPreviewShadow } from "../lib/decor";
import { haptic } from "../lib/haptics";
import { Button } from "./ui";

/** Почему рамку нельзя надеть. Одной строкой — и в подсказке, и для читалки. */
function условие(item: DecorItem): string {
  return `выпадает из кейса · ${item.rarity_title.toLowerCase()}`;
}

export default function DecorPicker() {
  const [данные, setДанные] = useState<DecorCollection | null>(null);
  const [занято, setЗанято] = useState<string | null>(null);
  const [ошибка, setОшибка] = useState("");

  const загрузить = useCallback(() => {
    setОшибка("");
    setДанные(null);
    getDecor()
      .then(setДанные)
      .catch(() => setОшибка("Не удалось загрузить оформления"));
  }, []);

  useEffect(загрузить, [загрузить]);

  const выбрать = useCallback(
    async (item: DecorItem | null) => {
      const код = item?.code ?? "";
      if (item && !item.unlocked) {
        haptic("warning");
        setОшибка(`«${item.title}» ещё не ваша: ${условие(item)}`);
        return;
      }
      haptic("light");
      setЗанято(код || "none");
      setОшибка("");
      try {
        // Снятие тоже идёт через сервер: снятая рамка должна исчезнуть
        // и у тех, кто уже листает карточку
        setДанные(await selectDecor(код));
        haptic("success");
      } catch (e: any) {
        haptic("warning");
        setОшибка(e?.response?.data?.detail || "Не удалось применить");
      } finally {
        setЗанято(null);
      }
    },
    []
  );

  if (ошибка && !данные) {
    // Секция вспомогательная — без полноэкранной заглушки, но с повтором:
    // тупиковый текст заставлял перезагружать весь экран кейсов
    return (
      <div className="px-1">
        <p className="text-[13px] text-text-muted mb-2">{ошибка}</p>
        <Button variant="secondary" size="sm" onClick={загрузить}>
          Повторить
        </Button>
      </div>
    );
  }
  if (!данные) {
    return <div className="h-28 rounded-2xl skeleton" />;
  }

  return (
    <section aria-labelledby="decor-title">
      <div className="flex items-baseline justify-between mb-2.5 px-1">
        <h3 id="decor-title" className="text-[15px] font-bold">
          Рамка карточки
        </h3>
        <span className="text-[12px] text-text-muted">
          {данные.owned} из {данные.total}
        </span>
      </div>

      <div className="grid grid-cols-3 gap-2.5">
        {/* «Без рамки» — полноценный вариант, а не отсутствие выбора:
            иначе снять рамку можно только догадавшись */}
        <button
          type="button"
          onClick={() => выбрать(null)}
          disabled={занято !== null}
          aria-pressed={!данные.selected}
          className={`relative aspect-[3/4] rounded-2xl bg-surface-2 transition-transform
                      active:scale-[.97] disabled:opacity-60
                      ${!данные.selected ? "avatar-ring" : ""}`}
        >
          <span className="absolute inset-0 flex items-center justify-center
                           text-[12px] font-semibold text-text-muted">
            Без рамки
          </span>
          {!данные.selected && (
            <span className="absolute top-1.5 right-1.5 w-5 h-5 rounded-full bg-accent
                             flex items-center justify-center">
              <Check size={13} className="text-white" strokeWidth={3} />
            </span>
          )}
        </button>

        {данные.decors.map((item) => {
          const надета = данные.selected === item.code;
          return (
            <motion.button
              key={item.code}
              type="button"
              onClick={() => выбрать(item)}
              disabled={занято !== null}
              aria-pressed={надета}
              aria-label={
                item.unlocked
                  ? `Рамка «${item.title}» · ${item.rarity_title}`
                  : `${item.title} — ${условие(item)}`
              }
              whileTap={item.unlocked ? { scale: 0.97 } : undefined}
              className={`relative aspect-[3/4] rounded-2xl overflow-hidden
                          disabled:opacity-60
                          ${item.unlocked ? "" : "cursor-not-allowed"}`}
              style={{
                background: "var(--gradient-placeholder)",
                // Закрытую рамку показываем той же тенью, но приглушённой:
                // человек должен видеть ИМЕННО то, что получит, иначе
                // цель не читается как награда
                boxShadow: decorPreviewShadow(item.code),
                opacity: item.unlocked ? 1 : 0.42,
              }}
            >
              <span className="absolute bottom-1.5 left-0 right-0 px-1.5
                               text-[11px] font-semibold text-white
                               drop-shadow-[0_1px_2px_rgba(0,0,0,.7)] truncate">
                {item.title}
              </span>

              {надета && (
                <span className="absolute top-1.5 right-1.5 w-5 h-5 rounded-full bg-accent
                                 flex items-center justify-center">
                  <Check size={13} className="text-white" strokeWidth={3} />
                </span>
              )}

              {!item.unlocked && (
                <>
                  <span className="absolute top-1.5 right-1.5 w-5 h-5 rounded-full
                                   bg-black/55 flex items-center justify-center">
                    <Lock size={11} className="text-white/90" />
                  </span>
                  {/* Редкость вместо полоски прогресса: рамка не набирается
                      счётчиком, а выпадает — и редкость единственное, что
                      честно объясняет, почему её ещё нет */}
                  <span className="absolute top-1.5 left-1.5 px-1.5 py-[1px]
                                   rounded-full bg-black/55 text-[9.5px] font-bold
                                   uppercase tracking-wide text-white/90">
                    {item.rarity_title}
                  </span>
                </>
              )}
            </motion.button>
          );
        })}
      </div>

      {ошибка && (
        <p className="mt-2.5 px-1 text-[12px] text-danger" role="status">
          {ошибка}
        </p>
      )}
    </section>
  );
}
