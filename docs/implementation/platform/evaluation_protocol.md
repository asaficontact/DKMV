# DKMV Platform v1 — Evaluation Protocol

The build → evaluate → fix → polish → PR loop that gates every slice. Grounded in `claude-code-research.md` (the dispatch tool is **`Agent`**; `Task` is an accepted alias).

## The loop, in code (per phase)

```
function executePhase(N):
  brief = "docs/implementation/platform/phase_N_*.md"
  slices = brief.slices          # from the phase brief's Slices table + Wave plan

  for wave in brief.waves:       # waves run sequentially; slices WITHIN a wave run in parallel
    # Step 0 — orchestrator-side worktree creation (Bash, NOT a dispatch parameter)
    for slice in wave:
      Bash(`git worktree add .claude/worktrees/phase-N-impl-<slice> -b phase-N-impl-<slice> platform`)
      appendProgressLog(`DISPATCH phase-N-impl-<slice>`)   # log on dispatch (resume-safety)

    # Step 1 — parallel implementer dispatch (ONE assistant turn, N Agent calls)
    reports = parallel: for slice in wave:
      Agent(subagent_type="dkmvp-implementer",
            description="Phase N <slice>",
            prompt="Implement slice <slice> from docs/implementation/platform/phase_N_*.md. "
                 + "Worktree: .claude/worktrees/phase-N-impl-<slice>. cd there first. Return JSON.")

    # Step 2 — collect + one retry on test failure
    for r in reports:
      if not r.tests_passed:
        retry = Agent(subagent_type="dkmvp-implementer",
                      prompt="Worktree .claude/worktrees/<r.branch>. Fix failing tests <r.tests_failed>. Return JSON.")
        if not retry.tests_passed: escalate(); return BLOCKED

    # Step 3 — independent evaluation (NO implementer context — brief path + branch only)
    verdicts = parallel: for r in reports:
      Agent(subagent_type="dkmvp-evaluator",
            description="Evaluate <r.branch>",
            prompt="Evaluate branch <r.branch> against docs/implementation/platform/phase_N_*.md. "
                 + "You have never seen the implementer's reasoning. Return VERDICT block.")

    # Step 4 — verdict resolution (max 3 fix loops)
    fixCount = 0
    while any(v == REJECTED) and fixCount < 3:
      if any(v.CRITICAL_ISSUES): escalate(); return BLOCKED   # CRITICAL = security / PRD-divergence, never auto-fix
      fixers = parallel: for v in REJECTED with only MAJOR/MINOR:
        Agent(subagent_type="dkmvp-implementer",
              prompt="Worktree .claude/worktrees/<v.branch>. Fix: <v.MAJOR_ISSUES + v.MINOR_NITS>. Return JSON.")
      verdicts = re-evaluate(fixers); fixCount += 1
    if any(v == REJECTED): escalate(); return BLOCKED

    # Step 5 — 3-lens polish (solo rule: ONLY for slices touching >3 files; else a single full polish)
    for branch in wave.branches:
      if branch.files_changed > 3:
        polish = parallel: lens in [security, performance, structure]:
          Agent(subagent_type="dkmvp-evaluator",
                prompt="Review <branch> through lens: <lens>. Return VERDICT.")
      else:
        polish = [Agent(subagent_type="dkmvp-evaluator", prompt="Polish-review <branch> (full). Return VERDICT.")]
      if any(polish.CRITICAL_ISSUES): goto Step 4 (fix) ; (max 2 polish passes, else escalate)

  # Step 6 — PR open (serialized PR mode: one open PR at a time)
  for branch in phase.branches:   # may be one PR per slice OR one PR per phase — see note
    waitUntil(previousPRMerged)
    pr = mcp__github__create_pull_request(title="Phase N: <branch>", head=branch, base="platform", body=buildPRBody(...))
    appendProgressLog(`PR-OPENED <branch> <pr.url>`)

  # Step 7 — human merge (orchestrator polls; reads phase N+1 brief while waiting; NEVER auto-merges)
  await humanMerge()

  # Step 8 — cleanup
  for branch in phase.branches:
    Bash(`git worktree remove .claude/worktrees/<branch>`); Bash(`git branch -D <branch>`)

  # Step 9 — advance
  appendProgressLog(`PHASE-N-COMPLETE`); start phase N+1
```

**PR granularity (solo mode).** Default: **one PR per slice**, opened serially (PR N+1 waits for PR N to merge) so Tawab is never facing a wall of PRs. For a tightly-coupled wave you MAY open one PR for the whole wave — note which in the phase's progress entry.

## When to escalate to the user (interrupt the loop)

Post a `🚨 BLOCKED` chat message (one-sentence reason, branch, files, recommended action, decision needed) and wait, when:

1. An evaluator returns any `CRITICAL_ISSUES` (security regression or PRD divergence — never auto-fixed).
2. The fix-loop count exceeds 3 on a slice.
3. An implementer's `open_questions` repeats across two consecutive reports for the same slice.
4. An implementer reports the **PRD/design needs a change** (the source of truth is locked — only Tawab unlocks).
5. An implementer reports an **engine ask** (`dkmv/` would need to change) — record it; do not edit the engine.
6. A `docker`/sandbox/gVisor prerequisite is unavailable on the host (e.g. `runsc` missing — OQ-6) for >30 min.
7. Any test or sandbox run times out >10 min.

## The unbiased-evaluator discipline (hard rule)

The evaluator dispatch prompt contains **only** the brief path + the branch name (+ an optional `lens:`). NEVER paraphrase the implementer's self-assessment, open_questions, or reasoning into the evaluator's prompt — that contaminates the judgment. The evaluator forms its own view from the diff + the brief + `_conventions.md`. (Anti-pattern #3.)

## The 3-lens polish pass

Three parallel `dkmvp-evaluator` dispatches per branch with `lens: security | performance | structure`. The evaluator's system prompt (`agents/dkmvp-evaluator.md` §7) enumerates each lens's focus. Aggregate `CRITICAL_ISSUES` across the three; any critical → back to the fix loop. **Solo compression:** run the 3-lens pass only for slices touching **>3 files**; for ≤3-file slices, a single full polish evaluator suffices.

## The PR body template

```
## Phase N — <slice>

**PRD:** <cited §sections>   **Branch:** <branch>   **Files:** <n>

### Acceptance checklist
<verbatim ACCEPTANCE_CHECKLIST from the final evaluator VERDICT — each criterion + met + evidence>

### Security checks
<verbatim SECURITY_CHECKS from the VERDICT — each predicate + true/false + grep evidence>

### Design fidelity
<verbatim DESIGN_FIDELITY from the VERDICT, or "n/a — no UI in this slice">

### Independent test results
<commands + exit codes from INDEPENDENT_TEST_RESULTS>

### Polish pass
<security / performance / structure lens summary — "clean" or the criticals that were fixed>

### Implementer notes
<self_assessment ; open_questions ; deferred_to_followup>
```

## Implementer JSON report — exact schema

First character MUST be `{`; no prose, no code fences. Fields: `branch, commit_sha, files_changed[], tests_run[], tests_passed (bool), tests_failed[{file,test_name,error_excerpt}], self_assessment (1 para), open_questions[], deferred_to_followup[]`. `tests_passed=false` if ANY test failed. (Full rules in `agents/dkmvp-implementer.md` §7.)

## Evaluator VERDICT block — exact schema

Plain text, `VERDICT:` line first, then `CRITICAL_ISSUES / MAJOR_ISSUES / MINOR_NITS / ACCEPTANCE_CHECKLIST / SECURITY_CHECKS / DESIGN_FIDELITY / INDEPENDENT_TEST_RESULTS`. **APPROVED only when** CRITICAL_ISSUES empty AND every ACCEPTANCE item `met: true|n/a` AND every applicable SECURITY/DESIGN check `true` AND every INDEPENDENT_TEST `passed: true`. Else REJECTED. (Full schema in `agents/dkmvp-evaluator.md` §5.)

## Acceptance-criteria template (for phase briefs)

`- [ ] PRD §X.Y: <requirement> — <greppable/testable verification>`. Every criterion cites a PRD § and has a concrete grep or command. (See the phase briefs + `_conventions.md` for the canonical INV-1..15 greps.)

## Resume semantics

`phase_progress.log` is appended on every `DISPATCH`, `PR-OPENED`, and `PHASE-N-COMPLETE`, plus a `session_end` marker by the Stop hook. To resume after a crash: read the log; the last `DISPATCH <branch>` without a matching `PR-OPENED`/merge is the in-flight slice; `git -C .claude/worktrees/<branch> log --oneline -5` shows whether work was committed; re-dispatch the implementer in the SAME worktree (`git worktree add` is idempotent). Never re-dispatch a slice already logged merged (anti-pattern #11). A corrupted worktree: `git worktree remove --force` + re-dispatch fresh.

---
*Evaluation protocol version v1.0 — built against PRD v1.1.*
