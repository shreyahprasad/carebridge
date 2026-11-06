"""Scripted (offline) provider-match agent. Deterministic stand-in for messages.create.

`tamper` makes it return a specific bad output, to test that the validator stops it:
  invent_id, raise_tier, false_fact, drop_question, extra_question, drop_tier_a, not_json, raise
"""
import json


def _response(text):
    return {'id': 'scripted', 'stop_reason': 'end_turn', 'usage': {'input_tokens': 0, 'output_tokens': 0},
            'content': [{'type': 'thinking', 'thinking': '', 'signature': 'sig'}, {'type': 'text', 'text': text}]}


def good_output(task):
    cands = task['candidates']
    picks = cands[:5]  # cards arrive sorted by tier then distance
    return {'shortlist': [{
        'provider_id': c['provider_id'], 'tier': c['tier'], 'facts': c['facts'][:4],
        'why': f'Tier {c["tier"]} option {c["distance_mi"]} miles away (scripted demo reasoning).',
        'questions': list(c['required_questions'])} for c in picks],
        'not_chosen_note': 'Scripted demo: kept the closest options in tier order.'}


def scripted_model(tamper=None, calls=None):
    def create(**kwargs):
        assert kwargs['system'].startswith('You are the CareBridge provider-match specialist')
        assert kwargs.get('thinking') == {'type': 'adaptive'}, 'profile must declare thinking'
        assert not kwargs.get('tools'), 'provider-match has no tools'
        task = json.loads(kwargs['messages'][0]['content'])
        if calls is not None:
            calls.append(task)
        out = good_output(task)
        first = out['shortlist'][0]
        if tamper == 'invent_id':
            first['provider_id'] = 'samhsa-invented-clinic-dc-20001'
        elif tamper == 'raise_tier':
            for p in out['shortlist']:
                if p['tier'] != 'A':
                    p['tier'] = 'A'
                    break
        elif tamper == 'false_fact':
            card = next(c for c in task['candidates'] if c['provider_id'] == first['provider_id'])
            missing = [f for f in ('domestic_violence_program', 'telehealth', 'sliding_fee', 'ptsd_program',
                                   'speaks_client_language', 'within_3_miles') if f not in card['facts']]
            first['facts'].append(missing[0])
        elif tamper == 'drop_question':
            for p in out['shortlist']:
                p['questions'] = [q for q in p['questions'] if q != 'woman_clinician'] or ['waitlist']
        elif tamper == 'extra_question':
            first['questions'].append(next(q for q in ('minor_consent', 'confirm_cost', 'interpreter')
                                           if q not in first['questions']))
        elif tamper == 'raise':
            raise RuntimeError('simulated API failure')
        elif tamper == 'drop_tier_a':
            out['shortlist'] = [p for p in out['shortlist'] if p['tier'] != 'A']
            extra = [c for c in task['candidates'] if c['tier'] != 'A'][len(out['shortlist']):][:1]
            out['shortlist'] += [{'provider_id': c['provider_id'], 'tier': c['tier'], 'facts': c['facts'][:2],
                                  'why': 'Scripted replacement pick.', 'questions': list(c['required_questions'])}
                                 for c in extra]
        elif tamper == 'not_json':
            return _response('Here are my picks: Gio Health first.')
        return _response(json.dumps(out))
    return create
