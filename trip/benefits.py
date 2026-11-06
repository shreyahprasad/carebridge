"""Transport benefits (app rules, no agent). One decision per transportation program.

Case-level: which programs she can use (from the trusted Case, never the agent).
Per pick: which of those apply to this trip, and on what condition. NEMT also
needs the provider enrolled in DC Medicaid: a DC provider listing Medicaid is
`likely`; anything else is `if_confirmed` with a call question.
Program data is single-agent research, not independently verified.
"""
import hashlib
import json
import re
from pathlib import Path

from shreyah_harness.decisions import Predicate, decision

from match.models import Case, InsuranceType
from .models import NEMT, Program, TripQuestion, Use

ROOT = Path(__file__).resolve().parent.parent
PROGRAMS_PATH = ROOT / 'data' / 'research' / 'programs.json'
RULE_VERSION = 'trip-rules-v1'
VERIFY = 'Research data, not independently verified. Confirm before relying on it.'

NOTES = {
    Program.nemt_amerihealth: ['Call at least 48 hours ahead for a routine visit (not counting weekends and holidays).',
                               'No rides on Sundays or holidays.',
                               'A loaded SmarTrip card needs 3-5 business days.'],
    Program.nemt_medstar: ['Booking lead time not stated; call early.'],
    Program.nemt_ffs: ['Book with MTM at least 3 business days ahead.', 'Alliance does not include this benefit.'],
    Program.metro_lift: ['50% off Metrobus and Metrorail; not valid on passes.',
                         'Enroll online or at L\'Enfant, Silver Spring or Rosslyn with SmarTrip, EBT card and photo ID.'],
    Program.kids_ride_free: ['Free Metrobus and Metrorail within DC only.',
                             'Stated purpose is school travel; medical trips are not addressed.'],
}


def load_programs(path=PROGRAMS_PATH):
    raw = Path(path).read_bytes()
    recs = {r['id']: r for r in json.loads(raw) if r.get('category') == 'transportation'}
    if set(recs) != {p.value for p in Program}:
        raise ValueError('transportation programs changed; update trip.models.Program')
    return recs, 'programs-' + hashlib.sha256(raw).hexdigest()[:12]


def _ev(case, field):
    return (f'{case.id}#{field}',)


def _predicates(case: Case, pid):
    ins, plan = case.insurance.type, (case.insurance.plan or '').strip().lower()
    medicaid = Predicate('dc_medicaid', ins == InsuranceType.dc_medicaid, _ev(case, 'insurance.type'))
    if pid == Program.nemt_amerihealth:
        return [medicaid, Predicate('plan_amerihealth', plan == 'amerihealth caritas dc', _ev(case, 'insurance.plan'))]
    if pid == Program.nemt_medstar:
        return [medicaid, Predicate('plan_medstar', plan == 'medstar family choice dc', _ev(case, 'insurance.plan'))]
    if pid == Program.nemt_ffs:
        return [medicaid, Predicate('no_managed_care_plan', not plan, _ev(case, 'insurance.plan'))]
    if pid == Program.nemt_hscsn:
        return [Predicate('hscsn_enrollee', 'hscsn' in plan, _ev(case, 'insurance.plan'))]
    if pid == Program.metro_lift:
        return [Predicate('snap', case.snap, _ev(case, 'snap'))]
    if pid == Program.kids_ride_free:
        dc = re.search(r',\s*DC\s+20\d{3}\s*$', case.address) is not None
        return [Predicate('age_5_to_21', 5 <= case.age <= 21, _ev(case, 'age')),
                Predicate('dc_resident', dc, _ev(case, 'address')),
                Predicate('dc_school', bool(case.school) and 'DC' in case.school, _ev(case, 'school'))]
    # MetroAccess and Transport DC are disability-based; the case has no disability field, so unknown.
    return [Predicate('disability_eligibility', None)]


def case_benefits(case, programs, programs_version):
    """Benefits she can use. Unknown (None) predicates are not eligible."""
    out = []
    for pid in Program:
        d = decision(pid.value, _predicates(case, pid), rule_version=RULE_VERSION, data_version=programs_version)
        if not d['eligible']:
            continue
        r = programs[pid.value]
        out.append({'program_id': pid.value, 'name': r['name'], 'how_to_access': r['how_to_access'],
                    'phone': r['phone'], 'notes': NOTES.get(pid, []),
                    'sources': [{'url': s['url'], 'title': s['title']} for s in r['sources']],
                    'confidence': r['confidence'], 'verify': VERIFY, 'decision': d})
    return out


def pick_benefits(benefits, pick, grade):
    """Which of her benefits apply to this pick. Returns [{program_id, use, question}]."""
    out = []
    facts = {f['code'] for f in pick['facts']}
    if grade in ('drive', 'unknown', 'not_realistic'):
        return out  # no car-free trip to pay for
    for b in benefits:
        pid = Program(b['program_id'])
        if pid in NEMT:
            if pick['state'] == 'DC' and 'accepts_medicaid' in facts:
                out.append({'program_id': pid.value, 'use': Use.likely.value, 'question': None})
            else:
                out.append({'program_id': pid.value, 'use': Use.if_confirmed.value,
                            'question': TripQuestion.provider_dc_medicaid_enrolled.value})
        elif pid == Program.kids_ride_free:
            if pick['state'] == 'DC' and grade != 'walk':  # within the District only
                out.append({'program_id': pid.value, 'use': Use.if_confirmed.value,
                            'question': TripQuestion.kids_ride_free_medical.value})
        elif grade != 'walk':
            out.append({'program_id': pid.value, 'use': Use.likely.value, 'question': None})
    return out
