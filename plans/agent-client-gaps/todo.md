# Task Checklist

> Purpose: execution checklist derived from
> `plans/agent-client-gaps/plan.md`.
> Treat this as the progress truth source once Gate 2 is approved.

## Task
- Summary:
  - Implement the approved shared paused-turn store design as a staged sequence
    of mergeable PRs while preserving current full-batch agent-client
    compatibility behavior.
- Links:
  - `plans/agent-client-gaps/research.md`
  - `plans/agent-client-gaps/design.md`
  - `plans/agent-client-gaps/plan.md`

## Plan Reference
- Plan version/date:
  - `plans/agent-client-gaps/plan.md` — 2026-04-19
- Approval status:
  - Gate 1 approved
  - Gate 2 approved

## Checklist
### Preparation
- [x] Reconfirm that the approved design still matches the repo before coding.
- [x] Reconfirm that deferred items stay out of scope:
  - public partial-result continuation
  - durable backend implementation
  - broader failure-lifecycle expansion
- [x] Reconfirm the current Responses replay / Anthropic full-batch behavior with
      targeted tests before changing route wiring.
- [x] Establish the current repeated/concurrent continuation baseline before the
      shared-store refactor:
  - run a targeted sequential duplicate-attempt check against the same paused turn
  - run a targeted concurrent-attempt check against the same paused turn
  - determine whether the current route-local bookkeeping prevents duplicate
    runtime resume, permits it, or fails in another observable way
  - record the baseline evidence in the Evidence Log before PR 1 starts so the
    shared-store migration does not accidentally preserve a known race as if it
    were required behavior
  - record, before PR 1 implementation begins, whether repeated/concurrent
    atomicity in PR 1 is preserving an already-safe path or explicitly hardening
    a discovered race in the current route-local path

### Implementation
- [x] PR 1: Shared paused-turn core and runtime seam
  - Acceptance criteria:
    - Shared paused-turn store protocol and in-memory implementation exist.
    - `PausedTurnRecord` preserves the base-slice continuation-affinity fields:
      `session_id`, `tool_ids`, `request_model_id`, `runtime_model_id`,
      `auth_context_fingerprint`, and `expires_at`.
    - Shared continuation logic preserves enough continuation-affinity data for
      early drift detection:
      - request model id
      - resolved runtime model id
      - auth context
    - `auth_context_fingerprint` uses the same auth-context key format as the
      existing auth-context cache path, and the shared store does not persist raw
      auth tokens.
    - The repeated/concurrent continuation baseline is recorded before PR 1
      implementation begins.
    - PR 1 lands atomic paused-turn resolve/consume semantics as a base-slice
      requirement, including dedicated shared-store unit coverage proving:
      - repeated/concurrent attempts return consumed/invalid outcomes instead of
        triggering duplicate runtime resume
      - at most one continuation attempt can consume the same paused turn
    - if baseline evidence exposed a duplicate-resume race in the current
      route-local path, PR 1 records that repeated/concurrent hardening
      explicitly instead of describing it as ordinary-flow preservation
    - Runtime cleanup seam exists for store-driven expiry.
    - `docs/design.md` canonical request section matches the full shipped field
      set:
      `request_id`, `conversation_id`, `session_id`, `runtime_auth_token`,
      `model_id`, `messages`, `tool_definitions`, `tool_results`,
      `tool_routing_policy`, and `stream`, plus any additional shipped
      `CanonicalChatRequest` fields if the implementation grows before PR 1 lands.
    - For ordinary sequential full-batch continuation flows, OpenAI Responses and
      Anthropic Messages northbound behavior remains unchanged because neither
      route has migrated to the shared store yet.
  - Evidence:
    - shared store code paths in `src/copilot_model_provider/core/`
    - `PausedTurnRecord` / shared-store model definitions showing the required
      continuation-affinity fields
    - code-path comparison showing `auth_context_fingerprint` uses the identical
      derivation/key shape as `ModelRouter._build_cache_key` in
      `src/copilot_model_provider/core/routing.py`, specifically
      `token:{sha256_hexdigest(runtime_auth_token)}` for authed requests and the
      current default-auth sentinel otherwise, without persisting raw tokens
    - runtime seam in `src/copilot_model_provider/runtimes/copilot_runtime.py`
    - updated `docs/design.md` canonical request section showing the full shipped
      field set
    - baseline evidence for sequential/concurrent duplicate attempts before PR 1,
      plus the recorded conclusion captured before PR 1 implementation begins
    - dedicated shared-store unit coverage proving single-consume atomicity and no
      duplicate runtime resume on repeated/concurrent consume attempts
    - code-path evidence showing OpenAI Responses and Anthropic Messages still use
      their existing route-local pending-session bookkeeping during PR 1 rather
      than calling the shared-store migration path
    - before/after regression evidence showing ordinary sequential OpenAI
      Responses / Anthropic Messages behavior remains unchanged before route
      migration

- [x] PR 2: OpenAI Responses shared-store migration
  - Acceptance criteria:
    - Responses uses the shared paused-turn store as its primary state source.
    - `previous_response_id` lookup is preserved.
    - mismatch rejection and historical replay ignore behavior are preserved.
    - full pending tool-batch requirement is unchanged.
    - duplicate runtime resume does not occur on repeated/concurrent continuations.
    - repeated/concurrent continuations surface consumed/invalid outcomes instead
      of re-entering runtime reuse.
    - regression coverage explicitly exercises repeated/concurrent continuation
      attempts against the same paused turn.
  - Evidence:
    - `src/copilot_model_provider/api/openai/responses.py`
    - OpenAI contract/integration assertions, including `previous_response_id`,
      mismatch rejection, historical replay ignore, and repeated/concurrent
      continuation cases

- [x] PR 3: Anthropic Messages shared-store migration
  - Acceptance criteria:
    - Anthropic Messages uses the shared paused-turn store as its primary state source.
    - full pending tool-result batch requirement is preserved.
    - duplicate-result rejection remains enforced.
    - duplicate runtime resume does not occur on repeated/concurrent continuations.
    - repeated/concurrent continuations surface consumed/invalid outcomes instead
      of re-entering runtime reuse.
    - regression coverage explicitly exercises repeated/concurrent continuation
      attempts against the same paused turn.
  - Evidence:
    - `src/copilot_model_provider/api/anthropic/messages.py`
    - Anthropic contract/integration assertions, including full-batch
      `tool_result`, duplicate-result rejection, and repeated/concurrent
      continuation cases

- [x] Cleanup PR: Shared continuation cleanup and verification closeout
  - Acceptance criteria:
    - leftover duplicated route-local continuation helpers are removed
    - docs/support surfaces match shipped shared-store behavior
    - cleanup starts only after both protocol migrations have landed
    - final verification meets the approved level
  - Evidence:
    - cleaned route/core files
    - refreshed docs
    - final validation output

### Acceptance Gate (before proposing execution complete)
- [x] All planned PR acceptance criteria are met with evidence.
- [x] Deferred items remained out of scope:
  - no public partial-result acknowledgement semantics were added
  - no durable backend/persistence layer was introduced as part of the shipped slice
  - no broader failure-lifecycle expansion was bundled into these PRs
- [x] Shared-store diff stayed consistent with the approved design.
- [x] Verification level executed for each landed slice and for final closeout.

If any check fails:
1. Fix directly if the approved plan still works.
2. Update `plan.md` and resubmit for Gate 2 if the execution split changed.
3. Update `design.md` and resubmit for Gate 1 if the design itself changed.
4. Stop and report with evidence if blocked.

### Verification
- [x] PR 1 targeted checks:
  - `uv run ruff check .`
  - `uv run pyright`
  - `uv run ty check .`
  - `uv run pytest -q tests/unit_tests`
  - `uv run pytest -q tests/contract_tests/test_openai_responses.py tests/contract_tests/test_anthropic_messages.py`
  - verify the sequential/concurrent duplicate-attempt baseline and the
    preservation-vs-hardening note were recorded in the Evidence Log before PR 1
    implementation began
  - verify the PR 1 test scope includes dedicated atomic consume coverage and
    proves no northbound OpenAI/Anthropic behavior change before route migration
  - verify the atomic consume coverage lives at the shared-store unit-test level,
    not only through route integration coverage
  - if the baseline exposed a duplicate-resume race, record PR 1 as intentional
    repeated/concurrent correctness hardening for that race case rather than as
    pure no-op preservation
- [x] PR 2 targeted checks:
  - `uv run ruff check .`
  - `uv run pyright`
  - `uv run ty check .`
  - `uv run pytest -q tests/contract_tests/test_openai_responses.py tests/integration_tests/test_responses.py`
  - verify the OpenAI suite includes repeated/concurrent continuation attempts
    against the same paused turn
- [x] PR 3 targeted checks:
  - `uv run ruff check .`
  - `uv run pyright`
  - `uv run ty check .`
  - `uv run pytest -q tests/contract_tests/test_anthropic_messages.py`
  - verify the Anthropic suite includes repeated/concurrent continuation attempts
    against the same paused turn
- [x] Final closeout:
  - `uv run ruff format --check .`
  - `uv run ruff check .`
  - `uv run ty check .`
  - `uv run pyright`
  - `uv run pytest -q`

## Evidence Log
- `src/copilot_model_provider/core/pending_turns.py` now defines the PR 1 shared
  semantic core: `PausedTurnRecord`, `PausedTurnResolution`,
  `PendingTurnStoreProtocol`, `InMemoryPendingTurnStore`,
  `build_auth_context_fingerprint(...)`, and `build_paused_turn_record(...)`.
  The shared record preserves the approved base-slice affinity fields:
  `session_id`, `tool_ids`, `request_model_id`, `runtime_model_id`,
  `auth_context_fingerprint`, and `expires_at`.
- `src/copilot_model_provider/core/routing.py` now exposes
  `build_auth_context_cache_key(...)`, and `ModelRouter._build_cache_key(...)`
  delegates to it. `src/copilot_model_provider/core/pending_turns.py`
  reuses that helper via `build_auth_context_fingerprint(...)`, so paused-turn
  auth fingerprints stay aligned with the router's
  `token:{sha256_hexdigest(runtime_auth_token)}` / default-sentinel shape
  without persisting raw auth tokens.
- `src/copilot_model_provider/runtimes/protocols/runtime.py` and
  `src/copilot_model_provider/runtimes/copilot_runtime.py` now expose the
  public `discard_interactive_session(session_id, disconnect)` seam required for
  store-driven expiry cleanup. Contract/unit-test runtime fakes were updated to
  satisfy the widened runtime protocol.
- `docs/design.md` section 5.1 now matches the shipped canonical request shape:
  `request_id`, `conversation_id`, `session_id`, `runtime_auth_token`,
  `model_id`, `messages`, `tool_definitions`, `tool_results`,
  `tool_routing_policy`, and `stream`.
- Baseline route-local duplicate-attempt evidence was captured while OpenAI
  Responses and Anthropic Messages still resolve continuations through their
  existing helper functions in
  `src/copilot_model_provider/api/openai/responses.py` and
  `src/copilot_model_provider/api/anthropic/messages.py`.
  New targeted tests in `tests/unit_tests/test_openai_response_sessions.py` and
  `tests/unit_tests/test_anthropic_message_sessions.py` show that, in the
  current single-process route-local path, the first successful continuation
  synchronously consumes the pending bookkeeping and duplicate sequential or
  concurrent attempts are rejected (`invalid_previous_response_id` for the
  OpenAI `previous_response_id` retry path, `invalid_tool_result` for Anthropic).
  No duplicate-resume race was observed in this baseline, so PR 1 records
  atomic consume as preserving already-safe route-local behavior rather than as
  explicit correctness hardening for a discovered race.
- Dedicated shared-store atomicity coverage lives in
  `tests/unit_tests/test_pending_turns.py`. It proves:
  - one full-batch continuation resolves to `ready_to_resume` exactly once
  - repeated consume attempts become `invalid`
  - concurrent consume attempts produce exactly one `ready_to_resume` winner and
    one `invalid` loser
  - partial batches and expected-session mismatches do not consume state
  - expiry invokes runtime cleanup through the shared seam
  - historical replay can be reported as ignored when the route opts in
- Ordinary northbound behavior remains on route-local wiring in PR 1. No route
  migration landed yet; the shared store is foundation-only in this slice.
  Verification:
  - `uv run ruff check . && uv run pyright && uv run ty check .` -> all passed
  - `uv run pytest -q tests/unit_tests` -> 180 passed, coverage 91.41%
  - `uv run pytest -q tests/contract_tests/test_openai_responses.py tests/contract_tests/test_anthropic_messages.py`
    -> 31 passed, coverage 91.30%
  - `uv run pytest -q -o addopts='' -p no:cov tests/unit_tests/test_pending_turns.py tests/unit_tests/test_catalog.py tests/unit_tests/test_copilot_runtime.py tests/unit_tests/test_openai_response_sessions.py tests/unit_tests/test_anthropic_message_sessions.py tests/contract_tests/test_openai_responses.py tests/contract_tests/test_anthropic_messages.py tests/contract_tests/test_openai_chat_non_streaming.py tests/contract_tests/test_openai_chat_streaming.py tests/contract_tests/test_openai_models.py tests/contract_tests/test_anthropic_models.py tests/unit_tests/test_app_boot.py`
    -> 114 passed
- `src/copilot_model_provider/api/openai/responses.py` now uses the shared
  paused-turn store as the primary paused-turn state source for the OpenAI
  Responses route. Route-local state is reduced to OpenAI-specific lookup
  indexes (`previous_response_id` and tool-call-id -> session-id) while the
  shared store owns the paused-turn record, full-batch validation source of
  truth, atomic consume, and TTL expiry.
- OpenAI expiry cleanup now runs through the shared store callback into the
  runtime cleanup seam. When a paused turn expires, the route clears its
  transport-specific lookup indexes and calls
  `runtime.discard_interactive_session(session_id, disconnect=True)` instead of
  owning a separate route-local TTL task implementation.
- `tests/unit_tests/test_openai_response_sessions.py` now exercises the OpenAI
  helper logic against `InMemoryPendingTurnStore`, preserving:
  - `previous_response_id` lookup success
  - missing-session rejection
  - full-batch-only continuation
  - historical replay ignore behavior
  - duplicate tool-result rejection
  - sequential and concurrent duplicate-continuation rejection after
    shared-store migration
- `tests/contract_tests/test_openai_responses.py` now covers repeated and
  concurrent duplicate follow-ups at the HTTP layer. The concurrent duplicate
  test uses a blocking fake runtime to prove only one continuation reaches
  runtime reuse (`continuation_call_count == 1`) while the duplicate request
  receives `invalid_previous_response_id`.
- OpenAI Responses verification:
  - `uv run ruff check . && uv run pyright && uv run ty check .` -> all passed
  - `uv run pytest -q -o addopts='' -p no:cov tests/unit_tests/test_openai_response_sessions.py tests/contract_tests/test_openai_responses.py`
    -> 25 passed
  - `uv run pytest -q -o addopts='' -p no:cov tests/contract_tests/test_openai_responses.py tests/integration_tests/test_responses.py`
    -> 21 passed
  - the repo's default coverage plugin still makes narrow pytest subsets fail
    unrelated to code correctness, so the targeted PR 2 pytest commands used the
    established `-o addopts='' -p no:cov` workaround
  - Docker-backed integration validation succeeded after starting the local
    Docker daemon; the successful `tests/integration_tests/test_responses.py`
    run confirms the migrated OpenAI route still works in the containerized path
- `src/copilot_model_provider/api/anthropic/messages.py` now uses the shared
  paused-turn store as the primary paused-turn state source for the Anthropic
  Messages route. Route-local state is reduced to Anthropic-specific
  `tool_use_id -> session_id` lookup while the shared store owns the paused-turn
  record, full-batch validation source of truth, atomic consume, and TTL expiry.
- Anthropic expiry cleanup now runs through the shared store callback into the
  runtime cleanup seam. When a paused turn expires, the route clears its
  transport-specific `tool_use_id` lookup index and calls
  `runtime.discard_interactive_session(session_id, disconnect=True)` instead of
  owning a separate route-local TTL task implementation.
- `tests/unit_tests/test_anthropic_message_sessions.py` now exercises the
  Anthropic helper logic against `InMemoryPendingTurnStore`, preserving:
  - missing-session rejection
  - mismatched-session rejection
  - full-batch-only continuation
  - duplicate `tool_use_id` rejection
  - sequential and concurrent duplicate-continuation rejection after
    shared-store migration
- `tests/contract_tests/test_anthropic_messages.py` now covers repeated and
  concurrent duplicate Anthropic follow-ups at the HTTP layer. The concurrent
  duplicate test uses a blocking fake runtime to prove only one continuation
  reaches runtime reuse (`continuation_call_count == 1`) while the duplicate
  request receives the same missing-session error payload.
- Anthropic Messages verification:
  - `uv run ruff check . && uv run pyright && uv run ty check .` -> all passed
  - `uv run pytest -q -o addopts='' -p no:cov tests/unit_tests/test_anthropic_message_sessions.py tests/contract_tests/test_anthropic_messages.py`
    -> 25 passed
  - `uv run pytest -q -o addopts='' -p no:cov tests/contract_tests/test_anthropic_messages.py`
    -> 18 passed
  - the repo's default coverage plugin still makes narrow pytest subsets fail
    unrelated to code correctness, so the targeted PR 3 pytest commands used the
    established `-o addopts='' -p no:cov` workaround
- Cleanup review over `aa04bdf`, `d4f3be0`, and `daa5593` found no blocking
  design-alignment or correctness regressions before final closeout.
- `src/copilot_model_provider/core/pending_turns.py` now treats expiry cleanup as
  post-expiry best-effort cleanup: the store logs callback failures instead of
  letting them convert an otherwise expired continuation into a 500 response
  after the paused-turn bookkeeping has already been removed.
- `tests/unit_tests/test_pending_turns.py` now covers the cleanup-hardening case,
  proving an expired continuation still returns `expired` and clears store state
  even when the expiry callback raises.
- Cleanup audit confirmed that no route-local paused-turn bookkeeping remains as
  the shipped source of truth. OpenAI keeps only transport-specific
  `previous_response_id` / tool-call lookup indexes, Anthropic keeps only
  `tool_use_id` lookup, and the shared store remains the sole owner of paused
  turn records, atomic consume, and TTL expiry.
- Cleanup doc sweep found no broader Markdown edits were required beyond this
  slug status update: `README.md` already describes the thin-gateway Responses
  scope, and `docs/design.md` already matches the shipped canonical request
  shape and current provider boundary.
- Final closeout verification:
  - `uv run ruff format --check . && uv run ruff check . && uv run ty check . && uv run pyright`
    -> all passed (`pyright` still reports 3 existing warnings in
    `tests/contract_tests/test_anthropic_messages.py`, but no errors)
  - `uv run pytest -q` -> 239 passed, 2 skipped, coverage 92.72%
- Post-closeout review follow-up aligned the northbound expiry path with the
  shared-store design: OpenAI Responses and Anthropic Messages now translate
  `PausedTurnResolution(status='expired')` into explicit
  `continuation_expired` 400 errors instead of falling through to generic
  invalid/missing-session errors.
- `tests/unit_tests/test_openai_response_sessions.py` and
  `tests/unit_tests/test_anthropic_message_sessions.py` now cover matched
  continuations that expire between route lookup and `resolve(...)`, while
  `tests/unit_tests/test_pending_turns.py` covers the overlap between background
  expiry cleanup and a concurrent `resolve(...)` attempt without double cleanup.
- `tests/contract_tests/test_openai_responses.py` and
  `tests/contract_tests/test_anthropic_messages.py` now use a controllable clock
  to hit the inline expired-resolution path deterministically, so the contract
  tests validate the intended `continuation_expired` surface without depending
  on background task scheduling order.
- Review follow-up verification:
  - `uv run ruff check . && uv run ty check . && uv run pyright` -> all passed
    (with the same 3 existing `test_anthropic_messages.py` warnings)
  - `uv run pytest -q -o addopts='' -p no:cov tests/unit_tests/test_pending_turns.py tests/unit_tests/test_openai_response_sessions.py tests/unit_tests/test_anthropic_message_sessions.py tests/unit_tests/test_errors.py tests/contract_tests/test_openai_responses.py tests/contract_tests/test_anthropic_messages.py`
    -> 69 passed
- Deferred items remained out of scope for the shipped slice:
  - no public partial-result continuation semantics
  - no durable backend implementation
  - no broader failure-lifecycle expansion

## Result
- Outcome:
  - PR 1, PR 2, PR 3, and cleanup are implemented and verified on the current
    branch.
- Follow-ups:
  - `plans/agent-client-gaps/` execution scope is complete.
