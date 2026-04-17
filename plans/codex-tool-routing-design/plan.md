# Plan

> Purpose: execution plan derived from the approved Codex tool-routing design.

## Objective

Deliver Codex/Desktop-style tool routing as a first-class provider capability by
introducing an explicit tool-aware client-passthrough routing policy, then
landing protocol-specific integration on top of that shared base.

## Constraints

- Keep the provider thin: no provider-owned tool or MCP execution.
- Preserve existing text-only flows.
- Keep OpenAI Responses and Anthropic Messages aligned on one shared routing
  policy rather than two parallel implementations.
- Keep unit/integration coverage above the repository's 90% gate.
- Do not merge the current mixed working tree as one large final review unit.

## Execution plan

### 1. Base routing-policy slice

- First extract a **base-only** diff from the current mixed working tree and
  treat the rest as protocol-specific follow-up work.
- If a shared helper or canonical-contract change would otherwise leave the
  repository type-incorrect, include the smallest directly coupled route
  adjustment in this slice, but keep contract/integration coverage in the later
  protocol slices.
- Add explicit canonical routing types for tool-aware sessions.
- Extend `CanonicalChatRequest` with a typed routing-policy field.
- Derive policy during protocol normalization instead of reconstructing it in
  runtime ad hoc.
- Move runtime built-in suppression, guidance injection, and tool-aware session
  decisions behind that policy object.
- Update `core/compat.py` so supported routing behavior is described honestly.
- Add targeted unit coverage for:
  - policy derivation
  - `none` vs `client_passthrough`
  - orphaned tool-result continuation rejection
  - invalid continuation `session_id` rejection
  - no-op policy derivation for non-tool requests
  - runtime consumption of the policy

### 2. OpenAI Responses routing slice

- Route Responses requests through the new canonical policy.
- Preserve `function`, `web_search`, and `custom` tool surfaces.
- Preserve narrow routing hints (`tool_choice`, `parallel_tool_calls`) as typed
  policy hints.
- Keep response-visible tool surfaces aligned with runtime-visible tool surfaces.
- Add/keep exact Codex replay-style regression coverage on top of the base.

### 3. Anthropic Messages alignment slice

- Route Anthropic tool-aware requests through the same canonical policy.
- Keep Anthropic-specific continuation logic on top of the shared base rather
  than introducing a second policy implementation.
- Add/keep Anthropic continuation coverage to ensure the base policy does not
  regress Claude-style flows.

### 4. Final verification and optional follow-up

- Run full repository validation once the base plus both protocol slices land.
- Reassess whether any prompt-bridge refinement is still needed after the shared
  policy is in place.
- Update external docs only if shipped behavior changes need to be documented.

## Validation commands

- Base slice:
  - `uv run pytest -q tests/unit_tests/test_copilot_runtime.py`
  - `uv run pytest -q tests/unit_tests/test_responses.py`
- OpenAI slice:
  - `uv run pytest -q tests/contract_tests/test_openai_responses.py`
  - `uv run pytest -q tests/integration_tests/test_responses.py`
- Anthropic slice:
  - `uv run pytest -q tests/contract_tests/test_anthropic_messages.py`
  - `uv run pytest -q tests/integration_tests/test_anthropic_messages.py`
- Final validation:
  - `uv run ruff format --check .`
  - `uv run ruff check .`
  - `uv run ty check .`
  - `uv run pyright`
  - `uv run pytest -q`

## Merge order

1. base routing-policy slice
2. OpenAI Responses routing slice
3. Anthropic Messages alignment slice
4. final verification / optional docs

## Notes

- `tool_choice` and `parallel_tool_calls` are preserved as routing hints in the
  base design; they are not yet a promise of full provider-enforced semantics.
- The current branch is an evidence/design branch, not the final PR shape; each
  implementation slice should be re-extracted into a reviewable diff.
- If prompt/system-message refinement is still desirable after the base policy
  lands, treat it as a follow-up slice rather than broadening the base PR.
