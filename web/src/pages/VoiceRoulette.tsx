/**
 * Голосовая рулетка: случайный звонок одним тапом.
 *
 * Звук идёт напрямую между браузерами через WebRTC — сервер только знакомит
 * собеседников и передаёт сигналы. Микрофон запрашиваем в момент нажатия, а не
 * при открытии экрана: системный запрос без явного действия пугает и его чаще
 * отклоняют.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { Flag, Mic, MicOff, PhoneOff, SkipForward } from "lucide-react";
import { getIceServers, reportUser } from "../lib/api";
import { haptic } from "../lib/haptics";
import { useSectionOpen } from "../lib/useSectionOpen";
import { ScreenHeader } from "../components/ui";

const WS_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

type Stage = "idle" | "waiting" | "talking";

export default function VoiceRoulette() {
  useSectionOpen("voice");
  const [stage, setStage] = useState<Stage>("idle");
  const [muted, setMuted] = useState(false);
  const [error, setError] = useState("");
  // Кто на другом конце — иначе пожаловаться не на кого, а голос незнакомца
  // без кнопки жалобы это то, чего в дейтинге быть не должно
  const [partnerId, setPartnerId] = useState<string | null>(null);
  const [reported, setReported] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const localRef = useRef<MediaStream | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const iceRef = useRef<RTCIceServer[] | null>(null);

  /** Снести соединение, но оставить сокет: он нужен для следующего поиска. */
  const teardownCall = useCallback(() => {
    pcRef.current?.close();
    pcRef.current = null;
    if (audioRef.current) audioRef.current.srcObject = null;
  }, []);

  const stopAll = useCallback(() => {
    teardownCall();
    localRef.current?.getTracks().forEach((t) => t.stop());
    localRef.current = null;
    wsRef.current?.close();
    wsRef.current = null;
    setStage("idle");
  }, [teardownCall]);

  // Уходя с экрана, обязательно отпускаем микрофон: иначе индикатор записи
  // остаётся гореть, и это выглядит как слежка
  useEffect(() => stopAll, [stopAll]);

  const createPeer = useCallback(
    (sendSignal: (payload: unknown) => void) => {
      const pc = new RTCPeerConnection({ iceServers: iceRef.current ?? [] });

      localRef.current?.getTracks().forEach((track) => {
        pc.addTrack(track, localRef.current as MediaStream);
      });

      pc.onicecandidate = (e) => {
        if (e.candidate) sendSignal({ candidate: e.candidate });
      };

      pc.ontrack = (e) => {
        if (audioRef.current) {
          audioRef.current.srcObject = e.streams[0];
          audioRef.current.play().catch(() => {
            /* автозапуск может быть запрещён до жеста — звук пойдёт позже */
          });
        }
      };

      pc.onconnectionstatechange = () => {
        if (pc.connectionState === "connected") setStage("talking");
        if (pc.connectionState === "failed") {
          setError("Не удалось соединиться. Попробуйте ещё раз.");
          teardownCall();
          setStage("idle");
        }
      };

      pcRef.current = pc;
      return pc;
    },
    [teardownCall]
  );

  const start = useCallback(async () => {
    setError("");
    haptic("light");

    try {
      if (!iceRef.current) iceRef.current = await getIceServers();

      if (!localRef.current) {
        localRef.current = await navigator.mediaDevices.getUserMedia({ audio: true });
      }
    } catch {
      setError("Нужен доступ к микрофону — разрешите его в настройках браузера");
      return;
    }

    setStage("waiting");

    const token = localStorage.getItem("sd_token") ?? "";
    const url = `${WS_URL.replace(/^http/, "ws")}/api/voice/ws/roulette?token=${token}`;
    const ws = new WebSocket(url);
    wsRef.current = ws;

    const sendSignal = (payload: unknown) =>
      ws.send(JSON.stringify({ type: "signal", payload }));

    ws.onopen = () => ws.send(JSON.stringify({ type: "find" }));

    ws.onmessage = async (event) => {
      const data = JSON.parse(event.data);

      if (data.type === "matched") {
        setPartnerId(data.partner_id ?? null);
        setReported(false);
        const pc = createPeer(sendSignal);
        // Offer шлёт только тот, кого сервер назначил инициатором: иначе оба
        // отправят offer и соединение не соберётся
        if (data.initiator) {
          const offer = await pc.createOffer();
          await pc.setLocalDescription(offer);
          sendSignal({ sdp: offer });
        }
        return;
      }

      if (data.type === "signal") {
        const pc = pcRef.current ?? createPeer(sendSignal);
        const { sdp, candidate } = data.payload ?? {};

        if (sdp) {
          await pc.setRemoteDescription(new RTCSessionDescription(sdp));
          if (sdp.type === "offer") {
            const answer = await pc.createAnswer();
            await pc.setLocalDescription(answer);
            sendSignal({ sdp: answer });
          }
        } else if (candidate) {
          try {
            await pc.addIceCandidate(new RTCIceCandidate(candidate));
          } catch {
            /* кандидат мог прийти до описания — WebRTC переживает */
          }
        }
        return;
      }

      if (data.type === "partner_left") {
        haptic("warning");
        teardownCall();
        setStage("idle");
        setError("Собеседник отключился");
      }
    };

    ws.onerror = () => setError("Нет связи с сервером");
    ws.onclose = () => {
      teardownCall();
      setStage((cur) => (cur === "idle" ? cur : "idle"));
    };
  }, [createPeer, teardownCall]);

  const report = useCallback(async () => {
    if (!partnerId || reported) return;
    haptic("warning");
    try {
      await reportUser(partnerId, "harassment", "Жалоба из голосовой рулетки");
      setReported(true);
      setError("Жалоба отправлена — модератор разберётся");
      // Разрываем звонок: продолжать разговор с тем, на кого пожаловался,
      // человек почти наверняка не хочет
      teardownCall();
      setStage("idle");
    } catch {
      haptic("error");
      setError("Не удалось отправить жалобу");
    }
  }, [partnerId, reported, teardownCall]);

  const next = useCallback(() => {
    haptic("light");
    teardownCall();
    setStage("waiting");
    wsRef.current?.send(JSON.stringify({ type: "find" }));
  }, [teardownCall]);

  const toggleMute = useCallback(() => {
    const track = localRef.current?.getAudioTracks()[0];
    if (!track) return;
    track.enabled = !track.enabled;
    setMuted(!track.enabled);
    haptic("light");
  }, []);

  return (
    <div className="flex flex-col h-[calc(100dvh-68px)]">
      <ScreenHeader title="Голосовая рулетка" />

      <div className="flex-1 flex flex-col items-center justify-center px-8 text-center">
        <audio ref={audioRef} autoPlay playsInline className="hidden" />

        <motion.button
          onClick={stage === "idle" ? start : undefined}
          disabled={stage !== "idle"}
          animate={
            stage === "waiting"
              ? { scale: [1, 1.06, 1] }
              : { scale: 1 }
          }
          transition={{
            duration: 1.4,
            repeat: stage === "waiting" ? Infinity : 0,
          }}
          className={`w-32 h-32 rounded-full flex items-center justify-center glow-rose
                      ${stage === "idle" ? "bg-dawn active:scale-95" : "bg-dawn/60"}
                      transition-transform`}
          aria-label={stage === "idle" ? "Начать звонок" : "Идёт поиск"}
        >
          <Mic size={44} className="text-white" />
        </motion.button>

        <p className="mt-6 text-[15px] text-text-secondary max-w-[280px]">
          {stage === "idle" && "Нажмите, чтобы начать случайный голосовой звонок"}
          {stage === "waiting" && "Ищем собеседника…"}
          {stage === "talking" && "Разговор идёт"}
        </p>

        {error && (
          <p role="alert" className="mt-4 text-[13.5px] text-danger max-w-[280px]">
            {error}
          </p>
        )}

        {stage !== "idle" && (
          <div className="flex items-center gap-3 mt-8">
            <button
              onClick={toggleMute}
              aria-label={muted ? "Включить микрофон" : "Выключить микрофон"}
              className="w-14 h-14 rounded-full glass-strong flex items-center
                         justify-center active:scale-95 transition-transform"
            >
              {muted ? <MicOff size={20} /> : <Mic size={20} />}
            </button>

            <button
              onClick={next}
              aria-label="Следующий собеседник"
              className="w-14 h-14 rounded-full glass-strong flex items-center
                         justify-center active:scale-95 transition-transform"
            >
              <SkipForward size={20} />
            </button>

            {/* Жалоба на голос: без неё разговор с незнакомцем — единственное
                место в приложении, откуда нельзя сообщить о нарушении */}
            {partnerId && (
              <button
                onClick={report}
                disabled={reported}
                aria-label={reported ? "Жалоба отправлена" : "Пожаловаться"}
                className="w-14 h-14 rounded-full glass-strong flex items-center
                           justify-center text-warn disabled:opacity-40
                           active:scale-95 transition-transform"
              >
                <Flag size={19} />
              </button>
            )}

            <button
              onClick={stopAll}
              aria-label="Завершить"
              className="w-14 h-14 rounded-full bg-danger text-white flex items-center
                         justify-center active:scale-95 transition-transform"
            >
              <PhoneOff size={20} />
            </button>
          </div>
        )}

        <p className="mt-8 text-[12px] text-text-faint max-w-[280px] leading-snug">
          Звонок идёт напрямую между устройствами. Мы не записываем разговоры —
          но фиксируем, кто с кем говорил, чтобы разбирать жалобы.
        </p>
      </div>
    </div>
  );
}
