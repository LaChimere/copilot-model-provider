# copilot-model-provider Design

## 1. Purpose

This document describes the **current implementation** in `src/copilot_model_provider/`.

It is intentionally implementation-first:

- it documents the behavior that is actually shipped on `main`
- it does **not** treat historical planning artifacts as normative
- it does **not** depend on or reference historical planning artifacts as design sources

At the time of writing, the repository implements a **thin, stateless, subprocess-backed OpenAI-compatible provider** on top of `github-copilot-sdk`.

## 2. System Overview

The service is a FastAPI application that exposes a small OpenAI-compatible HTTP surface and translates those requests into ephemeral Copilot SDK sessions.

The core design choice is to keep the provider layer intentionally thin:

- northbound compatibility happens over HTTP
- routing happens through a service-owned model catalog
- execution happens through `github-copilot-sdk`
- provider-owned conversation/session state is **not** persisted across requests
- server-side tools and MCP are **not** enabled

In practical terms, the provider behaves like a compatibility gateway plus a small amount of normalization and streaming translation, not like a provider-owned agent platform.

## 3. Implemented Surface

The service currently exposes these endpoints:

### 3.1 `GET /v1/models`

Implemented in `src/copilot_model_provider/api/openai_models.py`.

Behavior:

- lists the public model aliases exposed by the service-owned catalog
- returns an OpenAI-compatible model list response
- does not require runtime auth

### 3.2 `POST /v1/chat/completions`

Implemented in `src/copilot_model_provider/api/openai_chat.py`.

Behavior:

- accepts an OpenAI-compatible chat request
- supports non-streaming and streaming SSE responses
- resolves the requested public alias through the model router
- forwards optional bearer auth into the runtime layer

### 3.3 `POST /v1/responses`

Implemented in `src/copilot_model_provider/api/openai_responses.py`.

Behavior:

- accepts a thin OpenAI-compatible Responses subset intended for Codex-style clients
- supports non-streaming and streaming SSE responses
- reuses the same canonical chat/runtime path as `POST /v1/chat/completions`
- exposes Responses-specific lifecycle events for streaming

### 3.4 `GET /_internal/health`

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
- construct the model catalog and router
- install routes and error handlers
- optionally install the internal health endpoint

### 4.2 API layer

Implemented in `src/copilot_model_provider/api/`.

Responsibilities:

- parse HTTP requests
- normalize auth headers
- resolve public model aliases into runtime routes
- convert OpenAI-compatible requests into canonical internal requests
- format HTTP responses and SSE streams

### 4.3 Canonical core

Implemented in `src/copilot_model_provider/core/`.

Responsibilities:

- define internal request/response models
- normalize OpenAI chat and Responses requests
- render prompts for the runtime
- define the model catalog and model router
- translate runtime completions into northbound response shapes
- raise structured provider errors

### 4.4 Runtime layer

Implemented in `src/copilot_model_provider/runtimes/`.

Responsibilities:

- own the `github-copilot-sdk` integration
- create ephemeral Copilot sessions per request
- execute non-streaming and streaming turns
- translate raw runtime failures into provider errors
- deny runtime permission requests for tools/MCP

### 4.5 Streaming helpers

Implemented in `src/copilot_model_provider/streaming/`.

Responsibilities:

- translate Copilot SDK session events into canonical stream events
- translate canonical stream events into OpenAI-compatible chat chunks
- encode SSE frames for chat and Responses streaming

## 5. Request Normalization

### 5.1 Canonical request shape

The provider's shared execution path centers on `CanonicalChatRequest` in `src/copilot_model_provider/core/models.py`.

Current fields:

- `request_id`
- `conversation_id`
- `runtime_auth_token`
- `model_alias`
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

## 6. Routing and Model Catalog

### 6.1 Service-owned model catalog

Implemented in `src/copilot_model_provider/core/catalog.py`.

The default catalog is intentionally small and stable.

Shipped aliases:

- `default`
- `fast`

Each alias maps to:

- a runtime name
- an owner label
- a concrete runtime model identifier

For the default shipped catalog, those runtime model identifiers are built from the configured runtime name:

- `copilot-default`
- `copilot-fast`

### 6.2 Model router

Implemented in `src/copilot_model_provider/core/routing.py`.

Behavior:

- resolves a public alias to a `ResolvedRoute(runtime, runtime_model_id)`
- raises a structured `model_not_found` error for unknown aliases
- produces the OpenAI-compatible `/v1/models` payload from the catalog

The router is intentionally static:

- no dynamic catalog mutation API exists
- no runtime-side model discovery is exposed through the default public catalog
- no fallback or weighted routing logic exists

## 7. Runtime Execution Model

### 7.1 Runtime type

The only shipped runtime is `CopilotRuntime` in `src/copilot_model_provider/runtimes/copilot_runtime.py`.

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

Used when no bearer token is present.

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

### 7.4 Non-streaming execution

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

### 7.5 Streaming execution

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

- auth is request-scoped, not conversation-scoped
- bearer tokens are forwarded into the runtime layer only
- the provider does not persist raw bearer tokens
- the provider does not derive or store auth-subject fingerprints
- the provider does not implement a separate service-owned user/account system

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

Implemented in `src/copilot_model_provider/api/openai_chat.py` plus `streaming/sse.py`.

Behavior:

- emits OpenAI-compatible chat chunks
- emits the assistant role once at the start of the stream
- emits `[DONE]` at the end
- emits a structured error frame if a stream error is surfaced

### 9.3 Responses SSE

Implemented in `src/copilot_model_provider/api/openai_responses.py` plus `streaming/responses.py`.

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
- Anthropic-compatible facade
- multi-runtime fallback routing
- rate limiting, quotas, or billing
- advanced OpenAI compatibility features beyond the current thin chat/responses surface

This is intentional. The provider currently optimizes for a minimal, reliable, OpenAI-compatible surface over Copilot-backed execution.

## 13. Validation Strategy

The repository validates this design through multiple test layers.

### 13.1 Unit tests

Validate:

- normalization logic
- catalog/router behavior
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
- `/v1/models`, chat, and Responses behavior with real runtime auth

### 13.4 Opt-in live sweeps

Validate:

- the shipped `default` alias through both chat and Responses in fast mode
- every currently visible live Copilot model when full mode is explicitly requested

These live sweeps are intentionally opt-in because they depend on real auth and are much slower than the default repository test path.

## 14. Key Implementation Files

Primary entrypoints and modules:

- `src/copilot_model_provider/app.py`
- `src/copilot_model_provider/config.py`
- `src/copilot_model_provider/api/openai_models.py`
- `src/copilot_model_provider/api/openai_chat.py`
- `src/copilot_model_provider/api/openai_responses.py`
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

- a thin OpenAI-compatible HTTP facade
- a small internal normalization and routing layer
- a subprocess-backed Copilot SDK runtime
- a stateless provider with request-scoped auth passthrough

That narrower definition is the correct design baseline for the code currently shipped in `src/copilot_model_provider/`.
