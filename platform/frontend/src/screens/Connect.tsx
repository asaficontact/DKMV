/**
 * Screen 01 — Connect & project picker (FR-01, built to `connect.jsx`).
 *
 * Local state machine `disconnected → connecting → picker → syncing` (FR-01-1),
 * driven by the top Segmented tabs Welcome / Pick repo / Syncing. Each state
 * matches the prototype:
 *
 *   - **disconnected/connecting** — hero "Turn your GitHub issues into work that
 *     runs itself." + the verbatim reassurance line "…Nothing runs until you say
 *     so." + a PAT entry that lists the FOUR permissions to grant (FR-01-2/3).
 *   - **picker** — searchable repo list from `GET /repos`, a "What we'll do"
 *     card (Read issues / Add agent:* labels / Nothing runs until Run) and the
 *     Preflight box from `GET /preflight`; **Open project** → syncing →
 *     `POST /projects/{repo}/sync` (FR-01-4/5/6).
 *   - **syncing** — "Importing your issues…" indeterminate run-bar (FR-01-5).
 *
 * **INV-14.** No hardcoded hex — every color is a CSS variable / class ported
 * into `tokens.css`. State is conveyed by icon + text label, never color alone.
 * The repo lang dot uses the API-supplied `r.langColor` token string (an opaque
 * CSS color value from the backend, not a literal authored here).
 */

import { useCallback, useEffect, useState, type CSSProperties, type ReactNode } from "react";

import "./connect.css";
import {
  connectGitHub,
  getPreflight,
  listRepos,
  repoSlug,
  syncProject,
  type PreflightReport,
  type Repo,
} from "../api/connect";
import { REQUIRED_PERMISSIONS } from "../app/permissions";

type ConnectState = "disconnected" | "connecting" | "picker" | "syncing";

interface ConnectProps {
  /** Called once the project is opened + sync kicked off (→ navigate to board). */
  onDone: (slug: string) => void;
  /** Test seam: skip the real network and start in a given state with repos. */
  initialState?: ConnectState;
  initialRepos?: Repo[];
  initialPreflight?: PreflightReport;
}

// ── Inline icons (currentColor; no hardcoded hex — INV-14) ───────────────────

type IconProps = { size?: number; className?: string; style?: CSSProperties };

const GitHubIcon = ({ size = 18, style }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" style={style} aria-hidden>
    <path d="M12 1.5a10.5 10.5 0 00-3.32 20.46c.52.1.71-.23.71-.5v-1.74c-2.9.63-3.52-1.4-3.52-1.4-.47-1.2-1.16-1.52-1.16-1.52-.95-.65.07-.64.07-.64 1.05.08 1.6 1.08 1.6 1.08.94 1.6 2.46 1.14 3.06.87.1-.68.37-1.14.67-1.4-2.32-.27-4.76-1.16-4.76-5.16 0-1.14.4-2.07 1.07-2.8-.1-.27-.46-1.34.1-2.78 0 0 .88-.28 2.88 1.07a9.9 9.9 0 015.24 0c2-1.35 2.87-1.07 2.87-1.07.57 1.44.21 2.51.11 2.78.67.73 1.07 1.66 1.07 2.8 0 4.01-2.45 4.88-4.78 5.14.38.33.71.97.71 1.96v2.9c0 .28.19.61.72.5A10.5 10.5 0 0012 1.5z" />
  </svg>
);

const RefreshIcon = ({ size = 18, className, style }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" className={className} style={style} aria-hidden>
    <path d="M21 12a9 9 0 11-2.64-6.36M21 3v6h-6" />
  </svg>
);

const CheckIcon = ({ size = 14, style }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={3} strokeLinecap="round" strokeLinejoin="round" style={style} aria-hidden>
    <path d="M20 6L9 17l-5-5" />
  </svg>
);

const SearchIcon = ({ size = 15, style }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" style={style} aria-hidden>
    <circle cx="11" cy="11" r="7" />
    <path d="M21 21l-4.3-4.3" />
  </svg>
);

const ArrowRIcon = ({ size = 16, style }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" style={style} aria-hidden>
    <path d="M5 12h14M13 5l7 7-7 7" />
  </svg>
);

// ── Segmented tabs (Welcome / Pick repo / Syncing) ───────────────────────────

const SEGMENTS: { value: ConnectState; label: string }[] = [
  { value: "disconnected", label: "Welcome" },
  { value: "picker", label: "Pick repo" },
  { value: "syncing", label: "Syncing" },
];

function Segmented({ value, onChange }: { value: ConnectState; onChange: (v: ConnectState) => void }) {
  return (
    <div className="segmented" role="tablist" aria-label="Connect steps">
      {SEGMENTS.map((s) => (
        <button
          key={s.value}
          role="tab"
          aria-selected={value === s.value}
          className={`segmented-opt${value === s.value ? " is-active" : ""}`}
          onClick={() => onChange(s.value)}
        >
          {s.label}
        </button>
      ))}
    </div>
  );
}

function ConfirmRow({ text }: { text: ReactNode }) {
  return (
    <div className="confirm-row">
      <span className="confirm-row-ic" aria-hidden>
        <CheckIcon size={13} />
      </span>
      <span className="confirm-row-text">{text}</span>
    </div>
  );
}

// ── Screen ───────────────────────────────────────────────────────────────────

export default function Connect({
  onDone,
  initialState = "disconnected",
  initialRepos,
  initialPreflight,
}: ConnectProps) {
  const [state, setState] = useState<ConnectState>(initialState);
  const [token, setToken] = useState("");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Repo | null>(null);
  const [repos, setRepos] = useState<Repo[]>(initialRepos ?? []);
  const [preflight, setPreflight] = useState<PreflightReport | null>(initialPreflight ?? null);
  const [error, setError] = useState<string | null>(null);

  const segmentValue: ConnectState = state === "connecting" ? "disconnected" : state;

  const loadPicker = useCallback(async () => {
    setError(null);
    try {
      const [repoList, pre] = await Promise.all([listRepos(), getPreflight()]);
      setRepos(repoList);
      setPreflight(pre);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load repositories");
    }
  }, []);

  // When tests/storybook seed `initialState=picker` with no repos, fetch them.
  useEffect(() => {
    if (state === "picker" && repos.length === 0 && !initialRepos) {
      void loadPicker();
    }
  }, [state, repos.length, initialRepos, loadPicker]);

  const connect = useCallback(async () => {
    setError(null);
    setState("connecting");
    try {
      await connectGitHub(token);
      await loadPicker();
      setState("picker");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not connect to GitHub");
      setState("disconnected");
    }
  }, [token, loadPicker]);

  const openProject = useCallback(async () => {
    if (!selected) return;
    const slug = repoSlug(selected);
    setState("syncing");
    // Sync is slice 1.2; tolerate a 404 gracefully (the board still opens).
    try {
      await syncProject(slug);
    } catch {
      /* surfaced later on the board; do not strand the user in syncing */
    }
    onDone(slug);
  }, [selected, onDone]);

  const filtered = repos.filter((r) =>
    `${r.org}/${r.name} ${r.lang}`.toLowerCase().includes(query.toLowerCase()),
  );

  return (
    <div className="connect-shell">
      <header className="connect-top">
        <div className="connect-brand">
          <span className="connect-logo" aria-hidden>
            <GitHubIcon size={20} />
          </span>
          <span className="connect-wordmark">DKMV</span>
        </div>
        <Segmented value={segmentValue} onChange={setState} />
      </header>

      <main className="connect-stage">
        {(state === "disconnected" || state === "connecting") && (
          <section className="connect-hero fade-in">
            <div className="connect-hero-badge" aria-hidden>
              <GitHubIcon size={46} />
            </div>
            <h1 className="connect-hero-title">
              Turn your GitHub issues
              <br />
              into work that runs itself.
            </h1>
            <p className="connect-hero-sub">
              Connect a repo, assign each issue a workflow and an agent, and press Run. DKMV opens a
              sandbox, does the work, and brings back a pull request — while you watch.
            </p>

            <div className="connect-pat">
              <label className="connect-pat-label" htmlFor="pat-input">
                Fine-grained personal access token
              </label>
              <input
                id="pat-input"
                className="input mono"
                type="password"
                autoComplete="off"
                placeholder="github_pat_…"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                disabled={state === "connecting"}
              />
              <div className="connect-pat-perms">
                <span className="cap connect-pat-perms-title">Grant these permissions on the one repo</span>
                <ul className="connect-perm-list">
                  {REQUIRED_PERMISSIONS.map((perm) => (
                    <li key={perm} className="connect-perm">
                      <span className="confirm-row-ic" aria-hidden>
                        <CheckIcon size={11} />
                      </span>
                      <code className="mono">{perm}</code>
                    </li>
                  ))}
                </ul>
              </div>
            </div>

            <button
              className="btn btn-primary btn-lg connect-cta"
              onClick={() => void connect()}
              disabled={state === "connecting" || token.trim().length === 0}
            >
              {state === "connecting" ? (
                <>
                  <RefreshIcon size={18} className="spin" />
                  Connecting to GitHub…
                </>
              ) : (
                <>
                  <GitHubIcon size={19} />
                  Connect GitHub
                </>
              )}
            </button>

            {error && (
              <p className="connect-error" role="alert">
                {error}
              </p>
            )}

            <p className="cap connect-reassure">
              <span className="connect-reassure-ic" aria-hidden>
                <CheckIcon size={13} />
              </span>
              Read-only on your code. We only read issues and add{" "}
              <span className="mono">agent:*</span> labels. Nothing runs until you say so.
            </p>
          </section>
        )}

        {state === "picker" && (
          <section className={`connect-picker fade-in${selected ? " has-selection" : ""}`}>
            <div className="card connect-repo-card">
              <div className="connect-repo-head">
                <h2 className="connect-repo-title">Choose a repository</h2>
                <p className="connect-repo-desc">
                  One project at a time. You can switch any time from the sidebar.
                </p>
                <div className="connect-search">
                  <SearchIcon size={15} style={{ color: "var(--text-3)" }} />
                  <input
                    className="input"
                    autoFocus
                    placeholder="Search repositories…"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                  />
                </div>
              </div>
              <div className="connect-repo-list">
                {error && (
                  <p className="connect-error" role="alert">
                    {error}
                  </p>
                )}
                {filtered.map((r) => {
                  const active = selected?.name === r.name && selected?.org === r.org;
                  return (
                    <button
                      key={repoSlug(r)}
                      className={`connect-repo-row${active ? " is-active" : ""}`}
                      aria-label={`Select ${repoSlug(r)}`}
                      aria-pressed={active}
                      onClick={() => setSelected(r)}
                    >
                      <span className="connect-repo-avatar" aria-hidden>
                        {r.org.slice(0, 2).toUpperCase()}
                      </span>
                      <span className="connect-repo-meta">
                        <span className="connect-repo-name">
                          <span className="connect-repo-org">{r.org}/</span>
                          {r.name}
                        </span>
                        <span className="connect-repo-sub cap">
                          <span className="connect-repo-lang">
                            <span
                              className="connect-lang-dot"
                              style={{ background: r.langColor }}
                              aria-hidden
                            />
                            {r.lang}
                          </span>
                          <span>{r.issues} open issues</span>
                          <span>{r.updated}</span>
                        </span>
                      </span>
                      <span
                        className={`gh-label${r.private ? " is-private" : " is-public"}`}
                      >
                        {r.private ? "private" : "public"}
                      </span>
                      {active && (
                        <span className="connect-repo-check" aria-hidden>
                          <CheckIcon size={16} />
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            </div>

            {selected && (
              <aside className="card connect-confirm slide-in">
                <h3 className="connect-confirm-title">What we'll do</h3>
                <div className="connect-confirm-rows">
                  <ConfirmRow
                    text={
                      <>
                        Read issues from{" "}
                        <span className="mono">
                          {selected.org}/{selected.name}
                        </span>
                      </>
                    }
                  />
                  <ConfirmRow
                    text={
                      <>
                        Add <span className="mono">agent:*</span> labels to track work
                      </>
                    }
                  />
                  <ConfirmRow text="Nothing runs until you press Run" />
                </div>

                <div className="connect-preflight">
                  <div className="cap connect-preflight-title">Preflight</div>
                  {(preflight?.checks ?? []).map((p) => (
                    <div key={p.id} className="connect-preflight-row">
                      <span
                        className={`connect-preflight-ic${p.ok ? " is-ok" : " is-blocked"}`}
                        aria-hidden
                      >
                        <CheckIcon size={12} />
                      </span>
                      <span className="connect-preflight-label">{p.label}</span>
                      <span className="mono connect-preflight-sub">
                        {p.ok ? p.sub : "blocked"}
                      </span>
                    </div>
                  ))}
                </div>

                <button
                  className="btn btn-primary connect-open"
                  onClick={() => void openProject()}
                >
                  Open project
                  <ArrowRIcon size={16} />
                </button>
              </aside>
            )}
          </section>
        )}

        {state === "syncing" && (
          <section className="connect-syncing fade-in">
            <div className="connect-syncing-badge" aria-hidden>
              <RefreshIcon size={38} className="spin" />
            </div>
            <h2 className="connect-syncing-title">Importing your issues…</h2>
            <p className="connect-syncing-sub">
              Reading{" "}
              <span className="mono">
                {selected ? repoSlug(selected) : "your repository"}
              </span>{" "}
              and mapping labels to your board.
            </p>
            <div className="connect-syncing-bar">
              <div className="run-bar" />
            </div>
          </section>
        )}
      </main>
    </div>
  );
}
