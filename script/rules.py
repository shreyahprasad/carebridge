"""Call-script template (app code only; no model).

The script shares only the disclosures below, built from fixed fields of the Case.
Her name, phone, address, plan name, immigration status and free-text concerns are
never used in what is said on the call. The script says "a client"; the caseworker gives
her name only to book. after_call holds caseworker-only trip tasks (trip rules text),
which may name her ride benefit (and so her plan); the M9 call agent must not speak them.
"""
from match import rules as match_rules
from match.models import CareMode, EnglishLevel, InsuranceType, ProviderGender
from trip import reach
from trip.models import TripQuestion

from .models import AFTER_CALL, ON_CALL_TRIP, CallOnly, Disclosure, Guideline

RULE_VERSION = 'call-script-rules-v1'
MAX_CALLS = 3
YOUNG_CHILD_UNDER = reach.THRESHOLDS['young_child_under']

OPENING = ("Hi, my name is [caseworker]. I'm calling from [organization], a nonprofit that helps refugees and "
           "immigrants in DC find health care. I'm calling for a client, with her consent. She is looking for a "
           "therapist or counselor for mental health care.")
CLOSING = ("If she can be seen: book the intake, give her name as [client], and note the date, time and what to bring. "
           "If there is a waitlist: ask to add her, and note how long it is and when to call back. Thank them.")

GUIDELINES = {
    Guideline.identify: 'Say who is calling: a caseworker from [organization], calling for a client.',
    Guideline.consent: 'Say the call is made with her consent.',
    Guideline.disclose_only_listed: ('Share only the facts in the client summary. Give her name only to book an intake. '
                                     'Never give her phone number or home address.'),
    Guideline.never_status: 'Never give or confirm her immigration status, even if asked.',
    Guideline.follow_up_unlisted: 'If asked for anything not listed, say the caseworker will follow up.',
    Guideline.hand_back: ('Stop and hand the call to a human caseworker for anything clinical, legal, a crisis '
                          'or a request for payment. Do not answer it on her behalf.'),
    Guideline.record_answers: 'Record each answer as yes, no or unknown, with a short note.',
}
assert list(GUIDELINES) == list(Guideline)

ENGLISH = {EnglishLevel.none: 'She speaks no English.', EnglishLevel.basic: 'She speaks a little English.',
           EnglishLevel.intermediate: 'She speaks some English.', EnglishLevel.fluent: 'She speaks English fluently.'}
COVERAGE = {InsuranceType.dc_medicaid: 'She has DC Medicaid.',
            InsuranceType.dc_alliance: 'She has the DC Healthcare Alliance.',
            InsuranceType.private: 'She has private insurance.',
            InsuranceType.uninsured: 'She does not have health insurance.'}

CALL_TEXT = {CallOnly.new_patients: 'Are you taking new clients for therapy or counseling?',
             CallOnly.intake_steps: 'How does she book an intake, and what should she bring?'}
# Provider-facing wording for on-call trip questions. The trip rule text is addressed to
# the caseworker and names her plan, so the provider hears this instead.
ON_CALL_TEXT = {TripQuestion.provider_dc_medicaid_enrolled: 'Are you enrolled as a DC Medicaid provider?'}
assert set(ON_CALL_TEXT) == set(ON_CALL_TRIP)
LAST = ('waitlist',)  # asked near the end, before intake_steps


def guidelines():
    return [{'code': g.value, 'text': t} for g, t in GUIDELINES.items()]


def disclosures(case):
    out = [(Disclosure.age, f'She is {case.age}.' + (' She is a minor.' if case.age < 18 else '')),
           (Disclosure.language, f"She speaks {' and '.join(case.languages)}."),
           (Disclosure.english_level, ENGLISH[case.english_level]),
           (Disclosure.coverage, COVERAGE[case.insurance.type])]
    if case.care_mode_needed == CareMode.in_person:
        out.append((Disclosure.in_person, 'She needs in-person appointments.'))
    elif case.care_mode_needed == CareMode.in_person_preferred:
        out.append((Disclosure.in_person, 'She prefers in-person appointments.'))
    if case.pregnant:
        out.append((Disclosure.pregnancy, 'She is pregnant.'))
    if case.childcare_during_appointments == 'needed' or any(c.age < YOUNG_CHILD_UNDER for c in case.children):
        out.append((Disclosure.young_child, 'She has a young child who may need to come with her.'))
    if case.preferences.provider_gender == ProviderGender.woman:
        out.append((Disclosure.clinician_gender, 'She would prefer a woman clinician.'))
    elif case.preferences.provider_gender == ProviderGender.man:
        out.append((Disclosure.clinician_gender, 'She would prefer a male clinician.'))
    return [{'code': c.value, 'text': t} for c, t in out]


def call_questions(n, record, match_codes, plan):
    """Questions for one provider, in call order. n = match_rules.needs(case);
    match_codes from the MatchResult pick; plan = a validated TripPlan stop dict.
    Match text is rebuilt from the rules and the provider record, never copied from a file."""
    mq = [{'code': q, 'source': 'match', 'text': match_rules.question_text(q, n, record)} for q in match_codes]
    tq = [{'code': q['code'], 'source': 'trip', 'text': ON_CALL_TEXT[TripQuestion(q['code'])]}
          for q in plan['questions'] if TripQuestion(q['code']) in ON_CALL_TRIP]
    middle = [q for q in mq + tq if q['code'] not in LAST] + [q for q in mq if q['code'] in LAST]
    return ([{'code': CallOnly.new_patients.value, 'source': 'call', 'text': CALL_TEXT[CallOnly.new_patients]}]
            + middle
            + [{'code': CallOnly.intake_steps.value, 'source': 'call', 'text': CALL_TEXT[CallOnly.intake_steps]}])


def after_call(plan):
    """Trip tasks for after the call, with the trip rules' text unchanged."""
    return [{'code': q['code'], 'text': q['text']} for q in plan['questions'] if TripQuestion(q['code']) in AFTER_CALL]
