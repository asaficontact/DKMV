/**
 * Vitest setup — jest-dom matchers + per-test cleanup.
 *
 * Imported via `vite.config.ts` `test.setupFiles`. Registers the
 * `@testing-library/jest-dom` matchers (`toBeInTheDocument`, …) and tears down
 * the rendered DOM + localStorage between tests so theme-persistence tests start
 * from a clean store.
 */
import "@testing-library/jest-dom/vitest";
// Register the vitest-axe accessibility matcher (`toHaveNoViolations`) for the
// slice-5.3 axe render test (AC-10). The extend-expect entry augments the global
// `expect` and the `Vi.Assertion` type.
import "vitest-axe/extend-expect";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => {
  cleanup();
  try {
    globalThis.localStorage?.clear();
  } catch {
    /* storage disabled in this env — nothing to clear */
  }
});
