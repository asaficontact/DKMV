/**
 * Workflow picker (FR-03-2, AC-6). Renders one selectable card per workflow,
 * **populated from `GET /workflows`** (slice 4.1) — never a hardcoded list. Each
 * card shows an emoji, the name, the purpose, the stage chain (chevron-separated),
 * a **"pauses"** badge when the pipeline pauses, and the est. line.
 *
 * The workflow *data* (ids, names, agents, models, stages, est. total) all comes
 * from the API; the only local mapping is a small **presentation glyph** per id
 * (a display affordance, not the workflow list). AC-6 greps for `WORKFLOWS\s*=` —
 * there is no such constant here (the source of truth is the fetched array).
 *
 * All color is token-driven (the `wf-card` / `is-active` classes + the `--st-paused`
 * "pauses" badge); no hex (INV-14).
 */
import type { WorkflowSummary } from "../api/runs";
import { ChevRightIcon, PauseIcon } from "./icons";

/**
 * Presentation-only glyph per built-in workflow id (the small emoji on the card).
 * This is a *display* affordance keyed by the API-supplied id — NOT the workflow
 * list (which is fetched). Unknown/custom ids fall back to the gear glyph.
 */
const WORKFLOW_GLYPH: Record<string, string> = {
  plan: "🧭",
  dev: "🛠️",
  qa: "🔍",
  docs: "📝",
  ship: "🚀",
};

/** Format the est. total as a "$x" budget label, or null when unknown. */
export function formatBudget(estTotalUsd: number | null): string | null {
  if (estTotalUsd == null) return null;
  // Whole-dollar totals read cleaner without trailing zeros (~$12 vs ~$12.00).
  const rounded = Math.round(estTotalUsd * 100) / 100;
  return Number.isInteger(rounded) ? `~$${rounded}` : `~$${rounded.toFixed(2)}`;
}

export interface WorkflowPickerProps {
  /** The fetched workflow summaries (`GET /workflows`). */
  workflows: WorkflowSummary[];
  /** The currently-selected workflow id. */
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export default function WorkflowPicker({
  workflows,
  selectedId,
  onSelect,
}: WorkflowPickerProps) {
  if (workflows.length === 0) {
    return <p className="cap wf-empty">No workflows available.</p>;
  }
  return (
    <div className="wf-picker" role="radiogroup" aria-label="Workflow">
      {workflows.map((wf) => {
        const active = wf.id === selectedId;
        const pauses = wf.pause_count > 0;
        const budget = formatBudget(wf.est_total_usd);
        return (
          <button
            key={wf.id}
            type="button"
            role="radio"
            aria-checked={active}
            className={`wf-card${active ? " is-active" : ""}`}
            onClick={() => onSelect(wf.id)}
            data-workflow={wf.id}
          >
            <div className="wf-card-head">
              <span className="wf-emoji" aria-hidden>
                {WORKFLOW_GLYPH[wf.id] ?? "⚙️"}
              </span>
              <span className="wf-name">{wf.name}</span>
              {wf.description && <span className="cap wf-purpose">{wf.description}</span>}
              {pauses && (
                <span className="badge wf-pauses">
                  <PauseIcon size={9} />
                  pauses
                </span>
              )}
            </div>
            {wf.stages.length > 0 && (
              <div className="wf-stages">
                {wf.stages.map((stage, si) => (
                  <span className="wf-stage-step" key={stage.index}>
                    {si > 0 && (
                      <ChevRightIcon size={11} aria-hidden />
                    )}
                    <span className="mono wf-stage-name">{stage.name}</span>
                  </span>
                ))}
              </div>
            )}
            {budget && <div className="cap wf-est">Est. {budget}</div>}
          </button>
        );
      })}
    </div>
  );
}
