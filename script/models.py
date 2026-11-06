"""Typed contract for the call script (pydantic, extra='forbid').

CallScript (`call-script-v1`) is a fixed template filled from the trusted Case, the
validated MatchResult and TripPlan, and providers.json. No model writes any of it.
The caseworker reads it on the phone today; the future AI call agent (M9) will follow
the same guidelines, ask the same coded questions and fill the same answer slots.
"""
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from match.models import Mode, Question, Strict
from trip.models import Grade, TripQuestion


class CallOnly(StrEnum):
    new_patients = 'new_patients'
    intake_steps = 'intake_steps'


# Asked of the provider on the call: the general questions, every provider-match question,
# and the one trip question a provider can answer. Other trip questions are after-call tasks.
ON_CALL_TRIP = (TripQuestion.provider_dc_medicaid_enrolled,)
CallQuestion = StrEnum('CallQuestion', {q.value: q.value for q in [*CallOnly, *Question, *ON_CALL_TRIP]})
AFTER_CALL = tuple(q for q in TripQuestion if q not in ON_CALL_TRIP)
assert len(CallQuestion) == len(CallOnly) + len(Question) + len(ON_CALL_TRIP), 'question codes must be unique'

NO_CALL = (Grade.not_realistic, Grade.unknown)


class Disclosure(StrEnum):
    """Client facts a provider may be told. Text is built from the Case by script.rules."""
    age = 'age'
    language = 'language'
    english_level = 'english_level'
    coverage = 'coverage'
    in_person = 'in_person'
    young_child = 'young_child'
    pregnancy = 'pregnancy'
    clinician_gender = 'clinician_gender'


class Guideline(StrEnum):
    identify = 'identify'
    consent = 'consent'
    disclose_only_listed = 'disclose_only_listed'
    never_status = 'never_status'
    follow_up_unlisted = 'follow_up_unlisted'
    hand_back = 'hand_back'
    record_answers = 'record_answers'


class Answer(StrEnum):
    yes = 'yes'
    no = 'no'
    unknown = 'unknown'


class DisclosureText(Strict):
    code: Disclosure
    text: str


class GuidelineText(Strict):
    code: Guideline
    text: str


class CallQuestionText(Strict):
    code: CallQuestion
    source: Literal['call', 'match', 'trip']
    text: str


class AfterCall(Strict):
    """Trip task for the caseworker after the call (ride booking, DDOT, school). Trip rules text."""
    code: TripQuestion
    text: str


class AnswerSlot(Strict):
    """Filled after the call: by the caseworker now, by the AI call agent later."""
    code: CallQuestion
    answer: Answer | None = None
    note: str | None = None


class ProviderCall(Strict):
    order: int = Field(ge=1)
    trip_order: int = Field(ge=1)
    provider_id: str
    name: str
    phone: str                 # from providers.json
    intake_phone: str | None   # from providers.json
    address: str
    state: str
    grade: Grade
    questions: list[CallQuestionText] = Field(min_length=1)
    after_call: list[AfterCall]
    answers: list[AnswerSlot]

    @model_validator(mode='after')
    def _consistent(self):
        if self.grade in NO_CALL:
            raise ValueError('no call for a not_realistic or unknown trip')
        codes = [q.code for q in self.questions]
        if len(codes) != len(set(codes)):
            raise ValueError('duplicate question')
        if [a.code for a in self.answers] != codes:
            raise ValueError('one answer slot per question, in question order')
        return self


class Skipped(Strict):
    provider_id: str
    name: str
    trip_order: int = Field(ge=1)
    grade: Grade
    reason: str


class CallScript(Strict):
    version: Literal['call-script-v1']
    correlation_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,64}$')
    case_id: str
    synthetic: bool
    date: str
    rule_version: str
    match_mode: Mode
    trip_mode: Mode
    trip_plan_version: Literal['trip-plan-v1']
    client_placeholder: Literal['[client]']
    guidelines: list[GuidelineText]
    opening: str
    disclosures: list[DisclosureText] = Field(min_length=1)
    client_summary: str
    closing: str
    calls: list[ProviderCall] = Field(max_length=3)
    skipped: list[Skipped]

    @model_validator(mode='after')
    def _consistent(self):
        if [g.code for g in self.guidelines] != list(Guideline):
            raise ValueError('every guideline, in order')
        if len({d.code for d in self.disclosures}) != len(self.disclosures):
            raise ValueError('duplicate disclosure')
        if self.client_summary != ' '.join(d.text for d in self.disclosures):
            raise ValueError('client summary must be exactly the disclosures')
        if [c.order for c in self.calls] != list(range(1, len(self.calls) + 1)):
            raise ValueError('order must be 1..n')
        trip_orders = [c.trip_order for c in self.calls]
        if trip_orders != sorted(trip_orders):
            raise ValueError('calls must follow trip order')
        ids = [c.provider_id for c in self.calls] + [s.provider_id for s in self.skipped]
        if len(ids) != len(set(ids)):
            raise ValueError('provider listed twice')
        return self
