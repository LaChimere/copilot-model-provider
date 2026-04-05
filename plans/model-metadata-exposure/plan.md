# Plan

> Purpose: a reviewable plan that can be annotated. Do not implement until the plan is approved when plan mode is triggered.

## Objective
- What outcome we want (1–2 sentences):
  - Preserve all live model metadata returned by the Copilot runtime and expose it through the existing OpenAI and Anthropic model-list routes.
  - Ship the rollout in small, mergeable PRs so routing semantics stay stable while Codex-, Claude-, and other client-facing discovery gains an additive nested `copilot` object per model item.

## Constraints
- Compatibility constraints:
  - keep existing model IDs, auth-context routing, and required `/models` fields unchanged
  - only add optional metadata fields; do not require clients to send or understand new request inputs
  - expose only metadata actually returned by the runtime for each model
  - use an additive runtime-protocol rollout: do not hard-replace `list_model_ids()` in PR1
- Performance constraints:
  - reuse the existing auth-context catalog cache path; do not add an extra runtime discovery round trip per request
  - keep model-list translation deterministic and cheap relative to the existing snapshot build
- Security/safety constraints:
  - continue hashing auth-context tokens in cache keys
  - never expose tokens or provider-internal secrets in model metadata
- Timeline/rollout constraints (if any):
  - deliver as reviewable stacked PRs with trunk-safe intermediate states

## Assumptions
Mark each as **Verified** or **Unverified**.
- [x] (Verified) `github-copilot-sdk` `CopilotClient.list_models()` returns metadata-rich `ModelInfo` objects, including limits/capabilities/policy/billing for at least some live models.
- [x] (Verified) the current provider truncates runtime discovery to IDs before building the cached model catalog.
- [ ] (Unverified) current Codex/Claude clients tolerate additive nested objects on model-list items without rejecting the payload.
- [x] (Verified) `pyproject.toml` currently sets `requires-python = ">=3.14"`.

## Options Considered (if applicable)
### Option A
- Summary:
  - extend only the existing `/openai/v1/models` and `/anthropic/v1/models` responses with an additive nested `copilot` metadata object
- Pros:
  - metadata appears on the same discovery path current clients already use
  - no extra endpoint to document or maintain
  - one shared metadata object can serve both protocol facades
- Cons:
  - the metadata object is provider-specific
  - some clients may ignore it
- Why chosen / rejected:
  - chosen; this best matches the goal of making metadata visible to upper-layer clients without adding a second lookup path

### Option B
- Summary:
  - add a separate provider-native metadata endpoint and keep `/models` strictly minimal
- Pros:
  - cleaner separation from upstream compatibility schemas
  - easier independent versioning
- Cons:
  - clients would need an extra fetch and likely would not discover metadata automatically
  - larger API surface area
- Why chosen / rejected:
  - rejected for v1 because it weakens the "upper-layer discoverability" goal

## Proposed Approach (checklist)
- [ ] Step 1: build metadata-preserving runtime and catalog plumbing in a base PR
  - Acceptance criteria:
    - runtime discovery exposes normalized metadata-rich model snapshots through a new additive runtime method
    - `RuntimeProtocol.list_model_ids()` remains available as a compatibility shim in this PR
    - `build_live_model_catalog()` remains a stable ID-only wrapper, and a new metadata-aware catalog builder is introduced for the richer path
    - the shared nested `copilot` schema is defined in `core/models.py` in this PR so later public exposure PRs do not redesign the contract
    - `core/routing.py` switches its catalog-build path to the new metadata-rich runtime method while keeping `list_models_response()` behaviorally unchanged
    - auth-context caching still works and remains token-isolated
    - existing `list_model_ids()` fake runtimes in contract/unit tests remain valid unless they are directly exercising the new metadata method
    - current public `/models` responses stay behaviorally unchanged in this PR
- [ ] Step 2: expose the additive nested `copilot` object on `GET /openai/v1/models`
  - Acceptance criteria:
    - OpenAI model cards retain current required fields and add optional `copilot` metadata
    - the `copilot` object matches the approved schema exactly
    - only runtime-supplied metadata is serialized for each model
    - Codex and Claude tolerance checks pass before this PR is merged; if they fail, stop and return to design review instead of merging
    - unit and integration tests prove metadata appears on the OpenAI facade without changing model ordering
- [ ] Step 3: expose the same nested `copilot` object on `GET /anthropic/v1/models`
  - Acceptance criteria:
    - Anthropic model entries retain current required fields and add optional `copilot` metadata
    - Anthropic translation reuses the same shared catalog metadata shape as the OpenAI facade
    - Anthropic `display_name` prefers runtime `copilot.name` and falls back to the existing formatter when the runtime omits `name`
    - tests prove OpenAI and Anthropic views stay consistent for the same auth-context model snapshot
- [ ] Step 4: refresh docs and complete rollout validation in a cleanup PR
  - Acceptance criteria:
    - directly related docs are updated to describe the additive `copilot` metadata object
    - targeted and full validation cover runtime plumbing plus both model-list routes
    - no unrelated cleanup or schema churn is mixed into the PR

## Rollout / Dependency Notes
- PR1 is the base/contract PR. It introduces the shared runtime metadata models and the additive runtime/catalog interfaces.
- PR1 keeps public `/models` payloads unchanged while upgrading runtime discovery, router caching, and shared metadata models.
- PR2 is the first public-schema PR. It adds the nested `copilot` object to `GET /openai/v1/models` and serves as the tolerance-gated rollout step for Codex/Claude.
- PR3 is serial after PR2 because the current Anthropic translation path consumes the shared OpenAI-facing model-card shape and reuses `copilot.name` for `display_name`.
- PR4 stays serial after PR3 because it only refreshes docs and final validation once both public facades are in place.

## Touch Surface
- Key files/modules likely to change:
  - `src/copilot_model_provider/runtimes/protocols/runtime.py`
  - `src/copilot_model_provider/runtimes/copilot_runtime.py`
  - `src/copilot_model_provider/core/__init__.py`
  - `src/copilot_model_provider/core/models.py`
  - `src/copilot_model_provider/core/catalog.py`
  - `src/copilot_model_provider/core/routing.py`
  - `src/copilot_model_provider/api/openai/models.py`
  - `src/copilot_model_provider/api/anthropic/models.py`
  - `src/copilot_model_provider/api/anthropic/protocol.py`
  - `tests/unit_tests/test_catalog.py`
  - `tests/unit_tests/test_app_boot.py`
  - `tests/contract_tests/test_openai_models.py`
  - `tests/contract_tests/test_anthropic_models.py`
  - `tests/integration_tests/test_models.py`
- Public API / schema impacts:
  - additive nested `copilot` object on both public model-list responses
  - Anthropic `display_name` becomes runtime-name-aware when `ModelInfo.name` is available
- Data impacts:
  - none

## Verification Plan (Done = Evidence)
### Target verification level
- [ ] L1
- [x] L2
- [ ] L3

### Evidence to produce
- [ ] Tests to run (exact commands):
  - `uv run ruff check .`
  - `uv run pyright`
  - `uv run ty check .`
  - `uv run pytest -q tests/unit_tests/test_catalog.py tests/unit_tests/test_app_boot.py tests/contract_tests/test_openai_models.py tests/contract_tests/test_anthropic_models.py tests/integration_tests/test_models.py --no-cov`
  - `uv run pytest -q`
- [ ] Before/after behavior proof:
  - before: `/openai/v1/models` and `/anthropic/v1/models` return only minimal model-card fields
  - after: the same endpoints return additive nested `copilot` metadata for models whose runtime snapshot includes metadata
  - after: Anthropic `display_name` uses runtime `name` when available
- [ ] Logs/traces/metrics to capture:
  - live `list_models()` evidence for at least one 1M model and one non-1M model
  - Codex and Claude tolerance smoke-test evidence against the additive nested `copilot` object

### Client tolerance check procedure
- [ ] Capture the locally installed client versions with `codex --version` and `claude --version`
- [ ] Point each client at a local provider instance serving the enriched OpenAI model-list response (using the existing local config scripts where applicable)
- [ ] Trigger each client's normal model discovery path and one minimal prompt send using a model that remains visible in the enriched list
- [ ] Pass criteria:
  - model discovery succeeds with no parse/schema errors in client output or logs
  - the client can select/use the configured model after reading the enriched `/models` response
- [ ] Failure criteria:
  - JSON parsing, schema validation, or startup/model-discovery failure attributable to the additive nested `copilot` object
- [ ] Blocker rule:
  - if either client cannot be exercised locally or fails this check, do not merge PR2/PR3; stop and return to design review with the captured evidence

## Rollback / Recovery (if applicable)
- Rollback plan:
  - revert the additive public metadata fields and fall back to the existing minimal model-card responses while leaving routing behavior untouched
- Data safety notes:
  - no persistent data or migration state is introduced
- Feature flag / config toggles:
  - none planned for v1
- Recovery trigger:
  - if Codex or Claude rejects additive nested objects on model-list items, stop before merging PR2/PR3 and return to Gate 1 with a revised fallback design

## Risks / Non-goals
- Risks:
  - some clients may ignore or mishandle the additive nested `copilot` object
  - the SDK may return partial metadata across model families, increasing fixture variance
  - extending both protocol facades raises the chance of schema drift if not kept on a shared metadata model
  - auth-context cache entries will grow because they now store richer per-model metadata, though the current live model count and short TTL keep that risk low
- Explicit non-goals (out of scope):
  - inventing metadata not returned by the runtime
  - changing chat/message execution behavior based on metadata
  - adding a provider-native metadata endpoint in v1

## Review Notes / Annotations
(Place for inline user comments. Agent should incorporate these into the plan before coding.)

## Approval
- [x] Plan approved by: User
- Date: 2026-04-05
