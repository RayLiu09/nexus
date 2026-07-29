import { describe, expect, it } from "vitest";
import { formatApiCallerKeyReference } from "./api-caller-key";

describe("formatApiCallerKeyReference", () => {
  it("shows a stable truncated SHA-256 fingerprint for server-minted keys", () => {
    expect(
      formatApiCallerKeyReference(
        null,
        "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
      ),
    ).toBe("sha256:0123456789ab...89abcdef");
  });

  it("never renders a legacy plaintext key in full", () => {
    expect(formatApiCallerKeyReference("legacy-key-secret", null)).toBe("leg...cret");
  });

  it("returns a placeholder when a historical record has no key material", () => {
    expect(formatApiCallerKeyReference(null, null)).toBe("-");
  });
});
