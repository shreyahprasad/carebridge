# CareBridge

A tool for caseworkers at a DC immigrant and refugee support nonprofit. It helps them find accessible
mental health care for immigrant, refugee and asylum-seeking women, and make that care reachable:

1. **Provider match**: rules filter and tier 72 SAMHSA-listed DC-area providers by language, coverage,
   age and care mode; one Claude agent picks a shortlist; a validator checks every pick against the rules.
2. **Trip plan**: rules grade how reachable each provider is and which transport benefits apply
   (Medicaid rides, Metro Lift, Kids Ride Free); one Claude agent writes booking steps, checked the same way.
3. **Call script**: a fixed template, with no AI, built from the checked match and trip plan. It shares
   only safe client facts (never her name, phone, address, plan name or immigration status), asks every
   open question with coded answer slots, and lists the ride tasks for after the call.

All cases are synthetic. Program data is research, not independently verified.

## Setup

Python 3.14. Everything runs from this repo; the guarded Claude runtime is included in
`shreyah_harness/` (see its `NOTICE.md`).

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests      # offline tests, no API key needed
```

For live runs, put `ANTHROPIC_API_KEY=...` (and optionally `CLAUDE_MODEL=...`) in `.env`.

## Run

```sh
.venv/bin/python -m script case-001 --all            # match + trip + call script, scripted agents, offline
.venv/bin/python -m script case-001 --all --live     # real Claude agents (paid, up to 6 requests); writes data/runs/
.venv/bin/python -m script case-001                  # rebuild the call script from the latest run files
python3 -m http.server 8000                          # then open http://127.0.0.1:8000/ui/
```

`--rules-only` runs every stage without any model. Contracts for each stage are in `harness/contracts.md`.
