# Task Checklist

> Purpose: execution-phase checklist derived from `plans/model-metadata-exposure/plan.md`.
> Treat this as the progress truth source.

## Task
- Summary: preserve live Copilot model metadata and expose it on the existing OpenAI and Anthropic `/models` responses through an additive nested `copilot` object.
- Links:
  - `plans/model-metadata-exposure/research.md`
  - `plans/model-metadata-exposure/design.md`
  - `plans/model-metadata-exposure/plan.md`

## Plan Reference
- Plan version/date: revised Gate 2 draft after second Claude Opus review on 2026-04-05
- Approved by (if applicable): User on 2026-04-05

## Checklist
### Preparation
- [ ] Sync/confirm baseline (main branch / clean state)
- [ ] Confirm verification level target (L2)
- [ ] Reconfirm live metadata evidence for at least one model with 1M context and one standard-context model
- [ ] Capture `codex --version` and `claude --version` for the tolerance-check evidence
- [ ] Confirm the local tolerance-check path:
  - provider serves enriched OpenAI `/models`
  - Codex and Claude are pointed at that provider via the existing local config/scripts flow
  - each client completes model discovery and one minimal prompt send without parse/schema errors

### Implementation
- [x] Item 1: Base metadata plumbing PR
  - Acceptance criteria:
    - runtime protocol and Copilot runtime preserve metadata-rich model discovery via a new additive runtime method
    - `list_model_ids()` remains available as a compatibility shim in this PR
    - `build_live_model_catalog()` stays stable as an ID-only wrapper and a new metadata-aware catalog builder is added
    - `core/models.py` defines the shared nested `copilot` schema in this PR
    - `core/routing.py` switches to the metadata-rich runtime discovery path while keeping public `/models` payloads unchanged
    - auth-context catalog/cache stores normalized model metadata
    - broad `list_model_ids()` fixture churn is avoided; only tests directly touching the new metadata method are updated in PR1
    - current public `/models` payloads remain unchanged in this PR
  - Evidence:
    - Added `RuntimeDiscoveredModel` plus shared `CopilotModel*` metadata models in `src/copilot_model_provider/core/models.py`
    - Added additive `RuntimeProtocol.list_models()` shim and metadata-aware `build_live_model_catalog_from_models(...)`
    - Switched `ModelRouter` to metadata-rich runtime discovery without changing `OpenAIModelCard` construction
    - `CopilotRuntime.list_models()` now preserves normalized runtime metadata and `list_model_ids()` delegates to it
    - Added unit coverage for metadata preservation and protocol-shim compatibility in `tests/unit_tests/test_catalog.py` and `tests/unit_tests/test_copilot_runtime.py`
- [x] Item 2: OpenAI `/models` metadata exposure PR
  - Acceptance criteria:
    - `GET /openai/v1/models` model cards gain optional nested `copilot` metadata
    - the nested `copilot` object matches the approved schema exactly
    - model ordering and existing required fields remain unchanged
    - Codex and Claude tolerance checks pass before merge using the documented local smoke-test procedure
    - OpenAI-facing tests prove runtime metadata is serialized correctly
  - Evidence:
    - `OpenAIModelCard` now exposes optional `copilot` metadata while preserving existing required fields
    - OpenAI route now uses `response_model_exclude_none=True` so absent metadata is omitted instead of serialized as `null`
    - `tests/unit_tests/test_catalog.py` covers mixed metadata/no-metadata model-card responses
    - `tests/contract_tests/test_openai_models.py` proves the nested serialized `copilot` JSON shape
    - `tests/integration_tests/test_models.py` asserts live container responses include additive `copilot` metadata
    - Codex and Claude tolerance smoke tests both completed minimal prompts successfully against an isolated current-image container
- [ ] Item 3: Anthropic `/models` metadata exposure PR
  - Acceptance criteria:
    - `GET /anthropic/v1/models` model entries gain the same nested `copilot` metadata
    - Anthropic translation stays consistent with the shared catalog snapshot
    - Anthropic `display_name` prefers runtime `name` and falls back cleanly when absent
    - Anthropic-facing tests prove runtime metadata is serialized correctly
    - PR2 is already merged, since Anthropic exposure depends on the shared enriched OpenAI-facing model-card shape
  - Evidence:
    - pending
- [ ] Item 4: Cleanup/docs/validation PR
  - Acceptance criteria:
    - directly related docs are refreshed
    - targeted and full validation pass
    - no scope creep or unrelated refactors are mixed in
  - Evidence:
    - pending

### Acceptance Gate (before proposing PR)
- [ ] All acceptance criteria above are met with evidence
- [ ] Diff is consistent with approved plan (no scope creep, no missing pieces)
- [ ] Applicable verification level executed

If any check fails, follow the recovery flow defined in `AGENTS.md` (Verification rules → Acceptance criteria):
1. Can fix directly → fix and re-verify
2. Plan is infeasible → update `plan.md`, re-submit for Gate 2
3. Design is invalid → update `design.md`, re-submit for Gate 1 → Gate 2
4. Stuck → stop and report to user with evidence of what was attempted

### Verification (Evidence)
- [x] Run lint/typecheck: `uv run ruff check . && uv run pyright && uv run ty check .` (attach output/excerpt)
- [ ] Run unit/integration/contract tests: `uv run pytest -q tests/unit_tests/test_catalog.py tests/unit_tests/test_app_boot.py tests/contract_tests/test_openai_models.py tests/contract_tests/test_anthropic_models.py tests/integration_tests/test_models.py --no-cov` (attach output/excerpt)
- [x] Run full regression suite: `uv run pytest -q` (attach output/excerpt)
- [ ] Capture live metadata evidence for representative models
- [x] Capture Codex/Claude tolerance smoke-test evidence for the additive `copilot` object:
  - versions captured
  - model discovery succeeds
  - minimal prompt send succeeds
  - no parse/schema errors appear in client output/logs

### Review / Packaging
- [ ] Summarize changes (what/why)
- [ ] Confirm no scope creep / unrelated cleanup
- [ ] Check whether related docs need updating (use `refresh-related-docs` if behavior, config, or API changed)
- [ ] Prepare PR description / changelog notes (if applicable)

## Evidence Log
Paste concise evidence here (commands + key lines).
- `uv run ruff format --check .` -> all files formatted
- `uv run ruff check .` -> all checks passed
- `uv run ty check .` -> all checks passed
- `uv run pyright` -> 0 errors, 0 warnings
- `uv run pytest -q` -> `153 passed, 2 skipped`, coverage `93.74%`
- Claude Opus 4.6 1M pre-commit review -> final review reported `Findings: 0`
- Codex tolerance smoke -> `codex-cli 0.118.0`, config helper discovered live models from `/openai/v1/models`, `codex exec` returned `OK`, container log recorded `POST /openai/v1/responses 200`
- Claude tolerance smoke -> `Claude Code 2.1.84`, config helper discovered live models from `/anthropic/v1/models`, `claude -p` returned `OK`, container log recorded `POST /anthropic/v1/messages 200`

## Result
- Outcome: Items 1-2 ready to commit; PR2 validated and tolerance-checked
- Follow-ups (if any): Item 3 Anthropic `/models` metadata exposure after this commit
