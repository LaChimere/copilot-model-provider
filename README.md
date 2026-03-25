# copilot-model-provider

`copilot-model-provider` is a Python project for building a general-purpose model provider on top of [`github-copilot-sdk`](https://github.com/github/copilot-sdk).

The goal is to expose a stable northbound API for multiple client styles while using `copilot-sdk` as the runtime substrate for sessions, streaming, tools, MCP, and model execution.

## Status

This repository is currently in the **design + scaffold** stage.

Today it contains:

- the canonical architecture/design document in `docs/design.md`
- an approved MVP planning slug in `plans/copilot-model-provider-mvp/`
- a Python `src/`-layout package skeleton
- project tooling (`uv`, `ruff`, `pyright`, `ty`)

It does **not** yet contain the finished provider service. The current package entrypoint is still a placeholder CLI.

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
- provider-native response-style APIs
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
    cli.py

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

### Run the current placeholder package entrypoint

```bash
uv run python -m copilot_model_provider
uv run copilot-model-provider
```

### Lint and type-check

```bash
uv run ruff check .
uv run pyright
uv run ty check .
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
