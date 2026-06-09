/**
 * Human-in-the-loop decision card (Screen 05 — `run.jsx PauseCard`, FR-05 / §5.6).
 * Built to the prototype **but to the ENGINE-authoritative option shape** (§6.1).
 *
 * The amber card renders when a run pauses: a `PAUSED · after {task_name}` badge,
 * the `PauseQuestion.question`, the `context.summary`, and the options as radio
 * rows. **Critically (AC-19):**
 *
 *  - Options use the engine shape `{value, label, description?}` — NOT the
 *    `data.jsx PAUSE_REQUEST` `{label, description}` mock. The row displays `label`
 *    (bold) + optional `description`; the underlying choice is the option's
 *    **`value`**.
 *  - The **recommended** marker tracks the option whose **`value === default`**
 *    (NOT label-matching) — `default` matches an option's value (§6.1).
 *  - **Approve & continue** posts `{answers:{question_id: <chosen option VALUE>},
 *    skip_remaining:false}` — the chosen **value**, never the label.
 *  - **Ship as-is** and **Abort** set `skip_remaining:true`.
 *
 * **Standalone (this slice).** This component owns no layout slot — `LiveRun.tsx`
 * (slice 2.4) renders a slot for it; mounting this card into that slot is a
 * documented POST-MERGE integration step (this slice does not edit `LiveRun.tsx`).
 *
 * **No hardcoded hex (INV-14).** All color comes from the ported tokens
 * (`--st-paused`, `--st-paused-fg`, `--st-failed`, `--surface`, `--border`, …) via
 * `var()` / `color-mix()`; state is conveyed by **icon + label**, not color alone
 * (NFR-A11Y-1). Honest scope (§8.5.5): the copy never over-claims in-place run
 * recovery — it states the decision steers the run forward from here.
 */
import { useState } from "react";

import { apiPost } from "../api/client";
import { CheckIcon, PauseIcon } from "./icons";

/** One engine-authoritative option: `{value, label, description?}` (§6.1). */
export interface PauseOption {
  /** The choice value the engine stores as the question's `user_answer`. */
  value: string;
  /** The human-readable option label (bold row title). */
  label: string;
  /** Optional supporting description (sub-text). */
  description?: string;
}

/** One pause question (`dkmv/tasks/pause.py PauseQuestion`). */
export interface PauseQuestion {
  id: string;
  question: string;
  options: PauseOption[];
  /** Matches an option's `value`; that option is marked "recommended". */
  default: string | null;
}

/** The engine `PauseRequest` the card renders (§6.1 / §5.6). */
export interface PauseRequest {
  task_name: string;
  questions: PauseQuestion[];
  context: { summary?: string } & Record<string, string>;
}

/** The `POST /runs/{id}/answer` body (§8.5 `PauseResponse` shape). */
export interface AnswerBody {
  /** question_id → chosen option **value** (the engine value, not the label). */
  answers: Record<string, string>;
  /** Skip the remaining workflow (Ship-as-is / Abort). */
  skip_remaining: boolean;
}

export interface PauseCardProps {
  /** Platform UUID of the paused run (the `POST /runs/{id}/answer` target). */
  runId: string;
  /** The engine pause request to render. */
  request: PauseRequest;
  /**
   * Optional submit override (tests inject a spy; defaults to the real
   * `POST /runs/{id}/answer`). Receives the run id + the answer body.
   */
  onSubmit?: (runId: string, body: AnswerBody) => Promise<unknown>;
  /** Called after a successful answer (the parent re-fetches / hides the card). */
  onAnswered?: (body: AnswerBody) => void;
}

const paneBg = "color-mix(in oklab, var(--st-paused) 9%, var(--surface))";
const paneBorder = "color-mix(in oklab, var(--st-paused) 45%, transparent)";

/** Default submit: `POST /runs/{id}/answer` (CSRF-safe JSON via {@link apiPost}). */
async function postAnswer(runId: string, body: AnswerBody): Promise<{ resolved: boolean }> {
  return apiPost<{ resolved: boolean }>(`/runs/${encodeURIComponent(runId)}/answer`, body);
}

/**
 * Render the decision card. The first question drives the radio rows (the engine
 * built-ins author one question per pause); `skip_remaining` actions (Ship as-is /
 * Abort) bypass the selection.
 */
export default function PauseCard({ runId, request, onSubmit, onAnswered }: PauseCardProps) {
  const question = request.questions[0];
  // Track the chosen VALUE (not the label). Default to the recommended option's
  // value (`value === default`), else the first option's value.
  const [choice, setChoice] = useState<string>(
    question?.default ?? question?.options[0]?.value ?? "",
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = onSubmit ?? postAnswer;

  async function send(body: AnswerBody): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      await submit(runId, body);
      onAnswered?.(body);
    } catch {
      setError("Could not submit your decision. It may already be resolved — refresh.");
    } finally {
      setBusy(false);
    }
  }

  if (!question) {
    return null;
  }

  return (
    <div
      className="fade-in pause-card"
      role="group"
      aria-label="Decision required"
      style={{
        margin: "18px 0 4px",
        flex: "none",
        borderRadius: "var(--r-lg)",
        border: `1px solid ${paneBorder}`,
        background: paneBg,
        overflow: "hidden",
        boxShadow: "var(--shadow-md)",
      }}
    >
      <div style={{ padding: "16px 20px 14px", display: "flex", gap: 13, alignItems: "flex-start" }}>
        <span
          aria-hidden
          style={{
            width: 38,
            height: 38,
            borderRadius: 11,
            background: "color-mix(in oklab, var(--st-paused) 20%, transparent)",
            color: "var(--st-paused)",
            display: "grid",
            placeItems: "center",
            flex: "none",
          }}
        >
          <PauseIcon size={18} />
        </span>
        <div style={{ flex: 1 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
            <span
              className="badge"
              style={{
                background: "color-mix(in oklab, var(--st-paused) 18%, transparent)",
                color: "var(--st-paused)",
                fontSize: 10.5,
              }}
            >
              PAUSED · after {request.task_name}
            </span>
            <span className="cap">This run needs your decision to continue</span>
          </div>
          <h3
            style={{
              margin: "2px 0 4px",
              fontSize: 16.5,
              fontWeight: 800,
              letterSpacing: "-.01em",
              lineHeight: 1.35,
            }}
          >
            {question.question}
          </h3>
          {request.context.summary && (
            <p style={{ margin: 0, fontSize: 13, color: "var(--text-2)", lineHeight: 1.5 }}>
              {request.context.summary}
            </p>
          )}
        </div>
      </div>

      <div
        role="radiogroup"
        aria-label={question.question}
        style={{ padding: "0 20px 14px", display: "flex", flexDirection: "column", gap: 8 }}
      >
        {question.options.map((option) => {
          const active = choice === option.value;
          // Recommended = the option whose VALUE equals the question default
          // (NOT a label match) — §6.1 / AC-19.
          const recommended = option.value === question.default;
          return (
            <button
              key={option.value}
              type="button"
              role="radio"
              aria-checked={active}
              onClick={() => setChoice(option.value)}
              style={{
                display: "flex",
                alignItems: "flex-start",
                gap: 11,
                textAlign: "left",
                padding: "12px 14px",
                borderRadius: "var(--r-md)",
                cursor: "pointer",
                transition: "all .14s var(--ease)",
                border: `1px solid ${
                  active
                    ? "color-mix(in oklab, var(--st-paused) 60%, transparent)"
                    : "var(--border)"
                }`,
                background: active
                  ? "color-mix(in oklab, var(--st-paused) 14%, var(--surface))"
                  : "var(--surface)",
              }}
            >
              <span
                aria-hidden
                style={{
                  width: 20,
                  height: 20,
                  borderRadius: "var(--r-pill)",
                  border: `2px solid ${active ? "var(--st-paused)" : "var(--border-2)"}`,
                  display: "grid",
                  placeItems: "center",
                  flex: "none",
                  marginTop: 1,
                }}
              >
                {active && (
                  <span
                    style={{
                      width: 9,
                      height: 9,
                      borderRadius: "var(--r-pill)",
                      background: "var(--st-paused)",
                    }}
                  />
                )}
              </span>
              <div>
                <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 2 }}>
                  {option.label}
                  {recommended && (
                    <span
                      className="cap"
                      data-testid="recommended-marker"
                      style={{ marginLeft: 8, fontWeight: 600 }}
                    >
                      recommended
                    </span>
                  )}
                </div>
                {option.description && (
                  <div style={{ fontSize: 12.5, color: "var(--text-2)", lineHeight: 1.45 }}>
                    {option.description}
                  </div>
                )}
              </div>
            </button>
          );
        })}
      </div>

      {error && (
        <p
          role="alert"
          style={{ margin: 0, padding: "0 20px 10px", fontSize: 12.5, color: "var(--st-failed)" }}
        >
          {error}
        </p>
      )}

      <div
        style={{
          padding: "13px 20px",
          borderTop: "1px solid color-mix(in oklab, var(--st-paused) 25%, transparent)",
          display: "flex",
          alignItems: "center",
          gap: 10,
          background: "color-mix(in oklab, var(--st-paused) 5%, transparent)",
        }}
      >
        <button
          type="button"
          className="btn btn-primary"
          disabled={busy}
          onClick={() => void send({ answers: { [question.id]: choice }, skip_remaining: false })}
          style={{ background: "var(--st-paused)", color: "var(--st-paused-fg)" }}
        >
          <CheckIcon size={16} />
          Approve &amp; continue
        </button>
        <div style={{ flex: 1 }} />
        <button
          type="button"
          className="btn btn-soft btn-sm"
          disabled={busy}
          onClick={() => void send({ answers: {}, skip_remaining: true })}
        >
          Ship as-is
        </button>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          disabled={busy}
          onClick={() => void send({ answers: {}, skip_remaining: true })}
          style={{ color: "var(--st-failed)" }}
        >
          Abort
        </button>
      </div>
    </div>
  );
}
