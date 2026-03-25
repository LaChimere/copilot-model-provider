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
- [ ] Item 1: Land the serial foundation chain (`PR 1` -> `PR 2` -> `PR 3`)
  - Acceptance criteria:
    - base scaffold, `/v1/models`, and non-streaming chat land in order
    - shared contracts are stable enough for fan-out
    - lightweight smoke tests exist for the running app
  - Evidence:
    - pending execution
- [ ] Item 2: Fan out `feat/mvp-streaming-transport` and `feat/mvp-session-persistence`
  - Acceptance criteria:
    - both branches respect branch/worktree boundaries
    - streaming-only and storage/locking-only scopes land without touching forbidden paths
    - both branches contribute owned modules/tests only
  - Evidence:
    - pending execution
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
- [ ] Run integration/e2e or before/after check: targeted `tests/contract/**`, `tests/integration/**`, and incremental `tests/e2e/**` commands per step (attach proof)
- [ ] Confirm branch/worktree ownership boundaries were respected during fan-out and convergence
- [ ] Capture logs/metrics if required

### Review / Packaging
- [ ] Summarize changes (what/why)
- [ ] Confirm no scope creep / unrelated cleanup
- [ ] Check whether related docs need updating (use `refresh-related-docs` if behavior, config, or API changed)
- [ ] Prepare PR description / changelog notes (if applicable)

## Evidence Log
Paste concise evidence here (commands + key lines).
- pending

## Result
- Outcome:
  - Pending execution
- Follow-ups (if any):
  - None yet
