/**
 * Одна дорожка за раз: голосовое, кружок или ролик, начавший играть, ставит
 * на паузу то, что играло до него. Иначе два голосовых в ленте чата
 * накладывались бы друг на друга — так не делает ни один мессенджер.
 */

let release: (() => void) | null = null;

/** Заявить воспроизведение. Возвращает функцию «я закончил». */
export function claimPlayback(pause: () => void): () => void {
  if (release) release();
  let mine = true;
  release = () => {
    if (!mine) return;
    mine = false;
    pause();
  };
  return () => {
    if (release && mine) {
      mine = false;
      release = null;
    }
  };
}
