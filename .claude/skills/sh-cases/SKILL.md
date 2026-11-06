---
name: sh-cases
description: Create synthetic eval cases from project contracts, validate fixtures and separate expected outcomes from model output. Use for test data and scenario coverage.
---

Read the existing brief, contracts and eval plan, including the user's approved planning folder when provided. Work only within the authorized phase: preparing harness capability does not authorize generating a competition project's fixtures before its allowed start.

1. Derive a small scenario matrix from observable requirements: normal success, boundary, missing information, contradictory evidence and tool failure. Include project-specific risks, not arbitrary extra categories.
2. Use invented identities and records. Do not rewrite real client anecdotes into nominally synthetic cases. Keep factual source fixtures separately attributed; synthetic records are not evidence about real providers or policies.
3. Write a suite compatible with the harness eval runner. Each case has `id`, `scenario`, `synthetic: true`, `basis` (requirement/source references), `input` and `checks`. Use `equals` or `subset` to check outcomes; add tool constraints only when the tool behavior is itself required.
4. Derive expected results from the agreed rules and fixed fixtures before observing candidate responses. A separate reviewer checks expectations; the generating model's confidence is not ground truth. Keep held-out expectations out of builder context when evaluating generalization.
5. Run `fixtures` using the CLI location in `harness/README.md`, then validate actual input/output types with the project's chosen schema validator. The generic fixture checker does not replace Pydantic/JSON Schema validation.
6. Use the runtime guide's registered custom graders for evidence/semantic checks and its experiment mode for model/effort comparisons. Keep strict regression comparison unchanged; version graders and fixed grading context.
7. Run through the project adapter when implemented. Retain failures and record suite, prompt/model, environment and source-fixture versions. Promote a baseline only after independent review; do not edit expectations merely to fit output.

Return the scenario matrix, created paths, rule-to-case mapping, checks actually run and unresolved expectation questions. Routine schema/fixture validation needs no model call.

Basis: Anthropic P1, E1, E2 and T1 in the source map. This is an original workflow; ECC's test-collaboration and ai-regression-testing inform traceability and retained failures, not a claimed upstream synthetic-case generator.
