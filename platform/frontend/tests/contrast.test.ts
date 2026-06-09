/**
 * AA-contrast audit over the ported design tokens (AC-10, NFR-A11Y-1 / INV-14,
 * DESIGN_FIDELITY §8 — "the a11y pass adds no token that fails AA").
 *
 * The axe render test (a11y.test.tsx) is the live-DOM contrast pass (AC-10's
 * mechanism). This test adds a **deterministic** numeric AA check over the
 * fixed-hex token pairs the a11y surfaces depend on: the primary accent button
 * (``--accent-fg`` on ``--accent``) and the amber "Approve & continue" decision-card
 * CTA (``--st-paused-fg`` on ``--st-paused``). It computes the WCAG contrast ratio
 * and asserts ≥ 4.5:1 (AA normal text), so a future token edit that breaks AA fails
 * here even where jsdom can't evaluate rendered CSS.
 *
 * The expected hex values are the PORTED token values from
 * ``src/styles/tokens.css`` (the single hex-permitted file). They live in this
 * ``tests/`` file (outside the ``src`` INV-14 no-hardcoded-hex grep) purely as the
 * audit's reference; the source of truth remains ``tokens.css`` — keep these in
 * sync if a token value changes. Pure computation, no DOM.
 */
import { describe, expect, it } from "vitest";

// The ported token values under audit (mirrored from src/styles/tokens.css — the
// only hex-permitted file; this tests/ file is outside the src INV-14 grep scope).
const TOKENS = {
  accent: "#ff6b4a",
  accentFg: "#2a0f06",
  stPaused: "#f5a623",
  stPausedFg: "#3a2600",
} as const;

/** sRGB hex → linearized relative luminance (WCAG 2.x relative-luminance formula). */
function luminance(hex: string): number {
  const h = hex.replace("#", "");
  const full =
    h.length === 3
      ? h
          .split("")
          .map((c) => c + c)
          .join("")
      : h;
  const channels = [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16) / 255);
  const lin = channels.map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2];
}

/** WCAG contrast ratio between two hex colors (1:1 … 21:1). */
function contrastRatio(a: string, b: string): number {
  const la = luminance(a);
  const lb = luminance(b);
  const [hi, lo] = la > lb ? [la, lb] : [lb, la];
  return (hi + 0.05) / (lo + 0.05);
}

const AA_NORMAL = 4.5;

describe("design tokens — AA contrast (INV-14 / AC-10)", () => {
  it("accent button foreground on the accent background meets AA", () => {
    // The primary "Run with …" / launch button: --accent-fg text on --accent.
    const ratio = contrastRatio(TOKENS.accentFg, TOKENS.accent);
    expect(ratio).toBeGreaterThanOrEqual(AA_NORMAL);
  });

  it("the amber 'Approve & continue' foreground meets AA on the paused surface", () => {
    // --st-paused-fg (dark amber text) on the --st-paused amber (decision-card CTA).
    const ratio = contrastRatio(TOKENS.stPausedFg, TOKENS.stPaused);
    expect(ratio).toBeGreaterThanOrEqual(AA_NORMAL);
  });
});
