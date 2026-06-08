# DKMV Platform — Self-Evaluation Prompt (reuse on every refinement pass)

Dispatch a fresh Opus sub-agent with the prompt below (the methodology's Step-10 evaluator, adapted to this project: prefix `dkmvp`, plan dir `docs/implementation/platform/`, PRD `docs/design_docs/platform/PRD_dkmv_platform_v1.md`). Save the report to `docs/implementation/platform/self-eval-pass-N.md`.

```
You are an unbiased evaluator. Read these files:
1. docs/implementation/platform/README.md
2. docs/implementation/platform/orchestration.md
3. docs/implementation/platform/evaluation_protocol.md
4. docs/implementation/platform/CLAUDE_CODE_PROMPT.md
5. docs/implementation/platform/phase_0_foundation.md  (first)
6. docs/implementation/platform/phase_2_run_lifecycle.md  (a middle phase)
7. docs/implementation/platform/phase_5_scale_ship.md  (last)
8. docs/implementation/platform/agents/dkmvp-implementer.md
9. docs/implementation/platform/agents/dkmvp-evaluator.md
10. docs/implementation/platform/claude-code-research.md

Evaluate against these criteria:
A. Claude Code feature reality — does every claimed feature actually exist (per claude-code-research.md)?
   - Dispatch tool is Agent (Task alias); the dispatch passes subagent_type/description/prompt (model lives in frontmatter, per-call model optional)
   - Sub-agent frontmatter uses only real fields (name, description, model, tools; isolation/color are real; context/disable-model-invocation are SKILL fields, not agent fields)
   - Skill frontmatter uses name/description/allowed-tools (hyphenated)
   - Hook scripts read stdin via jq (not env vars); exit 2 blocks
   - MCP install is user-level, attaches on next session (GitHub MCP hosted-HTTP form)
   - Worktree creation is via Bash, not a dispatch parameter
B. Bootstrap chicken-and-egg — can the orchestrator actually start?
   - Sub-agent files exist (staged + copied at pre-flight, not Phase 0)
   - GitHub MCP attaches before first dispatch
   - Phase 0 doesn't reference itself for its own bootstrap
   - phase_progress.log has a missing-file fallback (the Stop hook seeds it)
C. Brief specificity — can the evaluator gate on the acceptance criteria?
   - Every acceptance criterion is greppable or testable (cites a PRD § + a grep/command)
   - Every SECURITY_CHECK has a concrete grep (the INV-1..15 patterns)
   - Independent verification commands are real and executable (ruff/mypy/pytest, tsc/vitest)
D. Cross-file consistency
   - Phase brief PRD citations resolve to real PRD sections (spot-check PRD_dkmv_platform_v1.md)
   - The master prompt's references match the plan-file structure (phase names, agent names, paths)
   - Sub-agent cross-references are accurate (skills exist; invariants match _conventions.md)
E. Slice conflicts
   - No two slices in the same wave edit the same file
   - Wave plans correctly identify sequential dependencies (incl. the 4.1-before-2.2 cross-phase pull)
F. Resume / failure
   - Mid-phase orchestrator crash has a documented resume path
   - Engine-ask / PRD-change / sandbox-prereq failures have escalation categories
   - Solo serialized-PR + reviewer-absent handling is present
Plus project-specific: do the system invariants (INV-1..15) and the verdict checks correctly encode the PRD's load-bearing rules — segment-sum meter, no-re-attach recovery, resolve-once HITL, capability-aware Codex cost, SQLite no-SKIP-LOCKED idempotency, set_agent_state (no PATCH .../label), SSE cookie auth, gVisor+egress, engine-locked?

Report in this structure:
1. BLOCKERS (orchestrator fails on first dispatch)
2. CRITICAL (fails later but inevitably)
3. MEDIUM (friction or wrong choices)
4. NICE-TO-HAVE
5. WHAT'S WORKING WELL
6. VERDICT: APPROVED FOR USE / NEEDS REVISION / NEEDS REWRITE
Cite file paths and line numbers. Under 2500 words.
```
