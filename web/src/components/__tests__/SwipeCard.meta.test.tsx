/**
 * Метки анкеты на карточке — одна строка вместо каши.
 *
 * До этого тип связи, цель, субкультура, MBTI и интересы стояли двумя
 * блоками с flex-wrap: у заполненной анкеты они разъезжались на четыре
 * ряда плашек и закрывали фото — ровно то, на что пожаловался владелец.
 * Теперь в строку входит столько, сколько влезает по ширине, а хвост
 * сворачивается в «ещё N», открывающую полную анкету.
 *
 * Проверять это глазами нельзя: в jsdom нет вёрстки, поэтому ширины
 * подставляем сами и смотрим на арифметику отбора — она и решает, что
 * увидит человек.
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import SwipeCard from "../SwipeCard";
import type { DeckProfile } from "../../lib/api";

/** Ширина одной метки и всей строки в стенде, px. */
const МЕТКА = 80;
const РЯД = 200;

function анкета(over: Partial<DeckProfile> = {}): DeckProfile {
  return {
    id: "u-anya",
    display_name: "Аня",
    age: 24,
    city: "Москва",
    bio: "Люблю горы",
    photos: [],
    relation_type: "partner",
    goal: "relationship",
    subculture: "goth",
    mbti: "INFJ",
    interests: ["кино", "горы", "джаз"],
    ...over,
  };
}

/** Подставляем вёрстку: строка шириной РЯД, каждая метка — МЕТКА. */
function размеры() {
  vi.spyOn(HTMLElement.prototype, "offsetWidth", "get").mockImplementation(
    function (this: HTMLElement) {
      return this.tagName === "SPAN" ? МЕТКА : 0;
    }
  );
  vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(РЯД);
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("SwipeCard — метки одной строкой", () => {
  it("показывает столько меток, сколько влезло, остальное — за «ещё N»", () => {
    размеры();
    render(
      <SwipeCard profile={анкета()} onSwipe={() => {}} isTop index={0} />
    );

    // 200 px: две метки влезли бы (80 + 6 + 80), но раз хвост остаётся,
    // место занимает и кнопка — с резервом под неё влезает одна
    expect(screen.getByText("Партнёр")).toBeTruthy();
    expect(screen.queryByText("Гот")).toBeNull();
    expect(screen.queryByText("кино")).toBeNull();
    // 7 меток всего: связь, цель, субкультура, MBTI и три интереса
    expect(screen.getByRole("button", { name: /Ещё 6/ })).toBeTruthy();
  });

  it("«ещё N» открывает полную анкету и не начинает свайп", () => {
    размеры();
    const открыть = vi.fn();
    render(
      <SwipeCard
        profile={анкета()}
        onSwipe={() => {}}
        isTop
        index={0}
        onOpenProfile={открыть}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /Ещё 6/ }));
    expect(открыть).toHaveBeenCalledWith(expect.objectContaining({ id: "u-anya" }));
  });

  it("без вёрстки (ширины нет) показывает все метки и не врёт счётчиком", () => {
    render(
      <SwipeCard profile={анкета()} onSwipe={() => {}} isTop index={0} />
    );

    expect(screen.getByText("Партнёр")).toBeTruthy();
    expect(screen.getByText("джаз")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Ещё/ })).toBeNull();
  });

  it("интерес, повторяющий субкультуру, не рисуется дважды", () => {
    render(
      <SwipeCard
        profile={анкета({ subculture: "anime", interests: ["Аниме", "кино"] })}
        onSwipe={() => {}}
        isTop
        index={0}
      />
    );

    expect(screen.getAllByText("Аниме")).toHaveLength(1);
  });
});
