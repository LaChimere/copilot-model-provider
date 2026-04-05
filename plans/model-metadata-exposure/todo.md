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
- [ ] Item 1: Base metadata plumbing PR
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
    - pending
- [ ] Item 2: OpenAI `/models` metadata exposure PR
  - Acceptance criteria:
    - `GET /openai/v1/models` model cards gain optional nested `copilot` metadata
    - the nested `copilot` object matches the approved schema exactly
    - model ordering and existing required fields remain unchanged
    - Codex and Claude tolerance checks pass before merge using the documented local smoke-test procedure
    - OpenAI-facing tests prove runtime metadata is serialized correctly
  - Evidence:
    - pending
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
- [ ] Run lint/typecheck: `uv run ruff check . && uv run pyright && uv run ty check .` (attach output/excerpt)
- [ ] Run unit/integration/contract tests: `uv run pytest -q tests/unit_tests/test_catalog.py tests/unit_tests/test_app_boot.py tests/contract_tests/test_openai_models.py tests/contract_tests/test_anthropic_models.py tests/integration_tests/test_models.py --no-cov` (attach output/excerpt)
- [ ] Run full regression suite: `uv run pytest -q` (attach output/excerpt)
- [ ] Capture live metadata evidence for representative models
- [ ] Capture Codex/Claude tolerance smoke-test evidence for the additive `copilot` object:
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
- pending

## Result
- Outcome: pending
- Follow-ups (if any): pending
