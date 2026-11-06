# Messages API application examples

These applications import the shared guarded runtime. They do not contain an independent agent loop. Claude Code uses `/sh-messages` to build product systems on it; coding-worker hooks/settings are separate.

Read the full [runtime guide](../../docs/MESSAGES_API.md) in the source harness (generated projects: `/Users/lebotomy/projects/personal/shreyah-harness/docs/MESSAGES_API.md`). It documents policy registration, privacy, safety classifiers, tool/resource grants, approvals, delegation, streaming, tests and limitations.

## Install

From the harness checkout:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[anthropic]'
.venv/bin/python -m unittest discover -s tests -v
```

From a generated project (`harness.py init TARGET --messages-api`), instead run:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r api_starter/requirements.txt
```

Initialization expands the local harness package path in requirements. The SDK extra pins the tested version; record all resolved dependencies for reproducible application deployment. `runner.py` is a compatibility import, not a copied runtime. Other machines must install the same reviewed harness revision from their own checkout/package.

## Local SQLite multiagent workflow

```sh
.venv/bin/python api_starter/workflow.py --demo --database /tmp/harness-notes.sqlite --id daily --body 'Reviewed plan'
python3 '/Users/lebotomy/projects/personal/shreyah-harness/harness.py' runtime-check api_starter
```

For a source checkout, replace `api_starter/` with `examples/messages_api/`. Demo responses are scripted; the restricted specialist, SQLite reads/writes, shared budgets, parent policy inheritance and final DB validation really execute. The DB path is trusted host configuration. The example assumes one local owner; it does not implement multi-user authentication or durable workflow resume. `--live` explicitly enables paid requests and requires `ANTHROPIC_API_KEY` and `CLAUDE_MODEL`.

## Live catalog rehearsal

The catalog adapter checks a real local lookup and validates identifiers, availability and source against observed state. It makes no request without `--live`. Metadata-only mode needs a model identifier but no key; it records installed SDK, shared runtime/adapter/fixture hashes and limits.

```sh
mkdir -p artifacts
.venv/bin/python api_starter/adapter.py --metadata-only > artifacts/baseline-metadata.json
python3 '/Users/lebotomy/projects/personal/shreyah-harness/harness.py' fixtures api_starter/suite.json
python3 '/Users/lebotomy/projects/personal/shreyah-harness/harness.py' eval api_starter/suite.json --timeout 40 --metadata artifacts/baseline-metadata.json --report artifacts/baseline.json --candidate .venv/bin/python api_starter/adapter.py --live
```

Keep `prompts/baseline.txt` as v0. Change prompts only after inspecting actual failures; retain unchanged runtime controls, fixture suites and comparison context. For each candidate use the same `--prompt` when generating metadata and running the adapter, then compare reports with `harness.py compare`. Prompt provenance may change; model/tool/data/runtime context drift requires a reviewed new baseline. Repeated trials measure sample consistency, not guaranteed quality.

## Default safeguards

- Only registered tools run, after local JSON Schema and semantic validation, trusted resource grants, inherited policy checks and any required exact-action approval.
- Read classification is explicit. Tools default to unknown/restricted; ordinary writes require a grant; destructive/sensitive tools also require approval. The catalog tool is read-only.
- Credential filtering is automatic on supported model/tool/output/report paths. Register known secrets/PII patterns centrally. Error details are suppressed. Arbitrary tool/SDK debug logs and internal network I/O require separate app controls.
- Child agents inherit policy, permissions, hooks and shared request/tool/retry/time budgets. Partial child results remain unresolved. Parallel delegation is unsupported.
- JSON finals require an output schema or semantic validator. Optional repair is bounded and disables tool calls. Streaming accumulates complete responses before dispatch/release.
- Request retries have one owner; SDK retries are disabled. Call IDs cannot replay within a run; this is not external exactly-once execution or crash recovery.

Offline tests use fake models and mock SDK transport. Live account access, model quality, classifier accuracy, app/browser behavior and deployment must be verified separately. Never label demo responses as live API proof.
