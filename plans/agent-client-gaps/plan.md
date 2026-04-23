# Feature Plan

> Purpose: translate the approved `plans/agent-client-gaps/design.md` into a
> reviewable staged delivery plan. Do not implement until this plan is approved.

## Feature summary
- Summary:
  - Centralize paused-turn continuation bookkeeping into one shared full-batch
    semantic core while preserving current OpenAI Responses and Anthropic
    Messages behavior on the existing thin-gateway boundary.
- Main constraints:
  - keep the provider thin: no provider-owned tool execution, MCP execution, or
    durable-by-default runtime resume
  - keep runtime reuse authoritative for continuation-context validation
  - preserve current full-batch continuation behavior; do not add public
    partial-result acknowledgement semantics in this slice
  - preserve current OpenAI Responses `previous_response_id` / replay behavior
    and current Anthropic full-batch tool-result behavior
  - align `docs/design.md` with the shipped canonical request shape as part of
    the base shared-store slice
- Why this split was chosen:
  - the shared paused-turn store, runtime seam, and docs alignment form a small
    but review-critical base that both protocol integrations depend on
  - OpenAI Responses and Anthropic Messages can then migrate separately on top of
    that base while preserving protocol-specific edge behavior
  - cleanup stays last so the repository remains trunk-safe at every
    intermediate merge point

## PR sequence
### PR 1: Shared paused-turn core and runtime seam
- Goal:
  - Introduce the shared paused-turn store contract, in-memory implementation,
    atomic resolve/consume semantics, and the runtime cleanup seam needed for
    later protocol integrations, while keeping current northbound behavior
    unchanged.
- Likely directories/files:
  - `src/copilot_model_provider/core/`
  - `src/copilot_model_provider/api/shared.py`
  - `src/copilot_model_provider/runtimes/copilot_runtime.py`
  - `docs/design.md`
  - `tests/unit_tests/`
- Dependencies:
  - None
- Allowed changes:
  - shared paused-turn models / store protocol / in-memory store
  - runtime seam for store-driven expiry and runtime-session cleanup
  - shared atomic resolve/consume contract
  - `docs/design.md` canonical-request alignment
  - targeted unit coverage for the new shared contract
- Prohibited changes:
  - no intentional OpenAI Responses or Anthropic Messages behavior changes yet
  - no public partial-result continuation semantics
  - no durable backend implementation
  - no unrelated prompt / model-routing redesign
- Acceptance criteria:
  - a shared paused-turn store abstraction exists and is ready to back both
    protocol routes
  - the shared paused-turn record preserves the base-slice continuation-affinity
    data required by the approved design:
    - `session_id`
    - `tool_ids`
    - `request_model_id`
    - `runtime_model_id`
    - `auth_context_fingerprint`
    - `expires_at`
  - shared continuation logic preserves enough continuation-affinity data for
    early drift detection in the base slice:
    - request model id
    - resolved runtime model id
    - auth context
  - `auth_context_fingerprint` uses the same auth-context key format already used
    by the current auth-context cache path, and the shared store does not persist
    raw auth tokens
  - baseline verification records the current route-local behavior for repeated
    and concurrent continuation attempts against the same paused turn before
    PR 1 implementation begins
  - regardless of that baseline, PR 1 lands the atomic paused-turn consume
    guarantee required by the approved design in the shared store layer
  - if that baseline reveals a duplicate-resume race in the current route-local
    path, PR 1 documents closing that race as explicit base-slice correctness
    hardening for repeated/concurrent attempts rather than presenting it as
    ordinary-flow behavior preservation
  - paused-turn resolution/consumption is defined as atomic at per-turn scope,
    including dedicated store-level coverage that proves repeated or concurrent
    consume attempts cannot trigger duplicate runtime resumes
  - runtime cleanup can be triggered from shared paused-turn expiry without
    route-local TTL ownership
  - `docs/design.md` documents the full shipped canonical request shape,
    including:
    - `request_id`
    - `conversation_id`
    - `session_id`
    - `runtime_auth_token`
    - `model_id`
    - `messages`
    - `tool_definitions`
    - `tool_results`
    - `tool_routing_policy`
    - `stream`
  - for ordinary sequential full-batch continuation flows, trunk behavior
    remains unchanged because no route has migrated yet, and existing OpenAI
    Responses / Anthropic Messages contract behavior still passes through the
    old route-local continuation wiring
- Validation commands:
  - `uv run ruff check .`
  - `uv run pyright`
  - `uv run ty check .`
  - `uv run pytest -q tests/unit_tests`
  - `uv run pytest -q tests/contract_tests/test_openai_responses.py tests/contract_tests/test_anthropic_messages.py`
- Mergeability notes:
  - must merge as a no-op foundation PR for ordinary route behavior: shared
    contracts land, but client-visible continuation behavior stays on the old
    route-local wiring until later PRs
  - if baseline verification exposes a duplicate-resume race in the current
    route-local path, PR 1 may close that correctness gap in the shared store,
    but the PR description and evidence must call it out explicitly as
    repeated/concurrent correctness hardening instead of presenting it as pure
    preservation

### PR 2: OpenAI Responses shared-store migration
- Goal:
  - Move OpenAI Responses paused-turn bookkeeping onto the shared store while
    preserving current `previous_response_id` / replay / mismatch behavior and
    current full-batch continuation semantics.
- Likely directories/files:
  - `src/copilot_model_provider/api/openai/responses.py`
  - `src/copilot_model_provider/core/`
  - `src/copilot_model_provider/api/shared.py`
  - `tests/contract_tests/test_openai_responses.py`
  - `tests/integration_tests/test_responses.py`
- Dependencies:
  - PR 1
- Allowed changes:
  - OpenAI Responses route migration from route-local pending dicts to shared
    store usage
  - OpenAI-specific lookup/index plumbing for `previous_response_id`
  - OpenAI regression/contract/integration coverage updates
- Prohibited changes:
  - no Anthropic route changes
  - no public partial-result continuation semantics
  - no durable backend work
  - no broader Responses failure-lifecycle expansion
- Acceptance criteria:
  - OpenAI Responses no longer owns route-local paused-turn bookkeeping as the
    primary state source
  - current `previous_response_id` lookup behavior is preserved
  - current mismatch rejection for mismatched tool-result submissions is preserved
  - historical replay ignore behavior is preserved
  - current full pending tool-batch requirement remains unchanged
  - repeated / concurrent continuations do not trigger duplicate runtime resumes
  - repeated / concurrent continuations surface consumed / invalid outcomes
    rather than re-entering runtime reuse
  - contract/integration coverage explicitly exercises repeated and concurrent
    continuation attempts against the same paused turn
- Validation commands:
  - `uv run ruff check .`
  - `uv run pyright`
  - `uv run ty check .`
  - `uv run pytest -q tests/contract_tests/test_openai_responses.py tests/integration_tests/test_responses.py`
- Mergeability notes:
  - mergeable once OpenAI-only behavior remains stable on the shared base, even
    before Anthropic migrates

### PR 3: Anthropic Messages shared-store migration
- Goal:
  - Move Anthropic Messages paused-turn bookkeeping onto the shared store while
    preserving current full-batch `tool_result` continuation behavior and current
    route-specific error handling.
- Likely directories/files:
  - `src/copilot_model_provider/api/anthropic/messages.py`
  - `src/copilot_model_provider/core/`
  - `src/copilot_model_provider/api/shared.py`
  - `tests/contract_tests/test_anthropic_messages.py`
  - `tests/integration_tests/`
- Dependencies:
  - PR 1
- Allowed changes:
  - Anthropic route migration from route-local pending dicts to shared store usage
  - Anthropic-specific lookup/index plumbing if needed for `tool_use_id`
  - Anthropic regression/contract/integration coverage updates
- Prohibited changes:
  - no OpenAI Responses behavior changes
  - no partial-result continuation semantics
  - no durable backend work
  - no broader Anthropic feature expansion
- Acceptance criteria:
  - Anthropic Messages no longer owns route-local paused-turn bookkeeping as the
    primary state source
  - current full pending tool-result batch requirement is preserved
  - duplicate-result rejection remains enforced
  - repeated / concurrent continuations do not trigger duplicate runtime resumes
  - repeated / concurrent continuations surface consumed / invalid outcomes
    rather than re-entering runtime reuse
  - contract/integration coverage explicitly exercises repeated and concurrent
    continuation attempts against the same paused turn
  - Anthropic route behavior remains aligned with the shared full-batch base
- Validation commands:
  - `uv run ruff check .`
  - `uv run pyright`
  - `uv run ty check .`
  - `uv run pytest -q tests/contract_tests/test_anthropic_messages.py`
- Mergeability notes:
  - mergeable independently of OpenAI once it preserves current Anthropic
    behavior on the shared store base

### Cleanup PR: Shared continuation cleanup and verification closeout
- Goal:
  - Remove leftover duplicated continuation helpers/tasks, align docs/support
    surfaces with the shipped base slice, and run the final verification pass.
- Likely directories/files:
  - `src/copilot_model_provider/api/openai/`
  - `src/copilot_model_provider/api/anthropic/`
  - `src/copilot_model_provider/core/`
  - `README.md`
  - `docs/design.md`
  - `tests/`
  - `plans/agent-client-gaps/`
- Dependencies:
  - PR 2 and PR 3 (both must be merged before cleanup begins)
- Allowed changes:
  - remove leftover duplicated route-local continuation helpers
  - final docs/support-matrix refresh tied to shipped behavior
  - final verification-only test adjustments
- Prohibited changes:
  - no new continuation semantics
  - no partial accumulation
  - no durable backend implementation
- Acceptance criteria:
  - no route-local paused-turn bookkeeping remains as the shipped source of truth
  - docs and support surfaces describe the shipped shared-store/full-batch
    behavior rather than the pre-migration behavior
  - final repo validation meets the approved verification level
- Validation commands:
  - `uv run ruff format --check .`
  - `uv run ruff check .`
  - `uv run ty check .`
  - `uv run pyright`
  - `uv run pytest -q`
- Mergeability notes:
  - must be last so docs and cleanup describe shipped behavior, not in-progress
    migration state

## Parallelization readiness
- Must stay serial:
  - PR 1 must land first because it defines the shared store contract and runtime
    seam that both protocol migrations depend on
  - Cleanup PR must land last and should not begin until both PR 2 and PR 3 are merged
- Can fan out after the base PR lands:
  - PR 2 (OpenAI Responses) and PR 3 (Anthropic Messages) can proceed in parallel
    after PR 1 if ownership boundaries are explicit and shared-base churn stops
  - This is readiness guidance only; use `plan-parallel-work` for explicit
    agent/branch/worktree ownership

## Risks
- Contract churn in `core/` and `runtimes/` could create merge conflicts or
  hidden behavior drift if the base PR grows too broad
- OpenAI replay preservation is correctness-sensitive and can regress easily if
  route-specific lookup behavior is over-centralized
- Anthropic migration can appear simpler than OpenAI, but still risks divergence
  if duplicate/full-batch validation is not kept on the shared base
- Docs alignment can get dropped unless it is treated as part of PR 1 rather than
  as optional cleanup
- Auth-context fingerprint implementation must exactly match the existing
  auth-context cache key format; a divergent fingerprint scheme would silently
  break continuation affinity even if the store shape and tests looked plausible

## Rollback
- PR 1 is a no-op foundation and can be reverted independently if the shared
  store abstraction proves wrong without changing northbound behavior
- PR 2 and PR 3 are independently revertible because each preserves one protocol
  surface on top of the shared base
- Cleanup PR should avoid bundling new behavior so it can be reverted without
  losing the underlying shared-store migrations
