/* ============================================================
   DKMV — mock data (real shapes from the brief's appendix)
   ============================================================ */

// ---- GitHub labels ----
const LABELS = {
  bug:        { name: "bug",        color: "#f2666b" },
  backend:    { name: "backend",    color: "#4f8cff" },
  frontend:   { name: "frontend",   color: "#a78bfa" },
  enhancement:{ name: "enhancement",color: "#34c98a" },
  auth:       { name: "auth",       color: "#f5a623" },
  docs:       { name: "docs",       color: "#7c7a82" },
  infra:      { name: "infra",      color: "#22b8cf" },
  "good first issue": { name: "good first issue", color: "#34c98a" },
};

// ---- Workflows (components) ----
const WORKFLOWS = [
  {
    id: "plan", name: "plan", emoji: "🧭",
    purpose: "PRD → full implementation docs",
    stages: ["Analyze", "Features & Stories", "Phases", "Assembly", "Evaluate-Fix"],
    pausesAfter: "Analyze", pauses: true,
    budget: "~$12", budgetRange: "$2–5 / task", estTime: "~40 min",
    model: "claude-sonnet-4-6", agent: "claude",
    maxTurns: 100, timeout: 30, maxBudget: 12,
  },
  {
    id: "dev", name: "dev", emoji: "🛠️",
    purpose: "Implement each phase from the plan docs",
    stages: ["Implement-Phase ×N (for-each phase)"],
    pausesAfter: null, pauses: false,
    budget: "$10 / phase", budgetRange: "$10 / phase", estTime: "~25 min / phase",
    model: "gpt-5.1-codex", agent: "codex",
    maxTurns: 120, timeout: 40, maxBudget: 10,
  },
  {
    id: "qa", name: "qa", emoji: "🔍",
    purpose: "Evaluate → fix → re-evaluate",
    stages: ["Evaluate", "Fix", "Re-evaluate"],
    pausesAfter: "Evaluate", pauses: true,
    budget: "~$2", budgetRange: "~$2", estTime: "~15 min",
    model: "claude-sonnet-4-6", agent: "claude",
    maxTurns: 80, timeout: 25, maxBudget: 2,
  },
  {
    id: "docs", name: "docs", emoji: "📝",
    purpose: "Update docs + open a PR",
    stages: ["Update-Docs", "Verify", "Create-PR"],
    pausesAfter: null, pauses: false,
    budget: "~$3", budgetRange: "~$3", estTime: "~12 min",
    model: "gpt-5.1-codex", agent: "codex",
    maxTurns: 60, timeout: 20, maxBudget: 3,
  },
  {
    id: "ship", name: "ship", emoji: "🚀",
    purpose: "End-to-end: analyze → plan → implement → evaluate-fix → finalize",
    stages: ["Analyze", "Plan", "Implement", "Evaluate-Fix", "Finalize"],
    pausesAfter: "Analyze", pauses: true,
    budget: "~$29.50", budgetRange: "~$29.50", estTime: "~2 hr",
    model: "claude-sonnet-4-6", agent: "claude",
    maxTurns: 200, timeout: 120, maxBudget: 30,
  },
];
const WF = Object.fromEntries(WORKFLOWS.map(w => [w.id, w]));

const AGENTS = {
  claude: { id: "claude", name: "Claude", model: "claude-sonnet-4-6", color: "#ff6b4a", short: "C" },
  codex:  { id: "codex",  name: "Codex",  model: "gpt-5.1-codex",     color: "#34c98a", short: "Cx" },
};

// ---- Issues (board) ----
// state: backlog | queued | progress | needsyou | review | done
const ISSUES = [
  { num: 247, title: "Fix auth token refresh dropping sessions after 1h", state: "progress",
    labels: ["bug", "auth", "backend"], workflow: "dev", agent: "codex",
    assignee: "AS", body: `### Summary\nUsers are silently logged out roughly an hour into a session. The access token refresh isn't firing before expiry, so the next API call 401s and the session is dropped.\n\n### Steps to reproduce\n1. Sign in\n2. Leave the tab idle ~60 min\n3. Make any authenticated request → \`401\`\n\n### Expected\nThe refresh token should rotate the access token in the background ~5 min before expiry.\n\n### Notes\nLikely in \`dkmv/auth/session.py\`. The refresh timer may be using a stale \`expires_at\`.`,
    run: "260307-0912-dev-issue-247-fix-auth-4a6c",
    liveCost: 4.18, liveTurns: 37, progress: 0.62, phase: "Phase 2 / 3 · Implement refresh timer",
    comments: [
      { author: "asaficontact", avatar: "AS", time: "2h ago", body: "Confirmed on prod — happens for everyone, not just SSO users." },
    ] },

  { num: 251, title: "Multi-agent adapter: support Codex alongside Claude", state: "needsyou",
    labels: ["enhancement", "backend"], workflow: "plan", agent: "claude",
    assignee: "AS", body: `### Goal\nIntroduce a clean adapter boundary so DKMV can drive **either** Claude or Codex through the same workflow engine.\n\n### Acceptance\n- A single \`AgentAdapter\` protocol\n- \`claude.py\` and \`codex.py\` implementations\n- Model→agent inference ("Auto")\n- Streaming events normalized to one shape\n\nThis is the big one — it unblocks the whole multi-agent direction.`,
    run: "260305-1355-plan-prd-multi-agent-adapter-7389",
    liveCost: 6.40, liveTurns: 64, progress: 0.4, phase: "Paused after Analyze · awaiting your call",
    comments: [
      { author: "asaficontact", avatar: "AS", time: "5h ago", body: "Let's make sure the event shape is normalized — don't want two code paths in the UI." },
    ] },

  { num: 239, title: "Streaming event feed flickers on rapid tool calls", state: "progress",
    labels: ["bug", "frontend"], workflow: "qa", agent: "claude",
    assignee: "AS", body: "The live feed re-mounts rows on each batch instead of appending, causing a flicker. Should key by event id and append only.",
    run: "260307-1020-qa-issue-239-feed-flicker-9c2f",
    liveCost: 1.12, liveTurns: 14, progress: 0.33, phase: "Evaluate · running tests" },

  { num: 233, title: "Add per-task budget overrides in workflow builder", state: "queued",
    labels: ["enhancement", "frontend"], workflow: "dev", agent: "auto",
    assignee: "AS", body: "Each task should allow overriding max_budget_usd independent of the component default." },

  { num: 256, title: "Sandbox container OOMs on large monorepos", state: "queued",
    labels: ["bug", "infra"], workflow: "qa", agent: "claude",
    assignee: "AS", body: "8g memory limit isn't enough for repos over ~2GB checked out. Need a configurable memory ceiling and a friendly preflight warning." },

  { num: 260, title: "Document the agent:* label control-plane mapping", state: "review",
    labels: ["docs"], workflow: "docs", agent: "codex",
    assignee: "AS", body: "Write up how GitHub labels map to board columns so contributors understand the state machine.",
    run: "260306-1458-docs-codex-adapter-35a2", pr: 184, prTitle: "docs: agent:* label mapping + board states" },

  { num: 258, title: "PR checks badge missing on review cards", state: "review",
    labels: ["bug", "frontend"], workflow: "dev", agent: "codex",
    assignee: "AS", body: "When a run opens a PR, the board card should reflect the PR's check status.",
    run: "260306-1812-dev-pr-checks-badge-77a1", pr: 181, prTitle: "fix: surface PR check status on review cards" },

  { num: 244, title: "Cost meter rounds tokens incorrectly above 100k", state: "done",
    labels: ["bug"], workflow: "qa", agent: "claude",
    assignee: "AS", body: "Token formatter truncates instead of rounding past 100k.", pr: 176, prTitle: "fix: round token totals" },

  { num: 230, title: "Retry queue with exponential backoff for failed runs", state: "done",
    labels: ["enhancement", "backend"], workflow: "dev", agent: "codex",
    assignee: "AS", body: "Failed runs should auto-retry with backoff up to 3 attempts.", pr: 169, prTitle: "feat: retry queue + backoff" },

  // backlog
  { num: 263, title: "Friendly empty states for first-run board", state: "backlog",
    labels: ["frontend", "good first issue"], workflow: null, agent: null,
    assignee: "AS", body: "Add warm illustrated empty states across Board, Runs and Workflows." },
  { num: 262, title: "Keyboard shortcuts for board navigation", state: "backlog",
    labels: ["enhancement", "frontend"], workflow: null, agent: null,
    assignee: "AS", body: "j/k to move between cards, enter to open, r to run." },
  { num: 261, title: "Export run history to CSV", state: "backlog",
    labels: ["enhancement"], workflow: null, agent: null,
    assignee: "AS", body: "Let users export the runs table for their own spend tracking." },
];

const COLUMNS = [
  { id: "backlog",  title: "Backlog",     state: "queued", label: "—",                hint: "no agent label" },
  { id: "queued",   title: "Queued",      state: "queued", label: "agent:queued",     hint: "ready to run" },
  { id: "progress", title: "In Progress", state: "running",label: "agent:in-progress",hint: "a run is live" },
  { id: "needsyou", title: "Needs You",   state: "paused", label: "agent:paused",     hint: "paused for a decision" },
  { id: "review",   title: "In Review",   state: "review", label: "agent:review",     hint: "PR open" },
  { id: "done",     title: "Done",        state: "done",   label: "closed / merged",  hint: "merged" },
];

// ---- Runs history ----
const RUNS = [
  { id: "260307-0912-dev-issue-247-fix-auth-4a6c", issue: 247, issueTitle: "Fix auth token refresh dropping sessions", wf: "dev", agent: "codex", model: "gpt-5.1-codex", status: "running", cost: 4.18, tokensIn: 71200, tokensOut: 18400, turns: 37, dur: null, started: "2026-03-07 09:12", branch: "feat/codex", pr: null },
  { id: "260307-1020-qa-issue-239-feed-flicker-9c2f", issue: 239, issueTitle: "Streaming event feed flickers", wf: "qa", agent: "claude", model: "claude-sonnet-4-6", status: "running", cost: 1.12, tokensIn: 22100, tokensOut: 5300, turns: 14, dur: null, started: "2026-03-07 10:20", branch: "feat/codex", pr: null },
  { id: "260305-1355-plan-prd-multi-agent-adapter-7389", issue: 251, issueTitle: "Multi-agent adapter: Codex + Claude", wf: "plan", agent: "claude", model: "claude-sonnet-4-6", status: "paused", cost: 6.40, tokensIn: 98400, tokensOut: 27100, turns: 64, dur: null, started: "2026-03-05 13:55", branch: "feat/codex", pr: null },
  { id: "260306-1458-docs-codex-adapter-35a2", issue: 260, issueTitle: "Document agent:* label mapping", wf: "docs", agent: "codex", model: "gpt-5.1-codex", status: "completed", cost: 2.74, tokensIn: 41200, tokensOut: 9800, turns: 41, dur: 932, started: "2026-03-06 14:58", branch: "feat/codex", pr: 184 },
  { id: "260306-1812-dev-pr-checks-badge-77a1", issue: 258, issueTitle: "PR checks badge missing on review cards", wf: "dev", agent: "codex", model: "gpt-5.1-codex", status: "completed", cost: 9.86, tokensIn: 132400, tokensOut: 38600, turns: 96, dur: 1684, started: "2026-03-06 18:12", branch: "feat/codex", pr: 181 },
  { id: "260305-1455-dev-codex-adapter-4a6c", issue: 251, issueTitle: "Multi-agent adapter — dev phase 1", wf: "dev", agent: "codex", model: "gpt-5.1-codex", status: "completed", cost: 10.42, tokensIn: 148900, tokensOut: 41200, turns: 112, dur: 2104, started: "2026-03-05 14:55", branch: "feat/codex", pr: null },
  { id: "260305-1946-qa-codex-adapter-30b8", issue: 251, issueTitle: "Multi-agent adapter — qa pass", wf: "qa", agent: "codex", model: "gpt-5.1-codex", status: "completed", cost: 1.88, tokensIn: 34200, tokensOut: 7400, turns: 29, dur: 712, started: "2026-03-05 19:46", branch: "feat/codex", pr: null },
  { id: "260305-1355-plan-prd-multi-agent-adapter-0a11", issue: 251, issueTitle: "Multi-agent adapter — plan (full)", wf: "plan", agent: "claude", model: "claude-sonnet-4-6", status: "completed", cost: 13.28, tokensIn: 184600, tokensOut: 52300, turns: 153, dur: 2611, started: "2026-03-05 13:55", branch: "feat/codex", pr: null },
  { id: "260304-1102-qa-cost-meter-round-88de", issue: 244, issueTitle: "Cost meter rounds tokens incorrectly", wf: "qa", agent: "claude", model: "claude-sonnet-4-6", status: "completed", cost: 1.64, tokensIn: 28800, tokensOut: 6100, turns: 24, dur: 588, started: "2026-03-04 11:02", branch: "feat/codex", pr: 176 },
  { id: "260304-0930-dev-retry-queue-12ab", issue: 230, issueTitle: "Retry queue with exponential backoff", wf: "dev", agent: "codex", model: "gpt-5.1-codex", status: "failed", cost: 3.21, tokensIn: 52100, tokensOut: 11200, turns: 48, dur: 940, started: "2026-03-04 09:30", branch: "feat/codex", pr: null, error: "Sandbox timed out after 40 min during test run (pytest hung on a network fixture)." },
  { id: "260303-1740-dev-retry-queue-55cd", issue: 230, issueTitle: "Retry queue — retry attempt", wf: "dev", agent: "codex", model: "gpt-5.1-codex", status: "completed", cost: 8.90, tokensIn: 118200, tokensOut: 33400, turns: 88, dur: 1521, started: "2026-03-03 17:40", branch: "feat/codex", pr: 169 },
  { id: "260303-1402-docs-readme-refresh-71fa", issue: 260, issueTitle: "Docs: readme refresh", wf: "docs", agent: "codex", model: "gpt-5.1-codex", status: "cancelled", cost: 0.42, tokensIn: 8200, tokensOut: 1400, turns: 6, dur: 121, started: "2026-03-03 14:02", branch: "feat/codex", pr: null },
];

// retry queue
const RETRY_QUEUE = [
  { id: "260304-0930-dev-retry-queue-12ab", issue: 230, attempt: 2, dueIn: "2m 10s", lastError: "Sandbox timed out (pytest hung on network fixture)" },
];

// ---- Live event stream (Screen D) ----
// {type, subtype, content, tool, costAt, turnAt}
const RUN_EVENTS = [
  { kind: "system", icon: "▸", text: "Session started · model claude-sonnet-4-6 · sandbox 8g", t: "00:00", turn: 0 },
  { kind: "assistant", icon: "💬", text: "Reading the implementation docs and the current auth module to understand the refresh flow…", t: "00:06", turn: 1 },
  { kind: "tool", icon: "📂", text: "Read dkmv/auth/session.py", tool: "read_file", t: "00:11", turn: 2 },
  { kind: "tool", icon: "📂", text: "Read impl_docs/phase-2-refresh.md", tool: "read_file", t: "00:18", turn: 3 },
  { kind: "assistant", icon: "💬", text: "Found it — the refresh timer reads a stale expires_at captured at login. I'll recompute it from the latest token on each tick.", t: "00:31", turn: 5 },
  { kind: "tool", icon: "✏️", text: "Edited dkmv/auth/session.py (+34 −12)", tool: "edit_file", t: "00:44", turn: 7 },
  { kind: "tool", icon: "✏️", text: "Edited dkmv/auth/refresh.py (+18 −3)", tool: "edit_file", t: "00:58", turn: 9 },
  { kind: "tool", icon: "🔧", text: "Ran `pytest tests/auth -q`", tool: "bash", t: "01:22", turn: 12 },
  { kind: "error", icon: "✗", text: "command failed: 2 failed, 39 passed — test_refresh_rotates_before_expiry", t: "01:40", turn: 13 },
  { kind: "assistant", icon: "💬", text: "Two tests expect the rotation 5 min before expiry; my threshold was 2 min. Adjusting the lead time.", t: "01:51", turn: 14 },
  { kind: "tool", icon: "✏️", text: "Edited dkmv/auth/refresh.py (+4 −4)", tool: "edit_file", t: "02:03", turn: 16 },
  { kind: "tool", icon: "🔧", text: "Ran `pytest tests/auth -q`", tool: "bash", t: "02:21", turn: 18 },
  { kind: "ok", icon: "✓", text: "passed 41/41", t: "02:35", turn: 19 },
];

// tail events that "stream in" live (appended by the UI)
const STREAM_TAIL = [
  { kind: "tool", icon: "🔧", text: "Ran `ruff check dkmv/auth`", tool: "bash" },
  { kind: "ok", icon: "✓", text: "no lint errors" },
  { kind: "assistant", icon: "💬", text: "Refresh now rotates 5 min before expiry and survives idle tabs. Writing a short changelog note." },
  { kind: "tool", icon: "✏️", text: "Edited CHANGELOG.md (+6 −0)", tool: "edit_file" },
  { kind: "tool", icon: "📦", text: "git commit -m \"fix(auth): rotate access token before expiry\"", tool: "bash" },
  { kind: "assistant", icon: "💬", text: "Verifying the session survives a simulated 90-minute idle window…" },
  { kind: "tool", icon: "🔧", text: "Ran `pytest tests/auth/test_idle.py -q`", tool: "bash" },
  { kind: "ok", icon: "✓", text: "passed 6/6 — sessions persist across refresh" },
];

// ---- Stage tracker for the live run (dev / 3 phases) ----
const RUN_STAGES = [
  { name: "Phase 1 · Audit refresh flow", status: "done",     cost: 1.84, turns: 12, dur: "6m 02s" },
  { name: "Phase 2 · Implement refresh timer", status: "running", cost: 2.34, turns: 25, dur: null },
  { name: "Phase 3 · Idle-session tests", status: "pending",  cost: null, turns: null, dur: null },
];

// ---- Pause request (HITL) — real PauseRequest shape ----
const PAUSE_REQUEST = {
  task_name: "Analyze",
  context: {
    phases_found: 4,
    summary: "Mapped the multi-agent adapter into 4 implementation phases: (1) AgentAdapter protocol, (2) Claude adapter, (3) Codex adapter, (4) model→agent inference + event normalization.",
  },
  questions: [
    {
      id: "phase_strategy",
      question: "I found 4 candidate phases for this implementation. How would you like to proceed?",
      options: [
        { label: "Proceed with all 4 phases", description: "Implement the full plan as analyzed (recommended)." },
        { label: "Merge phases 3 & 4", description: "Combine the last two phases to ship a smaller first cut." },
        { label: "Let me edit the plan first", description: "Pause here so I can adjust scope before continuing." },
      ],
      default: "Proceed with all 4 phases",
    },
  ],
};

// ---- Repos (Connect flow) ----
const REPOS = [
  { org: "asaficontact", name: "DKMV", lang: "Python", langColor: "#4f8cff", private: true, updated: "updated 2h ago", issues: 12, stars: 0, desc: "GitHub Issues → autonomous coding-agent runs" },
  { org: "asaficontact", name: "symphony-notes", lang: "TypeScript", langColor: "#4f8cff", private: true, updated: "updated 3d ago", issues: 4 },
  { org: "asaficontact", name: "agent-sandbox", lang: "Rust", langColor: "#f5a623", private: false, updated: "updated 1w ago", issues: 0 },
  { org: "asaficontact", name: "dotfiles", lang: "Shell", langColor: "#34c98a", private: false, updated: "updated 3w ago", issues: 1 },
  { org: "labs-ai", name: "eval-harness", lang: "Python", langColor: "#4f8cff", private: true, updated: "updated 1mo ago", issues: 27 },
  { org: "labs-ai", name: "prompt-registry", lang: "Go", langColor: "#22b8cf", private: true, updated: "updated 2mo ago", issues: 9 },
];

// preflight checklist
const PREFLIGHT = [
  { id: "github", label: "GitHub connected", sub: "asaficontact", ok: true },
  { id: "anthropic", label: "Anthropic API key", sub: "sk-ant-•••••4f2a", ok: true },
  { id: "docker", label: "Docker sandbox image", sub: "dkmv-sandbox:latest · 8g", ok: true },
];

Object.assign(window, {
  LABELS, WORKFLOWS, WF, AGENTS, ISSUES, COLUMNS, RUNS, RETRY_QUEUE,
  RUN_EVENTS, STREAM_TAIL, RUN_STAGES, PAUSE_REQUEST, REPOS, PREFLIGHT,
});
