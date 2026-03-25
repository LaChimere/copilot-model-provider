# Task Checklist

> Purpose: execution-phase checklist derived from `plans/{slug}/plan.md`.
> Treat this as the progress truth source.

## Task
- Summary:
  - Execute the approved `copilot-model-provider-mvp` plan through five execution phases implemented as seven mergeable branches that build the provider MVP over `copilot-sdk`.
- Links:
  - `plans/copilot-model-provider-mvp/research.md`
  - `plans/copilot-model-provider-mvp/design.md`
  - `plans/copilot-model-provider-mvp/plan.md`
  - `docs/design.md`

## Plan Reference
- Plan version/date:
  - Parallel-work Gate 2 draft, 2026-03-25
- Approved by (if applicable):
  - Pending Gate 2 approval

## Checklist
### Preparation
- [ ] Sync/confirm baseline (main branch / clean state)
- [ ] Confirm repro or failing test exists (if bug)
- [x] Confirm verification level target (L1/L2/L3)
  - Acceptance criteria:
    - L2 is the minimum verification target for MVP execution slices with HTTP/runtime behavior.
  - Evidence:
    - captured in `plans/copilot-model-provider-mvp/plan.md`
- [x] Confirm scope boundary for provider-native APIs
  - Acceptance criteria:
    - provider-native session APIs and provider-native response-style APIs are explicitly deferred until after MVP in this plan slug.
  - Evidence:
    - captured in `plans/copilot-model-provider-mvp/design.md` and `plan.md`
- [x] Confirm tool-scope boundary for MVP
  - Acceptance criteria:
    - MVP tool support is limited to server-approved tools plus MCP.
  - Evidence:
    - captured in `plans/copilot-model-provider-mvp/research.md`, `design.md`, and `plan.md`
- [x] Confirm parallel-work boundaries
  - Acceptance criteria:
    - `PR 1` -> `PR 3` remain serial
    - fan-out starts only after the foundation chain is merged
    - convergence owner and hot-file boundaries are explicit
  - Evidence:
    - captured in `plans/copilot-model-provider-mvp/design.md` and `plan.md`

### Implementation
- [x] Item 1: Land the serial foundation chain (`PR 1` -> `PR 2` -> `PR 3`)
  - Current execution status:
    - `PR 1` completed on branch `feat/pr1-foundation-scaffold` (`76db366`)
    - model-catalog slice merged into `main` as `7c4d12c`
    - non-streaming chat slice merged into `main` as `1df9534`
  - Acceptance criteria:
    - base scaffold, `/v1/models`, and non-streaming chat land in order
    - shared contracts are stable enough for fan-out
    - lightweight smoke tests exist for the running app
  - Evidence:
    - foundation evidence: `uv run ruff check .`, `uv run pyright`, `uv run ty check .`, `uv run pytest -q`
    - model-catalog evidence: `uv run ruff check .`, `uv run pyright`, `uv run ty check .`, `uv run pytest -q`
    - non-streaming chat evidence: `uv run ruff check .`, `uv run pyright`, `uv run ty check .`, `uv run pytest -q`
- [x] Item 2: Fan out `feat/mvp-streaming-transport` and `feat/mvp-session-persistence`
  - Current execution status:
    - streaming transport slice merged into `main` as `e78c081`
    - session persistence slice merged into `main` as `f07c035`
    - follow-up type-check/test cleanup landed on `main` as `4ceb451`
  - Acceptance criteria:
    - both branches respect branch/worktree boundaries
    - streaming-only and storage/locking-only scopes land without touching forbidden paths
    - both branches contribute owned modules/tests only
  - Evidence:
    - PR #4 merged: `feat/mvp-streaming-transport` -> `main`
    - PR #5 merged: `feat/mvp-session-persistence` -> `main`
    - both branches passed branch-scoped validation before merge and review findings were resolved before landing
- [ ] Item 3: Converge streaming and session branches
  - Acceptance criteria:
    - hot files are integrated by the convergence owner
    - streaming + resumed-follow-up E2E passes
    - locking/ownership behavior is covered by focused tests
  - Evidence:
    - pending execution
- [ ] Item 4: Land `feat/mvp-tools-mcp`
  - Acceptance criteria:
    - server-approved tool and MCP flows succeed at the agreed MVP depth
    - forbidden-path boundaries are respected
  - Evidence:
    - pending execution
- [ ] Item 5: Final cleanup and MVP release-gate E2E
  - Acceptance criteria:
    - release-gate scenarios pass
    - no temporary scaffolding is left undocumented
  - Evidence:
    - pending execution

### Acceptance Gate (before proposing PR)
- [ ] All acceptance criteria above are met with evidence
- [ ] Diff is consistent with approved plan (no scope creep, no missing pieces)
- [ ] Applicable verification level executed

If any check fails, follow the recovery flow defined in `AGENTS.md` (Verification rules → Acceptance criteria):
1. Can fix directly → fix and re-verify
2. Plan is infeasible → update `plan.md`, re-submit for Gate 2
3. Design is invalid → update `design.md`, re-submit for Gate 1 → Gate 2
4. Stuck → stop and report to user with evidence of what was attempted

### Verification (Evidence)
- [ ] Run lint/typecheck: `uv run ruff check . && uv run pyright && uv run ty check .` (attach output/excerpt)
- [ ] Run unit tests: targeted `tests/unit/**` commands (attach output/excerpt)
- [ ] Run integration/e2e or before/after check: targeted `tests/contract/**`, `tests/integration_tests/**`, and incremental `tests/integration_tests/**` commands per step (attach proof)
- [ ] Confirm branch/worktree ownership boundaries were respected during fan-out and convergence
- [ ] Capture logs/metrics if required

### Review / Packaging
- [ ] Summarize changes (what/why)
- [ ] Confirm no scope creep / unrelated cleanup
- [ ] Check whether related docs need updating (use `refresh-related-docs` if behavior, config, or API changed)
- [ ] Prepare PR description / changelog notes (if applicable)

## Evidence Log
Paste concise evidence here (commands + key lines).
- non-streaming chat slice:
  - `uv run ruff check . && uv run pyright && uv run ty check . && uv run pytest -q`
  - `35 passed`
  - `Required test coverage of 90% reached. Total coverage: 95.81%`
- streaming transport slice:
  - merged as `e78c081` via PR #4
  - branch-scoped validation and review-fix pass completed before merge
- session persistence slice:
  - merged as `f07c035` via PR #5
  - branch-scoped validation completed before merge; post-merge type-check cleanup landed as `4ceb451`

## Result
- Outcome:
  - Step 1 and Step 2 are complete on `main`; the next planned stage is convergence of streaming and session work.
- Follow-ups (if any):
  - Start the convergence branch for Step 3 and integrate the shared hot files plus combined streaming/resume validation.
