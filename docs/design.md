# copilot-model-provider Design

## 1. Purpose

This document describes the **current implementation** in `src/copilot_model_provider/`.

It is intentionally implementation-first:

- it documents the behavior that is actually shipped on `main`
- it does **not** treat historical planning artifacts as normative
- it does **not** depend on or reference historical planning artifacts as design sources

At the time of writing, the repository implements a **thin, stateless, subprocess-backed dual-protocol provider** on top of `github-copilot-sdk`.

## 2. System Overview

The service is a FastAPI application that exposes small OpenAI-compatible and Anthropic-compatible HTTP facades and translates those requests into ephemeral Copilot SDK sessions.

The core design choice is to keep the provider layer intentionally thin:

- northbound compatibility happens over HTTP
- routing happens through auth-context live model discovery
- execution happens through `github-copilot-sdk`
- provider-owned conversation/session state is **not** persisted across requests
- server-side tools and MCP are **not** enabled

In practical terms, the provider behaves like a compatibility gateway plus a small amount of normalization and streaming translation, not like a provider-owned agent platform.

## 3. Implemented Surface

The service currently exposes these endpoints:

### 3.1 `GET /openai/v1/models`

Implemented in `src/copilot_model_provider/api/openai/models.py`.

Behavior:

- lists the live model IDs visible to the current auth context
- returns an OpenAI-compatible model list response
- resolves auth the same way execution routes do:
  - `Authorization: Bearer ...`
  - otherwise the configured runtime fallback token

### 3.2 `GET /anthropic/v1/models`

Implemented in `src/copilot_model_provider/api/anthropic/models.py`.

Behavior:

- reuses the shared live model catalog already built for the active auth context
- returns an Anthropic-compatible model list response
- resolves auth from either:
  - `Authorization: Bearer ...`
  - `X-Api-Key`
  - otherwise the configured runtime fallback token

### 3.3 `POST /openai/v1/chat/completions`

Implemented in `src/copilot_model_provider/api/openai/chat.py`.

Behavior:

- accepts an OpenAI-compatible chat request
- supports non-streaming and streaming SSE responses
- resolves the requested public model ID through the model router
- forwards optional bearer auth into the runtime layer

### 3.4 `POST /openai/v1/responses`

Implemented in `src/copilot_model_provider/api/openai/responses.py`.

Behavior:

- accepts a thin OpenAI-compatible Responses subset intended for Codex-style clients
- supports non-streaming and streaming SSE responses
- reuses the same canonical chat/runtime path as `POST /v1/chat/completions`
- exposes Responses-specific lifecycle events for streaming

### 3.5 `GET /_internal/health`

Installed from `src/copilot_model_provider/app.py` when `enable_internal_health` is enabled.

Behavior:

- returns provider service metadata plus runtime health
- is intended as an internal diagnostics endpoint, not part of the public compatibility contract

## 4. High-Level Architecture

The implementation is split into five main layers.

### 4.1 Application assembly

Implemented in `src/copilot_model_provider/app.py`.

Responsibilities:

- load validated settings
- construct the runtime
- construct the model router
- validate injected runtimes and routers against explicit protocol contracts
- install routes and error handlers
- install structlog-backed HTTP request logging middleware
- optionally install the internal health endpoint

The formal service entrypoint in `src/copilot_model_provider/server.py` configures
`structlog` through `src/copilot_model_provider/logging_config.py` before calling
`uvicorn.run(...)` with the app factory entrypoint. Default uvicorn access logging
is disabled so startup/service logs and per-request logs all flow through the same
structured logging pipeline.

### 4.2 API layer

Implemented in `src/copilot_model_provider/api/`.

Responsibilities:

- parse HTTP requests
- normalize auth headers
- resolve public model IDs into runtime routes
- convert OpenAI-compatible and Anthropic-compatible requests into canonical internal requests
- format HTTP responses and SSE streams

### 4.3 Canonical core

Implemented in `src/copilot_model_provider/core/`.

Responsibilities:

- define internal request/response models
- normalize supported OpenAI and Anthropic request shapes
- render prompts for the runtime
- define the live model-catalog snapshot and model router
- translate runtime completions into northbound response shapes
- raise structured provider errors

### 4.4 Runtime layer

Implemented in `src/copilot_model_provider/runtimes/`.

Responsibilities:

- own the `github-copilot-sdk` integration
- list live model IDs for one auth context
- create ephemeral Copilot sessions per request
- execute non-streaming and streaming turns
- translate raw runtime failures into provider errors
- deny runtime permission requests for tools/MCP

### 4.5 Streaming helpers

Implemented in `src/copilot_model_provider/streaming/`.

Responsibilities:

- translate Copilot SDK session events into canonical stream events
- translate canonical stream events into protocol-specific streaming payloads
- encode SSE frames for chat, Responses, and Anthropic streaming

## 5. Request Normalization

### 5.1 Canonical request shape

The provider's shared execution path centers on `CanonicalChatRequest` in `src/copilot_model_provider/core/models.py`.

Current fields:

- `request_id`
- `conversation_id`
- `runtime_auth_token`
- `model_id`
- `messages`
- `stream`

Important note:

- `conversation_id` may be present in normalized data, but the current implementation does **not** use it for provider-managed session persistence or resume

### 5.2 Chat request normalization

Implemented in `src/copilot_model_provider/core/chat.py`.

Behavior:

- converts OpenAI chat messages into `CanonicalChatMessage`
- preserves only the current request's message list
- does not add provider-owned execution/session mode metadata

### 5.3 Responses request normalization

Implemented in `src/copilot_model_provider/core/responses.py`.

Behavior:

- converts `instructions` into system messages
- converts string or structured `input` into canonical messages
- normalizes `developer` role to `system`
- accepts the thin Responses subset needed by current clients

Important limitation:

- request fields such as `tools`, `tool_choice`, and `parallel_tool_calls` may be accepted by the request model for compatibility, but the provider does **not** execute server-side tools or MCP flows

### 5.4 Prompt rendering

Implemented in `src/copilot_model_provider/core/chat.py`.

Behavior:

- renders canonical messages into a plain text prompt using role labels such as `System:`, `User:`, and `Assistant:`
- sends that rendered prompt into the Copilot SDK session

The runtime path is therefore message-normalized at the provider boundary but prompt-based at the SDK call boundary.

## 6. Routing and Live Model Discovery

### 6.1 Auth-context model catalog snapshot

Implemented in `src/copilot_model_provider/core/catalog.py`.

A catalog snapshot is built dynamically from the live Copilot model IDs visible to the current auth context.

Each entry maps:

- a public model ID
- a runtime name
- an owner label
- a concrete runtime model identifier

In the current implementation, the public model ID and runtime model identifier are the same string.

`GET /openai/v1/models` and `GET /anthropic/v1/models` are therefore the canonical source-of-truth views for what callers may request through each public facade.

### 6.2 Model router

Implemented in `src/copilot_model_provider/core/routing.py`.

Behavior:

- validates a public model ID against the live model set for the current auth context
- resolves that model ID to `ResolvedRoute(runtime, runtime_model_id)`
- raises a structured `model_not_found` error for unknown model IDs
- produces the OpenAI-compatible `/openai/v1/models` payload from the catalog
- also supports Anthropic-compatible `/anthropic/v1/models` translation from the same live catalog
- caches auth-context-specific catalog snapshots for a short TTL so repeated requests do not rediscover the same upstream model set on every call
- coalesces concurrent requests for the same auth context so only one in-flight live-model discovery runs at a time

The shipped `ModelRouter` explicitly implements `ModelRouterProtocol` so the
composition root depends on a named routing contract rather than only on
structural compatibility.

The router is intentionally stateless:

- no provider-owned catalog mutation API exists
- no provider-owned alias layer exists on top of runtime model IDs
- no fallback or weighted routing logic exists

The cache is an implementation detail of discovery, not a provider-managed state surface:

- cache keys are derived from the auth context without persisting raw bearer tokens
- cache entries expire automatically and are rebuilt from the runtime on demand

## 7. Runtime Execution Model

### 7.1 Runtime type

The only shipped runtime is `CopilotRuntime` in `src/copilot_model_provider/runtimes/copilot_runtime.py`.

`CopilotRuntime` explicitly implements `RuntimeProtocol` from
`src/copilot_model_provider/runtimes/protocols/runtime.py`.

Its connection mode is always:

- `subprocess`

There is no separate external CLI runtime mode in the current implementation.

### 7.2 Session lifecycle

Execution is request-scoped and ephemeral.

For each request:

1. resolve the runtime client
2. start the client if needed
3. create a Copilot SDK session
4. execute the turn
5. disconnect the session
6. stop the client if the client was request-scoped

Consequences:

- no provider-managed session persistence
- no session resume path
- no provider-owned session locking
- no sticky routing requirement inside the provider itself

### 7.3 Default and authenticated clients

The runtime uses two client modes.

#### Shared default client

Used when no bearer token is present on the request and the runtime falls back to its configured auth context.

Behavior:

- created lazily
- cached on the runtime
- reused across unauthenticated requests

#### Request-scoped authenticated client

Used when a bearer token is present.

Behavior:

- built from `SubprocessConfig(github_token=...)`
- scoped to one request
- stopped after the request completes

This keeps runtime auth request-scoped without introducing provider-owned identity state.

### 7.4 Live model discovery

Implemented in `CopilotRuntime.list_model_ids()`.

Behavior:

- selects the same auth context that request execution would use
- starts the underlying Copilot client if needed
- calls `CopilotClient.list_models()`
- returns a stable, de-duplicated tuple of visible model IDs

### 7.5 Non-streaming execution

Implemented in `CopilotRuntime.complete_chat()`.

Behavior:

- sends the rendered prompt with `send_and_wait()`
- extracts assistant text and optional token metadata from the terminal event
- returns `RuntimeCompletion`

Structured failures include:

- `runtime_route_invalid`
- `runtime_timeout`
- `runtime_execution_failed`
- `runtime_empty_response`
- `runtime_invalid_response`
- `runtime_unhealthy`

### 7.6 Streaming execution

Implemented in `CopilotRuntime.stream_chat()`.

Behavior:

- sends the rendered prompt with `send()`
- subscribes to runtime events through `session.on(...)`
- yields raw SDK events until assistant turn end, session error, or session idle
- closes the session in a finalizer

## 8. Auth Model

### 8.1 Header normalization

Implemented in `src/copilot_model_provider/api/shared.py`.

Behavior:

- accepts `Authorization: Bearer <token>`
- returns the stripped token for runtime passthrough
- rejects malformed authorization headers with `invalid_authorization_header`

### 8.2 Auth scope

Current auth behavior is intentionally narrow:

- auth remains request/runtime-scoped, not conversation-scoped
- `Authorization: Bearer ...` is the highest-priority auth source for a request
- when the request omits `Authorization`, the service falls back to a host-resolved token injected into the container as `GITHUB_TOKEN` or `GH_TOKEN`
- bearer tokens are forwarded into the runtime layer only
- the provider does not persist raw bearer tokens
- the provider does not derive or store auth-subject fingerprints
- the provider does not implement a separate service-owned user/account system

### 8.3 Recommended deployment auth path

The recommended deployment flow is Docker-oriented:

1. authenticate on the host with `gh auth login`
2. obtain a token on the host with `gh auth token`
3. inject that token into the container as `GITHUB_TOKEN`

This keeps interactive OAuth outside the service container while still letting the
running provider construct request-scoped Copilot SDK clients. Request headers can
still override the container default on a per-request basis.

## 9. Streaming Behavior

### 9.1 Canonical stream translation

Implemented in `src/copilot_model_provider/streaming/translators.py`.

The provider translates Copilot SDK session events into a smaller canonical stream surface.

Handled event families:

- assistant text deltas
- aggregated assistant messages
- assistant turn completion
- session errors

Ignored event families:

- SDK events that are not part of the northbound text-stream contract

### 9.2 OpenAI chat SSE

Implemented in `src/copilot_model_provider/api/openai/chat.py` plus `streaming/sse.py`.

Behavior:

- emits OpenAI-compatible chat chunks
- emits the assistant role once at the start of the stream
- emits `[DONE]` at the end
- emits a structured error frame if a stream error is surfaced

### 9.3 Responses SSE

Implemented in `src/copilot_model_provider/api/openai/responses.py` plus `streaming/responses.py`.

Behavior:

- emits Responses lifecycle events such as:
  - `response.created`
  - `response.output_item.added`
  - `response.content_part.added`
  - `response.output_text.delta`
  - `response.content_part.done`
  - `response.output_item.done`
  - `response.completed`

### 9.4 De-duplication rule

Implemented in `src/copilot_model_provider/api/shared.py`.

The runtime may emit both text deltas and a later aggregated assistant message for the same turn. Once the provider has emitted delta text, it skips the later aggregated assistant message so clients do not display duplicated output.

## 10. Error Model

Structured provider errors are defined in `src/copilot_model_provider/core/errors.py`.

The design goal is that provider-owned failures surface as stable HTTP JSON errors rather than raw SDK exceptions.

Examples of stable error categories in the current implementation:

- `model_not_found`
- `invalid_authorization_header`
- `runtime_route_invalid`
- `runtime_timeout`
- `runtime_execution_failed`
- `runtime_empty_response`
- `runtime_invalid_response`
- `runtime_unhealthy`

## 11. Configuration Surface

Configuration is defined by `ProviderSettings` in `src/copilot_model_provider/config.py`.

Current environment-backed fields:

- `app_name`
- `environment`
- `server_host`
- `server_port`
- `enable_internal_health`
- `internal_health_path`
- `default_runtime`
- `runtime_timeout_seconds`
- `runtime_working_directory`
- `runtime_auth_token`

In addition to the provider-prefixed settings above, the service also recognizes
host-provided GitHub auth from `GITHUB_TOKEN` or `GH_TOKEN` as the default runtime
token source when `runtime_auth_token` is not explicitly configured.

Notably absent from the current implementation:

- no `runtime_cli_url`
- no MCP server configuration
- no session-store configuration
- no provider-owned auth/session binding configuration

## 12. Explicitly Deferred or Unsupported Scope

The current implementation does **not** provide these capabilities:

- provider-managed session persistence, resume, or locking
- auth-subject binding for conversation/session ownership
- server-side tool execution control planes
- MCP mounting or MCP tool execution
- external CLI runtime mode
- provider-native conversation/session APIs
- broader Anthropic compatibility features beyond the current models/messages/count-tokens surface
- multi-runtime fallback routing
- rate limiting, quotas, or billing
- advanced OpenAI compatibility features beyond the current thin chat/responses surface

This is intentional. The provider currently optimizes for a minimal, reliable, protocol-compatible surface over Copilot-backed execution.

## 13. Validation Strategy

The repository validates this design through multiple test layers.

### 13.1 Unit tests

Validate:

- normalization logic
- live model discovery and router behavior
- runtime behavior
- streaming translation helpers
- config validation

### 13.2 Contract tests

Validate:

- HTTP route shapes
- chat non-streaming and streaming behavior
- Responses non-streaming and streaming behavior
- structured auth and error handling

### 13.3 Container-backed integration tests

Validate:

- the built image
- real HTTP execution against the running provider container
- `/openai/v1/models`, `/anthropic/v1/models`, chat, and Responses behavior with real runtime auth

### 13.4 Opt-in live sweeps

Validate:

- one preferred visible live model through both chat and Responses in fast mode
- every currently visible live Copilot model when full mode is explicitly requested

These live sweeps are intentionally opt-in because they depend on real auth and are much slower than the default repository test path.

## 14. Key Implementation Files

Primary entrypoints and modules:

- `src/copilot_model_provider/app.py`
- `src/copilot_model_provider/config.py`
- `src/copilot_model_provider/server.py`
- `src/copilot_model_provider/logging_config.py`
- `src/copilot_model_provider/api/openai/models.py`
- `src/copilot_model_provider/api/anthropic/models.py`
- `src/copilot_model_provider/api/anthropic/protocol.py`
- `src/copilot_model_provider/api/openai/chat.py`
- `src/copilot_model_provider/api/openai/responses.py`
- `src/copilot_model_provider/api/shared.py`
- `src/copilot_model_provider/core/models.py`
- `src/copilot_model_provider/core/chat.py`
- `src/copilot_model_provider/core/responses.py`
- `src/copilot_model_provider/core/catalog.py`
- `src/copilot_model_provider/core/routing.py`
- `src/copilot_model_provider/core/errors.py`
- `src/copilot_model_provider/runtimes/protocols/runtime.py`
- `src/copilot_model_provider/runtimes/copilot_runtime.py`
- `src/copilot_model_provider/streaming/translators.py`
- `src/copilot_model_provider/streaming/sse.py`
- `src/copilot_model_provider/streaming/responses.py`

## 15. Design Summary

The current repository is best understood as:

- thin OpenAI-compatible and Anthropic-compatible HTTP facades
- a small internal normalization and routing layer
- a subprocess-backed Copilot SDK runtime
- a stateless provider with request-scoped auth passthrough

That narrower definition is the correct design baseline for the code currently shipped in `src/copilot_model_provider/`.
