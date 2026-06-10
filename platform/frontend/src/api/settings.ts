/**
 * Settings API surface (Screen Settings / FR-SET-1 — §5.9). Thin typed wrappers
 * over the generic {@link apiGet} / {@link apiPut} client for the **run defaults**
 * the Settings screen edits:
 *
 *   - `GET /settings`  — the current run-default view ({@link RunDefaults}), filled
 *     from the persisted overrides or the config/engine defaults.
 *   - `PUT /settings`  — persist a (partial) update; returns the new view.
 *
 * **No secret.** This surface carries ONLY non-secret run-shaping defaults (agent /
 * model / memory / timeout / budget / turns / the daily spend-alert threshold) — the
 * GitHub PAT and model keys are managed via the encrypted secret store / Connect
 * flow, never round-tripped through here.
 *
 * **INV-1 / INV-2.** Plain authed JSON over {@link apiGet} / {@link apiPut} (the
 * loopback token rides the `Authorization` header; the state-changing `PUT` passes
 * the JSON-only CSRF gate). No token is ever placed in a URL/query.
 */
import { apiGet, apiPut } from "./client";

/** The `GET /settings` view + the `PUT /settings` body shape (FR-SET-1). */
export interface RunDefaults {
  /** Default agent for new runs (`claude` | `codex`). */
  default_agent: string;
  /** Default model id for new runs. */
  default_model: string;
  /** Default container memory limit (e.g. `8g`). */
  default_memory: string;
  /** Default run timeout in minutes. */
  default_timeout_minutes: number;
  /** Default USD budget cap (budget-capable agents); null = none. */
  default_max_budget_usd: number | null;
  /** Default turn cap (turn-capable agents); null = none. */
  default_max_turns: number | null;
  /** Daily spend-alert threshold in USD (the §5.9 "$25.00 / day"). */
  daily_spend_alert_usd: number;
}

/** A partial Settings update — any omitted field keeps its current value. */
export type RunDefaultsUpdate = Partial<RunDefaults>;

/** Fetch the current run defaults (`GET /settings`). */
export function getSettings(): Promise<RunDefaults> {
  return apiGet<RunDefaults>("/settings");
}

/**
 * Persist a (partial) run-defaults update (`PUT /settings`). Returns the new view.
 * An invalid value surfaces as an {@link import("./client").ApiError} carrying
 * `validation_error` (§8.9), with `details.fields` mapping the error to its input.
 */
export function updateSettings(update: RunDefaultsUpdate): Promise<RunDefaults> {
  return apiPut<RunDefaults>("/settings", update);
}
