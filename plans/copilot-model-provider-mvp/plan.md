# Plan

> Purpose: a reviewable plan that can be annotated. Do not implement until the plan is approved when plan mode is triggered.

## Objective
- What outcome we want (1–2 sentences):
  - Implement the provider MVP as an OpenAI-compatible gateway over `copilot-sdk`, starting with `GET /v1/models` and `POST /v1/chat/completions`, while preserving the session-oriented runtime design in `docs/design.md`.
  - Deliver the work through **five execution phases implemented as seven mergeable branches** so the foundation chain stays serial, safe fan-out happens only after contracts stabilize, and convergence is explicitly owned.

## Constraints
- Compatibility constraints:
  - MVP northbound surface is limited to `GET /v1/models` and `POST /v1/chat/completions`.
  - Provider-native session APIs are deferred until after MVP, and provider-native response-style APIs are also deferred.
  - Anthropic-compatible facade is out of scope for this plan.
  - MVP tool support is limited to server-approved tools plus MCP; caller-supplied tool schemas are out of scope.
- Performance constraints:
  - streaming behavior must not regress chunk delivery or terminal framing
  - session mapping must not create duplicate or conflicting resumes under normal request flow
- Security/safety constraints:
  - external client auth must stay separate from runtime auth
  - tool and MCP access must be policy-controlled
  - the headless CLI transport remains internal-only
- Timeline/rollout constraints (if any):
  - use staged, mergeable PRs rather than a single MVP branch
  - use one agent per branch and one branch per worktree
  - keep `src/copilot_model_provider/api/openai_chat.py`, `src/copilot_model_provider/runtimes/copilot.py`, `src/copilot_model_provider/core/sessions.py`, and `tests/integration_tests/harness.py` under convergence-owner control once fan-out begins

## Assumptions
Mark each as **Verified** or **Unverified**.
- [x] (Verified) A1: The project will use Python `src/` layout with `github-copilot-sdk` and `structlog`, as already declared in `pyproject.toml`.
- [x] (Verified) A2: Provider-native session APIs and provider-native response-style APIs are not required to ship in MVP.
- [x] (Verified) A3: The first implementation target is the OpenAI-compatible facade, not Anthropic compatibility.
- [x] (Verified) A4: PR 1 does not require a health/readiness endpoint; if one is added, it remains internal-only and outside the MVP compatibility contract.
- [x] (Verified) A5: The first session-mapping backend may be local/file-backed as long as the abstraction keeps room for later shared-storage evolution.
- [x] (Verified) A6: MVP tool support is limited to server-approved tools plus MCP, not caller-supplied tool schemas.
- [x] (Verified) A7: If multiple agents are used, the foundation chain (`PR 1` -> `PR 2` -> `PR 3`) remains serial before any fan-out begins.

## Options Considered (if applicable)
### Option A
- Summary:
  - Execute the approved five-phase / seven-branch sequence from the decomposition and parallel-work design.
- Pros:
  - reviewable increments
  - stable core seams
  - acceptance criteria stay attached to each behavior slice
- Cons:
  - requires more explicit handoff discipline between PRs
- Why chosen / rejected:
  - chosen because it matches the approved Gate 1 design

### Option B
- Summary:
  - Collapse the work into fewer, larger PRs.
- Pros:
  - fewer approvals and merges
- Cons:
  - weaker isolation between contracts, execution, streaming, and tool behavior
  - higher risk of scope creep
- Why chosen / rejected:
  - rejected by the approved design

## Proposed Approach (checklist)
- [x] Step 1: Land the serial foundation chain (`PR 1` -> `PR 2` -> `PR 3`)
  - Current execution status:
    - `PR 1` is complete on branch `feat/pr1-foundation-scaffold` (`76db366`).
    - the model-catalog slice merged into `main` as `7c4d12c`.
    - the non-streaming chat slice merged into `main` as `1df9534`, so the serial foundation chain is complete.
  - Acceptance criteria:
    - the base scaffold, model catalog, and non-streaming chat path are merged in order
    - the shared app/runtime/test-harness contracts are stable enough for fan-out
    - lightweight E2E smoke exists for `/v1/models` and non-streaming chat

- [x] Step 2: Fan out two parallel branches from the `PR 3` merge commit
  - Current execution status:
    - `feat/mvp-streaming-transport` merged into `main` as `e78c081`.
    - `feat/mvp-session-persistence` merged into `main` as `f07c035`.
    - post-merge test/type cleanup for the session branch landed on `main` as `4ceb451`.
  - Acceptance criteria:
    - `feat/mvp-streaming-transport` owns only the streaming transport scope
    - `feat/mvp-session-persistence` owns only the storage/locking scope
    - both branches respect their forbidden-path boundaries
    - both branches contribute owned modules/tests only and leave hot-file wiring to the convergence owner

- [x] Step 3: Converge streaming and session work under a single owner
  - Current execution status:
    - the shared hot files are now integrated locally on `main`
    - `/v1/chat/completions` now supports streaming SSE in addition to non-streaming behavior
    - session persistence/resume and locking are now wired through the convergence path for session-backed routes
    - the streaming setup cleanup issue found during review has been resolved locally
  - Acceptance criteria:
    - one convergence branch integrates the shared hot files
    - combined streaming + resumed-follow-up checks pass
    - lock/ownership behavior is validated explicitly

- [x] Step 4: Land Tool/MCP completion on top of the convergence result
  - Current execution status:
    - server-approved tools are now mounted into SDK sessions through the existing chat/runtime path
    - configured MCP servers are now mounted through app/runtime session creation
    - permission handling is now policy-driven for both server-approved tools and registered MCP servers
    - focused HTTP integration coverage now validates one server-approved tool path and one MCP-backed path
  - Acceptance criteria:
    - `feat/mvp-tools-mcp` is rebased on the convergence branch result
    - at least one server-approved tool path succeeds
    - at least one MCP-backed path succeeds

- [ ] Step 5: Final cleanup and MVP release-gate E2E
  - Acceptance criteria:
    - the final cleanup owner expands and passes the MVP release-gate scenarios from `docs/design.md`
    - no temporary scaffolding is left undocumented
    - the diff remains consistent with the approved design boundaries

## Execution Topology
- Base prerequisite:
  - Foundation chain (`PR 1` -> `PR 2` -> `PR 3`)
- Branch count / phase model:
  - 5 execution phases
  - 7 mergeable branches:
    - `PR 1`
    - `PR 2`
    - `PR 3`
    - `feat/mvp-streaming-transport`
    - `feat/mvp-session-persistence`
    - convergence branch
    - `feat/mvp-tools-mcp` as the final release-gate branch
- Parallel tasks:

| Task | Branch | Worktree | Owns | Must not touch |
|---|---|---|---|---|
| Streaming transport | `feat/mvp-streaming-transport` | `wt-mvp-streaming-transport` | `src/copilot_model_provider/streaming/**`, `tests/integration_tests/test_streaming_chat.py`, `tests/integration_tests/test_streaming_smoke.py` | `src/copilot_model_provider/storage/**`, `src/copilot_model_provider/tools/**`, `src/copilot_model_provider/api/openai_chat.py`, `src/copilot_model_provider/runtimes/copilot.py`, `src/copilot_model_provider/core/sessions.py`, shared configs |
| Session persistence and locking | `feat/mvp-session-persistence` | `wt-mvp-session-persistence` | `src/copilot_model_provider/storage/**`, `tests/integration_tests/test_session_resume.py`, `tests/integration_tests/test_session_locking.py`, `tests/integration_tests/test_resume_smoke.py` | `src/copilot_model_provider/streaming/**`, `src/copilot_model_provider/tools/**`, `src/copilot_model_provider/api/openai_chat.py`, `src/copilot_model_provider/runtimes/copilot.py`, `src/copilot_model_provider/core/sessions.py`, shared configs |
| Tool and MCP completion | `feat/mvp-tools-mcp` | `wt-mvp-tools-mcp` | `src/copilot_model_provider/tools/**`, `src/copilot_model_provider/core/policies.py`, `tests/integration_tests/test_tool_flow.py`, `tests/integration_tests/test_mcp_mount.py` | `src/copilot_model_provider/streaming/**`, `src/copilot_model_provider/storage/**`, `src/copilot_model_provider/api/openai_models.py`, shared configs |

- Convergence owner:
  - one lead integrator owns final edits to `api/openai_chat.py`, `runtimes/copilot.py`, `core/sessions.py`, and `tests/integration_tests/harness.py`
  - fan-out branches supply owned modules/tests; the convergence owner performs the actual hot-file integration
- Final cleanup owner:
  - same lead integrator by default

## Touch Surface
- Key files/modules likely to change:
  - `src/copilot_model_provider/app.py`
  - `src/copilot_model_provider/config.py`
  - `src/copilot_model_provider/api/openai_models.py`
  - `src/copilot_model_provider/api/openai_chat.py`
  - `src/copilot_model_provider/core/models.py`
  - `src/copilot_model_provider/core/catalog.py`
  - `src/copilot_model_provider/core/routing.py`
  - `src/copilot_model_provider/core/sessions.py`
  - `src/copilot_model_provider/core/policies.py`
  - `src/copilot_model_provider/runtimes/base.py`
  - `src/copilot_model_provider/runtimes/copilot.py`
  - `src/copilot_model_provider/streaming/sse.py`
  - `src/copilot_model_provider/streaming/translators.py`
  - `src/copilot_model_provider/tools/registry.py`
  - `src/copilot_model_provider/tools/mcp.py`
  - `src/copilot_model_provider/storage/session_map.py`
  - `src/copilot_model_provider/storage/locks.py`
  - `tests/unit/**`
  - `tests/contract/**`
  - `tests/integration_tests/**`
  - `tests/integration_tests/**`
- Public API / schema impacts:
  - adds OpenAI-compatible `GET /v1/models`
  - adds OpenAI-compatible `POST /v1/chat/completions`
  - adds streaming support on the same chat endpoint
- Data impacts:
  - session mapping state is introduced
  - no end-user data migration is expected in MVP

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
  - targeted contract / integration / e2e tests as introduced per step
- [ ] Before/after behavior proof:
  - before: repo has no provider service or compatibility endpoints
  - current after `PR 1`: app scaffold, runtime/config contracts, internal health endpoint, and E2E harness boot path exist; public provider endpoints still do not
  - current after the model-catalog slice: `GET /v1/models` works through the app without runtime execution dependencies
  - current after the non-streaming chat slice: `POST /v1/chat/completions` executes one stateless Copilot-backed request path and rejects streaming with the shared error envelope
  - after Step 1: `/v1/models` and non-streaming chat work, including running-app smoke paths
  - after Step 3: streaming + session resume work, including focused locking evidence
  - after Step 4: tool/MCP paths work on top of the converged branch
  - after Step 5: MVP release-gate scenarios work end to end
- [ ] Logs/traces/metrics to capture:
  - request/session lifecycle logs
  - streaming event evidence
  - tool/MCP execution evidence where applicable

## Rollback / Recovery (if applicable)
- Rollback plan:
  - revert the active branch/slice only; each PR or convergence branch must remain independently revertible
  - if a fan-out branch violates ownership boundaries, stop and fall back to serial integration instead of force-merging overlapping work
  - if a later slice proves infeasible, stop and update the plan/design rather than folding extra recovery work into the same PR
- Data safety notes:
  - keep session mapping/storage evolution behind clear abstractions
  - do not persist raw secrets in session state
- Feature flag / config toggles:
  - if needed, early endpoint wiring may be guarded behind configuration until the slice is fully validated

## Risks / Non-goals
- Risks:
  - repeated edits to `openai_chat.py`, `core/sessions.py`, and `runtimes/copilot.py` can create conflict hotspots
  - wire-compatibility issues may only surface under streaming/tool/E2E conditions
  - session resume semantics can become incorrect if locking and ownership are underspecified
  - if lightweight E2E is not introduced early, later PRs may inherit already-merged wire-compatibility mistakes
  - if agents cross ownership boundaries during fan-out, convergence will collapse back into a large manual merge
- Explicit non-goals (out of scope):
  - provider-native session APIs
  - provider-native response-style APIs
  - Anthropic-compatible facade
  - caller-supplied tool schemas
  - multi-runtime fallback routing
  - admin UI, billing, or cross-region active-active support

## Review Notes / Annotations
(Place for inline user comments. Agent should incorporate these into the plan before coding.)

## Approval
- [ ] Plan approved by:
- Date:
