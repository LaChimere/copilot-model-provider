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
- [x] PR 2: OpenAI compatibility completion
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
- [x] PR 3: Anthropic correctness slice
  - Acceptance criteria:
    - Non-streaming Anthropic errors match Anthropic format.
    - `anthropic-version`, `anthropic-beta`, `X-Claude-Code-Session-Id` are accepted/surfaced as approved.
  - Evidence:
    - Anthropic error-shape assertions in `tests/contract_tests/test_anthropic_messages.py`
    - Header normalization/logging assertions in `tests/contract_tests/test_anthropic_messages.py`
- [x] PR 4: Anthropic behavior slice
  - Acceptance criteria:
    - `thinking` is accepted on Anthropic requests.
    - Runtime checkpoint evidence is recorded, and the current runtime path is documented as not surfacing structured `thinking` / `redacted_thinking` blocks for passthrough.
    - `thinking` remains accept-ignore on the current runtime path rather than being silently rejected.
    - Streaming `usage` behavior is implemented and tested.
  - Evidence:
    - Runtime checkpoint result captured from a live `claude-sonnet-4.6` SDK session probe
    - Anthropic contract assertions in `tests/contract_tests/test_anthropic_messages.py`
    - Streaming usage assertions in `tests/contract_tests/test_anthropic_messages.py`
- [x] Cleanup PR: Support matrix and verification closeout
  - Acceptance criteria:
    - Docs and support matrix match shipped behavior.
    - Final verification meets L2 expectations.
  - Evidence:
    - `README.md`
    - `docs/design.md`
    - Final validation + review evidence below

### Acceptance Gate (before proposing PR)
- [x] All acceptance criteria above are met with evidence
- [x] Diff is consistent with approved plan (no scope creep, no missing pieces)
- [x] Applicable verification level executed

If any check fails, follow the recovery flow defined in `AGENTS.md` (Verification rules → Acceptance criteria):
1. Can fix directly → fix and re-verify
2. Plan is infeasible → update `plan.md`, re-submit for Gate 2
3. Design is invalid → update `design.md`, re-submit for Gate 1 → Gate 2
4. Stuck → stop and report to user with evidence of what was attempted

### Verification (Evidence)
- [x] Run lint/typecheck: `uv run ruff check . && uv run pyright && uv run ty check .` (attach output/excerpt)
- [x] Run unit/contract tests via the full suite path: `uv run pytest -q` (covers `tests/contract_tests`)
- [x] Run broader verification: `uv run pytest -q` (attach output/excerpt)
- [x] Run integration or before/after checks tied to changed protocol behavior
- [x] Capture logs/metrics if required (not required for this slice)

### Review / Packaging
- [x] Summarize changes (what/why)
- [x] Confirm no scope creep / unrelated cleanup
- [x] Check whether related docs need updating (use `refresh-related-docs` if behavior, config, or API changed)
- [x] Prepare PR description / changelog notes (if applicable)

## Evidence Log
Paste concise evidence here (commands + key lines).
- `command`: output excerpt
- before/after: evidence
- `uv run ruff check . && uv run ty check . && uv run pyright`: all checks passed
- `uv run pytest -q`: `131 passed, 2 skipped`, coverage `94.40%`
- OpenAI external re-check: current Codex guidance still centers `responses`; provider keeps `chat/completions` first-class for broader clients
- `uv run pytest -q`: `133 passed, 2 skipped`, coverage `94.38%`
- Anthropic external re-check: current Messages / Claude Code gateway docs still require `anthropic-version`, preserve `anthropic-beta`, and use `X-Claude-Code-Session-Id` for session tracking
- `uv run pytest -q`: `137 passed, 2 skipped`, coverage `94.47%`
- Runtime checkpoint: Copilot SDK session API exposes `reasoning_effort` but not Anthropic-native `thinking`; live `claude-sonnet-4.6` probe returned no structured `thinking` / `redacted_thinking` / `reasoningText` / `reasoningOpaque` blocks, but did emit `assistant.usage`
- `uv run pytest -q tests/integration_tests/test_chat.py::test_container_chat_completion_supports_live_model_id tests/integration_tests/test_responses.py::test_container_responses_non_streaming_supports_live_model_id tests/integration_tests/test_responses.py::test_container_responses_streaming_emits_expected_lifecycle`: `3 passed`
- `uv run ruff format --check . && uv run ruff check . && uv run ty check . && uv run pyright && uv run pytest -q`: `141 passed, 2 skipped`, coverage `94.41%`
- Cleanup docs refresh: `README.md` and `docs/design.md` now describe the shipped OpenAI `responses` / `chat` surface, Anthropic `messages` / `count_tokens` surface, gateway headers, protocol-specific errors, streaming usage, and current `thinking` accept-ignore behavior
- Claude Opus 4.6 cleanup review: no significant issues found; doc claims verified against implementation
- Final cleanup validation: `uv run ruff format --check . && uv run ruff check . && uv run ty check . && uv run pyright && uv run pytest -q`: `141 passed, 2 skipped`, coverage `94.41%`

## Result
- Outcome: Protocol compatibility completion is fully implemented and documented across all planned staged commits.
- Follow-ups (if any): None.
