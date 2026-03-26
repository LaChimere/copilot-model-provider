# Task Checklist

> Purpose: execution-phase checklist derived from `plans/{slug}/plan.md`.
> Treat this as the progress truth source.

## Task
- Summary:
  - Execute the approved `copilot-model-provider-mvp` plan through the completed functional MVP, then track the completed containerization and thin OpenAI-compatible Responses/Codex follow-ons over `copilot-sdk`.
- Links:
  - `plans/copilot-model-provider-mvp/research.md`
  - `plans/copilot-model-provider-mvp/design.md`
  - `plans/copilot-model-provider-mvp/plan.md`
  - `docs/design.md`

## Plan Reference
- Plan version/date:
  - Parallel-work Gate 2 draft, updated after MVP completion to add the containerization follow-on and the later thin Responses/Codex compatibility slice
- Approved by (if applicable):
  - Gate 2 was approved for the functional MVP sequence; this checklist now also tracks the completed operational packaging and Responses/Codex follow-ons

## Checklist
### Preparation
- [ ] Sync/confirm baseline (main branch / clean state)
- [ ] Confirm repro or failing test exists (if bug)
- [x] Confirm verification level target (L1/L2/L3)
  - Acceptance criteria:
    - L2 is the minimum verification target for MVP execution slices with HTTP/runtime behavior.
  - Evidence:
    - captured in `plans/copilot-model-provider-mvp/plan.md`
- [x] Confirm scope boundary for provider-native APIs
  - Acceptance criteria:
    - provider-native session APIs are explicitly deferred until after MVP in this plan slug, while the later thin OpenAI-compatible `/v1/responses` follow-on remains a compatibility extension rather than a provider-native API family.
  - Evidence:
    - captured in `plans/copilot-model-provider-mvp/design.md` and `plan.md`
- [x] Confirm tool-scope boundary for MVP
  - Acceptance criteria:
    - MVP tool support is limited to server-approved tools plus MCP.
  - Evidence:
    - captured in `plans/copilot-model-provider-mvp/research.md`, `design.md`, and `plan.md`
- [x] Confirm parallel-work boundaries
  - Acceptance criteria:
    - `PR 1` -> `PR 3` remain serial
    - fan-out starts only after the foundation chain is merged
    - convergence owner and hot-file boundaries are explicit
  - Evidence:
    - captured in `plans/copilot-model-provider-mvp/design.md` and `plan.md`

### Implementation
- [x] Item 1: Land the serial foundation chain (`PR 1` -> `PR 2` -> `PR 3`)
  - Current execution status:
    - `PR 1` completed on branch `feat/pr1-foundation-scaffold` (`76db366`)
    - model-catalog slice merged into `main` as `7c4d12c`
    - non-streaming chat slice merged into `main` as `1df9534`
  - Acceptance criteria:
    - base scaffold, `/v1/models`, and non-streaming chat land in order
    - shared contracts are stable enough for fan-out
    - lightweight smoke tests exist for the running app
  - Evidence:
    - foundation evidence: `uv run ruff check .`, `uv run pyright`, `uv run ty check .`, `uv run pytest -q`
    - model-catalog evidence: `uv run ruff check .`, `uv run pyright`, `uv run ty check .`, `uv run pytest -q`
    - non-streaming chat evidence: `uv run ruff check .`, `uv run pyright`, `uv run ty check .`, `uv run pytest -q`
- [x] Item 2: Fan out `feat/mvp-streaming-transport` and `feat/mvp-session-persistence`
  - Current execution status:
    - streaming transport slice merged into `main` as `e78c081`
    - session persistence slice merged into `main` as `f07c035`
    - follow-up type-check/test cleanup landed on `main` as `4ceb451`
  - Acceptance criteria:
    - both branches respect branch/worktree boundaries
    - streaming-only and storage/locking-only scopes land without touching forbidden paths
    - both branches contribute owned modules/tests only
  - Evidence:
    - PR #4 merged: `feat/mvp-streaming-transport` -> `main`
    - PR #5 merged: `feat/mvp-session-persistence` -> `main`
    - both branches passed branch-scoped validation before merge and review findings were resolved before landing
- [x] Item 3: Converge streaming and session branches
  - Current execution status:
    - the shared hot files are integrated on `main`
    - streaming SSE, session persistence/resume, and locking behavior are now wired into `/v1/chat/completions`
    - the review-found streaming setup cleanup leak was fixed before completion
  - Acceptance criteria:
    - hot files are integrated by the convergence owner
    - streaming + resumed-follow-up E2E passes
    - locking/ownership behavior is covered by focused tests
  - Evidence:
    - `uv run ruff check . && uv run pyright && uv run ty check . && uv run pytest -q`
    - `85 passed`
    - `Required test coverage of 90% reached. Total coverage: 94.74%`
- [x] Item 4: Land `feat/mvp-tools-mcp`
  - Current execution status:
    - server-approved tools are now mounted into SDK sessions and approved by policy
    - configured MCP servers are now mounted into SDK sessions and approved by policy
    - focused HTTP integration tests now validate both the server-approved tool path and the MCP-backed path
  - Acceptance criteria:
    - server-approved tool and MCP flows succeed at the agreed MVP depth
    - forbidden-path boundaries are respected
  - Evidence:
    - `uv run ruff check . && uv run pyright && uv run ty check . && uv run pytest -q`
    - `109 passed`
    - `Required test coverage of 90% reached. Total coverage: 94.21%`
- [x] Item 5: Final cleanup and MVP release-gate E2E
  - Current execution status:
    - release-gate integration coverage now validates alias advertisement, routed `runtime_model_id` selection, sessional alias enforcement, session persistence, and clean `model_not_found` responses for unknown aliases
    - follow-up code review found no substantive issues to resolve
  - Acceptance criteria:
    - release-gate scenarios pass
    - no temporary scaffolding is left undocumented
  - Evidence:
    - `uv run ruff check . && uv run pyright && uv run ty check . && uv run pytest -q`
    - `113 passed`
    - `Required test coverage of 90% reached. Total coverage: 94.48%`
- [x] Item 6: Containerized deployment and production-image baseline
  - Current execution status:
    - completed
    - Step 6.1 is complete: the formal `server.py` entrypoint is in place, configuration now exposes `ProviderSettings.runtime_cli_url` / `COPILOT_MODEL_PROVIDER_RUNTIME_CLI_URL`, and the default `CopilotRuntimeAdapter` now supports the SDK external-server mode
    - Step 6.2 is complete: `Dockerfile` and `.dockerignore` exist, and the image starts through the formal `copilot-model-provider` service entrypoint
    - Step 6.3 is complete: request-scoped bearer-token extraction, auth-subject fingerprint persistence, and same-subject session resume enforcement are implemented without persisting raw runtime tokens
    - Step 6.4 is complete: full repo validation, image build smoke, container startup smoke, and packaging docs are in place
    - the canonical design and this slug now capture the backend/scaling/auth constraints plus the current external-server auth limitation of the installed SDK surface
  - Planned internal sequence:
    - [x] Step 6.1: server/config baseline
      - Acceptance criteria:
        - the service startup path is formalized around `src/copilot_model_provider/server.py`
        - Step 6 configuration can represent external headless CLI connectivity
        - no service-owned identity layer is introduced
    - [x] Step 6.2: container assets and startup path
      - Acceptance criteria:
        - `Dockerfile` and `.dockerignore` are added
        - the image starts the provider through the formal server entrypoint
        - the first documented topology remains API container + internal headless CLI
    - [x] Step 6.3: auth passthrough and subject-bound session resume
      - Acceptance criteria:
        - request-scoped GitHub bearer-token passthrough is implemented for runtime execution, with explicit fail-fast when `runtime_cli_url` points to an external CLI because the current SDK does not expose per-request GitHub auth injection for `ExternalServerConfig`
        - raw runtime tokens are not persisted
        - resumed sessions cannot cross authenticated subjects
    - [x] Step 6.4: smoke validation and packaging docs
      - Acceptance criteria:
        - image build smoke passes
        - service startup smoke passes against the container entrypoint
        - packaging docs describe the token contract, session-state storage, and internal CLI boundary
  - Acceptance criteria:
    - container startup uses a formal API server entrypoint
    - the provider connects to an internal headless CLI server instead of depending on per-request child-process spawning
    - session-state persistence and request-scoped GitHub bearer-token runtime credential passthrough are explicit in docs and packaging
    - raw runtime tokens are not persisted, and the packaging slice adds subject-bound resume enforcement before sessional auth passthrough is treated as production-ready
    - the first supported deployment topology is named explicitly
  - Evidence:
    - `uv run ruff check . && uv run pyright && uv run ty check . && uv run pytest -q`
    - `130 passed`
    - `Required test coverage of 90% reached. Total coverage: 94.72%`
    - `docker build -t copilot-model-provider:step6-smoke .`
    - `docker run -d -p 18080:8000 -e COPILOT_MODEL_PROVIDER_RUNTIME_CLI_URL=http://copilot-cli.internal:3000 copilot-model-provider:step6-smoke`
    - `GET /_internal/health` returned `200 OK`
- [x] Item 7: Thin OpenAI-compatible Responses support and Codex cutover
  - Current execution status:
    - `POST /v1/responses` is now implemented as a thin adapter over the existing canonical chat/session/runtime path
    - the Responses SSE lifecycle is aligned with Codex custom-provider expectations, including `response.output_item.done` before `response.completed`
    - Docker-backed smoke now validates a real `codex exec` path through the provider with `wire_api = "responses"` and `env_key = "GITHUB_TOKEN"`
    - a root `.env.example` now documents the required `GITHUB_TOKEN` contract for local Codex/provider usage
  - Acceptance criteria:
    - the provider reuses existing routing/session/runtime seams rather than creating a separate Responses execution stack
    - the final streamed answer renders exactly once for Codex-style clients
    - local configuration cutover to the provider is validated end to end
  - Evidence:
    - `uv run ruff check . && uv run pyright && uv run ty check . && uv run pytest -q`
    - `138 passed`
    - `Required test coverage of 90% reached. Total coverage: 94.36%`
    - `docker build -t copilot-model-provider:responses-smoke .`
    - `codex exec --skip-git-repo-check 'Reply with exactly HELLO.'`
    - stdout contained `HELLO.` when driven through the provider using the real `~/.codex/config.toml`

### Acceptance Gate (before proposing PR)
- [x] All acceptance criteria above are met with evidence
- [x] Diff is consistent with approved plan (no scope creep, no missing pieces)
- [x] Applicable verification level executed

If any check fails, follow the recovery flow defined in `AGENTS.md` (Verification rules → Acceptance criteria):
1. Can fix directly → fix and re-verify
2. Plan is infeasible → update `plan.md`, re-submit for Gate 2
3. Design is invalid → update `design.md`, re-submit for Gate 1 → Gate 2
4. Stuck → stop and report to user with evidence of what was attempted

### Verification (Evidence)
- [ ] Run lint/typecheck: `uv run ruff check . && uv run pyright && uv run ty check .` (attach output/excerpt)
- [ ] Run unit tests: targeted `tests/unit/**` commands (attach output/excerpt)
- [ ] Run integration/e2e or before/after check: targeted `tests/contract/**`, `tests/integration_tests/**`, and incremental `tests/integration_tests/**` commands per step (attach proof)
- [ ] Confirm branch/worktree ownership boundaries were respected during fan-out and convergence
- [ ] Capture logs/metrics if required

### Review / Packaging
- [x] Summarize changes (what/why)
- [x] Confirm no scope creep / unrelated cleanup
- [x] Check whether related docs need updating (use `refresh-related-docs` if behavior, config, or API changed)
- [ ] Prepare PR description / changelog notes (if applicable)

## Evidence Log
Paste concise evidence here (commands + key lines).
- non-streaming chat slice:
  - `uv run ruff check . && uv run pyright && uv run ty check . && uv run pytest -q`
  - `35 passed`
  - `Required test coverage of 90% reached. Total coverage: 95.81%`
- streaming transport slice:
  - merged as `e78c081` via PR #4
  - branch-scoped validation and review-fix pass completed before merge
- session persistence slice:
  - merged as `f07c035` via PR #5
  - branch-scoped validation completed before merge; post-merge type-check cleanup landed as `4ceb451`
- Step 3 convergence:
  - `uv run ruff check . && uv run pyright && uv run ty check . && uv run pytest -q`
  - `85 passed`
  - `Required test coverage of 90% reached. Total coverage: 94.74%`
- Step 4 Tool/MCP completion:
  - `uv run ruff check . && uv run pyright && uv run ty check . && uv run pytest -q`
  - `109 passed`
  - `Required test coverage of 90% reached. Total coverage: 94.21%`
- Step 5 release-gate coverage:
  - `uv run ruff check . && uv run pyright && uv run ty check . && uv run pytest -q`
  - `113 passed`
  - `Required test coverage of 90% reached. Total coverage: 94.48%`
- Containerization baseline:
  - `Dockerfile`, `.dockerignore`, and the formal `copilot-model-provider` startup path now exist
  - `docs/design.md`, `plans/copilot-model-provider-mvp/research.md`, and `plans/copilot-model-provider-mvp/design.md` now record the API-container + internal headless-CLI topology plus the current external-server auth limitation of the installed SDK surface
  - `uv run ruff check . && uv run pyright && uv run ty check . && uv run pytest -q`
  - `130 passed`
  - `Required test coverage of 90% reached. Total coverage: 94.72%`
  - `docker build -t copilot-model-provider:step6-smoke .`
  - `GET /_internal/health` returned `200 OK` from the started container image
- Thin Responses / Codex follow-on:
  - `src/copilot_model_provider/api/openai_responses.py`, `core/responses.py`, `streaming/responses.py`, and Responses tests now exist
  - `uv run ruff check . && uv run pyright && uv run ty check . && uv run pytest -q`
  - `138 passed`
  - `Required test coverage of 90% reached. Total coverage: 94.36%`
  - `docker build -t copilot-model-provider:responses-smoke .`
  - `codex exec --skip-git-repo-check 'Reply with exactly HELLO.'`
  - response output rendered `HELLO.` through the provider after the real `~/.codex/config.toml` cutover

## Result
- Outcome:
  - Step 1 through Step 7 are complete on `main`, including the first packaging baseline for container build/startup, safe subject-bound runtime auth handling, and thin OpenAI-compatible Responses/Codex compatibility.
- Follow-ups (if any):
  - Revisit external headless-CLI + request-scoped GitHub bearer-token passthrough when the SDK exposes per-request auth injection for `ExternalServerConfig`.
