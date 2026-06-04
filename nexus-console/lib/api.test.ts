import { describe, it, expect } from "vitest";
import { formatDateTime, shortId, textValue } from "./api";

describe("formatDateTime", () => {
  it("returns '-' for null", () => {
    expect(formatDateTime(null)).toBe("-");
  });

  it("returns '-' for undefined", () => {
    expect(formatDateTime(undefined)).toBe("-");
  });

  it("returns '-' for empty string", () => {
    expect(formatDateTime("")).toBe("-");
  });

  it("returns original value for invalid date string", () => {
    expect(formatDateTime("not-a-date")).toBe("not-a-date");
  });

  it("formats valid ISO date in zh-CN locale", () => {
    const result = formatDateTime("2025-01-15T08:30:00Z");
    // zh-CN format: YYYY/MM/DD HH:mm
    expect(result).toMatch(/2025\/01\/15/);
    expect(result).toContain(":");
  });

  it("handles date with timezone offset", () => {
    const result = formatDateTime("2025-06-04T12:00:00+08:00");
    expect(result).not.toBe("-");
    expect(result).not.toBe("2025-06-04T12:00:00+08:00");
  });
});

describe("shortId", () => {
  it("returns '-' for null", () => {
    expect(shortId(null)).toBe("-");
  });

  it("returns '-' for undefined", () => {
    expect(shortId(undefined)).toBe("-");
  });

  it("returns '-' for empty string", () => {
    expect(shortId("")).toBe("-");
  });

  it("returns short strings unchanged", () => {
    expect(shortId("abc123")).toBe("abc123");
  });

  it("truncates long UUIDs with ellipsis", () => {
    const uuid = "550e8400-e29b-41d4-a716-446655440000";
    const result = shortId(uuid);
    expect(result).toBe("550e8400...0000");
    expect(result).toHaveLength(15); // 8 + 3 + 4
  });

  it("truncates exactly 12-char strings at boundary", () => {
    expect(shortId("abcdefghijkl")).toBe("abcdefghijkl");
    expect(shortId("abcdefghijklm")).toBe("abcdefgh...jklm");
  });
});

describe("textValue", () => {
  it("returns '-' for null", () => {
    expect(textValue(null)).toBe("-");
  });

  it("returns '-' for undefined", () => {
    expect(textValue(undefined)).toBe("-");
  });

  it("returns '-' for empty string", () => {
    expect(textValue("")).toBe("-");
  });

  it("returns string values unchanged", () => {
    expect(textValue("hello")).toBe("hello");
  });

  it("returns number as string", () => {
    expect(textValue(42)).toBe("42");
  });

  it("returns boolean as string", () => {
    expect(textValue(true)).toBe("true");
    expect(textValue(false)).toBe("false");
  });

  it("joins array with comma-space", () => {
    expect(textValue(["a", "b", "c"])).toBe("a, b, c");
  });

  it("returns '-' for empty array", () => {
    expect(textValue([])).toBe("-");
  });

  it("JSON-stringifies objects", () => {
    expect(textValue({ key: "val" })).toBe('{"key":"val"}');
  });
});
