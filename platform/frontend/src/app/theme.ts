/**
 * Theme axes + persistence (FR-NAV-3, §7.1 — INV-14).
 *
 * The design system has two orthogonal axes, both driven by data-attributes on
 * the document root and resolved entirely in CSS (ported from `styles.css`):
 *
 *   - `data-mode`  = "dark" | "light"  (surface lightness)
 *   - `data-theme` = one of SKINS       (accent + neutral tint)
 *
 * The **default** is dark + indigo (the brand default per §7.1). Both axes are
 * persisted to `localStorage` under `dkmv-mode` / `dkmv-skin` so a reload keeps
 * the operator's choice. No hex lives here — every color is a CSS variable
 * resolved by `tokens.css` from these attributes (INV-14). This module only sets
 * the *attributes*; it never reads or writes a color value.
 */

export type Mode = "dark" | "light";
export type Skin = "ember" | "indigo" | "evergreen" | "graphite" | "plum" | "rose";

/** The six selectable skins (§7.1). Order is the picker order. */
export const SKINS: readonly Skin[] = [
  "indigo",
  "ember",
  "evergreen",
  "graphite",
  "plum",
  "rose",
] as const;

/** Brand defaults (§7.1): dark surface + indigo accent. */
export const DEFAULT_MODE: Mode = "dark";
export const DEFAULT_SKIN: Skin = "indigo";

/** localStorage keys (AC-13 greps for these literals). */
export const MODE_STORAGE_KEY = "dkmv-mode";
export const SKIN_STORAGE_KEY = "dkmv-skin";

const MODES: readonly Mode[] = ["dark", "light"];

function isMode(value: string | null): value is Mode {
  return value !== null && (MODES as readonly string[]).includes(value);
}

function isSkin(value: string | null): value is Skin {
  return value !== null && (SKINS as readonly string[]).includes(value);
}

/** Safe localStorage read — tolerates a disabled/throwing store (SSR/tests). */
function readStored(key: string): string | null {
  try {
    return globalThis.localStorage?.getItem(key) ?? null;
  } catch {
    return null;
  }
}

/** Safe localStorage write — never throws into the render path. */
function writeStored(key: string, value: string): void {
  try {
    globalThis.localStorage?.setItem(key, value);
  } catch {
    /* storage disabled — theme still applies in-memory via the attribute */
  }
}

/** The persisted mode, or the dark default when unset/invalid. */
export function loadMode(): Mode {
  const stored = readStored(MODE_STORAGE_KEY);
  return isMode(stored) ? stored : DEFAULT_MODE;
}

/** The persisted skin, or the indigo default when unset/invalid. */
export function loadSkin(): Skin {
  const stored = readStored(SKIN_STORAGE_KEY);
  return isSkin(stored) ? stored : DEFAULT_SKIN;
}

/**
 * Write `data-mode` / `data-theme` onto the document root so `tokens.css`
 * re-skins everything, and persist both to localStorage. Idempotent.
 */
export function applyTheme(mode: Mode, skin: Skin): void {
  const root = globalThis.document?.documentElement;
  if (root) {
    root.setAttribute("data-mode", mode);
    root.setAttribute("data-theme", skin);
  }
  writeStored(MODE_STORAGE_KEY, mode);
  writeStored(SKIN_STORAGE_KEY, skin);
}

/**
 * Apply the persisted (or default dark/indigo) theme at boot. Call once before
 * the first render so the very first paint is correctly themed.
 */
export function initTheme(): { mode: Mode; skin: Skin } {
  const mode = loadMode();
  const skin = loadSkin();
  applyTheme(mode, skin);
  return { mode, skin };
}
