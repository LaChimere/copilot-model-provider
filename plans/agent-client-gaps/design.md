# Design Document

> Purpose: document the solution design for review and approval before execution planning.
> Do not proceed to plan/execution until this design is approved.

## Objective
- What problem are we solving (1–2 sentences):
  - The provider already supports the core Codex/Claude tool-routing and continuation path, but its remaining gaps are still concentrated in **paused-turn state management** rather than in first-hop routing.
  - We need a design that lets Codex, Claude Code, and similar agent CLIs work through the existing thin provider with correct session, streaming, and tool-continuation semantics, while keeping provider-owned state minimal and explicit.
- Link to research:
  - `plans/agent-client-gaps/research.md`

## Architecture / Approach
- High-level approach:
  - keep the provider boundary thin:
    - HTTP compatibility gateway
    - auth-context live model discovery
    - execution delegated to `github-copilot-sdk`
    - no provider-owned tool execution or MCP execution
  - keep the existing live model router/catalog approach stable:
    - no provider-owned model alias layer
    - no redesign of auth-context-driven live model discovery
  - treat the next design boundary as a shared **paused-turn state manager** rather than more route-local continuation dictionaries
  - keep design quality work separate from semantic expansion:
    - centralize continuation state first
    - then add new continuation semantics
    - then optionally improve restart safety
    - keep docs and support-matrix claims aligned throughout
  - make OpenAI Responses and Anthropic Messages reuse the same paused-turn model:
    - same pending-turn record
    - same validation rules
    - same TTL / expiry policy
    - same future durable-store seam
  - split the design scope into:
     1. base shared-store slice:
        - architecture/contract alignment
        - shared paused-turn state foundation
        - protocol integration with current full-batch behavior
     2. later follow-ups, only if separately approved:
        - partial-result continuation semantics
        - optional durable backend
        - stream failure lifecycle completeness
        - longer-term runtime-boundary hardening
- Key components / layers involved:
  - `src/copilot_model_provider/core/`
  - `src/copilot_model_provider/api/openai/responses.py`
  - `src/copilot_model_provider/api/anthropic/messages.py`
  - `src/copilot_model_provider/api/shared.py`
  - `src/copilot_model_provider/runtimes/copilot_runtime.py`
  - `src/copilot_model_provider/streaming/responses.py`
  - contract / integration tests
- Interaction / data flow (describe or diagram):
  1. A tool-aware request is normalized into the current canonical request shape and routed to an interactive Copilot session.
  2. When the runtime reaches a tool boundary, it preserves the live interactive session and returns pending tool calls northbound.
  3. The route records a shared `PausedTurnRecord` through a common paused-turn store instead of storing route-local pending maps only.
  4. A continuation request resolves that paused turn by:
     - `previous_response_id`
     - tool-call / tool-use id
     - or both, depending on the surface
   5. The store performs provider-owned continuation bookkeeping and cheap pre-checks:
      - same paused turn
      - duplicate result rejection
      - full pending tool ids for the base policy
      - optional early rejection when stored affinity data clearly does not match the continuation request
   6. The runtime session remains the authoritative continuation validator for model/auth-context stability before resume.
   7. If the pending turn is now complete, the provider resumes the live runtime session with the accumulated tool results.
   8. If later work adds partial accumulation, that feature must define how store expiry and live runtime session expiry stay aligned before any public acknowledgement shape ships.
   9. TTL expiry and optional durable persistence are handled by the store layer, not by duplicated route-local bookkeeping.

### Proposed paused-turn state machine

```text
idle
  -> active-turn
  -> paused-awaiting-results
  -> resuming
  -> active-turn
  -> completed

paused-awaiting-results
  -> expired

paused-awaiting-results
  -> invalid-continuation-error
```

Later partial-accumulation work may extend `paused-awaiting-results`, but the base
design does not require a public partial-accept state.

Design rules:

1. The runtime session is the execution substrate.
2. The paused-turn store is the source of truth for provider-owned continuation bookkeeping.
3. Resumption is triggered only when the chosen continuation policy says the turn is complete.
4. Expiry clears provider-owned bookkeeping and discards the runtime session.
5. The base policy remains full-batch-only; no partial-result public acknowledgement is introduced in this slice.
6. If a future slice allows partial accumulation, it must define how accepted partial submissions keep live runtime-session liveness and store liveness in sync.
7. The store may reject obvious continuation drift early, but authoritative continuation-context validation remains in the runtime reuse path.

## Project-wide design principles
- Principle 1: **thin by default**
  - keep this project as a compatibility gateway, not a provider-owned agent
    runtime
- Principle 2: **one semantic core**
  - OpenAI and Anthropic should share continuation semantics through common
    abstractions whenever possible
- Principle 3: **memory-first, durable-optional**
  - in-memory behavior should remain the default deployment shape
- Principle 4: **transport-specific at the edge only**
  - protocol-specific differences should stay in route/stream translation rather
    than in duplicated semantic logic
- Principle 5: **typed contracts over prompt-only inference**
  - preserve typed canonical execution context whenever the runtime allows it,
    even if prompt rendering remains the immediate bridge
- Principle 6: **implementation-first docs must stay aligned**
  - `docs/design.md` and support-matrix docs only stay valuable if they match the
    shipped contract closely

## Explicit non-goals
- Replacing the current live model router/catalog with a provider-owned alias or
  static model map
- Replacing the current interactive runtime session substrate before the shared
  paused-turn semantic core is stabilized
- Making durable paused-turn persistence the default deployment model
- Expanding the project into provider-owned tool execution, MCP execution, or a
  full ACP-style agent platform
- Treating a durable bookkeeping store as equivalent to restart-safe runtime
  resume without additional runtime support

## Interface / API / Schema Design
- New or changed interfaces:
  - introduce a shared paused-turn storage abstraction, for example:
    - `PendingTurnStoreProtocol`
    - `InMemoryPendingTurnStore`
  - introduce shared paused-turn data models, for example:
    - `PausedTurnRecord`
    - `PausedTurnToolResult`
    - `PausedTurnResolution`
    - `PausedTurnContinuationPolicy`
  - keep the current route and runtime APIs, but refactor them to depend on the store instead of ad-hoc route-local maps
- New or changed API endpoints:
  - no new public endpoint is required
  - keep the current public surface:
    - `POST /openai/v1/responses`
    - `POST /anthropic/v1/messages`
    - related model-list and helper endpoints stay unchanged
- New or changed data models / schemas:
  - `PausedTurnRecord` should contain at least:
      - `session_id`
        - the runtime interactive session id reused on continuation
      - `tool_ids`
      - `request_model_id`
      - `runtime_model_id`
      - `auth_context_fingerprint`
        - stores the same auth-context key shape already used by the current
          auth-context cache path
        - this is a repo-internal continuity key for provider bookkeeping, not a
          public or client-visible protocol field
        - for requests with a runtime auth token, the stored value is
          `token:{sha256_hexdigest(runtime_auth_token)}`
        - for requests without a runtime auth token, the stored value is the
          same stable default-auth sentinel already used by the current
          auth-context cache path
      - `expires_at`
  - surface-specific lookup data may be stored alongside the base record, for example:
     - `surface`, when needed to reject cross-surface continuation attempts or preserve observability
     - `response_ids`, when needed for OpenAI Responses `previous_response_id` / replay / alias lookup
  - base-slice scope:
     - the record only needs the fields required to preserve today's full-batch behavior
     - shared semantic-core state should stay minimal; transport-specific lookup helpers should remain edge-owned unless they are required for correctness
     - per-tool submitted-result accumulation can be added later if partial continuation is separately approved
  - `PausedTurnContinuationPolicy` should initially distinguish:
     - `full_batch_required`
  - if later expanded, `partial_accumulation_allowed` must be added together with an explicit runtime-liveness rule and a reviewed northbound acknowledgement contract
  - `PausedTurnResolution` should distinguish:
     - `historical_replay_ignored`
     - `invalid`
     - `ready_to_resume`
     - `expired`
- Contract compatibility notes:
   - maintain the current thin-gateway boundary from `docs/design.md`
   - do not add provider-owned tool execution
   - do not add provider-owned MCP execution
   - keep live model-id transparency unchanged
   - keep current full-batch continuation behavior as the base compatibility mode
   - durable paused-turn persistence must remain optional rather than becoming the default service contract
    - "same continuation context" in the base slice means:
     - same request model id
     - same resolved runtime model id
      - same auth-context key derived from the runtime auth value
    - the store must align with the runtime continuation invariants already enforced by the interactive session:
     - request model id
     - resolved runtime model id
     - auth context
    - `auth_context_fingerprint` is derived from the same runtime auth value already carried through the current routing/runtime path, using the exact auth-context key format already used by the auth-context cache path
    - the shared store never needs to persist or log the raw auth token to perform its bookkeeping / affinity checks
    - in the base slice, `auth_context_fingerprint` is only used for request-affinity bookkeeping, observability, and optional cheap pre-checks before runtime reuse; it does not introduce a separate auth policy or token-rotation feature
    - `auth_context_fingerprint` is a request-affinity / correctness check inside provider-owned state; it is not a new standalone security boundary
    - `auth_context_fingerprint` is a repo-internal compatibility aid for shared-store consistency; clients do not observe or configure this value directly
    - final continuation validation remains the runtime session's responsibility
    - same-auth-context continuation is the base behavior in this design slice; token-rotation handling is deferred unless a concrete client requirement appears
    - paused-turn resolution in the base slice is atomic at paused-turn scope:
      - at most one continuation request may successfully resolve and consume one paused turn for runtime reuse
      - repeated or concurrent attempts must observe consumed / invalid state rather than triggering a second runtime resume
    - `tool_routing_policy` is intentionally not stored as a separate paused-turn
      affinity field in the base slice:
      - paused-turn reuse in this slice only targets the existing interactive,
        tool-aware continuation path
      - broader policy-drift handling is deferred unless the project later
        introduces more than one continuation-capable tool-routing mode
    - `historical_replay_ignored` is primarily an OpenAI Responses edge behavior; the shared core only needs enough vocabulary to preserve that behavior without forcing every surface to expose an identical replay contract
    - preserving current OpenAI `previous_response_id` / replay lookup behavior is part of the base slice even if the mapping itself remains edge-owned
   - for the base slice, that OpenAI preservation specifically includes:
     - `previous_response_id` lookup to the paused turn
     - mismatch rejection when submitted tool results do not belong to the
       paused turn resolved by `previous_response_id`
     - historical replay ignore behavior for replayed unmatched tool-result
       history

### Chosen design for partial-result continuation

- Base behavior:
  - keep the current full-batch public behavior for existing Codex/Claude flows
  - move validation/bookkeeping onto the shared paused-turn store
- Deferred extension:
  - if a target client later needs partial accumulation, add it as an explicit continuation policy mode in a follow-up design slice
  - that follow-up must specify:
    - the northbound acknowledgement shape before the tool batch is complete
    - whether accepted partial submissions refresh live runtime-session TTL
    - how store expiry and runtime-session expiry remain aligned
- Why chosen:
  - this keeps the base semantic-core change small and reviewable
  - it avoids shipping dead or weakly-specified partial-result semantics before a concrete client need exists

## Trade-off Analysis
### Option A (chosen)
- Summary:
  - introduce a shared paused-turn store with a memory-default backend and an optional durable backend seam
- Pros:
  - removes duplicated continuation logic across OpenAI and Anthropic routes
  - gives partial-result continuation one clear home instead of patching two route-specific dict implementations
  - preserves the thin-gateway default deployment shape
  - creates a clean path to optional durable resume later
- Cons:
  - adds a new core abstraction that touches multiple hot files
  - requires careful rollout so route behavior does not drift during refactor
- Why chosen:
  - this is the narrowest architecture change that solves the remaining shared problem instead of layering more route-local bookkeeping on top of the current implementation

### Option B (rejected)
- Summary:
  - keep separate OpenAI and Anthropic continuation stores and add partial support independently in each route
- Pros:
  - smaller short-term diffs inside each route
  - no new shared core abstraction
- Cons:
  - duplicates paused-turn semantics, TTL logic, replay handling, and future durable-store logic
  - makes OpenAI and Anthropic more likely to drift
  - raises the cost of every future continuation bug fix
- Why rejected:
  - the research shows the remaining gaps are shared semantics, not surface-specific product goals

### Option C (rejected)
- Summary:
  - move directly to a durable provider-owned session store as the default architecture
- Pros:
  - strongest restart-safe semantics
  - easiest long-term story for arbitrary agent clients
- Cons:
  - changes the product boundary and deployment profile too early
  - adds operational requirements that current users do not need for the default thin gateway
  - risks over-design before partial-result continuation semantics are stable
- Why rejected:
  - the repo explicitly documents a thin, stateless provider; durable state should be an optional later seam, not the new default identity

## Key Design Decisions
- Decision 1:
  - Context:
    - current continuation bookkeeping lives in route-local dictionaries keyed by response id, tool id, and TTL tasks
  - Choice:
    - introduce one shared paused-turn store abstraction in `core/`
  - Rationale:
    - OpenAI Responses and Anthropic Messages are solving the same paused-turn bookkeeping problem and should not diverge further

- Decision 2:
  - Context:
    - the runtime already preserves live interactive sessions correctly at tool boundaries
  - Choice:
    - keep the runtime session as the execution substrate and move only bookkeeping/state management into the store
  - Rationale:
    - the current runtime fix solved the important live continuation-loss bug; replacing that substrate would be unnecessary scope

- Decision 3:
  - Context:
     - partial-result continuation is the main remaining provider-owned gap, but current public behavior still expects full-batch submission
  - Choice:
     - keep the base store full-batch-first and defer partial accumulation to a separate approved design slice
  - Rationale:
     - this keeps the base refactor behavior-safe and avoids over-designing unapproved northbound semantics

- Decision 4:
  - Context:
     - request replay and mismatched continuation ids are part of real client behavior, especially on the OpenAI Responses path
  - Choice:
     - make replay filtering, duplicate rejection, and runtime-aligned continuation-context validation part of the shared paused-turn resolution contract
  - Rationale:
     - these are core continuation semantics, not route-specific quirks

- Decision 5:
  - Context:
     - the current thin boundary should remain intact for default deployments
  - Choice:
     - durable paused-turn persistence is an optional backend seam, not a required default
  - Rationale:
     - this keeps current deployments simple and avoids forcing every user onto a stateful service profile
     - without runtime changes, durable persistence only improves provider bookkeeping durability, not full restart-safe resume

- Decision 6:
  - Context:
    - OpenAI Responses failure streaming is thinner than the official event model
  - Choice:
    - defer richer terminal failure lifecycle work until after the shared paused-turn store is in place
  - Rationale:
    - failure-lifecycle completeness matters, but it is not the highest-risk shared correctness problem today

## Impact Assessment
- Affected modules / services:
  - `src/copilot_model_provider/core/`
  - `src/copilot_model_provider/api/openai/responses.py`
  - `src/copilot_model_provider/api/anthropic/messages.py`
  - `src/copilot_model_provider/api/shared.py`
  - `src/copilot_model_provider/runtimes/copilot_runtime.py`
  - `src/copilot_model_provider/streaming/responses.py`
  - `tests/unit_tests/`
  - `tests/contract_tests/`
  - `tests/integration_tests/`
- Public API / schema compatibility:
  - no new endpoint is introduced
  - base PRs should preserve current public behavior
  - later partial-continuation support may require a reviewed surface-specific acknowledgement design before it ships
- Data migration needs:
  - none for the in-memory backend
  - if a durable backend is later added, paused-turn records must be treated as ephemeral operational state, not user data with long retention
- Performance implications:
  - mostly neutral for the in-memory backend
  - a shared store may slightly reduce duplicate bookkeeping and simplify expiry cleanup
  - a future durable backend adds storage round-trips and must therefore remain optional
- Security considerations:
  - auth-context tokens must continue to be represented only by fingerprints/digests in provider-owned state
  - paused-turn records must not store secrets beyond what is necessary to validate resume context
  - durable backends, if added later, must keep the same minimization rules

## Design dependency notes
- Shared paused-turn semantics should be settled **before** public
  partial-result continuation semantics are introduced.
- Any durable backend decision should build on the shared paused-turn store
  abstraction rather than introducing a second state model.
- `docs/design.md` should be aligned with the current canonical request shape
  before or alongside the shared-store refactor so the implementation-first
  baseline does not drift further.
- OpenAI Responses failure-lifecycle completeness should follow semantic-core
  hardening rather than compete with it in the same change slice.
- OpenAI-specific replay/alias handling should stay explicit at the transport
  edge even when the paused-turn semantic core is shared.

## Acceptance criteria
- OpenAI Responses and Anthropic Messages resolve paused turns through one shared store abstraction rather than duplicated route-local bookkeeping.
- Paused-turn TTL scheduling and expiry cleanup move into the shared store layer rather than remaining as separate route-local task implementations.
- Full-batch validation and duplicate-result rejection are implemented once in shared continuation logic rather than duplicated per route.
- Shared continuation logic preserves enough continuation-affinity data to support early drift detection for the base slice:
  - request model id
  - resolved runtime model id
  - auth context
- `auth_context_fingerprint` uses the same auth-context key format as the current
  auth-context cache path, and the shared store does not persist raw auth tokens.
- `auth_context_fingerprint` remains a repo-internal/shared-store consistency
  contract rather than a public or client-visible compatibility contract.
- Paused-turn resolution and consumption are atomic per paused turn:
  - at most one continuation request may successfully consume a paused turn and trigger runtime reuse
  - repeated or concurrent attempts do not trigger duplicate runtime resumes
  - repeated or concurrent attempts surface consumed / invalid outcomes instead of re-entering runtime reuse
- The base refactor preserves current full-batch continuation behavior.
- The runtime reuse path remains the authoritative validator for continuation-context stability before resumption.
- OpenAI Responses `previous_response_id` / replay lookup behavior is preserved in the base slice, even if the lookup mapping remains transport-specific.
- That OpenAI preservation includes:
  - `previous_response_id` lookup
  - mismatch rejection for tool results that do not match the resolved paused turn
  - historical replay ignore behavior
- The base slice does not introduce public partial-result acknowledgement semantics.
- The runtime remains the execution substrate; the provider still does not execute user tools itself.
- Durable paused-turn persistence remains optional rather than becoming the default service contract.
- If a durable backend is added later, it is documented as bookkeeping durability rather than implied restart-safe runtime resume.
- As part of the base shared-store slice, `docs/design.md` is aligned with the shipped canonical request shape.
- The design leaves the current thin-gateway architecture intact.

## Open Questions
- Q1:
  - Does any concrete near-term client actually require partial-result continuation, or should the next mergeable slice stop at the shared full-batch semantic core?
- Q2:
  - If partial accumulation is later needed, should accepted partial submissions refresh live runtime-session TTL or should partial accumulation remain unavailable until the runtime can support that safely?
- Q3:
  - If durable state is added later, should it cover only paused tool turns, or also replay-assist metadata such as historical response-id aliases?

## Review Notes / Annotations
(Place for reviewer comments. Agent must incorporate feedback and re-submit for approval before proceeding to plan.)
