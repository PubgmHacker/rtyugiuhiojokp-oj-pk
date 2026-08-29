import { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { ChevronLeft, MapPin } from "lucide-react";
import { updateMyProfile, getMyProfile, type UserProfile } from "../lib/api";
import { useStore } from "../lib/store";
import { haptic } from "../lib/haptics";
import { getCurrentPosition } from "../lib/native";
import { setClosingConfirmation } from "../lib/telegram";
import { Button, Chip, ScreenHeader, Spinner } from "../components/ui";
import PhotoGrid, { usePhotoSlots } from "../components/PhotoGrid";
import VideoGrid, { useVideoSlots } from "../components/VideoGrid";
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
  MAX_VIDEOS,
  MAX_BIO,
  MIN_AGE,
  MAX_AGE,
} from "../lib/profileOptions";

/**
 * Точечное редактирование анкеты (аудит, блок «Продукт»).
 *
 * До этого экрана «Редактировать анкету» вела в онбординг: чтобы поправить
 * одно слово в био, человек прощёлкивал одиннадцать шагов заново. Здесь вся
 * анкета — один экран, а сохранение отправляет ТОЛЬКО изменённые поля одним
 * PATCH: сервер и так принимает частичный патч (exclude_unset), не хватало
 * ровно клиента.
 *
 * Это же единственное место, где рост можно стереть: онбординг пустое поле
 * просто не отправляет, и указанный однажды рост оставался навсегда.
 *
 * Свой обработчик кнопки «назад» Telegram не регистрируем: глобальный
 * TelegramBack в App.tsx уже делает navigate(-1) для не-корневых путей,
 * а второй обработчик заставил бы один тап срабатывать дважды.
 */
export default function EditProfile() {
  const navigate = useNavigate();
  const { user, setUser } = useStore();
  // Анкета обычно уже в сторе (сюда приходят из «Профиля»); прямое открытие
  // по ссылке — дотягиваем с сервера
  const [base, setBase] = useState<UserProfile | null>(user);

  useEffect(() => {
    if (base) return;
    let жив = true;
    getMyProfile()
      .then((p) => {
        if (!жив) return;
        setUser(p);
        setBase(p);
      })
      .catch(() => {});
    return () => {
      жив = false;
    };
  }, [base, setUser]);

  if (!base) {
    return (
      <div className="h-screen-safe flex items-center justify-center">
        <Spinner size={24} />
      </div>
    );
  }
  return <EditForm base={base} />;
}

/** Ключи фокуса (?focus=…) — те же, что в чек-листе заполненности и nudge. */
const АЛИАСЫ_ФОКУСА: Record<string, string> = { photo: "photos" };

function EditForm({ base }: { base: UserProfile }) {
  const navigate = useNavigate();
  const { setUser } = useStore();
  const { search } = useLocation();

  const [name, setName] = useState(base.display_name ?? "");
  const [age, setAge] = useState(base.age ? String(base.age) : "");
  const [gender, setGender] = useState(base.gender ?? "");
  const [lookingFor, setLookingFor] = useState(base.looking_for ?? "");
  const [city, setCity] = useState(base.city ?? "");
  const [coords, setCoords] = useState<{ lat: number; lon: number } | null>(null);
  const [geoBusy, setGeoBusy] = useState(false);
  const [geoError, setGeoError] = useState("");
  const { photos, addPhoto, removePhoto, makePrimary } = usePhotoSlots(
    base.photos ?? []
  );
  const { videos, addVideo, removeVideo } = useVideoSlots(base.videos ?? []);
  const [interests, setInterests] = useState<string[]>(base.interests ?? []);
  const [goal, setGoal] = useState(base.goal ?? "");
  const [relationType, setRelationType] = useState(base.relation_type ?? "");
  const [subculture, setSubculture] = useState(base.subculture ?? "");
  const [mbti, setMbti] = useState(base.mbti ?? "");
  const [height, setHeight] = useState(
    base.height_cm != null ? String(base.height_cm) : ""
  );
  const [bio, setBio] = useState(base.bio ?? "");

  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");

  /* ── Диff: в PATCH уходит только то, что реально поменялось ── */
  const patch = useMemo(() => {
    const p: Record<string, unknown> = {};
    if (name.trim() !== (base.display_name ?? "")) p.display_name = name.trim();
    const ageNum = Number(age);
    if (age.trim() && ageNum !== (base.age ?? 0)) p.age = ageNum;
    if (gender !== (base.gender ?? "")) p.gender = gender;
    if (lookingFor !== (base.looking_for ?? "")) p.looking_for = lookingFor;
    if (city.trim() !== (base.city ?? "")) p.city = city.trim();
    const urls = photos.filter((s) => s.url).map((s) => s.url as string);
    if (JSON.stringify(urls) !== JSON.stringify(base.photos ?? []))
      p.photos = urls;
    // Слоты держат только проигрываемые URL; file_id из бота (не-URL) в
    // сетке не видны — сохраняем их как есть, чтобы PATCH их не стёр молча
    const keptRaw = (base.videos ?? []).filter((v) => !/^https?:\/\//.test(v));
    const videoUrls = [
      ...keptRaw,
      ...videos.filter((s) => s.url).map((s) => s.url as string),
    ];
    if (JSON.stringify(videoUrls) !== JSON.stringify(base.videos ?? []))
      p.videos = videoUrls;
    if (JSON.stringify(interests) !== JSON.stringify(base.interests ?? []))
      p.interests = interests;
    if (goal !== (base.goal ?? "")) p.goal = goal;
    if (relationType !== (base.relation_type ?? ""))
      p.relation_type = relationType;
    if (subculture !== (base.subculture ?? "")) p.subculture = subculture;
    if (mbti !== (base.mbti ?? "")) p.mbti = mbti;
    // Пустое поле — осознанное «стереть рост»: сервер принимает явный null
    // ровно для этого поля (см. СБРАСЫВАЕМЫЕ в api/routers/profiles.py)
    const heightNum = height.trim() ? Number(height) : null;
    if (heightNum !== (base.height_cm ?? null)) p.height_cm = heightNum;
    if (bio.trim() !== (base.bio ?? "")) p.bio = bio.trim();
    if (coords) {
      p.latitude = coords.lat;
      p.longitude = coords.lon;
    }
    return p;
  }, [
    base,
    name,
    age,
    gender,
    lookingFor,
    city,
    photos,
    videos,
    interests,
    goal,
    relationType,
    subculture,
    mbti,
    height,
    bio,
    coords,
  ]);

  const dirty = Object.keys(patch).length > 0;
  const uploading =
    photos.some((s) => s.uploading) || videos.some((s) => s.uploading);

  // Те же границы, что в онбординге: сервер отклонит и без нас, но человек
  // должен услышать это до отправки, а не разбирать 422
  const ошибка = useMemo(() => {
    if (name.trim().length < 2) return "Имя — минимум 2 символа";
    const ageNum = Number(age);
    if (!age.trim() || !Number.isInteger(ageNum) || ageNum < MIN_AGE || ageNum > MAX_AGE)
      return `Возраст — целое число от ${MIN_AGE} до ${MAX_AGE}`;
    if (city.trim().length < 2) return "Укажите город";
    if (!photos.some((s) => s.url)) return "Нужно хотя бы одно фото";
    if (
      height.trim() &&
      (Number(height) < HEIGHT_MIN || Number(height) > HEIGHT_MAX)
    )
      return `Рост — от ${HEIGHT_MIN} до ${HEIGHT_MAX} см`;
    return "";
  }, [name, age, city, photos, height]);

  /* ── Фокус из nudge: ?focus=height прокручивает к полю ────── */
  const [highlight, setHighlight] = useState<string | null>(null);
  useEffect(() => {
    const raw = new URLSearchParams(search).get("focus");
    if (!raw) return;
    const key = АЛИАСЫ_ФОКУСА[raw] ?? raw;
    const el = document.getElementById(`edit-${key}`);
    if (!el) return;
    // Даём layout отрисоваться, затем скроллим; подсветку держим пару секунд
    const t = setTimeout(() => {
      el.scrollIntoView?.({ behavior: "smooth", block: "center" });
      setHighlight(key);
    }, 80);
    const t2 = setTimeout(() => setHighlight(null), 2400);
    return () => {
      clearTimeout(t);
      clearTimeout(t2);
    };
  }, [search]);

  // Несохранённые правки — подтверждение закрытия мини-аппа, как в онбординге
  useEffect(() => {
    setClosingConfirmation(dirty);
    return () => setClosingConfirmation(false);
  }, [dirty]);

  const detectLocation = async () => {
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
  };

  const save = async () => {
    setSaving(true);
    setSaveError("");
    try {
      const fresh = await updateMyProfile(patch);
      setUser(fresh);
      haptic("success");
      navigate("/profile");
    } catch (e: any) {
      setSaveError(
        e?.response?.data?.detail ?? "Не удалось сохранить. Попробуйте ещё раз."
      );
      haptic("error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex flex-col h-screen-safe">
      <ScreenHeader
        title="Редактирование"
        left={
          <button
            aria-label="Назад"
            onClick={() => {
              haptic("light");
              navigate(-1);
            }}
            className="tap-target flex items-center justify-center -ml-2 text-text-secondary"
          >
            <ChevronLeft size={24} />
          </button>
        }
      />

      <div className="flex-1 min-h-0 overflow-y-auto no-scrollbar px-5 pt-4 pb-6">
        <Section
          id="photos"
          title="Фото"
          hint={
            photos.filter((s) => s.url).length > 1
              ? "Первое — главное. Нажмите на любое другое, чтобы сделать его главным"
              : "Первое станет главным. Нужно хотя бы одно"
          }
          highlight={highlight === "photos"}
        >
          <PhotoGrid
            photos={photos}
            max={MAX_PHOTOS}
            onPick={addPhoto}
            onRemove={removePhoto}
            onMakePrimary={makePrimary}
          />
        </Section>

        <Section
          id="videos"
          title="Видео"
          hint="Необязательно. Ролики показываются в анкете после фото"
          highlight={highlight === "videos"}
        >
          <VideoGrid
            videos={videos}
            max={MAX_VIDEOS}
            onPick={addVideo}
            onRemove={removeVideo}
          />
        </Section>

        <Section id="name" title="Имя" highlight={highlight === "name"}>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Ваше имя"
            maxLength={50}
            aria-label="Имя"
            className="w-full h-12 px-4 rounded-[var(--radius-tile)]
                       bg-surface border border-hairline text-[16px]
                       outline-none focus:border-accent transition-colors
                       placeholder:text-text-faint"
          />
        </Section>

        <Section id="age" title="Возраст" highlight={highlight === "age"}>
          <input
            value={age}
            onChange={(e) => setAge(e.target.value.replace(/\D/g, "").slice(0, 2))}
            inputMode="numeric"
            placeholder="18"
            aria-label="Возраст"
            className="w-full h-12 px-4 rounded-[var(--radius-tile)]
                       bg-surface border border-hairline text-[16px]
                       outline-none focus:border-accent transition-colors
                       placeholder:text-text-faint"
          />
        </Section>

        <Section id="gender" title="Пол" highlight={highlight === "gender"}>
          <div className="flex flex-wrap gap-2">
            {[
              { value: "male", label: "Мужской" },
              { value: "female", label: "Женский" },
              { value: "other", label: "Другое" },
            ].map((o) => (
              <Chip
                key={o.value}
                active={gender === o.value}
                onClick={() => setGender(o.value)}
              >
                {o.label}
              </Chip>
            ))}
          </div>
        </Section>

        <Section
          id="looking_for"
          title="Кого показывать"
          highlight={highlight === "looking_for"}
        >
          <div className="flex flex-wrap gap-2">
            {[
              { value: "female", label: "Девушек" },
              { value: "male", label: "Парней" },
              { value: "any", label: "Всех" },
            ].map((o) => (
              <Chip
                key={o.value}
                active={lookingFor === o.value}
                onClick={() => setLookingFor(o.value)}
              >
                {o.label}
              </Chip>
            ))}
          </div>
        </Section>

        <Section id="city" title="Город" highlight={highlight === "city"}>
          <input
            value={city}
            onChange={(e) => setCity(e.target.value)}
            placeholder="Москва"
            maxLength={100}
            aria-label="Город"
            className="w-full h-12 px-4 rounded-[var(--radius-tile)]
                       bg-surface border border-hairline text-[16px]
                       outline-none focus:border-accent transition-colors
                       placeholder:text-text-faint"
          />
          <Button
            variant="secondary"
            size="md"
            fullWidth
            className="mt-2.5"
            onClick={detectLocation}
            disabled={geoBusy}
          >
            {geoBusy ? (
              <Spinner size={17} />
            ) : (
              <>
                <MapPin size={16} />
                {coords ? "Местоположение определено" : "Обновить геопозицию"}
              </>
            )}
          </Button>
          {geoError && (
            <p className="mt-2 text-caption text-danger text-center" role="alert">
              {geoError}
            </p>
          )}
        </Section>

        <Section
          id="goal"
          title="Цель знакомства"
          highlight={highlight === "goal"}
        >
          <div className="flex flex-wrap gap-2">
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
        </Section>

        <Section
          id="relation_type"
          title="С кем"
          highlight={highlight === "relation_type"}
        >
          <div className="flex flex-wrap gap-2">
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
        </Section>

        <Section
          id="subculture"
          title="Субкультура"
          highlight={highlight === "subculture"}
        >
          <div className="flex flex-wrap gap-2">
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
        </Section>

        <Section
          id="mbti"
          title="Тип личности (MBTI)"
          highlight={highlight === "mbti"}
        >
          <div className="flex flex-wrap gap-2">
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
        </Section>

        <Section
          id="height"
          title="Рост, см"
          hint="Оставьте пустым, чтобы убрать рост из анкеты"
          highlight={highlight === "height"}
        >
          <input
            value={height}
            onChange={(e) =>
              setHeight(e.target.value.replace(/\D/g, "").slice(0, 3))
            }
            inputMode="numeric"
            placeholder="Не указывать"
            aria-label="Рост в сантиметрах"
            className="w-full h-12 px-4 rounded-[var(--radius-tile)]
                       bg-surface border border-hairline text-[16px]
                       outline-none focus:border-accent transition-colors
                       placeholder:text-text-faint"
          />
        </Section>

        <Section
          id="interests"
          title="Интересы"
          hint={`Выбрано ${interests.length} из ${MAX_INTERESTS}`}
          highlight={highlight === "interests"}
        >
          <InterestsPicker
            value={interests}
            onChange={setInterests}
            max={MAX_INTERESTS}
          />
        </Section>

        <Section id="bio" title="О себе" highlight={highlight === "bio"}>
          <textarea
            value={bio}
            onChange={(e) => setBio(e.target.value.slice(0, MAX_BIO))}
            placeholder="Чем занимаетесь, что любите, кого ищете…"
            rows={5}
            aria-label="О себе"
            className="w-full px-4 py-3.5 rounded-[var(--radius-tile)]
                       bg-surface border border-hairline resize-none
                       outline-none focus:border-accent transition-colors
                       placeholder:text-text-faint"
          />
          <p className="mt-1.5 text-caption text-text-muted text-right">
            {bio.length} / {MAX_BIO}
          </p>
        </Section>
      </div>

      {/* ── Липкая кнопка: активна только когда есть что сохранять ── */}
      <div className="px-5 pt-3 pb-5 safe-bottom shrink-0 border-t border-hairline/60 chrome">
        {saveError && (
          <p className="mb-2 text-[13.5px] text-danger text-center">{saveError}</p>
        )}
        {dirty && ошибка && (
          <p className="mb-2 text-[13.5px] text-danger text-center">{ошибка}</p>
        )}
        <Button
          size="lg"
          fullWidth
          onClick={save}
          disabled={!dirty || !!ошибка || saving || uploading}
          hapticKind="success"
        >
          {saving ? (
            <Spinner size={20} />
          ) : uploading ? (
            "Фото загружается…"
          ) : (
            "Сохранить"
          )}
        </Button>
      </div>
    </div>
  );
}

function Section({
  id,
  title,
  hint,
  highlight,
  children,
}: {
  id: string;
  title: string;
  hint?: string;
  highlight?: boolean;
  children: React.ReactNode;
}) {
  return (
    <section
      id={`edit-${id}`}
      data-highlight={highlight || undefined}
      className={`mb-7 rounded-[var(--radius-tile)] transition-shadow duration-500 ${
        highlight ? "ring-2 ring-accent ring-offset-4 ring-offset-bg" : ""
      }`}
    >
      <p className="text-caption text-text-muted mb-2">{title}</p>
      {children}
      {hint && <p className="mt-2 text-caption text-text-faint">{hint}</p>}
    </section>
  );
}
