# copilot-model-provider Design

## 1. Problem Statement

We want a **general-purpose model provider** built on top of `copilot-sdk` that can serve multiple clients and interaction styles, including:

- Codex-style apps
- Claude Code style clients
- CLI tools
- agent frameworks
- IDE integrations
- internal platform services

The provider should offer a stable northbound API while using `copilot-sdk` as the primary **agent runtime and model execution substrate**, rather than treating it as a thin stateless completion library.

## 2. Executive Summary

This project should be designed as a **compatibility gateway + routing layer + Copilot runtime adapter**.

At a high level:

1. **Northbound compatibility layer**
   exposes OpenAI-compatible HTTP APIs first, with optional additional provider-native or Anthropic-compatible APIs later.
2. **Canonical core**
   normalizes requests, model metadata, capabilities, streaming events, tools, and session lifecycle.
3. **Southbound runtime adapters**
   translate canonical requests to runtime-specific execution engines. The first and primary adapter is `copilot-sdk`.

The most important design choice is to model **sessions, tools, streaming events, and policy** as first-class concepts. This follows the architecture and operating model of the official `copilot-sdk`, which is deeply session-oriented and agent-oriented rather than purely stateless completion-oriented. [R1][R2][R6][R7]

### 2.1 Feasibility and compatibility boundaries

After validating the relevant client and SDK documentation, the overall design is feasible, but only if we treat "client compatibility" as a **multi-protocol integration problem**, not as a single universal HTTP endpoint.

Compatibility by client class:

- **Codex-style apps and OpenAI-style clients:** feasible through an OpenAI-compatible facade. The Codex configuration model explicitly supports `openai_base_url` as well as custom `model_providers` with configurable `base_url`, `wire_api`, headers, and query params. Official OpenAI SDKs also support custom `base_url` / `baseUrl`. [R11][R12][R13]
- **Claude Code style clients:** feasible, but not through an OpenAI facade alone. Claude Code's gateway documentation requires an Anthropic-compatible interface, most importantly `/v1/messages` and `/v1/messages/count_tokens`, with correct forwarding of `anthropic-version` and `anthropic-beta` headers. [R14][R15]
- **General CLI tools, agent frameworks, and internal platform services:** generally feasible when the caller can set a custom base URL, supply custom headers, or use its own SDK client configuration. In practice, these are the easiest classes to support because they usually control their own transport configuration. [R12][R13][R14]
- **IDE integrations:** partially feasible, but the support surface depends on the IDE product. VS Code's BYOK and Language Model Chat Provider ecosystem can expose custom models and OpenAI-compatible chat endpoints, but the current documented experience is focused on chat/model-provider integration rather than arbitrary completions replacement. The VS Code team explicitly notes that BYOK does not currently work with completions. [R16][R17]
- **GitHub Copilot enterprise custom models:** feasible through Copilot's own BYOK/custom model controls, but that is a separate product integration path from exposing our own standalone gateway to arbitrary IDE clients. It validates that OpenAI-compatible providers and custom models are operationally supported in the Copilot ecosystem, but it should not be confused with universal client-level custom endpoint support. [R17]

The practical implication is:

1. We should definitely build an **OpenAI-compatible facade** for Codex-style and OpenAI-style clients.
2. We should plan a separate **Anthropic Messages facade** for Claude Code compatibility.
3. We should keep room in the overall architecture for a **provider-native session-oriented API** for internal workflows, richer event streams, and clients that benefit from explicit session control.
4. We should avoid over-promising support for every official IDE completion surface unless that client is documented to allow custom providers or custom chat model extensions.

## 3. Goals

- Provide one stable service with the right protocol facades for multiple downstream clients.
- Reuse `copilot-sdk` for model execution, tools, MCP integration, streaming, and session persistence.
- Support both stateless and stateful interaction patterns.
- Allow model aliasing, routing, and policy enforcement independent of the downstream client.
- Make tools and MCP available through a unified control plane.
- Support backend deployment topologies suitable for internal tools and multi-tenant services.

## 4. Non-Goals

- Reimplement the Copilot CLI runtime.
- Build a full universal LLM abstraction that erases all provider differences.
- Promise perfect wire-level compatibility with every OpenAI- or Anthropic-compatible client on day one.
- Build a collaborative multi-user shared-session product in MVP.
- Replace specialized orchestration systems for large-scale multi-agent workflows.

## 5. Key Findings from `copilot-sdk`

The design is grounded in these characteristics of the official repo:

### 5.1 SDK architecture is runtime-oriented

All SDKs talk to the Copilot CLI server over JSON-RPC. The SDK manages the CLI process lifecycle automatically, or can connect to an externally managed headless CLI server. [R1][R3][R10]

Implication:

- We should treat `copilot-sdk` as an **execution runtime**.
- The provider service should usually connect to a persistent headless CLI, not spawn a CLI process per request.

### 5.2 Sessions are first-class

`create_session(...)` and `resume_session(...)` are the primary interaction model. Sessions persist planning state, conversation history, tool results, and artifacts to disk under `~/.copilot/session-state/{sessionId}/`. [R7][R10]

Implication:

- The provider must model **conversation/session identity** explicitly.
- A stateless request API can be offered, but it should be implemented on top of ephemeral sessions or short-lived mapped sessions.

### 5.3 The SDK already exposes major extension points

The Python SDK supports:

- `provider` for BYOK/custom endpoints
- `streaming`
- `tools`
- `available_tools` and `excluded_tools`
- `hooks`
- `mcp_servers`
- `custom_agents`
- `agent`
- `skill_directories`
- `disabled_skills`
- `infinite_sessions`
- `set_model(...)` on a live session [R2][R5][R6][R8][R9]

Implication:

- The provider should **not** flatten all of these into a raw prompt proxy.
- The provider should preserve them through a canonical internal model.

### 5.4 Model listing is customizable

`CopilotClient` supports `on_list_models`, which can fully replace the CLI-side `models.list` RPC. The results are cached after first call. [R5][R9]

Implication:

- We can build a custom model catalog and expose it consistently across clients.
- Alias models and policy-filtered models should be generated by our own catalog layer, not inferred ad hoc from the runtime.

### 5.5 Streaming is richer than token deltas

The SDK emits many event types, including:

- `assistant.message_delta`
- `assistant.reasoning_delta`
- `assistant.message`
- `tool.execution_start`
- `tool.execution_partial_result`
- `tool.execution_progress`
- `tool.execution_complete`
- `external_tool.requested`
- `external_tool.completed`
- `session.idle`
- `session.error` [R6]

Implication:

- Streaming translation should be event-based, not text-only.
- The provider should define a canonical event stream and then translate it into OpenAI-style SSE, Anthropic-style streaming, or internal websocket/event feeds.

### 5.6 Backend deployment and scaling constraints are explicit

The official docs call out:

- headless CLI deployment for backends
- file-based session state
- no built-in session locking
- no built-in load balancing
- 30-minute idle cleanup
- shared storage requirement for resumable sessions across multiple CLI servers [R3][R4][R7]

Implication:

- Session locking, routing, cleanup, sticky sessions, and storage strategy must be implemented at our provider layer or deployment layer.

## 6. Design Principles

1. **Session-first, not completion-first**
   The internal model must respect the runtime's stateful nature.

2. **Compatibility outside, capability-aware inside**
   Northbound APIs can be familiar, but the core should not pretend all backends are equivalent.

3. **Canonical event model**
   Streaming, tools, and reasoning should have one internal representation.

4. **Runtime adapters, not provider-specific sprawl**
   Add new runtimes behind adapter boundaries.

5. **Policy and routing belong above the runtime**
   Access control, quota, allowlists, and model aliasing should be service-managed.

6. **Operationally safe defaults**
   Prefer explicit session ownership, sticky routing, cleanup, and persistent storage over magical behavior.

## 7. Proposed Architecture

```text
Clients
  |- Codex app / OpenAI clients
  |- Claude Code-like clients
  |- CLI / IDE / agent tools
  v
Northbound Compatibility Layer
  |- OpenAI API facade
  |- Anthropic facade (optional)
  |- Native provider API (optional)
  v
Canonical Core
  |- Request normalizer
  |- Model catalog
  |- Router
  |- Session manager
  |- Tool registry
  |- Policy engine
  |- Event translator
  |- Audit / telemetry
  v
Runtime Adapters
  |- CopilotRuntimeAdapter (MVP)
  |- OpenAIRuntimeAdapter (future)
  |- AnthropicRuntimeAdapter (future)
  |- Ollama/LiteLLM adapter (future)
  v
copilot-sdk -> Copilot CLI (headless) -> Copilot or BYOK provider
```

## 8. Component Design

### 8.1 Northbound Compatibility Layer

Recommended initial endpoints for the current MVP path:

- `GET /v1/models`
- `POST /v1/chat/completions`

Implemented compatibility extension after the MVP baseline stabilized:

- `POST /v1/responses` as a thin OpenAI-compatible Responses surface for Codex-style clients

Optional later:

- `POST /provider/v1/conversations`
- `POST /provider/v1/conversations/{id}/messages`
- `POST /anthropic/v1/messages`

Responsibilities:

- request credential extraction / passthrough and optional tenant resolution
- request validation
- compatibility translation
- SSE framing
- error normalization

Important note:

Wire compatibility should be treated as **best-effort compatibility with a documented supported subset**, not as an unbounded commitment to every provider extension.

### 8.2 Canonical Request Model

Define one internal request model, for example:

```text
ModelRequest
  - tenant_id
  - user_id
  - app_id
  - conversation_id
  - request_id
  - model_alias
  - messages[]
  - attachments[]
  - tools[]
  - tool_choice
  - stream
  - reasoning_effort
  - metadata
  - execution_mode: stateless | sessional
```

Key idea:

- `model_alias` is what clients ask for.
- The router resolves it to a runtime target and policy.

### 8.3 Canonical Response and Event Model

Define one internal response/event model:

```text
ModelEvent
  - type
  - request_id
  - conversation_id
  - message_id
  - tool_call_id
  - payload
  - timestamp
```

Suggested internal event types:

- `message.delta`
- `message.completed`
- `reasoning.delta`
- `reasoning.completed`
- `tool.call.requested`
- `tool.call.started`
- `tool.call.delta`
- `tool.call.completed`
- `session.idle`
- `session.error`

This maps cleanly from the Copilot SDK event model. [R6]

### 8.4 Model Catalog

The model catalog should be service-owned.

Each catalog entry should include:

- `alias`
- `display_name`
- `runtime`
- `runtime_model_id`
- `provider_config_ref`
- `capabilities`
- `limits`
- `reasoning_defaults`
- `policy`
- `billing_class`
- `visibility`

Example:

```yaml
- alias: claude-code-default
  runtime: copilot
  runtime_model_id: claude-sonnet-4.5
  provider_config_ref: anthropic-prod
  capabilities:
    vision: true
    reasoning_effort: false
    tools: true
    mcp: true
  policy:
    tenants: ["internal", "design-partners"]
    allow_builtin_tools: ["view", "glob", "grep"]
```

Why this matters:

- `copilot-sdk` supports `on_list_models`, so our catalog can fully define what is exposed northbound. [R5][R9]
- Different clients may need different visible aliases even if they route to the same underlying runtime model.

### 8.5 Router

The router resolves a canonical request into an execution target:

```text
ResolvedRoute
  - runtime = copilot
  - cli_pool = shared or isolated
  - runtime_model_id
  - provider_config
  - built_in_tools_policy
  - mcp_mounts
  - skills
  - session_mode
```

Routing inputs:

- tenant
- user
- app
- requested model alias
- required capabilities
- data residency/policy
- budget/quota

The first router should be deterministic and policy-driven. Fallback chains can be added later.

### 8.6 Session Manager

This is one of the most important components.

Responsibilities:

- map external `conversation_id` to internal Copilot `session_id`
- decide create vs resume
- enforce ownership and tenant isolation
- implement session locking
- manage lifecycle and cleanup

Recommended ID format:

```text
tenant-{tenant_id}-user-{user_id}-app-{app_id}-conv-{conversation_id}
```

This follows the official guidance that structured session IDs simplify audit and cleanup. [R7]

Session modes:

- **ephemeral**
  create session, send request, disconnect immediately
- **persistent**
  create/resume named session, preserve history and tool context

Locking:

- Use Redis-based locks for any operation that can mutate the same session concurrently.
- This is required because official docs explicitly state there is no built-in session locking. [R4][R7]

### 8.7 Tool Registry and MCP Control Plane

Tool sources should be separated conceptually:

1. **Client-declared tools**
   tools provided by the caller's request.
2. **Server-mounted tools**
   tools owned by the provider service.
3. **MCP tools**
   tools exposed through local or HTTP MCP servers. [R8]

Canonical tool descriptor:

```text
ToolDescriptor
  - name
  - description
  - schema
  - source = client | server | mcp
  - permission_mode
  - override_builtin
```

Mapping to `copilot-sdk`:

- client/server custom tools -> `tools`
- built-in tool policy -> `available_tools` / `excluded_tools`
- MCP mounts -> `mcp_servers`

Permission control:

- use `on_permission_request`
- use hooks such as `on_pre_tool_use` / `on_post_tool_use` for allow/deny, redaction, audit, and transformation [R2][R9]

### 8.8 Copilot Runtime Adapter

This is the core MVP adapter.

Responsibilities:

- manage `CopilotClient` lifecycle
- connect to external headless CLI where possible [R3]
- create or resume sessions
- translate provider config for BYOK
- attach tools, hooks, MCP, skills, agent config
- forward streaming events
- map canonical errors to provider errors

Key adapter methods:

```text
list_models()
get_or_create_session()
send()
send_stream()
set_model()
disconnect_session()
delete_session()
```

Important SDK details to honor:

- `on_permission_request` is required when creating/resuming sessions in Python SDK tests and API surface. [R5]
- `list_models()` is cached and can be replaced by custom `on_list_models`. [R5][R9]
- `set_model()` exists on the session and should be used when changing models in a live conversation. [R5]

### 8.9 Streaming Translator

Streaming translation should be layered:

1. `copilot-sdk` event stream
2. canonical internal event stream
3. output protocol encoder

Example mappings:

| Copilot event | Canonical event | OpenAI-style stream |
|---|---|---|
| `assistant.message_delta` | `message.delta` | text delta chunk |
| `assistant.reasoning_delta` | `reasoning.delta` | reasoning delta or vendor extension |
| `tool.execution_start` | `tool.call.started` | tool call chunk / internal event |
| `tool.execution_partial_result` | `tool.call.delta` | optional internal event |
| `assistant.message` | `message.completed` | final content chunk |
| `session.idle` | `session.idle` | `[DONE]` or terminal event |

Not every downstream protocol can represent every internal event exactly. In those cases:

- preserve fidelity internally
- degrade gracefully on the public wire
- optionally provide a richer native event stream later

### 8.10 Policy Engine

The policy engine sits above the runtime and below the external API.

Responsibilities:

- model allow/deny
- tool allow/deny
- MCP allow/deny
- rate limits and quotas
- tenant scoping
- audit requirements
- prompt attachment restrictions

Recommended policy levels:

- tenant policy
- application policy
- route policy
- request policy

Where enforced:

- before route resolution
- before session resume
- before tool execution
- after tool execution for result scrubbing

### 8.11 Observability and Audit

Minimum observability:

- request logs
- session lifecycle logs
- model selection logs
- tool execution logs
- latency/error metrics
- active session count
- CLI health status

For this repository, the application logger can be implemented with `structlog` so request-, session-, and tool-scoped events remain consistently structured and easy to route into downstream log pipelines.

The official SDK docs also describe OpenTelemetry support and trace propagation in the client. That should be preserved where practical. [R2]

Recommended correlation identifiers:

- `request_id`
- `conversation_id`
- `copilot_session_id`
- `tenant_id`
- `tool_call_id`

## 9. Deployment Topologies

### 9.1 Recommended MVP: Shared CLI with sticky session routing

Use one or more headless CLI servers and a shared provider API layer.

Pros:

- simple
- low resource overhead
- good enough for internal tools

Cons:

- requires application-level ownership enforcement
- requires locking and careful session cleanup

This follows the official backend-services and scaling guidance. [R3][R4]

### 9.2 Strong-isolation topology: CLI per tenant or per user

Recommended for:

- multi-tenant SaaS
- compliance-sensitive workloads
- per-user auth credentials

Pros:

- better isolation
- simpler reasoning about storage and ownership

Cons:

- more expensive
- more operational complexity

Also explicitly supported by official scaling guidance. [R4]

### 9.3 Shared storage

If sessions must survive failover across CLI servers, mount shared persistent storage for the session-state directory. [R4][R7]

Without shared storage, use sticky routing instead.

### 9.4 Containerized backend deployment

For production-oriented deployment, follow the official backend-services guidance and treat the SDK as a client that connects to an independently managed **headless Copilot CLI server** over `cliUrl`, rather than spawning a child CLI process inside request handling. [R3]

This repository's current packaging baseline now exposes that contract through `ProviderSettings.runtime_cli_url` (environment variable: `COPILOT_MODEL_PROVIDER_RUNTIME_CLI_URL`), `ProviderSettings.server_host`, and `ProviderSettings.server_port`. The repository now includes a production-image baseline (`Dockerfile`, `.dockerignore`) and a formal package entrypoint (`copilot-model-provider`) that starts the FastAPI app through `uvicorn` and `copilot_model_provider.app:create_app --factory`.

Recommended default container topology for this repository:

- one provider API container with a formal ASGI server entrypoint
- one headless Copilot CLI container or sidecar
- private network connectivity only between the API and the CLI
- a persistent volume for the CLI session-state directory
- request-scoped GitHub bearer-token passthrough, plus secret injection for any BYOK credentials

Image/startup smoke for the current baseline is:

- `docker build -t copilot-model-provider:step6-smoke .`
- `docker run -p 18080:8000 -e COPILOT_MODEL_PROVIDER_RUNTIME_CLI_URL=http://copilot-cli.internal:3000 copilot-model-provider:step6-smoke`
- `GET /_internal/health` returns `200 OK`

Important operational implications:

- do **not** rely on interactive CLI login or system keychain state inside a production image
- for a single replica, a local persistent volume can be enough for CLI session state
- for multiple replicas, choose either sticky routing or shared storage for CLI session state [R4]
- if the provider API itself maintains session maps or locks, move those off node-local files before claiming multi-replica production readiness
- subject-bound session resume is now enforced by storing only an auth-subject fingerprint derived from the presented bearer token, never the raw token itself
- readiness should cover both provider health and CLI reachability, while keeping the CLI transport internal-only

## 10. Security Considerations

### 10.1 Authentication

Possible runtime credential modes:

- caller-supplied GitHub bearer token
- caller-supplied GitHub bearer token obtained through OAuth
- service-level GitHub token for server-to-server scenarios
- BYOK provider credentials [R1][R3][R5]

Preferred baseline for this repository:

- callers supply a GitHub bearer token directly, or obtain one through GitHub OAuth and forward it per request
- the provider treats that token as runtime credential material for Copilot execution, not as the basis for its own user/account system
- BYOK credentials remain a separate optional runtime/provider concern

Provider design recommendation:

- do **not** build a separate service-owned identity system for the MVP baseline
- keep any optional caller auth layer separate from runtime credential passthrough
- store BYOK secrets in a secret manager
- never persist raw GitHub bearer tokens or API keys in session storage
- sessional resume is now bound to the stored bearer-token subject fingerprint so one caller cannot resume another caller's Copilot session
- switching auth mode (anonymous vs bearer) or switching bearer tokens should start a new conversation ID rather than attempting to resume the old conversation
- in production containers, prefer request-scoped GitHub bearer-token passthrough and injected BYOK credentials over interactive logged-in-user credentials [R1][R3][R5]

Current implementation caveat:

- request-scoped GitHub bearer-token passthrough is implemented for subprocess-backed Copilot clients
- when `runtime_cli_url` points to an external headless CLI server, the provider rejects request-scoped GitHub bearer-token passthrough explicitly because the current `github-copilot-sdk` surface exposes `github_token` only on `SubprocessConfig`, not on `ExternalServerConfig`
- operator guidance: use subprocess mode for per-request GitHub bearer tokens; reserve `runtime_cli_url` for pre-authenticated or service-scoped external CLI deployments

This is especially important because the official docs note that BYOK provider credentials are **not persisted** and must be re-supplied on resume. [R5][R7]

### 10.2 Network boundaries

Official docs note there is no built-in auth between SDK and CLI when using external headless CLI. [R3]

Therefore:

- keep API and CLI on the same host, private subnet, or service mesh
- do not expose the CLI server publicly
- treat CLI transport as internal-only

### 10.3 Tool safety

Tools are a major part of the risk surface.

Use:

- `available_tools` / `excluded_tools`
- `on_permission_request`
- hooks for pre/post tool policy [R2][R9]

Start with read-only defaults in lower-trust deployments.

## 11. API Strategy

### 11.1 Supported northbound surface for MVP

- `GET /v1/models`
- `POST /v1/chat/completions`
- SSE streaming for chat completions
- thin OpenAI-compatible `POST /v1/responses` support for Codex-style clients
- The current MVP baseline still defers provider-native session APIs and any separate provider-native response-style API family until after the compatibility APIs are stable.

### 11.2 Session-aware extensions

Because `copilot-sdk` is stateful, a provider-native session API is still valuable:

- `POST /provider/v1/conversations`
- `POST /provider/v1/conversations/{id}/messages`
- `GET /provider/v1/conversations/{id}`
- `DELETE /provider/v1/conversations/{id}`

This allows us to expose stateful behavior cleanly without forcing every concept through stateless OpenAI-style shapes.

## 12. MVP Scope

### In scope

- FastAPI service
- OpenAI-compatible `/v1/models`
- OpenAI-compatible `/v1/chat/completions`
- thin OpenAI-compatible `/v1/responses`
- canonical model catalog
- Copilot runtime adapter
- session create/resume mapping
- streaming translation
- basic tool support
- basic MCP mounting
- policy enforcement for built-in tools
- sticky session routing or single shared CLI

Current implementation status:

- basic tool support, basic MCP mounting, policy-controlled approval, and the remaining routing/policy release-gate scenario are all now implemented on `main`
- the documented MVP release gate now has focused coverage for `/v1/models`, non-streaming chat, streaming, tool flow, persistent resume, and routing/policy behavior
- containerized deployment and the production-oriented packaging baseline are now implemented on `main`
- the thin `/v1/responses` compatibility surface is also implemented on `main` and validated against Docker-backed Codex traffic

### Out of scope

- complete Anthropic compatibility
- multi-runtime fallback routing
- collaborative shared sessions
- advanced quota billing engine
- admin UI
- cross-region active-active session mobility

### Operationalization follow-on

After the functional MVP, the next tracked extension should package the provider for containerized deployment:

- add a formal server entrypoint for the FastAPI service
- build a provider API image intended to connect to an external headless CLI server
- document the default API-container + CLI-container topology
- define persistent session-state storage, internal CLI networking, and secret-injection requirements before claiming production readiness

## 13. Validation Strategy and Real-Client Test Scenarios

Unit tests and adapter-level tests are necessary, but they are not sufficient for this project.

Because the provider is meant to serve clients that behave like Codex apps, coding CLIs, and agent-capable IDE tooling, we also need **end-to-end validation scenarios that exercise the service through real client request patterns**, especially:

- streaming
- session reuse
- tool calling
- model routing
- error handling under compatibility APIs

The goal is to verify not only correctness of response payloads, but also whether the provider feels correct when used from a real interactive client.

### 13.1 Test Layers

Recommended validation pyramid:

1. **Pure unit tests**
   request normalization, routing rules, model catalog behavior, event translation, and policy decisions.

2. **Adapter integration tests**
   `CopilotRuntimeAdapter` tests against a local or test headless CLI, validating `create_session`, `resume_session`, `send`, streaming, tools, and model switching. These directly exercise the SDK/session APIs described in the official docs. [R2][R6][R7]

3. **HTTP contract tests**
   verify northbound API behavior for `/v1/models` and `/v1/chat/completions`, plus any optional provider-native endpoints we choose to add later.

4. **Real-client E2E scenarios**
   run the provider as a service and exercise it the way downstream clients actually behave.

### 13.2 Why Real-Client E2E Matters

The official Copilot SDK runtime is:

- stateful through sessions [R7]
- event-driven during streaming [R6]
- tool-capable through built-in tools, custom tools, and MCP [R2][R8][R9]

That means many failures will only show up when the system is used in a realistic client loop, for example:

- a client expects stable SSE framing during long streaming responses
- a tool call arrives mid-stream and the compatibility layer encodes it incorrectly
- a second turn accidentally creates a new session instead of resuming the existing one
- model aliasing works for `/v1/models` but routes incorrectly during actual execution

### 13.3 Core Real-Client Scenarios

The following scenarios should be treated as required acceptance tests for MVP.

#### Scenario A: Stateless chat completion from an OpenAI-style client

Purpose:

- validate the compatibility layer for the simplest request path

Flow:

1. Start the provider service.
2. Send a single-turn `POST /v1/chat/completions` request from an OpenAI-compatible client.
3. Assert:
   - the response schema is valid
   - the requested alias resolves to the expected runtime model
   - no persistent conversation is created unless configured

This is the basic "Codex app or CLI asks one question" smoke path.

#### Scenario B: Streaming chat completion with incremental output

Purpose:

- validate SSE framing and event translation

Flow:

1. Send a streaming request to `/v1/chat/completions`.
2. Assert:
   - text deltas arrive incrementally
   - stream termination is correct
   - provider logs show a matching canonical event sequence
   - no dropped chunks occur when the assistant produces multiple deltas

This directly validates the mapping from Copilot session events such as `assistant.message_delta` and `session.idle`. [R6]

#### Scenario C: Tool-calling request from a CLI-style coding client

Purpose:

- verify that the provider correctly supports tool schemas and tool execution flow

Flow:

1. Start the provider with a small approved tool set or MCP mount.
2. Use a prompt that reliably requires a tool invocation.
3. Assert:
   - the tool call is represented correctly on the northbound wire
   - the provider enforces permissions correctly
   - tool completion is reflected back into the final assistant response

This scenario is important because coding-oriented clients frequently depend on tools rather than plain text completion. It validates the adapter's use of `tools`, `available_tools`, `excluded_tools`, `on_permission_request`, and hooks. [R2][R9]

#### Scenario D: Persistent multi-turn conversation

Purpose:

- verify conversation identity and session reuse

Flow:

1. Create or select a provider-native `conversation_id`.
2. Send a first request that establishes context.
3. Send a second request that refers back to previous context.
4. Assert:
   - the second request resumes the same Copilot session
   - previous context is preserved
   - the session mapping is stable across requests

This validates the provider's session manager against the Copilot SDK's `create_session(...)` and `resume_session(...)` model. [R7]

#### Scenario E: Resume after process restart

Purpose:

- verify persistent session storage assumptions

Flow:

1. Create a persistent conversation.
2. Stop the provider API process.
3. Restart the provider while preserving backing CLI session state.
4. Send another message into the same conversation.
5. Assert:
   - the session resumes correctly
   - prior context is still available
   - no duplicate session is created

This is especially important if we rely on shared storage or sticky routing, since the Copilot session state is file-based. [R4][R7]

#### Scenario F: Model alias and routing verification

Purpose:

- verify that the catalog and router behave correctly under real requests

Flow:

1. Configure at least two aliases that route differently.
2. Call `/v1/models` and verify both are advertised as expected.
3. Execute requests against each alias.
4. Assert:
   - the correct runtime model is chosen
   - reasoning-effort and capability policy are applied correctly
   - policy-restricted aliases fail cleanly when accessed by the wrong tenant/app

This validates the custom model catalog strategy and `on_list_models`-style behavior described in the SDK docs. [R2][R5]

#### Scenario G: MCP-backed tool path

Purpose:

- verify that MCP tool mounting works end to end

Flow:

1. Mount a known MCP server through provider configuration.
2. Send a request that requires that MCP tool.
3. Assert:
   - the tool is available to the session
   - the runtime invokes the MCP tool
   - partial/progress/final tool events are handled correctly

This validates the part of the design that depends on `mcp_servers`. [R8]

### 13.4 Codex-App-or-CLI Style Acceptance Profiles

Since the exact downstream clients may vary over time, we should define **behavioral profiles** rather than tie validation only to one brand or binary.

#### Profile 1: OpenAI-compatible interactive client

Characteristics:

- calls `/v1/models`
- uses `/v1/chat/completions`
- may use `/v1/responses` when the client prefers the Responses wire surface
- may enable streaming
- may be mostly stateless

Representative uses:

- Codex-like apps
- generic coding assistants built on OpenAI wire compatibility

#### Profile 2: Coding CLI client

Characteristics:

- may stream aggressively
- may depend on tool calls
- may prefer `wire_api = "responses"` and use `/v1/responses`
- may send long prompts and iterative turns
- often expects deterministic error shapes and low-latency chunk delivery

Representative uses:

- CLI coding agents
- terminal pair-programming tools

#### Profile 3: Session-oriented agent client

Characteristics:

- expects conversation continuity
- may switch models within a workflow
- may rely on MCP and tool permissions

Representative uses:

- IDE-side agents
- workflow automation services

Each release candidate should pass at least one scenario from each profile.

### 13.5 Suggested E2E Harness Approach

To keep validation practical, build a small test harness with:

- provider startup helper
- test CLI/headless Copilot runtime configuration
- fixture model aliases
- fixture custom tool and MCP server
- HTTP client wrappers for:
  - `/v1/models`
  - `/v1/chat/completions`
- SSE stream collector
- session/conversation assertion helpers

The harness should support both:

- **synthetic HTTP E2E**
  where we emulate the requests a Codex app or coding CLI would send
- **real client smoke tests**
  where feasible, against an actual compatible client configured to point at this provider

For early MVP, synthetic HTTP E2E is acceptable as long as the requests mirror real client behavior closely.

### 13.6 Minimum Release Gate for MVP

Before calling the provider MVP-ready, require all of the following to pass:

1. `/v1/models` returns the expected aliases.
2. one non-streaming chat completion scenario passes.
3. one streaming scenario passes without dropped chunks.
4. one tool-calling scenario passes.
5. one persistent conversation resume scenario passes.
6. one routing/policy scenario passes.

If any of these fail, the issue should be treated as a product-level incompatibility, not merely a test failure.

## 14. Suggested Repository Structure

```text
docs/
  design.md

src/
  copilot_model_provider/
    app.py
    config.py
    api/
      openai_models.py
      openai_chat.py
      openai_responses.py
      provider_conversations.py
    core/
      models.py
      events.py
      routing.py
      policies.py
      catalog.py
      sessions.py
      errors.py
      responses.py
    runtimes/
      base.py
      copilot.py
    streaming/
      sse.py
      translators.py
      responses.py
    tools/
      registry.py
      mcp.py
    storage/
      session_map.py
      locks.py
```

## 15. Open Questions

These should be resolved before implementation moves beyond MVP:

1. Beyond the implemented thin OpenAI-compatible `/v1/responses` route, do we also want a separate provider-native response-style API family? (Current baseline: later phase.)
2. Do provider-native session APIs ship in MVP, or do they land in a later phase after the compatibility APIs? (Current baseline: later phase after the compatibility APIs.)
3. What isolation level is required initially: shared CLI, per-tenant CLI, or per-user CLI?
4. Will external callers be allowed to declare arbitrary tools, or only choose from approved tool packs? (Current baseline: approved tool packs only.)
5. Should model aliases be global, tenant-scoped, or app-scoped?
6. Do we need durable request logs and tool transcripts for audit on day one?

## 16. Recommendation

Build the provider as a **stateful compatibility gateway** over `copilot-sdk`, with `copilot-sdk` serving as the primary runtime adapter.

Do not design it as a generic stateless prompt proxy.

The official SDK's strengths are:

- session lifecycle
- agent runtime
- streaming events
- tools
- MCP
- hooks
- persistence
- dynamic model listing and switching

The architecture should embrace those strengths instead of hiding them, and the validation plan should test them through real client interaction patterns rather than adapter-only mocks.

## 17. References

- [R1] GitHub Copilot SDK repository root README  
  https://github.com/github/copilot-sdk/blob/main/README.md

- [R2] Copilot Python SDK README  
  https://github.com/github/copilot-sdk/blob/main/python/README.md

- [R3] Backend Services Setup  
  https://github.com/github/copilot-sdk/blob/main/docs/setup/backend-services.md

- [R4] Scaling & Multi-Tenancy  
  https://github.com/github/copilot-sdk/blob/main/docs/setup/scaling.md

- [R5] BYOK (Bring Your Own Key)  
  https://github.com/github/copilot-sdk/blob/main/docs/auth/byok.md

- [R6] Streaming Session Events  
  https://github.com/github/copilot-sdk/blob/main/docs/features/streaming-events.md

- [R7] Session Resume & Persistence  
  https://github.com/github/copilot-sdk/blob/main/docs/features/session-persistence.md

- [R8] Using MCP Servers with the GitHub Copilot SDK  
  https://github.com/github/copilot-sdk/blob/main/docs/features/mcp.md

- [R9] Working with Hooks  
  https://github.com/github/copilot-sdk/blob/main/docs/features/hooks.md

- [R10] Getting Started Guide  
  https://github.com/github/copilot-sdk/blob/main/docs/getting-started.md

- [R11] OpenAI Codex advanced configuration  
  https://developers.openai.com/codex/config-advanced

- [R12] OpenAI API libraries documentation  
  https://developers.openai.com/api/docs/libraries

- [R13] OpenAI Node SDK README  
  https://github.com/openai/openai-node

- [R14] Claude Code environment variables  
  https://code.claude.com/docs/en/env-vars

- [R15] Claude Code LLM gateway requirements  
  https://code.claude.com/docs/en/llm-gateway

- [R16] VS Code Bring Your Own Key announcement  
  https://code.visualstudio.com/blogs/2025/10/22/bring-your-own-key

- [R17] GitHub Docs: using your own API keys with Copilot  
  https://docs.github.com/en/copilot/how-tos/administer-copilot/manage-for-enterprise/use-your-own-api-keys
