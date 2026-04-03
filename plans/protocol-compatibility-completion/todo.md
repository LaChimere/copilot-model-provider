# Task Checklist

> Purpose: execution-phase checklist derived from `plans/{slug}/plan.md`.
> Treat this as the progress truth source.

## Task
- Summary:
  - Execute protocol-compatibility completion as a staged series of mergeable PRs across the OpenAI and Anthropic facades.
- Links:
  - `plans/protocol-compatibility-completion/research.md`
  - `plans/protocol-compatibility-completion/design.md`
  - `plans/protocol-compatibility-completion/plan.md`

## Plan Reference
- Plan version/date:
  - `plans/protocol-compatibility-completion/plan.md` — 2026-04-03
- Approved by (if applicable):
  - Gate 1 approved
  - Gate 2 approved

## Checklist
### Preparation
- [x] Sync/confirm baseline (main branch / clean state)
- [x] Confirm verification level target (L2)
- [ ] Re-verify fast-moving external requirements for:
  - Codex `responses` vs `chat/completions` wording
  - Claude Code gateway header contract
  - Anthropic thinking / streaming usage expectations

### Implementation
- [x] PR 1: Compatibility scaffolding and contract harness
  - Acceptance criteria:
    - Shared compatibility classification helpers exist.
    - Shared error-abstraction seam exists for protocol-specific envelopes.
    - Test scaffolding is ready for later PRs.
  - Evidence:
    - `src/copilot_model_provider/core/compat.py`
    - `src/copilot_model_provider/core/errors.py`
    - `tests/contract_tests/helpers.py`
    - `tests/contract_tests/test_compat_scaffolding.py`
- [ ] PR 2: OpenAI compatibility completion
  - Acceptance criteria:
    - `chat/completions` remains first-class with explicit compatibility coverage.
    - `chat/completions` contract tests cover the approved field/error/streaming behavior, including a dedicated chat streaming contract case.
    - Responses accepts `truncation` as designed.
    - OpenAI Responses `response.completed` usage is populated according to the approved rule when runtime data is available.
    - OpenAI contract tests describe the shipped supported/ignored field set.
  - Evidence:
    - Request-model diff
    - OpenAI contract test assertions
    - Chat streaming contract assertions
    - Responses usage assertions or before/after event samples
- [ ] PR 3: Anthropic correctness slice
  - Acceptance criteria:
    - Non-streaming Anthropic errors match Anthropic format.
    - `anthropic-version`, `anthropic-beta`, `X-Claude-Code-Session-Id` are accepted/surfaced as approved.
  - Evidence:
    - Anthropic error-shape assertions
    - Header-handling tests or request traces
- [ ] PR 4: Anthropic behavior slice
  - Acceptance criteria:
    - `thinking` is accepted on Anthropic requests.
    - **CHECKPOINT:** verify with runtime evidence whether `thinking` / `redacted_thinking` are returned in a structured form before implementing passthrough.
    - Thinking passthrough is implemented only if runtime evidence supports it; otherwise the plan/design is updated before merging.
    - Streaming `usage` behavior is implemented and tested.
  - Evidence:
    - Runtime checkpoint result for structured thinking behavior
    - Anthropic contract/integration assertions
    - Streaming event samples or test snapshots
- [ ] Cleanup PR: Support matrix and verification closeout
  - Acceptance criteria:
    - Docs and support matrix match shipped behavior.
    - Final verification meets L2 expectations.
  - Evidence:
    - Updated docs
    - Full verification output

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
- [ ] Run unit/contract tests: `uv run pytest -q tests/contract_tests` (attach output/excerpt)
- [ ] Run broader verification: `uv run pytest -q` (attach output/excerpt)
- [ ] Run integration or before/after checks tied to changed protocol behavior
- [ ] Capture logs/metrics if required

### Review / Packaging
- [ ] Summarize changes (what/why)
- [ ] Confirm no scope creep / unrelated cleanup
- [ ] Check whether related docs need updating (use `refresh-related-docs` if behavior, config, or API changed)
- [ ] Prepare PR description / changelog notes (if applicable)

## Evidence Log
Paste concise evidence here (commands + key lines).
- `command`: output excerpt
- before/after: evidence
- `uv run ruff check . && uv run ty check . && uv run pyright`: all checks passed
- `uv run pytest -q`: `131 passed, 2 skipped`, coverage `94.40%`

## Result
- Outcome: PR 1 scaffolding is implemented locally and ready for commit.
- Follow-ups (if any):
