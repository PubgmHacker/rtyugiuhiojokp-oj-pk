import { useState, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { SlidersHorizontal, X } from "lucide-react";
import SwipeDeck from "../components/SwipeDeck";
import { useStore } from "../lib/store";
import { updateMyProfile, getMyProfile, type UserProfile } from "../lib/api";
import { haptic } from "../lib/haptics";
import { Button, Chip, Spinner } from "../components/ui";

const LOOKING_FOR = [
  { value: "female", label: "Девушек" },
  { value: "male", label: "Парней" },
  { value: "any", label: "Всех" },
];

export default function Discover() {
  const { user, setUser } = useStore();
  const [filtersOpen, setFiltersOpen] = useState(false);

  return (
    // Высота за вычетом нижней навигации (её отступ задаёт Protected):
    // при 100dvh кнопки действий уезжают под панель
    <div className="flex flex-col h-[calc(100dvh-68px)]">
      <header className="chrome safe-top border-b border-hairline/60 shrink-0">
        <div className="flex items-center justify-between px-4 pb-2.5 min-h-[48px]">
          <h1 className="text-[24px] font-extrabold tracking-[-0.03em] text-gradient">
            Souldawn
          </h1>
          <button
            aria-label="Настройки поиска"
            onClick={() => {
              haptic("light");
              setFiltersOpen(true);
            }}
            className="tap-target flex items-center justify-center rounded-full
                       text-text-secondary active:scale-90 transition-transform"
          >
            <SlidersHorizontal size={21} />
          </button>
        </div>
      </header>

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
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");

  // При открытии подтягиваем актуальные значения из профиля
  useEffect(() => {
    if (!open || !user) return;
    setLookingFor(user.looking_for ?? "any");
    setAgeMin(user.age_min ?? 18);
    setAgeMax(user.age_max ?? 45);
    setDistance(user.distance_max ?? 100);
    setSaveError("");
  }, [open, user]);

  const save = useCallback(async () => {
    setSaving(true);
    setSaveError("");
    try {
      await updateMyProfile({
        looking_for: lookingFor,
        age_min: ageMin,
        age_max: ageMax,
        distance_max: distance,
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
  }, [lookingFor, ageMin, ageMax, distance, setUser, onClose]);

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

            {/* Расстояние */}
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
              />
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

            <Button size="lg" fullWidth onClick={save} disabled={saving}>
              {saving ? <Spinner size={20} /> : "Применить"}
            </Button>
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
}: {
  label: string;
  min: number;
  max: number;
  step?: number;
  value: number;
  onChange: (v: number) => void;
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
      className="w-full h-1.5 rounded-full appearance-none cursor-pointer mb-3
                 [&::-webkit-slider-thumb]:appearance-none
                 [&::-webkit-slider-thumb]:w-6 [&::-webkit-slider-thumb]:h-6
                 [&::-webkit-slider-thumb]:rounded-full
                 [&::-webkit-slider-thumb]:bg-white
                 [&::-webkit-slider-thumb]:shadow-[0_2px_8px_rgb(0_0_0/0.5)]
                 [&::-moz-range-thumb]:w-6 [&::-moz-range-thumb]:h-6
                 [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:border-0
                 [&::-moz-range-thumb]:bg-white"
      style={{
        background: `linear-gradient(to right, var(--color-accent) ${pct}%, var(--color-surface-3) ${pct}%)`,
      }}
    />
  );
}
