import { useState, useCallback, useMemo, useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useNavigate } from "react-router-dom";
import { X, ChevronLeft, MapPin, Check } from "lucide-react";
import {
  updateMyProfile,
  getMyProfile,
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
import PhotoGrid, { usePhotoSlots } from "../components/PhotoGrid";
import OnboardingIntro from "../components/OnboardingIntro";
import InterestsPicker from "../components/InterestsPicker";
import {
  GOALS,
  RELATION_TYPES,
  SUBCULTURES,
  MBTI_TYPES,
  HEIGHT_MIN,
  HEIGHT_MAX,
  MAX_INTERESTS,
  MAX_PHOTOS,
  MAX_BIO,
  MIN_AGE,
  MAX_AGE,
} from "../lib/profileOptions";

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

export default function Onboarding() {
  const navigate = useNavigate();
  const { user, setUser } = useStore();

  // Черновик читаем ровно один раз, при монтировании: повторное чтение на
  // рендере затирало бы то, что человек набрал в этой сессии.
  const [draft] = useState(loadDraft);
  const [restored, setRestored] = useState(() => !!draft);
  // Интро с живыми экранами — только новичку: тот, у кого есть черновик
  // или имя в анкете, уже видел приложение и пришёл доделать
  const [intro, setIntro] = useState(() => !draft && !user?.display_name);

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
  const [geoError, setGeoError] = useState("");
  const { photos, addPhoto, removePhoto, makePrimary, reset: resetPhotos } =
    usePhotoSlots(draft?.photos ?? user?.photos ?? []);
  const [interests, setInterests] = useState<string[]>(
    draft?.interests ?? user?.interests ?? []
  );
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
    resetPhotos(user?.photos ?? []);
    setInterests(user?.interests ?? []);
    setGoal(user?.goal ?? "");
    setRelationType(user?.relation_type ?? "");
    setSubculture(user?.subculture ?? "");
    setMbti(user?.mbti ?? "");
    setHeight(user?.height_cm != null ? String(user.height_cm) : "");
    setBio(user?.bio ?? "");
    haptic("light");
  }, [user, resetPhotos]);

  /* ── Геопозиция ──────────────────────────────────────────── */
  const detectLocation = useCallback(async () => {
    setGeoBusy(true);
    setGeoError("");
    const pos = await getCurrentPosition();
    setGeoBusy(false);
    if (!pos) {
      haptic("error");
      setGeoError("Не удалось определить геопозицию — проверьте доступ к ней");
      return;
    }
    setCoords({ lat: pos.latitude, lon: pos.longitude });
    setGeoError("");
    haptic("success");
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

  if (intro) {
    return <OnboardingIntro onStart={() => setIntro(false)} />;
  }

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
                /* Непройденные шаги держим на акценте с прозрачностью, а не
                   на поверхности: surface-2 на почти чёрной канве — это два
                   тёмных тона, на полосе 3 px они не различались вовсе, и
                   вместо «сколько осталось» человек видел одинокую чёрточку
                   без конца. Альфа акцента честно работает и на светлых
                   схемах, где любая заливка «белым по прозрачности» пропала бы */
                className={`h-[3px] flex-1 rounded-full transition-colors duration-300 ${
                  i <= index ? "bg-accent" : "bg-accent/25"
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
                {geoError && (
                  <p className="mt-2 text-caption text-danger text-center" role="alert">
                    {geoError}
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
                <PhotoGrid
                  photos={photos}
                  max={MAX_PHOTOS}
                  onPick={addPhoto}
                  onRemove={removePhoto}
                  onMakePrimary={makePrimary}
                />
              </StepShell>
            )}

            {step === "interests" && (
              <StepShell
                title="Что вам интересно?"
                hint={`Выбрано ${interests.length} из ${MAX_INTERESTS}`}
              >
                <InterestsPicker
                  value={interests}
                  onChange={setInterests}
                  max={MAX_INTERESTS}
                />
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
                  className="field w-full px-3.5 py-3 rounded-[var(--radius-tile)] text-[15px]"
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
                  className="field w-full px-4 py-3.5 rounded-[var(--radius-tile)] resize-none"
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
      type="text"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      maxLength={maxLength}
      inputMode={inputMode}
      aria-label={placeholder}
      spellCheck={inputMode !== "numeric"}
      autoFocus={autoFocus}
      className="field w-full h-14 px-4 rounded-[var(--radius-tile)] text-[17px]"
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
    <div className="flex flex-col gap-2.5" role="group" aria-label="Выберите вариант">
      {options.map((o) => {
        const active = value === o.value;
        return (
          <button
            key={o.value}
            type="button"
            aria-pressed={active}
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
    <div className="glass rounded-[20px] p-5">
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
