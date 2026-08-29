import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import VoiceRoulette from "../VoiceRoulette";
import * as api from "../../lib/api";

class MockWebSocket {
  static OPEN = 1;
  static CLOSED = 3;
  static instances: MockWebSocket[] = [];
  readyState = 0;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  send = vi.fn();

  constructor(public url: string) {
    MockWebSocket.instances.push(this);
  }

  open() {
    this.readyState = MockWebSocket.OPEN;
    this.onopen?.();
  }

  close() {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.();
  }
}

class MockPeerConnection {
  connectionState = "new";
  onicecandidate: ((event: { candidate: unknown }) => void) | null = null;
  ontrack: ((event: { streams: MediaStream[] }) => void) | null = null;
  onconnectionstatechange: (() => void) | null = null;
  close = vi.fn(() => {
    this.connectionState = "closed";
  });
  addTrack = vi.fn();
  createOffer = vi.fn(async () => ({ type: "offer", sdp: "offer" }));
  createAnswer = vi.fn(async () => ({ type: "answer", sdp: "answer" }));
  setLocalDescription = vi.fn(async () => undefined);
  setRemoteDescription = vi.fn(async () => undefined);
  addIceCandidate = vi.fn(async () => undefined);
}

beforeEach(() => {
  MockWebSocket.instances = [];
  vi.spyOn(api, "recordSectionOpen").mockResolvedValue(undefined);
  vi.spyOn(api, "getIceServers").mockResolvedValue([]);
  vi.stubGlobal("WebSocket", MockWebSocket);
  vi.stubGlobal("RTCPeerConnection", MockPeerConnection);
  vi.stubGlobal("RTCSessionDescription", class {
    constructor(public value: unknown) {}
  });
  vi.stubGlobal("RTCIceCandidate", class {
    constructor(public value: unknown) {}
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("VoiceRoulette — lifecycle звонка", () => {
  it("освобождает микрофон и позволяет начать новый звонок после завершения", async () => {
    const track = {
      enabled: true,
      stop: vi.fn(),
    } as unknown as MediaStreamTrack;
    const stream = {
      getTracks: () => [track],
      getAudioTracks: () => [track],
    } as unknown as MediaStream;
    const getUserMedia = vi
      .fn()
      .mockResolvedValue(stream);
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia },
    });
    localStorage.setItem("sd_token", "test-token");

    render(
      <MemoryRouter>
        <VoiceRoulette />
      </MemoryRouter>
    );

    fireEvent.click(screen.getByRole("button", { name: "Начать звонок" }));
    await waitFor(() => expect(getUserMedia).toHaveBeenCalledTimes(1));
    expect(screen.getByText("Ищем собеседника…")).toBeInTheDocument();

    const firstSocket = MockWebSocket.instances[0];
    firstSocket.open();
    expect(firstSocket.send).toHaveBeenCalledWith(JSON.stringify({ type: "find" }));

    fireEvent.click(screen.getByRole("button", { name: "Завершить" }));
    expect(track.stop).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Начать звонок" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Начать звонок" }));
    await waitFor(() => expect(getUserMedia).toHaveBeenCalledTimes(2));
    expect(MockWebSocket.instances).toHaveLength(2);
  });
});
