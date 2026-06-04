/// <reference types="vitest/globals" />

import "@testing-library/jest-dom/vitest";
import { server } from "./test-utils/msw-server";
import { vi } from "vitest";

beforeAll(() => server.listen({ onUnhandledRequest: "warn" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

// React 19 needs navigator.userAgent; jsdom 29 may not provide it
if (!("userAgent" in globalThis.navigator)) {
  Object.defineProperty(globalThis.navigator, "userAgent", {
    value: "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    configurable: true,
  });
}

// Override navigator.clipboard — jsdom 29 provides a stub that isn't a vitest spy
Object.defineProperty(globalThis.navigator, "clipboard", {
  value: {
    writeText: vi.fn().mockResolvedValue(undefined),
    readText: vi.fn().mockResolvedValue(""),
  },
  configurable: true,
  writable: true,
});

// Suppress Antd cssinjs warnings in test
const originalWarn = console.warn;
console.warn = (...args: unknown[]) => {
  const msg = String(args[0]);
  if (msg.includes("antd") || msg.includes("cssinjs")) return;
  originalWarn(...args);
};

// Mock window.matchMedia for Antd responsive components
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});
