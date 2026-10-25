import { describe, it, expect } from "vitest";

// Tokens from DESIGN.md section 3
export const TOKENS = {
  paper: "#F5F7F6",
  ink: "#18242C",
  rule: "#D5DAD8",
  viewer: "#4A4C4E",
  gentian: "#4B2E83",
  white: "#FFFFFF",
  urgent: "#B42318",
  soon: "#B7791F",
  routine: "#2F7D57",
  uncertain: "#52627A",
};

/**
 * Standard WCAG 2.1 relative luminance calculation.
 * https://www.w3.org/WAI/GL/wiki/Relative_luminance
 */
export function getRelativeLuminance(hex: string): number {
  const cleanHex = hex.replace("#", "");
  const r = parseInt(cleanHex.substring(0, 2), 16) / 255;
  const g = parseInt(cleanHex.substring(2, 4), 16) / 255;
  const b = parseInt(cleanHex.substring(4, 6), 16) / 255;

  const toLinear = (c: number) => (c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4));

  return 0.2126 * toLinear(r) + 0.7152 * toLinear(g) + 0.0722 * toLinear(b);
}

/**
 * Standard WCAG 2.1 contrast ratio calculation.
 * https://www.w3.org/TR/WCAG21/#dfn-contrast-ratio
 */
export function getContrastRatio(hex1: string, hex2: string): number {
  const lum1 = getRelativeLuminance(hex1);
  const lum2 = getRelativeLuminance(hex2);
  const lighter = Math.max(lum1, lum2);
  const darker = Math.min(lum1, lum2);
  return (lighter + 0.05) / (darker + 0.05);
}

describe("DESIGN.md Color Contrast WCAG Compliance", () => {
  it("proves ink on paper passes the 4.5:1 text contrast ratio", () => {
    const ratio = getContrastRatio(TOKENS.ink, TOKENS.paper);
    // Expected ~ 14.7:1
    expect(ratio).toBeGreaterThanOrEqual(4.5);
  });

  it("proves white on gentian passes the 4.5:1 primary action contrast ratio", () => {
    const ratio = getContrastRatio(TOKENS.white, TOKENS.gentian);
    // Expected ~ 10.9:1
    expect(ratio).toBeGreaterThanOrEqual(4.5);
  });

  it("proves gentian on paper passes the 4.5:1 focus ring and link contrast ratio", () => {
    const ratio = getContrastRatio(TOKENS.gentian, TOKENS.paper);
    // Expected ~ 10.1:1
    expect(ratio).toBeGreaterThanOrEqual(4.5);
  });

  it("proves urgent triage color against paper passes the 3:1 graphical component ratio", () => {
    const ratio = getContrastRatio(TOKENS.urgent, TOKENS.paper);
    // Expected ~ 6.9:1
    expect(ratio).toBeGreaterThanOrEqual(3.0);
  });

  it("proves soon triage color against paper passes the 3:1 graphical component ratio", () => {
    const ratio = getContrastRatio(TOKENS.soon, TOKENS.paper);
    // Expected ~ 3.5:1
    expect(ratio).toBeGreaterThanOrEqual(3.0);
  });

  it("proves routine triage color against paper passes the 3:1 graphical component ratio", () => {
    const ratio = getContrastRatio(TOKENS.routine, TOKENS.paper);
    // Expected ~ 4.4:1
    expect(ratio).toBeGreaterThanOrEqual(3.0);
  });

  it("proves uncertain triage color against paper passes the 3:1 graphical component ratio", () => {
    const ratio = getContrastRatio(TOKENS.uncertain, TOKENS.paper);
    // Expected ~ 5.5:1
    expect(ratio).toBeGreaterThanOrEqual(3.0);
  });
});
