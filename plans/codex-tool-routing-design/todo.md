# Task Checklist

> Purpose: execution checklist derived from `plans/codex-tool-routing-design/plan.md`.

## Task

- Summary:
  - Implement first-class tool-aware client-passthrough routing so Codex/Desktop
    and Anthropic-style clients share one explicit provider routing policy.
- Links:
  - `plans/codex-tool-routing-design/research.md`
  - `plans/codex-tool-routing-design/design.md`
  - `plans/codex-tool-routing-design/plan.md`

## Checklist

### Base routing-policy slice

- [x] Extract the base-only slice from the current mixed working tree before
      landing protocol-specific follow-up work.
- [x] Add canonical tool-routing hint and policy types.
- [x] Add `tool_routing_policy` to `CanonicalChatRequest`.
- [x] Define derivation rules for `none` vs `client_passthrough`.
- [x] Reject orphaned tool-result continuations.
- [x] Reject invalid continuation `session_id` values that do not match a live
      provider session.
- [x] Ensure non-tool requests derive a no-op routing policy.
- [x] Move runtime built-in suppression and guidance injection behind the policy.
- [x] Update `core/compat.py` to match actual tool-routing support.
- [x] Add targeted unit coverage for policy derivation and runtime consumption.

### OpenAI Responses routing slice

- [x] Derive Responses routing policy during normalization.
- [x] Preserve `function`, `web_search`, and `custom` tool surfaces.
- [x] Preserve narrow Responses routing hints.
- [x] Keep response-visible tools aligned with runtime-visible tools.
- [x] Add exact Codex replay-style regression coverage.

### Anthropic Messages alignment slice

- [x] Derive Anthropic tool-aware routing through the shared policy.
- [x] Keep Anthropic continuation behavior on the shared runtime base.
- [x] Add Anthropic contract/integration coverage for the shared policy path.

### Multi-tool batching follow-up

- [x] Land the shared multi-tool batching implementation across runtime,
      translators, OpenAI Responses, and Anthropic Messages.
- [x] Add unit and contract coverage for batched continuation result handling
      across OpenAI Responses and Anthropic Messages.
- [x] Add container-backed integration coverage for the multi-tool batching
      slice.
- [x] Re-run final repo validation for the multi-tool batching slice.

### Verification

- [x] Run targeted unit tests for the base slice.
- [x] Run targeted Responses contract/integration tests.
- [x] Run targeted Anthropic contract/integration tests.
- [x] Run `uv run ruff format --check .`.
- [x] Run `uv run ruff check .`.
- [x] Run `uv run ty check .`.
- [x] Run `uv run pyright`.
- [x] Run `uv run pytest -q`.
