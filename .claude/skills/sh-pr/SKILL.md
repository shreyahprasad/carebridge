---
name: sh-pr
description: Write or update a concise pull request from the actual branch diff and verification evidence. Publish only when the user's request authorizes it.
---

First resolve the GitHub account, repository, base branch and head. Inspect project instructions, templates, the full diff and all commits since the merge-base. Check for an existing PR. Use the intended account; never infer it from the Git commit author.

Write for a reviewer who has not seen the conversation:

- Title: concrete final behavior or problem fixed.
- Body: problem and resulting behavior; meaningful implementation tradeoffs; actual tests/evals and their outcomes; material limitations. Keep small changes to a few sentences unless the repository template needs more.
- Include a trigger/before-after example when useful. Do not list every changed file or repeat the chat history. Distinguish NOT RUN, failed and passed checks.

Use `/sh-review` before calling work ready to merge. A draft PR may be opened earlier when authorized, with incomplete checks stated. Never create a second PR when updating the existing one is appropriate.

Writing a draft in chat or a local file is separate from publishing. If publishing is authorized, push the intended branch and create/update the PR using the existing connector or `gh`. Pass the exact multiline body via a structured API or `--body-file`. Do not automatically rebase, force-push, merge or approve a PR to recover from a failure. Verify account/repo, URL, base and head after publishing.

Return the proposed title/body or verified PR URL, current review/CI status and next step. Push, PR creation and merge are separate operations governed by the user's authorization.

Basis: Anthropic A4, A6, C2 for clean progress, tool contracts and reusable workflow packaging. PR-writing details come from ECC commands/pr.md, skills/git-workflow and this user's concise-writing preferences; they are not presented as Anthropic-specific instructions.
