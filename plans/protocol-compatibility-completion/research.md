# Research Log

> Purpose: capture facts, evidence, and unknowns before planning/implementation.
> This is the review surface for understanding and diagnosis.

## Task
- Summary:
  - Deep research the next round of protocol compatibility completion for `copilot-model-provider`, using the latest official API, Codex, and Claude Code docs plus the current repository implementation.
- Links (issue/PR/spec):
  - `AGENTS.md`
  - `docs/design.md`
  - OpenAI Codex docs:
    - https://developers.openai.com/codex/config-reference
    - https://developers.openai.com/codex/config-sample
    - https://developers.openai.com/codex/config-advanced
  - Claude Code docs:
    - https://code.claude.com/docs/en/settings
    - https://code.claude.com/docs/en/model-config
    - https://code.claude.com/docs/en/llm-gateway
  - Anthropic docs:
    - https://platform.claude.com/docs/en/api/messages
    - https://platform.claude.com/docs/en/build-with-claude/working-with-messages
    - https://platform.claude.com/docs/en/build-with-claude/streaming

## Current Behavior
- Observed behavior:
  - The repository already ships a dual-protocol, thin, stateless provider with:
    - OpenAI facade under `/openai/v1/...`
    - Anthropic facade under `/anthropic/v1/...`
  - The current shipped northbound endpoints are:
    - `GET /openai/v1/models`
    - `POST /openai/v1/chat/completions`
    - `POST /openai/v1/responses`
    - `GET /anthropic/v1/models`
    - `POST /anthropic/v1/messages`
    - `POST /anthropic/v1/messages/count_tokens`
    - `GET /_internal/health`
  - The product is intentionally thin:
    - no provider-owned session persistence
    - no server-side tools / MCP execution
    - auth-context-driven live model exposure
    - runtime execution delegated to `github-copilot-sdk`
- Expected behavior:
  - Keep the same product boundary, but close the highest-value protocol compatibility gaps that matter for the current official Codex and Claude Code clients and for the latest public API shapes they rely on.
  - Preserve **upper-layer transparency**: for any model visible from the current GitHub Copilot auth context, upper-layer clients such as Codex and Claude Code should be able to address that model by setting the model id only.
  - Differences that come from the model's own native capability surface (for example deeper Claude-native tool/computer/multimodal semantics) remain out of scope for this provider.
- Scope affected (modules/endpoints/commands):
  - `src/copilot_model_provider/api/openai/`
  - `src/copilot_model_provider/api/anthropic/`
  - `src/copilot_model_provider/api/shared.py`
  - `src/copilot_model_provider/core/`
  - `src/copilot_model_provider/streaming/`
  - `scripts/config_codex.py`
  - `scripts/config_claude.py`
  - protocol contract tests and client-facing docs

## Environment
- OS:
  - Darwin
- Runtime/tool versions:
  - Repository uses Python 3.14+ and `uv`
  - Runtime integration is built on `github-copilot-sdk`
- Repro command(s):
  - Code reading with `view` / `rg`
  - Official doc fetches with `web_fetch`
  - Official doc search with `web_search`

## Evidence
Include concrete evidence. Prefer copy/paste of relevant excerpts with context.
- Logs / stack traces:
  - No runtime failure investigation was needed for this planning task.
- Failing tests (name + output excerpt):
  - No failing tests were required to justify the research direction; the work is driven by compatibility-completion opportunity rather than a single breakage.
- Metrics (numbers + method):
  - Current validation baseline in this repo is stable and above the coverage gate.
- Repro steps (minimal):
  1. Read the current shipped surface from `README.md` and `docs/design.md`.
  2. Inspect source and tests for the concrete request/response/streaming behavior.
  3. Compare that behavior to current official docs for Codex config, Claude Code gateway requirements, Anthropic Messages, and the latest public OpenAI/Codex guidance.

### External documentation facts
- Codex official config docs confirm that Codex is configured through `~/.codex/config.toml` (and project-scoped `.codex/config.toml`) with:
  - root `model`
  - root `model_provider`
  - `[model_providers.<id>]`
  - provider fields such as `base_url`, `env_key`, `wire_api`, optional headers, query params, and retry settings
- Codex advanced config docs confirm:
  - project-scoped `.codex/config.toml` layers exist
  - `openai_base_url` can retarget the built-in OpenAI provider
  - custom provider layers remain a first-class configuration mechanism
- Claude Code official settings docs confirm:
  - settings scopes:
    - `~/.claude/settings.json`
    - `.claude/settings.json`
    - `.claude/settings.local.json`
  - user scope is the right default for personal CLI bootstrap flows
- Claude Code official gateway docs confirm:
  - supported gateway API families are:
    - Anthropic Messages
    - Bedrock InvokeModel
    - Vertex rawPredict
  - an Anthropic-compatible gateway must expose at least:
    - `/v1/messages`
    - `/v1/messages/count_tokens`
  - Claude Code sends `X-Claude-Code-Session-Id` on every API request
  - gateway auth commonly uses `ANTHROPIC_AUTH_TOKEN` or `apiKeyHelper`
- Anthropic working-with-messages docs confirm:
  - the Messages API is stateless
  - clients send the full conversation history every turn
  - system content, multi-turn messages, vision, tools, and structured outputs are all part of the broader Messages surface
- Anthropic streaming docs confirm:
  - standard event flow:
    - `message_start`
    - content block start / delta / stop events
    - one or more `message_delta`
    - `message_stop`
  - `ping` events may appear
  - unknown future event types should be tolerated gracefully
  - streaming errors may appear in-stream

### Repository evidence
- `README.md`
  - documents the currently supported OpenAI and Anthropic routes
  - documents Codex and Claude setup scripts as first-class user flows
- `docs/design.md`
  - documents the current implementation as a dual-protocol, thin, stateless provider
  - explicitly states that session persistence and server-side tools/MCP are out of scope
- `src/copilot_model_provider/api/openai/*.py`
  - provides OpenAI models, chat completions, and responses routes
- `src/copilot_model_provider/api/anthropic/*.py`
  - provides Anthropic models, messages, and count_tokens routes
- `src/copilot_model_provider/core/routing.py`
  - centralizes auth-context live model discovery and routing
  - now includes short-TTL auth-context cache entries with concurrent request coalescing
- `tests/contract_tests/`
  - already lock down meaningful parts of both protocol facades and should remain the main regression surface for compatibility work
- User requirement established during design discussion:
  - any GitHub Copilot-provided visible model should be addressable transparently by upper-layer clients through this provider when the client is configured with the matching model id
  - model-native capability differences themselves are not the provider's responsibility

## Code Reading Notes
List the most relevant files and what you learned.
- `README.md` — current user-facing contract already treats Codex and Claude as the two main client targets.
- `docs/design.md` — current architecture baseline is dual-protocol, stateless, text-first, and thin.
- `src/copilot_model_provider/api/openai/chat.py` — current chat facade is intentionally narrow; many standard OpenAI parameters are not forwarded.
- `src/copilot_model_provider/api/openai/responses.py` — current Responses facade is intentionally shaped around Codex-style needs rather than full Responses parity.
- `src/copilot_model_provider/api/openai/models.py` — current model listing is auth-context-aware and driven by the shared live catalog.
- `src/copilot_model_provider/api/anthropic/messages.py` — current Anthropic messages facade already exists, including streaming and count_tokens.
- `src/copilot_model_provider/api/anthropic/protocol.py` — current Anthropic normalization/count-token behavior is intentionally text-first and estimation-based.
- `src/copilot_model_provider/api/shared.py` — central auth extraction and streaming dedup logic live here; this is a likely hot spot for compatibility completion.
- `src/copilot_model_provider/core/models.py` — canonical internal request/response shapes constrain what both facades can support.
- `src/copilot_model_provider/core/chat.py` and `src/copilot_model_provider/core/responses.py` — normalization is currently text-oriented and strips many richer protocol concepts.
- `src/copilot_model_provider/streaming/` — protocol-specific streaming completion is translated from shared runtime events here.
- `tests/contract_tests/test_openai_*` — lock down the current OpenAI compatibility subset.
- `tests/contract_tests/test_anthropic_*` — lock down the current Anthropic compatibility subset.
- `scripts/config_codex.py` — codifies the practical assumptions Codex integration depends on.
- `scripts/config_claude.py` — codifies the practical assumptions Claude Code integration depends on.

## Supplementary Research (Round 2) — 2026-04-03

### Critical Finding 1: Codex-side compatibility now centers on `wire_api = "responses"`

- Source: https://github.com/openai/codex/discussions/7782
- Based on current external Codex materials (docs and discussions), `wire_api = "responses"` appears to be the Codex-preferred path and `chat/completions` appears to be secondary for Codex.
- Treat this as an external prioritization signal rather than a repository-verified fact.
- Implication: our `/openai/v1/responses` endpoint is the primary Codex-relevant OpenAI-style endpoint and should be treated as the main Codex compatibility anchor.
- This does **not** change our provider boundary or endpoint support strategy: `/openai/v1/chat/completions` still matters for non-Codex OpenAI-compatible clients and remains in scope as a first-class endpoint.
- Re-verify the exact Codex wording and behavior immediately before implementation.

### Critical Finding 2: Codex Responses API — actual fields sent

Based on Codex source analysis and official documentation:

| Field | Always sent? | Our support |
|---|---|---|
| `model` | Yes | ✅ Forwarded |
| `instructions` | Yes | ✅ Forwarded (system message) |
| `input` | Yes | ✅ Forwarded (messages) |
| `tools` | Often | ⚠️ Accepted, echoed back, not executed |
| `stream` | Usually true | ✅ Forwarded |
| `previous_response_id` | Optional (stateful) | ⚠️ Accepted, echoed back |
| `truncation` | Optional ("auto"/"disabled") | ❌ **Not in our request model** |
| `reasoning` | Optional (reasoning models) | ⚠️ Accepted, ignored |
| `reasoning.encrypted_content` | Optional (ZDR mode) | ❌ **Not handled** |
| `store` | Optional (default false) | ⚠️ Accepted, echoed back |
| `tool_choice` | Optional | ⚠️ Accepted, echoed back |
| `parallel_tool_calls` | Optional | ⚠️ Accepted, echoed back |
| `include` | Optional | ⚠️ Accepted, ignored |
| `prompt_cache_key` | Optional | ⚠️ Accepted, ignored |

- `truncation` parameter controls context window management ("auto" = drop oldest, "disabled" = error if too long). This is missing from our request model entirely.

### Critical Finding 3: Claude Code gateway header requirements

Official Claude Code gateway docs (https://code.claude.com/docs/en/llm-gateway) explicitly state:

> "Must forward request headers: `anthropic-beta`, `anthropic-version`"
> "Failure to forward headers or preserve body fields may result in reduced functionality or inability to use Claude Code features."

Claude Code headers sent on every request:

| Header | Purpose | Our support |
|---|---|---|
| `Authorization: Bearer <token>` | Auth | ✅ Extracted |
| `x-api-key` | Alt auth | ✅ Extracted (fallback) |
| `anthropic-version` | API version (value: `2023-06-01`) | ❌ **Not handled** |
| `anthropic-beta` | Beta feature flags | ❌ **Not handled** |
| `X-Claude-Code-Session-Id` | Session tracking | ❌ **Not handled** |
| `Content-Type: application/json` | Content type | ✅ Standard |

- Because these header requirements come from external documentation, the exact contract should be re-verified immediately before implementation.

### Critical Finding 4: Extended thinking / thinking blocks

- Claude Code supports extended thinking via the `thinking` request parameter: `{"type": "enabled", "budget_tokens": N}`.
- Claude Code also supports `effort` levels (low/medium/high/max) which map to thinking budget.
- API response includes new content block types:
  - `ThinkingBlock`: `{type: "thinking", thinking: str, signature: str}`
  - `RedactedThinkingBlock`: `{type: "redacted_thinking", data: str}`
- Streaming events for thinking: `content_block_start` with `type: "thinking"`, then `content_block_delta` with thinking text deltas.
- **Impact on our facade:** Our Anthropic facade is text-only — it strips all content blocks except `type: "text"`. Extended thinking functionality is effectively broken through our gateway.
- The `thinking` field is a top-level request parameter (not in `messages`), and our request model (`AnthropicMessagesRequest`) does not include it.
- This is not just a missing field: supporting thinking passthrough would be a behavior change in request normalization, response shaping, and contract tests because the current implementation explicitly discards non-text content blocks.

### Critical Finding 5: Anthropic content block richness

The Anthropic Messages API now supports many content block types beyond `text`:

| Block type | Purpose | Our support |
|---|---|---|
| `text` | Plain text output | ✅ Handled |
| `thinking` | Extended thinking reasoning | ❌ Not handled |
| `redacted_thinking` | Redacted reasoning | ❌ Not handled |
| `tool_use` | Tool calling | ❌ Not handled (accepted in request, not in response) |
| `tool_result` | Tool execution results | ❌ Not handled |
| `code_execution_result` | Server code execution | ❌ Not handled |
| `bash_code_execution_result` | Bash execution | ❌ Not handled |
| `container_upload` | File uploads | ❌ Not handled |
| Citations in `text` blocks | Source attribution | ❌ Not handled |

- For model-id transparency, when an upper-layer client (Claude Code) sends requests with `thinking` enabled, the gateway should aim to **pass through** thinking blocks in responses even if it does not generate them itself.
- The Copilot SDK runtime handles the actual model interaction; the question is whether the runtime returns thinking blocks and whether our facade strips them.

### Critical Finding 6: Anthropic error response format mismatch

Official Anthropic error format:
```json
{
  "type": "error",
  "error": {
    "type": "invalid_request_error",
    "message": "Human-readable error message"
  },
  "request_id": "req_XXXXXXXXXXXX"
}
```

Error types and HTTP status codes:
- `invalid_request_error` → 400
- `authentication_error` → 401
- `rate_limit_error` → 429
- `overloaded_error` → 529

Our current implementation:
- **Streaming errors** already use an Anthropic-shaped error event: `{type: "error", error: {type: "api_error", message: "..."}}` ✅
- **Non-streaming errors** use the shared OpenAI-style format for both facades: `{error: {code: "...", message: "..."}}` ❌
- Impact: Claude Code may not correctly parse non-streaming error responses from our Anthropic facade.

### Critical Finding 7: Anthropic streaming usage data

Official API includes `usage` in streaming events:
- `message_start` event: `{usage: {input_tokens: N, output_tokens: 0}}`
- `message_delta` event: `{usage: {output_tokens: N}}`

Our facade:
- The streaming/event schemas are usage-capable, but current builders do not populate `usage` from runtime token data.
- Claude Code may depend on populated streaming usage for cost tracking and display.

### Critical Finding 8: Anthropic prompt caching (`cache_control`)

- `cache_control: {type: "ephemeral", ttl: "5m"|"1h"}` can be attached to content blocks.
- Used by Claude Code for prompt caching in multi-turn agent workflows.
- Our facade strips these fields.
- **Assessment:** This is likely acceptable as "accepted-but-ignored" since caching is a server-side optimization and our runtime (Copilot SDK) has its own caching semantics.

### Critical Finding 9: Claude Code model configuration

- Claude Code supports `ANTHROPIC_CUSTOM_MODEL_OPTION` env var to add custom model IDs to the picker.
- Quote: _"Claude Code skips validation for the model ID set in ANTHROPIC_CUSTOM_MODEL_OPTION, so you can use any string your API endpoint accepts."_
- This supports our model-id transparency goal — any Copilot-visible model id can be set.
- Claude Code model aliases (sonnet, opus, haiku) can be overridden via `ANTHROPIC_DEFAULT_*_MODEL` env vars.
- Our `config_claude.py` script should ensure these are configured correctly.

### Critical Finding 10: Responses API streaming event taxonomy

Full event lifecycle:
1. `response.created` — initial response object (status: 'in_progress')
2. `response.output_item.added` — new output item
3. `response.content_part.added` — new content part within item
4. `response.output_text.delta` — text delta (repeated)
5. `response.content_part.done` — finalized content part
6. `response.output_item.done` — finalized output item
7. `response.completed` — final response (status: 'completed')

Additional events (not in our implementation):
- `response.queued` — queued for processing
- `response.in_progress` — started processing
- `response.failed` — generation failed
- `response.incomplete` — generation truncated

Our implementation covers the happy-path event sequence correctly ✅. Missing events are primarily for error/edge cases.

### Critical Finding 11: Responses API `usage` in final event

The `response.completed` event's response object should include `usage`:
```json
{
  "usage": {
    "input_tokens": N,
    "output_tokens": N,
    "total_tokens": N
  }
}
```

Our facade includes `usage` in the response object but may not populate actual token counts from runtime.

### Revised gap analysis

Based on this supplementary research, the **priority-ranked gaps** are:

1. **[P0] Anthropic facade: non-streaming error response format** — uses OpenAI format, should use Anthropic format. Claude Code will misparse errors.
2. **[P0] Anthropic facade: `anthropic-version` / `anthropic-beta` header handling** — gateway docs say "must forward", failure = "reduced functionality". At minimum should accept and log.
3. **[P1] Anthropic facade: `thinking` request parameter and thinking content blocks in responses** — extended thinking is broken through our gateway.
4. **[P1] Responses API: `truncation` field** — missing from request model, Codex may send it.
5. **[P1] Anthropic facade: streaming usage data** — `message_start` and `message_delta` should include usage counts.
6. **[P2] Anthropic facade: `X-Claude-Code-Session-Id` header** — useful for observability, not strictly required for function.
7. **[P2] Responses API: additional streaming events** — `response.failed`, `response.incomplete` for error cases.
8. **[P2] Chat/completions stays first-class** — apply same compatibility treatment (error handling, field classification) as Responses; document Codex's preference for Responses.
9. **[P3] Anthropic facade: `cache_control` passthrough** — acceptable as ignored for now.
10. **[P3] Responses API: `reasoning.encrypted_content`** — ZDR-specific, niche.

## Hypotheses (ranked)
1. **The biggest missing value is not “more endpoints”, but tighter compatibility semantics on the existing endpoints.**
   - The repo already has both OpenAI and Anthropic facades.
   - The most likely gains are in request-field handling, header semantics, streaming correctness, error envelopes, and support-matrix clarity.
2. **Trying to chase full upstream API parity would violate the product boundary.**
   - Current official APIs include tools, multimodal content, persistent/stateful flows, prompt caching, and other platform features that this repo explicitly does not own.
   - A better target is “client-critical compatibility completion” for Codex and Claude Code.
3. **The missing design artifact is an explicit compatibility policy, not just more route code.**
   - Today there is no single documented support matrix for:
     - supported
     - accepted-but-ignored
     - rejected-with-structured-error
    - Without that policy, future compatibility additions will be ad hoc and brittle.
4. **Model-id transparency across clients is the real success criterion.**
   - The provider does not need to emulate every native model-family feature.
   - It does need to ensure that any Copilot-visible model id can be selected cleanly from either client family through the appropriate facade.

## Experiments Run
For each experiment:
- Command / action:
  - Read `AGENTS.md` and repository planning templates.
  - Result:
    - Repo-resident planning artifacts are explicitly allowed when requested and should be written under `plans/{slug}/`.
  - Interpretation:
    - This task should produce a reviewable slug with `research.md` and `design.md`, then stop for approval.

- Command / action:
  - Read `README.md` and `docs/design.md`.
  - Result:
    - The repo already positions itself as a dual-protocol provider targeting Codex-style and Claude-style clients.
  - Interpretation:
    - Compatibility completion should work with this positioning, not replace it.

- Command / action:
  - Inspect current API and contract test files.
  - Result:
    - Both protocol facades exist today, but they intentionally support a text-first subset.
  - Interpretation:
    - The next milestone should prioritize compatible semantics on the existing routes.

- Command / action:
  - Fetch Codex official config docs.
  - Result:
    - Codex expects config-driven model provider definitions with explicit provider selection and wire API choices.
  - Interpretation:
    - OpenAI-side compatibility work should be evaluated against what Codex actually consumes rather than generic OpenAI parity alone.

- Command / action:
  - Fetch Claude Code official settings and gateway docs.
  - Result:
    - Claude Code is explicitly gateway-oriented and officially anchored on Anthropic Messages, Bedrock, or Vertex-compatible surfaces.
  - Interpretation:
    - Anthropic-side compatibility semantics matter directly for Claude Code interoperability.

- Command / action:
  - Fetch Anthropic Messages working/streaming docs.
  - Result:
    - Anthropic streaming and stateless message semantics are richer than the repo’s current text-first subset.
  - Interpretation:
    - Claude-facing compatibility completion should focus on the client-relevant subset while explicitly rejecting out-of-bound features.

## Open Questions / Unknowns
- Q1:
  - Which currently accepted-but-ignored fields are safe to continue accepting silently, and which should instead fail with explicit structured errors because silent no-op behavior would mislead clients?
- Q2:
  - Which Claude Code requests in practice rely on `anthropic-beta`, `anthropic-version`, `X-Claude-Code-Session-Id`, and related gateway semantics strongly enough that they should be surfaced, persisted in request context, or reflected in logs/tests?
- Q3:
  - For OpenAI Responses semantics, which parts are required by current Codex releases versus merely present in the broader public API?
- Q4:
  - Should protocol compatibility completion also formalize a public support matrix in docs, or keep the matrix test-only plus internal design?

## Recommendation for Plan
- Proposed direction:
  - Design for **client-critical compatibility completion** rather than broad upstream parity.
  - Keep the current endpoint set and product boundary.
  - Elevate **model-id transparency** to a first-class compatibility contract:
    - if a model id is visible in the current auth context, upper-layer clients should be able to switch to it without any provider-side alias mapping or client-specific special casing beyond configuring that model id
  - Add an explicit compatibility policy across both facades:
    - supported and translated
    - accepted but intentionally ignored
    - explicitly rejected with structured errors
  - Prioritize work that improves real Codex and Claude Code interoperability:
    - request-field handling
    - header/auth semantics
    - streaming/event correctness
    - usage / token-count semantics
    - structured error behavior
    - documentation of the supported subset
- Risks:
  - Official APIs and client behaviors move quickly, so any design should anchor to documented client-critical behaviors, not attempt endless parity chasing.
  - Silent no-op support for unsupported fields can look compatible while producing surprising behavior.
  - Expanding too far into tools, multimodal, or persistence would violate the project boundary.
- Suggested verification level (L1/L2/L3):
  - **L2**
  - This work changes public protocol behavior and should be validated with contract/integration/client-smoke evidence, not only unit tests.
