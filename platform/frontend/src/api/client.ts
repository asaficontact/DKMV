/**
 * Typed API client for the loopback control plane (§8.9) + an EventSource
 * primitive (instantiated, NOT yet consuming a run stream — that is Phase 2).
 *
 * Every request goes to the `/api/v1` base. Responses use the §8.9 error
 * envelope `{ error: { code, message, details? } }`; a non-2xx is surfaced as an
 * {@link ApiError} carrying the machine `code` so the UI can branch.
 *
 * **INV-1.** The control plane requires the local token. The browser app reads
 * it from a build-time/dev-time injected global (never hardcoded); state-changing
 * POSTs additionally pass through the backend's Host/Origin/CSRF middleware. We
 * do NOT put any token in a URL (INV-2) — the EventSource primitive below relies
 * on the HttpOnly SameSite cookie the backend sets on connect (Phase 2), never a
 * `?token=` query string.
 */

/** The versioned API base (every endpoint hangs off this). */
export const API_BASE = "/api/v1";

/** The §8.9 error envelope body. */
export interface ApiErrorEnvelope {
  error: { code: string; message: string; details?: Record<string, unknown> };
}

/** A non-2xx response, decoded from the §8.9 envelope. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details?: Record<string, unknown>;

  constructor(status: number, code: string, message: string, details?: Record<string, unknown>) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

/** The local control-plane token. Injected at runtime; never hardcoded (INV-1). */
function localToken(): string | undefined {
  const w = globalThis as unknown as { __DKMV_TOKEN__?: string };
  return w.__DKMV_TOKEN__;
}

function authHeaders(): Record<string, string> {
  const token = localToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function decode<T>(resp: Response): Promise<T> {
  const text = await resp.text();
  const body = text ? (JSON.parse(text) as unknown) : null;
  if (!resp.ok) {
    const env = body as ApiErrorEnvelope | null;
    const err = env?.error;
    throw new ApiError(
      resp.status,
      err?.code ?? "error",
      err?.message ?? resp.statusText,
      err?.details,
    );
  }
  return body as T;
}

/** GET `path` (relative to {@link API_BASE}) → decoded JSON. */
export async function apiGet<T>(path: string): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    method: "GET",
    headers: { ...authHeaders() },
    credentials: "same-origin",
  });
  return decode<T>(resp);
}

/** POST `path` with a JSON `body` → decoded JSON. JSON content type satisfies CSRF. */
export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: "same-origin",
  });
  return decode<T>(resp);
}

/** PUT `path` with a JSON `body` → decoded JSON. JSON content type satisfies CSRF. */
export async function apiPut<T>(path: string, body?: unknown): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: "same-origin",
  });
  return decode<T>(resp);
}

/**
 * Open a Server-Sent-Events stream against the API.
 *
 * **Phase boundary.** This primitive exists so the run view (Phase 2) can stream
 * `GET /runs/{id}/events`; it is exported and unit-instantiable now but is NOT
 * wired to any run stream in Phase 1 (the Board/chip are poll-driven — AC-20).
 *
 * **INV-2.** Auth rides the HttpOnly `SameSite=Strict` cookie set by the backend
 * on connect; `withCredentials: true` sends it. The token is NEVER placed in the
 * URL/query — doing so would leak it into logs and the append-only events table.
 */
export function openEventStream(path: string): EventSource {
  return new EventSource(`${API_BASE}${path}`, { withCredentials: true });
}
