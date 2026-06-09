/**
 * RunGuardrails — the capability-aware **cost guardrails** of the run panel
 * (INV-8 / ADR-P009, NFR-COST-1, §7.2; AC-9 / R-10).
 *
 * The single place the launch panel renders the budget/turn caps, branching on
 * the resolved agent's cost capability:
 *
 *   - **Claude** (budget-capable): the **Max budget ($)** + **Max turns** inputs
 *     are shown (the API enforces them as hard caps).
 *   - **Codex** (timeout-only): those fields are **hidden entirely** and the panel
 *     states "Codex runs are time-bounded, not cost-bounded." The API still
 *     rejects a budget/turn body with `400 unsupported_for_agent`; the UI simply
 *     never offers — or sends — those fields for Codex.
 *
 * The **Timeout (min)** field is always shown — it is the universal guardrail and
 * Codex's *only* runtime bound (with a tighter server-side default). All color is
 * token-driven (INV-14); this component adds **no** color literal.
 */

/** The exact AC-9 copy: a Codex run's only guardrail is wall-clock time. */
export const CODEX_TIME_BOUNDED_COPY =
  "Codex runs are time-bounded, not cost-bounded.";

export interface RunGuardrailsProps {
  /** Whether the resolved agent is Codex (timeout-only — hides budget/turns). */
  isCodex: boolean;
  /** Max-budget input value (controlled). */
  maxBudget: string;
  onMaxBudgetChange: (value: string) => void;
  /** Placeholder for the budget input (e.g. the workflow's estimate), if any. */
  budgetPlaceholder?: string;
  /** Max-turns input value (controlled). */
  maxTurns: string;
  onMaxTurnsChange: (value: string) => void;
  /** Timeout (minutes) input value (controlled) — always shown. */
  timeout: string;
  onTimeoutChange: (value: string) => void;
}

/** A labeled mini-field (mirrors the run-panel advanced grid). */
function MiniField({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="mini-field">
      <span className="cap mini-field-label">{label}</span>
      {children}
    </label>
  );
}

export default function RunGuardrails({
  isCodex,
  maxBudget,
  onMaxBudgetChange,
  budgetPlaceholder,
  maxTurns,
  onMaxTurnsChange,
  timeout,
  onTimeoutChange,
}: RunGuardrailsProps) {
  return (
    <>
      {/* INV-8: Max budget + Max turns are Claude-only — hidden for Codex. */}
      {!isCodex && (
        <>
          <MiniField label="Max budget ($)">
            <input
              className="input mono"
              aria-label="Max budget"
              inputMode="decimal"
              placeholder={budgetPlaceholder ?? ""}
              value={maxBudget}
              onChange={(e) => onMaxBudgetChange(e.target.value)}
            />
          </MiniField>
          <MiniField label="Max turns">
            <input
              className="input mono"
              aria-label="Max turns"
              inputMode="numeric"
              value={maxTurns}
              onChange={(e) => onMaxTurnsChange(e.target.value)}
            />
          </MiniField>
        </>
      )}
      {isCodex && (
        <p className="cap advanced-codex-note" data-testid="codex-time-bounded">
          {CODEX_TIME_BOUNDED_COPY}
        </p>
      )}
      {/* Timeout is the universal guardrail — Codex's only runtime bound. */}
      <MiniField label="Timeout (min)">
        <input
          className="input mono"
          aria-label="Timeout in minutes"
          inputMode="numeric"
          value={timeout}
          onChange={(e) => onTimeoutChange(e.target.value)}
        />
      </MiniField>
    </>
  );
}
