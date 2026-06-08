/**
 * Theme defaults + persistence (AC-13, FR-NAV-3).
 *
 * Asserts the dark/indigo default, that `applyTheme`/`initTheme` write the
 * `data-mode`/`data-theme` attributes onto the document root, and that both axes
 * round-trip through `localStorage` under `dkmv-mode`/`dkmv-skin`.
 */
import { beforeEach, describe, expect, it } from "vitest";

import {
  DEFAULT_MODE,
  DEFAULT_SKIN,
  MODE_STORAGE_KEY,
  SKIN_STORAGE_KEY,
  applyTheme,
  initTheme,
  loadMode,
  loadSkin,
} from "./theme";

beforeEach(() => {
  localStorage.clear();
  document.documentElement.removeAttribute("data-mode");
  document.documentElement.removeAttribute("data-theme");
});

describe("theme defaults", () => {
  it("defaults to dark + indigo", () => {
    expect(DEFAULT_MODE).toBe("dark");
    expect(DEFAULT_SKIN).toBe("indigo");
    expect(loadMode()).toBe("dark");
    expect(loadSkin()).toBe("indigo");
  });

  it("initTheme applies dark/indigo to the root on first boot", () => {
    const { mode, skin } = initTheme();
    expect(mode).toBe("dark");
    expect(skin).toBe("indigo");
    expect(document.documentElement.getAttribute("data-mode")).toBe("dark");
    expect(document.documentElement.getAttribute("data-theme")).toBe("indigo");
  });
});

describe("theme persistence", () => {
  it("persists both axes to localStorage under dkmv-mode / dkmv-skin", () => {
    applyTheme("light", "plum");
    expect(localStorage.getItem(MODE_STORAGE_KEY)).toBe("light");
    expect(localStorage.getItem(SKIN_STORAGE_KEY)).toBe("plum");
  });

  it("reloads the persisted choice over the default", () => {
    localStorage.setItem(MODE_STORAGE_KEY, "light");
    localStorage.setItem(SKIN_STORAGE_KEY, "rose");
    expect(loadMode()).toBe("light");
    expect(loadSkin()).toBe("rose");
    const { mode, skin } = initTheme();
    expect(mode).toBe("light");
    expect(skin).toBe("rose");
  });

  it("falls back to the default for an invalid stored value", () => {
    localStorage.setItem(MODE_STORAGE_KEY, "neon");
    localStorage.setItem(SKIN_STORAGE_KEY, "chartreuse");
    expect(loadMode()).toBe("dark");
    expect(loadSkin()).toBe("indigo");
  });
});
