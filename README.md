# copilot-model-provider

`copilot-model-provider` is a Python project for building a general-purpose model provider on top of [`github-copilot-sdk`](https://github.com/github/copilot-sdk).

The goal is to expose a stable northbound API for multiple client styles while using `copilot-sdk` as the runtime substrate for model execution, streaming, and request-scoped auth passthrough.

## Status

This repository now has the **functional MVP plus packaging and Codex-compatibility follow-ons** implemented on `main`.

Today it contains:

- the canonical architecture/design document in `docs/design.md`
- an approved MVP planning slug in `plans/copilot-model-provider-mvp/`
- a FastAPI app scaffold with an internal health endpoint
- auth-aware live model discovery for both OpenAI- and Anthropic-compatible facades
- an OpenAI-compatible `POST /openai/v1/chat/completions` supporting non-streaming and streaming SSE behavior
- a thin OpenAI-compatible `POST /openai/v1/responses` surface for Codex-style clients
- an Anthropic-compatible `GET /anthropic/v1/models`, `POST /anthropic/v1/messages`, and `POST /anthropic/v1/messages/count_tokens` surface for Claude-style clients
- a Copilot SDK-backed runtime for thin stateless chat execution
- a container packaging baseline (`Dockerfile`, `.dockerignore`) plus a root `.env.example` for local token/config setup
- focused release-gate integration coverage for models, chat, Responses, and Docker-backed end-to-end execution
- project tooling (`uv`, `ruff`, `pyright`, `ty`)
- `pytest`-based unit, contract, and lightweight integration coverage

The package entrypoints are now intentionally thin service launchers: `python -m copilot_model_provider` and `copilot-model-provider` start the HTTP/ASGI service through the formal `server.py` entrypoint rather than pretending to be a separate end-user CLI. The MVP HTTP surface, the packaging baseline, and the thin Responses/Codex follow-on are implemented on `main`.

## Current implemented surface

Available today:

- `GET /openai/v1/models`
- `POST /openai/v1/chat/completions` (non-streaming and streaming SSE)
- `POST /openai/v1/responses` (thin OpenAI-compatible Responses surface)
- `GET /anthropic/v1/models`
- `POST /anthropic/v1/messages`
- `POST /anthropic/v1/messages/count_tokens`
- `GET /_internal/health`

Minimum release-gate coverage now includes:

- `/openai/v1/models` live model advertisement
- non-streaming chat
- streaming SSE framing
- thin `/openai/v1/responses` compatibility
- Anthropic-compatible models, messages, and count-tokens behavior
- Docker-backed black-box integration coverage

## What this project is trying to build

At a high level, the target system is:

1. a **northbound compatibility layer**
   for OpenAI-style and Anthropic-style clients
2. a **canonical core**
   for request normalization, live model discovery, routing, and event translation
3. a **Copilot runtime**
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

- `GET /openai/v1/models`
- `POST /openai/v1/chat/completions`
- SSE streaming for chat completions
- thin OpenAI-compatible `/openai/v1/responses`
- `GET /anthropic/v1/models`
- `POST /anthropic/v1/messages`
- `POST /anthropic/v1/messages/count_tokens`
- auth-aware live Copilot model exposure
- a Copilot runtime
- subprocess-backed request-scoped GitHub bearer-token passthrough

Out of scope for the current MVP:

- provider-native session APIs
- server-side tool/MCP control planes
- external CLI runtime mode
- provider-native response-style API families beyond the thin OpenAI-compatible `/openai/v1/responses` route
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
    logging_config.py
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

Both commands start the provider through programmatic `uvicorn.run(...)` using the app factory entrypoint. The service entrypoint configures `structlog` first, disables uvicorn's default access-log formatter, and lets the application emit HTTP request logs through the same structured logging pipeline.

### Packaging-oriented runtime baseline

The current packaging baseline runs the provider as a normal ASGI service and lets the runtime use the SDK's subprocess-backed execution mode.

```bash
export COPILOT_MODEL_PROVIDER_SERVER_HOST=0.0.0.0
export COPILOT_MODEL_PROVIDER_SERVER_PORT=8000
uv run copilot-model-provider
```

### Recommended Docker deployment flow

The repository treats the container image as the primary deployment example.

Recommended auth flow:

1. log in on the host with `gh auth login`
2. resolve a token on the host with `gh auth token`
3. pass that token into the container as `GITHUB_TOKEN`

```bash
gh auth login
export GITHUB_TOKEN="$(gh auth token)"
docker build -t copilot-model-provider:local .
docker run --rm \
  -e GITHUB_TOKEN \
  -p 8000:8000 \
  copilot-model-provider:local
```

Auth precedence is:

- `Authorization: Bearer ...` on an individual request
- otherwise the container-injected `GITHUB_TOKEN` / `GH_TOKEN`

The provider forwards the selected token into a short-lived subprocess-backed Copilot client and never persists the raw bearer token.

### Local Codex / custom-provider baseline

For local Codex testing, the repository now exposes a thin OpenAI-compatible `/openai/v1/responses` route and includes `scripts/config_codex.py` to:

- resolve `gh auth token`
- start or restart the local container on the requested port
- back up `~/.codex/config.toml`
- point Codex at the local provider
- default the configured model to `gpt-5.4`
- fail fast if the requested model is not visible from the running service's auth context

Visible model IDs depend on the bearer token or fallback container token that the running provider sees. `GET /openai/v1/models` is the canonical source of truth for what Codex may request.

### Local Claude baseline

For local Claude testing, the repository includes `scripts/config_claude.py` to:

- resolve `gh auth token`
- start or restart the local container on the requested port
- back up `~/.claude/settings.json`
- point Claude at the local provider through `ANTHROPIC_BASE_URL`
- discover visible Claude-family models from `GET /anthropic/v1/models`
- persist `ANTHROPIC_MODEL` plus Claude tier defaults into `settings.json`

Once configured, plain `claude` invocations use the provider's Anthropic-compatible facade.

See `.env.example` for the minimal local environment contract.

### Build the API image

```bash
docker build -t copilot-model-provider:local .
docker run --rm -e GITHUB_TOKEN -p 8000:8000 copilot-model-provider:local
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

### Opt-in live runtime sweeps

The repository also includes a real-auth live sweep for the provider's
implemented northbound execution routes:

```bash
# Fast mode: verify one preferred visible live model through chat + responses
COPILOT_MODEL_PROVIDER_RUN_LIVE_MODEL_SWEEP=1 \
  uv run pytest -q tests/live_tests/test_all_models.py -s

# Full mode: expand the sweep to every currently visible live Copilot model
COPILOT_MODEL_PROVIDER_RUN_LIVE_MODEL_SWEEP=1 \
COPILOT_MODEL_PROVIDER_RUN_LIVE_MODEL_SWEEP_ALL=1 \
  uv run pytest -q tests/live_tests/test_all_models.py -s
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

- Logging is unified through `structlog`, including service startup, uvicorn-integrated logs, and application-level HTTP request completion/failure events.
- Concrete `CopilotRuntime` and `ModelRouter` implementations explicitly inherit `RuntimeProtocol` and `ModelRouterProtocol`.
- The design assumes `copilot-sdk` remains the primary runtime integration for the first release.
- If you are looking for the implementation plan, start with `plans/copilot-model-provider-mvp/plan.md`.
