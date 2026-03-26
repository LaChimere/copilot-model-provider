# Research Log

> Purpose: capture facts, evidence, and unknowns before planning/implementation.
> This is the review surface for understanding and diagnosis.

## Task
- Summary: Decompose the `copilot-model-provider` MVP into a sequence of small, mergeable PRs and define whether any part of that sequence can be parallelized safely across multiple agents.
- Links (issue/PR/spec):
  - `docs/design.md`
  - `AGENTS.md`
  - `.agents/templates/RESEARCH.md`
  - `.agents/templates/DESIGN.md`

## Current Behavior
- Observed behavior:
  - The repository now contains the foundation scaffold, a service-owned model catalog, routing metadata, an OpenAI-compatible `GET /v1/models` endpoint, and a `POST /v1/chat/completions` path that supports both non-streaming and streaming SSE behavior through the Copilot runtime adapter.
  - The Step 2 fan-out slices are merged, and the Step 3 convergence work is now implemented on `main`: the shared hot files wire in streaming transport, session persistence/resume, and locking behavior.
  - Step 4 is now also implemented on `main`: server-approved tool execution, MCP mounting, and policy-controlled permission handling are wired into runtime session creation and validated through focused integration coverage.
  - Step 5 is now implemented on `main`: release-gate integration coverage validates model alias listing, routed `runtime_model_id` selection, sessional alias enforcement, session persistence, and clean `model_not_found` responses for unknown aliases.
  - The documented auth baseline for the next packaging slice is now caller-supplied GitHub bearer-token passthrough (direct token or OAuth-issued token), not a service-owned identity layer.
  - The repository still has no `Dockerfile`, `.dockerignore`, compose file, formal server entrypoint, or production-oriented `cli_url` wiring, so containerized deployment remains a design and packaging follow-on rather than a completed capability.
- Expected behavior:
  - The repository should expose the completed MVP surface over a `copilot-sdk` runtime adapter and then package that service for containerized deployment without violating the SDK's backend-services, scaling, and authentication guidance.
  - The packaging/auth model should keep the service as a wrapped provider: callers pass GitHub bearer tokens through per request, the service does not become a separate identity provider, raw tokens are never persisted in session state, and subject-bound session resume remains a Step 6 implementation requirement rather than a current capability.
- Scope affected (modules/endpoints/commands):
  - `src/copilot_model_provider/**`
  - `tests/**`
  - `pyproject.toml`
  - provider HTTP API surface

## Environment
- OS: Linux
- Runtime/tool versions:
  - Python `>=3.14` (`pyproject.toml`)
  - runtime dependencies: `github-copilot-sdk`, `structlog`
  - dev tooling: `ruff`, `pyright`, `ty`
- Repro command(s):
  - `uv run ruff check .`
  - `uv run pyright`
  - `uv run ty check .`
  - `uv run python -m copilot_model_provider`

## Evidence
Include concrete evidence. Prefer copy/paste of relevant excerpts with context.
- Logs / stack traces:
  - Current repo validation is green for `ruff`, `pyright`, `ty`, and the thin service entrypoints (`python -m copilot_model_provider` / `copilot-model-provider`).
- Failing tests (name + output excerpt):
  - None at the time of this update; validation is green with `uv run pytest -q` (`114 passed`), and the enforced coverage gate remains satisfied at `94.51%`.
- Metrics (numbers + method):
  - Not applicable for containerization design yet; this update is about operational packaging prerequisites rather than benchmark results.
- Repro steps (minimal):
  1. Inspect repository root: `docs/`, `plans/`, `src/`, `tests/`, and project configs exist.
  2. Read `docs/design.md`.
  3. Confirm the current provider implementation and tests are present, but that no container assets (`Dockerfile`, compose file, `.dockerignore`) exist.

## Code Reading Notes
List the most relevant files and what you learned.
- `docs/design.md` — canonical architecture and MVP scope. Key conclusions:
  - the provider should be a compatibility gateway + canonical core + Copilot runtime adapter
  - MVP northbound surface is `GET /v1/models` and `POST /v1/chat/completions`
  - provider-native session APIs and provider-native response-style APIs remain architecturally valuable, but are not required to ship first
  - real-client E2E must cover streaming, tool calls, session reuse, routing, and MCP
- `pyproject.toml` — confirms the project is Python `src/` layout, depends on `github-copilot-sdk` and `structlog`, and now exposes a thin service entrypoint through `copilot_model_provider.server:main`.
- `pyproject.toml` — now also includes `fastapi`, `pydantic-settings`, `pytest`, `pytest-asyncio`, `pytest-cov`, and `httpx`, which means the repo has standardized both in-process app testing and HTTP-level contract/smoke checks.
- `src/copilot_model_provider/` — the app/config/core/runtime seams are in place, and the first public compatibility endpoint (`GET /v1/models`) is now wired through the app.
- `tests/` — unit tests, contract tests, and integration coverage now exist for the functional MVP, so any containerization slice should add packaging/smoke coverage rather than redefining functional behavior.
- `AGENTS.md` — requires evidence-driven work, reviewable increments, and Gate 1 / Gate 2 when the work spans multiple components or includes multiple design options.
- Official `copilot-sdk` setup/auth docs — the backend-services guide recommends an external headless CLI server connected via `cliUrl`, the scaling guide recommends sticky routing or shared storage for session state and explicit locking for shared sessions, and the auth docs support OAuth/env/BYOK auth without relying on interactive logged-in-user state for server-side deployments.
- Chosen auth baseline — the provider remains service-first rather than identity-first: callers pass a GitHub bearer token directly or via OAuth, the service forwards that credential into runtime execution, raw runtime tokens are never stored, and subject-bound session resume must be added in the packaging slice before that flow is treated as production-ready.
- Hot files for parallel planning:
  - `src/copilot_model_provider/api/openai_chat.py`
  - `src/copilot_model_provider/runtimes/copilot.py`
  - `src/copilot_model_provider/core/sessions.py`
  - `tests/integration_tests/harness.py`
  These are likely conflict hotspots because they sit on the convergence path for chat execution, streaming, session resume, and tool behavior.

## Hypotheses (ranked)
1. A base-contracts-first split will minimize churn and keep hot files stable while the service grows from skeleton to working gateway.
2. `GET /v1/models` should ship before chat execution because it exercises the catalog/router boundary without depending on session, streaming, or tool semantics.
3. Provider-native conversation APIs should be deferred until after MVP so the first PR sequence stays focused on the OpenAI-compatible compatibility path.

## Experiments Run
For each experiment:
- Command / action: reviewed `docs/design.md` sections covering architecture, component design, API strategy, MVP scope, validation strategy, and suggested repository structure.
  - Result: the document provides enough architectural evidence to derive a staged implementation plan.
  - Interpretation: decomposition can be based on explicit repo artifacts rather than speculation.
- Command / action: inspected repository structure and `pyproject.toml`.
  - Result: the repo already has the standard Python package layout and dependencies needed for the first implementation slices.
  - Interpretation: the base PR can focus on service scaffolding and contracts instead of package migration.
- Command / action: confirmed with the user that provider-native session APIs are deferred until after MVP.
  - Result: MVP scope is tighter and less ambiguous.
  - Interpretation: the PR split can center on OpenAI-compatible models/chat, then layer stateful behavior internally before exposing any provider-native API.
- Command / action: reviewed the first Gate 2 draft and refined the slug to resolve ambiguous assumptions and validation timing.
  - Result: the decomposition now explicitly fixes the MVP scope decision, treats health/readiness as internal-only if present, chooses a local/file-backed starting point for session mapping abstraction, and introduces lightweight E2E earlier in the sequence.
  - Interpretation: the split is more execution-ready and less likely to discover wire-compatibility problems too late.
- Command / action: confirmed with the user that MVP tool support is limited to server-approved tools plus MCP.
  - Result: the final open MVP scope question for tool support is resolved.
  - Interpretation: the cleanup PR can target a narrower and more reviewable tool surface without adding caller-supplied tool schema support.
- Command / action: reviewed the approved PR sequence through the `plan-parallel-work` lens.
  - Result: safe multi-agent fan-out is limited; the foundation chain must stay serial until the first non-streaming chat path is stable.
  - Interpretation: parallelism should be introduced only after shared runtime/API seams stop changing rapidly, with a designated convergence owner for the hot files.

## Open Questions / Unknowns
- Q1: None blocking the functional MVP. For containerization, the recommended default is now clear from the official docs: API container + headless CLI container, internal-only transport, persistent CLI session-state storage, and explicit runtime auth injection.

## Dependency / Conflict Analysis
- Serial prerequisite chain:
  - `PR 1` -> `PR 2` -> `PR 3` should remain serial because the application scaffold, catalog/router contract, and first chat/runtime path all stabilize shared seams used by every later slice.
- Earliest safe fan-out point:
  - After `PR 3` is merged, two lower-overlap branches can proceed in parallel:
    - streaming transport work under `streaming/**`
    - session persistence / locking work under `storage/**`
- Convergence requirement:
  - A single convergence owner must later integrate those branches into the hot files:
    - `src/copilot_model_provider/api/openai_chat.py`
    - `src/copilot_model_provider/runtimes/copilot.py`
    - `src/copilot_model_provider/core/sessions.py`
    - `tests/integration_tests/harness.py`
  - The fan-out branches should contribute only owned modules and tests; they do not directly wire their work into the hot files above.
- Unsafe parallel areas:
  - `PR 1` through `PR 3` should not be parallelized because they still define shared contracts.
  - Tool/MCP completion should not fan out until streaming/session convergence is complete, because `runtimes/copilot.py` and release-gate E2E remain shared integration surfaces.

## Recommendation for Plan
- Proposed direction:
  - Use a staged base -> read-only metadata -> chat execution -> streaming/session hardening -> tools/MCP completion sequence.
  - Keep tests with the code they validate.
  - Keep provider-native session endpoints and provider-native response-style APIs out of the first sequence.
  - Keep MVP tool support limited to server-approved tools plus MCP.
  - Introduce lightweight E2E scaffolding early and expand it incrementally instead of deferring all running-app checks to the last PR.
  - If multiple agents are used, keep `PR 1` through `PR 3` serial, then fan out streaming and session-persistence work into separate branches/worktrees, and assign a single convergence owner before Tool/MCP completion.
  - Treat the plan as **five execution phases implemented through seven mergeable branches**: `PR 1`, `PR 2`, `PR 3`, streaming branch, session branch, convergence branch, and final Tool/MCP + release-gate branch.
  - After the functional MVP, add one operational packaging follow-on focused on containerization: formal server entrypoint, provider API image, headless CLI container connectivity through `cliUrl`, persistent CLI session-state storage, internal-only CLI networking, caller-supplied GitHub bearer-token passthrough, subject-bound session resume enforcement, and optional BYOK secret injection.
- Risks:
  - session, streaming, and tool support touch overlapping files (`api/openai_chat.py`, `runtimes/copilot.py`, `core/sessions.py`), so the split must keep responsibilities crisp
  - premature introduction of provider-native APIs would expand the surface faster than the runtime adapter is proven
  - tool/MCP scope can still widen unexpectedly if post-MVP expansion pressure leaks into this first release
  - parallel work started before the foundation chain is stable will create rebasing churn in the same hot files
  - a naive single-image deployment that relies on interactive CLI login or exposes the headless CLI publicly would conflict with the SDK's backend/auth guidance and create avoidable operational risk
  - if raw runtime tokens are persisted or resumed sessions are not bound to the original auth subject, the provider could create cross-user session leakage
- Suggested verification level (L1/L2/L3):
  - Base PR: L1
  - Metadata and chat slices: L1 moving to L2 once HTTP endpoints exist, with lightweight E2E smoke beginning early
  - Streaming / session / tool / MCP slices: L2 minimum, with targeted real-client style checks where feasible
