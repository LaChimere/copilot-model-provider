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
- [ ] Reconfirm that the approved design still matches the repo before coding.
- [ ] Reconfirm that deferred items stay out of scope:
  - public partial-result continuation
  - durable backend implementation
  - broader failure-lifecycle expansion
- [ ] Reconfirm the current Responses replay / Anthropic full-batch behavior with
      targeted tests before changing route wiring.
- [ ] Establish the current repeated/concurrent continuation baseline before the
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
- [ ] PR 1: Shared paused-turn core and runtime seam
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

- [ ] PR 2: OpenAI Responses shared-store migration
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

- [ ] PR 3: Anthropic Messages shared-store migration
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

- [ ] Cleanup PR: Shared continuation cleanup and verification closeout
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
- [ ] All planned PR acceptance criteria are met with evidence.
- [ ] Deferred items remained out of scope:
  - no public partial-result acknowledgement semantics were added
  - no durable backend/persistence layer was introduced as part of the shipped slice
  - no broader failure-lifecycle expansion was bundled into these PRs
- [ ] Shared-store diff stayed consistent with the approved design.
- [ ] Verification level executed for each landed slice and for final closeout.

If any check fails:
1. Fix directly if the approved plan still works.
2. Update `plan.md` and resubmit for Gate 2 if the execution split changed.
3. Update `design.md` and resubmit for Gate 1 if the design itself changed.
4. Stop and report with evidence if blocked.

### Verification
- [ ] PR 1 targeted checks:
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
- [ ] PR 2 targeted checks:
  - `uv run ruff check .`
  - `uv run pyright`
  - `uv run ty check .`
  - `uv run pytest -q tests/contract_tests/test_openai_responses.py tests/integration_tests/test_responses.py`
  - verify the OpenAI suite includes repeated/concurrent continuation attempts
    against the same paused turn
- [ ] PR 3 targeted checks:
  - `uv run ruff check .`
  - `uv run pyright`
  - `uv run ty check .`
  - `uv run pytest -q tests/contract_tests/test_anthropic_messages.py`
  - verify the Anthropic suite includes repeated/concurrent continuation attempts
    against the same paused turn
- [ ] Final closeout:
  - `uv run ruff format --check .`
  - `uv run ruff check .`
  - `uv run ty check .`
  - `uv run pyright`
  - `uv run pytest -q`

## Evidence Log
- (Fill during execution with command output, before/after behavior, and key file references.)

## Result
- Outcome:
  - Gate 2 approved; ready for execution.
- Follow-ups:
  - None yet; deferred items remain intentionally out of scope.
