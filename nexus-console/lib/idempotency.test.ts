import { afterEach, describe, expect, it, vi } from "vitest";
import { createIdempotencyKey } from "./idempotency";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("createIdempotencyKey", () => {
  it("uses randomUUID when the browser provides it", () => {
    const randomUUID = vi.fn(() => "11111111-1111-4111-8111-111111111111");
    vi.stubGlobal("crypto", { randomUUID });

    expect(createIdempotencyKey()).toBe("11111111-1111-4111-8111-111111111111");
    expect(randomUUID).toHaveBeenCalledOnce();
  });

  it("creates a version-4 UUID when randomUUID is unavailable", () => {
    vi.stubGlobal("crypto", {
      getRandomValues: (bytes: Uint8Array) => {
        bytes.fill(0xab);
        return bytes;
      },
    });

    expect(createIdempotencyKey()).toBe("abababab-abab-4bab-abab-abababababab");
  });

  it("has a random-number fallback when Web Crypto is unavailable", () => {
    vi.stubGlobal("crypto", undefined);
    const random = vi.spyOn(Math, "random").mockReturnValue(0);

    expect(createIdempotencyKey()).toBe("00000000-0000-4000-8000-000000000000");
    random.mockRestore();
  });
});
