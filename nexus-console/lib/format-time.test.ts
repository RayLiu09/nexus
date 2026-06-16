import { describe, expect, it } from "vitest";
import { formatSla, formatTime, slaTier } from "./format-time";

describe("formatTime", () => {
  it("returns fallback for missing values", () => {
    expect(formatTime(null)).toEqual({ display: "-", iso: "" });
    expect(formatTime(undefined)).toEqual({ display: "-", iso: "" });
    expect(formatTime("")).toEqual({ display: "-", iso: "" });
  });

  it("returns fallback for invalid values", () => {
    expect(formatTime("not-a-date")).toEqual({ display: "-", iso: "" });
  });
});

describe("SLA time helpers", () => {
  it("return neutral fallback for invalid deadlines", () => {
    expect(slaTier(undefined)).toBe("normal");
    expect(slaTier("not-a-date")).toBe("normal");
    expect(formatSla(undefined)).toBe("-");
    expect(formatSla("not-a-date")).toBe("-");
  });
});
