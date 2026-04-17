# Design Document

> Purpose: define the first-class architecture for Codex tool routing support
> before resuming implementation.

## Objective

- Support Codex/Desktop-style tool routing as a **designed provider capability**,
  not as a narrow hotfix.
- Preserve the provider's thin boundary: the provider routes and resumes tool
  turns, but does not execute user tools or MCP servers itself.
- Stabilize one shared base that both OpenAI Responses and Anthropic Messages
  can build on.

## Non-goals

- Provider-owned tool execution.
- Full generic agent-platform expansion inside the provider.
- Immediate enforcement of every northbound `tool_choice` /
  `parallel_tool_calls` semantic if the runtime cannot honor it yet.
- Merging the current mixed working tree as one large "design" PR.

## Chosen architecture

### 1. Introduce a first-class tool-aware session policy

Add one explicit canonical policy object for tool-aware sessions. It should be
the single source of truth for:

- whether the request is a client-passthrough tool session
- which SDK built-in tools are suppressed in favor of northbound tools
- what routing guidance is attached to the model for this session
- which upstream routing hints are preserved for future policy decisions

This turns the current implicit combination of normalization rules, excluded
built-ins, and synthetic guidance into one owned design surface.

### 1a. Make the policy concrete in PR 1

PR 1 should not merely mention a future policy abstraction. It should introduce
concrete internal types along these lines:

- `CanonicalToolRoutingHint`
  - `surface`: `openai_responses | anthropic_messages`
  - `tool_choice`: preserved Responses value, if present
  - `parallel_tool_calls`: preserved Responses value, if present
- `CanonicalToolRoutingPolicy`
  - `mode`: `none | client_passthrough`
  - `hint`: `CanonicalToolRoutingHint | None`
  - `excluded_builtin_tools`: ordered tuple of SDK built-ins to suppress
  - `guidance`: optional routing guidance text

The exact field names may differ, but PR 1 must ship a real policy object rather
than leaving the routing rules encoded only as runtime constants.

### 2. Keep the shared interactive session as the runtime substrate

Do not redesign away from the current interactive-session approach. It already
provides the right base behavior:

- resumable provider session ids
- pending tool-call tracking
- tool-result continuation
- translation from SDK external-tool events into canonical tool calls

The design problem is not session continuity anymore; it is how those sessions
should be configured for tool-aware routing.

### 3. Separate routing policy from prompt rendering

`render_prompt()` may continue to render canonical message history as text for
now, but routing policy must not live as ad-hoc constants buried in runtime
code.

The initial implementation may still realize policy through:

- a narrow guidance message
- a narrow built-in exclusion list

but those behaviors should be **derived from the policy object**, not hard-coded
as one-off hotfix logic.

### 3a. Define policy derivation and validation explicitly

The base design must also define how policy is derived:

1. `mode = none`
   - when the canonical request has no `tool_definitions`, no `tool_results`,
     and no continuation `session_id`
2. `mode = client_passthrough`
   - when the request starts a tool-aware turn with client-provided tools
   - when the request continues a prior tool-aware turn via recovered
     `session_id`
   - when the request contains `tool_results`

And it must define the minimum validation rules:

1. A request that carries `tool_results` but has no recoverable provider
   `session_id` is invalid and should fail fast with a client error.
2. A continuation `session_id` that does not match a live provider session is
   invalid and should fail fast.
3. Non-tool requests must derive a no-op policy and keep current behavior.

This makes PR 1 testable and prevents PR 2 from depending on an underspecified
"base policy."

### 4. Preserve northbound tool surfaces losslessly enough for routing

The provider must continue preserving the tool surface the model actually needs
to see:

- OpenAI Responses `function`
- OpenAI Responses `web_search`
- OpenAI Responses `custom`
- Anthropic Messages `tools`

The response-visible tool list must stay aligned with the runtime-visible tool
surface so that clients, logs, and tests all describe the same routing context.

### 5. Make compatibility documentation match actual support

Once the base design lands, compatibility metadata should stop describing key
tool-routing fields as pure `accept_ignore` when they now participate in real
behavior.

At minimum:

- Responses `tools` and `previous_response_id` should reflect actual support.
- If `tool_choice` / `parallel_tool_calls` are preserved only as hints, that
  should be represented honestly in compat notes and internal naming.
- Anthropic `tools` should reflect actual supported passthrough behavior.

PR 1 should therefore include the compatibility-table update, not defer it to a
later cleanup PR.

## Proposed internal interfaces

### Canonical request

Extend `CanonicalChatRequest` with a routing-policy field, for example:

- `tool_routing_policy: CanonicalToolRoutingPolicy`

The exact names can change, but the design goal is fixed: policy must become a
first-class part of the canonical contract instead of being reconstructed in
runtime ad hoc.

The policy should be:

- **request-scoped and immutable**
  - protocol adapters derive it once from the validated northbound request
- **typed, not opaque**
  - preserve only the routing hints that current or near-term logic can use
- **stable across continuation**
  - continuation requests should recover or rebuild the same effective policy,
    rather than creating a new ad-hoc routing context

### Runtime

`CopilotRuntime` should consume the canonical routing policy and derive:

- `excluded_tools`
- external tool registration behavior
- session guidance injection
- fast-fail validation for invalid tool-result continuations

This keeps protocol-specific routes from directly owning runtime routing rules.

### Protocol normalization

Each protocol adapter should own only:

- mapping its northbound fields into canonical messages/tool definitions/results
- preserving any routing-relevant hints
- shaping the northbound response/events back out

Protocol adapters should not each invent their own routing policy.

For v1, "preserving routing-relevant hints" should stay narrow:

- Responses:
  - preserve `tool_choice`
  - preserve `parallel_tool_calls`
  - preserve whether tool surfaces included `function`, `web_search`, and
    `custom`
- Anthropic:
  - no extra hint payload is required yet beyond tool-aware session detection

Do not add generic opaque hint storage without a concrete consumer.

## PR sequence

### PR 1: base tool-routing design slice

**Goal**

- Introduce the canonical tool-routing policy and runtime policy plumbing.

**Likely files**

- `src/copilot_model_provider/core/models.py`
- `src/copilot_model_provider/core/compat.py`
- `src/copilot_model_provider/core/chat.py`
- `src/copilot_model_provider/runtimes/copilot_runtime.py`
- targeted unit tests

**Must include**

- first-class canonical policy representation
- runtime consumption of that policy
- no-op defaults for non-tool flows
- updated compatibility story
- explicit derivation rules for `none` vs `client_passthrough`
- validation for orphaned tool-result continuations
- targeted unit coverage for policy derivation and runtime consumption

**Must not include**

- large protocol-specific output rewrites unless required by the new base
- mixed OpenAI + Anthropic feature expansion in the same PR

### PR 2: OpenAI Responses routing integration

**Goal**

- Make Codex-style Responses routing use the new base policy.

**Likely files**

- `src/copilot_model_provider/core/responses.py`
- `src/copilot_model_provider/api/openai/responses.py`
- `tests/unit_tests/test_responses.py`
- `tests/contract_tests/test_openai_responses.py`
- `tests/integration_tests/test_responses.py`

**Must include**

- preserved routing-relevant tools
- exact Codex replay-style regression coverage
- response-visible tool surface alignment
- reuse of the PR 1 routing policy without redefining it inside Responses code

**Must not include**

- Anthropic-specific behavior changes

### PR 3: Anthropic Messages alignment

**Goal**

- Reuse the same base policy for Anthropic tool-aware sessions.

**Likely files**

- `src/copilot_model_provider/api/anthropic/messages.py`
- `src/copilot_model_provider/api/anthropic/protocol.py`
- Anthropic contract/integration tests

**Must include**

- policy reuse, not a second routing-policy implementation
- Anthropic continuation protection

**Must not include**

- unrelated OpenAI cleanup

### PR 4: optional prompt-bridge refinement

**Goal**

- Evaluate whether a more structured SDK prompt/system-message path is worth the
  added complexity after the base design is stable.

This is explicitly optional and should not block PR 1-3.

## Acceptance criteria

- The exact reproduced Codex request, or a stable replay equivalent, ends as a
  northbound `function_call` / tool pause rather than an assistant-only stop.
- The canonical contract contains one explicit routing-policy surface used by the
  runtime instead of re-deriving behavior from scattered constants.
- The design specifies and PR 1 implements the derivation rules for `none` vs
  `client_passthrough`.
- Invalid tool-result continuations fail fast instead of opening a fresh
  unrelated session.
- OpenAI Responses and Anthropic continuation flows remain green.
- Non-tool text flows keep their current behavior.
- The provider still does not execute user tools locally.
- Compatibility notes in `core/compat.py` no longer misdescribe implemented
  tool-routing behavior.

## Risks

- Over-designing `tool_choice` semantics before the runtime can truly enforce
  them.
- Letting the base PR absorb too much protocol-specific behavior.
- Allowing Responses and Anthropic to diverge into separate routing-policy
  implementations.

## Parallelization readiness

- **Do not fan out yet.** The base policy touches shared hot files and must
  stabilize first.
- After PR 1 lands, Responses and Anthropic can fan out onto separate branches
  and worktrees.

### Conflict hotspots

- `src/copilot_model_provider/core/models.py`
- `src/copilot_model_provider/core/compat.py`
- `src/copilot_model_provider/runtimes/copilot_runtime.py`
- `src/copilot_model_provider/core/responses.py`

### Convergence owner

- `lachimere/codex-tool-routing-design`

## Recommendation

Treat the current branch/worktree as the **base design branch**. Approve the
base architecture first, then re-extract the implementation into the PR sequence
above instead of trying to bless the current mixed diff as one final solution.
