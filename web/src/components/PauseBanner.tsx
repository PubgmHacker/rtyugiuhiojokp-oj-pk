import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { EyeOff } from "lucide-react";
import { useStore } from "../lib/store";
import { updateMyProfile } from "../lib/api";
import { haptic } from "../lib/haptics";
import { Spinner } from "./ui";

/**
 * Напоминание о том, что анкета на паузе, — на каждом экране.
 *
 * Пауза скрывает анкету из деки, из «кто лайкнул», из оценки фото, из
 * рейтинга и из роликов (`api/services/matching.py`, `photo_ratings.py`,
 * `leaderboard.py`, `reels.py`). Снаружи это выглядит как отсутствие анкеты,
 * а изнутри — ровно как обычная работа приложения: дека листается, экраны
 * открываются, только новых лайков и мэтчей нет никогда.
 *
 * До появления этой плашки включить паузу мог только Telegram-бот, а мини-апп
 * про неё не знал вовсе: человек, нажавший «скрыть анкету» в боте месяц назад,
 * открывал приложение и видел тишину без объяснения. Худший вид поломки —
 * когда всё «работает».
 *
 * Плашку нельзя закрыть намеренно. Скрываемое ею состояние снимается одним
 * тапом здесь же, а пока оно включено, главный цикл приложения не работает:
 * закрывающийся крестик вернул бы ту самую немую невидимость. Форма — тот же
 * плавающий пузырь над нижней навигацией, каким дека показывает ошибки, чтобы
 * не ломать вёрстку экранов с фиксированной высотой (см. `Discover.tsx`).
 */
export default function PauseBanner() {
  const user = useStore((s) => s.user);
  const setUser = useStore((s) => s.setUser);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  const paused = Boolean(user?.is_paused);

  const resume = async () => {
    if (busy) return;
    setBusy(true);
    setFailed(false);
    haptic("light");
    try {
      // Ответ — свежая анкета целиком: кладём её в store, иначе плашка
      // осталась бы висеть до перезагрузки, а человек решил бы, что снять
      // паузу не удалось, и нажал ещё раз
      setUser(await updateMyProfile({ is_paused: false }));
      haptic("success");
    } catch {
      // Молчать здесь нельзя: человек уверен, что вернулся в выдачу, а он
      // по-прежнему скрыт. Вибрации на вебе может не быть вовсе
      setFailed(true);
      haptic("error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <AnimatePresence>
      {paused && (
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: 12 }}
          transition={{ type: "spring", stiffness: 420, damping: 34 }}
          role="status"
          className="fixed bottom-[84px] inset-x-3 z-40 mx-auto max-w-[420px]
                     flex items-center gap-3 px-4 py-3
                     rounded-[var(--radius-tile)] bg-surface-3 border border-warn/35
                     float-shadow"
        >
          <EyeOff size={18} className="shrink-0 text-warn" aria-hidden />
          <div className="flex-1 min-w-0">
            <p className="text-[14px] font-semibold leading-tight">
              Анкета на паузе
            </p>
            <p className="text-[12.5px] text-text-secondary leading-snug mt-0.5">
              {failed
                ? "Не удалось снять паузу — проверьте соединение и попробуйте ещё раз"
                : "Вас никто не видит: ни в ленте, ни в лайках"}
            </p>
          </div>
          <button
            onClick={resume}
            disabled={busy}
            className="shrink-0 px-3.5 py-2 rounded-full bg-accent text-white
                       text-[13px] font-bold active:scale-95 transition-transform
                       disabled:opacity-60"
          >
            {busy ? <Spinner size={16} /> : failed ? "Ещё раз" : "Показывать"}
          </button>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
