/**
 * Small board chips — GitHub label pill, workflow chip, agent chip, avatar.
 * Ported from `components.jsx` (`GhLabel`/`WfChip`/`AgentChip`/`Avatar`) but with
 * **all color via tokens** (the `--lbl-*` / `--agent-*` / `--accent` vars in
 * tokens.css) — no hardcoded hex here (INV-14).
 */
import type { CSSProperties } from "react";

/** The §7.4 `LABELS` set we have a token color for; anything else falls back. */
const LABEL_TOKEN: Record<string, string> = {
  bug: "var(--lbl-bug)",
  backend: "var(--lbl-backend)",
  frontend: "var(--lbl-frontend)",
  enhancement: "var(--lbl-enhancement)",
  auth: "var(--lbl-auth)",
  docs: "var(--lbl-docs)",
  infra: "var(--lbl-infra)",
  "good first issue": "var(--lbl-good-first-issue)",
};

/** A GitHub label pill, colored from the `--lbl-*` token map (§7.4). */
export function GhLabel({ name }: { name: string }) {
  const color = LABEL_TOKEN[name] ?? "var(--st-cancel)";
  // CSS custom prop carries the resolved token reference (not a hex literal).
  const style = { "--lc": color } as CSSProperties;
  return (
    <span className="gh-label" style={style}>
      {name}
    </span>
  );
}

/** Workflow (component) chip — emoji + name. */
export function WfChip({ workflowId }: { workflowId: string }) {
  return (
    <span className="badge badge-soft wf-chip">
      <span aria-hidden>{WORKFLOW_EMOJI[workflowId] ?? "⚙️"}</span>
      {workflowId}
    </span>
  );
}

const WORKFLOW_EMOJI: Record<string, string> = {
  plan: "🧭",
  dev: "🛠️",
  qa: "🔍",
  docs: "📝",
  ship: "🚀",
};

/** Per-agent display (from `data.jsx AGENTS`); color resolves to a token var. */
const AGENT_META: Record<string, { name: string; short: string; colorVar: string }> = {
  claude: { name: "Claude", short: "C", colorVar: "var(--agent-claude)" },
  codex: { name: "Codex", short: "Cx", colorVar: "var(--agent-codex)" },
};

/** Agent chip — a small brand square + the agent name. "auto"/unknown → "Auto". */
export function AgentChip({ agent }: { agent: string }) {
  const meta = AGENT_META[agent];
  if (!meta) {
    return (
      <span className="badge badge-soft" style={{ fontSize: 11 }}>
        Auto
      </span>
    );
  }
  const squareStyle = {
    "--ac": meta.colorVar,
  } as CSSProperties;
  return (
    <span className="agent-chip">
      <span className="agent-square" style={squareStyle} aria-hidden>
        {meta.short}
      </span>
      <span className="agent-name">{meta.name}</span>
    </span>
  );
}

/** A circular initials avatar; accent-tinted by default. */
export function Avatar({ initials, size = 26 }: { initials: string; size?: number }) {
  const style: CSSProperties = {
    width: size,
    height: size,
    fontSize: size * 0.4,
  };
  return (
    <span className="avatar" style={style} aria-hidden>
      {initials}
    </span>
  );
}
