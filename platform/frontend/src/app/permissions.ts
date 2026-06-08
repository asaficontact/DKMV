/**
 * The four fine-grained PAT permissions the operator grants on the single
 * selected repo (§8.1 / FR-01-3). Listed verbatim on the Connect screen's PAT
 * entry (AC-10 greps `src` for all four) and echoed by `POST /connect/github`.
 */
export const REQUIRED_PERMISSIONS = [
  "issues:write",
  "pull_requests:write",
  "contents:write",
  "metadata:read",
] as const;

export type RequiredPermission = (typeof REQUIRED_PERMISSIONS)[number];
