# Design Document

> Purpose: document the solution design for review and approval before execution planning.
> Do not proceed to plan/execution until this design is approved.

## Objective
- What problem are we solving (1–2 sentences):
  - We need a staged implementation plan for the provider MVP so the repository can move from design-only state to a working service through a sequence of small, mergeable PRs.
  - The split must preserve trunk safety, keep validation attached to each behavior slice, and honor the architecture in `docs/design.md`.
- Link to research: `plans/copilot-model-provider-mvp/research.md`

## Architecture / Approach
- High-level approach:
  - Use a base-then-integration decomposition:
    1. establish service scaffolding and internal contracts
    2. ship the read-only model catalog surface
    3. add non-streaming chat execution
    4. add streaming + persistent session behavior
    5. add tool / MCP completion and release-gate E2E
- Key components / layers involved:
  - FastAPI application layer
  - OpenAI-compatible API facade
  - canonical core (`catalog`, `routing`, `sessions`, `errors`, request/response models)
  - Copilot runtime adapter
  - streaming translation
  - tool / MCP control plane
  - tests and E2E harness
- Interaction / data flow (describe or diagram):

```text
PR 1: app/config/contracts
  -> creates stable internal seams without user-visible provider behavior

PR 2: model catalog + /v1/models
  client -> FastAPI -> catalog/router -> OpenAI models response

PR 3: non-streaming chat
  client -> /v1/chat/completions -> canonical request -> CopilotRuntimeAdapter -> completion response

Parallel branches after PR 3:
  branch A -> streaming transport modules/tests
  branch B -> session persistence/locking modules/tests

Convergence branch:
  -> integrates branch outputs into hot files
  -> validates streaming + resumed follow-up behavior

Final branch: tools + MCP + release-gate E2E
  client -> tool-capable request -> policy/tool registry/MCP mounts -> runtime -> validated end-to-end
```

## Interface / API / Schema Design
- New or changed interfaces:
  - runtime adapter interface
  - canonical request / event / error models
  - model catalog and router interfaces
  - session mapping interface
- New or changed API endpoints:
  - `PR 1`: no provider API endpoint is required; an internal-only health/readiness endpoint is allowed if it stays outside the MVP compatibility contract
  - `PR 2`: `GET /v1/models`
  - `PR 3`: `POST /v1/chat/completions` (non-streaming path first)
  - convergence branch: streaming chat completion on the same endpoint
  - final branch: no new public endpoint required; completes tool/MCP behavior on existing endpoint
- New or changed data models / schemas:
  - OpenAI-style models response schema
  - canonical internal request / route / event structures
  - session mapping/storage shape
- Contract compatibility notes:
  - MVP prioritizes the OpenAI-compatible surface.
  - Provider-native session APIs are explicitly deferred until after MVP; provider-native response-style APIs are also deferred. This plan resolves the open MVP questions in `docs/design.md` without changing the baseline architecture for later phases.
  - Anthropic-compatible facade is also deferred.
  - MVP tool support is limited to server-approved tools plus MCP; caller-supplied tool schemas are deferred.

## Trade-off Analysis
### Option A (chosen)
- Summary:
  - Execute five implementation phases; under the approved parallel-work design these phases expand into seven mergeable branches.
- Pros:
  - keeps early PRs small and easy to review
  - limits churn in shared core modules
  - allows validation to grow with functionality
  - reduces the chance of one oversized “MVP PR”
- Cons:
  - requires temporary no-op wiring and partial capability states
  - takes more planning discipline than a big-bang branch
- Why chosen:
  - It best matches the repo’s current blank-slate state, the documented architecture, and the requirement for mergeable intermediate states.

### Option B (rejected)
- Summary:
  - Implement the entire MVP in one PR: API layer, runtime adapter, streaming, sessions, tools, and E2E together.
- Pros:
  - fewer review rounds
  - no temporary interfaces
- Cons:
  - too large to review safely
  - high risk of mixed concerns and incomplete verification
  - harder to isolate regressions or feasibility gaps
- Why rejected:
  - It conflicts with the repository workflow and would create a high-risk first implementation change.

### Option C (rejected, if applicable)
- Summary:
  - Split by protocol brand, for example one PR for “OpenAI compatibility,” one PR for “session API,” one PR for “Claude compatibility.”
- Pros:
  - intuitive from an external product perspective
  - may align with marketing or docs boundaries
- Cons:
  - cuts across the actual implementation seams
  - forces repeated edits in the same adapter/core files
  - increases conflict risk before the base runtime exists
- Why rejected:
  - The repo needs internal seams and runtime proof before protocol fan-out.

## Key Design Decisions
- Decision 1:
  - Context:
    - The current repo has no provider implementation yet, only package scaffolding and a design document.
  - Choice:
    - Start with a base PR that introduces app/config/core/runtime interfaces but does not ship the full provider behavior yet.
  - Rationale:
    - This creates stable seams for follow-on PRs and keeps the first merge low risk.

- Decision 2:
  - Context:
    - `docs/design.md` identifies `GET /v1/models` and `POST /v1/chat/completions` as the MVP northbound surface.
  - Choice:
    - Ship `GET /v1/models` before chat execution.
  - Rationale:
    - It proves the catalog/router/public-surface path with much lower complexity than chat, streaming, or tools.

- Decision 3:
  - Context:
    - Stateful session behavior is important, but provider-native session APIs remain an open question in the design baseline.
  - Choice:
    - Defer provider-native session APIs until after MVP, defer provider-native response-style APIs as well, and implement persistent session mapping internally first.
  - Rationale:
    - This keeps the first public API surface narrow while still preserving the session-oriented architecture.

- Decision 4:
  - Context:
    - The design requires real-client-style validation for streaming, tool calls, routing, and session reuse.
  - Choice:
    - Attach unit/integration/contract tests to each PR, introduce a thin E2E harness no later than the read-only metadata slice, and expand E2E scenarios incrementally through the later PRs.
  - Rationale:
    - Tests stay close to the behavior they verify, while earlier E2E coverage reduces the risk of discovering wire-compatibility problems only after multiple PRs have landed.

- Decision 5:
  - Context:
    - The earlier draft left PR 1 health/readiness behavior and the session-mapping storage starting point as open assumptions.
  - Choice:
    - PR 1 does not require a health/readiness endpoint, though one may be added if it is internal-only; the session-persistence branch starts with a local/file-backed session-mapping abstraction that preserves room for later shared-storage evolution.
  - Rationale:
    - This removes ambiguity from the PR boundaries without expanding the MVP surface or forcing a distributed storage commitment too early.

- Decision 6:
  - Context:
    - The earlier draft still left the MVP tool surface slightly ambiguous.
  - Choice:
    - Limit MVP tool support to server-approved tools plus MCP, and defer caller-supplied tool schemas.
  - Rationale:
    - This keeps the first release narrower, safer, and easier to validate while still exercising the core tool/mounting path.

## Impact Assessment
- Affected modules / services:
  - `src/copilot_model_provider/app.py`
  - `src/copilot_model_provider/config.py`
  - `src/copilot_model_provider/api/**`
  - `src/copilot_model_provider/core/**`
  - `src/copilot_model_provider/runtimes/**`
  - `src/copilot_model_provider/streaming/**`
  - `src/copilot_model_provider/tools/**`
  - `src/copilot_model_provider/storage/**`
  - `tests/**`
- Public API / schema compatibility:
  - adds new OpenAI-compatible HTTP surfaces incrementally
  - avoids exposing provider-native APIs before they are intentionally designed
- Data migration needs:
  - none expected for MVP
  - session mapping storage and lock strategy must support forward evolution
- Performance implications:
  - early PRs have negligible runtime impact
  - streaming/session/tool slices will determine latency and concurrency behavior
- Security considerations:
  - external auth vs runtime auth must remain separate
  - tool permissions and MCP mounting must be policy-controlled
  - headless CLI connectivity remains internal-only

## PR Sequence

## Feature summary
- one-sentence summary:
  - Build the provider MVP through five execution phases implemented as seven mergeable branches that progressively add the API surface, runtime execution path, and high-risk behavior.
- main constraints:
  - every intermediate state must be mergeable
  - provider-native session APIs are out of MVP
  - provider-native response-style APIs are out of MVP
  - caller-supplied tool schemas are out of MVP
  - tests must ship with their implementation slices
  - `copilot-sdk` remains the primary runtime adapter
- why this split was chosen:
  - it follows the repo’s desired base -> implementation -> integration progression and reduces churn in the same core files.

## PR 1: Base service scaffold and internal contracts
- Status:
  - Completed on branch `feat/pr1-foundation-scaffold` and committed as `76db366`.
- Goal:
  - Introduce the FastAPI app skeleton, configuration loading, core data types/errors, runtime adapter interface, and dependency wiring with no real model execution yet.
- Likely directories/files:
  - `src/copilot_model_provider/app.py`
  - `src/copilot_model_provider/config.py`
  - `src/copilot_model_provider/core/models.py`
  - `src/copilot_model_provider/core/errors.py`
  - `src/copilot_model_provider/runtimes/base.py`
  - `src/copilot_model_provider/__init__.py`
  - `tests/unit_tests/test_config.py`
  - `tests/unit_tests/test_app_boot.py`
  - `tests/unit_tests/test_cli.py`
  - `tests/unit_tests/test_errors.py`
  - `tests/unit_tests/test_runtime_base.py`
  - `tests/integration_tests/harness.py`
- Dependencies:
  - none
- Allowed changes:
  - app factory
  - dependency injection scaffolding
  - settings/config objects
  - canonical type definitions and error contracts
  - optional internal-only health/readiness endpoint
  - E2E harness scaffolding without real MVP scenario claims
- Prohibited changes:
  - real Copilot SDK session execution
  - public `/v1/models` or `/v1/chat/completions` behavior
  - streaming translation
  - tool/MCP execution logic
- Acceptance criteria (concrete, verifiable conditions that must be true before this PR can be proposed):
  - the package exposes a runnable app skeleton
  - core request/route/error abstractions exist and are importable
  - app startup and config tests pass
  - any health/readiness endpoint remains internal-only and is not treated as MVP surface
  - the E2E harness can boot the app under test, even though no provider scenario passes yet
- Validation commands:
  - `uv run ruff check .`
  - `uv run pyright`
  - `uv run ty check .`
  - `uv run pytest -q`
- Mergeability notes:
  - safe to merge first because it establishes structure only and does not promise full provider behavior.

## PR 2: Model catalog and `GET /v1/models`
- Status:
  - Implemented on branch `feat/model-catalog-surface`; pending review and merge.
- Goal:
  - Implement the service-owned model catalog and router metadata path, then expose `GET /v1/models` through the OpenAI-compatible facade.
- Likely directories/files:
  - `src/copilot_model_provider/api/openai_models.py`
  - `src/copilot_model_provider/core/catalog.py`
  - `src/copilot_model_provider/core/routing.py`
  - `src/copilot_model_provider/core/models.py`
  - `tests/unit_tests/test_catalog.py`
  - `tests/contract_tests/test_openai_models.py`
  - `tests/integration_tests/test_models_smoke.py`
- Dependencies:
  - PR 1
- Allowed changes:
  - alias schema
  - catalog loading/config
  - router resolution for read-only metadata
  - `/v1/models` contract tests
- Prohibited changes:
  - chat execution
  - session mutation
  - streaming/tool/MCP behavior
- Acceptance criteria:
  - `/v1/models` returns stable alias entries from the service-owned catalog
  - router/catalog rules are unit-tested
  - endpoint behavior is covered by contract tests
  - a lightweight E2E smoke path validates `/v1/models` through the running app
  - no runtime execution dependency is required to serve model listing
- Validation commands:
  - `uv run ruff check .`
  - `uv run pyright`
  - `uv run ty check .`
  - `uv run pytest -q`
- Mergeability notes:
  - mergeable independently because it adds a read-only public capability and validates the first compatibility path.

## PR 3: Non-streaming chat execution via Copilot runtime
- Goal:
  - Add the Copilot runtime adapter and support non-streaming `POST /v1/chat/completions` for the basic single-request path.
- Likely directories/files:
  - `src/copilot_model_provider/api/openai_chat.py`
  - `src/copilot_model_provider/runtimes/copilot.py`
  - `src/copilot_model_provider/core/sessions.py`
  - `src/copilot_model_provider/core/errors.py`
  - `tests/integration_tests/test_copilot_runtime_chat.py`
  - `tests/contract/test_openai_chat_non_streaming.py`
  - `tests/integration_tests/test_non_streaming_chat.py`
- Dependencies:
  - PR 2
- Allowed changes:
  - `CopilotRuntimeAdapter`
  - request normalization into canonical model
  - ephemeral or internally managed session create/send path
  - non-streaming response translation
  - structured logging with `structlog` for request/session lifecycle events
- Prohibited changes:
  - SSE streaming
  - persistent conversation resume behavior across requests
  - tool/MCP execution completion
- Acceptance criteria:
  - a basic non-streaming chat completion succeeds through the runtime adapter
  - errors are normalized into the public API shape
  - adapter integration tests cover create/send behavior
  - endpoint contract tests verify non-streaming response compatibility
  - a lightweight end-to-end smoke test proves the non-streaming wire path through the running app
- Validation commands:
  - `uv run ruff check .`
  - `uv run pyright`
  - `uv run ty check .`
  - targeted adapter integration tests
  - targeted HTTP contract tests for non-streaming chat
- Mergeability notes:
  - mergeable because it unlocks the first useful end-to-end behavior without yet taking on streaming/tool complexity.

## Parallel branch A: Streaming transport
- Goal:
  - Implement the streaming transport modules and streaming-focused tests without directly editing the shared hot files.
- Likely directories/files:
  - `src/copilot_model_provider/streaming/sse.py`
  - `src/copilot_model_provider/streaming/translators.py`
  - `tests/integration_tests/test_streaming_chat.py`
  - `tests/integration_tests/test_streaming_smoke.py`
- Dependencies:
  - PR 3
- Allowed changes:
  - SSE encoding
  - canonical event translation helpers
  - streaming-specific tests in owned paths
- Prohibited changes:
  - `src/copilot_model_provider/api/openai_chat.py`
  - `src/copilot_model_provider/runtimes/copilot.py`
  - `src/copilot_model_provider/core/sessions.py`
  - provider-native session endpoints
  - provider-native response-style APIs
  - tool/MCP behavior
- Acceptance criteria:
  - streaming-specific modules and tests exist in owned paths
  - no forbidden-path edits are introduced
  - streaming-focused tests are ready for the convergence owner to wire into the hot files
- Validation commands:
  - `uv run ruff check .`
  - `uv run pyright`
  - `uv run ty check .`
  - targeted streaming tests in owned paths
- Mergeability notes:
  - mergeable after PR 3 because it stays inside owned paths and defers hot-file integration to convergence.

## Parallel branch B: Session persistence and locking
- Goal:
  - Implement the persistence/locking modules and session-focused tests without directly editing the shared hot files.
- Likely directories/files:
  - `src/copilot_model_provider/storage/session_map.py`
  - `src/copilot_model_provider/storage/locks.py`
  - `tests/integration_tests/test_session_resume.py`
  - `tests/integration_tests/test_session_locking.py`
  - `tests/integration_tests/test_resume_smoke.py`
- Dependencies:
  - PR 3
- Allowed changes:
  - persistent session ID mapping using a local/file-backed abstraction that can evolve later
  - locking/session ownership logic in owned paths
  - session-focused tests in owned paths
- Prohibited changes:
  - `src/copilot_model_provider/api/openai_chat.py`
  - `src/copilot_model_provider/runtimes/copilot.py`
  - `src/copilot_model_provider/core/sessions.py`
  - provider-native session endpoints
  - provider-native response-style APIs
  - tool/MCP behavior
- Acceptance criteria:
  - persistence/locking modules and tests exist in owned paths
  - no forbidden-path edits are introduced
  - focused tests are ready for the convergence owner to wire into the hot files
- Validation commands:
  - `uv run ruff check .`
  - `uv run pyright`
  - `uv run ty check .`
  - targeted session/locking tests in owned paths
- Mergeability notes:
  - mergeable after PR 3 because it stays inside owned paths and defers hot-file integration to convergence.

## Convergence PR: Streaming and session integration
- Goal:
  - Integrate the streaming and session fan-out branches into the shared hot files and validate the combined resumed-follow-up behavior.
- Likely directories/files:
  - `src/copilot_model_provider/api/openai_chat.py`
  - `src/copilot_model_provider/runtimes/copilot.py`
  - `src/copilot_model_provider/core/sessions.py`
  - `tests/integration_tests/harness.py`
  - `tests/integration_tests/test_streaming_and_resume.py`
- Dependencies:
  - Parallel branch A
  - Parallel branch B
- Allowed changes:
  - integrate streaming helpers into the chat/runtime path
  - integrate session persistence and locking into the chat/runtime path
  - wire fan-out branch tests into combined behavior
- Prohibited changes:
  - provider-native session endpoints
  - provider-native response-style APIs
  - tool/MCP completion
  - unrelated deployment-topology expansion
- Acceptance criteria:
  - streaming chat sends incremental chunks with correct terminal behavior
  - repeated turns can resume the same underlying Copilot session
  - restart/resume behavior is covered at least by focused integration tests
  - session ownership/locking rules are explicit in code and tests
  - focused tests cover at least one lock/ownership path so session-resume correctness is not inferred indirectly from happy-path behavior
  - an E2E scenario covers both streaming framing and a resumed follow-up turn
- Validation commands:
  - `uv run ruff check .`
  - `uv run pyright`
  - `uv run ty check .`
  - targeted integration tests for streaming, session resume, and locking/ownership behavior
  - targeted E2E streaming/resume smoke
- Mergeability notes:
  - mergeable because it is the explicitly owned convergence point for the hot files before Tool/MCP work begins.

## Final PR: Tool / MCP completion and MVP release gate
- Goal:
  - Complete the MVP’s tool and MCP story on top of the existing chat surface, remove temporary limitations that were only acceptable for earlier slices, and add the minimum release-gate E2E coverage.
- Likely directories/files:
  - `src/copilot_model_provider/tools/registry.py`
  - `src/copilot_model_provider/tools/mcp.py`
  - `src/copilot_model_provider/core/policies.py`
  - `src/copilot_model_provider/runtimes/copilot.py`
  - `tests/integration_tests/test_tool_flow.py`
  - `tests/integration_tests/test_mcp_mount.py`
  - `tests/integration_tests/**`
- Dependencies:
  - Convergence PR
- Allowed changes:
  - built-in tool policy
  - server-approved tool registry where needed for MVP
  - MCP mounting
  - final release-gate E2E expansion for models/chat/streaming/tool/routing/session
  - cleanup of temporary no-op behavior from earlier PRs
- Prohibited changes:
  - Anthropic-compatible facade
  - provider-native session or response-style API families
  - caller-supplied tool schema support
  - unrelated admin/billing/multi-runtime work
- Acceptance criteria:
  - at least one tool-calling path succeeds through the existing chat endpoint
  - at least one MCP-backed tool path is validated
  - MVP release-gate scenarios from `docs/design.md` are covered at the agreed minimum depth
  - any temporary scaffolding from earlier PRs is either removed or documented as intentional
- Validation commands:
  - `uv run ruff check .`
  - `uv run pyright`
  - `uv run ty check .`
  - targeted integration tests for tool/MCP behavior
  - MVP E2E scenarios covering `/v1/models`, non-streaming chat, streaming, session resume, and routing/tool behavior
- Mergeability notes:
  - this is the final MVP-enabling PR; after it lands, the repo should satisfy the documented minimum release gate.

## Parallel execution design

### Base prerequisite
- Name:
  - Foundation chain (`PR 1` -> `PR 2` -> `PR 3`)
- Purpose:
  - stabilize the app skeleton, catalog/router contract, first non-streaming chat path, and the shared test harness before any multi-agent fan-out
- Why serial:
  - these slices still define or heavily touch the same shared seams:
    - `src/copilot_model_provider/app.py`
    - `src/copilot_model_provider/core/models.py`
    - `src/copilot_model_provider/api/openai_chat.py`
    - `src/copilot_model_provider/runtimes/copilot.py`
    - `src/copilot_model_provider/core/sessions.py`
    - `tests/integration_tests/harness.py`
  - parallelizing before those contracts settle would create constant rebasing and ambiguous ownership
- Must stabilize first:
  - app/config boot path
  - canonical request/response contracts
  - catalog/router metadata shape
  - first non-streaming runtime execution path

### Parallel task table

| Task name | Branch name | Worktree name | Owns | Must not touch | Depends on | Validation |
|---|---|---|---|---|---|---|
| Streaming transport | `feat/mvp-streaming-transport` | `wt-mvp-streaming-transport` | `src/copilot_model_provider/streaming/**`, `tests/integration_tests/test_streaming_chat.py`, `tests/integration_tests/test_streaming_smoke.py` | `src/copilot_model_provider/storage/**`, `src/copilot_model_provider/tools/**`, `src/copilot_model_provider/api/openai_chat.py`, `src/copilot_model_provider/runtimes/copilot.py`, `src/copilot_model_provider/core/sessions.py`, shared configs/lockfiles | Foundation chain merged | `uv run ruff check .`, `uv run pyright`, `uv run ty check .`, targeted streaming tests |
| Session persistence and locking | `feat/mvp-session-persistence` | `wt-mvp-session-persistence` | `src/copilot_model_provider/storage/**`, `tests/integration_tests/test_session_resume.py`, `tests/integration_tests/test_session_locking.py`, `tests/integration_tests/test_resume_smoke.py` | `src/copilot_model_provider/streaming/**`, `src/copilot_model_provider/tools/**`, `src/copilot_model_provider/api/openai_chat.py`, `src/copilot_model_provider/runtimes/copilot.py`, `src/copilot_model_provider/core/sessions.py`, shared configs/lockfiles | Foundation chain merged | `uv run ruff check .`, `uv run pyright`, `uv run ty check .`, targeted session/locking tests |
| Tool and MCP completion | `feat/mvp-tools-mcp` | `wt-mvp-tools-mcp` | `src/copilot_model_provider/tools/**`, `src/copilot_model_provider/core/policies.py`, `tests/integration_tests/test_tool_flow.py`, `tests/integration_tests/test_mcp_mount.py` | `src/copilot_model_provider/streaming/**`, `src/copilot_model_provider/storage/**`, `src/copilot_model_provider/api/openai_models.py`, shared configs/lockfiles | Convergence PR merged | `uv run ruff check .`, `uv run pyright`, `uv run ty check .`, targeted tool/MCP tests |

Notes:
- One agent = one branch = one worktree.
- Fan-out branches may create owned modules, helpers, and tests only in their declared paths; they do not directly modify the hot files.
- The convergence owner, not the fan-out branches, owns final edits to:
  - `src/copilot_model_provider/api/openai_chat.py`
  - `src/copilot_model_provider/runtimes/copilot.py`
  - `src/copilot_model_provider/core/sessions.py`
  - `tests/integration_tests/harness.py`
- If those ownership boundaries cannot be respected in practice, the work should fall back to serial execution.

### Merge strategy
- Rebase order:
  1. Merge the foundation chain serially: `PR 1` -> `PR 2` -> `PR 3`
  2. Fan out `Streaming transport` and `Session persistence and locking` from the `PR 3` merge commit
  3. Merge the two fan-out branches after they pass owned-path validation
  4. Convergence owner creates and merges a dedicated convergence branch (for example `feat/mvp-streaming-session-converge`) to integrate the hot files and run the combined streaming/resume checks
  5. Rebase `Tool and MCP completion` onto the convergence merge result and use it as the final release-gate PR
- Conflict hotspots:
  - `src/copilot_model_provider/api/openai_chat.py`
  - `src/copilot_model_provider/runtimes/copilot.py`
  - `src/copilot_model_provider/core/sessions.py`
  - `tests/integration_tests/harness.py`
  - shared configs / lockfiles such as `pyproject.toml`, `uv.lock`, `pyrightconfig.json`, `ruff.toml`, `ty.toml`
- Convergence owner:
  - lead integrator for the feature branch stack; should be a single agent/person, not shared ownership
- Final cleanup owner:
  - same lead integrator by default, unless the team explicitly reassigns release-gate E2E and merge reconciliation

## Risks
- contract churn:
  - `core/models.py`, `core/sessions.py`, and `runtimes/copilot.py` are likely conflict hotspots if responsibilities are not tightly staged.
- migration hazards:
  - introducing persistent session mapping before ownership/locking semantics are explicit could create hard-to-debug resume bugs.
- conflict hotspots:
  - `api/openai_chat.py`, the runtime adapter, and test harness files will be touched repeatedly across the middle PRs.
- rollback considerations:
  - each PR should be independently revertible; do not merge provider-native session APIs, provider-native response-style APIs, or secondary protocol facades into this sequence.

## Open Questions
- Q1:
  - Do we want to add the optional internal-only health/readiness endpoint in PR 1, or skip it entirely?
- Q2:
  - Is local/file-backed session mapping sufficient for the first MVP cut, or do we already know we need a shared backing store abstraction immediately?

## Review Notes / Annotations
(Place for reviewer comments. Agent must incorporate feedback and re-submit for approval before proceeding to plan.)

## Approval
- [x] Design approved by: user
- Date: 2026-03-25
