# Shared contracts · v1

- Startup command and app URL:
- Verification commands:
- Data schemas and example records:
- API request/response examples and errors:
- Unknown/partial/failed AI result behavior:
- UI flow, hierarchy and design tokens:
- References and observed design decisions:
- Target viewports:
- Applicable interaction states:
- External effects and demo fixtures:
- Product-agent roles/prompts, allowed tools, validators and handoff input/output schemas:
- Connected-slice acceptance: downstream use of validated upstream results, stage/run correlation and live versus scripted evidence:
- Shared request/tool/retry/time limits; usage accounting and incomplete usage:
- Proposed/accepted facts; current-draft human review requirements:
- Eval adapter, fixed comparison metadata, prompt versions and observed-state checks:

For Messages API applications, use the source harness's `docs/MESSAGES_API.md` and optional `api_starter/`. First prove one live tool round trip; native coding subagents/hooks are not product runtime controls.

Coordinator owns changes; dependent tasks pause when a contract changes. Define an executable outcome check for every must-have behavior.

Messages API runtime contract: shared harness/SDK versions, trusted identity source, tool risk/resource metadata, inherited grants/policies, secret/PII configuration, human approval UI/store, result schemas/evidence validators, I/O timeouts, persistence/transactions/idempotency and recovery expectations. Use `/sh-messages`; include `runtime-check` plus runtime boundary tests in acceptance.
