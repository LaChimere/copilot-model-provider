# copilot-model-provider

`copilot-model-provider` is a Python project for building a general-purpose model provider on top of [`github-copilot-sdk`](https://github.com/github/copilot-sdk).

The goal is to expose a stable northbound API for multiple client styles while using `copilot-sdk` as the runtime substrate for model execution, streaming, and request-scoped auth passthrough.

## Status

This repository now has the **functional MVP plus packaging and Codex-compatibility follow-ons** implemented on `main`.

Today it contains:

- the canonical architecture/design document in `docs/design.md`
- an approved MVP planning slug in `plans/copilot-model-provider-mvp/`
- a FastAPI app scaffold with an internal health endpoint
- a service-owned model catalog and OpenAI-compatible `GET /v1/models`
- an OpenAI-compatible `POST /v1/chat/completions` supporting non-streaming and streaming SSE behavior
- a thin OpenAI-compatible `POST /v1/responses` surface for Codex-style clients
- a Copilot SDK-backed runtime adapter for thin stateless chat execution
- a container packaging baseline (`Dockerfile`, `.dockerignore`) plus a root `.env.example` for local token/config setup
- focused release-gate integration coverage for models, chat, Responses, and Docker-backed end-to-end execution
- project tooling (`uv`, `ruff`, `pyright`, `ty`)
- `pytest`-based unit, contract, and lightweight integration coverage

The package entrypoints are now intentionally thin service launchers: `python -m copilot_model_provider` and `copilot-model-provider` start the HTTP/ASGI service through the formal `server.py` entrypoint rather than pretending to be a separate end-user CLI. The MVP HTTP surface, the packaging baseline, and the thin Responses/Codex follow-on are implemented on `main`.

## Current implemented surface

Available today:

- `GET /v1/models`
- `POST /v1/chat/completions` (non-streaming and streaming SSE)
- `POST /v1/responses` (thin OpenAI-compatible Responses surface)
- `GET /_internal/health`

Minimum release-gate coverage now includes:

- `/v1/models` alias advertisement
- non-streaming chat
- streaming SSE framing
- thin `/v1/responses` compatibility
- Docker-backed black-box integration coverage

## What this project is trying to build

At a high level, the target system is:

1. a **northbound compatibility layer**
   for OpenAI-style clients first, with room for additional protocol facades later
2. a **canonical core**
   for request normalization, model catalog, routing, and event translation
3. a **Copilot runtime adapter**
   that uses `copilot-sdk` as the first execution backend

The key architectural choice is that this project treats `copilot-sdk` as the execution backend while keeping the current provider implementation intentionally **thin and stateless**.

That means the current implementation keeps these concepts first-class:

- streaming events
- model routing
- request-scoped auth passthrough
- observability

## MVP scope

The current MVP direction is intentionally narrow.

In scope:

- `GET /v1/models`
- `POST /v1/chat/completions`
- SSE streaming for chat completions
- thin OpenAI-compatible `/v1/responses`
- a service-owned model catalog
- a Copilot runtime adapter
- subprocess-backed request-scoped GitHub bearer-token passthrough

Out of scope for the current MVP:

- provider-native session APIs
- server-side tool/MCP control planes
- external CLI runtime mode
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

The current packaging baseline runs the provider as a normal ASGI service and lets the runtime adapter use the SDK's subprocess-backed execution mode.

```bash
export COPILOT_MODEL_PROVIDER_SERVER_HOST=0.0.0.0
export COPILOT_MODEL_PROVIDER_SERVER_PORT=8000
uv run copilot-model-provider
```

Request-scoped runtime auth uses the incoming `Authorization: Bearer ...` header. The provider forwards that token into a short-lived subprocess-backed Copilot client for the request and never persists the raw bearer token.

### Local Codex / custom-provider baseline

For local Codex testing, the repository now exposes a thin OpenAI-compatible `/v1/responses` route and expects Codex to forward a GitHub token through `env_key = "GITHUB_TOKEN"`.

See `.env.example` for the minimal local environment contract.

### Build the API image

```bash
docker build -t copilot-model-provider:local .
docker run --rm -p 8000:8000 copilot-model-provider:local
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

The historical MVP slug includes broader session/tool/MCP branches, but the current implementation on `main` has been intentionally tightened back down to the thin stateless provider surface listed above.

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
