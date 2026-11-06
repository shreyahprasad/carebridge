"""Call script: build it from a checked match + trip handoff, and the three-stage workflow.

build_script reads the trip plan only through trip.models.TripPlan, re-checks the match
handoff (trip.workflow.check_handoff) and recomputes every trip stop from the rules
(check_trip_handoff). A broken handoff raises HandoffError and nothing is written.
No model call: the script is a fixed template, so it is instant, free and offline.
"""
from datetime import date
import json
from pathlib import Path
from uuid import uuid4

from shreyah_harness.runtime import Budget

from match import rules as match_rules
from match.output import write_run
from trip import benefits as ben
from trip import reach
from trip import workflow as trip_wf
from trip.models import TripPlan
from trip.workflow import WORKFLOW_BUDGET, HandoffError, default_runtime

from . import rules
from .models import NO_CALL, CallScript

RESULT_VERSION = 'call-script-v1'

__all__ = ['HandoffError', 'build_script', 'check_trip_handoff', 'script_from_latest', 'run_workflow']


def _strip(d):
    return {k: v for k, v in d.items() if k != 'path'} if isinstance(d, dict) else d


def check_trip_handoff(trip_plan, match_result, case, providers, programs, programs_version, correlation_id=None):
    """Validate the TripPlan contract, re-check the match handoff, and recompute every stop from rules.
    Returns (MatchResult, TripPlan)."""
    try:
        tp = trip_plan if isinstance(trip_plan, TripPlan) else TripPlan.model_validate(_strip(trip_plan))
    except Exception as e:
        raise HandoffError(f'trip plan breaks contract: {e.__class__.__name__}') from e
    mr = trip_wf.check_handoff(_strip(match_result), case, providers, correlation_id)
    if tp.case_id != case.id:
        raise HandoffError('trip plan is for another case')
    if tp.correlation_id != mr.correlation_id:
        raise HandoffError('trip plan belongs to another workflow run')
    benefits = ben.case_benefits(case, programs, programs_version)
    if [b.program_id.value for b in tp.benefits] != [b['program_id'] for b in benefits]:
        raise HandoffError('trip benefits differ from the rules')
    _, stops = trip_wf._stops(mr, case, benefits, providers)
    by_id = {s['pick']['provider_id']: s for s in stops}
    if {p.provider_id for p in tp.plans} != set(by_id):
        raise HandoffError('trip plans are not exactly the match picks')
    for p in tp.plans:
        s = by_id[p.provider_id]
        if p.grade.value != s['grade'] or p.match_rank != s['pick']['rank']:
            raise HandoffError('trip grade or rank differs from the rules')
        if [u.model_dump(mode='json') for u in p.benefits] != s['uses']:
            raise HandoffError('trip benefits per pick differ from the rules')
        if [q.code.value for q in p.questions] != s['required_questions']:
            raise HandoffError('trip questions differ from the rules')
        if ([q.text for q in p.questions] != [reach.question_text(c, s['pick'], benefits) for c in s['required_questions']]
                or p.grade_basis != s['grade_basis']):
            raise HandoffError('trip question text or grade basis differs from the rules')
        for f in ('name', 'address', 'state'):
            if getattr(p, f) != s['pick'][f]:
                raise HandoffError(f'trip {f} differs from the match pick')
    return mr, tp


def _calls(case, mr, tp, providers):
    """Top MAX_CALLS reachable providers in trip order, with rule questions; the rest are skipped."""
    n = match_rules.needs(case)
    recs = {p['id']: p for p in providers}
    picks = {p.provider_id: p for p in mr.picks}
    calls, skipped = [], []
    for plan in tp.plans:  # already in trip order
        p = plan.model_dump(mode='json')
        base = {'provider_id': p['provider_id'], 'name': p['name'], 'trip_order': p['order'], 'grade': p['grade']}
        if plan.grade in NO_CALL:
            skipped.append({**base, 'reason': p['grade_basis'] + ' No call.'})
        elif len(calls) >= rules.MAX_CALLS:
            skipped.append({**base, 'reason': f'Beyond the top {rules.MAX_CALLS}; call if those fall through.'})
        else:
            rec = recs[p['provider_id']]
            qs = rules.call_questions(n, rec, [q.code.value for q in picks[p['provider_id']].questions], p)
            calls.append({**base, 'order': len(calls) + 1, 'phone': rec['phone'], 'intake_phone': rec['intake_phone'],
                          'address': rec['address'], 'state': rec['state'], 'questions': qs,
                          'after_call': rules.after_call(p),
                          'answers': [{'code': q['code'], 'answer': None, 'note': None} for q in qs]})
    return calls, skipped


def build_script(case, match_result, trip_plan, *, correlation_id=None, providers=None, programs=None,
                 programs_version=None, out_dir=None, log=print):
    """Return a validated CallScript dict. Raises HandoffError if the match or trip handoff is not valid."""
    case = match_rules.as_case(case)
    if providers is None:
        providers, _ = match_rules.load_providers()
    if programs is None:
        programs, programs_version = ben.load_programs()
    mr, tp = check_trip_handoff(trip_plan, match_result, case, providers, programs, programs_version, correlation_id)
    calls, skipped = _calls(case, mr, tp, providers)
    disclosures = rules.disclosures(case)
    report = {
        'version': RESULT_VERSION, 'correlation_id': tp.correlation_id, 'case_id': case.id,
        'synthetic': case.synthetic, 'date': date.today().isoformat(), 'rule_version': rules.RULE_VERSION,
        'match_mode': mr.mode.value, 'trip_mode': tp.mode.value, 'trip_plan_version': tp.version,
        'client_placeholder': '[client]', 'guidelines': rules.guidelines(), 'opening': rules.OPENING,
        'disclosures': disclosures, 'client_summary': ' '.join(d['text'] for d in disclosures),
        'closing': rules.CLOSING, 'calls': calls, 'skipped': skipped,
    }
    report = CallScript.model_validate(report).model_dump(mode='json')
    log(f'[{tp.correlation_id}] call script: {len(calls)} calls, {len(skipped)} skipped')
    if out_dir is not None:
        path = write_run(report, out_dir, f'{report["date"]}-{case.id}-{tp.correlation_id}.json', CallScript)
        report['path'] = str(path)
        log(f'[{tp.correlation_id}] wrote {path}')
    return report


def script_from_latest(case, runs_dir, out_dir=None, log=print):
    """Build the script from <runs_dir>/match/ and trip/<case_id>-latest.json (what the UI shows).
    Raises FileNotFoundError if either is missing, ValueError if corrupt, HandoffError if they don't fit
    together; on any failure the old script -latest.json is removed."""
    case = match_rules.as_case(case)
    runs = Path(runs_dir)
    out = runs / 'script' if out_dir is None else Path(out_dir)
    try:
        m = json.loads((runs / 'match' / f'{case.id}-latest.json').read_text())
        t = json.loads((runs / 'trip' / f'{case.id}-latest.json').read_text())
        return build_script(case, m, t, out_dir=out, log=log)
    except (OSError, ValueError):  # missing, corrupt, or a broken handoff (HandoffError is a ValueError)
        # An older script would belong to a run that is no longer the latest; don't leave it for the page.
        (out / f'{case.id}-latest.json').unlink(missing_ok=True)
        raise


def run_workflow(case, create=None, *, model, live=False, runtime=None, budget=None, correlation_id=None,
                 match_out=None, trip_out=None, out_dir=None, log=print):
    """Match, trip plan, call script with one Runtime, Budget and correlation id. Returns (match, trip, script).
    Only match and trip call a model; the script never does."""
    case = match_rules.as_case(case)
    correlation_id = correlation_id or uuid4().hex[:12]
    budget = budget or Budget(**WORKFLOW_BUDGET)
    if create is not None:
        runtime = runtime or default_runtime()
    m, t = trip_wf.run_workflow(case, create, model=model, live=live, runtime=runtime, budget=budget,
                                correlation_id=correlation_id, match_out=match_out, out_dir=trip_out, log=log)
    s = build_script(case, _strip(m), _strip(t), correlation_id=correlation_id, out_dir=out_dir, log=log)
    return m, t, s
