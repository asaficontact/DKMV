/**
 * Screen 07 — Workflows viewer (read-only) (F12 / §5.8 FR-07-1v, §7.2, §7).
 * Built to the design prototype's **Screen F read-only subset**: a level-1 list
 * of every component + a pipeline-summary rail + the read-only "compiles to YAML"
 * peek. **No** form editor, task-editor drawer, templates, or "Test run"
 * authoring affordances (those are v1.1 — OUT of scope, ADR-P010 / N7).
 *
 * Data:
 *  - **List** — every component from `GET /workflows`: **built-in**
 *    (`plan/dev/qa/docs/ship`) **and registered** custom ones (AC-5). Each row is a
 *    selectable card (emoji, name, purpose, compact stage chain). A registered
 *    on-disk custom component appears here (the backend wires `project_root`).
 *  - **Detail** — selecting a component fetches `GET /workflows/{id}` and renders
 *    its {@link PipelineSummary} (stages / pauses / est. — AC-6) + {@link YamlView}
 *    (`component.yaml` + task text, read-only + the authoring-deferred note — AC-7).
 *
 * Mounted inside the global chrome ({@link AppLayout}) with the **Workflows** nav
 * active (the sidebar item navigates here — 3.6). No editing, no save, no "new
 * workflow" CTA. All color is token-driven (INV-14); state is icon + label.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import "./workflows.css";
import {
  type WorkflowDetail,
  type WorkflowSummary,
  getWorkflow,
  listWorkflows,
} from "../api/workflows";
import AppLayout from "../chrome/AppLayout";
import { ChevRightIcon, FlowIcon, PauseIcon } from "../components/icons";
import PipelineSummary from "../components/PipelineSummary";
import YamlView from "../components/YamlView";

type LoadPhase = "loading" | "ready" | "error";

/**
 * Presentation-only glyph per built-in workflow id (the small emoji on the card).
 * A *display* affordance keyed by the API-supplied id — NOT the workflow list
 * (which is fetched from `GET /workflows`). Unknown/custom ids fall back to a gear.
 */
const WORKFLOW_GLYPH: Record<string, string> = {
  plan: "🧭",
  dev: "🛠️",
  qa: "🔍",
  docs: "📝",
  ship: "🚀",
};

function glyphFor(id: string): string {
  return WORKFLOW_GLYPH[id] ?? "⚙️";
}

export interface WorkflowsProps {
  /** The connected repo slug (for the chrome). */
  repoSlug?: string;
}

export default function Workflows({ repoSlug = "" }: WorkflowsProps) {
  const [phase, setPhase] = useState<LoadPhase>("loading");
  const [workflows, setWorkflows] = useState<WorkflowSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<WorkflowDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const load = useCallback(async () => {
    try {
      const list = await listWorkflows();
      setWorkflows(list);
      setPhase("ready");
      // Default-select the first component so the rails are never blank.
      setSelectedId((prev) => prev ?? list[0]?.id ?? null);
    } catch {
      setPhase((prev) => (prev === "loading" ? "error" : prev));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Fetch the selected component's detail (summary + YAML) on selection change.
  useEffect(() => {
    if (selectedId == null) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    setDetailLoading(true);
    getWorkflow(selectedId)
      .then((d) => {
        if (!cancelled) setDetail(d);
      })
      .catch(() => {
        if (!cancelled) setDetail(null);
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  const selectedSummary = useMemo(
    () => workflows.find((w) => w.id === selectedId) ?? null,
    [workflows, selectedId],
  );

  return (
    <AppLayout
      repoSlug={repoSlug}
      title={`${repoSlug || "Workflows"} · Workflows`}
      activeNav="workflows"
      onRefresh={() => void load()}
    >
      {phase === "loading" && <LoadingState />}
      {phase === "error" && <ErrorState onRetry={() => void load()} />}
      {phase === "ready" && workflows.length === 0 && <WorkflowsEmpty />}
      {phase === "ready" && workflows.length > 0 && (
        <div className="workflows-screen">
          {/* level-1 list (built-in + registered) */}
          <div className="workflows-list" role="listbox" aria-label="Workflows">
            {workflows.map((wf) => (
              <WorkflowRow
                key={wf.id}
                workflow={wf}
                active={wf.id === selectedId}
                onSelect={() => setSelectedId(wf.id)}
              />
            ))}
          </div>

          {/* detail: pipeline summary rail + read-only YAML peek */}
          <div className="workflows-detail">
            {selectedSummary ? (
              <>
                <header className="workflows-detail-head">
                  <span className="workflows-detail-emoji" aria-hidden>
                    {glyphFor(selectedSummary.id)}
                  </span>
                  <span className="workflows-detail-meta">
                    <span className="workflows-detail-name">{selectedSummary.name}</span>
                    {selectedSummary.description && (
                      <span className="cap workflows-detail-purpose">
                        {selectedSummary.description}
                      </span>
                    )}
                  </span>
                  {!selectedSummary.is_builtin && (
                    <span className="badge badge-soft workflows-custom-badge">custom</span>
                  )}
                </header>

                <PipelineSummary workflow={selectedSummary} />

                {detailLoading && !detail ? (
                  <p className="cap workflows-yaml-loading">Loading YAML…</p>
                ) : (
                  <YamlView
                    componentYaml={detail?.component_yaml ?? null}
                    taskYaml={detail?.task_yaml ?? []}
                  />
                )}
              </>
            ) : (
              <p className="cap workflows-detail-empty">Select a workflow to view its pipeline.</p>
            )}
          </div>
        </div>
      )}
    </AppLayout>
  );
}

/** One selectable workflow card in the level-1 list (emoji, name, purpose, chain). */
function WorkflowRow({
  workflow,
  active,
  onSelect,
}: {
  workflow: WorkflowSummary;
  active: boolean;
  onSelect: () => void;
}) {
  const pauses = workflow.pause_count > 0;
  return (
    <button
      type="button"
      role="option"
      aria-selected={active}
      className={`workflow-row${active ? " is-active" : ""}`}
      onClick={onSelect}
      data-workflow={workflow.id}
    >
      <span className="workflow-row-head">
        <span className="workflow-row-emoji" aria-hidden>
          {glyphFor(workflow.id)}
        </span>
        <span className="workflow-row-name">{workflow.name}</span>
        {pauses && (
          <span className="badge workflow-row-pauses">
            <PauseIcon size={9} />
            {workflow.pause_count} pause{workflow.pause_count === 1 ? "" : "s"}
          </span>
        )}
      </span>
      {workflow.description && (
        <span className="cap workflow-row-purpose">{workflow.description}</span>
      )}
      {workflow.stages.length > 0 && (
        <span className="workflow-row-chain">
          {workflow.stages.map((stage, si) => (
            <span className="workflow-row-step" key={stage.index}>
              {si > 0 && <ChevRightIcon size={10} aria-hidden />}
              <span className="mono workflow-row-step-name">{stage.name}</span>
            </span>
          ))}
        </span>
      )}
    </button>
  );
}

/** Empty state — no components resolved (a fresh install before connect). */
function WorkflowsEmpty() {
  return (
    <div className="workflows-state">
      <FlowIcon size={32} />
      <h2 className="workflows-state-title">No workflows yet</h2>
      <p className="cap">
        Built-in workflows load automatically once the control plane is reachable.
      </p>
    </div>
  );
}

function LoadingState() {
  return (
    <div className="workflows-state">
      <div className="run-bar workflows-loading-bar" />
      <p className="cap">Loading workflows…</p>
    </div>
  );
}

function ErrorState({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="workflows-state" role="alert">
      <FlowIcon size={28} />
      <h2 className="workflows-state-title">Couldn&rsquo;t load workflows</h2>
      <p className="cap">We hit a snag reaching the control plane.</p>
      <button type="button" className="btn btn-soft" onClick={onRetry}>
        Try again
      </button>
    </div>
  );
}
