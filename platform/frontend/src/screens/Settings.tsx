/**
 * Screen Settings — run defaults, daily spend alert, preflight, GitHub (FR-SET-1, §5.9).
 * Built to the design prototype's `settings.jsx`: three (now four) sections inside
 * the global chrome —
 *
 *  - **Preflight** — the same standing checks as Connect (`GET /preflight`), each row
 *    an icon + label + state badge (icon + text, never color alone — INV-14/a11y).
 *  - **GitHub** — the connected account + active repo, with a **Switch repo** button
 *    routing back to Connect (`onSwitchRepo`).
 *  - **Defaults** — the editable run defaults (`GET/PUT /settings`): default agent,
 *    model, memory, timeout, and the optional budget/turn caps.
 *  - **Spend alert** — the daily spend-alert threshold (the prototype's "$25.00 / day").
 *
 * Editing a default and pressing **Save** `PUT`s `/settings`; the screen shows a
 * dirty/saved state and surfaces a §8.9 `validation_error` (per-field message) so a
 * bad value (out-of-bounds timeout, malformed memory) is corrected in place.
 *
 * All color is token-driven (INV-14); state is conveyed by icon + label.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import "./settings.css";
import { ApiError } from "../api/client";
import { getPreflight, type PreflightReport } from "../api/connect";
import {
  type RunDefaults,
  type RunDefaultsUpdate,
  getSettings,
  updateSettings,
} from "../api/settings";
import AppLayout from "../chrome/AppLayout";
import { CheckIcon, RefreshIcon } from "../components/icons";

type LoadPhase = "loading" | "ready" | "error";
type SaveState = "idle" | "saving" | "saved" | "error";

export interface SettingsProps {
  /** The connected repo slug ("owner/name") — shown in the chrome + GitHub section. */
  repoSlug?: string;
  /** Switch-repo affordance: routes back to Connect (FR-SET-1). */
  onSwitchRepo?: () => void;
  /** Test seam: start with given defaults (skip the GET). */
  initialDefaults?: RunDefaults;
  /** Test seam: start with a given preflight (skip the GET). */
  initialPreflight?: PreflightReport | null;
}

/** A per-field validation message keyed by the field name (from §8.9 details). */
type FieldErrors = Partial<Record<keyof RunDefaults, string>>;

export default function Settings({
  repoSlug = "",
  onSwitchRepo,
  initialDefaults,
  initialPreflight,
}: SettingsProps) {
  const [phase, setPhase] = useState<LoadPhase>(initialDefaults ? "ready" : "loading");
  const [defaults, setDefaults] = useState<RunDefaults | null>(initialDefaults ?? null);
  const [draft, setDraft] = useState<RunDefaults | null>(initialDefaults ?? null);
  const [preflight, setPreflight] = useState<PreflightReport | null>(initialPreflight ?? null);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [saveError, setSaveError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setPhase("loading");
    try {
      const [d, pf] = await Promise.all([getSettings(), getPreflight()]);
      setDefaults(d);
      setDraft(d);
      setPreflight(pf);
      setPhase("ready");
    } catch {
      setPhase("error");
    }
  }, []);

  useEffect(() => {
    if (!initialDefaults) void load();
  }, [initialDefaults, load]);

  const dirty = useMemo(
    () => Boolean(defaults && draft && !shallowEqual(defaults, draft)),
    [defaults, draft],
  );

  const setField = useCallback(
    <K extends keyof RunDefaults>(key: K, value: RunDefaults[K]) => {
      setDraft((prev) => (prev ? { ...prev, [key]: value } : prev));
      setSaveState("idle");
      setFieldErrors((prev) => {
        if (!(key in prev)) return prev;
        const next = { ...prev };
        delete next[key];
        return next;
      });
    },
    [],
  );

  const onSave = useCallback(async () => {
    if (!draft) return;
    setSaveState("saving");
    setSaveError(null);
    setFieldErrors({});
    try {
      const update: RunDefaultsUpdate = { ...draft };
      const saved = await updateSettings(update);
      setDefaults(saved);
      setDraft(saved);
      setSaveState("saved");
    } catch (err) {
      setSaveState("error");
      if (err instanceof ApiError && err.code === "validation_error") {
        setFieldErrors(fieldErrorsFromDetails(err.details));
        setSaveError("Some values are invalid — fix the highlighted fields.");
      } else {
        setSaveError(err instanceof Error ? err.message : "Could not save settings.");
      }
    }
  }, [draft]);

  return (
    <AppLayout repoSlug={repoSlug} title="Settings" activeNav="settings" onRefresh={load}>
      <div className="settings-screen">
        <div className="settings-wrap">
          <h1 className="settings-h1">Settings</h1>
          <p className="settings-sub">
            Run defaults, spend alert and sandbox preflight
            {repoSlug && (
              <>
                {" for "}
                <span className="mono settings-repo">{repoSlug}</span>
              </>
            )}
            .
          </p>

          {phase === "loading" && (
            <p className="cap settings-status" role="status">
              Loading settings…
            </p>
          )}
          {phase === "error" && (
            <div className="settings-error" role="alert">
              <span>Could not load settings.</span>
              <button type="button" className="btn btn-soft" onClick={load}>
                <RefreshIcon size={14} />
                Retry
              </button>
            </div>
          )}

          {phase === "ready" && draft && (
            <>
              <PreflightSection preflight={preflight} />

              <GitHubSection repoSlug={repoSlug} onSwitchRepo={onSwitchRepo} />

              <DefaultsSection
                draft={draft}
                fieldErrors={fieldErrors}
                onField={setField}
              />

              <SpendAlertSection
                draft={draft}
                fieldErrors={fieldErrors}
                onField={setField}
              />

              <SaveBar
                dirty={dirty}
                saveState={saveState}
                saveError={saveError}
                onSave={onSave}
              />
            </>
          )}
        </div>
      </div>
    </AppLayout>
  );
}

// ── Sections ─────────────────────────────────────────────────────────────────

function SettingsSection({
  title,
  sub,
  children,
}: {
  title: string;
  sub: string;
  children: React.ReactNode;
}) {
  return (
    <section className="card settings-section">
      <header className="settings-section-head">
        <h3 className="settings-section-title">{title}</h3>
        <p className="cap">{sub}</p>
      </header>
      {children}
    </section>
  );
}

function PreflightSection({ preflight }: { preflight: PreflightReport | null }) {
  const checks = preflight?.checks ?? [];
  return (
    <SettingsSection title="Preflight" sub="Everything DKMV needs before a run">
      {checks.length === 0 ? (
        <p className="cap settings-status">Preflight unavailable.</p>
      ) : (
        <ul className="settings-preflight">
          {checks.map((c) => (
            <li key={c.id} className="settings-preflight-row">
              <span
                className={`settings-preflight-ic${c.ok ? " is-ok" : " is-blocked"}`}
                aria-hidden
              >
                <CheckIcon size={15} />
              </span>
              <span className="settings-preflight-body">
                <span className="settings-preflight-label">{c.label}</span>
                <span className="mono cap">{c.sub}</span>
              </span>
              <span className={`state ${c.ok ? "s-done" : "s-failed"}`}>
                <span className="dot" />
                {c.ok ? "Ready" : "Blocked"}
              </span>
            </li>
          ))}
        </ul>
      )}
    </SettingsSection>
  );
}

function GitHubSection({
  repoSlug,
  onSwitchRepo,
}: {
  repoSlug: string;
  onSwitchRepo?: () => void;
}) {
  const owner = repoSlug.includes("/") ? repoSlug.split("/")[0] : repoSlug;
  return (
    <SettingsSection title="GitHub" sub="The connected account & active repository">
      <div className="settings-github">
        <span className="settings-github-meta">
          <span className="settings-github-name">{owner || "Not connected"}</span>
          <span className="cap">
            Connected · read issues, write <span className="mono">agent:*</span> labels
          </span>
        </span>
        <button
          type="button"
          className="btn btn-soft"
          onClick={onSwitchRepo}
          disabled={!onSwitchRepo}
        >
          <RefreshIcon size={14} />
          Switch repo
        </button>
      </div>
    </SettingsSection>
  );
}

interface FieldSectionProps {
  draft: RunDefaults;
  fieldErrors: FieldErrors;
  onField: <K extends keyof RunDefaults>(key: K, value: RunDefaults[K]) => void;
}

function DefaultsSection({ draft, fieldErrors, onField }: FieldSectionProps) {
  return (
    <SettingsSection title="Defaults" sub="Applied to new runs unless overridden">
      <div className="settings-grid">
        <DefField label="Default agent" error={fieldErrors.default_agent} htmlFor="set-agent">
          <select
            id="set-agent"
            className="input"
            value={draft.default_agent}
            onChange={(e) => onField("default_agent", e.target.value)}
          >
            <option value="claude">Claude</option>
            <option value="codex">Codex</option>
          </select>
        </DefField>

        <DefField label="Default model" error={fieldErrors.default_model} htmlFor="set-model">
          <input
            id="set-model"
            className="input mono"
            value={draft.default_model}
            onChange={(e) => onField("default_model", e.target.value)}
          />
        </DefField>

        <DefField label="Default memory" error={fieldErrors.default_memory} htmlFor="set-mem">
          <input
            id="set-mem"
            className="input mono"
            value={draft.default_memory}
            onChange={(e) => onField("default_memory", e.target.value)}
            placeholder="8g"
          />
        </DefField>

        <DefField
          label="Default timeout (min)"
          error={fieldErrors.default_timeout_minutes}
          htmlFor="set-timeout"
        >
          <input
            id="set-timeout"
            type="number"
            min={1}
            className="input mono"
            value={draft.default_timeout_minutes}
            onChange={(e) => onField("default_timeout_minutes", numberOr(e.target.value, 0))}
          />
        </DefField>

        <DefField
          label="Default budget (USD)"
          error={fieldErrors.default_max_budget_usd}
          htmlFor="set-budget"
          hint="Claude only — Codex is time-bounded, not cost-bounded"
        >
          <input
            id="set-budget"
            type="number"
            min={0}
            step="0.01"
            className="input mono"
            value={draft.default_max_budget_usd ?? ""}
            onChange={(e) => onField("default_max_budget_usd", optionalNumber(e.target.value))}
            placeholder="none"
          />
        </DefField>

        <DefField
          label="Default max turns"
          error={fieldErrors.default_max_turns}
          htmlFor="set-turns"
          hint="Claude only"
        >
          <input
            id="set-turns"
            type="number"
            min={0}
            className="input mono"
            value={draft.default_max_turns ?? ""}
            onChange={(e) => onField("default_max_turns", optionalNumber(e.target.value))}
            placeholder="none"
          />
        </DefField>
      </div>
    </SettingsSection>
  );
}

function SpendAlertSection({ draft, fieldErrors, onField }: FieldSectionProps) {
  return (
    <SettingsSection title="Spend alert" sub="Warn when the day's spend crosses a threshold">
      <div className="settings-grid">
        <DefField
          label="Alert at (USD / day)"
          error={fieldErrors.daily_spend_alert_usd}
          htmlFor="set-alert"
        >
          <input
            id="set-alert"
            type="number"
            min={0}
            step="0.01"
            className="input mono"
            value={draft.daily_spend_alert_usd}
            onChange={(e) => onField("daily_spend_alert_usd", numberOr(e.target.value, 0))}
          />
        </DefField>
      </div>
      <p className="cap settings-codex-note">
        Codex runs report no cost and are excluded from spend totals — the alert is a
        Claude-spend guardrail.
      </p>
    </SettingsSection>
  );
}

function DefField({
  label,
  htmlFor,
  hint,
  error,
  children,
}: {
  label: string;
  htmlFor: string;
  hint?: string;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="settings-field" htmlFor={htmlFor}>
      <span className="settings-field-label">{label}</span>
      {children}
      {hint && !error && <span className="cap settings-field-hint">{hint}</span>}
      {error && (
        <span className="settings-field-err" role="alert">
          {error}
        </span>
      )}
    </label>
  );
}

function SaveBar({
  dirty,
  saveState,
  saveError,
  onSave,
}: {
  dirty: boolean;
  saveState: SaveState;
  saveError: string | null;
  onSave: () => void;
}) {
  return (
    <div className="settings-savebar">
      <span className="cap settings-save-status" role="status">
        {saveState === "saving" && "Saving…"}
        {saveState === "saved" && !dirty && "Saved"}
        {saveState === "idle" && dirty && "Unsaved changes"}
        {saveState === "error" && saveError}
      </span>
      <button
        type="button"
        className="btn btn-primary"
        onClick={onSave}
        disabled={!dirty || saveState === "saving"}
      >
        {saveState === "saving" ? "Saving…" : "Save changes"}
      </button>
    </div>
  );
}

// ── helpers ──────────────────────────────────────────────────────────────────

function shallowEqual(a: RunDefaults, b: RunDefaults): boolean {
  return (Object.keys(a) as (keyof RunDefaults)[]).every((k) => a[k] === b[k]);
}

/** Parse a numeric input, falling back to `fallback` on an empty/NaN value. */
function numberOr(value: string, fallback: number): number {
  const n = Number(value);
  return value.trim() === "" || Number.isNaN(n) ? fallback : n;
}

/** Parse an optional numeric input: empty → null, else the number. */
function optionalNumber(value: string): number | null {
  if (value.trim() === "") return null;
  const n = Number(value);
  return Number.isNaN(n) ? null : n;
}

/** Map a §8.9 `details.fields` list to a per-field message (last loc segment). */
function fieldErrorsFromDetails(details: Record<string, unknown> | undefined): FieldErrors {
  const out: FieldErrors = {};
  const fields = details?.fields;
  if (!Array.isArray(fields)) return out;
  for (const f of fields) {
    if (typeof f !== "object" || f === null) continue;
    const entry = f as { loc?: unknown[]; msg?: unknown };
    const loc = Array.isArray(entry.loc) ? entry.loc : [];
    const key = loc.length > 0 ? String(loc[loc.length - 1]) : "";
    if (key && key in EMPTY_DEFAULTS) {
      out[key as keyof RunDefaults] = String(entry.msg ?? "Invalid value");
    }
  }
  return out;
}

/** A key-set sentinel so `fieldErrorsFromDetails` only keeps known field keys. */
const EMPTY_DEFAULTS: Record<keyof RunDefaults, true> = {
  default_agent: true,
  default_model: true,
  default_memory: true,
  default_timeout_minutes: true,
  default_max_budget_usd: true,
  default_max_turns: true,
  daily_spend_alert_usd: true,
};
