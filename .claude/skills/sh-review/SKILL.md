---
name: sh-review
description: Review a branch or pull request before integration using independent code review, behavioral checks and revision-specific evidence.
---

Resolve the intended repository, base and head from the request or existing task. Read project guidance and inspect the entire proposed diff against its merge-base, plus relevant staged/unstaged/untracked changes. Record actual commit IDs; a clean working tree is not proof that a branch has no changes.

- Delegate an independent review to `sh-code-reviewer`. Review surrounding callers, shared contracts, test behavior and failure paths. If delegation is unavailable, report that limitation rather than claiming independent review.
- Have `sh-verifier` run the agreed checks and affected downstream integration/agent regressions. UI changes also need rendered review when acceptance calls for it. Do not impose a universal coverage percentage or six-reviewer stack.
- Deduplicate findings. Require exact location, concrete trigger, consequence and supporting evidence; skip style preferences and unproven speculation. Trace swallowed errors and fallbacks that turn failures into apparent success. Zero findings is valid.
- Return failures to the builder. Neither reviewer edits implementation or weakens expectations. Rerun affected checks and refresh review after a code change. A finding marked fixed without rechecking is unresolved.
- Create a review report with the format in `harness/review-report.example.json`. List required checks from acceptance, not just whichever checks passed. Each check and the review have an evidence artifact. Use project-relative paths.
- Run `gate` with the report, actual project root, current head revision and every required check ID. The checker validates the report's completeness and evidence files; it cannot prove the recorded observations are true.

Outcome: pass / changes requested / incomplete, reviewed base/head, findings, check evidence and remaining risks. A local pass is not a GitHub approval, successful remote CI, merge authorization or a guarantee of correctness. On a PR verify remote CI targets the same current head before declaring it merge-ready. Re-review and re-test after conflict resolution or new commits.

Basis: Anthropic A3, E2, C1; ECC agents/code-reviewer.md, agents/pr-test-analyzer.md, agents/silent-failure-hunter.md and commands/review-pr.md. Adapted to one reviewer plus focused verification.
