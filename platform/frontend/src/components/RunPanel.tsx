/**
 * The "Run this issue" panel (FR-03-2/3, AC-6/AC-7) — the right pane of the
 * issue-detail screen. It owns:
 *
 *   - the {@link WorkflowPicker} (cards from `GET /workflows`, slice 4.1);
 *   - the **agent** segmented control (`auto | claude | codex`) with model
 *     resolution: Auto shows "→ {model}" resolving to the workflow's default
 *     agent/model (engine-sourced — §6.1 drift; Codex default `gpt-5.4`);
 *   - the **branch** input (prefilled `dkmv/issue-{num}-{slug}`, editable, mono);
 *   - the collapsed **Advanced guardrails** (Max budget / Max turns / Timeout /
 *     Memory / Extra context);
 *   - the sticky footer (est. line + **Queue for later** + **Run with {…}**).
 *
 * **Capability-aware (INV-8 / R-10).** For a **Codex** resolved agent the Max
 * budget and Max turns fields are **hidden entirely** and the panel shows
 * "Codex runs are time-bounded, not cost-bounded." The API still enforces the
 * rejection (`400 unsupported_for_agent`); the UI never even sends those fields.
 *
 * **Launch (FR-03-3).** "Run with {Claude|Codex}" posts `POST /runs` with
 * `resolvedAgent = agent === "auto" ? workflow.agent : agent` and navigates to
 * the live run on success. An `ApiError` (e.g. `validation_error` from
 * `validate_agent_model`, or `unsupported_for_agent`) surfaces inline.
 *
 * All color is token-driven (INV-14); no model/agent constant is inlined — the
 * model strings come from the engine adapter defaults via the workflow API.
 */
import { useMemo, useState } from "react";

import { ApiError } from "../api/client";
import {
  type CreateRunRequest,
  type WorkflowSummary,
  createRun,
} from "../api/runs";
import { BranchIcon, ChevRightIcon, CoinIcon, PlayIcon, SparkleIcon } from "./icons";
import WorkflowPicker, { formatBudget } from "./WorkflowPicker";

/** The agent choices in the segmented control (FR-03-2). */
const AGENT_OPTIONS = ["auto", "claude", "codex"] as const;
type AgentChoice = (typeof AGENT_OPTIONS)[number];

/** Agents whose runs are bounded by timeout, not budget/turns (INV-8 / R-10). */
const TIME_BOUNDED_AGENT = "codex";

/** Display label for a resolved agent name (no model constants — names only). */
function agentLabel(agent: string | null): string {
  const a = (agent ?? "").toLowerCase();
  if (a === "codex") return "Codex";
  if (a === "claude") return "Claude";
  return "Claude";
}

/** Strip a model string to its short tail for the dense segmented-control caption. */
export function shortModel(model: string | null): string {
  if (!model) return "";
  return model.replace(/^claude-/, "").replace(/^gpt-/, "gpt-");
}

/**
 * Resolve each agent's default **model** from the fetched workflows (engine
 * adapter defaults surfaced via the API — §6.1 drift; never a hardcoded label).
 * A workflow whose `agent` is e.g. `codex` carries that agent's default `model`
 * (Codex default `gpt-5.4`). Returns a `{claude?, codex?}` map.
 */
export function deriveAgentModels(
  workflows: WorkflowSummary[],
): Record<string, string> {
  const out: Record<string, string> = {};
  for (const wf of workflows) {
    const agent = (wf.agent ?? "").toLowerCase();
    if (agent && wf.model && !(agent in out)) {
      out[agent] = wf.model;
    }
  }
  return out;
}

export interface RunPanelProps {
  issueNum: number;
  issueTitle: string;
  repo: string;
  /** The base branch caption ("Base main"). */
  baseBranch?: string;
  workflows: WorkflowSummary[];
  /** Navigate to the live run after a successful launch (routed by run id). */
  onLaunched: (runId: string) => void;
  /** "Queue for later" — leaves the issue queued without launching (FR-03-2). */
  onQueueForLater?: () => void;
}

/** Slugify the issue title into the branch suffix (`[a-z0-9-]`, first 3 words). */
function slugFromTitle(title: string): string {
  return title
    .toLowerCase()
    .split(/\s+/)
    .slice(0, 3)
    .join("-")
    .replace(/[^a-z0-9-]/g, "");
}

export default function RunPanel({
  issueNum,
  issueTitle,
  repo,
  baseBranch = "main",
  workflows,
  onLaunched,
  onQueueForLater,
}: RunPanelProps) {
  const [selectedId, setSelectedId] = useState<string | null>(
    () => workflows[0]?.id ?? null,
  );
  const [agent, setAgent] = useState<AgentChoice>("auto");
  const [branch, setBranch] = useState(
    () => `dkmv/issue-${issueNum}-${slugFromTitle(issueTitle)}`,
  );
  const [advanced, setAdvanced] = useState(false);
  const [maxBudget, setMaxBudget] = useState("");
  const [maxTurns, setMaxTurns] = useState("");
  const [timeout, setTimeout] = useState("");
  const [memory, setMemory] = useState("8g");
  const [context, setContext] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const workflow = useMemo(
    () => workflows.find((w) => w.id === selectedId) ?? null,
    [workflows, selectedId],
  );
  const agentModels = useMemo(() => deriveAgentModels(workflows), [workflows]);

  // resolvedAgent = agent === "auto" ? workflow.agent : agent (FR-03-3).
  const resolvedAgent = useMemo(() => {
    if (agent === "auto") return (workflow?.agent ?? "claude").toLowerCase();
    return agent;
  }, [agent, workflow]);

  // The model the resolved agent will use: the workflow's model for Auto, else
  // the explicit agent's engine default (from the API — never a hardcoded label).
  const resolvedModel = useMemo(() => {
    if (agent === "auto") return workflow?.model ?? agentModels[resolvedAgent] ?? null;
    return agentModels[agent] ?? null;
  }, [agent, workflow, agentModels, resolvedAgent]);

  const isCodex = resolvedAgent === TIME_BOUNDED_AGENT;

  async function onLaunch() {
    if (!workflow) {
      setError("Pick a workflow first.");
      return;
    }
    setSubmitting(true);
    setError(null);
    const contextPaths = context
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    const body: CreateRunRequest = {
      issue_num: issueNum,
      repo,
      workflow_id: workflow.id,
      // Send the resolved agent (FR-03-3): the backend re-validates + re-resolves.
      agent: resolvedAgent,
      branch: branch.trim(),
      feature_name: slugFromTitle(issueTitle) || `issue-${issueNum}`,
      memory: memory.trim() || undefined,
      context: contextPaths,
    };
    // INV-8: never send budget/turns for a Codex run (the fields are hidden). For
    // Claude, pass them only when the operator set a value.
    if (!isCodex) {
      const budget = parseFloat(maxBudget);
      if (!Number.isNaN(budget)) body.max_budget_usd = budget;
      const turns = parseInt(maxTurns, 10);
      if (!Number.isNaN(turns)) body.max_turns = turns;
    }
    const to = parseInt(timeout, 10);
    if (!Number.isNaN(to)) body.timeout_minutes = to;

    try {
      const res = await createRun(body);
      onLaunched(res.run_id);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message || err.code);
      } else {
        setError("Could not start the run. Please try again.");
      }
      setSubmitting(false);
    }
  }

  const budgetLabel = workflow ? formatBudget(workflow.est_total_usd) : null;
  const pauses = (workflow?.pause_count ?? 0) > 0;

  return (
    <aside className="run-panel" aria-label="Run this issue">
      <div className="run-panel-head">
        <div className="run-panel-title-row">
          <PlayIcon size={17} />
          <h2 className="run-panel-title">Run this issue</h2>
        </div>
        <p className="run-panel-sub">
          Pick a workflow and let&rsquo;s go. You can change everything later.
        </p>
      </div>
      <hr className="run-panel-divider" />

      <div className="run-panel-body">
        {/* Workflow */}
        <Field label="Workflow" hint="What pipeline should the agent run?">
          <WorkflowPicker
            workflows={workflows}
            selectedId={selectedId}
            onSelect={setSelectedId}
          />
        </Field>

        {/* Agent */}
        <Field label="Agent" hint="Auto picks the workflow&rsquo;s default.">
          <div className="agent-seg" role="radiogroup" aria-label="Agent">
            {AGENT_OPTIONS.map((a) => {
              const active = agent === a;
              const caption =
                a === "auto"
                  ? `→ ${shortModel(workflow?.model ?? null)}`
                  : shortModel(agentModels[a] ?? null);
              return (
                <button
                  key={a}
                  type="button"
                  role="radio"
                  aria-checked={active}
                  className={`agent-seg-btn${active ? " is-active" : ""}`}
                  onClick={() => setAgent(a)}
                  data-agent={a}
                >
                  <span className="agent-seg-name">
                    {a === "auto" ? (
                      <>
                        <SparkleIcon size={12} /> Auto
                      </>
                    ) : (
                      agentLabel(a)
                    )}
                  </span>
                  <span className="mono agent-seg-model">{caption}</span>
                </button>
              );
            })}
          </div>
        </Field>

        {/* Branch */}
        <Field
          label="Branch"
          hint={
            <>
              Base <span className="mono">{baseBranch}</span>
            </>
          }
        >
          <div className="branch-input">
            <BranchIcon size={14} aria-hidden />
            <input
              className="input mono branch-field"
              aria-label="Branch name"
              value={branch}
              onChange={(e) => setBranch(e.target.value)}
            />
          </div>
        </Field>

        {/* Advanced guardrails */}
        <div className="advanced">
          <button
            type="button"
            className="advanced-toggle"
            aria-expanded={advanced}
            onClick={() => setAdvanced((a) => !a)}
          >
            <ChevRightIcon
              size={14}
              className={advanced ? "advanced-chev is-open" : "advanced-chev"}
            />
            Advanced guardrails
          </button>
          {advanced && (
            <div className="advanced-grid fade-in">
              {/* INV-8: Max budget + Max turns are Claude-only — hidden for Codex. */}
              {!isCodex && (
                <>
                  <MiniField label="Max budget ($)">
                    <input
                      className="input mono"
                      aria-label="Max budget"
                      inputMode="decimal"
                      placeholder={budgetLabel ? budgetLabel.replace(/[~$]/g, "") : ""}
                      value={maxBudget}
                      onChange={(e) => setMaxBudget(e.target.value)}
                    />
                  </MiniField>
                  <MiniField label="Max turns">
                    <input
                      className="input mono"
                      aria-label="Max turns"
                      inputMode="numeric"
                      value={maxTurns}
                      onChange={(e) => setMaxTurns(e.target.value)}
                    />
                  </MiniField>
                </>
              )}
              {isCodex && (
                <p className="cap advanced-codex-note" data-testid="codex-time-bounded">
                  Codex runs are time-bounded, not cost-bounded.
                </p>
              )}
              <MiniField label="Timeout (min)">
                <input
                  className="input mono"
                  aria-label="Timeout in minutes"
                  inputMode="numeric"
                  value={timeout}
                  onChange={(e) => setTimeout(e.target.value)}
                />
              </MiniField>
              <MiniField label="Memory">
                <input
                  className="input mono"
                  aria-label="Memory limit"
                  value={memory}
                  onChange={(e) => setMemory(e.target.value)}
                />
              </MiniField>
              <div className="advanced-wide">
                <MiniField label="Extra context files">
                  <input
                    className="input mono"
                    aria-label="Extra context files"
                    placeholder="impl_docs/, ARCHITECTURE.md"
                    value={context}
                    onChange={(e) => setContext(e.target.value)}
                  />
                </MiniField>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Sticky footer */}
      <div className="run-panel-foot">
        {error && (
          <p className="run-panel-error" role="alert">
            {error}
          </p>
        )}
        <div className="run-est">
          <CoinIcon size={15} />
          <span className="run-est-text">
            Est. <strong className="mono">{budgetLabel ?? "—"}</strong>
            {pauses && (
              <>
                {" · "}
                <span className="run-est-pauses">pauses once for you</span>
              </>
            )}
          </span>
        </div>
        <div className="run-panel-actions">
          <button
            type="button"
            className="btn btn-soft run-queue-btn"
            onClick={onQueueForLater}
            disabled={!onQueueForLater}
          >
            Queue for later
          </button>
          <button
            type="button"
            className="btn btn-primary run-go-btn"
            onClick={() => void onLaunch()}
            disabled={submitting || !workflow}
          >
            <PlayIcon size={16} />
            Run with {agentLabel(resolvedAgent)}
          </button>
        </div>
        {resolvedModel && (
          <p className="cap run-resolved-model mono" data-testid="resolved-model">
            {resolvedAgent} · {resolvedModel}
          </p>
        )}
      </div>
    </aside>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="run-field">
      <div className="run-field-head">
        <span className="run-field-label">{label}</span>
        {hint && <span className="cap">{hint}</span>}
      </div>
      {children}
    </div>
  );
}

function MiniField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="mini-field">
      <span className="cap mini-field-label">{label}</span>
      {children}
    </label>
  );
}
