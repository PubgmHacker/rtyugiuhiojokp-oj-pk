/**
 * Шкала оценки фото.
 *
 * Раньше это были пять одинаковых плиток bg-surface-2: направление шкалы
 * не читалось вообще — «1» выглядела ровно как «5», и человек выбирал
 * вслепую. Держим две вещи, которые ломаются молча:
 *  1. ступени различимы — доля акцента в заливке растёт от первой к
 *     последней (6 → 28 %);
 *  2. цифра под пальцем уходит на сервер той, какую нажали, — сбитый на
 *     единицу индекс в ramp'е самая дешёвая ошибка в такой правке.
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import PhotoRatings from "../PhotoRatings";
import * as api from "../../lib/api";
import { useStore } from "../../lib/store";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

async function шкала() {
  useStore.setState({ token: "test-token" });
  vi.spyOn(api, "getRatingQueue").mockResolvedValue([
    { user_id: "u1", display_name: "Марина", photo: "https://example.test/p.jpg" },
    { user_id: "u2", display_name: "Аня", photo: "https://example.test/q.jpg" },
  ]);
  render(
    <MemoryRouter>
      <PhotoRatings />
    </MemoryRouter>
  );
  await screen.findByLabelText("Оценка 5");
}

/** Доля акцента в заливке ступени: `color-mix(… N%, transparent)`. */
function долиАкцента(): number[] {
  return [1, 2, 3, 4, 5].map((n) => {
    const фон = screen.getByLabelText(`Оценка ${n}`).style.background || "";
    const m = фон.match(/([\d.]+)%/);
    expect(m, `нет процента в заливке ступени ${n}: "${фон}"`).not.toBeNull();
    return Number(m![1]);
  });
}

describe("Оценка фото — шкала", () => {
  it("ступени различимы: заливка растёт от 1 к 5", async () => {
    await шкала();
    const доли = долиАкцента();
    for (let i = 1; i < доли.length; i++) {
      expect(доли[i]).toBeGreaterThan(доли[i - 1]);
    }
  });

  it("нажатая цифра уходит на сервер как есть", async () => {
    const rate = vi.spyOn(api, "ratePhoto").mockResolvedValue(undefined as never);
    await шкала();
    fireEvent.click(screen.getByLabelText("Оценка 4"));
    await waitFor(() => expect(rate).toHaveBeenCalledWith("u1", 4));
  });
});
