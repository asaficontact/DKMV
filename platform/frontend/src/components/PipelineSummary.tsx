/**
 * Pipeline summary rail (Screen F summary rail — F12 / §7.2 FR-07-2). For the
 * selected component it renders the **ordered stages** (each with its per-stage
 * budget + a pause marker), and a footer with the **Stages** count, **Pause
 * points** count, and the **Est. total budget**.
 *
 * Authoritative `qa` render (FR-07-2): **3 stages (Evaluate → Fix → Re-evaluate),
 * 1 pause (after Evaluate), $2.00 total**. The $2.00 component-level
 * `max_budget_usd` is the authoritative total; per-stage splits are illustrative.
 *
 * **A11y (INV-14 / §7.3).** State is conveyed by **icon + label**, never color
 * alone: each stage shows a numbered step glyph + its name; a stage that pauses
 * after carries a `PauseIcon` **and** a "pauses after" text marker. The numeric
 * cells (budgets + est. total) use the mono / `tnum` style (`.mono`). No hex —
 * all color is token-driven (INV-14).
 *
 * This is a **read-only viewer** component: it renders the configured pipeline
 * shape, not a live run's status (that is the `StageTracker`). No editing.
 */
import type { WorkflowSummary } from "../api/workflows";
import { PauseIcon } from "./icons";

/** Format a per-stage / total budget as "$x.xx", or null when unknown. */
export function formatUsd(usd: number | null): string | null {
  if (usd == null) return null;
  return `$${usd.toFixed(2)}`;
}

export interface PipelineSummaryProps {
  /** The selected component's summary (`GET /workflows` entry). */
  workflow: WorkflowSummary;
}

/**
 * Render the ordered-stage rail + the stats footer for one component.
 */
export default function PipelineSummary({ workflow }: PipelineSummaryProps) {
  const estTotal = formatUsd(workflow.est_total_usd);
  return (
    <section className="pipeline-summary" aria-label="Pipeline summary">
      <h3 className="pipeline-summary-title cap">Pipeline</h3>

      <ol className="pipeline-stages">
        {workflow.stages.map((stage) => {
          const budget = formatUsd(stage.budget_usd);
          return (
            <li className="pipeline-stage" key={stage.index} data-stage={stage.name}>
              <span className="pipeline-stage-num mono" aria-hidden>
                {stage.index + 1}
              </span>
              <span className="pipeline-stage-body">
                <span className="pipeline-stage-name">{stage.name}</span>
                {stage.description && (
                  <span className="cap pipeline-stage-desc">{stage.description}</span>
                )}
                {stage.pause_after && (
                  <span className="badge pipeline-stage-pause" data-testid="stage-pause">
                    <PauseIcon size={9} />
                    pauses after
                  </span>
                )}
              </span>
              <span className="mono pipeline-stage-budget" data-testid="stage-budget">
                {budget ?? "—"}
              </span>
            </li>
          );
        })}
      </ol>

      <dl className="pipeline-stats">
        <div className="pipeline-stat">
          <dt className="cap">Stages</dt>
          <dd className="mono" data-testid="stage-count">
            {workflow.stage_count}
          </dd>
        </div>
        <div className="pipeline-stat">
          <dt className="cap">Pause points</dt>
          <dd className="mono" data-testid="pause-count">
            {workflow.pause_count}
          </dd>
        </div>
        <div className="pipeline-stat">
          <dt className="cap">Est. total budget</dt>
          <dd className="mono" data-testid="est-total">
            {estTotal ?? "—"}
          </dd>
        </div>
      </dl>
    </section>
  );
}
