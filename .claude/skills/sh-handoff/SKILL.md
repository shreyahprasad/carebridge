---
name: sh-handoff
description: Preserve resumable project state and route the next agent from verified prerequisites. Write a dated session handoff when requested or needed for a session transition.
---

For routine worker completion, return a short result to the coordinator and update the existing progress record: task, branch/worktree, base/head revision, contract version, changed paths, checks/evidence, blockers and next action. Do not create a separate handoff file for every worker.

The coordinator selects the next agent:

- Builder returns work → independent code review and verification.
- Failed check or confirmed issue → builder repair; bounded retries, then replan.
- UI criteria need evidence → browser reviewer, with one browser owner.
- Required checks and review pass on the current revision → integrate if authorized, then rerun affected checks on the integrated revision.
- Only mark prerequisites verified after checking evidence; run `plan` for ready tasks before delegating downstream work. Blocked tasks leave independent tasks available.
- Contract changes, stale evidence or expired timebox → replan dependent work.

For a session handoff, read the latest existing handoff first. Use the user's exact convention:

- Directory: `~/projects/_handoffs/<project>/`.
- Name: `handoff-YYYY-MM-DD.md`, then `-2`, `-3`, etc.; never overwrite a same-day file. Default date timezone is America/Los_Angeles unless the user changes it.
- Carry forward the optional top metadata block. Use `project:` only for a file directly at the handoff root; `public:` and `site:` only for published HTTPS links; `status: complete` only when the owner says it is done.
- Include `## Next`, whose first line/bullet is one sentence stating the next action. Record enough verified state, exact resume commands and unresolved work for a fresh agent to continue. No credentials or private payloads.
- End with `## Milestones`, carrying forward the whole plan. Each heading is `### <id> <title> · <stage>`; stages progress design → build → harden → ship → shipped, or parked. Optional steps use `[x]`, `[ ]` or `[-]`, then an id and title. Nothing else belongs in this final section. Do not invent or silently drop milestones.
- Never put Megalai work under `~/projects/_handoffs/` or `~/projects/personal/`. Use that project's approved location instead; ask if none is established.

Writing a handoff does not launch or message another agent. The coordinator delegates through its native tools within the user's authorized task. A resumed agent rechecks revision, environment and evidence instead of blindly trusting prior status.

Basis: Anthropic A2, A4, A5; ECC skills/team-agent-orchestration and skills/dynamic-workflow-mode. Paths, dates and milestone format are the user's conventions, not upstream requirements.
