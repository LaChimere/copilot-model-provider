# AGENTS.md

## Purpose

This repository uses an agent-driven, small-PR, reviewable, incremental delivery model.

The default expectation is:

- prefer small, focused PRs
- prefer atomic commits inside each PR
- prefer mergeable intermediate states
- prefer staged delivery for large features
- prefer explicit planning before parallel execution

This repository is currently a small Python project built around `github-copilot-sdk`. At the time of writing:

- the main architecture context lives in `docs/design.md`
- the Python package metadata lives in `pyproject.toml`
- planning templates are available in `.agents/templates/`
- a repository `plans/` directory exists for repo-resident planning artifacts when explicitly requested
- `uv` is the expected dependency/runtime tool unless the repo later standardizes on something else

## Operating contract

- Prefer **evidence-driven** work: claims must be backed by repo artifacts such as code references, documentation, logs, or executed command output.
- Avoid speculative implementation. If key facts are missing, run the **Discovery Loop** first.
- Ask the user only the **minimal** blocking questions.

Minimal blocking questions usually mean:

- expected vs actual behavior
- repro steps
- environment/version details
- a relevant log snippet or error message

## Mode switching

**Default**: If the task is trivial and low-risk (single-file, clearly specified, no public API/CI/data impact), proceed in execution mode.

**Enter plan mode** if ANY of these apply:

| Risk triggers | Design required? | Complexity triggers | Design required? |
|---|---|---|---|
| Public API/interface/schema changes | Yes | Spans multiple components/directories | No |
| Auth/security/concurrency/caching/correctness-critical logic | Yes | Needs comparing >1 design | Yes |
| Data migration/backfill/transformation | Yes | Unclear requirements or missing repro | No |
| CI/deploy/infra changes | No | Requires multiple verification steps beyond a single build | No |
| Dependency add/upgrade | No |  |  |
| Performance-sensitive change | No |  |  |

**Design required** means both Gate 1 and Gate 2 apply.

When design is not required, only Gate 2 applies. Gate 1 may still be added at the user's request.

## Discovery loop

When information is missing:

1. List unknowns.
2. Collect minimal evidence:
   - read relevant code and docs
   - run existing tests if they exist
   - reproduce locally if possible
   - inspect logs, traces, or stack traces
3. Stop once a justified plan can be written.

## Core delivery rules

- One PR should have one logical purpose.
- Do not mix behavioral changes, refactors, formatting-only edits, generated-file churn, and dependency upgrades in the same PR unless explicitly requested.
- If a task becomes too large to review comfortably, stop and split it.
- If a task can only be described with "A and B", it is probably not atomic enough for one PR.
- For large features, prefer this sequence:
  1. base / contract / flag / abstraction
  2. implementation
  3. integration
  4. cleanup

## Planning artifacts and approval gates

When plan mode is triggered, create and maintain planning artifacts in the **session workspace by default**, not in the repository, unless the user explicitly requests repository-resident planning documents or the task is specifically about maintaining repository planning artifacts.

Default planning locations:

- session `plan.md` for the working plan
- session todo tracking in the execution system used by the agent

Repository docs should be updated only when they are part of the actual deliverable. In this repository, `docs/design.md` is an architecture/design artifact and may be updated when explicitly requested or when the implementation task directly changes the documented design.

If repository-resident planning artifacts are explicitly requested, use:

- `.agents/templates/RESEARCH.md`
- `.agents/templates/DESIGN.md`
- `.agents/templates/PLAN.md`
- `.agents/templates/TODO.md`
- `.agents/templates/LESSONS.md`

and place the resulting artifacts under `plans/{slug}/` unless the user requests a different repository path.

**Workflow with approval gates**:

```text
Research -> Design -> [Gate 1: Human Approve] -> Plan -> [Gate 2: Human Approve] -> Execute -> Verify -> [Gate 3: Post-exec Review (high-risk only)] -> Lessons
```

```text
Fast path (urgent): Execute -> Verify -> Lessons (backfill)
```

**What counts as explicit approval**:

- the user says `approved`, `proceed`, `LGTM`, `可以开始`, or similarly clear approval language
- the user explicitly asks for implementation to begin after reviewing the plan/design

These do **not** count as approval:

- silence
- acknowledgement without clear approval
- requests for clarification, edits, or more investigation

### Gate 1 — Design approval

Apply when design is required.

1. After research and design are complete, stop and present the design for review.
2. Use the design artifact as the review surface, with supporting evidence as needed.
3. If the reviewer requests changes, incorporate them and re-submit.
4. Do **not** proceed to the execution plan until design is explicitly approved.

### Gate 2 — Plan approval

Apply when plan mode is active.

1. After the execution plan is complete, present it for review.
2. If the reviewer requests changes, incorporate them.
3. Do **not** proceed to execution until the plan is explicitly approved.
4. After approval, implement the approved plan and keep execution tracking aligned with it.

### Skipping gates

- For trivial, low-risk tasks that do not trigger plan mode, both gates may be skipped.
- When plan mode is triggered but design is not required, Gate 1 may be skipped.
- The user may always request Gate 1 regardless of the trigger table.

### Fast path

When a production issue, urgent hotfix, or time-critical breakage requires bypassing gates:

- state explicitly that the fast path is being used and why
- still run the minimum relevant verification before proposing completion
- backfill lessons if the incident revealed a systemic gap

### Gate 3 — Post-execution review

Optional, and primarily for high-risk changes such as:

- auth/security
- data migration
- public API/schema changes
- infra/deploy changes

Use Gate 3 when:

- the change type requires L2+ verification
- the implementation materially deviated from the approved plan
- the reviewer explicitly requested a post-execution review

## Verification rules

Never mark work done without evidence.

Before proposing completion, confirm:

1. acceptance criteria are met with evidence
2. the diff is consistent with the approved plan
3. the relevant verification level has been executed
4. related documentation has been considered and updated when appropriate

If an acceptance criterion is not met:

1. fix it directly if it is a straightforward implementation issue
2. update the plan and re-approve if the approved plan is incomplete or infeasible
3. update the design and re-approve if the design itself is invalidated
4. stop and report clearly if the task is stuck

| Verification level | Scope |
|---|---|
| **L1** | lint/typecheck + unit tests or targeted test |
| **L2** | integration/contract tests OR reproducible before/after behavior check |
| **L3** | e2e/staging/production-like validation when feasible |

| Change type | Minimum level |
|---|---|
| Refactor / no behavior change | L1 |
| Bug fix / behavior change | L2 |
| Infra / CI / deploy / security / data migration | L2 + rollback, L3 when feasible |
| Performance-related | numbers + method (before/after) |

Before proposing completion, run the narrowest relevant validation first, then broader validation if needed.

### Validation command guidance

Preferred commands depend on the repository.

If the repository later adds standard targets such as:

- `make lint`
- `make test`
- `make typecheck`

use them.

If they do not exist:

- inspect the repository
- use the closest project-native commands
- report exactly what was run

For this repository today, likely validation sources include:

- Python project commands driven by `uv`
- any test/lint/typecheck tools later added to `pyproject.toml`
- targeted behavior checks for provider/documentation changes

Do not claim validation that was not actually executed.

Evidence can include:

- test output
- logs
- traces
- before/after behavior
- metrics
- command output

## Parallel work rules

- Do not assume parallel work is safe by default.
- When parallelizing, use one branch per task and one worktree per branch.
- Shared contracts, schemas, and interfaces should be changed only in the base PR unless explicitly instructed otherwise.
- Parallel tasks must have explicit ownership boundaries:
  - owned directories
  - forbidden directories
  - dependency order
  - validation commands

## Subagent strategy

- Use subagents only when parallelism reduces uncertainty or execution time.
- Prefer no more than **3 subagents** at once.
- Each subagent should own one task with no overlap.
- Each subagent output should include:
  - Assumptions
  - Findings
  - Evidence
  - Recommendation
  - Open questions / Risks

## Git discipline

- Do not commit directly to `main`.
- Prefer a branch name that reflects one task and one purpose.
- Prefer atomic commits with concise, descriptive commit messages.
- If the working tree contains multiple concerns, split them before proposing final commits or PRs.

## Elegance check and over-engineering guardrails

For non-trivial changes, briefly check whether complexity or coupling can be reduced. At the same time, avoid over-design.

### Simplicity first

- Solve the stated problem, not imagined future problems.
- Prefer the simplest implementation that meets acceptance criteria.
- Add abstraction only when justified by a concrete present requirement.
- If a simpler approach is good enough now and can be changed later safely, prefer the simpler approach.

### When extensibility is justified

- there is an explicit near-term requirement
- the cost of adding the seam now is low
- the seam is natural, such as an interface boundary, config boundary, or plugin hook

### When extensibility is not justified

- the only argument is "we might need this later"
- it adds indirection that no current caller needs
- it makes the code harder to understand without a concrete benefit

### Decision rule

When in doubt, prefer:

- concrete over abstract
- direct over indirect
- easy to change later over prematurely generalized now

### Scope guardrails

- Do not expand scope into unrelated cleanup.
- Refactor only if it measurably reduces complexity without weakening verification.
- If extensibility work exceeds roughly 20% of the task's core change, split it into a separate PR.

## Lessons

After a material correction that caused wrong results or rework, record lessons in the current planning flow if the mistake exposed a systemic gap.

Do not record purely stylistic feedback as lessons learned.

## Skill routing

Skills specialize the workflow in this file; they do **not** bypass discovery, plan mode, or approval gates unless explicitly stated.

Use the appropriate skill automatically when the request matches:

- `decompose-feature`
  - automatically enters plan mode
  - use when a feature is too large for one PR
  - use when the user asks how to split a large feature
  - use when a staged rollout or stacked PR plan is needed
  - use this skill to decide **what PRs should exist**

- `plan-parallel-work`
  - automatically enters plan mode
  - use when multiple agents need to work in parallel
  - use when branch/worktree ownership and merge order need to be defined
  - use when a base PR must be established before fan-out work
  - use this skill to decide **who works where, on which branch/worktree, and in what order**

- `ensure-atomic-pr`
  - may be used in any mode
  - use when a diff, commit, or PR is too large
  - use when concerns are mixed
  - use when recovery or splitting guidance is needed

- `refresh-related-docs`
  - use when behavior, configuration, or API surface changes make existing Markdown docs stale
  - ask the user before editing existing docs unless the user explicitly requested those doc edits

- `scan-image-vulnerabilities`
  - use for image CVE or container vulnerability inspection
  - read-only inspection; does not require plan mode

## Repository-specific notes

- Treat `docs/design.md` as the current design baseline for the provider architecture.
- Keep architecture decisions consistent with that document unless the user asks to revise the design.
- Prefer Python ecosystem tooling already present in the repository.
- Do not invent repository-wide process or file layout beyond what is needed for the requested change.
- For Python code in this repository, every method/function must have a docstring.
- Public methods/functions must have **detailed** docstrings that explain purpose plus relevant inputs, outputs, side effects, or constraints; one-line placeholder docstrings are not sufficient for public APIs.
- Unit test coverage in this repository must stay at or above **90%**; changes that lower the enforced `pytest` coverage gate are not acceptable unless the user explicitly approves that policy change.

## Output style

Prefer concrete plans over abstract advice.
Prefer explicit boundaries over vague recommendations.
Prefer mergeable increments over large end-to-end changes.
