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

## Provider match · v1 (approved 2026-11-06)

- Command: `.venv/bin/python -m match <case-id> [--live | --rules-only] [--out DIR]`; function `match.workflow.run_match(case, create, model=..., budget=, correlation_id=, runtime=)`.
- Rules (app code, `match/rules.py`, `match-rules-v1`): hard filters = in area, serves age group, in person + known location when she needs in person, telehealth when she needs telehealth, trauma program for refugee/asylum or explicit preference, no tier C when `interpreter_ok` is false. Tiers A/B/C as in the module docstring. Dari maps to Farsi. Unknowns (woman clinician, interpreter, waitlist, Dari only when matched via Farsi, DC Medicaid for out-of-state Medicaid providers, coverage/cost when the listing shows no Medicaid for a Medicaid client or for any non-Medicaid client, minor consent, perinatal, childcare) are required call-question codes, never filters. Question text is built per case and provider (`question_text`), never fixed to one client.
- Agent `provider-match` v2, prompt `provider-match-v2` (v2: no telehealth fact/card field when care_mode is in_person; no speculative or unusable reasons): no tools, no web, adaptive thinking, effort medium, max_tokens 6000, 1 output repair. Input = needs profile (no name, phone, address, coordinates, immigration status or plan name) + candidate cards. Output = 3-5 picks `{provider_id, tier, facts[code], why, questions[code], extra_questions[]}` + `not_chosen_note`.
- Validator: ids in candidate set and unique; at least min(3, candidates); tier equals rules tier; facts subset of the provider's true facts; question codes exactly the required set; every tier A included. `why`, `extra_questions`, `not_chosen_note` are unchecked model text (listed in `unchecked_fields`).
- Failure: agent error or rejected output -> `mode: rules_only` with `fallback_reason` (tier then distance, `why: null`); with `fallback=False` returns None and writes nothing.
- Handoff `MatchResult` (`match-result-v1`): `{correlation_id, case_id, mode, fallback_reason, rule_version, data_version, prompt_version, model, needs, counts, picks[{rank, provider_id, name, tier, address, state, lat, lng, distance_mi, phone, intake_phone, website, facts[{code,text}], questions[{code,text}], why, decision, source}], stages, budget_used}`. All provider fields are copied from `data/providers.json`. Transportation consumes `picks[].provider_id/lat/lng/address` only from a MatchResult.
- Budget: stage default 3 requests / 0 tools / 240 s; pass the workflow Budget to share it. `budget_used` = shared Budget totals so far; per-stage counts are in `stages`.
- Files: `<date>-<case>-<mode>-<correlation>.json`; a live run that fell back is named `-rules_only-` and the CLI exits 1. Free-text concerns are scrubbed of the client's and caseworker's name, phone, address and email before reaching the agent.
- Typed edges (`match/models.py`, pydantic 2.14.3 from the Anthropic SDK): `Case` checked at run start (bad input raises before any model call), `Provider` at load, `MatchResult` before return/write; transportation reads with `load_match_result(path)`. `extra='forbid'`. StrEnums: EnglishLevel, CareMode, InsuranceType, Coverage, ProviderGender, Urgency, Tier, Mode, Fact, Question; the agent JSON Schema lists are generated from Tier/Fact/Question.
- Evidence: `tests/test_match.py` (37 offline tests, 57 total); `runtime-check match` passed; `sh-code-reviewer` findings 1-9 fixed with tests. Live: case-001 with prompt v1 completed in 1 request, validated (`data/runs/match/2026-11-06-case-001-866d1e5d6fcd.json`); prompt v2 not yet run live.

## Transport benefits and trip plan · v1 (approved 2026-11-06)

- Command: `.venv/bin/python -m trip <case-id> [--live | --rules-only] [--out DIR]` runs provider match then trip plan. Functions: `trip.workflow.run_workflow(case, create, model=, budget=, correlation_id=, runtime=)` and `run_trip(case, match_result, create, ...)`.
- Benefits (`trip/benefits.py`, `trip-rules-v1`, app code only): one `decision` per transportation record in `programs.json`, from the trusted `Case` (plan name never comes from the agent or the MatchResult). AmeriHealth / MedStar NEMT by DC Medicaid + plan; FFS NEMT = DC Medicaid with no plan; HSCSN by plan; Metro Lift = SNAP; Kids Ride Free = age 5-21 + DC address + DC school; MetroAccess and Transport DC = unknown (no disability field), so not eligible. Every benefit carries sources, confidence and "Research data, not independently verified".
- Per pick: NEMT is `likely` only for a DC provider listing Medicaid, otherwise `if_confirmed` with `provider_dc_medicaid_enrolled`; Kids Ride Free is DC picks only and always `if_confirmed` with `kids_ride_free_medical`; fare programs skip `walk` picks; `drive`, `unknown` and `not_realistic` picks get no benefits or questions.
- Reachability (`trip/reach.py`, straight-line miles): `walk` under 0.5 mi and she walks (owner changed from ≤1 mi after the first live run: 0.7 mi is not walkable); `one_bus` ≤4 mi with Metro/Metrobus; `hard` ≤8 mi with transit; `drive` ≤25 mi with a car; `unknown` no location; `not_realistic` otherwise, or out of DC with no car and a child under 6. Times are labeled estimates; no live routing.
- Handoff check (`check_handoff`, before any model call): `MatchResult.model_validate`, same case and correlation id, every pick a known provider with name/address/state/lat/lng equal to `providers.json`, distance within 0.15 mi of a recomputation from her coordinates. Any break raises `HandoffError`; the trip agent is not called and nothing is written.
- Agent `trip-plan` v2, prompt `trip-plan-v2` (v2: items to bring only from benefit notes; lead times as the notes state them; no language or interpreter advice, after the first live run said "ask for a Dari interpreter" for a tier A Farsi-listing pick and added an ID/insurance-card list): no tools, adaptive thinking, effort medium, max_tokens 6000, 1 output repair. Input = trip-relevant needs (no concerns text, name, address, coordinates, status) + pick cards (id, name, address, state, tier, distance, grade, benefits, required questions) + benefit booking notes. Output per pick `{provider_id, grade, benefit_ids, steps[], tell_client, questions[code], extra_questions[]}`. Validator: every pick exactly once, grade unchanged, benefit ids exactly that pick's, question codes exactly the required set. `steps`, `tell_client`, `extra_questions` are unchecked.
- Failure: rejected or failed output, or a shared Budget already spent by match -> `mode: rules_only` with `fallback_reason` (grades + benefits, no prose).
- Result `TripPlan` (`trip-plan-v1`, `trip/models.py`): plans ordered by grade then match rank; `stages` = match stages + trip stage; `budget_used` = shared Budget totals. File `data/runs/trip/<date>-<case>-<match mode>-<trip mode>-<correlation>.json`; the CLI exits 1 if either stage fell back.
- Workflow Budget: 6 requests / 0 tools / 2 retries / 480 s, shared by both stages, one Runtime (`actor='carebridge'`).
- Handoff check also recomputes `needs` from the Case and each pick's tier, true facts and required questions from the provider record; NEMT `likely` uses the record's `payment.medicaid`, not the facts the match agent chose. The agent must echo exactly the pick's benefit ids; the result always carries the rules' list.
- Evidence: `tests/test_trip.py` (31 offline tests, 88 total); `runtime-check trip match` passed; `sh-code-reviewer` findings 1-3 fixed with tests. Live: case-001 with prompt v1, both stages complete in 1 request each, validated (`data/runs/trip/2026-11-06-case-001-live-live-994ee988f800.json`); prompt v2 not yet run live.
