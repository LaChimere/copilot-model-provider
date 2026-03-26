# copilot-model-provider

`copilot-model-provider` is a Python project for building a general-purpose model provider on top of [`github-copilot-sdk`](https://github.com/github/copilot-sdk).

The goal is to expose a stable northbound API for multiple client styles while using `copilot-sdk` as the runtime substrate for sessions, streaming, tools, MCP, and model execution.

## Status

This repository now has the **functional MVP plus packaging and Codex-compatibility follow-ons** implemented on `main`.

Today it contains:

- the canonical architecture/design document in `docs/design.md`
- an approved MVP planning slug in `plans/copilot-model-provider-mvp/`
- a FastAPI app scaffold with an internal health endpoint
- a service-owned model catalog and OpenAI-compatible `GET /v1/models`
- an OpenAI-compatible `POST /v1/chat/completions` supporting non-streaming and streaming SSE behavior
- a thin OpenAI-compatible `POST /v1/responses` surface for Codex-style clients
- session-backed convergence for routes configured as `sessional`, including persistent session resume and locking via `X-Copilot-Conversation-Id`
- a Copilot SDK-backed runtime adapter for stateless and session-backed chat execution
- basic server-approved tool mounting and policy-driven approval
- basic MCP mounting for configured session launches
- a container packaging baseline (`Dockerfile`, `.dockerignore`) plus a root `.env.example` for local token/config setup
- focused release-gate integration coverage for model alias routing and policy behavior
- project tooling (`uv`, `ruff`, `pyright`, `ty`)
- `pytest`-based unit, contract, and lightweight integration coverage

The package entrypoints are now intentionally thin service launchers: `python -m copilot_model_provider` and `copilot-model-provider` start the HTTP/ASGI service through the formal `server.py` entrypoint rather than pretending to be a separate end-user CLI. The MVP HTTP surface, the packaging baseline, and the thin Responses/Codex follow-on are implemented on `main`.

## Current implemented surface

Available today:

- `GET /v1/models`
- `POST /v1/chat/completions` (non-streaming and streaming SSE)
- `POST /v1/responses` (thin OpenAI-compatible Responses surface)
- session-backed resume/locking behavior for routes configured as `sessional`
- basic server-approved tool execution through the existing chat/runtime path
- basic MCP mounting for configured runtime sessions
- `GET /_internal/health`

Minimum release-gate coverage now includes:

- `/v1/models` alias advertisement
- non-streaming chat
- streaming SSE framing
- session-backed resume/locking for routes configured as `sessional`
- one server-approved tool path
- one MCP-backed path
- one routing/policy alias path

## What this project is trying to build

At a high level, the target system is:

1. a **northbound compatibility layer**
   for OpenAI-style clients first, with room for additional protocol facades later
2. a **canonical core**
   for request normalization, model catalog, routing, session lifecycle, policy, and event translation
3. a **Copilot runtime adapter**
   that uses `copilot-sdk` as the first execution backend

The key architectural choice is that this project treats `copilot-sdk` as a **runtime kernel**, not as a thin stateless completion proxy.

That means the design keeps these concepts first-class:

- sessions
- streaming events
- tool execution
- MCP integration
- model routing
- policy enforcement
- observability

## MVP scope

The current MVP direction is intentionally narrow.

In scope:

- `GET /v1/models`
- `POST /v1/chat/completions`
- SSE streaming for chat completions
- a service-owned model catalog
- a Copilot runtime adapter
- session create/resume mapping
- basic server-approved tool support
- basic MCP mounting

Out of scope for the current MVP:

- provider-native session APIs
- provider-native response-style API families beyond the thin OpenAI-compatible `/v1/responses` route
- Anthropic-compatible facade
- caller-supplied tool schemas
- multi-runtime fallback routing

The detailed rationale lives in:

- `docs/design.md`
- `plans/copilot-model-provider-mvp/research.md`
- `plans/copilot-model-provider-mvp/design.md`
- `plans/copilot-model-provider-mvp/plan.md`

## Repository layout

```text
docs/
  design.md

plans/
  copilot-model-provider-mvp/
    research.md
    design.md
    plan.md
    todo.md

src/
  copilot_model_provider/
    __init__.py
    __main__.py
    api/
    config.py
    core/
    runtimes/
    server.py

tests/
```

## Development

This repository uses `uv` and a standard Python `src/` layout.

### Requirements

- Python 3.14+
- `uv`

### Install dependencies

```bash
uv sync
```

### Run the service entrypoint

```bash
uv run python -m copilot_model_provider
uv run copilot-model-provider
```

Both commands start the provider through `uvicorn` using the app factory entrypoint.

### Packaging-oriented runtime baseline

For deployment-oriented setups, the provider can connect to an already managed headless Copilot CLI server instead of using the SDK's default subprocess mode.

```bash
export COPILOT_MODEL_PROVIDER_SERVER_HOST=0.0.0.0
export COPILOT_MODEL_PROVIDER_SERVER_PORT=8000
export COPILOT_MODEL_PROVIDER_RUNTIME_CLI_URL=http://copilot-cli.internal:3000
uv run copilot-model-provider
```

When `COPILOT_MODEL_PROVIDER_RUNTIME_CLI_URL` is set, `ProviderSettings.runtime_cli_url` wires the default `CopilotRuntimeAdapter` through the SDK external-server configuration while keeping the provider as a thin API wrapper around Copilot-managed models.

Request-scoped runtime auth uses the incoming `Authorization: Bearer ...` header. The provider never persists the raw bearer token; session-backed resume stores only a derived bearer-token subject fingerprint. That means one subject cannot resume another subject's Copilot session.

In practice, conversation resume is bound to the original auth context. If you switch between anonymous and bearer-authenticated requests, or rotate to a different bearer token, start a new conversation ID instead of trying to resume the old one.

Current limitation: the installed `github-copilot-sdk` exposes `github_token` injection only on `SubprocessConfig`, not on `ExternalServerConfig`. Because of that, request-scoped GitHub bearer-token passthrough currently works in subprocess-backed runtime mode, while `runtime_cli_url` + request-scoped GitHub bearer auth is rejected explicitly instead of silently mixing credentials.

Use these deployment patterns today:

- use the default subprocess-backed runtime when callers need to forward their own GitHub bearer tokens, including local Codex testing
- use `runtime_cli_url` only when the external Copilot CLI server is already authenticated or otherwise managed as a service-scoped runtime, without per-request bearer passthrough

### Local Codex / custom-provider baseline

For local Codex testing, the repository now exposes a thin OpenAI-compatible `/v1/responses` route and expects Codex to forward a GitHub token through `env_key = "GITHUB_TOKEN"`.

See `.env.example` for the minimal local environment contract.

### Build the API image

```bash
docker build -t copilot-model-provider:local .
docker run --rm -p 8000:8000 \
  -e COPILOT_MODEL_PROVIDER_RUNTIME_CLI_URL=http://copilot-cli.internal:3000 \
  copilot-model-provider:local
```

### Lint and type-check

```bash
uv run ruff check .
uv run pyright
uv run ty check .
```

### Run tests

```bash
uv run pytest -q
```

## Planning and execution model

This repository follows an agent-driven, reviewable workflow defined in `AGENTS.md`.

For the current MVP slug, the approved execution model is:

1. land the serial foundation chain
   - app/config/contracts
   - `/v1/models`
   - non-streaming chat
2. fan out streaming and session-persistence work in parallel
3. converge those branches under a single owner
4. add Tool/MCP completion
5. finish release-gate E2E and cleanup

The current plan describes this as **five execution phases implemented as seven mergeable branches**.
All five phases are now implemented locally on `main`, and the later packaging plus thin Responses/Codex follow-ons are also complete.

## Important documents

- `docs/design.md`
  - canonical architecture/design baseline
- `plans/copilot-model-provider-mvp/`
  - current MVP planning slug
- `AGENTS.md`
  - repo-local workflow and approval-gate rules

## Notes

- Logging is expected to use `structlog`.
- The design assumes `copilot-sdk` remains the primary runtime adapter for the first release.
- If you are looking for the implementation plan, start with `plans/copilot-model-provider-mvp/plan.md`.
