/**
 * Полноэкранный просмотр чужой анкеты (ProfileSheet) — ответ на находку
 * аудита «экрана чужого профиля нет вообще»: решение принималось по одному
 * кадру тайла. Здесь проверяем, что шторка показывает всё, что сервер
 * прислал в UserProfile, листает фото и закрывается.
 */

import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import ProfileSheet from "../ProfileSheet";
import type { UserProfile } from "../../lib/api";

function анкета(over: Partial<UserProfile> = {}): UserProfile {
  return {
    id: "u-anya",
    display_name: "Аня",
    age: 24,
    bio: "Люблю горы и старое кино.\nИщу компанию в походы.",
    gender: "female",
    city: "Москва",
    height_cm: 172,
    goal: "relationship",
    mbti: "INFJ",
    photos: ["https://x/1.jpg", "https://x/2.jpg"],
    interests: ["кино", "горы", "джаз"],
    looking_for: "",
    is_incognito: false,
    is_verified: true,
    tg_channel: "anya_channel",
    like_message: "У нас общие горы!",
    ...over,
  } as UserProfile;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("ProfileSheet — полный профиль человека", () => {
  it("null-профиль не рисует ничего", () => {
    render(<ProfileSheet profile={null} onClose={() => {}} />);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("показывает всё, ради чего открывали: био целиком, интересы, факты", () => {
    render(<ProfileSheet profile={анкета()} onClose={() => {}} />);

    expect(screen.getByRole("dialog", { name: "Профиль Аня" })).toBeInTheDocument();
    expect(screen.getByText("Аня")).toBeInTheDocument();
    expect(screen.getByText("24")).toBeInTheDocument();
    expect(screen.getByText("Москва")).toBeInTheDocument();
    expect(screen.getByText("172 см")).toBeInTheDocument();
    // Био без обрезки — в тайле его не видно вовсе
    expect(screen.getByText(/Ищу компанию в походы/)).toBeInTheDocument();
    // Все интересы, а не первые N
    for (const и of ["кино", "горы", "джаз"]) {
      expect(screen.getByText(и)).toBeInTheDocument();
    }
    // Код цели превращается в человеческий лейбл
    expect(screen.getByText("Отношения")).toBeInTheDocument();
    expect(screen.getByText("INFJ")).toBeInTheDocument();
    // Текст лайка — причина, по которой вас вообще заметили
    expect(screen.getByText(/У нас общие горы!/)).toBeInTheDocument();
    // Канал собирается в ссылку, как в шапке чата
    expect(screen.getByRole("link", { name: "@anya_channel" })).toHaveAttribute(
      "href",
      "https://t.me/anya_channel"
    );
  });

  it("листает фото тап-зонами", () => {
    render(<ProfileSheet profile={анкета()} onClose={() => {}} />);

    const кадр = () => screen.getByAltText("Аня") as HTMLImageElement;
    expect(кадр().src).toContain("/1.jpg");

    fireEvent.click(screen.getByLabelText("Следующее фото"));
    expect(кадр().src).toContain("/2.jpg");

    fireEvent.click(screen.getByLabelText("Предыдущее фото"));
    expect(кадр().src).toContain("/1.jpg");
  });

  it("одно фото — пейджер не рисуется", () => {
    render(
      <ProfileSheet
        profile={анкета({ photos: ["https://x/1.jpg"] })}
        onClose={() => {}}
      />
    );
    expect(screen.queryByLabelText("Следующее фото")).toBeNull();
  });

  it("закрывается кнопкой и по Escape", () => {
    const onClose = vi.fn();
    render(<ProfileSheet profile={анкета()} onClose={onClose} />);

    fireEvent.click(screen.getByLabelText("Закрыть профиль"));
    expect(onClose).toHaveBeenCalledTimes(1);

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("кнопки решения приходят через actions", () => {
    render(
      <ProfileSheet
        profile={анкета()}
        onClose={() => {}}
        actions={<button>Лайк из шторки</button>}
      />
    );
    expect(screen.getByText("Лайк из шторки")).toBeInTheDocument();
  });
});
