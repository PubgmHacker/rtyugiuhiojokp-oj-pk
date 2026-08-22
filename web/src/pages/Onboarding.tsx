import { useState, useCallback, useMemo, useId, useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useNavigate } from "react-router-dom";
import {
  Camera, X, ChevronLeft, ChevronDown, MapPin, Check, Star,
} from "lucide-react";
import {
  updateMyProfile,
  getMyProfile,
  uploadPhoto,
  type UserProfile,
} from "../lib/api";
import { useStore } from "../lib/store";
import { haptic } from "../lib/haptics";
import { legalUrl } from "../lib/legal";
import { getCurrentPosition } from "../lib/native";
import { setClosingConfirmation } from "../lib/telegram";
import { useTelegramBack } from "../lib/useTelegramBack";
import {
  loadDraft,
  saveDraft,
  clearDraft,
  type DraftFields,
} from "../lib/onboardingDraft";
import { Button, Chip, Spinner } from "../components/ui";
import {
  GOALS,
  RELATION_TYPES,
  SUBCULTURES,
  MBTI_TYPES,
  HEIGHT_MIN,
  HEIGHT_MAX,
  INTEREST_CATEGORIES,
} from "../lib/profileOptions";

// Было 8 при 24 тегах в одном списке (треть списка). Список интересов
// расширен до ~110 по категориям, а лимит выбора сознательно уменьшен, а
// не увеличен вместе с ним: у конкурента («Мимолёт») лимит 3-5, и это
// работает лучше — чем меньше тегов, тем осмысленнее совпадение в подборе
// (см. matching._compatibility: там считаются общие интересы, и 12 тегов
// почти у всех пересекались бы хоть чем-то, обесценивая совпадение).
const MAX_INTERESTS = 5;
const MAX_PHOTOS = 6;
const MAX_BIO = 500;
// Те же числа, что MIN_AGE/MAX_AGE в api/config.py: сервер отклонит анкету
// вне границ, а клиент обязан сказать это до отправки, теми же числами.
// Синхронность с сервером и текстами проверяет api/tests/test_age_floor.py.
const MIN_AGE = 18;
const MAX_AGE = 99;

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
  | "terms"
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
  // Явное согласие: магазины кладут приложение, если согласие спрятано
  // в ссылку под «Войти». Отдельный шаг — иначе его пропускают.
  "terms",
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

  // Черновик читаем ровно один раз, при монтировании: повторное чтение на
  // рендере затирало бы то, что человек набрал в этой сессии.
  const [draft] = useState(loadDraft);
  const [restored, setRestored] = useState(() => !!draft);

  const [index, setIndex] = useState(() =>
    draft ? Math.min(draft.index, STEPS.length - 1) : 0
  );
  const [direction, setDirection] = useState(1);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");

  // Экран используется и для правки анкеты — подставляем, что уже есть.
  // Черновик приоритетнее профиля: он новее, и именно его человек не докончил.
  const [name, setName] = useState(draft?.name ?? user?.display_name ?? "");
  const [age, setAge] = useState(
    draft?.age ?? (user?.age ? String(user.age) : "")
  );
  const [gender, setGender] = useState(draft?.gender ?? user?.gender ?? "");
  const [lookingFor, setLookingFor] = useState(
    draft?.lookingFor ?? user?.looking_for ?? ""
  );
  const [city, setCity] = useState(draft?.city ?? user?.city ?? "");
  const [coords, setCoords] = useState<{ lat: number; lon: number } | null>(
    draft?.coords ?? null
  );
  const [geoBusy, setGeoBusy] = useState(false);
  const [photos, setPhotos] = useState<PhotoSlot[]>(() =>
    (draft?.photos ?? user?.photos ?? []).map((url) => ({
      id: `init-${photoSeq++}`,
      url,
    }))
  );
  const [interests, setInterests] = useState<string[]>(
    draft?.interests ?? user?.interests ?? []
  );
  // Категории интересов сворачиваемые: на экране 320px список из ~110 тегов
  // одной простыней не читается. Открытые по умолчанию — те, где у человека
  // уже есть выбранный тег (правка анкеты), плюс первая категория для новых.
  const [openCategories, setOpenCategories] = useState<Set<string>>(() => {
    const initial = new Set<string>();
    const mine = new Set(interests);
    for (const [cat, tags] of Object.entries(INTEREST_CATEGORIES)) {
      if (tags.some((t) => mine.has(t))) initial.add(cat);
    }
    if (initial.size === 0) initial.add(Object.keys(INTEREST_CATEGORIES)[0]);
    return initial;
  });
  const [goal, setGoal] = useState(draft?.goal ?? user?.goal ?? "");
  const [relationType, setRelationType] = useState(
    draft?.relationType ?? user?.relation_type ?? ""
  );
  const [subculture, setSubculture] = useState(
    draft?.subculture ?? user?.subculture ?? ""
  );
  const [mbti, setMbti] = useState(draft?.mbti ?? user?.mbti ?? "");
  const [height, setHeight] = useState(
    draft?.height ?? (user?.height_cm != null ? String(user.height_cm) : "")
  );
  const [bio, setBio] = useState(draft?.bio ?? user?.bio ?? "");

  const step = STEPS[index];
  const ageNum = Number(age);

  const canContinue = useMemo(() => {
    switch (step) {
      case "name":
        return name.trim().length >= 2;
      case "age":
        return Number.isInteger(ageNum) && ageNum >= MIN_AGE && ageNum <= MAX_AGE;
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

  // Нативная кнопка «назад» Telegram водит по шагам анкеты, а не выкидывает из
  // мини-аппа: в шапке она стоит рядом с «Закрыть», и человек, тапнув привычную
  // стрелку, терял всю анкету. На первом шаге прячем — назад некуда.
  useTelegramBack(index > 0 ? () => go(-1) : null);

  // Подтверждение закрытия на весь онбординг. Черновик мы теперь пишем, так что
  // данные не сгорят, но незакрытая анкета — это незарегистрированный человек:
  // случайный тап «Закрыть» посреди воронки чаще всего не возвращается. Снимаем
  // при уходе с экрана, иначе подтверждение осталось бы висеть на всём
  // приложении — кнопка в Telegram одна и глобальная.
  useEffect(() => {
    setClosingConfirmation(true);
    return () => setClosingConfirmation(false);
  }, []);

  /* ── Черновик ────────────────────────────────────────────────
     Пишем при любом изменении, а не «на следующем шаге»: потерять можно
     ровно тот шаг, который человек заполняет прямо сейчас. */

  const черновик = useMemo<DraftFields>(
    () => ({
      index,
      name,
      age,
      gender,
      lookingFor,
      city,
      coords,
      photos: photos.filter((p) => p.url).map((p) => p.url as string),
      interests,
      goal,
      relationType,
      subculture,
      mbti,
      height,
      bio,
    }),
    [
      index,
      name,
      age,
      gender,
      lookingFor,
      city,
      coords,
      photos,
      interests,
      goal,
      relationType,
      subculture,
      mbti,
      height,
      bio,
    ]
  );

  // Свежий снимок для обработчика выгрузки: он навешивается один раз и иначе
  // видел бы значения на момент монтирования
  const черновикRef = useRef(черновик);
  черновикRef.current = черновик;
  // Первый прогон эффекта — это монтирование. Запись на нём создала бы
  // черновик из подставленных значений профиля там, где человек ничего не
  // трогал, и в следующий раз ему показали бы плашку «продолжаем» на пустом
  // месте.
  const монтирование = useRef(true);
  const завершено = useRef(false);

  useEffect(() => {
    if (монтирование.current) {
      монтирование.current = false;
      return;
    }
    if (завершено.current) return;
    const t = setTimeout(() => saveDraft(черновик), 400);
    return () => clearTimeout(t);
  }, [черновик]);

  // Telegram на iOS выгружает мини-апп при переключении чата и не обещает, что
  // отложенная запись успеет сработать. `pagehide` и переход в hidden —
  // единственные события, которые приходят до выгрузки; без них задержка в
  // 400 мс означала бы потерю последнего введённого шага.
  useEffect(() => {
    const сбросить = () => {
      if (!монтирование.current && !завершено.current) {
        saveDraft(черновикRef.current);
      }
    };
    const наСкрытие = () => {
      if (document.visibilityState === "hidden") сбросить();
    };
    window.addEventListener("pagehide", сбросить);
    document.addEventListener("visibilitychange", наСкрытие);
    return () => {
      window.removeEventListener("pagehide", сбросить);
      document.removeEventListener("visibilitychange", наСкрытие);
    };
  }, []);

  /** Отказаться от восстановленного черновика и начать анкету с нуля. */
  const начатьЗаново = useCallback(() => {
    clearDraft();
    // Следующий прогон эффекта — не ввод человека, а этот сброс: иначе он
    // тут же записал бы черновик заново
    монтирование.current = true;
    setRestored(false);
    setDirection(-1);
    setIndex(0);
    setName(user?.display_name ?? "");
    setAge(user?.age ? String(user.age) : "");
    setGender(user?.gender ?? "");
    setLookingFor(user?.looking_for ?? "");
    setCity(user?.city ?? "");
    setCoords(null);
    setPhotos((user?.photos ?? []).map((url) => ({ id: `init-${photoSeq++}`, url })));
    setInterests(user?.interests ?? []);
    setGoal(user?.goal ?? "");
    setRelationType(user?.relation_type ?? "");
    setSubculture(user?.subculture ?? "");
    setMbti(user?.mbti ?? "");
    setHeight(user?.height_cm != null ? String(user.height_cm) : "");
    setBio(user?.bio ?? "");
    haptic("light");
  }, [user]);

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

  const toggleInterest = useCallback((tag: string) => {
    setInterests((cur) => {
      if (cur.includes(tag)) return cur.filter((t) => t !== tag);
      if (cur.length >= MAX_INTERESTS) return cur;
      return [...cur, tag];
    });
  }, []);

  const toggleCategory = useCallback((cat: string) => {
    haptic("light");
    setOpenCategories((cur) => {
      const next = new Set(cur);
      if (next.has(cat)) next.delete(cat);
      else next.add(cat);
      return next;
    });
  }, []);

  // Теги из старой анкеты, не входящие ни в одну текущую категорию
  // (например, интерес отменили при реорганизации списка). Их нельзя молча
  // потерять при следующем сохранении — показываем отдельной секцией,
  // всегда открытой, чтобы человек видел, что выбрано, и мог снять галочку.
  const legacyInterests = useMemo(() => {
    const known = new Set(Object.values(INTEREST_CATEGORIES).flat());
    return interests.filter((t) => !known.has(t));
  }, [interests]);

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
        relation_type: relationType,
        subculture,
        mbti,
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
      // Анкета на сервере — черновик больше не нужен и не должен всплыть
      // плашкой «продолжаем» при следующей правке профиля. Чистим сразу после
      // успешного PATCH, а не после перехода: если следующий запрос упадёт,
      // данные всё равно уже сохранены.
      завершено.current = true;
      clearDraft();
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
    relationType,
    subculture,
    mbti,
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
                  i <= index ? "bg-accent" : "bg-surface-2"
                }`}
              />
            ))}
          </div>
        </div>
      </header>

      {/* Восстановленный черновик: без этой строки человек не понимает, почему
          анкета уже заполнена и открыта на середине — и подозревает, что видит
          чужие данные */}
      {restored && (
        <div
          className="mx-5 mb-1 flex items-center gap-1 shrink-0
                     rounded-[var(--radius-tile)] border border-hairline
                     bg-surface pl-3.5 pr-1 py-2"
        >
          <p className="flex-1 text-[13px] leading-snug text-text-muted">
            Продолжаем с того места, где вы остановились
          </p>
          <button
            onClick={начатьЗаново}
            className="tap-target px-2 text-[13px] font-semibold text-accent"
          >
            Заново
          </button>
          <button
            aria-label="Скрыть подсказку"
            onClick={() => setRestored(false)}
            className="tap-target px-1.5 text-text-faint"
          >
            <X size={15} />
          </button>
        </div>
      )}

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
                hint="Симп — сервис с 18 лет"
              >
                <TextField
                  value={age}
                  onChange={(v) => setAge(v.replace(/\D/g, "").slice(0, 2))}
                  placeholder="18"
                  inputMode="numeric"
                  autoFocus
                />
                {age && ageNum < MIN_AGE && (
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
                hint={
                  photos.filter((p) => p.url).length > 1
                    ? "Первое — главное. Нажмите на любое другое, чтобы сделать его главным"
                    : "Первое станет главным. Нужно хотя бы одно"
                }
              >
                <div className="grid grid-cols-3 gap-2.5">
                  {Array.from({ length: MAX_PHOTOS }).map((_, i) => (
                    <PhotoTile
                      key={photos[i]?.id ?? `empty-${i}`}
                      slot={photos[i]}
                      isPrimary={i === 0}
                      onPick={addPhoto}
                      onRemove={() => photos[i] && removePhoto(photos[i].id)}
                      onMakePrimary={() => photos[i] && makePrimary(photos[i].id)}
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
                <div className="flex flex-col gap-2">
                  {legacyInterests.length > 0 && (
                    <div className="rounded-[var(--radius-tile)] border border-hairline bg-surface p-3.5">
                      <p className="text-caption text-text-muted mb-2.5">
                        Уже выбрано ранее
                      </p>
                      <div className="flex flex-wrap gap-2">
                        {legacyInterests.map((tag) => (
                          <Chip key={tag} active onClick={() => toggleInterest(tag)}>
                            {tag}
                          </Chip>
                        ))}
                      </div>
                    </div>
                  )}

                  {Object.entries(INTEREST_CATEGORIES).map(([cat, tags]) => {
                    const open = openCategories.has(cat);
                    const chosenHere = tags.filter((t) => interests.includes(t)).length;
                    return (
                      <div
                        key={cat}
                        className="rounded-[var(--radius-tile)] border border-hairline bg-surface overflow-hidden"
                      >
                        <button
                          type="button"
                          onClick={() => toggleCategory(cat)}
                          aria-expanded={open}
                          className="w-full flex items-center justify-between px-3.5 py-3
                                     text-[14.5px] font-semibold"
                        >
                          <span className="flex items-center gap-2">
                            {cat}
                            {chosenHere > 0 && (
                              <span className="w-5 h-5 rounded-full bg-accent/15 text-accent
                                                text-[11px] font-bold flex items-center justify-center">
                                {chosenHere}
                              </span>
                            )}
                          </span>
                          <ChevronDown
                            size={17}
                            className={`text-text-muted transition-transform ${open ? "rotate-180" : ""}`}
                          />
                        </button>
                        {open && (
                          <div className="flex flex-wrap gap-2 px-3.5 pb-3.5">
                            {tags.map((tag) => (
                              <Chip
                                key={tag}
                                active={interests.includes(tag)}
                                onClick={() => toggleInterest(tag)}
                              >
                                {tag}
                              </Chip>
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })}
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

                {/* Тип связи — «с кем», отдельная ось от цели («зачем») */}
                <p className="text-caption text-text-muted mb-2.5">С кем</p>
                <div className="flex flex-wrap gap-2 mb-7">
                  {RELATION_TYPES.map((o) => (
                    <Chip
                      key={o.value}
                      active={relationType === o.value}
                      onClick={() =>
                        setRelationType(relationType === o.value ? "" : o.value)
                      }
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

                <p className="text-caption text-text-muted mb-2.5">
                  Тип личности (MBTI)
                </p>
                <div className="flex flex-wrap gap-2 mb-7">
                  {MBTI_TYPES.map((o) => (
                    <Chip
                      key={o.value}
                      active={mbti === o.value}
                      onClick={() => setMbti(mbti === o.value ? "" : o.value)}
                    >
                      {o.value}
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

            {step === "terms" && (
              <StepShell
                title="Правила и безопасность"
                hint="Прочтите перед тем, как начать знакомиться"
              >
                <div className="space-y-3 text-[14px] text-text-muted">
                  <p>
                    Нажимая «Принимаю», вы подтверждаете, что вам 18 лет или
                    больше, и принимаете{" "}
                    {/* Адрес абсолютный не для красоты: в нативной сборке origin —
                        `capacitor://localhost`, и относительная ссылка с
                        `target="_blank"` не открывается ничем. Экран согласия без
                        читаемого документа — это и претензия ревью App Store, и
                        человек, принимающий то, чего не видел. */}
                    <a
                      href={legalUrl("terms")}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-text underline underline-offset-2"
                    >
                      условия
                    </a>{" "}
                    и{" "}
                    <a
                      href={legalUrl("privacy")}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-text underline underline-offset-2"
                    >
                      политику
                    </a>
                    .
                  </p>
                  {/* Обещание нулевой терпимости — требование App Store к
                      приложениям с пользовательским контентом (Guideline
                      1.2): оно должно прозвучать до начала общения, а не
                      прятаться в оферте. То же обещание — в правилах
                      сообщества и в согласии бота. */}
                  <p>
                    К оскорблениям, травле и откровенному контенту у нас
                    нулевая терпимость: такие анкеты и сообщения блокируются,
                    а пожаловаться можно на любую анкету, фото или сообщение.
                  </p>
                  <p>
                    Мы не мониторим и не продаём ваши переписки.
                  </p>
                </div>
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
        ) : step === "terms" ? (
          <Button
            size="lg"
            fullWidth
            onClick={() => go(1)}
            hapticKind="success"
          >
            Принимаю
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
  onMakePrimary,
  disabled,
}: {
  slot?: PhotoSlot;
  isPrimary: boolean;
  onPick: (f: File) => void;
  onRemove: () => void;
  onMakePrimary: () => void;
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
      <div className="relative aspect-[3/4] rounded-[var(--radius-tile)] overflow-hidden bg-surface-2">
        <img src={slot.url} alt="" className="w-full h-full object-cover" />
        {isPrimary ? (
          <span
            className="absolute top-1.5 left-1.5 px-2 py-0.5 rounded-full
                       bg-accent text-[10px] font-bold text-white
                       flex items-center gap-1"
          >
            <Star size={9} fill="currentColor" />
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
            <span
              className="px-2 py-0.5 rounded-full bg-black/55 backdrop-blur-sm
                         text-[10px] font-semibold text-white
                         flex items-center gap-1"
            >
              <Star size={9} />
              Главным
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
