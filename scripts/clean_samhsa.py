"""Clean the SAMHSA FindTreatment.gov export into data/providers.json.

Input:  data/raw/samhsa_dc_mh.json  (locator export: mental health, 10 mi of DC)
Output: data/providers.json         (one flat record per facility)

Every derived flag keeps the original SAMHSA wording in `raw_services`, so the
UI can show the source text. Fields SAMHSA does not publish (e.g. clinician
gender) are left as null and must be confirmed by phone.
"""
import collections
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / 'data/raw/samhsa_dc_mh.json'
OUT = ROOT / 'data/providers.json'
SOURCE_URL = 'https://findtreatment.gov/'

# SAMHSA "Other Languages" values -> our language names.
LANGUAGE_ALIASES = {'Any Chinese Language': 'Chinese', 'Creole': 'Haitian Creole'}


def split(value):
    return [v.strip() for v in value.split(';') if v.strip()] if value else []


def services_by_code(row):
    return {s['f2']: split(s['f3']) for s in row.get('services') or []}


def slug(text):
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')


def clean(row):
    s = services_by_code(row)
    sl, ol = s.get('SL', []), s.get('OL', [])
    languages = ['English']
    if 'Spanish' in sl:
        languages.append('Spanish')
    languages += [LANGUAGE_ALIASES.get(x, x) for x in ol]
    groups = set(s.get('SG', []))
    approaches = set(s.get('TAP', []))
    pay = set(s.get('PAY', []))
    pay_assist = s.get('PYAS', [])
    ages = set(s.get('AGE', []))
    settings = s.get('SET', [])
    address = ', '.join(x for x in [row['street1'], row.get('street2'), row['city'], f"{row['state']} {row['zip']}"] if x)
    name = row['name1'] + (f" — {row['name2']}" if row.get('name2') else '')
    return {
        'id': f"samhsa-{slug(row['name1'])}-{row['zip']}",
        'name': name,
        'address': address,
        'zip': row['zip'],
        # Medicaid is state-run: 'medicaid' below means the facility's own state plan;
        # DC Medicaid at an MD/VA facility must be verified on the call.
        'state': row['state'],
        'lat': float(row['latitude']) if row.get('latitude') else None,
        'lng': float(row['longitude']) if row.get('longitude') else None,
        # No coordinates: distance unknown. Out of area: address outside DC/MD/VA.
        'location_unknown': not (row.get('latitude') and row.get('longitude')),
        'out_of_area': row['state'] not in ('DC', 'MD', 'VA'),
        'phone': row.get('phone') or None,
        'intake_phone': row.get('intake1') or None,
        'hotline': row.get('hotline1') or None,
        'website': row.get('website') or None,
        'operator': (s.get('FOP') or [None])[0],
        'facility_type': (s.get('FT') or [None])[0],
        'settings': settings,
        'in_person_outpatient': 'Outpatient' in settings,
        'telehealth': 'Telemedicine/telehealth therapy' in approaches,
        'languages': languages,
        'sign_language': any('Sign language' in x for x in sl),
        'other_languages_unspecified': 'Other languages (excluding Spanish)' in sl and not ol,
        'ages': {
            'children_adolescents': 'Children/Adolescents' in ages,
            'young_adults': 'Young Adults' in ages,
            'adults': 'Adults' in ages,
            'seniors': 'Seniors' in ages,
        },
        'programs': {
            'trauma': 'Clients who have experienced trauma' in groups,
            'ptsd': 'Persons with post-traumatic stress disorder (PTSD)' in groups,
            'domestic_violence': 'Clients who have experienced intimate partner violence, domestic violence' in groups,
            'young_adults': 'Young adults' in groups,
            'children_sed': 'Children/adolescents with serious emotional disturbance (SED)' in groups,
            'co_occurring': 'Clients with co-occurring mental and substance use disorders' in groups,
        },
        'therapies': sorted(approaches),
        'payment': {
            'medicaid': 'Medicaid' in pay,
            'state_plan_other_than_medicaid': 'State-financed health insurance plan other than Medicaid' in pay,
            'cash_self_pay': 'Cash or self-payment' in pay,
            'sliding_fee': any('Sliding fee' in x for x in pay_assist),
            'payment_assistance': any('Payment assistance' in x for x in pay_assist),
            'public_funds': bool(pay & {'State mental health agency (or equivalent) funds', 'Community Mental Health Block Grants',
                                        'County or local government funds', 'Other State funds'}),
            'accepted': sorted(pay),
        },
        'emergency_services': s.get('EMS', []),
        # Not published by SAMHSA: must be asked on the call.
        'woman_clinician_available': None,
        'interpreter_services': None,
        'source': {'name': 'SAMHSA FindTreatment.gov locator export', 'url': SOURCE_URL,
                   'retrieved': '2026-11-06', 'distance_from_dc_center_mi': row.get('miles')},
        'raw_services': {x['f1']: x['f3'] for x in row.get('services') or []},
    }


def main():
    rows = json.loads(RAW.read_text())['rows']
    providers = [clean(r) for r in rows]
    counts = collections.Counter(p['id'] for p in providers)
    for p in providers:  # disambiguate same name+zip by full address (suites differ)
        if counts[p['id']] > 1:
            p['id'] += '-' + slug(p['address'])
    assert len({p['id'] for p in providers}) == len(providers), 'duplicate provider ids'
    OUT.write_text(json.dumps(providers, indent=2, ensure_ascii=False) + '\n')
    print(f'{len(providers)} providers -> {OUT.relative_to(ROOT)}', file=sys.stderr)


if __name__ == '__main__':
    main()
