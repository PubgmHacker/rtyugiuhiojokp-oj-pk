/**
 * Пересланный ролик внутри сообщения — и в личке, и в комнате.
 *
 * Играет на месте, а не ведёт в ленту: у ролика нет своего экрана, а лента
 * пагинируется от свежих к старым, так что «открыть именно этот» означало бы
 * листать её до нужного места. Уходить из переписки, чтобы посмотреть
 * присланное, тоже неверно — разговор идёт здесь.
 *
 * Пока не тапнули, грузим только обложку: в истории таких сообщений может быть
 * много, и десяток видео разом съест трафик.
 */

import { useRef, useState } from "react";
import { Play } from "lucide-react";
import type { ReelPreview } from "../lib/api";
import { haptic } from "../lib/haptics";

export default function ReelBubble({
  reel,
  mine,
}: {
  reel: ReelPreview;
  /** В своём пузыре подпись светлая, в чужом — обычная. */
  mine?: boolean;
}) {
  const [playing, setPlaying] = useState(false);
  const ref = useRef<HTMLVideoElement | null>(null);

  return (
    <div className="mb-1 w-[190px] max-w-full">
      <div className="relative rounded-xl overflow-hidden bg-black/40 aspect-[9/16]">
        {playing ? (
          <video
            ref={ref}
            src={reel.video_url}
            poster={reel.cover_url || undefined}
            autoPlay
            loop
            controls
            playsInline
            className="w-full h-full object-contain"
          />
        ) : (
          <button
            onClick={() => {
              haptic("light");
              setPlaying(true);
            }}
            aria-label="Смотреть видео"
            className="w-full h-full active:scale-[0.98] transition-transform"
          >
            {reel.cover_url ? (
              <img
                src={reel.cover_url}
                alt=""
                loading="lazy"
                className="w-full h-full object-cover"
              />
            ) : (
              <span
                className="block w-full h-full"
                style={{ background: "var(--gradient-placeholder)" }}
              />
            )}
            <span
              className="absolute inset-0 flex items-center justify-center"
              aria-hidden
            >
              <span
                className="w-12 h-12 rounded-full glass-strong flex items-center
                           justify-center text-white"
              >
                <Play size={20} fill="currentColor" />
              </span>
            </span>
          </button>
        )}
      </div>

      {reel.caption && (
        <p
          className={`mt-1 text-[12.5px] leading-snug line-clamp-2 ${
            mine ? "text-on-accent/80" : "text-text-muted"
          }`}
        >
          {reel.caption}
        </p>
      )}
    </div>
  );
}
