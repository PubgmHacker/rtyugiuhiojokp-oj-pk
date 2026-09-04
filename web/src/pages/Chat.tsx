import {
  useState,
  useEffect,
  useLayoutEffect,
  useRef,
  useCallback,
  useMemo,
} from "react";
import { useParams, useNavigate, useLocation } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { askConfirm } from "../lib/telegram";
import { letterAvatarStyle } from "../lib/aura";
import {
  ArrowLeft,
  Send,
  MoreVertical,
  Paperclip,
  Palette,
  ListChecks,
  Sparkles,
  Flag,
  Ban,
  UserX,
  Check,
  CheckCheck,
  Lock,
  WifiOff,
  Heart,
  Mic,
  Video,
  ChevronDown,
} from "lucide-react";
import {
  getMessages,
  getMatches,
  getIcebreakers,
  getChatTheme,
  getDailyLimits,
  reportUser,
  blockUser,
  unmatch,
  uploadVoice,
  uploadVideoNote,
  putReaction,
  type ChatMessage,
  type ChatTheme,
  type MessageQuote,
  type MessageReaction,
  type DailyLimits,
  type MatchResponse,
} from "../lib/api";
import { ChatWebSocket, type ConnectionStatus } from "../lib/websocket";
import { useStore } from "../lib/store";
import { haptic } from "../lib/haptics";
import { useIsMounted } from "../hooks/useSafeAsync";
import { Button, IdentityBadge, Skeleton, Spinner } from "../components/ui";
import ReelBubble from "../components/ReelBubble";
import VoiceBubble from "../components/VoiceBubble";
import VideoNoteBubble from "../components/VideoNoteBubble";
import NoteRecorder, { type NoteControls } from "../components/NoteRecorder";
import {
  readPreferredKind,
  recordingSupported,
  savePreferredKind,
  type NoteKind,
  type Recording,
} from "../lib/recorder";
import { ChatThemeSheet } from "../components/ChatThemeSheet";
import { HabitsSheet } from "../components/HabitsSheet";
import { AttachmentsSheet } from "../components/AttachmentsSheet";
import ProfileSheet from "../components/ProfileSheet";
import MessageRow from "../components/MessageRow";
import MessageActions, { type Действие } from "../components/MessageActions";
import { QuoteBlock, ReplyStrip } from "../components/MessageQuote";
import { когдаСлот } from "../components/LimitSheet";
import {
  useЯзык,
  перевести,
  форматВремени,
  форматДняРазделителя,
  type Язык,
} from "../lib/i18n";
import { REPORT_REASONS } from "../lib/profileOptions";
import { readableOn } from "../lib/aura";
import { useChatWallpaper } from "../lib/chatWallpaper";

// Порция истории — столько же, сколько сервер отдаёт по умолчанию.
const ПОРЦИЯ = 50;

/**
 * Одна общая кнопка справа: тап меняет микрофон на камеру, удержание пишет.
 * ДЕРЖУ_МС — граница между тапом и удержанием: ниже 200 мс обычный тап уже
 * успевает поднять микрофон, выше 300 мс удержание кажется залипшим.
 * ЗАКРЕПИТЬ_PX — подъём пальца, ОТМЕНА_PX — уход влево, как в Telegram.
 */
const ДЕРЖУ_МС = 240;
const ЗАКРЕПИТЬ_PX = 44;
const ОТМЕНА_PX = 64;

interface Удержание {
  id: number;
  x: number;
  y: number;
  начали: boolean;
  закрепили: boolean;
  сорвали: boolean;
  таймер: number;
}

export default function Chat() {
  const { matchId } = useParams<{ matchId: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const { token } = useStore();

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [match, setMatch] = useState<MatchResponse | null>(null);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(true);
  const [историяНеЗагрузилась, setИсторияНеЗагрузилась] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [attachOpen, setAttachOpen] = useState(false);
  const [partnerTyping, setPartnerTyping] = useState(false);
  const [icebreakers, setIcebreakers] = useState<string[]>([]);
  const [loadingIce, setLoadingIce] = useState(false);
  const [status, setStatus] = useState<ConnectionStatus>("connecting");
  const [sendError, setSendError] = useState(false);
  // Сбои жалобы/блокировки/размэтча: раньше catch глотал их молча (одна
  // вибрация), и человек был уверен, что жалоба ушла
  const [actionError, setActionError] = useState("");
  const [theme, setTheme] = useState<ChatTheme | null>(null);
  const [themeOpen, setThemeOpen] = useState(false);
  //: Обои переписки: мягкий градиент из пятен плюс узор, выведенные из
  //: цвета темы пары или, если своей темы нет, из палитры схемы.
  const обоиЧата = useChatWallpaper(theme?.background_color, theme?.pattern_key);
  const [habitsOpen, setHabitsOpen] = useState(false);
  // Профиль собеседника по тапу на шапку: из чата анкету было не открыть
  // вообще (аудит, блок «Продукт»)
  const [profileOpen, setProfileOpen] = useState(false);
  // Мэтч за суточным лимитом бесплатного уровня. Сервер закрывает и историю
  // (429), и сокет (код 4029) — тогда открывать переписку нечем, и вместо
  // пустой ленты с «нет связи» показываем причину
  const [лимитМэтчей, setЛимитМэтчей] = useState(false);
  const [limits, setLimits] = useState<DailyLimits | null>(null);
  // Голосовое / видеокружок: пока идёт запись, панель стоит на месте поля
  // ввода; пока файл едет на сервер — кнопки панели заперты
  const [recording, setRecording] = useState<NoteKind | null>(null);
  const [sendingNote, setSendingNote] = useState(false);
  const [noteError, setNoteError] = useState("");
  const canRecord = useMemo(() => recordingSupported(), []);
  // Режим общей кнопки — тот же, каким её оставили в прошлый раз
  const [noteKind, setNoteKind] = useState<NoteKind>(() => readPreferredKind());
  // Палец убрали, а запись идёт: у панели появляется корзина, у кнопки — «Отправить»
  const [noteLocked, setNoteLocked] = useState(true);
  const [noteReady, setNoteReady] = useState(false);
  const noteCtl = useRef<NoteControls | null>(null);
  const удержание = useRef<Удержание | null>(null);
  // Отпускание пальца рождает click: он не должен отправить запись второй раз
  const неКликПослеЖеста = useRef(0);
  // Ответ: держим само сообщение, а не id — полосе над полем нужны кадр
  // кружка и подпись, а искать их заново в ленте пришлось бы уже после
  // того, как сообщение уехало из окна.
  const [replyTo, setReplyTo] = useState<ChatMessage | null>(null);
  // Панель долгого нажатия: вместе с сообщением держим прямоугольник пузыря —
  // панель встаёт вплотную к нему, а не «где-то по центру экрана».
  const [menuFor, setMenuFor] = useState<{ msg: ChatMessage; rect: DOMRect } | null>(null);
  // Прыжок по цитате без подсветки читается как случайная прокрутка
  const [подсвечено, setПодсвечено] = useState<string | null>(null);
  const [тост, setТост] = useState("");

  // Сколько новых сообщений пришло, пока человек читал переписку выше
  const [новых, setНовых] = useState(0);
  // Ушёл далеко вверх — показываем кнопку возврата, как в мессенджерах
  const [далеко, setДалеко] = useState(false);
  // Прокрутка назад по истории. Клиент всегда держал только последнюю
  // страницу: переписка не листалась вообще, а прыжок к цитате или к
  // вложению старше пятидесяти сообщений упирался в тупик.
  const [подгрузка, setПодгрузка] = useState(false);
  const [историяКончилась, setИсторияКончилась] = useState(false);
  // Лента стоит на куске из середины переписки (прыжок к вложению или к
  // цитате): «вниз» тогда значит «вернуться к свежим», а не «прокрутить».
  const [вКонтексте, setВКонтексте] = useState(false);

  const wsRef = useRef<ChatWebSocket | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const лентаRef = useRef<HTMLDivElement>(null);
  // Человек у нижнего края (или в 120 px от него) — тогда лента едет за
  // новыми сообщениями сама; выше — не едет, иначе чтение старого куска
  // прерывается на каждом «привет»
  const прижат = useRef(true);
  const былоСообщений = useRef(0);
  // Долив старых сообщений сверху удлиняет массив так же, как приход нового
  // снизу. Без этой метки эффект автопрокрутки принимает долив за приход и
  // либо уезжает вниз, либо врёт значком «+50 новых».
  const историяПодгружена = useRef(false);
  // Высота ленты до долива: после вставки сверху прокрутку надо вернуть на
  // место, иначе кусок, который человек читал, уедет вниз за край экрана.
  const восстановитьПрокрутку = useRef<number | null>(null);
  // Запрос истории идёт — второй не нужен. Реф, а не состояние: обработчик
  // прокрутки создан один раз и состояние в нём было бы вечно устаревшим.
  const идётПодгрузка = useRef(false);
  // Первое сообщение в ленте нужно обработчику прокрутки как курсор, а
  // пересобирать обработчик на каждое сообщение — терять его в onScroll.
  const messagesRef = useRef<ChatMessage[]>(messages);
  messagesRef.current = messages;
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const typingTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastTypingSent = useRef(0);
  const тостТаймер = useRef<ReturnType<typeof setTimeout> | null>(null);
  const подсветкаТаймер = useRef<ReturnType<typeof setTimeout> | null>(null);

  const myId = useStore((s) => s.user?.id);
  const язык = useЯзык();
  const isMounted = useIsMounted();
  // Живой matchId на каждый рендер: замыкание эффекта хранит свой matchId
  // навсегда, а этот реф нужен именно для сравнения "а актуален ли ещё тот
  // запрос", когда параметр маршрута уже успел смениться.
  const currentMatchIdRef = useRef(matchId);
  currentMatchIdRef.current = matchId;

  /* ── Загрузка истории и сокет ────────────────────────────── */
  useEffect(() => {
    if (!matchId) return;

    // matchId меняется без размонтирования компонента (переход между
    // чатами по маршруту): если старый запрос ответит позже, чем эффект
    // перезапустится на новом matchId, его результат нельзя применять —
    // иначе он затрёт уже открытую переписку данными чужого матча.
    const requestedMatchId = matchId;
    // Матч меняется без размонтирования: страницы истории прошлой переписки
    // не должны считаться загруженными, а её курсор — действующим
    setИсторияКончилась(false);
    setВКонтексте(false);
    идётПодгрузка.current = false;
    восстановитьПрокрутку.current = null;
    const stillCurrent = () =>
      isMounted() && requestedMatchId === currentMatchIdRef.current;

    (async () => {
      try {
        const [msgs, matchList] = await Promise.all([
          getMessages(requestedMatchId),
          getMatches(),
        ]);
        if (!stillCurrent()) return;
        // История может прийти позже сокета — мержим без дублей
        setMessages((prev) => {
          const seen = new Set(msgs.map((m) => m.id));
          return [...msgs, ...prev.filter((m) => !seen.has(m.id))];
        });
        setMatch(matchList.find((m) => m.id === requestedMatchId) ?? null);
        // Страница короче порции — переписка целиком в ленте, и просить у
        // сервера предыдущую при прокрутке вверх незачем
        if (msgs.length < ПОРЦИЯ) setИсторияКончилась(true);
      } catch (e: any) {
        if (!stillCurrent()) return;
        if (e?.response?.status === 429) {
          // Суточный лимит открытых мэтчей: это не сбой, а закрытая дверь.
          // Подтягиваем время возврата слота, чтобы не обещать «завтра»
          setЛимитМэтчей(true);
          getDailyLimits()
            .then((l) => {
              if (stillCurrent()) setLimits(l);
            })
            .catch(() => {});
        } else {
          // Сбой и «переписки ещё нет» выглядели одинаково: человек видел
          // приглашение написать первым, хотя история просто не загрузилась
          setИсторияНеЗагрузилась(true);
        }
      } finally {
        if (stillCurrent()) setLoading(false);
      }
    })();

    if (!token) return;

    const ws = new ChatWebSocket(matchId, token);
    wsRef.current = ws;

    const offStatus = ws.onStatusChange(setStatus);

    const offMessage = ws.onMessage((data: any) => {
      if (data.type === "message") {
        setMessages((prev) =>
          prev.some((m) => m.id === data.id) ? prev : [...prev, data]
        );
        setPartnerTyping(false);
        if (data.sender_id !== useStore.getState().user?.id) {
          haptic("light");
          ws.sendRaw({ type: "read" });
        }
      } else if (data.type === "typing") {
        // Событие из своей второй вкладки игнорируем
        if (data.user_id === useStore.getState().user?.id) return;
        setPartnerTyping(true);
        if (typingTimer.current) clearTimeout(typingTimer.current);
        typingTimer.current = setTimeout(() => setPartnerTyping(false), 3000);
      } else if (data.type === "rejected") {
        // Сервер не принял сообщение — медиа чужое, антифлуд или модерация.
        // Раньше отказ читался только в логах: текст исчезал, а человек был
        // уверен, что оно ушло
        setNoteError(
          typeof data.reason === "string" && data.reason
            ? data.reason
            : "Сообщение не принято"
        );
        haptic("error");
      } else if (data.type === "reaction") {
        // Кадр приходит обоим — включая того, кто нажал: так две вкладки
        // одного человека не разъезжаются, а оптимистичная догадка просто
        // подтверждается тем же списком авторов.
        setMessages((prev) =>
          prev.map((m) =>
            m.id === data.message_id ? { ...m, reactions: data.reactions } : m
          )
        );
      } else if (data.type === "read") {
        const now = new Date().toISOString();
        const me = useStore.getState().user?.id;
        setMessages((prev) =>
          prev.map((m) =>
            m.read_at || m.sender_id !== me ? m : { ...m, read_at: now }
          )
        );
      }
    });

    // При открытии чата отмечаем входящие прочитанными
    const offOpen = ws.onOpen(() => ws.sendRaw({ type: "read" }));

    // Сокет тоже упирается в суточный лимит — и закрывается кодом 4029.
    // Без этой ветки экран показывал бы «нет связи»: сообщение о лимите
    // приходит только кодом закрытия, тела у него нет
    const offFatal = ws.onFatalClose((info) => {
      if (!stillCurrent() || info.code !== 4029) return;
      setЛимитМэтчей(true);
      getDailyLimits()
        .then((l) => {
          if (stillCurrent()) setLimits(l);
        })
        .catch(() => {});
    });

    ws.connect();

    return () => {
      offStatus();
      offMessage();
      offOpen();
      offFatal();
      ws.close();
      wsRef.current = null;
      if (typingTimer.current) clearTimeout(typingTimer.current);
    };
  }, [matchId, token]);

  // Лента едет вниз не на любое изменение массива: реакция, галочка
  // «прочитано» и правка сообщения меняют его же, и прыжок к низу на
  // реакцию по вчерашнему сообщению — то, за что мессенджеры ругают.
  // Едем на: первую загрузку, своё сообщение, чужое при чтении у низа.
  useEffect(() => {
    const стало = messages.length;
    const было = былоСообщений.current;
    былоСообщений.current = стало;
    // Долив истории сверху или страница из середины: последнее сообщение
    // то же самое, ехать некуда и «новых» не прибавилось
    if (историяПодгружена.current) {
      историяПодгружена.current = false;
      return;
    }
    if (стало === 0) return;

    if (было === 0) {
      bottomRef.current?.scrollIntoView({ block: "end" });
      setНовых(0);
      return;
    }
    if (стало <= было) return; // реакция/прочтение — лента стоит

    const моё = messages[стало - 1]?.sender_id === myId;
    if (моё || прижат.current) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
      setНовых(0);
    } else {
      setНовых((n) => n + (стало - было));
    }
  }, [messages, myId]);

  // «Печатает…» подрастает снизу и заслоняет последнее сообщение — но
  // только если человек и так внизу
  useEffect(() => {
    if (partnerTyping && прижат.current) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    }
  }, [partnerTyping]);

  // Прокрутку возвращаем до кадра: в useEffect прочитанный кусок успевает
  // мигнуть вниз и вернуться — это видно глазом.
  useLayoutEffect(() => {
    const было = восстановитьПрокрутку.current;
    if (было === null) return;
    восстановитьПрокрутку.current = null;
    const el = лентаRef.current;
    if (!el) return;
    el.scrollTop += el.scrollHeight - было;
  }, [messages]);

  const показатьТост = useCallback((текст: string) => {
    setТост(текст);
    if (тостТаймер.current) clearTimeout(тостТаймер.current);
    тостТаймер.current = setTimeout(() => setТост(""), 1800);
  }, []);

  // Долив старой истории. Курсор — время самого раннего загруженного
  // сообщения, а не offset: пока человек читает верх, снизу приходят новые,
  // окно по offset сдвигается и отдаёт ту же страницу второй раз.
  const подгрузитьСтарые = useCallback(async () => {
    const матч = currentMatchIdRef.current;
    if (!матч || идётПодгрузка.current || историяКончилась) return;
    const самое = messagesRef.current[0];
    if (!самое?.created_at) return;
    const el = лентаRef.current;
    идётПодгрузка.current = true;
    setПодгрузка(true);
    try {
      const порция = await getMessages(матч, {
        before: самое.created_at,
        limit: ПОРЦИЯ,
      });
      if (!isMounted() || матч !== currentMatchIdRef.current) return;
      // Короткая страница — значит начало переписки: больше не просим
      if (порция.length < ПОРЦИЯ) setИсторияКончилась(true);
      if (порция.length === 0) return;
      историяПодгружена.current = true;
      восстановитьПрокрутку.current = el ? el.scrollHeight : null;
      setMessages((prev) => {
        const есть = new Set(prev.map((m) => m.id));
        const новые = порция.filter((m) => !есть.has(m.id));
        return новые.length ? [...новые, ...prev] : prev;
      });
    } catch {
      // Молча: подгрузка фоновая, и плашка сети поверх переписки назойливее
      // самой пропажи. Верхний край остался — жест повторит запрос.
    } finally {
      if (isMounted()) setПодгрузка(false);
      идётПодгрузка.current = false;
    }
  }, [историяКончилась, isMounted]);

  // Возврат к концу переписки после прыжка в середину: ленту надо не
  // прокрутить, а перезагрузить — свежих сообщений в ней сейчас нет.
  const вернутьсяКСвежим = useCallback(async () => {
    const матч = currentMatchIdRef.current;
    if (!матч || идётПодгрузка.current) return;
    идётПодгрузка.current = true;
    setПодгрузка(true);
    try {
      const хвост = await getMessages(матч, { limit: ПОРЦИЯ });
      if (!isMounted() || матч !== currentMatchIdRef.current) return;
      историяПодгружена.current = true;
      восстановитьПрокрутку.current = null;
      setИсторияКончилась(false);
      setВКонтексте(false);
      прижат.current = true;
      setMessages(хвост);
      requestAnimationFrame(() =>
        bottomRef.current?.scrollIntoView({ block: "end" })
      );
    } catch {
      показатьТост("Не удалось вернуться к свежим сообщениям");
    } finally {
      if (isMounted()) setПодгрузка(false);
      идётПодгрузка.current = false;
    }
  }, [isMounted, показатьТост]);

  const кНовым = useCallback(() => {
    setНовых(0);
    прижат.current = true;
    // Лента держит кусок из прошлого — «вниз» должно вернуть к свежим
    // сообщениям, а не к концу этого куска
    if (вКонтексте) {
      void вернутьсяКСвежим();
      return;
    }
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [вКонтексте, вернутьсяКСвежим]);

  const лентаПрокручена = useCallback(() => {
    const el = лентаRef.current;
    if (!el) return;
    const хвост = el.scrollHeight - el.scrollTop - el.clientHeight;
    const внизу = хвост < 120;
    прижат.current = внизу;
    // «Далеко» считаем от НИЗА, а не от верха: кнопка возвращает к последним
    setДалеко(хвост > 280);
    if (внизу) setНовых(0);
    // Верхний край близко — доливаем предыдущую страницу заранее, чтобы
    // прокрутка не упиралась в пустоту и не ждала запроса
    if (el.scrollTop < 200) void подгрузитьСтарые();
  }, [подгрузитьСтарые]);

  /* ── Отправка ────────────────────────────────────────────── */
  // Тему тянем при входе и при возврате на вкладку: её мог поменять
  // партнёр, а отдельного канала для этого нет — сообщения ходят своим
  // сокетом, и вешать на него оформление значит связать два несвязанных.
  useEffect(() => {
    if (!matchId) return;
    let живо = true;
    const тянуть = () => {
      getChatTheme(matchId)
        .then((t) => живо && setTheme(t))
        .catch(() => {});
    };
    тянуть();
    const onFocus = () => document.visibilityState === "visible" && тянуть();
    document.addEventListener("visibilitychange", onFocus);
    window.addEventListener("focus", onFocus);
    return () => {
      живо = false;
      document.removeEventListener("visibilitychange", onFocus);
      window.removeEventListener("focus", onFocus);
    };
  }, [matchId]);

  // Ответ на историю приходит текстом в состоянии перехода: сама история
  // живёт сутки, а переписка остаётся, поэтому ответ — обычное сообщение.
  useEffect(() => {
    const prefill = (location.state as { prefill?: string } | null)?.prefill;
    if (prefill) {
      setInput(prefill);
      navigate(location.pathname, { replace: true, state: null });
    }
    // Разово при входе: state гасится тут же, и повторный проход стёр бы
    // текст, который человек уже начал править.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const send = useCallback(
    (override?: string) => {
      const text = (override ?? input).trim();
      if (!text || !wsRef.current) return;

      const sent = wsRef.current.send(text, undefined, undefined, replyTo?.id);
      if (!sent) {
        // Сокет мог отвалиться — текст не теряем
        if (override) setInput(override);
        setSendError(true);
        haptic("error");
        setTimeout(() => setSendError(false), 3000);
        return;
      }
      setInput("");
      setIcebreakers([]);
      setReplyTo(null);
      haptic("light");
      if (inputRef.current) inputRef.current.style.height = "auto";
    },
    [input, replyTo]
  );

  const onInputChange = useCallback((value: string) => {
    setInput(value);

    // Растущее поле: до пяти строк, дальше прокрутка
    const el = inputRef.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = `${Math.min(el.scrollHeight, 120)}px`;
    }

    const now = Date.now();
    if (now - lastTypingSent.current > 2000 && wsRef.current) {
      wsRef.current.sendRaw({ type: "typing" });
      lastTypingSent.current = now;
    }
  }, []);

  // Запись готова: грузим файл (видео — вместе с кадрами на модерацию) и
  // шлём сообщение тем же сокетом, что и текст. Текст пустой — сервер
  // подпишет превью сам («Голосовое сообщение» в списке чатов).
  const sendNote = useCallback(
    async (rec: Recording, shape: string, kind: NoteKind) => {
      if (!wsRef.current) return;
      setSendingNote(true);
      setNoteError("");
      try {
        const uploaded =
          kind === "voice"
            ? await uploadVoice(rec.blob, rec.duration)
            : await uploadVideoNote(rec.blob, rec.covers, rec.duration);
        const media: Record<string, unknown> = {
          url: uploaded.url,
          kind,
          duration: rec.duration,
        };
        if (kind === "voice") {
          media.waveform = rec.waveform;
        } else {
          media.shape = shape;
          const poster = (uploaded as { poster?: string | null }).poster;
          if (poster) media.poster = poster;
        }
        const sent = wsRef.current?.send("", undefined, media, replyTo?.id);
        if (!sent) {
          setNoteError("Запись не ушла — нет связи. Попробуйте ещё раз");
          haptic("error");
          return;
        }
        haptic("light");
        setRecording(null);
        setReplyTo(null);
      } catch (e: any) {
        haptic("error");
        const status = e?.response?.status;
        setNoteError(
          e?.response?.data?.detail ??
            (status === 503
              ? "Загрузка медиа сейчас недоступна"
              : status === 413
                ? "Запись слишком длинная"
                : "Не удалось отправить запись — попробуйте ещё раз")
        );
        setRecording(null);
      } finally {
        setSendingNote(false);
      }
    },
    [replyTo]
  );

  const startNote = useCallback((kind: NoteKind, держат = false) => {
    setNoteError("");
    setNoteReady(false);
    setNoteLocked(!держат);
    setRecording(kind);
    haptic("light");
  }, []);

  /* ── Общая кнопка записи: тап переключает, удержание пишет ──── */

  const переключитьРежим = () => {
    const другой: NoteKind = noteKind === "voice" ? "video_note" : "voice";
    setNoteKind(другой);
    savePreferredKind(другой);
    haptic("light");
    показатьТост(
      другой === "voice" ? "Голосовое · держите кнопку" : "Кружок · держите кнопку"
    );
  };

  const начатьУдержание = (e: React.PointerEvent<HTMLButtonElement>) => {
    if (recording || !canRecord || input.trim()) return;
    // Захват пальца: пока он не отпущен, события идут этой кнопке, даже если
    // палец сполз с неё на панель записи
    try {
      e.currentTarget.setPointerCapture(e.pointerId);
    } catch {
      /* мышь и старые движки живут без захвата */
    }
    const вид = noteKind;
    const жест: Удержание = {
      id: e.pointerId,
      x: e.clientX,
      y: e.clientY,
      начали: false,
      закрепили: false,
      сорвали: false,
      таймер: 0,
    };
    жест.таймер = window.setTimeout(() => {
      жест.таймер = 0;
      if (удержание.current !== жест) return;
      жест.начали = true;
      startNote(вид, true);
    }, ДЕРЖУ_МС);
    удержание.current = жест;
  };

  const вестиУдержание = (e: React.PointerEvent<HTMLButtonElement>) => {
    const жест = удержание.current;
    if (!жест || жест.id !== e.pointerId || !жест.начали || жест.сорвали) return;
    if (e.clientX - жест.x <= -ОТМЕНА_PX) {
      жест.сорвали = true;
      noteCtl.current?.cancel();
      haptic("light");
      показатьТост("Запись отменена");
      return;
    }
    if (!жест.закрепили && жест.y - e.clientY >= ЗАКРЕПИТЬ_PX) {
      жест.закрепили = true;
      неКликПослеЖеста.current = Date.now();
      setNoteLocked(true);
      haptic("medium");
    }
  };

  const отпуститьУдержание = (e: React.PointerEvent<HTMLButtonElement>) => {
    const жест = удержание.current;
    if (!жест || жест.id !== e.pointerId) return;
    if (жест.таймер) clearTimeout(жест.таймер);
    удержание.current = null;
    if (жест.сорвали || жест.закрепили) return;
    if (!жест.начали) {
      переключитьРежим();
      return;
    }
    неКликПослеЖеста.current = Date.now();
    const итог = noteCtl.current?.stop() ?? "cold";
    if (итог === "short") показатьТост("Коротко — держите кнопку");
    if (итог === "cold") {
      setNoteLocked(true);
      показатьТост("Ещё готовим — отправьте кнопкой");
    }
  };

  const перехватУдержания = (e: React.PointerEvent<HTMLButtonElement>) => {
    // Жест забрала система (в WebView это может быть её собственное меню).
    // Дубль не теряем: закрепляем запись, палец для неё больше не нужен.
    const жест = удержание.current;
    if (!жест || жест.id !== e.pointerId) return;
    if (жест.таймер) clearTimeout(жест.таймер);
    удержание.current = null;
    if (жест.сорвали || жест.закрепили || !жест.начали) return;
    неКликПослеЖеста.current = Date.now();
    setNoteLocked(true);
    показатьТост("Запись закреплена");
  };

  const наКлавишеЗаписи = (e: React.KeyboardEvent<HTMLButtonElement>) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    // С клавиатуры кнопку не подержишь — запись сразу закреплённая
    e.preventDefault();
    startNote(noteKind);
  };

  const отправитьЗапись = () => {
    if (Date.now() - неКликПослеЖеста.current < 500) return;
    noteCtl.current?.stop();
  };

  // Что сейчас за кнопка: набран текст → «Отправить», запись под пальцем →
  // курок, закреплённая запись → «Отправить запись», покой → микрофон/камера
  const правая: "text" | "note" | "hold" | "arm" = recording
    ? noteLocked
      ? "note"
      : "hold"
    : input.trim() || !canRecord
      ? "text"
      : "arm";
  // Обработчики жеста нужны в обоих его состояниях: посреди удержания кнопка
  // перерисовывается из «arm» в «hold», а палец с неё не уходит
  const жест = правая === "arm" || правая === "hold";

  useEffect(
    () => () => {
      const жест = удержание.current;
      if (жест?.таймер) clearTimeout(жест.таймер);
    },
    []
  );

  /* ── Ответы, реакции, панель действий ────────────────────── */

  useEffect(
    () => () => {
      if (тостТаймер.current) clearTimeout(тостТаймер.current);
      if (подсветкаТаймер.current) clearTimeout(подсветкаТаймер.current);
    },
    []
  );

  const ответить = useCallback((m: ChatMessage) => {
    setReplyTo(m);
    setMenuFor(null);
    haptic("light");
    inputRef.current?.focus();
  }, []);

  // Прыжок к процитированному и к вложению из витрины. Сообщения может не
  // быть на загруженной странице — тогда просим у сервера страницу вокруг
  // него и встаём на неё. Раньше здесь была отписка «осталось выше», и любое
  // фото старше пятидесяти сообщений было тупиком.
  const прыгнутьК = useCallback(
    async (id: string) => {
      const подсветить = (el: HTMLElement) => {
        el.scrollIntoView({ block: "center", behavior: "smooth" });
        setПодсвечено(id);
        if (подсветкаТаймер.current) clearTimeout(подсветкаТаймер.current);
        подсветкаТаймер.current = setTimeout(() => setПодсвечено(null), 1500);
      };

      const рядом = document.getElementById(`msg-${id}`);
      if (рядом) {
        подсветить(рядом);
        return;
      }

      const матч = currentMatchIdRef.current;
      if (!матч || идётПодгрузка.current) return;
      идётПодгрузка.current = true;
      setПодгрузка(true);
      try {
        const страница = await getMessages(матч, { around: id, limit: ПОРЦИЯ * 2 });
        if (!isMounted() || матч !== currentMatchIdRef.current) return;
        if (страница.length === 0) {
          показатьТост("Сообщение не найдено в переписке");
          return;
        }
        // Страница из середины заменяет ленту целиком: склеить её с хвостом
        // нельзя — между ними дыра, и разделители дней соврут о порядке.
        историяПодгружена.current = true;
        восстановитьПрокрутку.current = null;
        setИсторияКончилась(false);
        setВКонтексте(true);
        прижат.current = false;
        setMessages(страница);
        // Два кадра: первый отдаёт React новую страницу в DOM, второй ждёт
        // раскладку — иначе прыжок уходит по старым координатам.
        requestAnimationFrame(() =>
          requestAnimationFrame(() => {
            const el = document.getElementById(`msg-${id}`);
            if (el) подсветить(el);
          })
        );
      } catch {
        показатьТост("Не удалось открыть это место переписки");
      } finally {
        if (isMounted()) setПодгрузка(false);
        идётПодгрузка.current = false;
      }
    },
    [isMounted, показатьТост]
  );

  // Реакция встаёт сразу, не дожидаясь сервера: сетевая пауза на нажатии по
  // своему же сообщению читается как «не нажалось». Сокет закрыт — тот же
  // код уходит по REST, и ответ сервера всё равно перекрывает догадку.
  const переключитьРеакцию = useCallback(
    (msg: ChatMessage, key: string) => {
      const me = myId;
      if (!me) return;
      haptic("light");
      setMenuFor(null);
      setMessages((prev) =>
        prev.map((m) =>
          m.id === msg.id ? { ...m, reactions: свестиРеакции(m.reactions, key, me) } : m
        )
      );
      if (wsRef.current?.sendReaction(msg.id, key)) return;
      if (!matchId) return;
      putReaction(matchId, msg.id, key)
        .then((r) =>
          setMessages((prev) =>
            prev.map((m) => (m.id === msg.id ? { ...m, reactions: r.reactions } : m))
          )
        )
        .catch(() => {
          setNoteError("Реакция не ушла — нет связи");
          haptic("error");
        });
    },
    [myId, matchId]
  );

  const открытьМеню = useCallback((msg: ChatMessage, rect: DOMRect) => {
    setMenuFor({ msg, rect });
  }, []);

  // Имя над цитатой. Сервер имён в цитате не шлёт намеренно — в личке двое,
  // и оба известны клиенту по sender_id.
  const авторЦитаты = useCallback(
    (id: string) =>
      id === myId ? "Вы" : match?.partner.display_name || "Собеседник",
    [myId, match]
  );

  const действия = useMemo<Действие[]>(() => {
    const m = menuFor?.msg;
    if (!m) return [];
    const список: Действие[] = [
      { key: "reply", label: "Ответить", icon: "reply", onPick: () => ответить(m) },
    ];
    // Кружок в ответ на голосовое или кружок: разговор голосом не должен
    // обрываться о клавиатуру — камера открывается сразу, с цитатой.
    if (m.media && canRecord) {
      список.push({
        key: "note",
        label: "Ответить кружком",
        icon: "note",
        onPick: () => {
          setReplyTo(m);
          setMenuFor(null);
          startNote("video_note");
        },
      });
    }
    if (m.text) {
      список.push({
        key: "copy",
        label: "Копировать",
        icon: "copy",
        onPick: () => {
          setMenuFor(null);
          navigator.clipboard
            ?.writeText(m.text)
            .then(() => показатьТост("Скопировано"))
            .catch(() => показатьТост("Не удалось скопировать"));
        },
      });
    }
    return список;
  }, [menuFor, ответить, startNote, показатьТост, canRecord]);

  // Моя реакция берётся из живой ленты, а не из снимка в menuFor: пока панель
  // открыта, кадр от собеседника мог поменять список.
  const менюАктив = useMemo(() => {
    if (!menuFor || !myId) return null;
    const живое = messages.find((x) => x.id === menuFor.msg.id) ?? menuFor.msg;
    return живое.reactions?.find((r) => r.users.includes(myId))?.key ?? null;
  }, [menuFor, messages, myId]);

  const loadIcebreakers = useCallback(async () => {
    if (!matchId || loadingIce) return;
    setLoadingIce(true);
    haptic("light");
    try {
      setIcebreakers(await getIcebreakers(matchId));
    } catch {
      /* подсказки необязательны */
    } finally {
      setLoadingIce(false);
    }
  }, [matchId, loadingIce]);

  // Причину выбирает человек: раньше любая жалоба уходила как «other», и
  // модератор не понимал, на что смотреть в первую очередь
  const [reportOpen, setReportOpen] = useState(false);

  const sendReport = useCallback(
    async (reason: string) => {
      if (!match) return;
      setReportOpen(false);
      try {
        await reportUser(match.partner.id, reason, "Жалоба из чата");
      } catch (e: any) {
        haptic("error");
        setActionError(
          e?.response?.data?.detail ??
            "Жалоба не отправлена — проверьте связь и попробуйте ещё раз"
        );
        return;
      }
      // Жалоба уже у модератора. Размэтч — вспомогательный шаг: его сбой
      // не должен читаться как «жалоба не ушла», мэтч можно разорвать руками.
      try {
        await unmatch(match.id);
      } catch {
        /* не маскируем принятую жалобу под ошибку */
      }
      haptic("success");
      navigate("/matches", { replace: true });
    },
    [match, navigate]
  );

  const handleBlock = useCallback(async () => {
    if (!match) return;
    const name = match.partner.display_name || "этого пользователя";
    const ok = await askConfirm(
      `Заблокировать ${name}?\n\nВы больше не увидите друг друга и не сможете связаться. Отменить можно в настройках профиля.`
    );
    if (!ok) return;
    try {
      await blockUser(match.partner.id);
      haptic("success");
      navigate("/matches", { replace: true });
    } catch (e: any) {
      haptic("error");
      setActionError(
        e?.response?.data?.detail ??
          "Не удалось заблокировать — попробуйте ещё раз"
      );
    }
  }, [match, navigate]);

  const handleUnmatch = useCallback(async () => {
    if (!match) return;
    if (!(await askConfirm("Разорвать мэтч? Чат исчезнет у обоих."))) return;
    try {
      await unmatch(match.id);
      haptic("medium");
      navigate("/matches", { replace: true });
    } catch (e: any) {
      haptic("error");
      setActionError(
        e?.response?.data?.detail ??
          "Не удалось разорвать мэтч — попробуйте ещё раз"
      );
    }
  }, [match, navigate]);

  /* ── Группировка сообщений ───────────────────────────────── */
  const groups = useMemo(() => groupMessages(messages, myId, язык), [messages, myId, язык]);

  const partnerName = match?.partner.display_name || "Чат";
  const partnerPhoto = match?.partner.photos?.[0];

  /* ── Мэтч закрыт суточным лимитом ────────────────────────── */
  // Отдельным экраном, а не шторкой поверх чата: под шторкой всё равно
  // пусто — ни истории, ни сокета сервер не даст, — и закрыв её человек
  // остался бы на мёртвой странице. Здесь единственный выход осмысленный:
  // подписка или назад к списку
  if (лимитМэтчей) {
    return (
      <div className="flex flex-col h-screen-safe">
        <header className="chrome safe-top border-b border-hairline/70 shrink-0">
          <div className="flex items-center gap-2.5 px-3 pb-2.5 min-h-[52px]">
            <button
              aria-label="Назад"
              onClick={() => navigate(-1)}
              className="tap-target flex items-center justify-center text-text-secondary"
            >
              <ArrowLeft size={22} />
            </button>
            <span className="font-semibold text-[15px]">Мэтч закрыт</span>
          </div>
        </header>

        <div className="flex-1 flex flex-col items-center justify-center px-8 text-center">
          <span
            className="w-16 h-16 rounded-full bg-accent/12 flex items-center
                       justify-center mb-5"
          >
            <Lock size={26} className="text-accent" />
          </span>
          <h2 className="text-heading font-bold mb-2">Лимит мэтчей на сегодня</h2>
          <p className="text-[14px] leading-snug text-text-secondary mb-1.5">
            На бесплатном уровне открыто{" "}
            {limits && limits.matches_total > 0 ? limits.matches_total : 3} мэтча в
            сутки. Уже открытые переписки остаются доступны.
          </p>
          {limits?.matches_reset_at && (
            <p className="text-caption text-text-muted mb-6">
              Следующий слот вернётся {когдаСлот(limits.matches_reset_at, язык)}.
            </p>
          )}
          {!limits?.matches_reset_at && <div className="mb-6" />}

          <div className="flex flex-col gap-2.5 w-full max-w-[280px]">
            <Button
              size="lg"
              fullWidth
              onClick={() => {
                haptic("light");
                navigate("/plans");
              }}
            >
              Открыть без лимитов
            </Button>
            <Button
              variant="secondary"
              size="lg"
              fullWidth
              onClick={() => navigate("/matches")}
            >
              К списку чатов
            </Button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-screen-safe">
      {/* ── Заголовок ───────────────────────────────────────── */}
      <header className="chrome safe-top border-b border-hairline/70 shrink-0 z-20">
        <div className="flex items-center gap-2.5 px-3 pb-2.5 min-h-[52px]">
          <button
            aria-label="Назад"
            onClick={() => navigate(-1)}
            className="tap-target flex items-center justify-center text-text-secondary"
          >
            <ArrowLeft size={22} />
          </button>

          {/* Аватар и имя открывают полный профиль собеседника. Две соседние
              кнопки, а не одна обёртка: внутри блока живёт ссылка канала,
              и интерактив внутри интерактива — ломаный HTML */}
          <button
            aria-label={`Профиль ${partnerName}`}
            disabled={!match}
            onClick={() => {
              haptic("light");
              setProfileOpen(true);
            }}
            className="w-9 h-9 rounded-full overflow-hidden bg-surface-2 shrink-0"
          >
            {partnerPhoto ? (
              <img src={partnerPhoto} alt="" className="w-full h-full object-cover" />
            ) : (
              <span
                className="w-full h-full flex items-center justify-center text-[14px] font-bold"
                style={letterAvatarStyle(match?.partner.id)}
              >
                {partnerName[0]?.toUpperCase()}
              </span>
            )}
          </button>

          <div className="flex-1 min-w-0">
            <button
              disabled={!match}
              onClick={() => {
                haptic("light");
                setProfileOpen(true);
              }}
              className="flex items-center gap-1.5 min-w-0 max-w-full text-left"
            >
              <span className="font-semibold text-[15px] truncate">{partnerName}</span>
              {match?.partner && <IdentityBadge profile={match.partner} size={14} />}
            </button>
            {/* Канал показывает сервер только если у собеседника открыта эта
                фича по тарифу — здесь просто собираем ссылку из username */}
            {match?.partner.tg_channel ? (
              <a
                href={`https://t.me/${match.partner.tg_channel}`}
                target="_blank"
                rel="noopener noreferrer"
                onClick={(e) => e.stopPropagation()}
                className="text-[11.5px] text-accent truncate block hover:underline"
              >
                @{match.partner.tg_channel}
              </a>
            ) : (
            <p className="text-[11.5px] text-text-muted truncate">
              {partnerTyping
                ? "печатает…"
                : status === "open"
                  ? "в сети"
                  : status === "connecting"
                    ? "подключение…"
                    : "нет связи"}
            </p>
            )}
          </div>


          <button
            aria-label="Задачи на день"
            onClick={() => {
              haptic("light");
              setHabitsOpen(true);
            }}
            className="tap-target flex items-center justify-center text-text-secondary"
          >
            <ListChecks size={20} />
          </button>

          <button
            aria-label="Тема переписки"
            onClick={() => {
              haptic("light");
              setThemeOpen(true);
            }}
            className="tap-target flex items-center justify-center text-text-secondary"
          >
            <Palette size={20} />
          </button>

          <div className="relative">
            <button
              aria-label="Действия"
              onClick={() => setMenuOpen((v) => !v)}
              className="tap-target flex items-center justify-center text-text-secondary"
            >
              <MoreVertical size={20} />
            </button>

            <AnimatePresence>
              {menuOpen && (
                <>
                  <div className="fixed inset-0 z-30" onClick={() => setMenuOpen(false)} />
                  <motion.div
                    initial={{ opacity: 0, scale: 0.94, y: -6 }}
                    animate={{ opacity: 1, scale: 1, y: 0 }}
                    exit={{ opacity: 0, scale: 0.96 }}
                    transition={{ type: "spring", stiffness: 420, damping: 30 }}
                    className="absolute right-0 top-11 z-40 w-56 rounded-[var(--radius-tile)]
                               bg-bg-elevated border border-hairline float-shadow overflow-hidden"
                  >
                    <button
                      onClick={() => {
                        setMenuOpen(false);
                        setAttachOpen(true);
                      }}
                      className="w-full flex items-center gap-2.5 px-4 py-3 text-left
                                 text-[14.5px] active:bg-surface transition-colors"
                    >
                      <Paperclip size={16} className="text-text-secondary" />
                      Вложения
                    </button>
                    <button
                      onClick={() => {
                        setMenuOpen(false);
                        setReportOpen(true);
                      }}
                      className="w-full flex items-center gap-2.5 px-4 py-3 text-left
                                 text-[14.5px] border-t border-hairline
                                 active:bg-surface transition-colors"
                    >
                      <Flag size={16} className="text-warn" />
                      Пожаловаться
                    </button>
                    <button
                      onClick={() => {
                        setMenuOpen(false);
                        handleBlock();
                      }}
                      className="w-full flex items-center gap-2.5 px-4 py-3 text-left
                                 text-[14.5px] border-t border-hairline
                                 active:bg-surface transition-colors"
                    >
                      <Ban size={16} className="text-danger" />
                      Заблокировать
                    </button>
                    <button
                      onClick={() => {
                        setMenuOpen(false);
                        handleUnmatch();
                      }}
                      className="w-full flex items-center gap-2.5 px-4 py-3 text-left
                                 text-[14.5px] text-danger border-t border-hairline
                                 active:bg-surface transition-colors"
                    >
                      <UserX size={16} />
                      Разорвать мэтч
                    </button>
                  </motion.div>
                </>
              )}
            </AnimatePresence>
          </div>
        </div>

        {status !== "open" && !loading && (
          <div className="px-4 pb-2">
            <p role="status" aria-live="polite" className="text-[12px] text-warn text-center">
              {status === "connecting" ? "Переподключение…" : "Нет связи с чатом"}
            </p>
          </div>
        )}
      </header>

      {/* ── Лента сообщений ─────────────────────────────────── */}
      <div
        ref={лентаRef}
        onScroll={лентаПрокручена}
        role="log"
        aria-live="polite"
        aria-relevant="additions"
        aria-label="Переписка"
        className="chat-surface flex flex-col flex-1 min-h-0 overflow-y-auto
                   overscroll-contain no-scrollbar px-3 py-3"
        style={{
          ...обоиЧата,
          ["--chat-ink" as any]: theme?.background_color
            ? readableOn(theme.background_color)
            : undefined,
          ["--chat-accent" as any]: theme?.bubble_mine_color || undefined,
        }}
      >
        {loading ? (
          <div className="flex flex-col gap-3">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton
                key={i}
                className={`h-11 ${i % 2 ? "w-2/3 ml-auto" : "w-1/2"} rounded-[18px]`}
              />
            ))}
          </div>
        ) : messages.length === 0 && историяНеЗагрузилась ? (
          <div className="h-full flex flex-col items-center justify-center text-center px-6">
            <div className="empty-glyph mb-4" aria-hidden="true">
              <WifiOff size={30} strokeWidth={1.6} />
            </div>
            <p className="text-[15px] font-semibold mb-1">Не удалось загрузить переписку</p>
            <p className="text-[13.5px] text-text-muted mb-6 max-w-[32ch]">
              Сообщения на месте — не хватило связи. Проверьте соединение.
            </p>
            <Button variant="secondary" size="md" onClick={() => window.location.reload()}>
              Повторить
            </Button>
          </div>
        ) : messages.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center px-6">
            <div className="empty-glyph mb-4" aria-hidden="true">
              <Heart size={30} strokeWidth={1.6} />
            </div>
            <p className="text-[15px] font-semibold mb-1">Вы понравились друг другу</p>
            <p className="text-[13.5px] text-text-muted mb-6 max-w-[32ch]">
              Первое сообщение решает многое. Можно начать с подсказки.
            </p>

            {icebreakers.length > 0 ? (
              <div className="flex flex-col gap-2 w-full max-w-[320px]">
                {icebreakers.map((text) => (
                  <button
                    key={text}
                    onClick={() => send(text)}
                    className="px-4 py-3 rounded-[var(--radius-tile)] bg-surface
                               border border-hairline text-[14px] text-left
                               active:bg-surface-2 transition-colors"
                  >
                    {text}
                  </button>
                ))}
              </div>
            ) : (
              <button
                onClick={loadIcebreakers}
                disabled={loadingIce}
                className="inline-flex items-center gap-2 px-4 h-11 rounded-full
                           bg-surface border border-hairline text-[14px]
                           disabled:opacity-50"
              >
                {loadingIce ? (
                  <Spinner size={16} />
                ) : (
                  <Sparkles size={15} className="text-accent" />
                )}
                Подсказать фразу
              </button>
            )}
          </div>
        ) : (
          <>
            {/* Распорка съедает пустоту сверху: три фразы в новой переписке
                должны лежать НА поле ввода, как в Telegram и VK, а не висеть
                под шапкой с провалом в пол-экрана. Растёт только на слабину,
                при переполнении сжимается в ноль и не мешает прокрутке */}
            <div className="flex-1 min-h-0 shrink" aria-hidden="true" />

            {/* Верх ленты: полоса ожидания, пока едет предыдущая страница.
                «Начало переписки» — только если человек действительно
                пролистал историю, иначе подпись висит над тремя фразами */}
            {подгрузка ? (
              <div className="flex justify-center py-3" aria-live="polite">
                <Spinner size={18} />
              </div>
            ) : историяКончилась && messages.length >= ПОРЦИЯ ? (
              <p className="text-center text-[12px] text-text-muted py-3">
                Начало переписки
              </p>
            ) : null}

            {groups.map((group) => {
              const last = group.messages[group.messages.length - 1];
              return (
                <div key={group.key}>
                  {group.dateLabel && (
                    <div className="flex justify-center my-4">
                      <span className="chat-divider">{group.dateLabel}</span>
                    </div>
                  )}

                  <div
                    className={`flex flex-col gap-0.5 mb-2.5 ${
                      group.mine ? "items-end" : "items-start"
                    }`}
                  >
                    {group.messages.map((m, i) => {
                      const isLast = i === group.messages.length - 1;
                      const время = formatTime(m.created_at, язык);
                      if (m.media?.kind === "video_note") {
                        // Кружок сам себе пузырь: подложка под звездой или
                        // ёлкой превратила бы форму в «картинку в рамке»
                        const цитата = m.reply_to;
                        return (
                          <MessageRow
                            key={m.id}
                            m={m}
                            mine={group.mine}
                            myId={myId}
                            подсвечено={подсвечено === m.id}
                            поднято={menuFor?.msg.id === m.id}
                            onReply={ответить}
                            onMenu={открытьМеню}
                            onToggleReaction={переключитьРеакцию}
                          >
                            <motion.div
                              initial={{ opacity: 0, scale: 0.92 }}
                              animate={{ opacity: 1, scale: 1 }}
                              transition={{ type: "spring", stiffness: 420, damping: 32 }}
                              className={`py-0.5 flex flex-col ${
                                group.mine ? "items-end" : "items-start"
                              }`}
                            >
                              {цитата && (
                                <div className="w-[200px] max-w-full -mb-0.5">
                                  <QuoteBlock
                                    quote={цитата}
                                    author={авторЦитаты(цитата.sender_id)}
                                    mine={false}
                                    onJump={() => прыгнутьК(цитата.id)}
                                  />
                                </div>
                              )}
                              {/* Время стоит рядом с формой, а не под ней: под
                                  звездой оно висело само по себе и читалось
                                  как подпись к следующему сообщению */}
                              <div
                                className={`flex items-end gap-1.5 ${
                                  group.mine ? "flex-row-reverse" : ""
                                }`}
                              >
                                <VideoNoteBubble media={m.media} mine={group.mine} />
                                <span className="pb-1.5">
                                  <МетаСообщения
                                    время={время}
                                    mine={group.mine}
                                    прочитано={!!m.read_at}
                                    наФоне
                                    цветФона={theme?.background_color}
                                  />
                                </span>
                              </div>
                            </motion.div>
                          </MessageRow>
                        );
                      }

                      // Время с галочками — внутри пузыря, как в мессенджерах.
                      // Снаружи оно отрывалось от сообщения и в группе стояло
                      // одно на всех. Пустая распорка в конце текста бронирует
                      // ему место в последней строке: иначе оно легло бы
                      // поверх слов, а перенос строки ради времени — расточительство.
                      const надМедиа = !m.text && !!(m.image_url || m.reel);
                      const распорка = group.mine ? 54 : 38;

                      return (
                        <MessageRow
                          key={m.id}
                          m={m}
                          mine={group.mine}
                          myId={myId}
                          подсвечено={подсвечено === m.id}
                          поднято={menuFor?.msg.id === m.id}
                          onReply={ответить}
                          onMenu={открытьМеню}
                          onToggleReaction={переключитьРеакцию}
                        >
                        <motion.div
                          initial={{ opacity: 0, y: 6 }}
                          animate={{ opacity: 1, y: 0 }}
                          transition={{ type: "spring", stiffness: 420, damping: 32 }}
                          className={`relative max-w-[78%] text-[15px] leading-snug
                                      break-words selectable ${
                                        m.media?.kind === "voice"
                                          ? "px-2 py-1.5"
                                          : "px-3.5 py-2"
                                      } ${
                                        theme?.bubble_mine_color ||
                                        theme?.bubble_theirs_color
                                          ? ""
                                          : group.mine
                                            ? "bg-accent text-white"
                                            : "bg-surface-2 text-text"
                                      }`}
                          style={{
                            borderRadius: 20,
                            borderBottomRightRadius: group.mine && isLast ? 6 : 20,
                            borderBottomLeftRadius: !group.mine && isLast ? 6 : 20,
                            // Тема задана — красим значением; нет — оставляем
                            // классы выше. Класс и style одновременно дали бы
                            // градиент под сплошным цветом, и на полупрозрачных
                            // цветах он проступал бы полосами.
                            background: group.mine
                              ? theme?.bubble_mine_color || undefined
                              : theme?.bubble_theirs_color || undefined,
                            color: group.mine
                              ? theme?.bubble_mine_color
                                ? readableOn(theme.bubble_mine_color)
                                : undefined
                              : theme?.bubble_theirs_color
                                ? readableOn(theme.bubble_theirs_color)
                                : undefined,
                          }}
                        >
                          {m.reply_to && (
                            <QuoteBlock
                              quote={m.reply_to}
                              author={авторЦитаты(m.reply_to.sender_id)}
                              mine={group.mine}
                              onJump={() => прыгнутьК(m.reply_to!.id)}
                            />
                          )}
                          {m.reel && <ReelBubble reel={m.reel} mine={group.mine} />}
                          {m.media?.kind === "voice" && (
                            <VoiceBubble media={m.media} mine={group.mine} />
                          )}
                          {m.image_url && (
                            <img
                              src={m.image_url}
                              alt=""
                              className="rounded-xl mb-1 max-w-full"
                            />
                          )}
                          {m.text}
                          {!!m.text && (
                            <span
                              aria-hidden="true"
                              className="inline-block h-0 align-baseline"
                              style={{ width: распорка }}
                            />
                          )}
                          <span
                            className={`absolute pointer-events-none ${
                              надМедиа
                                ? "px-1.5 py-[2px] rounded-full text-white"
                                : ""
                            }`}
                            style={
                              надМедиа
                                ? {
                                    right: 12,
                                    bottom: 10,
                                    background: "rgba(0,0,0,0.45)",
                                    backdropFilter: "blur(6px)",
                                    WebkitBackdropFilter: "blur(6px)",
                                  }
                                : { right: 12, bottom: 5 }
                            }
                          >
                            <МетаСообщения
                              время={время}
                              mine={group.mine}
                              прочитано={!!m.read_at}
                              светлая={надМедиа}
                            />
                          </span>
                        </motion.div>
                        </MessageRow>
                      );
                    })}
                  </div>
                </div>
              );
            })}

            <AnimatePresence>
              {partnerTyping && (
                <motion.div
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                  className="flex gap-1 px-3.5 py-3 rounded-[20px] bg-surface-2 w-fit"
                >
                  {[0, 1, 2].map((i) => (
                    <motion.span
                      key={i}
                      className="w-1.5 h-1.5 rounded-full bg-text-muted"
                      animate={{ opacity: [0.3, 1, 0.3], y: [0, -3, 0] }}
                      transition={{ duration: 1.1, repeat: Infinity, delay: i * 0.16 }}
                    />
                  ))}
                </motion.div>
              )}
            </AnimatePresence>
          </>
        )}

        <div ref={bottomRef} />
      </div>

      {/* ── Поле ввода ──────────────────────────────────────── */}
      <div className="relative shrink-0 chrome border-t border-hairline/70 px-3 pt-2.5 pb-2 safe-bottom">
        {/* Возврат к последним сообщениям: висит над полем, как в Telegram,
            и носит счётчик пропущенного, чтобы не гадать, стоит ли ехать */}
        <AnimatePresence>
          {(далеко || новых > 0 || вКонтексте) && (
            <motion.button
              type="button"
              initial={{ opacity: 0, scale: 0.7, y: 8 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.7, y: 8 }}
              transition={{ type: "spring", stiffness: 520, damping: 30 }}
              onClick={кНовым}
              aria-label={
                новых > 0
                  ? `К новым сообщениям, ${новых}`
                  : вКонтексте
                    ? "Вернуться к свежим сообщениям"
                    : "К последним сообщениям"
              }
              className="absolute right-3 -top-[54px] w-11 h-11 rounded-full liquid
                         flex items-center justify-center text-text-secondary
                         float-shadow active:scale-95 transition-transform"
            >
              <ChevronDown size={20} />
              {новых > 0 && (
                <span
                  className="absolute -top-1 -right-1 min-w-[20px] h-5 px-1.5 rounded-full
                             bg-accent text-white text-[11px] font-bold tabular-nums
                             flex items-center justify-center"
                >
                  {новых > 99 ? "99+" : новых}
                </span>
              )}
            </motion.button>
          )}
        </AnimatePresence>

        {sendError && (
          <p className="text-[12px] text-danger text-center mb-2">
            Сообщение не ушло — нет связи. Попробуйте ещё раз.
          </p>
        )}

        {actionError && (
          <button
            onClick={() => setActionError("")}
            className="block mx-auto mb-2 px-4 py-2 rounded-full bg-danger/15
                       border border-danger/30 text-danger text-[13px] font-medium"
          >
            {actionError} · закрыть
          </button>
        )}

        {noteError && (
          <button
            onClick={() => setNoteError("")}
            className="block mx-auto mb-2 px-4 py-2 rounded-full bg-danger/15
                       border border-danger/30 text-danger text-[13px] font-medium"
          >
            {noteError} · закрыть
          </button>
        )}

        <AnimatePresence>
          {тост && (
            <motion.div
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              className="mx-auto mb-2 w-fit px-3.5 py-1.5 rounded-full
                         bg-surface-3 text-[13px] text-text-secondary"
            >
              {тост}
            </motion.div>
          )}
        </AnimatePresence>

        {replyTo && (
          <ReplyStrip
            quote={цитатаИз(replyTo)}
            author={авторЦитаты(replyTo.sender_id)}
            onCancel={() => setReplyTo(null)}
            onJump={() => прыгнутьК(replyTo.id)}
          />
        )}

        {/*
          Справа ровно одна кнопка на все состояния — так же, как в Telegram и
          ВК: микрофон меняется на камеру тапом по ней самой, а не второй
          кнопкой в поле (камера в поле вечно стояла криво и читалась как
          панель инструментов). Отдельная кнопка «Отправить запись» тоже не
          нужна: палец и так стоит здесь.

          Элемент кнопки один и тот же во всех четырёх состояниях намеренно —
          при подмене button на span браузер терял захват пальца, и отпускание
          посреди записи уже никуда не приходило.
        */}
        <div className="flex items-end gap-2">
          {recording ? (
            <NoteRecorder
              kind={recording}
              locked={noteLocked}
              busy={sendingNote}
              onControls={(c) => {
                noteCtl.current = c;
              }}
              onReady={() => setNoteReady(true)}
              onDone={sendNote}
              onCancel={() => setRecording(null)}
              onError={(msg) => {
                setRecording(null);
                setNoteError(msg);
                haptic("error");
              }}
            />
          ) : (
            <div className="relative flex-1 min-w-0">
              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => onInputChange(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    send();
                  }
                }}
                placeholder="Сообщение…"
                rows={1}
                className="field w-full max-h-[120px] py-2.5 px-4 rounded-[22px]
                           resize-none text-[15px] no-scrollbar"
              />
            </div>
          )}

          <button
            type="button"
            aria-label={
              правая === "text"
                ? "Отправить"
                : правая === "note"
                  ? "Отправить запись"
                  : правая === "hold"
                    ? "Идёт запись — отпустите, чтобы отправить"
                    : noteKind === "voice"
                      ? "Голосовое: держите, чтобы записать, тап — камера"
                      : "Кружок: держите, чтобы записать, тап — микрофон"
            }
            disabled={
              правая === "text"
                ? !input.trim()
                : правая === "note"
                  ? !noteReady || sendingNote
                  : false
            }
            onClick={
              правая === "text"
                ? () => send()
                : правая === "note"
                  ? отправитьЗапись
                  : undefined
            }
            onPointerDown={правая === "arm" ? начатьУдержание : undefined}
            onPointerMove={жест ? вестиУдержание : undefined}
            onPointerUp={жест ? отпуститьУдержание : undefined}
            onPointerCancel={жест ? перехватУдержания : undefined}
            onContextMenu={жест ? (e) => e.preventDefault() : undefined}
            onKeyDown={правая === "arm" ? наКлавишеЗаписи : undefined}
            style={{ WebkitTouchCallout: "none" }}
            className={`relative w-11 h-11 rounded-full liquid-primary shrink-0
                        flex items-center justify-center select-none
                        disabled:opacity-30 transition-transform
                        ${жест ? "touch-none" : ""}
                        ${
                          правая === "hold"
                            ? "scale-[1.14] rec-halo"
                            : "active:scale-95"
                        }`}
          >
            {правая === "text" || правая === "note" ? (
              <Send size={18} />
            ) : правая === "hold" ? (
              recording === "voice" ? (
                <Mic size={20} />
              ) : (
                <Video size={20} />
              )
            ) : (
              // Иконки не подменяются, а сменяются: микрофон уходит вниз-влево,
              // камера приезжает ему на место — тап видно, даже не глядя на подсказку
              // Размер чётный (20 в коробке 44): нечётные 19 сажали значок на
              // половину пикселя и на 3× экране это читалось как перекос.
              // Никаких доводочных сдвигов: на чётном размере габарит чернил
              // камеры и микрофона совпадает с центром круга (замер по снимку).
              <>
                <span
                  aria-hidden="true"
                  className={`absolute flex transition-all duration-200 ease-out ${
                    noteKind === "voice"
                      ? "opacity-100 scale-100 rotate-0"
                      : "opacity-0 scale-[.55] -rotate-45"
                  }`}
                >
                  <Mic size={20} />
                </span>
                <span
                  aria-hidden="true"
                  className={`absolute flex transition-all duration-200 ease-out ${
                    noteKind === "video_note"
                      ? "opacity-100 scale-100 rotate-0"
                      : "opacity-0 scale-[.55] rotate-45"
                  }`}
                >
                  <Video size={20} />
                </span>
              </>
            )}
          </button>
        </div>
      </div>

      <ReportSheet
        open={reportOpen}
        name={match?.partner.display_name || "этого пользователя"}
        onClose={() => setReportOpen(false)}
        onPick={sendReport}
      />

      <ChatThemeSheet
        open={themeOpen}
        onClose={() => setThemeOpen(false)}
        matchId={matchId!}
        theme={theme}
        onApplied={(t) => {
          setTheme(t);
          setThemeOpen(false);
        }}
        onNeedPlus={() => {
          setThemeOpen(false);
          navigate("/plans");
        }}
      />

      <AnimatePresence>
        {menuFor && (
          <MessageActions
            anchor={menuFor.rect}
            mine={menuFor.msg.sender_id === myId}
            active={менюАктив}
            actions={действия}
            onPick={(k) => переключитьРеакцию(menuFor.msg, k)}
            onClose={() => setMenuFor(null)}
          />
        )}
      </AnimatePresence>

      <HabitsSheet open={habitsOpen} onClose={() => setHabitsOpen(false)} />

      {matchId && (
        <AttachmentsSheet
          open={attachOpen}
          onClose={() => setAttachOpen(false)}
          matchId={matchId}
          partnerName={match?.partner?.display_name || "собеседник"}
          onJump={прыгнутьК}
        />
      )}
      <ProfileSheet
        profile={profileOpen ? match?.partner ?? null : null}
        onClose={() => setProfileOpen(false)}
      />
    </div>
  );
}

/* ── Ответы и реакции: чистые помощники ─────────────────────── */

/**
 * Что станет с реакциями сообщения, если этот человек нажмёт этот код.
 *
 * Повторяет правило сервера (`api/services/chat_delivery.py: set_reaction`):
 * одна реакция на человека, повторное нажатие снимает, другой код заменяет.
 * Догадка живёт до ответа сокета и должна совпадать с ним, иначе список
 * дёрнется на глазах.
 */
function свестиРеакции(
  было: MessageReaction[] | null | undefined,
  key: string,
  myId: string
): MessageReaction[] {
  const своя = (было ?? []).find((r) => r.users.includes(myId));
  const снимаем = своя?.key === key;
  const без = (было ?? [])
    .map((r) => ({ key: r.key, users: r.users.filter((u) => u !== myId) }))
    .filter((r) => r.users.length > 0);
  if (снимаем) return без;
  const есть = без.find((r) => r.key === key);
  if (есть) return без.map((r) => (r.key === key ? { ...r, users: [...r.users, myId] } : r));
  return [...без, { key, users: [myId] }];
}

/**
 * Сообщение ленты → цитата в том же виде, в каком её отдаёт сервер.
 *
 * Нужна, пока ответ не ушёл: полоса над полем ввода рисуется тем же
 * компонентом, что и цитата внутри пузыря, и подсовывать ей второй формат
 * значило бы держать два описания одного и того же.
 */
function цитатаИз(m: ChatMessage): MessageQuote {
  const kind: MessageQuote["kind"] =
    m.media?.kind === "voice"
      ? "voice"
      : m.media?.kind === "video_note"
        ? "video_note"
        : m.reel
          ? "reel"
          : m.image_url
            ? "photo"
            : "text";
  return {
    id: m.id,
    sender_id: m.sender_id,
    text: m.text,
    kind,
    shape: m.media?.shape ?? null,
    poster: m.media?.poster ?? null,
    image_url: m.image_url ?? null,
    duration: m.media?.duration ?? 0,
  };
}

/* ── Время и галочки ────────────────────────────────────────── */

/**
 * Метка под сообщением: время, а у своих — галочки доставки.
 *
 * Внутри пузыря берёт его цвет (`currentColor`) и гасится прозрачностью —
 * так она читается и на акцентном фоне, и на любой пользовательской теме,
 * где фиксированный «серый» пропадал. На холсте (у видеокружка) цвет считаем
 * от фона темы.
 */
function МетаСообщения({
  время,
  mine,
  прочитано,
  наФоне,
  цветФона,
  светлая,
}: {
  время: string;
  mine: boolean;
  прочитано: boolean;
  /** Метка стоит на фоне чата, а не в пузыре. */
  наФоне?: boolean;
  цветФона?: string | null;
  /** Метка лежит поверх картинки — белая по тёмной подложке. */
  светлая?: boolean;
}) {
  return (
    <span
      className={`inline-flex items-center gap-[3px] text-[10.5px] leading-none
                  tabular-nums ${наФоне ? "text-text-faint" : ""}`}
      style={
        наФоне
          ? {
              color: цветФона ? readableOn(цветФона) : undefined,
              opacity: цветФона ? 0.6 : undefined,
            }
          : { opacity: светлая ? 0.92 : 0.68 }
      }
    >
      {время}
      {mine &&
        (прочитано ? (
          <CheckCheck size={13} className={наФоне ? "text-info" : undefined} />
        ) : (
          <Check size={13} />
        ))}
    </span>
  );
}

/* ── Выбор причины жалобы ───────────────────────────────────── */

function ReportSheet({
  open,
  name,
  onClose,
  onPick,
}: {
  open: boolean;
  name: string;
  onClose: () => void;
  onPick: (reason: string) => void;
}) {
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
            aria-label="Причина жалобы"
            initial={{ y: "100%" }}
            animate={{ y: 0 }}
            exit={{ y: "100%" }}
            transition={{ type: "spring", stiffness: 380, damping: 36 }}
            className="fixed bottom-0 left-0 right-0 z-50 bg-bg-elevated
                       rounded-t-[var(--radius-sheet)] border-t border-hairline
                       px-5 pt-3 pb-7 safe-bottom max-h-[80dvh] overflow-y-auto no-scrollbar"
          >
            <div className="w-10 h-1 rounded-full bg-surface-3 mx-auto mb-5" />

            <h2 className="text-heading font-bold mb-1.5">Пожаловаться на {name}</h2>
            <p className="text-caption text-text-muted mb-4">
              Мэтч будет удалён, а жалоба уйдёт модератору
            </p>

            <div className="flex flex-col gap-1.5 mb-4">
              {REPORT_REASONS.map((r) => (
                <button
                  key={r.value}
                  onClick={() => onPick(r.value)}
                  className="w-full px-4 py-3 rounded-[var(--radius-tile)] text-left
                             bg-surface-2 border border-hairline text-[15px]
                             active:bg-surface transition-colors"
                >
                  {r.label}
                </button>
              ))}
            </div>

            <Button variant="secondary" size="lg" fullWidth onClick={onClose}>
              Отмена
            </Button>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}

/* ── Группировка ────────────────────────────────────────────── */

interface Group {
  key: string;
  mine: boolean;
  dateLabel: string | null;
  messages: ChatMessage[];
}

/** Подряд идущие сообщения одного автора в пределах 5 минут — одна группа. */
function groupMessages(messages: ChatMessage[], myId: string | undefined, язык: Язык): Group[] {
  const groups: Group[] = [];
  let lastDate = "";

  for (const m of messages) {
    const mine = m.sender_id === myId;
    const dayKey = m.created_at ? new Date(m.created_at).toDateString() : "";
    const dateLabel = dayKey && dayKey !== lastDate ? formatDate(m.created_at, язык) : null;
    if (dateLabel) lastDate = dayKey;

    const prev = groups[groups.length - 1];
    const canAppend =
      prev &&
      prev.mine === mine &&
      !dateLabel &&
      withinGap(prev.messages[prev.messages.length - 1].created_at, m.created_at);

    if (canAppend) {
      prev.messages.push(m);
    } else {
      groups.push({ key: m.id, mine, dateLabel, messages: [m] });
    }
  }

  return groups;
}

function withinGap(a?: string | null, b?: string | null): boolean {
  if (!a || !b) return true;
  const diff = Math.abs(new Date(b).getTime() - new Date(a).getTime());
  return diff < 5 * 60 * 1000;
}

function formatTime(iso: string | null | undefined, язык: Язык): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return форматВремени(d, язык);
}

function formatDate(iso: string | null | undefined, язык: Язык): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";

  const now = new Date();
  if (d.toDateString() === now.toDateString()) return перевести(язык, "date.today");

  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (d.toDateString() === yesterday.toDateString()) return перевести(язык, "date.yesterday");

  // Год добавляем только чужой: «20 августа 2026» в переписке этого года —
  // шум, а без года в переписке прошлого не понять, о каком дне речь.
  return форматДняРазделителя(d, язык, d.getFullYear() !== now.getFullYear());
}
