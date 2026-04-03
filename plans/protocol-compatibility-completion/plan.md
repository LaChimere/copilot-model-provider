# Plan

> Purpose: a reviewable plan that can be annotated. Do not implement until the plan is approved when plan mode is triggered.

## Objective
- What outcome we want (1–2 sentences):
  - Deliver protocol-compatibility completion as a sequence of small, mergeable PRs that improve real Codex and Claude Code interoperability on the existing dual-protocol surface.
  - Preserve the thin, stateless provider boundary while making request handling, streaming behavior, and error semantics more explicit and predictable.

## Constraints
- Compatibility constraints:
  - Keep the existing endpoint set: `/openai/v1/models`, `/openai/v1/chat/completions`, `/openai/v1/responses`, `/anthropic/v1/models`, `/anthropic/v1/messages`, `/anthropic/v1/messages/count_tokens`.
  - `/openai/v1/chat/completions` remains a first-class endpoint even though Codex primarily uses `/openai/v1/responses`.
  - Preserve model-id transparency as **addressability/selection** by model id, not cross-family feature parity.
- Performance constraints:
  - Avoid repeated runtime model discovery or unnecessary streaming overhead.
  - Keep additional compatibility logic lightweight and localized.
- Security/safety constraints:
  - Do not add provider-owned session persistence.
  - Do not add server-side tools, MCP execution, or hidden capability expansion.
  - Keep auth/header handling explicit and deterministic.
- Timeline/rollout constraints (if any):
  - Deliver as reviewable stacked PRs with trunk-safe intermediate states.
  - Re-verify fast-moving upstream docs immediately before implementation where the design depends on current Codex or Claude Code wording.

## Assumptions
Mark each as **Verified** or **Unverified**.
- [ ] (Verified) A1: The current codebase already exposes the required OpenAI and Anthropic endpoint families and has contract/integration/live tests that can anchor compatibility work.
- [ ] (Verified) A2: Anthropic non-streaming errors currently use the shared OpenAI-style error envelope and need a protocol-specific shape.
- [ ] (Verified) A3: The OpenAI Responses request model does not currently include `truncation`.
- [ ] (Verified) A4: The Anthropic request/response normalization path is text-only and explicitly discards non-text content blocks today.
- [ ] (Unverified) A5: The runtime can surface enough structure for `thinking` / `redacted_thinking` passthrough to be feasible without violating the product boundary.
- [ ] (Unverified) A6: The exact Codex and Claude Code external requirements cited in research still hold unchanged at implementation time.

## Options Considered (if applicable)
### Option A
- Summary:
  - Base PR plus protocol-specific implementation PRs plus cleanup/docs.
- Pros:
  - Keeps shared contract churn isolated.
  - Lets OpenAI and Anthropic work progress in smaller review units.
  - Preserves mergeable intermediate states.
- Cons:
  - Requires discipline to avoid leaking implementation into the base PR.
- Why chosen / rejected:
  - Chosen because the work touches shared models/helpers plus two protocol surfaces with different risk profiles.

### Option B
- Summary:
  - Split only by client family: one OpenAI PR, one Anthropic PR, one docs PR.
- Pros:
  - Simpler PR sequence.
- Cons:
  - Shared contract and helper changes would be repeated or mixed into larger PRs.
  - Anthropic slice would still be too broad because it combines error/header fixes with thinking/usage behavior changes.
- Why chosen / rejected:
  - Rejected because it yields larger, less reviewable PRs and weaker merge boundaries.

## Proposed Approach (checklist)
- [ ] PR 1: Add shared compatibility scaffolding and test hooks.
  - Acceptance criteria:
    - Shared compatibility helpers/classification utilities exist without changing public protocol behavior.
    - Shared test fixtures or assertion helpers are ready for later PRs.
- [ ] PR 2: Complete the OpenAI compatibility slice.
  - Acceptance criteria:
    - `/openai/v1/chat/completions` and `/openai/v1/responses` have explicit field classification.
    - `truncation` is accepted on Responses requests as designed.
    - `chat/completions` and `responses` contract coverage explicitly covers the approved field/error/streaming behavior where applicable.
    - OpenAI Responses `response.completed` usage is populated according to the approved rule when runtime data is available.
- [ ] PR 3: Complete Anthropic correctness fixes.
  - Acceptance criteria:
    - Non-streaming Anthropic errors use Anthropic-shaped envelopes.
    - `anthropic-version`, `anthropic-beta`, and `X-Claude-Code-Session-Id` are accepted and surfaced per the approved behavior.
- [ ] PR 4: Complete Anthropic behavior upgrades.
  - Acceptance criteria:
    - `thinking` is accepted on requests.
    - **Checkpoint:** verify with runtime evidence whether `thinking` / `redacted_thinking` arrive in a structured form before implementing passthrough.
    - Thinking passthrough is implemented only if that runtime evidence supports it; otherwise work stops and `design.md` / `plan.md` are updated before proceeding.
    - Streaming `usage` behavior is explicitly implemented and tested.
- [ ] Cleanup PR: Finalize support matrix, docs, and end-to-end validation.
  - Acceptance criteria:
    - Public/internal support matrix matches the implemented field classifications.
    - Relevant tests and behavior checks demonstrate the final contract.

## PR Sequence
## PR 1: Compatibility scaffolding and contract harness
Goal:
- Introduce shared compatibility classification helpers, protocol-specific error abstraction seams, and test scaffolding needed by later PRs without intentionally changing client-visible behavior.
Acceptance criteria:
- Shared helpers exist for classifying supported / accept-ignore / reject behavior.
- Shared error abstraction can represent OpenAI and Anthropic envelopes without changing route behavior yet.
- Test utilities are added or updated so later PRs can assert field/header behavior cleanly.
Likely paths:
- `src/copilot_model_provider/core/`
- `src/copilot_model_provider/api/shared.py`
- `tests/contract_tests/`
- `tests/integration_tests/` (fixtures/helpers only)
Allowed:
- Shared helper additions
- Internal refactors that preserve current behavior
- Test harness improvements
Prohibited:
- No intentional protocol behavior changes yet
- No docs/support-matrix promises that are not implemented
Validation:
- `uv run ruff check .`
- `uv run pyright`
- `uv run ty check .`
- `uv run pytest -q tests/contract_tests`
Depends on:
- None
Mergeability notes:
- Must be trunk-safe and reviewable as a no-op foundation PR.

## PR 2: OpenAI compatibility completion
Goal:
- Make the OpenAI surface explicit and predictable for both chat/completions and responses, including accepting `truncation` on Responses requests and tightening contract coverage.
Acceptance criteria:
- `/openai/v1/chat/completions` remains first-class and covered by explicit compatibility rules.
- `chat/completions` contract tests cover the approved field classification, error handling, and streaming behavior, including a dedicated chat streaming contract case added in this PR.
- `/openai/v1/responses` accepts `truncation` as accept-ignore.
- OpenAI Responses `response.completed` usage is populated according to the approved rule when runtime data is available.
- Contract tests document and enforce the supported/ignored OpenAI field set.
Likely paths:
- `src/copilot_model_provider/api/openai/`
- `src/copilot_model_provider/core/models.py`
- `src/copilot_model_provider/core/responses.py`
- `tests/contract_tests/test_openai_*`
- `tests/contract_tests/test_openai_chat_streaming.py`
- `tests/integration_tests/test_responses.py`
Allowed:
- OpenAI request-model changes
- OpenAI route/translator changes
- OpenAI contract/integration tests
Prohibited:
- No Anthropic behavior changes
- No server-side tool execution or persistence work
Validation:
- `uv run ruff check .`
- `uv run pyright`
- `uv run ty check .`
- `uv run pytest -q tests/contract_tests/test_openai_chat_non_streaming.py tests/contract_tests/test_openai_chat_streaming.py tests/contract_tests/test_openai_responses.py tests/contract_tests/test_openai_models.py`
Depends on:
- PR 1
Mergeability notes:
- Mergeable on its own once OpenAI behavior and tests are internally consistent.

## PR 3: Anthropic correctness slice (errors + headers)
Goal:
- Fix Anthropic protocol correctness issues that are independent of thinking passthrough: non-streaming error envelopes and gateway-header handling.
Acceptance criteria:
- Anthropic non-streaming errors use Anthropic-shaped error responses.
- `anthropic-version`, `anthropic-beta`, and `X-Claude-Code-Session-Id` are accepted and surfaced as designed.
- Anthropic contract tests lock down the corrected error/header behavior.
Likely paths:
- `src/copilot_model_provider/api/anthropic/`
- `src/copilot_model_provider/api/shared.py`
- `src/copilot_model_provider/core/errors.py`
- `tests/contract_tests/test_anthropic_messages.py`
Allowed:
- Anthropic route/error-shape changes
- Header extraction and logging plumbing
- Anthropic contract tests
Prohibited:
- No thinking passthrough yet
- No usage estimation changes yet
- No unrelated OpenAI changes
Validation:
- `uv run ruff check .`
- `uv run pyright`
- `uv run ty check .`
- `uv run pytest -q tests/contract_tests/test_anthropic_messages.py`
Depends on:
- PR 1
Mergeability notes:
- Mergeable independently of thinking support and reduces the biggest Anthropic correctness risk first.

## PR 4: Anthropic behavior slice (thinking + streaming usage)
Goal:
- Implement the approved Anthropic behavior upgrades that remain feasible on the current runtime path: accept `thinking` for compatibility and add streaming `usage` handling.
Acceptance criteria:
- `thinking` is accepted in the Anthropic request model.
- Runtime checkpoint evidence is recorded in `design.md`, and the current runtime path is documented as not surfacing structured `thinking` / `redacted_thinking` blocks for passthrough.
- `thinking` remains accept-ignore on the current runtime path rather than being silently rejected.
- Streaming `usage` behavior is implemented according to the approved rule (exact counts when available, otherwise explicit estimation).
Likely paths:
- `src/copilot_model_provider/api/anthropic/`
- `src/copilot_model_provider/core/models.py`
- `src/copilot_model_provider/streaming/`
- `tests/contract_tests/test_anthropic_messages.py`
- `tests/integration_tests/test_chat.py`
- `tests/live_tests/` (if narrow live proof is needed)
Allowed:
- Anthropic request/response model changes
- Streaming translator changes
- Anthropic contract/integration/live validation tied to thinking/usage behavior
Prohibited:
- No server-side tool execution
- No broad multimodal/tool parity work
- No docs-only cleanup mixed into this PR
Validation:
- `uv run ruff check .`
- `uv run pyright`
- `uv run ty check .`
- `uv run pytest -q tests/contract_tests/test_anthropic_messages.py tests/integration_tests/test_chat.py`
Depends on:
- PR 3
Mergeability notes:
- This is the highest-risk behavior PR and should stay isolated for review.

## Cleanup PR: Support matrix and verification closeout
Goal:
- Align docs and final regression coverage with the implemented compatibility contract after the behavior PRs land.
Acceptance criteria:
- Support matrix reflects the shipped supported / accept-ignore / reject decisions.
- Docs and tests no longer describe stale pre-implementation behavior.
- Final verification evidence covers the minimum L2 bar for the overall feature.
Likely paths:
- `README.md`
- `docs/design.md`
- `plans/protocol-compatibility-completion/`
- `tests/contract_tests/`
- `tests/integration_tests/`
- `tests/live_tests/`
Allowed:
- Documentation refresh tied to implemented behavior
- Final test additions or expectation updates that belong to the shipped contract
Prohibited:
- No new protocol behavior
- No unrelated documentation cleanup
Validation:
- `uv run ruff check .`
- `uv run pyright`
- `uv run ty check .`
- `uv run pytest -q`
Depends on:
- PR 2
- PR 4
Mergeability notes:
- Must be last so docs/support matrix describe shipped behavior rather than planned behavior.

## Parallelization readiness
Must stay serial:
- PR 1 must land first.
- PR 4 depends on PR 3 because both touch Anthropic hot paths and the higher-risk thinking work should build on the corrected Anthropic base.
- Cleanup PR stays last.
Can fan out after base:
- PR 2 (OpenAI slice) and PR 3 (Anthropic correctness slice) can proceed in parallel after PR 1 if path ownership is kept explicit.
- This is readiness guidance only; use `plan-parallel-work` if explicit agent/branch/worktree ownership is needed.

## Touch Surface
- Key files/modules likely to change:
  - `src/copilot_model_provider/api/openai/`
  - `src/copilot_model_provider/api/anthropic/`
  - `src/copilot_model_provider/api/shared.py`
  - `src/copilot_model_provider/core/models.py`
  - `src/copilot_model_provider/core/errors.py`
  - `src/copilot_model_provider/core/responses.py`
  - `src/copilot_model_provider/streaming/`
  - `tests/contract_tests/`
  - `tests/integration_tests/`
  - `tests/live_tests/`
- Public API / schema impacts:
  - OpenAI Responses request schema gains `truncation`.
  - Anthropic error envelopes become protocol-correct.
  - Anthropic request/stream behavior may expand for `thinking` and `usage`.
- Data impacts:
  - None.

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
  - `uv run pytest -q`
- [ ] Before/after behavior proof:
  - Anthropic non-streaming error envelope before/after
  - OpenAI Responses request with `truncation` before/after
  - Anthropic header acceptance before/after
  - Anthropic thinking/usage streaming proof if implemented
- [ ] Logs/traces/metrics to capture:
  - Narrow request/response examples or test assertions showing the corrected protocol shapes

## Rollback / Recovery (if applicable)
- Rollback plan:
  - Revert the latest PR if a protocol behavior change breaks client compatibility.
  - Stop and update `design.md` / `plan.md` if runtime evidence invalidates the approved approach for thinking passthrough or usage handling.
- Data safety notes:
  - No data migration or persistent state rollback is needed.
- Feature flag / config toggles:
  - None currently planned; rollback is by revert rather than long-lived compatibility flags.

## Risks / Non-goals
- Risks:
  - Anthropic hot files (`protocol.py`, `messages.py`, streaming translators) are conflict hotspots.
  - Runtime evidence for `thinking` passthrough may not match current assumptions.
  - Upstream Codex / Claude Code docs may drift before execution.
  - Silent accept-ignore decisions can still mislead clients if classification is too permissive.
- Explicit non-goals (out of scope):
  - Full OpenAI or Anthropic API parity
  - Server-side tool execution or MCP execution
  - Provider-owned session persistence
  - Broad multimodal parity beyond what is required for client-critical compatibility and supported by the existing boundary

## Review Notes / Annotations
(Place for inline user comments. Agent should incorporate these into the plan before coding.)

## Approval
- [x] Plan approved by: User
- Date: 2026-04-03
