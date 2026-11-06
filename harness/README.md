# Local harness commands

Harness installation: `/Users/lebotomy/projects/personal/shreyah-harness`.

```sh
python3 '/Users/lebotomy/projects/personal/shreyah-harness/harness.py' plan harness/plan.json
python3 '/Users/lebotomy/projects/personal/shreyah-harness/harness.py' doctor
python3 '/Users/lebotomy/projects/personal/shreyah-harness/harness.py' fixtures path/to/suite.json
python3 '/Users/lebotomy/projects/personal/shreyah-harness/harness.py' gate path/to/review.json --project . --revision CURRENT_HEAD_SHA --require build tests
```

Invoke `/start` in Claude Code from this project. Read the source harness's README for eval commands, `prompts/task-contract.md` for worker assignments, `prompts/review-rubric.md` for independent acceptance, `docs/TOOLS.md` for tool profiles and `docs/FOUNDATIONS.md` for Anthropic grounding. These reference paths are relative to the installation above. No global settings were modified.

Skills: `/sh-messages`, `/sh-cases`, `/sh-review`, `/sh-pr`, `/sh-handoff`. Set the gate revision from the actual `git rev-parse HEAD`, and select required checks from task acceptance; `build tests` is only an example. The review-report example starts untested and cannot pass as-is.

Messages API projects: read `/Users/lebotomy/projects/personal/shreyah-harness/docs/MESSAGES_API.md`. Optional initialization with `--messages-api` adds `api_starter/` without installing dependencies or running paid calls. The eval CLI supports `--metadata FILE` for fixed comparison context, plus `run_status` assertions. Put all options before `--candidate`, which consumes the remaining arguments. Keep product runtime code and credentials separate from coding-worker configuration.

For Messages API workflows, `/sh-messages` uses the shared installed runtime and automatic policy inheritance. Run `python3 '/Users/lebotomy/projects/personal/shreyah-harness/harness.py' runtime-check PATH_TO_APP` alongside application tests. This static check supplements review and does not sandbox arbitrary Python.
