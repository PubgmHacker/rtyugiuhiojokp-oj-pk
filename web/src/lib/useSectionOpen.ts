/**
 * Отметить открытие раздела при монтировании экрана.
 *
 * Отдельный хук, а не вызов в каждом экране: пять копий одного `useEffect`
 * рано или поздно разъедутся — где-то забудут код раздела, где-то повторят
 * запрос на каждый рендер.
 *
 * Отправляем один раз за монтирование: перерисовки не должны считаться
 * новыми открытиями, иначе цифры превратятся в шум.
 */

import { useEffect, useRef } from "react";
import { recordSectionOpen, type Section } from "../lib/api";

export function useSectionOpen(section: Section): void {
  const sent = useRef(false);

  useEffect(() => {
    if (sent.current) return;
    sent.current = true;
    recordSectionOpen(section);
  }, [section]);
}
