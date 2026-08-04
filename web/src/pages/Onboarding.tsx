import { useState, useCallback, useMemo, useId } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useNavigate } from "react-router-dom";
import { Camera, X, ChevronLeft, MapPin, Check, Star } from "lucide-react";
import {
  updateMyProfile,
  getMyProfile,
  uploadPhoto,
  type UserProfile,
} from "../lib/api";
import { useStore } from "../lib/store";
import { haptic } from "../lib/haptics";
import { getCurrentPosition } from "../lib/native";
import { Button, Chip, Spinner } from "../components/ui";
import {
  GOALS,
  SUBCULTURES,
  HEIGHT_MIN,
  HEIGHT_MAX,
} from "../lib/profileOptions";

const INTERESTS = [
  "Музыка", "Кино", "Сериалы", "Книги",
  "Спорт", "Зал", "Бег", "Йога",
  "Путешествия", "Походы", "Кофе", "Кулинария",
  "Вино", "Игры", "Аниме", "Искусство",
  "Фотография", "Танцы", "Театр", "Животные",
  "Мода", "Технологии", "Психология", "Волонтёрство",
];

const MAX_INTERESTS = 8;
const MAX_PHOTOS = 6;
const MAX_BIO = 500;

type StepId =
  | "name"
  | "age"
  | "gender"
  | "lookingFor"
  | "city"
  | "photos"
  | "interests"
  | "about"
  | "bio"
  | "done";

const STEPS: StepId[] = [
  "name",
  "age",
  "gender",
  "lookingFor",
  "city",
  "photos",
  "interests",
  "about",
  "bio",
  "done",
];

interface PhotoSlot {
  /** Свой идентификатор: индекс в массиве не годится, пока идёт загрузка. */
  id: string;
  url?: string;
  uploading?: boolean;
  error?: string;
}

let photoSeq = 0;

export default function Onboarding() {
  const navigate = useNavigate();
  const { user, setUser } = useStore();

  const [index, setIndex] = useState(0);
  const [direction, setDirection] = useState(1);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");

  // Экран используется и для правки анкеты — подставляем, что уже есть
  const [name, setName] = useState(user?.display_name ?? "");
  const [age, setAge] = useState(user?.age ? String(user.age) : "");
  const [gender, setGender] = useState(user?.gender ?? "");
  const [lookingFor, setLookingFor] = useState(user?.looking_for ?? "");
  const [city, setCity] = useState(user?.city ?? "");
  const [coords, setCoords] = useState<{ lat: number; lon: number } | null>(null);
  const [geoBusy, setGeoBusy] = useState(false);
  const [photos, setPhotos] = useState<PhotoSlot[]>(
    (user?.photos ?? []).map((url) => ({ id: `init-${photoSeq++}`, url }))
  );
  const [interests, setInterests] = useState<string[]>(user?.interests ?? []);
  const [goal, setGoal] = useState(user?.goal ?? "");
  const [subculture, setSubculture] = useState(user?.subculture ?? "");
  const [height, setHeight] = useState(
    user?.height_cm != null ? String(user.height_cm) : ""
  );
  const [bio, setBio] = useState(user?.bio ?? "");

  const step = STEPS[index];
  const ageNum = Number(age);

  const canContinue = useMemo(() => {
    switch (step) {
      case "name":
        return name.trim().length >= 2;
      case "age":
        return Number.isInteger(ageNum) && ageNum >= 18 && ageNum <= 99;
      case "gender":
        return !!gender;
      case "lookingFor":
        return !!lookingFor;
      case "city":
        return city.trim().length >= 2;
      case "photos":
        return photos.some((p) => p.url);
      // Шаг необязателен целиком, но заведомо неверный рост дальше не пускаем:
      // сервер всё равно отклонит патч, и человек не поймёт, что пошло не так
      case "about":
        return (
          !height.trim() ||
          (Number(height) >= HEIGHT_MIN && Number(height) <= HEIGHT_MAX)
        );
      default:
        return true;
    }
  }, [step, name, ageNum, gender, lookingFor, city, photos, height]);

  const go = useCallback((delta: number) => {
    setDirection(delta);
    setIndex((i) => Math.min(STEPS.length - 1, Math.max(0, i + delta)));
    haptic("light");
  }, []);

  /* ── Геопозиция ──────────────────────────────────────────── */
  const detectLocation = useCallback(async () => {
    setGeoBusy(true);
    const pos = await getCurrentPosition();
    setGeoBusy(false);
    if (!pos) {
      haptic("error");
      return;
    }
    setCoords({ lat: pos.latitude, lon: pos.longitude });
    haptic("success");
  }, []);

  /* ── Фото ────────────────────────────────────────────────── */
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

  const toggleInterest = useCallback((tag: string) => {
    setInterests((cur) => {
      if (cur.includes(tag)) return cur.filter((t) => t !== tag);
      if (cur.length >= MAX_INTERESTS) return cur;
      return [...cur, tag];
    });
  }, []);

  /* ── Сохранение ──────────────────────────────────────────── */
  const finish = useCallback(async () => {
    setSaving(true);
    setSaveError("");
    try {
      const patch: Record<string, unknown> = {
        display_name: name.trim(),
        age: ageNum,
        gender,
        looking_for: lookingFor,
        city: city.trim(),
        photos: photos.filter((p) => p.url).map((p) => p.url as string),
        interests,
        goal,
        subculture,
        bio: bio.trim(),
      };
      // Рост необязателен: пустое поле не отправляем вовсе, иначе схема
      // отклонит null как «меньше 120»
      const heightNum = Number(height);
      if (height.trim() && Number.isInteger(heightNum)) {
        patch.height_cm = heightNum;
      }
      if (coords) {
        patch.latitude = coords.lat;
        patch.longitude = coords.lon;
      }
      await updateMyProfile(patch);
      const fresh: UserProfile = await getMyProfile();
      setUser(fresh);
      haptic("success");
      navigate("/discover", { replace: true });
    } catch (e: any) {
      setSaveError(
        e?.response?.data?.detail ??
          "Не удалось сохранить анкету. Попробуйте ещё раз."
      );
      haptic("error");
    } finally {
      setSaving(false);
    }
  }, [
    name,
    ageNum,
    gender,
    lookingFor,
    city,
    photos,
    interests,
    goal,
    subculture,
    height,
    bio,
    coords,
    navigate,
    setUser,
  ]);

  return (
    <div className="flex flex-col h-screen-safe">
      {/* ── Шапка: назад и прогресс ─────────────────────────── */}
      <header className="safe-top px-4 pb-3 shrink-0">
        <div className="flex items-center gap-3 min-h-[44px]">
          <button
            aria-label="Назад"
            onClick={() => go(-1)}
            disabled={index === 0}
            className="tap-target flex items-center justify-center -ml-2
                       text-text-secondary disabled:opacity-0 transition-opacity"
          >
            <ChevronLeft size={24} />
          </button>
          <div className="flex-1 flex gap-1.5">
            {STEPS.map((_, i) => (
              <div
                key={i}
                className={`h-[3px] flex-1 rounded-full transition-colors duration-300 ${
                  i <= index ? "bg-dawn" : "bg-surface-2"
                }`}
              />
            ))}
          </div>
        </div>
      </header>

      {/* ── Шаги ────────────────────────────────────────────── */}
      <div className="flex-1 min-h-0 overflow-y-auto no-scrollbar px-5">
        <AnimatePresence mode="wait" custom={direction}>
          <motion.div
            key={step}
            custom={direction}
            initial={{ opacity: 0, x: direction * 40 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: direction * -40 }}
            transition={{ type: "spring", stiffness: 380, damping: 34 }}
            className="pt-4 pb-6"
          >
            {step === "name" && (
              <StepShell title="Как вас зовут?" hint="Это имя увидят другие люди">
                <TextField
                  value={name}
                  onChange={setName}
                  placeholder="Ваше имя"
                  maxLength={50}
                  autoFocus
                />
              </StepShell>
            )}

            {step === "age" && (
              <StepShell
                title="Сколько вам лет?"
                hint="Souldawn — сервис только для совершеннолетних"
              >
                <TextField
                  value={age}
                  onChange={(v) => setAge(v.replace(/\D/g, "").slice(0, 2))}
                  placeholder="18"
                  inputMode="numeric"
                  autoFocus
                />
                {age && ageNum < 18 && (
                  <p className="mt-3 text-[14px] text-danger">
                    Регистрация возможна с 18 лет.
                  </p>
                )}
              </StepShell>
            )}

            {step === "gender" && (
              <StepShell title="Ваш пол?">
                <OptionList
                  value={gender}
                  onChange={setGender}
                  options={[
                    { value: "male", label: "Мужской" },
                    { value: "female", label: "Женский" },
                    { value: "other", label: "Другое" },
                  ]}
                />
              </StepShell>
            )}

            {step === "lookingFor" && (
              <StepShell title="Кого показывать?">
                <OptionList
                  value={lookingFor}
                  onChange={setLookingFor}
                  options={[
                    { value: "female", label: "Девушек" },
                    { value: "male", label: "Парней" },
                    { value: "any", label: "Всех" },
                  ]}
                />
              </StepShell>
            )}

            {step === "city" && (
              <StepShell
                title="Из какого вы города?"
                hint="Поможем найти людей поблизости"
              >
                <TextField
                  value={city}
                  onChange={setCity}
                  placeholder="Москва"
                  maxLength={100}
                  autoFocus
                />
                <Button
                  variant="secondary"
                  size="md"
                  fullWidth
                  className="mt-3"
                  onClick={detectLocation}
                  disabled={geoBusy}
                >
                  {geoBusy ? (
                    <Spinner size={17} />
                  ) : (
                    <>
                      <MapPin size={16} />
                      {coords
                        ? "Местоположение определено"
                        : "Определить по геопозиции"}
                    </>
                  )}
                </Button>
                {coords && (
                  <p className="mt-2 text-caption text-text-muted text-center">
                    Точные координаты другим не показываются — только расстояние
                  </p>
                )}
              </StepShell>
            )}

            {step === "photos" && (
              <StepShell
                title="Добавьте фото"
                hint="Первое станет главным. Нужно хотя бы одно"
              >
                <div className="grid grid-cols-3 gap-2.5">
                  {Array.from({ length: MAX_PHOTOS }).map((_, i) => (
                    <PhotoTile
                      key={photos[i]?.id ?? `empty-${i}`}
                      slot={photos[i]}
                      isPrimary={i === 0}
                      onPick={addPhoto}
                      onRemove={() => photos[i] && removePhoto(photos[i].id)}
                      disabled={i > photos.length}
                    />
                  ))}
                </div>
              </StepShell>
            )}

            {step === "interests" && (
              <StepShell
                title="Что вам интересно?"
                hint={`Выбрано ${interests.length} из ${MAX_INTERESTS}`}
              >
                <div className="flex flex-wrap gap-2">
                  {INTERESTS.map((tag) => (
                    <Chip
                      key={tag}
                      active={interests.includes(tag)}
                      onClick={() => toggleInterest(tag)}
                    >
                      {tag}
                    </Chip>
                  ))}
                </div>
              </StepShell>
            )}

            {step === "about" && (
              <StepShell
                title="Что о вас скажет больше?"
                hint="Всё необязательно — но по этому вас найдут свои"
              >
                <p className="text-caption text-text-muted mb-2.5">Цель знакомства</p>
                <div className="flex flex-wrap gap-2 mb-7">
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

                <p className="text-caption text-text-muted mb-2.5">Субкультура</p>
                <div className="flex flex-wrap gap-2 mb-7">
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

                <p className="text-caption text-text-muted mb-2.5">Рост, см</p>
                <input
                  value={height}
                  onChange={(e) =>
                    setHeight(e.target.value.replace(/\D/g, "").slice(0, 3))
                  }
                  inputMode="numeric"
                  placeholder="Не указывать"
                  aria-label="Рост в сантиметрах"
                  className="w-full px-3.5 py-3 rounded-[var(--radius-tile)]
                             bg-surface-2 border border-hairline text-[15px]
                             placeholder:text-text-muted focus:outline-none
                             focus:border-accent/60"
                />
                {!!height && (Number(height) < HEIGHT_MIN || Number(height) > HEIGHT_MAX) && (
                  <p className="mt-2 text-[12px] text-danger">
                    Укажите рост от {HEIGHT_MIN} до {HEIGHT_MAX} см
                  </p>
                )}
              </StepShell>
            )}

            {step === "bio" && (
              <StepShell
                title="Пара слов о себе"
                hint="С этого людям проще начать разговор"
              >
                <textarea
                  value={bio}
                  onChange={(e) => setBio(e.target.value.slice(0, MAX_BIO))}
                  placeholder="Чем занимаетесь, что любите, кого ищете…"
                  rows={5}
                  className="w-full px-4 py-3.5 rounded-[var(--radius-tile)]
                             bg-surface border border-hairline resize-none
                             outline-none focus:border-accent transition-colors
                             placeholder:text-text-faint"
                />
                <p className="mt-2 text-caption text-text-muted text-right">
                  {bio.length} / {MAX_BIO}
                </p>
              </StepShell>
            )}

            {step === "done" && (
              <StepShell title="Всё готово!" hint="Проверьте, что всё верно">
                <Summary
                  name={name}
                  age={ageNum}
                  city={city}
                  photos={photos.filter((p) => p.url).length}
                  interests={interests}
                  bio={bio}
                />
                {saveError && (
                  <p className="mt-4 text-[14px] text-danger text-center">
                    {saveError}
                  </p>
                )}
              </StepShell>
            )}
          </motion.div>
        </AnimatePresence>
      </div>

      {/* ── Кнопка продолжения ──────────────────────────────── */}
      <div className="px-5 pt-3 pb-5 safe-bottom shrink-0">
        {step === "done" ? (
          <Button
            size="lg"
            fullWidth
            onClick={finish}
            disabled={saving}
            hapticKind="success"
          >
            {saving ? <Spinner size={20} /> : "Начать знакомиться"}
          </Button>
        ) : (
          <div className="flex flex-col gap-2">
            <Button size="lg" fullWidth onClick={() => go(1)} disabled={!canContinue}>
              Далее
            </Button>
            {(step === "bio" || step === "interests") && (
              <Button variant="ghost" size="md" fullWidth onClick={() => go(1)}>
                Пропустить
              </Button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Вспомогательные компоненты ─────────────────────────────── */

function StepShell({
  title,
  hint,
  children,
}: {
  title: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <h1 className="text-title font-extrabold mb-1.5">{title}</h1>
      <p className="text-[15px] text-text-muted mb-6">{hint ?? " "}</p>
      {children}
    </div>
  );
}

function TextField({
  value,
  onChange,
  placeholder,
  maxLength,
  inputMode,
  autoFocus,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  maxLength?: number;
  inputMode?: "text" | "numeric";
  autoFocus?: boolean;
}) {
  return (
    <input
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      maxLength={maxLength}
      inputMode={inputMode}
      autoFocus={autoFocus}
      className="w-full h-14 px-4 rounded-[var(--radius-tile)]
                 bg-surface border border-hairline text-[17px]
                 outline-none focus:border-accent transition-colors
                 placeholder:text-text-faint"
    />
  );
}

function OptionList({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <div className="flex flex-col gap-2.5">
      {options.map((o) => {
        const active = value === o.value;
        return (
          <button
            key={o.value}
            onClick={() => {
              haptic("select");
              onChange(o.value);
            }}
            className={`h-14 px-5 rounded-[var(--radius-tile)] text-left text-[16px]
                        font-medium flex items-center justify-between
                        border transition-colors ${
                          active
                            ? "border-accent bg-accent/10 text-text"
                            : "border-hairline bg-surface text-text-secondary"
                        }`}
          >
            {o.label}
            {active && <Check size={19} className="text-accent" />}
          </button>
        );
      })}
    </div>
  );
}

function PhotoTile({
  slot,
  isPrimary,
  onPick,
  onRemove,
  disabled,
}: {
  slot?: PhotoSlot;
  isPrimary: boolean;
  onPick: (f: File) => void;
  onRemove: () => void;
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
        if (f) onPick(f);
        // Сбрасываем значение, иначе повторный выбор того же файла не сработает
        e.target.value = "";
      }}
    />
  );

  if (slot?.url) {
    return (
      <div className="relative aspect-[3/4] rounded-[var(--radius-tile)] overflow-hidden bg-surface-2">
        <img src={slot.url} alt="" className="w-full h-full object-cover" />
        {isPrimary && (
          <span
            className="absolute top-1.5 left-1.5 px-2 py-0.5 rounded-full
                       bg-dawn text-[10px] font-bold text-white
                       flex items-center gap-1"
          >
            <Star size={9} fill="currentColor" />
            Главное
          </span>
        )}
        <button
          aria-label="Удалить фото"
          onClick={onRemove}
          className="absolute top-1.5 right-1.5 w-7 h-7 rounded-full
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

function Summary({
  name,
  age,
  city,
  photos,
  interests,
  bio,
}: {
  name: string;
  age: number;
  city: string;
  photos: number;
  interests: string[];
  bio: string;
}) {
  return (
    <div className="rounded-[var(--radius-tile)] bg-surface border border-hairline p-5">
      <p className="text-[19px] font-bold mb-0.5">
        {name}
        {Number.isFinite(age) && age > 0 ? `, ${age}` : ""}
      </p>
      <p className="text-[14px] text-text-muted mb-4">{city}</p>

      <Row label="Фотографии" value={String(photos)} />
      <Row
        label="Интересы"
        value={interests.length ? interests.join(", ") : "не выбраны"}
      />
      <Row
        label="О себе"
        value={bio.trim() ? `${bio.trim().slice(0, 60)}…` : "не заполнено"}
      />
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-3 py-2 border-t border-hairline first:border-t-0">
      <span className="text-caption text-text-muted w-[92px] shrink-0">{label}</span>
      <span className="text-[14px] flex-1 min-w-0 break-words">{value}</span>
    </div>
  );
}
