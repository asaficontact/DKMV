/**
 * Right rail (FR-04-5, AC-16) — ported from `run.jsx RunRail`.
 *
 * Four sections:
 *  - **Run config** — the verbatim §8.9 keys `repo, branch, feature_name, model,
 *    max_turns, timeout_minutes, max_budget_usd, memory_limit` (a `null` value
 *    renders "null"). The order + key names are pinned (AC-16 asserts each).
 *  - **Sandbox** — `dkmv-sandbox:latest` + a health line (`8g · 2 vCPU · healthy`).
 *  - **Artifacts** — the run's artifact list (a `live` one gets a "live" badge).
 *  - **Pull request** — shown only when a PR is linked.
 *
 * All color is token-driven (INV-14); the sandbox health is conveyed by an
 * icon-bearing label, not color alone.
 */
import type { RunDetailResponse } from "../api/runs";
import { CheckIcon, ExtIcon, GitHubIcon, PrIcon, SettingsIcon } from "./icons";

export interface RunRailProps {
  run: RunDetailResponse;
  /** GitHub URL for the linked PR (built by the screen from repo + pr.num). */
  prUrl?: string;
}

/** The verbatim FR-04-5 run-config keys, in display order (AC-16). */
const CONFIG_KEYS = [
  "repo",
  "branch",
  "feature_name",
  "model",
  "max_turns",
  "timeout_minutes",
  "max_budget_usd",
  "memory_limit",
] as const;

/** Render a config value: a `null` shows "null"; strip the github URL prefix. */
function renderConfigValue(value: unknown): string {
  if (value == null) return "null";
  return String(value).replace("https://github.com/", "");
}

export default function RunRail({ run, prUrl }: RunRailProps) {
  const sandbox = run.sandbox;
  const isLive = run.status === "running";
  const healthLabel = isLive
    ? `${sandbox.mem} · ${sandbox.vcpu} vCPU · ${sandbox.health}`
    : run.status === "failed"
      ? "exited · timeout"
      : `${sandbox.mem} · idle`;

  return (
    <aside className="run-rail" aria-label="Run details">
      <RailSection title="Run config" Icon={SettingsIcon}>
        <div className="rail-config">
          {CONFIG_KEYS.map((key) => {
            const value = run.config[key];
            return (
              <div className="rail-config-row" key={key}>
                <span className="mono rail-config-key">{key}</span>
                <span
                  className={`mono rail-config-val${value == null ? " is-null" : ""}`}
                  data-testid={`config-${key}`}
                >
                  {renderConfigValue(value)}
                </span>
              </div>
            );
          })}
        </div>
      </RailSection>

      <RailSection title="Sandbox" Icon={GitHubIcon}>
        <div className="rail-sandbox">
          <span
            className={`rail-sandbox-dot${isLive ? " is-up" : run.status === "failed" ? " is-down" : ""}`}
            aria-hidden
          />
          <div className="rail-sandbox-meta">
            <div className="mono rail-sandbox-image">{sandbox.image}</div>
            <div className="cap">{healthLabel}</div>
          </div>
        </div>
      </RailSection>

      <RailSection title="Artifacts" Icon={PrIcon}>
        <div className="rail-artifacts">
          {run.artifacts.length === 0 && <span className="cap">No artifacts yet.</span>}
          {run.artifacts.map((a) => (
            <div className="rail-artifact" key={a.name}>
              <span className="mono rail-artifact-name">{a.name}</span>
              {a.live ? (
                <span className="badge rail-artifact-live">live</span>
              ) : (
                <span className="cap mono">{a.size != null ? `${a.size}` : ""}</span>
              )}
            </div>
          ))}
        </div>
      </RailSection>

      {run.pr && (
        <RailSection title="Pull request" Icon={PrIcon}>
          <div className="rail-pr">
            <div className="rail-pr-head">
              <PrIcon size={14} />
              <span className="mono rail-pr-num">#{run.pr.num}</span>
              <span className="badge rail-pr-checks">
                <CheckIcon size={9} /> checks pass
              </span>
            </div>
            {run.pr.title && <div className="rail-pr-title">{run.pr.title}</div>}
            <a
              className="btn btn-soft btn-sm rail-pr-link"
              href={prUrl ?? "#"}
              target="_blank"
              rel="noreferrer"
            >
              <GitHubIcon size={13} /> View on GitHub <ExtIcon size={12} />
            </a>
          </div>
        </RailSection>
      )}
    </aside>
  );
}

function RailSection({
  title,
  Icon,
  children,
}: {
  title: string;
  Icon: (p: { size?: number }) => JSX.Element;
  children: React.ReactNode;
}) {
  return (
    <section className="rail-section">
      <div className="rail-section-head">
        <Icon size={14} />
        <span className="rail-section-title">{title}</span>
      </div>
      {children}
    </section>
  );
}
