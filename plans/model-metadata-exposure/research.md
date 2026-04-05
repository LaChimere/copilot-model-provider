# Research Log

> Purpose: capture facts, evidence, and unknowns before planning/implementation.
> This is the review surface for understanding and diagnosis.

## Task
- Summary: expose live Copilot model metadata, including context-window-related limits, through the provider so upper-layer clients can discover it.
- Links (issue/PR/spec): session request on 2026-04-04; local `github-copilot-sdk` `ModelInfo` types.

## Current Behavior
- Observed behavior:
  - `github-copilot-sdk` returns rich `ModelInfo` objects from `CopilotClient.list_models()`.
  - The provider currently collapses that data to model IDs for routing/catalog building.
  - `GET /openai/v1/models` and `GET /anthropic/v1/models` only expose minimal model-card fields.
  - the Anthropic facade currently synthesizes `display_name` from the model ID instead of reusing the runtime-provided `ModelInfo.name`.
- Expected behavior:
  - the provider should preserve all runtime metadata that is actually available for each live model
  - the provider should expose that metadata northbound so OpenAI-facing, Anthropic-facing, and other clients can query it
- Scope affected (modules/endpoints/commands):
  - `src/copilot_model_provider/runtimes/`
  - `src/copilot_model_provider/core/`
  - `src/copilot_model_provider/api/openai/models.py`
  - `src/copilot_model_provider/api/anthropic/models.py`
  - model-list unit/integration/contract tests

## Environment
- OS: Darwin
- Runtime/tool versions:
  - Python `>=3.14` (verified from `pyproject.toml`)
  - `github-copilot-sdk>=0.2.0`
- Repro command(s):
  - `uv run python - <<'PY' ... await client.list_models() ... PY`
  - `uv run pytest -q tests/integration_tests/test_models.py --no-cov`

## Evidence
Include concrete evidence. Prefer copy/paste of relevant excerpts with context.
- Logs / stack traces:
  - none; this is a capability gap, not a crash
- Failing tests (name + output excerpt):
  - none yet; current tests only assert model IDs
- Metrics (numbers + method):
  - live Copilot SDK discovery returned:
    - `claude-opus-4.6-1m`: `max_prompt_tokens=936000`, `max_context_window_tokens=1000000`
    - `claude-opus-4.6`: `max_prompt_tokens=168000`, `max_context_window_tokens=200000`
    - `claude-sonnet-4.6`: `max_prompt_tokens=168000`, `max_context_window_tokens=200000`
    - `gpt-5.4`: `max_prompt_tokens=272000`, `max_context_window_tokens=400000`
- Repro steps (minimal):
  1. Authenticate with `gh auth login` or reuse existing GitHub auth.
  2. Run a subprocess-backed `CopilotClient`.
  3. Call `list_models()` and inspect `model.capabilities.limits`.
  4. Compare with provider `GET /openai/v1/models` and `GET /anthropic/v1/models`, which currently omit those fields.

## Code Reading Notes
List the most relevant files and what you learned.
- `src/copilot_model_provider/runtimes/protocols/runtime.py` — runtime contract only exposes `list_model_ids()`, so metadata is discarded at the interface boundary.
- `src/copilot_model_provider/runtimes/copilot_runtime.py` — runtime already calls `CopilotClient.list_models()`, but only extracts `model.id`.
- `src/copilot_model_provider/core/catalog.py` — catalog entries currently preserve alias/runtime/owner/created only, and the exported `build_live_model_catalog()` helper currently accepts IDs only.
- `src/copilot_model_provider/core/routing.py` — router caches auth-context model catalogs but only returns minimal `OpenAIModelCard`s.
- `src/copilot_model_provider/core/models.py` — public model schemas lack any metadata container for limits/capabilities/policy/billing.
- `src/copilot_model_provider/api/openai/models.py` — OpenAI facade returns the router response unchanged.
- `src/copilot_model_provider/api/anthropic/models.py` and `src/copilot_model_provider/api/anthropic/protocol.py` — Anthropic model list is translated from the same minimal OpenAI list response, and `display_name` is currently derived from the model ID.
- `.venv/lib/python3.14/site-packages/copilot/types.py` — `ModelInfo` includes `capabilities`, `limits`, `policy`, `billing`, and reasoning-effort metadata.
- `tests/contract_tests/test_openai_models.py`, `tests/contract_tests/test_anthropic_models.py`, `tests/unit_tests/test_catalog.py`, and related fake runtimes — existing protocol-facing tests stub `list_model_ids()`, so a hard replace of that method would create avoidable fixture churn.

## Hypotheses (ranked)
1. The primary gap is provider-side truncation of `ModelInfo` to IDs; preserving the full runtime model object should make metadata available end-to-end.
2. Existing clients are most likely to discover metadata if it is attached to their normal `/models` responses rather than hidden behind a new side endpoint.
3. A separate provider-native metadata endpoint may still be useful later, but it is not required for the first compatibility pass if `/models` extension fields are sufficient.

## Experiments Run
For each experiment:
- Command / action: inspected `CopilotClient.list_models()` source in the installed SDK.
  - Result: the SDK returns `list[ModelInfo]` built from `models.list` RPC payloads.
  - Interpretation: the provider can use runtime-sourced metadata instead of inferring it from model IDs.
- Command / action: inspected `copilot.types.ModelInfo`, `ModelCapabilities`, and `ModelLimits`.
  - Result: the SDK surface includes `max_prompt_tokens`, `max_context_window_tokens`, vision limits, support flags, policy, billing, and reasoning-effort metadata.
  - Interpretation: the provider can support more than just context-window values.
- Command / action: ran local live model discovery against the current auth context.
  - Result: `claude-opus-4.6-1m` reports `max_context_window_tokens=1000000`.
  - Interpretation: the runtime data needed for the Claude `/context` investigation is already available.

## Open Questions / Unknowns
- Q1: should a separate provider-native metadata endpoint be deferred entirely unless a concrete client proves `/models` extension fields are insufficient?
- Q2: are there any client-specific parsing quirks that require additional compatibility testing once the additive `copilot` object ships on model-list responses?

## Recommendation for Plan
- Proposed direction:
  - supplement the runtime protocol with a metadata-rich discovery method and keep `list_model_ids()` as a compatibility shim during the rollout
  - preserve full runtime metadata in the auth-context model catalog
  - add a new metadata-aware catalog builder while keeping the exported ID-only helper stable as a wrapper
  - expose it through protocol-compatible `/models` responses using an explicit provider-owned nested `copilot` object
  - include runtime `name` in the `copilot` object and use it as the preferred source for Anthropic `display_name`
  - add a concrete client-tolerance check before merging the first public schema change; if Codex or Claude reject the additive nested object, stop and revisit the design instead of merging partial exposure PRs
  - stage the work as base plumbing, OpenAI exposure, Anthropic exposure, and docs/validation
- Risks:
  - public schema churn on model-list endpoints
  - some clients may ignore unknown fields even when the metadata is present
  - richer metadata increases snapshot/test fixture breadth
- Suggested verification level (L1/L2/L3): L2
