/**
 * Витрина рамок. Живёт рядом с коллекцией наклеек: условие открытия —
 * размер той же коллекции, и человек должен видеть цель там, где видит
 * прогресс.
 *
 * Закрытые рамки показываем с полоской «12 из 15». Скрывать их — терять
 * весь смысл: рамка мотивирует, только если о ней известно заранее.
 */

import { useCallback, useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Check, Lock } from "lucide-react";
import { getDecor, selectDecor, type DecorCollection, type DecorItem } from "../lib/api";
import { decorPreviewShadow } from "../lib/decor";
import { haptic } from "../lib/haptics";

export default function DecorPicker() {
  const [данные, setДанные] = useState<DecorCollection | null>(null);
  const [занято, setЗанято] = useState<string | null>(null);
  const [ошибка, setОшибка] = useState("");

  useEffect(() => {
    let отменено = false;
    (async () => {
      try {
        const d = await getDecor();
        if (!отменено) setДанные(d);
      } catch {
        if (!отменено) setОшибка("Не удалось загрузить оформления");
      }
    })();
    return () => {
      отменено = true;
    };
  }, []);

  const выбрать = useCallback(
    async (item: DecorItem | null) => {
      const код = item?.code ?? "";
      if (item && !item.unlocked) {
        haptic("warning");
        setОшибка(item.hint);
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
    return <p className="text-[13px] text-text-muted px-1">{ошибка}</p>;
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
          {данные.stickers_owned} наклеек
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
                item.unlocked ? `Рамка «${item.title}»` : `${item.title} — ${item.hint}`
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
                  {/* Полоска вместо подписи «нужно 15»: «12 из 15» читается
                      как «почти», а требование — как «не для меня» */}
                  {item.need > 0 && (
                    <span className="absolute bottom-6 left-1.5 right-1.5 h-[3px]
                                     rounded-full bg-white/25 overflow-hidden">
                      <span
                        className="block h-full rounded-full bg-white/85"
                        style={{ width: `${(item.have / item.need) * 100}%` }}
                      />
                    </span>
                  )}
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
