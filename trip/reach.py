"""Reachability grades and trip call questions (app code, never the model).

Thresholds are a design choice (owner-approved 2026-11-06), straight-line miles
from the provider match. No live transit routing: any time is labeled an estimate.
"""
from .models import NEMT, Grade, Program, TripQuestion

THRESHOLDS = {
    'walk_under_mi': 0.5,     # strictly under, and she lists walking (owner 2026-11-06)
    'one_bus_max_mi': 4.0,    # and she lists Metro or Metrobus
    'hard_max_mi': 8.0,
    'drive_max_mi': 25.0,     # she has a car
    'young_child_under': 6,   # out of state + no car + a child this young -> not_realistic
}
MINUTES = {Grade.walk: '5-10 min walk (estimate)', Grade.one_bus: '20-45 min by bus or Metro (estimate)',
           Grade.hard: '45-90 min, likely a transfer (estimate)', Grade.drive: None, Grade.unknown: None,
           Grade.not_realistic: None}


def _transit(n):
    return any('metro' in t.lower() or 'bus' in t.lower() for t in n['transportation'])


def _walks(n):
    return any(t.lower().startswith('walk') for t in n['transportation'])


def grade(n, case, pick):
    """Returns (Grade, basis sentence). n is MatchResult.needs (dict)."""
    d = pick['distance_mi']
    if d is None:
        return Grade.unknown, 'No location on file; no trip to plan.'
    young = any(c.age < THRESHOLDS['young_child_under'] for c in case.children)
    if n['has_car']:
        if d <= THRESHOLDS['drive_max_mi']:
            return Grade.drive, f'{d:g} mi and she has a car.'
        return Grade.not_realistic, f'{d:g} mi is over {THRESHOLDS["drive_max_mi"]:g} mi even by car.'
    if pick['state'] != 'DC' and young:
        return Grade.not_realistic, f'Out of DC ({pick["state"]}), no car, and a child under {THRESHOLDS["young_child_under"]}.'
    if d < THRESHOLDS['walk_under_mi'] and _walks(n):
        return Grade.walk, f'{d:g} mi; she walks.'
    if d <= THRESHOLDS['one_bus_max_mi'] and _transit(n):
        return Grade.one_bus, f'{d:g} mi; she uses Metro or Metrobus.'
    if d <= THRESHOLDS['hard_max_mi'] and _transit(n):
        return Grade.hard, f'{d:g} mi by transit, likely with a transfer.'
    return Grade.not_realistic, f'{d:g} mi without a car is not realistic for her.'


def required_questions(n, case, uses, grade):
    """Call questions for this trip. uses = pick_benefits() output."""
    if grade in (Grade.not_realistic, Grade.unknown):
        return []  # no trip to plan
    q = [u['question'] for u in uses if u['question']]
    if any('help' in t.lower() for t in n['transportation']):
        q.append(TripQuestion.travel_help.value)
    if n['childcare_needed'] or any(c.age < THRESHOLDS['young_child_under'] for c in case.children):
        q.append(TripQuestion.child_on_trip.value)
    if any(Program(u['program_id']) in NEMT for u in uses):
        q.append(TripQuestion.book_ride_ahead.value)
    return list(dict.fromkeys(q))


def question_text(code, pick, benefits):
    names = {b['program_id']: b['name'] for b in benefits}
    nemt = next((names[p.value] for p in NEMT if p.value in names), 'her Medicaid ride benefit')
    if code == 'provider_dc_medicaid_enrolled':
        return f"Ask {pick['name']}: are you enrolled as a DC Medicaid provider? {nemt} only covers rides to DC Medicaid providers."
    if code == 'kids_ride_free_medical':
        return 'Ask DDOT or her school: can her Kids Ride Free card be used for a medical appointment, not only school travel?'
    if code == 'travel_help':
        return 'She uses the bus with help. Who can ride with her, or can the ride service help her board?'
    if code == 'child_on_trip':
        return 'Can her young child ride along, and is there a car seat or childcare at the visit?'
    if code == 'book_ride_ahead':
        return f'Once the appointment is set, book the ride with {nemt} early enough (see booking notes).'
    raise KeyError(code)


assert set(MINUTES) == set(Grade)
