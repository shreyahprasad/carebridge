"""Trip stage and the combined match -> trip workflow.

run_trip reads the provider match only through match.models.MatchResult and
cross-checks every pick against providers.json and the trusted Case before any
model call (check_handoff). A broken handoff raises HandoffError; nothing downstream runs.
run_workflow runs both stages with one Runtime, one Budget and one correlation id.
"""
from datetime import date
import os
from uuid import uuid4

from shreyah_harness.guardrails import Policy, SensitiveData
from shreyah_harness.runtime import Budget, Runtime

from match import rules as match_rules
from match.models import MatchResult
from match.output import write_run
from match.workflow import run_match

from . import agent, benefits as ben, reach
from .models import GRADE_ORDER, TripPlan

WORKFLOW_BUDGET = dict(max_requests=6, max_tools=0, max_retries=2, seconds=480)
STAGE_BUDGET = dict(max_requests=3, max_tools=0, max_retries=1, seconds=240)
RESULT_VERSION = 'trip-plan-v1'
DISTANCE_TOLERANCE_MI = 0.15


class HandoffError(ValueError):
    """The match result is not a valid, trustworthy handoff for this case."""


def default_runtime(audit=None):
    secrets = tuple(v for v in [os.environ.get('ANTHROPIC_API_KEY')] if v)
    return Runtime(actor='carebridge', policy=Policy(privacy=SensitiveData(secrets=secrets)), audit=audit)


def check_handoff(match_result, case, providers, correlation_id=None):
    """Validate the MatchResult contract, then check it against trusted data. Returns a MatchResult."""
    try:
        mr = match_result if isinstance(match_result, MatchResult) else MatchResult.model_validate(match_result)
    except Exception as e:
        raise HandoffError(f'match result breaks contract: {e.__class__.__name__}') from e
    if mr.case_id != case.id:
        raise HandoffError('match result is for another case')
    if correlation_id and mr.correlation_id != correlation_id:
        raise HandoffError('match result belongs to another workflow run')
    n = match_rules.needs(case)
    if mr.needs.model_dump(mode='json') != match_rules.agent_view(n):
        raise HandoffError('match needs differ from the case')
    by_id = {p['id']: p for p in providers}
    for pick in mr.picks:
        rec = by_id.get(pick.provider_id)
        if rec is None:
            raise HandoffError('pick is not a known provider')
        ev = match_rules.evaluate(n, rec, mr.data_version)
        if (not ev['decision']['eligible'] or ev['tier'] != pick.tier
                or not {f.code.value for f in pick.facts} <= set(ev['facts'])
                or {q.code.value for q in pick.questions} != set(ev['required_questions'])):
            raise HandoffError('pick tier, facts or questions differ from the rules')
        for f in ('name', 'address', 'state', 'lat', 'lng'):
            if getattr(pick, f) != rec[f]:
                raise HandoffError(f'pick {f} differs from the provider record')
        if pick.lat is not None and pick.lng is not None:
            d = match_rules.miles(case.lat, case.lng, pick.lat, pick.lng)
            if pick.distance_mi is None or abs(d - pick.distance_mi) > DISTANCE_TOLERANCE_MI:
                raise HandoffError('pick distance does not match her location')
        elif pick.distance_mi is not None:
            raise HandoffError('distance without coordinates')
    return mr


def _stops(mr, case, benefits, providers):
    n = mr.needs.model_dump(mode='json')  # checked equal to the case's needs in check_handoff
    by_id = {p['id']: p for p in providers}
    out = []
    for pick in mr.picks:
        p = pick.model_dump(mode='json')
        g, basis = reach.grade(n, case, p)
        uses = ben.pick_benefits(benefits, p, g.value, by_id[p['provider_id']]['payment']['medicaid'])
        qs = reach.required_questions(n, case, uses, g)
        out.append({'pick': p, 'grade': g.value, 'grade_basis': basis, 'uses': uses,
                    'benefit_ids': [u['program_id'] for u in uses], 'required_questions': qs})
    return n, out


def _needs_view(n):
    """Trip-relevant needs only (no concerns text)."""
    keys = ('languages', 'english_level', 'minor', 'needs_in_person', 'childcare_needed', 'has_car',
            'transportation', 'urgency', 'pregnant')
    return {k: n[k] for k in keys}


def _card(s):
    p = s['pick']
    return {'provider_id': p['provider_id'], 'name': p['name'], 'address': p['address'], 'state': p['state'],
            'tier': p['tier'], 'distance_mi': p['distance_mi'], 'grade': s['grade'], 'grade_basis': s['grade_basis'],
            'benefits': s['uses'], 'required_questions': s['required_questions']}


def _stop(s, chosen, benefits):
    p = s['pick']
    return {
        'match_rank': p['rank'], 'provider_id': p['provider_id'], 'name': p['name'], 'address': p['address'],
        'state': p['state'], 'tier': p['tier'], 'distance_mi': p['distance_mi'],
        'grade': s['grade'], 'grade_basis': s['grade_basis'], 'time_estimate': reach.MINUTES[reach.Grade(s['grade'])],
        'benefits': s['uses'],  # always the rules' list
        'steps': chosen['steps'] if chosen else None,
        'tell_client': chosen['tell_client'] if chosen else None,
        'questions': [{'code': q, 'text': reach.question_text(q, p, benefits)} for q in s['required_questions']],
        'extra_questions': chosen.get('extra_questions', []) if chosen else [],
    }


def run_trip(case, match_result, create=None, *, model, live=False, runtime=None, budget=None, correlation_id=None,
             providers=None, programs=None, programs_version=None, out_dir=None, fallback=True, log=print):
    """Return a validated TripPlan dict (or None if the agent failed and fallback=False).
    Raises HandoffError before any model call if the match result is not valid for this case."""
    case = match_rules.as_case(case)
    if providers is None:
        providers, _ = match_rules.load_providers()
    if programs is None:
        programs, programs_version = ben.load_programs()
    mr = check_handoff(match_result, case, providers, correlation_id)
    correlation_id = mr.correlation_id
    budget = budget or Budget(**STAGE_BUDGET)
    benefits = ben.case_benefits(case, programs, programs_version)
    n, stops = _stops(mr, case, benefits, providers)
    log(f'[{correlation_id}] trip rules: benefits {[b["program_id"] for b in benefits]}, '
        f'grades {[s["grade"] for s in stops]}')
    stage = {'stage': 'trip-plan', 'profile': None, 'run_id': None, 'status': 'skipped', 'reason': None,
             'requests': 0, 'tools': 0}

    chosen, mode, fallback_reason = None, 'rules_only', None
    if create is not None and stops:
        runtime = runtime or default_runtime()
        result = agent.profile(model).run(
            runtime, create, task=agent.task(_needs_view(n), [_card(s) for s in stops], benefits),
            budget=budget, validate_output=agent.validator({s['pick']['provider_id']: s for s in stops}),
            output_retries=1, max_tokens=6000)
        run = result['run']
        stage.update(profile=run.get('profile', {}).get('name'), run_id=run['run_id'], status=run['status'],
                     reason=run['reason'], requests=run['requests'], tools=run['tools'])
        log(f'[{correlation_id}] trip-plan agent: {run["status"]} {run["reason"] or ""}'.rstrip())
        if run['status'] == 'complete':
            chosen = {p['provider_id']: p for p in result['output']['plans']}
            mode = 'live' if live else 'scripted'
        else:
            fallback_reason = run['reason'] or run['status']
            if not fallback:
                return None
    elif create is not None:
        fallback_reason = 'no_picks'

    plans = [_stop(s, chosen[s['pick']['provider_id']] if chosen else None, benefits) for s in stops]
    plans.sort(key=lambda s: (GRADE_ORDER.index(s['grade']), s['match_rank']))
    for i, s in enumerate(plans):
        s['order'] = i + 1

    report = {
        'version': RESULT_VERSION, 'correlation_id': correlation_id, 'case_id': case.id,
        'synthetic': case.synthetic, 'date': date.today().isoformat(),
        'mode': mode, 'fallback_reason': fallback_reason,
        'model': model if mode != 'rules_only' else None,
        'prompt_version': agent.PROMPT_VERSION if mode != 'rules_only' else None,
        'rule_version': ben.RULE_VERSION, 'programs_version': programs_version,
        'match_mode': mr.mode.value, 'match_result_version': mr.version,
        'thresholds': reach.THRESHOLDS, 'benefits': benefits, 'plans': plans,
        'unchecked_fields': ['plans[].steps', 'plans[].tell_client', 'plans[].extra_questions'],
        'stages': [s.model_dump(mode='json') for s in mr.stages] + [stage],
        'budget_used': {'requests': budget.requests, 'tools': budget.tools},
    }
    report = TripPlan.model_validate(report).model_dump(mode='json')
    if out_dir is not None:
        path = write_run(report, out_dir,
                         f'{report["date"]}-{case.id}-{report["match_mode"]}-{report["mode"]}-{correlation_id}.json',
                         TripPlan)
        report['path'] = str(path)
        log(f'[{correlation_id}] wrote {path}')
    return report


def run_workflow(case, create=None, *, model, live=False, runtime=None, budget=None, correlation_id=None,
                 match_out=None, out_dir=None, log=print):
    """Provider match then trip plan: one Runtime, one Budget, one correlation id. Returns (match, trip)."""
    case = match_rules.as_case(case)
    correlation_id = correlation_id or uuid4().hex[:12]
    budget = budget or Budget(**WORKFLOW_BUDGET)
    if create is not None:
        runtime = runtime or default_runtime()
    providers, data_version = match_rules.load_providers()
    m = run_match(case, create, model=model, live=live, runtime=runtime, budget=budget,
                  correlation_id=correlation_id, providers=providers, data_version=data_version,
                  out_dir=match_out, log=log)
    handoff = {k: v for k, v in m.items() if k != 'path'}  # file path is not part of the contract
    t = run_trip(case, handoff, create, model=model, live=live, runtime=runtime, budget=budget,
                 correlation_id=correlation_id, providers=providers, out_dir=out_dir, log=log)
    return m, t
