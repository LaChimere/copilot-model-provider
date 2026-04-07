# Design Document

> Purpose: document the solution design for review and approval before execution planning.
> Do not proceed to plan/execution until this design is approved.

## Objective
- What problem are we solving (1–2 sentences):
  - The provider currently drops live Copilot model metadata, so upper-layer clients can only discover model IDs and not runtime-reported limits/capabilities such as context window size.
  - We need to preserve all model metadata that the Copilot runtime actually returns and expose it through the provider in a way that remains mergeable and protocol-safe.
- Link to research: `plans/model-metadata-exposure/research.md`

## Architecture / Approach
- High-level approach:
  - supplement the runtime/catalog pipeline from ID-only discovery to metadata-rich discovery without breaking the existing `list_model_ids()` contract during the rollout
  - cache auth-context-aware model metadata snapshots the same way the current router caches model IDs
  - expose provider-owned metadata through existing model-list responses so Codex, Claude, and other clients can query it from the same discovery surfaces they already use
- Key components / layers involved:
  - runtime protocol and Copilot runtime implementation
  - catalog/router models and caching
  - OpenAI and Anthropic model-list schemas/translators
  - unit and integration test fixtures for model listing
- Interaction / data flow (describe or diagram):
  1. `CopilotRuntime` calls `CopilotClient.list_models()` and normalizes each live `ModelInfo` into provider-owned runtime metadata models.
  2. `RuntimeProtocol` gains a new metadata-rich discovery method; `list_model_ids()` remains in place as a compatibility shim during v1.
  3. `ModelRouter` caches the normalized per-model metadata per auth context.
  4. `GET /openai/v1/models` returns model cards plus an optional nested `copilot` object.
  5. `GET /anthropic/v1/models` translates the same catalog into Anthropic model objects, prefers runtime `name` for `display_name`, and exposes the same nested `copilot` object.

## Interface / API / Schema Design
- New or changed interfaces:
  - **chosen strategy:** supplement `RuntimeProtocol.list_model_ids()` with a new metadata-rich discovery method such as `list_models(...) -> tuple[RuntimeDiscoveredModel, ...]`
  - keep `list_model_ids()` during v1 as a compatibility shim so existing fake runtimes and callers do not need an all-at-once interface rewrite
  - add a new metadata-aware catalog builder such as `build_live_model_catalog_from_models(...)`, while keeping the exported `build_live_model_catalog(model_ids=...)` helper as a stable wrapper for existing callers and tests
  - extend catalog entries to retain runtime metadata for each live model
- New or changed API endpoints:
  - `GET /openai/v1/models` gains an optional nested `copilot` metadata object per model item
  - `GET /anthropic/v1/models` gains an optional nested `copilot` metadata object per model item
- New or changed data models / schemas:
  - internal normalized runtime models:
    - `RuntimeDiscoveredModel`
    - `RuntimeModelCapabilities`
    - `RuntimeModelSupports`
    - `RuntimeModelLimits`
    - `RuntimeModelVisionLimits`
    - `RuntimeModelPolicy`
    - `RuntimeModelBilling`
  - public OpenAI/Anthropic model card schemas with one explicit nested `copilot` metadata field
  - v1 `copilot` object shape:

    ```json
    {
      "copilot": {
        "name": "Claude Opus 4.6 (1M context)(Internal only)",
        "capabilities": {
          "supports": {
            "vision": true,
            "reasoning_effort": true
          },
          "limits": {
            "max_prompt_tokens": 936000,
            "max_context_window_tokens": 1000000,
            "vision": {
              "supported_media_types": ["image/png", "image/jpeg"],
              "max_prompt_images": 20,
              "max_prompt_image_size": 5242880
            }
          }
        },
        "policy": {
          "state": "enabled",
          "terms": "..."
        },
        "billing": {
          "multiplier": 1.0
        },
        "supported_reasoning_efforts": ["low", "medium", "high"],
        "default_reasoning_effort": "high"
      }
    }
    ```

  - field rules:
    - `copilot` is omitted only when the runtime yields no metadata beyond the required top-level model-card fields
    - `copilot.name` is included when the runtime provides `ModelInfo.name` (always true for the current Copilot runtime; optional in the provider schema for future runtimes)
    - nested objects are omitted when all of their fields are absent
    - omission semantics are enforced via explicit `exclude_none` response serialization on the model-list routes so absent fields are omitted rather than emitted as `null`
    - the provider preserves SDK field meaning; it does not invent synthetic limits, policy, billing, or reasoning-effort defaults
- Contract compatibility notes:
  - existing required fields remain unchanged
  - new metadata is additive and optional on a per-model basis
  - Anthropic `display_name` prefers runtime `copilot.name` when available, then falls back to the current model-id formatter
  - only metadata actually returned by the runtime is exposed; the provider does not invent or infer absent fields

## Trade-off Analysis
### Option A (chosen)
- Summary:
  - extend the existing `/openai/v1/models` and `/anthropic/v1/models` payloads with a nested `copilot` metadata object while preserving all current required fields
- Pros:
  - keeps discovery on the exact routes that current clients already call
  - avoids a second fetch for clients that want metadata
  - works for both OpenAI-facing and Anthropic-facing clients with one shared catalog pipeline
- Cons:
  - the added metadata is provider-specific rather than part of strict upstream OpenAI/Anthropic schemas
  - some clients may ignore unknown fields
- Why chosen:
  - it best satisfies the requirement to expose metadata to Codex, Claude, and other clients without depending on a new route that those clients are unlikely to query by default

### Option B (rejected)
- Summary:
  - keep existing `/models` responses unchanged and add a new provider-native metadata endpoint
- Pros:
  - clean separation between strict compatibility payloads and provider-specific metadata
  - easier to version independently
- Cons:
  - Codex and Claude would not automatically discover metadata from their normal model-list flow
  - adds another public surface to document, validate, and maintain
- Why rejected:
  - it exposes metadata, but not on the main client discovery path the user asked us to support

### Option C (rejected, if applicable)
- Summary:
  - infer metadata from model IDs or maintain a static local map of limits
- Pros:
  - simple implementation with no runtime contract changes
- Cons:
  - violates the repo's live-model design
  - risks stale or incorrect limits, especially for internal-only or newly added models
- Why rejected:
  - the runtime already provides authoritative metadata, so static inference would be both less correct and less maintainable

## Key Design Decisions
- Decision 1:
  - Context:
    - the current runtime protocol truncates discovery to `tuple[str, ...]`, which permanently loses metadata before routing or API translation.
  - Choice:
    - introduce a normalized metadata-rich runtime discovery shape via a new additive runtime method, and keep `list_model_ids()` as a compatibility shim during v1.
  - Rationale:
    - the metadata must survive the runtime boundary before it can be cached or exposed northbound, but the rollout should not force a repo-wide stub rewrite in the base PR.

- Decision 2:
  - Context:
    - the SDK can return partial metadata per model, and different model families may expose different capability subsets.
  - Choice:
    - represent metadata as one explicit nested `copilot` object with optional additive subfields for `name`, `capabilities`, `policy`, `billing`, `supported_reasoning_efforts`, and `default_reasoning_effort`.
  - Rationale:
    - this keeps the provider faithful to runtime truth, prevents fake defaults from misleading clients, and avoids deferring public schema design into execution.

- Decision 3:
  - Context:
    - the exported `build_live_model_catalog()` helper is already part of the repo's public core surface.
  - Choice:
    - add a new metadata-aware catalog builder for runtime-model inputs and keep the existing ID-only helper as a compatibility wrapper.
  - Rationale:
    - this keeps PR1 merge-safe and avoids breaking existing helper callers while the richer path is introduced.

- Decision 4:
  - Context:
    - Codex and Claude discover models through different compatibility facades, but both should see the same underlying metadata when available.
  - Choice:
    - attach one shared nested `copilot` metadata object shape to both OpenAI and Anthropic model list items, and define that shared shape in PR1.
  - Rationale:
    - a shared shape reduces drift and makes the later serial OpenAI/Anthropic exposure steps easier to reason about and test.

- Decision 5:
  - Context:
    - the SDK already provides `ModelInfo.name`, while the Anthropic facade currently synthesizes `display_name` from the model ID.
  - Choice:
    - include `name` in `copilot` metadata and use it as the preferred source for Anthropic `display_name`, with fallback to the current formatter when absent.
  - Rationale:
    - this improves display-name fidelity without inventing provider-only naming rules.

- Decision 6:
  - Context:
    - the main unresolved compatibility risk is whether current clients tolerate additive nested objects on model-list entries.
  - Choice:
    - require an explicit Codex/Claude tolerance check before merging the first public schema change; if either client rejects the additive `copilot` object, stop and return to Gate 1 instead of merging the exposure PRs.
  - Rationale:
    - this turns an unverified assumption into a concrete rollout gate rather than a post-merge surprise.

- Decision 7:
  - Context:
    - the current Anthropic facade translates from the shared OpenAI-facing model-list response shape rather than from an independent metadata source.
  - Choice:
    - keep the rollout serial after the base PR: PR1 plumbing, PR2 OpenAI exposure, PR3 Anthropic exposure, PR4 cleanup/docs.
  - Rationale:
    - this avoids claiming false parallelism, keeps PR1 behaviorally unchanged, and lets Anthropic exposure build on the already-shipped OpenAI-facing `copilot` shape.

## Impact Assessment
- Affected modules / services:
  - `src/copilot_model_provider/runtimes/protocols/runtime.py`
  - `src/copilot_model_provider/runtimes/copilot_runtime.py`
  - `src/copilot_model_provider/core/catalog.py`
  - `src/copilot_model_provider/core/__init__.py`
  - `src/copilot_model_provider/core/models.py`
  - `src/copilot_model_provider/core/routing.py`
  - `src/copilot_model_provider/api/openai/models.py`
  - `src/copilot_model_provider/api/anthropic/models.py`
  - `src/copilot_model_provider/api/anthropic/protocol.py`
  - model-list unit/integration/contract tests
- Public API / schema compatibility:
  - additive-only model-list response changes
  - existing model IDs and routing semantics remain unchanged
- Data migration needs:
  - none
- Performance implications:
  - larger cached model snapshots and response payloads, but still bounded by the current live model count per auth context and the existing short TTL
  - no extra runtime round trip if metadata reuses the existing catalog TTL/cache path
  - if the live model catalog grows materially in the future, the auth-context cache may need a size bound in addition to TTL pruning
- Security considerations:
  - continue keying caches by auth-context token digest only
  - do not expose auth-context tokens or provider-internal secrets inside model metadata

## Open Questions
- Q1:
  - should a separate provider-native metadata endpoint be deferred entirely unless a concrete client proves `/models` extension fields are insufficient?
- Q2:
  - if a client rejects additive nested objects on model-list entries, should the fallback be an opt-in response shape or a provider-native endpoint in a future design revision?

## Review Notes / Annotations
(Place for reviewer comments. Agent must incorporate feedback and re-submit for approval before proceeding to plan.)

## Approval
- [x] Design approved by: User
- Date: 2026-04-05
