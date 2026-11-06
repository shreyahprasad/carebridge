"""Deterministic provider matching (app code, never the model).

needs(case)            -> minimal needs profile (no name, phone, address or immigration details)
evaluate(needs, p)     -> hard-filter decision, tier, true facts and required call questions
candidates(case)       -> eligible providers, tiered and sorted

Tiers (owner-approved 2026-11-06):
  A  speaks her language, in DC, coverage matches
  B  speaks her language, but MD/VA (confirm DC Medicaid) or cost to confirm
  C  in DC, coverage matches, interpreter needed
SAMHSA has no clinician gender, interpreter, waitlist or Dari data. Those are
never filters; they become required call questions.
"""
import hashlib
import json
import math
import re
from pathlib import Path

from shreyah_harness.decisions import Predicate, decision

from .models import Case, CareMode, Coverage, Fact, Provider, ProviderGender, Question

ROOT = Path(__file__).resolve().parent.parent
PROVIDERS_PATH = ROOT / 'data' / 'providers.json'
CASES_PATH = ROOT / 'data' / 'cases.json'
RULE_VERSION = 'match-rules-v1'

# SAMHSA language list has no Dari; Farsi is the closest listed (confirm on call).
LANGUAGE_ALIASES = {'Dari': 'Farsi'}
NEAR_MILES = 3.0

# Facts the agent may cite. Each is computed from the provider record here, so
# the validator can check every cited fact is true for that provider.
FACTS = {
    'speaks_client_language': 'Lists her language',
    'in_dc': 'Located in DC',
    'accepts_medicaid': "Accepts Medicaid (the facility's state plan)",
    'sliding_fee': 'Sliding fee scale',
    'payment_assistance': 'Payment assistance',
    'public_funds': 'Accepts public funding',
    'in_person': 'In-person outpatient care',
    'telehealth': 'Offers telehealth',
    'trauma_program': 'Trauma program',
    'ptsd_program': 'PTSD program',
    'domestic_violence_program': 'Domestic violence program',
    'serves_age_group': 'Serves her age group',
    'within_3_miles': f'Within {NEAR_MILES:g} miles of her',
}

# Call questions. Labels here; the text actually shown is built per case and
# provider by question_text(), so it never states something untrue about her.
QUESTIONS = {
    'woman_clinician': 'Woman clinician available',
    'interpreter': 'Interpreter for her language',
    'dari_speaker': 'Clinician speaks Dari (listing says Farsi)',
    'confirm_dc_medicaid': 'Accepts DC Medicaid (out-of-state provider)',
    'confirm_cost': 'Coverage and cost',
    'waitlist': 'Wait for a first appointment',
    'minor_consent': 'Minor can consent to care',
    'perinatal': 'Sees pregnant clients',
    'childcare': 'Child can come along / childcare',
}


def question_text(code, n, p):
    lang = ' or '.join(n['languages'])
    if code == 'woman_clinician':
        return 'Is a woman clinician available for her?'
    if code == 'interpreter':
        return f'Do you provide a {lang} interpreter at no cost to her?'
    if code == 'dari_speaker':
        return 'Your listing says Farsi. Does the clinician speak Dari?'
    if code == 'confirm_dc_medicaid':
        return f"You are in {p['state']}. Do you accept DC Medicaid, not only {p['state']} Medicaid?"
    if code == 'confirm_cost':
        if n['coverage'] == Coverage.medicaid:
            return 'Your listing does not show Medicaid. Do you accept DC Medicaid? If not, what would she pay?'
        if n['coverage'] == Coverage.uninsured:
            return 'She is uninsured. What would she pay per session, and is there a sliding fee, free option or payment help?'
        return 'Do you accept her coverage? What would she pay per session, and is there a sliding fee or payment help?'
    if code == 'waitlist':
        return 'How long is the wait for a first appointment?'
    if code == 'minor_consent':
        return f"She is {n['age']}. Can she start care without a parent or legal guardian's signature?"
    if code == 'perinatal':
        return 'Do you see clients who are pregnant?'
    if code == 'childcare':
        return 'Can she bring her young child, or is childcare available during sessions?'
    raise KeyError(code)


assert set(FACTS) == set(Fact) and set(QUESTIONS) == set(Question)


def load_providers(path=PROVIDERS_PATH):
    """Every record is checked against models.Provider; returns plain dicts + data version."""
    raw = Path(path).read_bytes()
    records = json.loads(raw)
    for r in records:
        Provider.model_validate(r)
    return records, 'samhsa-' + hashlib.sha256(raw).hexdigest()[:12]


def load_cases(path=CASES_PATH):
    """Every case is checked against models.Case."""
    return {c['id']: Case.model_validate(c) for c in json.loads(Path(path).read_text())}


def as_case(case):
    return case if isinstance(case, Case) else Case.model_validate(case)


def miles(lat1, lng1, lat2, lng2):
    r = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2 +
         math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(a))


def _age_groups(age):
    if age < 18:
        return ['children_adolescents']
    if age <= 25:
        return ['young_adults', 'adults']
    return ['adults']


def needs(case):
    """Matching inputs only. This is all the agent sees about the client."""
    case = as_case(case)
    prefs = case.preferences
    status = case.immigration_status.lower()
    forced = any(w in status for w in ('refugee', 'asylum', 'asylee'))
    return {
        'case_id': case.id,
        'languages': list(case.languages),
        'english_level': case.english_level.value,
        'age': case.age,
        'age_groups': _age_groups(case.age),
        'minor': case.age < 18,
        'coverage': case.coverage.value,
        'care_mode': case.care_mode_needed.value,
        'needs_in_person': case.care_mode_needed in (CareMode.in_person, CareMode.in_person_preferred),
        'trauma_informed': forced if prefs.trauma_informed is None else prefs.trauma_informed,
        'provider_gender': prefs.provider_gender.value,
        'interpreter_ok': prefs.interpreter_ok,
        'pregnant': case.pregnant,
        'childcare_needed': case.childcare_during_appointments == 'needed',
        'has_car': case.has_car,
        'transportation': list(case.transportation_options),
        'concerns': _scrub(case.mental_health_concerns, case),
        'urgency': case.urgency.value,
        # Coordinates are used by app code only (distance); not sent to the agent.
        '_lat': case.lat, '_lng': case.lng,
    }


def _scrub(text, case):
    """Free text goes to the agent, so remove identifiers a caseworker might type into it."""
    for value in (case.first_name, case.last_name, case.phone, case.address,
                  case.caseworker.name, case.caseworker.email):
        if value and len(value) >= 2:
            text = re.sub(re.escape(value), '[redacted]', text, flags=re.I)
    return text


def agent_view(n):
    return {k: v for k, v in n.items() if not k.startswith('_')}


def fact_text(code, required_questions):
    if code == 'speaks_client_language' and 'dari_speaker' in required_questions:
        return 'Lists Farsi (closest listed language to Dari)'
    return FACTS[code]


def _ev(p, field):
    return (f"{p['id']}#{field}",)


def evaluate(n, p, data_version):
    direct = any(l in p['languages'] for l in n['languages'])
    via_alias = not direct and any(LANGUAGE_ALIASES.get(l) in p['languages'] for l in n['languages'])
    lang_match = direct or via_alias
    in_dc = p['state'] == 'DC'
    pay = p['payment']
    if n['coverage'] == Coverage.medicaid:
        coverage = bool(pay['medicaid'])
    else:  # uninsured, Alliance or private: needs a low-cost route
        coverage = bool(pay['sliding_fee'] or pay['payment_assistance'] or pay['public_funds'])
    age_ok = any(p['ages'].get(g) for g in n['age_groups'])
    has_location = not p['location_unknown'] and p['lat'] is not None

    preds = [Predicate('in_area', not p['out_of_area'], _ev(p, 'out_of_area')),
             Predicate('serves_age_group', age_ok, _ev(p, 'ages'))]
    if n['needs_in_person']:
        preds += [Predicate('in_person', bool(p['in_person_outpatient']), _ev(p, 'in_person_outpatient')),
                  Predicate('location_known', has_location, _ev(p, 'location_unknown'))]
    if n['care_mode'] == CareMode.telehealth:
        preds.append(Predicate('telehealth', bool(p['telehealth']), _ev(p, 'telehealth')))
    if n['trauma_informed']:
        preds.append(Predicate('trauma_program', bool(p['programs']['trauma']), _ev(p, 'programs.trauma')))
    d = decision(p['id'], preds, rule_version=RULE_VERSION, data_version=data_version)

    if lang_match and in_dc and coverage:
        tier = 'A'
    elif lang_match:
        tier = 'B'
    elif in_dc and coverage:
        tier = 'C'
    else:
        tier = None
    d['eligible'] = d['eligible'] and tier is not None and (lang_match or n['interpreter_ok'])
    d['tier'] = tier

    dist = round(miles(n['_lat'], n['_lng'], p['lat'], p['lng']), 1) if has_location else None
    truth = {
        'speaks_client_language': lang_match, 'in_dc': in_dc, 'accepts_medicaid': bool(pay['medicaid']),
        'sliding_fee': bool(pay['sliding_fee']), 'payment_assistance': bool(pay['payment_assistance']),
        'public_funds': bool(pay['public_funds']), 'in_person': bool(p['in_person_outpatient']),
        'telehealth': bool(p['telehealth']), 'trauma_program': bool(p['programs']['trauma']),
        'ptsd_program': bool(p['programs']['ptsd']),
        'domestic_violence_program': bool(p['programs']['domestic_violence']),
        'serves_age_group': age_ok, 'within_3_miles': dist is not None and dist <= NEAR_MILES,
    }
    assert set(truth) == set(Fact)

    required = ['waitlist']
    if n['provider_gender'] == ProviderGender.woman:
        required.append('woman_clinician')
    if not lang_match:
        required.append('interpreter')
    if via_alias and 'Dari' in n['languages']:
        required.append('dari_speaker')
    if n['coverage'] == Coverage.medicaid:
        if not pay['medicaid']:
            required.append('confirm_cost')  # listing shows no Medicaid at all
        elif not in_dc:
            required.append('confirm_dc_medicaid')  # their Medicaid is their own state's plan
    else:  # a sliding fee or public funds still needs a price
        required.append('confirm_cost')
    if n['minor']:
        required.append('minor_consent')
    if n['pregnant']:
        required.append('perinatal')
    if n['childcare_needed']:
        required.append('childcare')

    if n['care_mode'] == CareMode.in_person:
        truth['telehealth'] = False  # she cannot use it; never offer it as a reason
    return {'decision': d, 'tier': tier, 'distance_mi': dist,
            'facts': [f for f in FACTS if truth[f]],
            'required_questions': required,
            'question_texts': {q: question_text(q, n, p) for q in required},
            'tier_basis': {'language_match': lang_match, 'in_dc': in_dc, 'coverage_match': coverage}}


def candidates(case, providers, data_version):
    """Eligible providers sorted by tier, then distance. Returns (n, cands, counts)."""
    n = needs(case)
    out, excluded = [], 0
    for p in providers:
        ev = evaluate(n, p, data_version)
        if ev['decision']['eligible']:
            out.append({'provider': p, **ev})
        else:
            excluded += 1
    out.sort(key=lambda c: (c['tier'], c['distance_mi'] if c['distance_mi'] is not None else 99, c['provider']['name']))
    counts = {t: sum(1 for c in out if c['tier'] == t) for t in 'ABC'}
    counts['excluded'] = excluded
    return n, out, counts


def card(c, n):
    """Compact candidate card for the agent. Public SAMHSA data only.
    Telehealth is left out when she needs in-person care, so it cannot become a reason."""
    p = c['provider']
    out = {'provider_id': p['id'], 'name': p['name'], 'tier': c['tier'], 'state': p['state'],
           'distance_mi': c['distance_mi'], 'facts': c['facts'], 'languages': p['languages'],
           'facility_type': p['facility_type'], 'required_questions': c['required_questions']}
    if n['care_mode'] != CareMode.in_person:
        out['telehealth'] = p['telehealth']
    return out
