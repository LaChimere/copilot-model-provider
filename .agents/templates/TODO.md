# Task Checklist

> Purpose: execution-phase checklist derived from `plans/{slug}/plan.md`.
> Treat this as the progress truth source.

## Task
- Summary:
- Links:

## Plan Reference
- Plan version/date:
- Approved by (if applicable):

## Checklist
### Preparation
- [ ] Sync/confirm baseline (main branch / clean state)
- [ ] Confirm repro or failing test exists (if bug)
- [ ] Confirm verification level target (L1/L2/L3)

### Implementation
- [ ] Item 1:
  - Acceptance criteria:
  - Evidence:
- [ ] Item 2:
  - Acceptance criteria:
  - Evidence:
- [ ] Item 3:
  - Acceptance criteria:
  - Evidence:

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
- [ ] Run lint/typecheck: `...` (attach output/excerpt)
- [ ] Run unit tests: `...` (attach output/excerpt)
- [ ] Run integration/e2e or before/after check: `...` (attach proof)
- [ ] Capture logs/metrics if required

### Review / Packaging
- [ ] Summarize changes (what/why)
- [ ] Confirm no scope creep / unrelated cleanup
- [ ] Check whether related docs need updating (use `refresh-related-docs` if behavior, config, or API changed)
- [ ] Prepare PR description / changelog notes (if applicable)

## Evidence Log
Paste concise evidence here (commands + key lines).
- `command`: output excerpt
- before/after: evidence

## Result
- Outcome:
- Follow-ups (if any):
