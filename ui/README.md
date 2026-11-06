# CareBridge UI

A static page with no build step. Serve the repo root and open `/ui/`:

```sh
python3 -m http.server 8000   # then open http://127.0.0.1:8000/ui/
```

Routes: `#/case/<id>` shows the case details. `#/case/<id>/providers` shows the provider match and, when there is one, the trip plan.

## What the page reads

| File | Written by | If it's missing |
|---|---|---|
| `data/cases.json` | intake / fixtures | Error message |
| `data/runs/match/<case_id>-latest.json` | provider match workflow | "No provider match yet" plus the command to run |
| `data/runs/trip/<case_id>-latest.json` | trip-plan workflow | "Not planned yet" on the ride strip and on each card |

Rules for the `-latest.json` files:

1. **Same JSON as the dated run file.** Validate it first (`MatchResult` / `TripPlan`), then write it beside the dated file. Write it on every run in every mode (live, scripted, rules_only), so the page always shows the last run.
2. **`version` and `case_id` are checked.** The page reads only `match-result-v1` and `trip-plan-v1`. Any other version shows an error instead of guessing. Bump the version when a field the page uses changes meaning.
3. **A trip plan is shown only if its `correlation_id` matches the match's.** A combined match→trip run writes both files with the same id. A match run on its own makes the old trip plan stale, and the page hides it with a "rerun trip" notice.
4. **Write atomically**: write a temp file, then `os.replace`, so the page never reads half a file.

Fields used. Match: `date, mode, fallback_reason, counts, needs, picks[] (rank, provider_id, name, tier, tier_basis, address, state, distance_mi, phone, intake_phone, website, telehealth, facts[].text, questions[].code/text, extra_questions, why), not_chosen_note, rule_version, data_version, prompt_version, correlation_id`.
Trip: `correlation_id, benefits[] (program_id, name, how_to_access, phone, notes, sources[].url/title, confidence), plans[] (order, provider_id, grade, grade_basis, time_estimate, benefits[].program_id/use/question, questions[].code/text, extra_questions, steps, tell_client)`.

Fields listed in `unchecked_fields` (model-written) are shown in a dashed "AI note · not checked" box, apart from rule-checked facts.

The call checklist ticks are saved in the browser's localStorage only. They aren't shared and aren't saved to the repo.
