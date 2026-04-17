# Research Log

> Purpose: capture the evidence behind treating Codex tool routing as a design
> problem instead of a narrow hotfix.

## Task

- Re-evaluate the current Codex/Desktop "one sentence then stop" work as a
  first-class architecture slice.
- Identify the real design boundary that should stabilize before more code lands.

## Current state

- The provider already supports client-driven tool continuation across turns.
- The remaining Codex failure is concentrated in **first-hop tool routing**:
  whether the model enters the external/MCP tool loop at all.
- The current working tree solves that empirically, but the behavior is still
  spread across multiple layers instead of being represented as one deliberate
  design surface.

## Evidence

### Protocol and canonical-contract evidence

- `src/copilot_model_provider/core/models.py:354-380`
  - `OpenAIResponsesCreateRequest` accepts `previous_response_id`,
    `parallel_tool_calls`, `tool_choice`, and `tools`.
- `src/copilot_model_provider/core/models.py:88-108`
  - `CanonicalChatRequest` currently carries `messages`, `tool_definitions`,
    `tool_results`, `session_id`, and `stream`, but no first-class routing
    policy or preserved tool-routing hints.
- `src/copilot_model_provider/core/compat.py:50-113`
  - Responses `previous_response_id`, `parallel_tool_calls`, `tool_choice`, and
    `tools` are still documented as `accept_ignore`.
  - Anthropic `tools` is also still documented as `accept_ignore`.

### Prompt and runtime evidence

- `src/copilot_model_provider/core/chat.py:56-77`
  - Canonical messages are flattened into a plain-text transcript ending with
    `Assistant:`.
- `src/copilot_model_provider/runtimes/copilot_runtime.py:53-59`
  - Current routing behavior depends on hard-coded guidance and a hard-coded
    excluded built-in tool list.
- `src/copilot_model_provider/runtimes/copilot_runtime.py:668-836`
  - Interactive-session creation, built-in suppression, external tool
    registration, and tool-aware guidance are already real runtime behavior.

### Tool-surface evidence

- `src/copilot_model_provider/core/responses.py:38-84`
  - Responses normalization already maps northbound tools into canonical
    `tool_definitions` and continuation items into `tool_results`.
- `src/copilot_model_provider/core/responses.py:417-520`
  - Responses normalization now preserves `web_search` and `custom`, and keeps
    the response-visible tool surface aligned with the runtime-visible one.
- `tests/unit_tests/test_responses.py:96-167`
  - Unit tests already lock in `web_search` / `custom` preservation and
    response-visible `web_search` normalization.
- `tests/unit_tests/test_copilot_runtime.py:981-1033`
  - Unit tests already lock in `skip_permission=True` and built-in
    `apply_patch` override handling.

### Wire-path evidence

- `src/copilot_model_provider/api/openai/responses.py:63-131`
  - The Responses route already maps `response_id -> session_id` for
    continuation.
- `src/copilot_model_provider/api/openai/responses.py:141-340`
  - Streaming Responses output already serializes pending tool calls as
    `function_call`.
- `src/copilot_model_provider/streaming/translators.py:244-263`
  - SDK `EXTERNAL_TOOL_REQUESTED` is already translated into a canonical
    `ToolCallRequestedEvent`.
- `tests/integration_tests/test_responses.py:127-185`
  - OpenAI Responses continuation is already covered end to end.
- `tests/integration_tests/test_anthropic_messages.py:70-123`
  - Anthropic Messages continuation is already covered end to end.

## Findings

1. **This is no longer a "missing tool loop" problem.**
   - The provider already has the shared continuation substrate.
   - The unresolved design gap is the policy that decides how tool-aware
     sessions should route their first tool request.

2. **The current behavior is design-relevant, but the design is implicit.**
   - Today the effective routing policy is encoded as:
     - tool-surface preservation in protocol normalization
     - SDK built-in suppression in runtime session creation
     - synthetic guidance injected into tool-aware prompts
    - Leaving this as scattered implementation detail will make future routing
      regressions hard to reason about.
   - The current mixed working tree proves the behavior can work, but it still
     does **not** provide a first-class policy object. That mismatch must be
     resolved at design time before the branch is treated as an implementation
     baseline.

3. **The right first-class boundary is "tool-aware client-passthrough session
   policy".**
   - The provider should explicitly represent:
     - whether a request is a client-passthrough tool session
     - which SDK built-ins must yield to northbound tools
     - what routing guidance applies to the model
     - which upstream tool-routing hints are preserved, even if not yet fully
       enforced

4. **The provider should remain thin.**
   - Nothing in the evidence justifies provider-owned tool or MCP execution.
   - The correct boundary remains: provider preserves and routes tool use,
     northbound clients execute the tools.

5. **A design-first approach does not require full `tool_choice` enforcement in
   v1.**
   - But it does require stopping the current pattern where these fields are
     accepted and then conceptually disappear from the design story.

6. **The design must specify derivation and validation, not only new field
   names.**
   - The key unresolved questions are:
     - when a request enters `client_passthrough` mode
     - what happens when tool results arrive without a recoverable provider
       session
     - which upstream hints are preserved as typed fields versus opaque payloads
   - Without these rules, the proposed policy abstraction would still be too
     vague to guide PR 1 safely.

## Conflict hotspots

- `src/copilot_model_provider/core/models.py`
- `src/copilot_model_provider/core/compat.py`
- `src/copilot_model_provider/core/chat.py`
- `src/copilot_model_provider/core/responses.py`
- `src/copilot_model_provider/runtimes/copilot_runtime.py`
- `src/copilot_model_provider/api/openai/responses.py`
- `src/copilot_model_provider/api/anthropic/messages.py`
- `src/copilot_model_provider/api/anthropic/protocol.py`

## Unknowns

- Whether `tool_choice` should become a preserved canonical hint immediately, or
  wait for a later protocol-policy slice.
- Whether the current text-prompt bridge should later move to a more structured
  SDK `system_message` path.
- Whether Anthropic should share the exact same routing-policy abstraction, or
  only the same runtime substrate.

## Conclusion

Proceed with a **base design slice** that makes tool-aware client-passthrough
policy explicit in the canonical/runtime contract, then fan protocol work out on
top of that base. The current mixed diff should be treated as evidence and prior
art, not as the final review unit.
