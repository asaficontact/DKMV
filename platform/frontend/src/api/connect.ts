/**
 * Connect-flow API surface (Screen 01, FR-01). Thin typed wrappers over the
 * generic {@link apiGet}/{@link apiPost} client for the four endpoints the
 * connect flow touches:
 *
 *   - `POST /connect/github`     — store the fine-grained PAT (slice 1.4).
 *   - `GET  /repos`              — accessible repos (slice 1.1; called, not built).
 *   - `GET  /preflight`          — standing env checks (Phase 0 / 1.1).
 *   - `POST /projects/{repo}/sync` — import issues (slice 1.2; called, not built).
 *
 * Repos/preflight/sync are owned by sibling slices; this module only *calls*
 * them over the API. When `sync` is not yet present it 404s — the UI tolerates
 * that gracefully (the syncing state still advances to the board).
 */

import { apiGet, apiPost } from "./client";

/** A repo row from `GET /repos` (PRD §6.1 `Repo` shape / `data.jsx REPOS`). */
export interface Repo {
  org: string;
  name: string;
  lang: string;
  langColor: string;
  private: boolean;
  updated: string;
  issues: number;
  stars?: number;
  desc?: string;
}

/** A single preflight check row (§8.9 `{ id, label, sub, ok }`). */
export interface PreflightCheck {
  id: string;
  label: string;
  sub: string;
  ok: boolean;
}

/** The `GET /preflight` envelope (FR-01-6). */
export interface PreflightReport {
  ready: boolean;
  checks: PreflightCheck[];
  blockers: string[];
}

/** The `POST /connect/github` response (slice 1.4 — carries no token). */
export interface ConnectResult {
  connected: boolean;
  token_hint: string;
  permissions: string[];
}

/** Store the fine-grained PAT (slice 1.4 — `POST /connect/github`). */
export function connectGitHub(token: string): Promise<ConnectResult> {
  return apiPost<ConnectResult>("/connect/github", { token });
}

/** List the token's accessible repos (slice 1.1 — `GET /repos`). */
export function listRepos(): Promise<Repo[]> {
  return apiGet<Repo[]>("/repos");
}

/** Standing environment checklist (Phase 0 / 1.1 — `GET /preflight`). */
export function getPreflight(): Promise<PreflightReport> {
  return apiGet<PreflightReport>("/preflight");
}

/** A repo "org/name" identifier used in the sync path. */
export function repoSlug(repo: Pick<Repo, "org" | "name">): string {
  return `${repo.org}/${repo.name}`;
}

/**
 * Import the repo's issues onto the board (slice 1.2 — `POST /projects/{repo}/sync`).
 *
 * The sync endpoint is built in slice 1.2; in slice 1.4 the "Open project"
 * button wires the call and tolerates a 404 (returns `false`) so the connect
 * flow still advances to the board if 1.2 has not merged yet.
 */
export async function syncProject(slug: string): Promise<boolean> {
  const encoded = encodeURIComponent(slug);
  try {
    await apiPost<unknown>(`/projects/${encoded}/sync`);
    return true;
  } catch (err) {
    // Tolerate "not yet implemented" (404) gracefully — see the docstring.
    if (err && typeof err === "object" && "status" in err && (err as { status: number }).status === 404) {
      return false;
    }
    throw err;
  }
}
