# Design Document

> Purpose: document the solution design for review and approval before execution planning.
> Do not proceed to plan/execution until this design is approved.

## Objective
- What problem are we solving (1–2 sentences):
  - Improve protocol compatibility for the current dual-protocol provider without expanding the product boundary beyond a thin, stateless compatibility layer.
  - The goal is to make the shipped OpenAI facade work more predictably for current Codex clients and the shipped Anthropic facade work more predictably for current Claude Code clients.
  - A key product requirement is upper-layer transparency: any model visible from the current GitHub Copilot auth context should be addressable by upper-layer clients through `model id` configuration alone.
- Link to research: `plans/protocol-compatibility-completion/research.md`
- Definition:
  - **Model-id transparency** means an upper-layer client can set the `model` request parameter to a catalog-visible model id without requiring provider-side alias layers or client-specific model-name mappings.

## Architecture / Approach
- High-level approach:
  - Keep the current endpoint families and runtime architecture intact.
  - Treat **model-id transparency across client families** as a top-level compatibility contract.
  - Introduce an explicit **compatibility policy layer** for both OpenAI and Anthropic surfaces so each incoming field/header is classified as one of:
    - supported and translated
    - accepted but intentionally ignored
    - explicitly rejected with a structured provider error
  - Apply the policy consistently in:
    - request parsing and normalization
    - streaming event translation
    - error shaping
    - client bootstrap scripts and docs
- Key components / layers involved:
  - `src/copilot_model_provider/api/openai/`
  - `src/copilot_model_provider/api/anthropic/`
  - `src/copilot_model_provider/api/shared.py`
  - `src/copilot_model_provider/core/`
  - `src/copilot_model_provider/streaming/`
  - contract / integration / live-client smoke tests
- Interaction / data flow (describe or diagram):
  1. Protocol-specific endpoint receives request.
  2. Facade applies protocol-specific compatibility policy:
     - validate required headers/fields
     - preserve supported request semantics
     - explicitly classify unsupported semantics
  3. Request is normalized into canonical internal form only for supported text-first execution semantics.
  4. Runtime executes through `github-copilot-sdk`.
  5. Protocol-specific translator reconstructs the best compatible northbound response and stream shape.
  6. Errors are emitted using protocol-specific envelopes but shared internal classification.
   7. Model ids remain auth-context-driven and are exposed consistently enough that upper-layer clients can select among visible Copilot models without client-specific alias layers.

## Interface / API / Schema Design
- New or changed interfaces:
  - No new top-level product surface is required.
  - Internal compatibility helpers/policies will likely be added to protocol modules and shared helpers.
- New or changed API endpoints:
  - Keep the current endpoint set:
    - `GET /openai/v1/models`
    - `POST /openai/v1/chat/completions`
    - `POST /openai/v1/responses`
    - `GET /anthropic/v1/models`
    - `POST /anthropic/v1/messages`
    - `POST /anthropic/v1/messages/count_tokens`
  - Compatibility completion should focus on semantics within these endpoints, not endpoint expansion.
- New or changed data models / schemas:
  - Request models may need richer protocol-field tracking so that ignored vs rejected semantics are explicit.
  - Error models may need additional protocol-specific codes/messages for unsupported-but-recognized features.
  - Streaming translators may need protocol-specific metadata additions where client behavior depends on them.
- Contract compatibility notes:
  - Preserve the thin, stateless, text-first boundary.
  - Preserve model-id transparency across clients for any model visible in the active Copilot auth context.
  - Treat model-id transparency as **addressability and selection**, not as a guarantee that different model families expose identical native capabilities.
  - Do not add provider-owned session persistence.
  - Do not add server-side tool execution or MCP execution.
  - Do not expand into broad multimodal or agent-platform semantics unless strictly required for client-critical compatibility and still representable within the boundary.
  - Model-native feature differences are not provider bugs by themselves; the provider is responsible for compatibility of the shared facade contract, not for making every model family look identical internally.

## Trade-off Analysis
### Option A (chosen)
- Summary:
  - **Client-critical compatibility completion on the existing dual-protocol surface.**
- Pros:
  - Aligns directly with the repo’s current product boundary.
  - Improves real Codex / Claude Code interoperability where it matters most.
  - Avoids runaway scope into platform features the provider does not own.
  - Makes behavior more predictable through explicit compatibility classification.
  - Aligns with the product requirement that upper layers should select models by model id alone.
- Cons:
  - Will not achieve full upstream API parity.
  - Requires careful decisions about when to ignore versus reject unsupported fields.
  - Some official API features will remain intentionally unsupported.
- Why chosen:
  - This is the highest-value path that improves actual client compatibility without turning the project into a full provider platform.

### Option B (rejected)
- Summary:
  - **Attempt broad parity with the latest OpenAI and Anthropic public APIs.**
- Pros:
  - Maximizes nominal protocol coverage.
  - Reduces future “missing field” reports in the short term.
- Cons:
  - Violates the thin-provider boundary quickly.
  - Pulls the project into tools, multimodal, caching, persistence, and other platform semantics.
  - Produces a large, hard-to-review diff with weak verification economics.
- Why rejected:
  - The repo explicitly avoids becoming a provider-owned agent platform.

### Option C (rejected)
- Summary:
  - **Treat compatibility as a script/client-bootstrap problem only.**
- Pros:
  - Small code surface.
  - Low implementation cost.
- Cons:
  - Does not solve actual HTTP compatibility gaps.
  - Leaves protocol behavior underspecified and brittle.
  - Pushes complexity into client setup instead of the compatibility layer.
- Why rejected:
  - The remaining work is primarily in route semantics and error/stream behavior, not installer scripts.

## Key Design Decisions
- Decision 1:
  - Context:
    - The repo already ships both OpenAI and Anthropic facades, but supported semantics are narrower than the latest upstream APIs.
  - Choice:
    - Keep the existing endpoint families and improve semantics within them instead of adding broad new surfaces.
  - Rationale:
    - Existing routes are already the contract consumed by Codex and Claude Code in this repo.

- Decision 2:
  - Context:
    - Some request fields today are accepted but ignored, which can be compatibility-friendly or misleading depending on the field.
  - Choice:
    - Introduce an explicit three-way classification:
      - supported
      - accepted-but-ignored
      - structured-rejection
  - Rationale:
    - This prevents accidental “fake compatibility” and gives a stable rule for future additions.

- Decision 3:
  - Context:
    - Official APIs include features outside the project boundary, such as tools, multimodal inputs, prompt caching, and stateful flows.
  - Choice:
    - Preserve the current thin, stateless, text-first boundary and reject or clearly document out-of-bound features rather than partially emulating them.
  - Rationale:
    - Boundary clarity is more valuable than shallow parity.

- Decision 4:
  - Context:
    - Current user-facing clients are Codex and Claude Code, and both have official docs that define what they practically need from a gateway/provider.
  - Choice:
    - Use Codex and Claude Code as the primary compatibility anchors for prioritization, rather than the full theoretical upstream API surface.
  - Rationale:
    - The project should optimize for real client interoperability, not abstract completeness.

- Decision 5:
  - Context:
    - The product requirement is that any Copilot-visible model should be addressable from upper-layer clients by setting the model id only.
  - Choice:
    - Make model-id transparency a first-class contract of compatibility completion across both facades.
  - Rationale:
    - This turns model selection into a shared provider guarantee while still keeping model-native deeper capabilities out of scope.

## Impact Assessment
- Affected modules / services:
  - `src/copilot_model_provider/api/openai/`
  - `src/copilot_model_provider/api/anthropic/`
  - `src/copilot_model_provider/api/shared.py`
  - `src/copilot_model_provider/core/`
  - `src/copilot_model_provider/streaming/`
  - `tests/contract_tests/`
  - `tests/integration_tests/`
  - `tests/live_tests/`
  - `README.md` and `docs/design.md`
- Public API / schema compatibility:
  - Existing endpoints remain.
  - Request/response semantics and error behavior will become stricter and more explicit.
  - Some currently silent no-op fields may become structured 4xx rejections if they are misleading.
  - Model ids exposed from the live auth-context catalog should remain the canonical selection surface for both Codex-style and Claude-style clients.
- Data migration needs:
  - None.
- Performance implications:
  - Mostly neutral.
  - Additional validation and translation logic adds small overhead.
  - Stronger compatibility tests may lengthen validation time modestly.
- Security considerations:
  - Header/auth handling must remain explicit and deterministic.
  - Compatibility work must not accidentally enable tool execution, state carryover, or hidden capability expansion.

## Supplementary Design Additions (Round 2) — 2026-04-03

Based on deep-dive research into latest official Codex, Claude Code, and API documentation.

### New Decision 6: Chat/completions remains a first-class endpoint
- Context:
  - Based on current external Codex materials, `wire_api = "responses"` appears to be the main Codex integration path and `chat/completions` appears to be secondary for Codex.
  - However, our provider serves many potential upstream clients beyond Codex. Other OpenAI-compatible clients still rely on chat/completions.
- Choice:
  - Keep `/openai/v1/chat/completions` as a first-class, fully supported endpoint.
  - Apply the same compatibility-completion treatment (error handling, field classification, streaming correctness) to chat/completions as to the Responses endpoint.
  - Document in the support matrix that Codex specifically uses the Responses endpoint.
- Rationale:
  - Our provider is not Codex-only. Dropping or deprioritizing chat/completions would break other clients. The Codex deprecation is a Codex-side decision; our provider should remain protocol-agnostic.
  - Treat this as an external prioritization signal rather than a repository-verified fact.
  - Re-verify the exact Codex wording and behavior immediately before implementation.

### New Decision 7: Anthropic error response format must match official shape
- Context:
  - Our non-streaming Anthropic error handler uses the OpenAI-style `{error: {code, message}}` format.
  - Official Anthropic format is `{type: "error", error: {type: "error_type", message: "..."}}`.
  - Claude Code may fail to parse our current error responses.
- Choice:
  - Implement protocol-specific error response formatting:
    - OpenAI routes → `{error: {code, message}}` (already correct)
    - Anthropic routes → `{type: "error", error: {type: "error_type", message: "..."}}` (needs fix)
  - Map internal error codes to Anthropic error types: `invalid_request_error`, `authentication_error`, `api_error`.
- Rationale:
  - This is a functional correctness issue, not a nicety. Claude Code expects Anthropic-shaped error responses.

### New Decision 8: Anthropic gateway headers must be handled
- Context:
  - Current external Claude Code gateway docs state: "Must forward request headers: `anthropic-beta`, `anthropic-version`" and "Failure to forward headers may result in reduced functionality."
  - `X-Claude-Code-Session-Id` is sent on every request for session tracking.
- Choice:
  - Accept and log `anthropic-version`, `anthropic-beta`, and `X-Claude-Code-Session-Id`.
  - Do NOT validate or reject requests missing these headers (they are optional for non-Claude-Code clients).
  - Forward `anthropic-beta` and `anthropic-version` context to the runtime if the runtime supports it; otherwise accept-and-ignore.
  - Expose `X-Claude-Code-Session-Id` in request logs for observability.
  - Re-verify the exact external header contract immediately before implementation.
- Rationale:
  - Forwarding is required by the gateway contract. Even if the Copilot SDK runtime doesn't use them, accepting them prevents Claude Code from failing.

### New Decision 9: Extended thinking — accept and pass through where possible
- Context:
  - Claude Code uses `thinking` request parameter for extended thinking. Response includes `thinking` and `redacted_thinking` content blocks.
  - Our facade is text-only and strips all non-text content blocks.
  - The Copilot SDK runtime interacts with Claude-family models and may return thinking blocks.
- Choice:
  - Add the `thinking` field to the Anthropic request model (accepted-but-ignored if runtime doesn't support it).
  - Pass through `thinking` / `redacted_thinking` only when the runtime surfaces them in a structured form.
  - Runtime checkpoint result (2026-04-03): the current Copilot SDK session path exposes `reasoning_effort` but not an Anthropic-native `thinking` request parameter, and a live `claude-sonnet-4.6` streaming probe with `reasoning_effort=high` returned no structured `thinking`, `redacted_thinking`, `reasoningText`, or `reasoningOpaque` content. Passthrough is therefore deferred on the current runtime path.
  - Keep tool_use/code_execution blocks out of scope (these are deep model-specific features beyond our boundary).
  - If upstream runtime behavior changes later, revisit passthrough as a separate behavior change covering normalization, response models, and contract/streaming tests.
- Rationale:
  - Extended thinking is a high-value Claude Code feature. Stripping thinking blocks silently degrades the user experience without clear indication. Passthrough is low-risk because it doesn't require the provider to generate thinking — only to not strip it.

### New Decision 10: Streaming usage data should be included
- Context:
  - Official Anthropic API includes `usage` in `message_start` and `message_delta` streaming events.
  - Our current schemas can carry usage data, but the streaming builders do not populate those fields from runtime token data.
  - Claude Code may depend on populated usage for cost tracking and display.
- Choice:
  - Populate Anthropic streaming `usage` fields where token counts are available from the runtime.
  - Use estimation (consistent with count_tokens) when exact counts are not available.
  - For the OpenAI Responses surface, populate `usage` in the final `response.completed` event.
- Rationale:
  - Usage data is observability-critical for cost-conscious clients and agent loops.

### New Decision 11: Responses API `truncation` field
- Context:
  - Codex sends `truncation` ("auto" or "disabled") to control context management.
  - Our request model does not include this field.
- Choice:
  - Add `truncation` to the Responses request model as accepted-but-ignored.
  - Do not implement actual truncation logic (the Copilot SDK runtime manages its own context).
- Rationale:
  - Prevents Codex from receiving validation errors for an expected field. Truncation semantics are runtime-managed, not provider-managed.

### Revised compatibility classification

Based on all findings, here is the consolidated field classification for both facades:

#### OpenAI Responses (Codex-facing)

| Field | Classification | Notes |
|---|---|---|
| `model` | ✅ Supported | Forwarded to runtime |
| `input` | ✅ Supported | Normalized to canonical messages |
| `instructions` | ✅ Supported | System message |
| `stream` | ✅ Supported | Forwarded |
| `tools` | ⚠️ Accept-ignore | Echoed in response, not executed |
| `tool_choice` | ⚠️ Accept-ignore | Echoed |
| `parallel_tool_calls` | ⚠️ Accept-ignore | Echoed |
| `previous_response_id` | ⚠️ Accept-ignore | Echoed |
| `store` | ⚠️ Accept-ignore | Echoed |
| `truncation` | ⚠️ Accept-ignore | **NEW: needs adding** |
| `reasoning` | ⚠️ Accept-ignore | Accepted, not processed |
| `include` | ⚠️ Accept-ignore | Accepted |
| `prompt_cache_key` | ⚠️ Accept-ignore | Accepted |

#### Anthropic Messages (Claude Code-facing)

| Field | Classification | Notes |
|---|---|---|
| `model` | ✅ Supported | Forwarded to runtime |
| `messages` | ✅ Supported | Text content extracted; structured thinking passthrough is deferred because current runtime evidence does not surface those blocks |
| `system` | ✅ Supported | Extracted as system message |
| `max_tokens` | ⚠️ Accept-ignore | Accepted, not enforced |
| `stream` | ✅ Supported | Forwarded |
| `metadata` | ⚠️ Accept-ignore | Accepted |
| `tools` | ⚠️ Accept-ignore | Accepted, not executed |
| `thinking` | ⚠️ Accept-ignore | **NEW: accepted for compatibility; passthrough deferred on current runtime path** |
| `temperature` | ⚠️ Accept-ignore | Accepted |
| `top_p` | ⚠️ Accept-ignore | Accepted |
| `top_k` | ⚠️ Accept-ignore | Accepted |
| `stop_sequences` | ⚠️ Accept-ignore | Accepted |
| `tool_choice` | ⚠️ Accept-ignore | Accepted |

#### Anthropic Headers (Claude Code-facing)

| Header | Classification | Notes |
|---|---|---|
| `Authorization` | ✅ Supported | Extracted |
| `x-api-key` | ✅ Supported | Fallback auth |
| `anthropic-version` | ⚠️ Accept-log | **NEW: must handle** |
| `anthropic-beta` | ⚠️ Accept-log | **NEW: must handle** |
| `X-Claude-Code-Session-Id` | ⚠️ Accept-log | **NEW: for observability** |

## Open Questions
- Q1:
  - Which currently ignored fields are harmless enough to remain accepted for client smoothness, and which should become explicit rejections?
- Q2:
  - Should compatibility completion include a published support matrix in `README.md`, or keep the matrix limited to design/tests and only document the highest-impact gaps?
- Q3:
  - How much Claude Code gateway metadata should be surfaced internally (for logs/tests) versus simply tolerated and ignored?
- Q4 (resolved):
  - Runtime checkpoint on 2026-04-03 showed that the current Copilot SDK session path does not expose structured thinking blocks or Anthropic-native thinking controls, so passthrough is not currently feasible without upstream runtime changes.
- Q5 (new):
  - When runtime exact token counts are unavailable, how should estimated usage be labeled or documented so clients can distinguish approximation from exact counts?
- Q6 (new):
  - What is the exact current Codex wording and behavior around `chat/completions` versus `responses`, and how should that be reflected in user-facing docs at implementation time?

## Review Notes / Annotations
(Place for reviewer comments. Agent must incorporate feedback and re-submit for approval before proceeding to plan.)

## Approval
- [x] Design approved by: User
- Date: 2026-04-03
