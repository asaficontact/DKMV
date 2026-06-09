/**
 * React seam over the `theme.ts` data layer (FR-NAV-3 / §7.1). `theme.ts` owns
 * the persistence + attribute-writing; this hook holds the current `(mode, skin)`
 * in React state and re-applies on change so the TopBar theme toggle + skin
 * picker re-render. Defaults are dark + indigo (AC-13); no color lives here — the
 * hook only sets data-attributes via `applyTheme` (INV-14).
 */
import { useCallback, useState } from "react";

import { applyTheme, loadMode, loadSkin, type Mode, type Skin } from "./theme";

export interface ThemeController {
  mode: Mode;
  skin: Skin;
  toggleMode: () => void;
  setSkin: (skin: Skin) => void;
}

export function useTheme(): ThemeController {
  const [mode, setMode] = useState<Mode>(() => loadMode());
  const [skin, setSkinState] = useState<Skin>(() => loadSkin());

  const toggleMode = useCallback(() => {
    setMode((prev) => {
      const next: Mode = prev === "dark" ? "light" : "dark";
      applyTheme(next, loadSkin());
      return next;
    });
  }, []);

  const setSkin = useCallback((next: Skin) => {
    setSkinState(next);
    applyTheme(loadMode(), next);
  }, []);

  return { mode, skin, toggleMode, setSkin };
}
