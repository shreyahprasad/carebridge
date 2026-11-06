"""Scripted (offline) trip-plan agent, plus a combined create for the two-stage workflow.

`tamper`: invent_benefit, drop_benefits, change_grade, drop_pick, drop_question, not_json, raise
"""
import json

from match.scripted import _response, scripted_model as match_model


def good_output(task):
    return {'plans': [{
        'provider_id': c['provider_id'], 'grade': c['grade'],
        'benefit_ids': [b['program_id'] for b in c['benefits']],
        'steps': [f'Scripted demo step for a {c["grade"]} trip.'],
        'tell_client': f'Scripted demo: this one is {c["grade"]} for you.',
        'questions': list(c['required_questions'])} for c in task['picks']]}


def scripted_trip(tamper=None, calls=None):
    def create(**kwargs):
        assert kwargs['system'].startswith('You are the CareBridge trip-plan specialist')
        assert kwargs.get('thinking') == {'type': 'adaptive'}, 'profile must declare thinking'
        assert not kwargs.get('tools'), 'trip-plan has no tools'
        task = json.loads(kwargs['messages'][0]['content'])
        if calls is not None:
            calls.append(task)
        out = good_output(task)
        first = out['plans'][0]
        if tamper == 'invent_benefit':
            used = set(first['benefit_ids'])
            first['benefit_ids'].append(next(p for p in ('wmata-metroaccess', 'transport-dc') if p not in used))
        elif tamper == 'drop_benefits':
            for p in out['plans']:
                p['benefit_ids'] = []
        elif tamper == 'change_grade':
            first['grade'] = 'walk' if first['grade'] != 'walk' else 'one_bus'
        elif tamper == 'drop_pick':
            out['plans'] = out['plans'][1:]
        elif tamper == 'drop_question':
            for p in out['plans']:
                p['questions'] = p['questions'][1:]
        elif tamper == 'raise':
            raise RuntimeError('simulated API failure')
        elif tamper == 'not_json':
            return _response('Take the bus.')
        return _response(json.dumps(out))
    return create


def scripted_workflow(trip_tamper=None, match_tamper=None, calls=None):
    """One create for both stages; dispatches on the system prompt. calls gets (stage, task)."""
    m_calls, t_calls = [], []
    m, t = match_model(match_tamper, m_calls), scripted_trip(trip_tamper, t_calls)

    def create(**kwargs):
        stage = 'trip' if kwargs['system'].startswith('You are the CareBridge trip-plan') else 'match'
        before = len(m_calls) + len(t_calls)
        r = (t if stage == 'trip' else m)(**kwargs)
        if calls is not None and len(m_calls) + len(t_calls) > before:
            calls.append((stage, (t_calls if stage == 'trip' else m_calls)[-1]))
        return r
    return create
