import { useState, useEffect, useCallback } from "react";
import { Link } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { SlidersHorizontal, X, Flame, MapPin } from "lucide-react";
import SwipeDeck from "../components/SwipeDeck";
import DailyCardBanner from "../components/DailyCard";
import { useStore } from "../lib/store";
import { updateMyProfile, getMyProfile, type UserProfile } from "../lib/api";
import { haptic } from "../lib/haptics";
import { Button, Chip, Spinner } from "../components/ui";
import {
  GOALS,
  SUBCULTURES,
  HEIGHT_MIN,
  HEIGHT_MAX,
} from "../lib/profileOptions";

const LOOKING_FOR = [
  { value: "female", label: "Девушек" },
  { value: "male", label: "Парней" },
  { value: "any", label: "Всех" },
];

export default function Discover() {
  const { user, setUser } = useStore();
  const [filtersOpen, setFiltersOpen] = useState(false);

  // Заданы ли нишевые фильтры — по этому кнопка подсвечивается: иначе
  // человек не помнит, почему выдача сузилась
  const filtersActive = Boolean(
    user?.filter_goal ||
      user?.filter_subculture ||
      user?.filter_city ||
      user?.filter_height_min ||
      user?.filter_height_max
  );

  return (
    // Высота за вычетом нижней навигации (её отступ задаёт Protected):
    // при 100dvh кнопки действий уезжают под панель
    <div className="flex flex-col h-[calc(100dvh-68px)]">
      {/* Шапка поверх карточки, как в референсе: пилюля-режим слева,
          фильтры справа. Фон прозрачный — фото уходит под неё */}
      <header className="safe-top shrink-0 px-3 pb-2 pt-1">
        <div className="flex items-center justify-between gap-2 min-h-[44px]">
          <span
            className="inline-flex items-center gap-2 pl-2 pr-4 py-1.5 rounded-full
                       bg-dawn text-white font-bold text-[15px] shadow-lg"
          >
            <span
              aria-hidden
              className="w-7 h-7 rounded-full bg-white/20 flex items-center justify-center"
            >
              <Flame size={16} />
            </span>
            Анкеты
          </span>

          <button
            aria-label="Настройки поиска"
            onClick={() => {
              haptic("light");
              setFiltersOpen(true);
            }}
            className={`inline-flex items-center gap-2 pl-3.5 pr-4 py-2 rounded-full
                        text-[14.5px] font-semibold glass-strong
                        active:scale-95 transition-transform
                        ${filtersActive ? "text-accent" : "text-text-secondary"}`}
          >
            <SlidersHorizontal size={17} />
            Фильтры
            {filtersActive && (
              <span aria-hidden className="w-1.5 h-1.5 rounded-full bg-accent" />
            )}
          </button>
        </div>
      </header>

      <DailyCardBanner />

      <SwipeDeck onOpenFilters={() => setFiltersOpen(true)} />

      <FilterSheet
        open={filtersOpen}
        onClose={() => setFiltersOpen(false)}
        user={user}
        setUser={setUser}
      />
    </div>
  );
}

/* ── Нижняя шторка с фильтрами ──────────────────────────────── */

function FilterSheet({
  open,
  onClose,
  user,
  setUser,
}: {
  open: boolean;
  onClose: () => void;
  user: UserProfile | null;
  setUser: (u: UserProfile | null) => void;
}) {
  const [lookingFor, setLookingFor] = useState(user?.looking_for ?? "any");
  const [ageMin, setAgeMin] = useState(user?.age_min ?? 18);
  const [ageMax, setAgeMax] = useState(user?.age_max ?? 45);
  const [distance, setDistance] = useState(user?.distance_max ?? 100);
  const [goal, setGoal] = useState(user?.filter_goal ?? "");
  const [subculture, setSubculture] = useState(user?.filter_subculture ?? "");
  const [city, setCity] = useState(user?.filter_city ?? "");
  // Рост фильтруем только если человек включил ползунки: иначе анкеты без
  // указанного роста молча исчезли бы из выдачи
  const [heightOn, setHeightOn] = useState(
    user?.filter_height_min != null || user?.filter_height_max != null
  );
  const [heightMin, setHeightMin] = useState(user?.filter_height_min ?? 155);
  const [heightMax, setHeightMax] = useState(user?.filter_height_max ?? 195);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");

  // При открытии подтягиваем актуальные значения из профиля
  useEffect(() => {
    if (!open || !user) return;
    setLookingFor(user.looking_for ?? "any");
    setAgeMin(user.age_min ?? 18);
    setAgeMax(user.age_max ?? 45);
    setDistance(user.distance_max ?? 100);
    setGoal(user.filter_goal ?? "");
    setSubculture(user.filter_subculture ?? "");
    setCity(user.filter_city ?? "");
    setHeightOn(user.filter_height_min != null || user.filter_height_max != null);
    setHeightMin(user.filter_height_min ?? 155);
    setHeightMax(user.filter_height_max ?? 195);
    setSaveError("");
  }, [open, user]);

  const reset = useCallback(() => {
    haptic("light");
    setLookingFor("any");
    setAgeMin(18);
    setAgeMax(45);
    setDistance(100);
    setGoal("");
    setSubculture("");
    setCity("");
    setHeightOn(false);
    setHeightMin(155);
    setHeightMax(195);
  }, []);

  const save = useCallback(async () => {
    setSaving(true);
    setSaveError("");
    try {
      await updateMyProfile({
        looking_for: lookingFor,
        age_min: ageMin,
        age_max: ageMax,
        distance_max: distance,
        filter_goal: goal,
        filter_subculture: subculture,
        filter_city: city.trim(),
        filter_height_min: heightOn ? heightMin : null,
        filter_height_max: heightOn ? heightMax : null,
      });
      const fresh = await getMyProfile();
      setUser(fresh);
      // Дека собрана по старым фильтрам — сбрасываем, чтобы применились новые
      useStore.getState().setDeck([]);
      haptic("success");
      onClose();
    } catch {
      // Без видимого текста человек не понимает, почему фильтры не
      // применились: вибрации на вебе может не быть вовсе
      setSaveError("Не удалось сохранить. Проверьте соединение.");
      haptic("error");
    } finally {
      setSaving(false);
    }
  }, [
    lookingFor,
    ageMin,
    ageMax,
    distance,
    goal,
    subculture,
    city,
    heightOn,
    heightMin,
    heightMax,
    setUser,
    onClose,
  ]);

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm"
          />
          <motion.div
            role="dialog"
            aria-label="Настройки поиска"
            initial={{ y: "100%" }}
            animate={{ y: 0 }}
            exit={{ y: "100%" }}
            transition={{ type: "spring", stiffness: 380, damping: 36 }}
            drag="y"
            dragConstraints={{ top: 0, bottom: 0 }}
            dragElastic={{ top: 0, bottom: 0.5 }}
            onDragEnd={(_, info) => {
              if (info.offset.y > 110) onClose();
            }}
            className="fixed bottom-0 left-0 right-0 z-50 bg-bg-elevated
                       rounded-t-[var(--radius-sheet)] border-t border-hairline
                       px-5 pt-3 pb-7 safe-bottom max-h-[86dvh] overflow-y-auto no-scrollbar"
          >
            <div className="w-10 h-1 rounded-full bg-surface-3 mx-auto mb-5" />

            <div className="flex items-center justify-between mb-6">
              <h2 className="text-heading font-bold">Кого показывать</h2>
              <button
                aria-label="Закрыть"
                onClick={onClose}
                className="tap-target flex items-center justify-center text-text-muted"
              >
                <X size={21} />
              </button>
            </div>

            {/* Пол */}
            <div className="mb-7">
              <p className="text-caption text-text-muted mb-2.5">Интересуют</p>
              <div className="flex gap-2">
                {LOOKING_FOR.map((o) => (
                  <Chip
                    key={o.value}
                    active={lookingFor === o.value}
                    onClick={() => setLookingFor(o.value)}
                  >
                    {o.label}
                  </Chip>
                ))}
              </div>
            </div>

            {/* Возраст */}
            <div className="mb-7">
              <div className="flex items-baseline justify-between mb-2.5">
                <p className="text-caption text-text-muted">Возраст</p>
                <p className="text-[15px] font-semibold">
                  {ageMin} – {ageMax}
                </p>
              </div>
              <Range
                label="Минимальный возраст"
                min={18}
                max={80}
                value={ageMin}
                onChange={(v) => setAgeMin(Math.min(v, ageMax - 1))}
              />
              <Range
                label="Максимальный возраст"
                min={19}
                max={99}
                value={ageMax}
                onChange={(v) => setAgeMax(Math.max(v, ageMin + 1))}
              />
            </div>

            {/* Расстояние. Без геопозиции сервер не может посчитать км, и
                ползунок ничего не фильтрует — предупреждаем прямо тут,
                а не оставляем человека гадать, почему выдача не меняется */}
            <div className="mb-8">
              <div className="flex items-baseline justify-between mb-2.5">
                <p className="text-caption text-text-muted">Расстояние</p>
                <p className="text-[15px] font-semibold">
                  {distance >= 500 ? "Без ограничений" : `до ${distance} км`}
                </p>
              </div>
              <Range
                label="Максимальное расстояние"
                min={5}
                max={500}
                step={5}
                value={distance}
                onChange={setDistance}
                disabled={!user?.has_location}
              />
              {!user?.has_location && (
                <p className="text-[12px] text-text-muted mt-1">
                  Расстояние заработает, когда вы включите геолокацию в{" "}
                  <Link to="/profile" onClick={onClose} className="text-accent font-semibold">
                    профиле
                  </Link>
                </p>
              )}
            </div>

            {/* Цель знакомства */}
            <div className="mb-7">
              <p className="text-caption text-text-muted mb-2.5">Цель знакомства</p>
              <div className="flex flex-wrap gap-2">
                <Chip active={goal === ""} onClick={() => setGoal("")}>
                  Любая
                </Chip>
                {GOALS.map((o) => (
                  <Chip
                    key={o.value}
                    active={goal === o.value}
                    onClick={() => setGoal(goal === o.value ? "" : o.value)}
                  >
                    {o.label}
                  </Chip>
                ))}
              </div>
            </div>

            {/* Субкультура */}
            <div className="mb-7">
              <p className="text-caption text-text-muted mb-2.5">Субкультура</p>
              <div className="flex flex-wrap gap-2">
                <Chip active={subculture === ""} onClick={() => setSubculture("")}>
                  Любая
                </Chip>
                {SUBCULTURES.map((o) => (
                  <Chip
                    key={o.value}
                    active={subculture === o.value}
                    onClick={() =>
                      setSubculture(subculture === o.value ? "" : o.value)
                    }
                  >
                    {o.label}
                  </Chip>
                ))}
              </div>
            </div>

            {/* Город */}
            <div className="mb-7">
              <p className="text-caption text-text-muted mb-2.5">Город</p>
              <input
                value={city}
                onChange={(e) => setCity(e.target.value)}
                placeholder="Любой"
                aria-label="Город"
                className="w-full px-3.5 py-3 rounded-[var(--radius-tile)]
                           bg-surface-2 border border-hairline text-[15px]
                           placeholder:text-text-muted focus:outline-none
                           focus:border-accent/60"
              />
            </div>

            {/* Рост */}
            <div className="mb-8">
              <div className="flex items-baseline justify-between mb-2.5">
                <p className="text-caption text-text-muted">Рост</p>
                <button
                  onClick={() => {
                    haptic("light");
                    setHeightOn((v) => !v);
                  }}
                  className="text-[13px] font-semibold text-accent"
                >
                  {heightOn ? `${heightMin} – ${heightMax} см` : "Не важен"}
                </button>
              </div>
              {heightOn && (
                <>
                  <Range
                    label="Минимальный рост"
                    min={HEIGHT_MIN}
                    max={HEIGHT_MAX - 1}
                    value={heightMin}
                    onChange={(v) => setHeightMin(Math.min(v, heightMax - 1))}
                  />
                  <Range
                    label="Максимальный рост"
                    min={HEIGHT_MIN + 1}
                    max={HEIGHT_MAX}
                    value={heightMax}
                    onChange={(v) => setHeightMax(Math.max(v, heightMin + 1))}
                  />
                  <p className="text-[12px] text-text-muted">
                    Анкеты без указанного роста не попадут в выдачу
                  </p>
                </>
              )}
            </div>

            {saveError && (
              <p
                role="alert"
                className="mb-2.5 px-3.5 py-2.5 rounded-[var(--radius-tile)]
                           bg-danger/12 border border-danger/30 text-danger text-[13px]"
              >
                {saveError}
              </p>
            )}

            <div className="flex gap-2.5">
              <Button
                variant="secondary"
                size="lg"
                onClick={reset}
                disabled={saving}
              >
                Сбросить
              </Button>
              <Button size="lg" fullWidth onClick={save} disabled={saving}>
                {saving ? <Spinner size={20} /> : "Применить"}
              </Button>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}

function Range({
  label,
  min,
  max,
  step = 1,
  value,
  onChange,
  disabled = false,
}: {
  label: string;
  min: number;
  max: number;
  step?: number;
  value: number;
  onChange: (v: number) => void;
  disabled?: boolean;
}) {
  const pct = ((value - min) / (max - min)) * 100;
  return (
    <input
      type="range"
      aria-label={label}
      min={min}
      max={max}
      step={step}
      value={value}
      onChange={(e) => onChange(Number(e.target.value))}
      disabled={disabled}
      className="w-full h-1.5 rounded-full appearance-none cursor-pointer mb-3
                 disabled:opacity-40 disabled:cursor-not-allowed
                 [&::-webkit-slider-thumb]:appearance-none
                 [&::-webkit-slider-thumb]:w-6 [&::-webkit-slider-thumb]:h-6
                 [&::-webkit-slider-thumb]:rounded-full
                 [&::-webkit-slider-thumb]:bg-white
                 [&::-webkit-slider-thumb]:shadow-[0_2px_8px_rgb(0_0_0/0.5)]
                 [&::-moz-range-thumb]:w-6 [&::-moz-range-thumb]:h-6
                 [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:border-0
                 [&::-moz-range-thumb]:bg-white"
      style={{
        background: disabled
          ? "var(--color-surface-3)"
          : `linear-gradient(to right, var(--color-accent) ${pct}%, var(--color-surface-3) ${pct}%)`,
      }}
    />
  );
}
