"""Provider-match workflow: case -> rules (filter + tier) -> provider-match agent -> validate -> MatchResult.

MatchResult is the handoff to the transportation stage. Provider facts in it
(name, address, phone, lat/lng) come from the provider record, never from the model.
Modes: live (real Claude), scripted (offline demo agent), rules_only (no agent,
or the agent's output was rejected/failed).
"""
from datetime import date
import json
import os
from pathlib import Path
from uuid import uuid4

from shreyah_harness.guardrails import Policy, SensitiveData
from shreyah_harness.runtime import Budget, Runtime

from . import agent, rules
from .models import MatchResult

STAGE_BUDGET = dict(max_requests=3, max_tools=0, max_retries=1, seconds=240)
RESULT_VERSION = 'match-result-v1'


def default_runtime(audit=None):
    secrets = tuple(v for v in [os.environ.get('ANTHROPIC_API_KEY')] if v)
    return Runtime(actor='carebridge-match', policy=Policy(privacy=SensitiveData(secrets=secrets)), audit=audit)


def _rules_shortlist(cands):
    """Fallback: every tier A, then nearest by tier, up to MAX_PICKS."""
    picks = cands[:agent.MAX_PICKS]
    return [{'provider_id': c['provider']['id'], 'tier': c['tier'], 'facts': c['facts'],
             'why': None, 'questions': c['required_questions'], 'extra_questions': []} for c in picks], None


def _pick(c, chosen, rank):
    p = c['provider']
    return {
        'rank': rank,
        'provider_id': p['id'], 'name': p['name'], 'tier': c['tier'],
        # Record fields (trusted source data) for the caseworker and the transport stage.
        'address': p['address'], 'state': p['state'], 'lat': p['lat'], 'lng': p['lng'],
        'distance_mi': c['distance_mi'], 'phone': p['phone'], 'intake_phone': p['intake_phone'],
        'website': p['website'], 'languages': p['languages'], 'telehealth': p['telehealth'],
        'facts': [{'code': f, 'text': rules.fact_text(f, c['required_questions'])} for f in chosen['facts']],
        'tier_basis': c['tier_basis'],
        'why': chosen['why'],  # model-written, not checked; None in rules_only
        'questions': [{'code': q, 'text': c['question_texts'][q]} for q in chosen['questions']],
        'extra_questions': chosen.get('extra_questions', []),  # model-written, not checked
        'decision': c['decision'],
        'source': {'name': p['source']['name'], 'url': p['source']['url'], 'retrieved': p['source']['retrieved']},
    }


def run_match(case, create=None, *, model, live=False, runtime=None, budget=None, correlation_id=None,
              providers=None, data_version=None, out_dir=None, fallback=True, log=print):
    """Return a validated MatchResult as a JSON-ready dict (or None if the agent failed and fallback=False).

    case: a models.Case or a dict (checked against models.Case; bad input raises before any model call).

    create=None means rules only. Pass a shared runtime/budget/correlation_id when
    this runs as one stage of a larger workflow.
    """
    case = rules.as_case(case)
    if providers is None:
        providers, data_version = rules.load_providers()
    correlation_id = correlation_id or uuid4().hex[:12]
    budget = budget or Budget(**STAGE_BUDGET)
    needs, cands, counts = rules.candidates(case, providers, data_version)
    by_id = {c['provider']['id']: c for c in cands}
    log(f'[{correlation_id}] rules: {counts} for {case.id}')
    stage = {'stage': 'provider-match', 'profile': None, 'run_id': None, 'status': 'skipped', 'reason': None,
             'requests': 0, 'tools': 0}

    shortlist, note, mode, fallback_reason = None, None, 'rules_only', None
    if create is not None and cands:
        runtime = runtime or default_runtime()
        result = agent.profile(model).run(
            runtime, create, task=agent.task(rules.agent_view(needs), [rules.card(c, needs) for c in cands]),
            budget=budget, validate_output=agent.validator(cands), output_retries=1, max_tokens=6000)
        run = result['run']
        stage.update(profile=run.get('profile', {}).get('name'), run_id=run['run_id'], status=run['status'],
                     reason=run['reason'], requests=run['requests'], tools=run['tools'])
        log(f'[{correlation_id}] provider-match agent: {run["status"]} {run["reason"] or ""}'.rstrip())
        if run['status'] == 'complete':
            shortlist, note = result['output']['shortlist'], result['output']['not_chosen_note']
            mode = 'live' if live else 'scripted'
        else:
            fallback_reason = run['reason'] or run['status']
            if not fallback:
                return None
    elif create is not None:
        fallback_reason = 'no_candidates'

    if shortlist is None:
        shortlist, note = _rules_shortlist(cands)

    report = {
        'version': RESULT_VERSION, 'correlation_id': correlation_id, 'case_id': case.id,
        'synthetic': case.synthetic, 'date': date.today().isoformat(),
        'mode': mode, 'fallback_reason': fallback_reason, 'model': model if mode != 'rules_only' else None,
        'prompt_version': agent.PROMPT_VERSION if mode != 'rules_only' else None,
        'rule_version': rules.RULE_VERSION, 'data_version': data_version,
        'needs': rules.agent_view(needs),
        'counts': counts,
        'picks': [_pick(by_id[s['provider_id']], s, i + 1) for i, s in enumerate(shortlist)],
        'not_chosen_note': note,
        'unchecked_fields': ['picks[].why', 'picks[].extra_questions', 'not_chosen_note'],
        'stages': [stage],
        'budget_used': {'requests': budget.requests, 'tools': budget.tools},  # workflow totals so far (shared Budget)
    }
    # Contract check before anything leaves this stage; a break raises and nothing is written.
    report = MatchResult.model_validate(report).model_dump(mode='json')
    if out_dir is not None:
        # The mode is in the name, so a live run that fell back is visible at a glance.
        path = Path(out_dir) / f'{report["date"]}-{case.id}-{report["mode"]}-{correlation_id}.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
        report['path'] = str(path)
        log(f'[{correlation_id}] wrote {path}')
    return report
