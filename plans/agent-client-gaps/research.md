# Research Log

> Purpose: capture facts, evidence, and unknowns before planning/implementation.
> This is the review surface for understanding and diagnosis.

## Task
- Summary:
  - Deep research the remaining gaps between the current `copilot-model-provider`
    implementation and the goal of letting Codex, Claude Code, and similar agent
    CLIs use their required session, streaming, and tool-continuation semantics
    successfully through this provider.
- Links (issue/PR/spec):
  - `AGENTS.md`
  - `docs/design.md`
  - `README.md`
  - `plans/codex-tool-routing-design/research.md`
  - `plans/protocol-compatibility-completion/research.md`
  - `plans/model-metadata-exposure/research.md`
  - OpenAI docs:
    - https://developers.openai.com/api/docs/guides/function-calling
    - https://developers.openai.com/api/docs/guides/streaming-responses
  - Claude Code docs:
    - https://code.claude.com/docs/en/llm-gateway
    - https://code.claude.com/docs/en/model-config

## Current Behavior
- Observed behavior:
  - The repository already ships a **thin, stateless compatibility gateway** on
    top of `github-copilot-sdk`, not a provider-owned agent runtime.
  - The current provider already supports:
    - OpenAI Responses and Anthropic Messages tool-aware request paths
    - replay-tolerant continuation recovery
    - in-memory paused-turn bookkeeping with TTL cleanup
    - Anthropic gateway headers and `count_tokens`
    - streaming `usage` on both main northbound surfaces
    - live model-id and model-metadata exposure
  - The current implementation still keeps provider-owned state deliberately
    narrow:
    - no durable provider-owned conversation/session persistence
    - no server-side tools / MCP execution
    - no provider-owned prompt-caching semantics
- Expected behavior:
  - Upper-layer clients such as Codex, Claude Code, and similar agent CLIs
    should work through the provider as long as they rely on the provider's
    supported session / streaming / tool-continuation semantics.
  - The repository should continue behaving like a **thin compatibility layer**,
    not grow into an ACP-like provider-owned agent platform.
- Scope affected (modules/endpoints/commands):
  - `src/copilot_model_provider/api/openai/responses.py`
  - `src/copilot_model_provider/api/anthropic/messages.py`
  - `src/copilot_model_provider/api/shared.py`
  - `src/copilot_model_provider/core/compat.py`
  - `src/copilot_model_provider/core/responses.py`
  - `src/copilot_model_provider/runtimes/copilot_runtime.py`
  - `src/copilot_model_provider/streaming/responses.py`
  - `scripts/config_claude.py`
  - `README.md`
  - `docs/design.md`

## Environment
- OS:
  - Darwin
- Runtime/tool versions:
  - Repository uses Python 3.14+ and `uv`
  - Runtime integration is built on `github-copilot-sdk`
- Repro command(s):
  - code reading with `view` / `rg`
  - official doc fetches with `web_fetch`
  - official doc search with `web_search`

## Evidence
Include concrete evidence. Prefer copy/paste of relevant excerpts with context.
- Logs / stack traces:
  - No single crash drove this research slice; the work is about compatibility
    completion and remaining semantic gaps after the recent tool-continuation
    fixes.
- Failing tests (name + output excerpt):
  - none required to justify the research; current questions are about
    capability boundaries rather than an unfixed red test
- Metrics (numbers + method):
  - repository design and README evidence confirm the provider is intentionally
    thin and stateless rather than provider-persistent
  - live model metadata exposure already surfaces runtime token-window limits,
    including 1M context variants, through `/models`
- Repro steps (minimal):
  1. Read `docs/design.md` and `README.md` for the current shipped product
     boundary.
  2. Inspect OpenAI Responses continuation handling, Anthropic Messages
     continuation handling, and runtime interactive-session preservation.
  3. Compare current behavior with the latest official OpenAI Responses and
     Claude Code gateway/model-config docs.

### External documentation facts
- OpenAI function-calling docs confirm tool calling is a multi-step loop:
  1. request with tools
  2. receive tool call
  3. application executes the tool
  4. application sends tool output back
  5. model returns final text or more tool calls
- OpenAI streaming docs confirm the Responses API uses typed semantic events and
  documents lifecycle events such as:
  - `response.created`
  - `response.in_progress`
  - `response.completed`
  - `error`
  - plus dedicated tool / function-call argument streaming events
- Claude Code gateway docs confirm an Anthropic-compatible gateway must expose:
  - `/v1/messages`
  - `/v1/messages/count_tokens`
  - and forward `anthropic-version` and `anthropic-beta`
- Claude Code gateway docs also confirm `X-Claude-Code-Session-Id` is sent on
  every request.
- Claude Code model-config docs confirm custom model names and family defaults
  are configured client-side rather than invented by the gateway; this matches
  the provider's model-id transparency goal.

### Repository evidence
- `docs/design.md:13-27`
  - the provider is documented as thin, stateless, subprocess-backed, and not a
    provider-owned agent platform
- `docs/design.md:200-228`
  - `conversation_id` is not used for provider-managed persistence or resume,
    and accepted Responses fields do not imply provider-owned persistence or MCP
    semantics
- `src/copilot_model_provider/core/compat.py:50-113`
  - OpenAI Responses supports `previous_response_id`, `tools`,
    `parallel_tool_calls`, and `tool_choice`
  - Anthropic Messages supports `tools`
  - Anthropic `thinking` remains `accept_ignore`
- `src/copilot_model_provider/api/openai/responses.py:582-692`
  - OpenAI Responses continuation resolution now supports:
    - `previous_response_id` lookup
    - tool-call-id recovery
    - filtering historical replayed `function_call_output` items on new turns
- `src/copilot_model_provider/api/openai/responses.py:856-872`
  - OpenAI Responses currently requires the **full pending tool-result batch**
    in one continuation
- `src/copilot_model_provider/api/anthropic/messages.py:768-784`
  - Anthropic Messages also currently requires the **full pending tool-result
    batch** in one continuation
- `src/copilot_model_provider/runtimes/copilot_runtime.py:709-760`
  - runtime now preserves interactive sessions before yielding the terminal
    tool-turn event, fixing the live streamed continuation-loss bug
- `src/copilot_model_provider/api/openai/responses.py:268-283`
  - streaming runtime errors are currently surfaced as a minimal `error` event
    and the stream then terminates
- `src/copilot_model_provider/streaming/responses.py:23-42`
  - the current Responses error helper only encodes the minimal `error` shape
- `scripts/config_claude.py:420-525`
  - Claude configuration already:
    - persists `ANTHROPIC_MODEL`
    - maps 1M variants to `opus[1m]` / `sonnet[1m]`
    - pins `ANTHROPIC_DEFAULT_*_MODEL` to concrete visible provider ids
- `README.md:106-116`
  - user-facing docs already state:
    - Responses is a thin subset
    - Anthropic gateway headers are accepted
    - Anthropic `thinking` is accept-ignore
    - model metadata is exposed via nested `copilot`

## Code Reading Notes
List the most relevant files and what you learned.
- `docs/design.md` — current architecture baseline remains the most important
  product-boundary document; the provider is thin and intentionally not durable.
- `README.md` — current user-facing contract already reflects most shipped
  compatibility improvements and explicitly documents remaining thin-gateway
  boundaries.
- `src/copilot_model_provider/core/compat.py` — support vs accept-ignore vs
  reject is explicit and should remain the compatibility source of truth.
- `src/copilot_model_provider/api/openai/responses.py` — this is the main
  Codex-facing compatibility surface and already contains the replay-safe
  continuation logic.
- `src/copilot_model_provider/api/anthropic/messages.py` — this is the main
  Claude Code-facing compatibility surface and already contains header handling,
  `count_tokens`, streaming usage, and tool-result continuation validation.
- `src/copilot_model_provider/runtimes/copilot_runtime.py` — interactive
  session lifecycle defines the practical limits of current paused-turn
  semantics.
- `src/copilot_model_provider/streaming/responses.py` — current OpenAI failure
  streaming is deliberately minimal.
- `scripts/config_claude.py` — the provider is already doing the right local
  work for custom Claude selectors and 1M variants; the remaining context-window
  limitation is not caused by missing local wiring.

## Findings
1. **Most client-critical semantics are already shipped.**
   - The provider now covers the major semantics that recently blocked live
     Codex- and Claude-style clients:
     - tool-aware request normalization
     - replay-safe continuation
     - live paused-turn session preservation
     - Anthropic gateway headers
     - streaming usage
     - live model metadata exposure

2. **The remaining gaps are narrower than ACP-level parity.**
   - The repository does **not** need to become a provider-owned agent platform
     to satisfy the stated goal.
   - Server-side tool execution, provider-owned MCP, prompt-cache semantics, and
     full Claude-native multimodal / computer-use / deep-thinking equivalence
     should remain out of scope for this product boundary.

3. **Partial-result continuation is the most important provider-owned gap.**
   - Both OpenAI Responses and Anthropic Messages currently require a
     continuation to submit the full pending tool-result batch in one go.
   - This is good enough for current full-batch client loops, but it is still a
     real limitation for more generic agent CLIs that may want to resume
     incrementally as tools finish.

4. **Durable provider-owned resume is still absent by design.**
   - Current continuation semantics rely on a live provider process keeping the
     interactive session and pending tool-batch bookkeeping alive in memory.
   - This is acceptable for the current thin-gateway boundary, but it remains a
     compatibility gap for clients or workflows that need restart-safe paused
     turns.

5. **Claude custom-model context behavior is still partly upstream-blocked.**
   - The provider now exposes live model metadata and already configures Claude
     selectors/defaults correctly.
   - Remaining custom-model context-window mismatch should be treated as a
     Claude Code limitation rather than as evidence that the provider should
     invent aliases or fake limits.

6. **Anthropic structured thinking remains accept-ignore.**
   - This is currently a runtime/upstream limitation, not the first provider gap
     to prioritize.
   - The provider should not simulate or invent `thinking` /
     `redacted_thinking` blocks before the runtime can surface them faithfully.

7. **OpenAI Responses failure streaming is still thinner than the official event model.**
   - The provider already emits the happy-path lifecycle, but stream failures
     are still surfaced only as a minimal `error` event rather than a richer
     terminal failure lifecycle.
   - This is a protocol-completeness gap, but not the top blocker for today's
     Codex flow.

## Overall architecture assessment

### Current design strengths
- The repository's top-level product boundary is **correct** for the stated
  goal:
  - thin compatibility gateway
  - auth-context live model discovery
  - execution delegated to `github-copilot-sdk`
  - no provider-owned tool execution or MCP execution
- The live model-routing path is also close to best practice for this scope:
  - routing is built from the live auth-context-visible model catalog
  - cache keys do not persist raw bearer tokens
  - concurrent catalog builds are coalesced
- The compatibility layer is stronger than a typical ad-hoc proxy because the
  project now has:
  - an explicit support matrix in `core/compat.py`
  - a canonical tool-routing policy in `core/models.py`
  - a shared live-model catalog and router rather than route-local model logic

### Current design weaknesses
- The most important remaining architectural weakness is **semantic core
  fragmentation**:
  - OpenAI Responses and Anthropic Messages still keep paused-turn bookkeeping in
    separate route-local dictionaries with separate TTL task management
  - this is workable, but it is not the cleanest long-term design for agent
    client compatibility
- The current runtime boundary is still **prompt-first** rather than
  semantics-first:
  - canonical messages are ultimately rendered into plain text with role labels
  - this is a practical bridge today, but it is a long-term ceiling for richer
    future compatibility semantics
- The project currently has some **design hygiene drift**:
  - the shipped code already includes `session_id`, `tool_definitions`,
    `tool_results`, and `tool_routing_policy` on `CanonicalChatRequest`
  - the implementation-first `docs/design.md` canonical-request section still
    documents a narrower older field set
- The current public contract is also slightly more permissive than ideal:
  - `accept_ignore` remains the right strategy for some upstream fields
  - but overuse of that category risks widening the gap between
    "wire-compatible" and "semantically supported"

### Best-practice conclusion
- The project is already **well-designed for a thin compatibility gateway**.
- It is **not yet best practice** for a mature agent-client compatibility layer,
  because:
  1. paused-turn semantics are not yet centralized into one state manager
  2. the runtime bridge is still text-first
  3. the implementation baseline and the implementation-first design document are
     no longer perfectly aligned
  4. the failure lifecycle on the OpenAI Responses stream is still minimal

## Recommended project-wide improvement themes

1. **Promote paused-turn semantics to a first-class core abstraction.**
   - The next core design unit should be a shared paused-turn store/state
     manager, not more route-local continuation dictionaries.

2. **Keep durable state optional.**
   - Restart-safe resume is valuable, but it should remain an optional backend
     seam rather than redefining the whole service as stateful by default.

3. **Move toward a richer execution envelope at the runtime boundary.**
   - The current prompt bridge is acceptable for today's scope, but the project
     should gradually prefer typed execution context over more prompt-only
     inference whenever the runtime surface allows it.

4. **Tighten the support matrix over time.**
   - Keep `supported`, `accept_ignore`, and `reject`, but continue shrinking the
     gray area where fields are accepted for compatibility while their semantics
     remain underspecified.

5. **Keep docs aligned with shipped internals.**
   - The implementation-first design baseline is one of the repository's
     strengths only if it stays synchronized with the actual core contract.

6. **Treat protocol completeness as a follow-up after semantic correctness.**
   - Shared paused-turn correctness and partial-result continuation are more
     important than polishing every last lifecycle event first.

## Conflict hotspots
- `src/copilot_model_provider/api/openai/responses.py`
- `src/copilot_model_provider/api/anthropic/messages.py`
- `src/copilot_model_provider/runtimes/copilot_runtime.py`
- `src/copilot_model_provider/core/compat.py`
- `src/copilot_model_provider/core/responses.py`
- `src/copilot_model_provider/streaming/responses.py`
- `scripts/config_claude.py`
- `docs/design.md`
- `README.md`

## Open Questions / Unknowns
- Q1: should partial-result continuation remain an internal/provider-only
  accumulation mechanism until the full pending batch is ready to resume, or do
  we eventually want explicit multi-resume semantics at the public protocol
  layer?
- Q2: if durable paused-turn state becomes necessary, should it stay optional
  and feature-flagged to preserve the thin default deployment shape?
- Q3: do any generic agent CLIs we care about immediately require richer
  OpenAI failure lifecycle semantics, or is this still a follow-up completeness
  slice after partial-result continuation?
- Q4: when the Copilot SDK/runtime eventually surfaces structured thinking, can
  Anthropic passthrough remain thin and faithful without adding provider-owned
  synthesis logic?

## Recommendation for Plan
- Proposed direction:
  - keep the product boundary thin and continue optimizing for **client-critical
    compatibility completion**, not ACP-style platform expansion
  - improve the project through two linked tracks:
    1. **semantic-core hardening**
       - shared paused-turn store
       - partial-result continuation
       - optional durable paused-turn backend
    2. **project-quality hardening**
       - refresh the implementation-first design baseline so it matches the
         current canonical contract
       - reduce route-local drift
       - tighten failure lifecycle semantics and support-matrix precision
  - prioritize the remaining work in this order:
    1. shared paused-turn store extraction
    2. partial-result continuation
    3. optional durable paused-turn resume
    4. OpenAI Responses failure-lifecycle completeness
    5. Anthropic structured thinking passthrough only when the runtime can
       genuinely supply it
  - treat Claude custom-model context behavior as an **external blocker**, not a
    reason to distort provider-owned model metadata or aliases
  - keep OpenAI and Anthropic continuation behavior aligned through one shared
    canonical paused-turn state machine, with surface-specific wire translation
    only at the boundary
  - continue validating against real client traffic and contract tests instead
    of relying only on synthetic narrow unit coverage
- Risks:
  - partial-result continuation adds paused-turn state complexity and can easily
    regress the current full-batch invariants if the state machine is not made
    explicit
  - durable resume risks changing the project's deployment/operations profile if
    it stops being optional
  - richer failure semantics can drift from the official event model if they are
    invented heuristically instead of derived from the actual lifecycle contract
 - Suggested verification level (L1/L2/L3): L2

## Decomposition Notes
- Why decompose:
  - the approved design introduces one shared paused-turn semantic core that
    touches hot shared files (`core/`, `runtimes/`, and both protocol routes),
    so a single large PR would be hard to review and risky to merge
  - OpenAI Responses and Anthropic Messages need to preserve different
    transport-edge continuation behavior on top of the same base store contract,
    which makes a base-plus-integration split safer than one mixed diff
  - `docs/design.md` already lags the shipped canonical request contract, so the
    implementation-first baseline should be aligned in the same base slice rather
    than deferred to the very end
- Constraints that justify the split:
  - keep the provider boundary thin: no provider-owned tool execution, MCP, or
    durable-by-default runtime resume
  - preserve current full-batch continuation behavior while migrating route-local
    bookkeeping to one shared paused-turn store
  - keep runtime reuse authoritative for continuation-context validation
  - preserve OpenAI Responses `previous_response_id` / replay behavior while
    avoiding protocol-specific leakage into the shared core
- Proposed PR sequence rationale:
  1. base shared-store contract + runtime seam + canonical-doc alignment
  2. OpenAI Responses migration onto the shared base
  3. Anthropic Messages migration onto the shared base
  4. cleanup / verification closeout after both protocol integrations land
- Explicitly deferred from this execution plan:
  - public partial-result continuation semantics
  - optional durable paused-turn backend
  - richer OpenAI Responses failure lifecycle
