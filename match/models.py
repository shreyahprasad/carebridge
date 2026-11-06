"""Typed contracts at the workflow's edges (pydantic), plus the shared enums.

Case       checked when a run starts (input from cases.json or the future intake form)
Provider   checked when providers.json loads
MatchResult checked before it is written or handed to transportation; load_match_result()
           is how the next stage reads one.

The agent's own output is still checked by the runtime's JSON Schema and
agent.validator; its fact/question/tier lists are generated from these enums.
Unknown fields are rejected (extra='forbid') so a typo fails loudly instead of
silently changing a match.
"""
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


# ---------- enums ----------
class EnglishLevel(StrEnum):
    none = 'none'
    basic = 'basic'
    conversational = 'conversational'
    fluent = 'fluent'


class CareMode(StrEnum):
    in_person = 'in_person'
    in_person_preferred = 'in_person_preferred'
    telehealth = 'telehealth'
    any = 'any'


class InsuranceType(StrEnum):
    dc_medicaid = 'DC Medicaid'
    dc_alliance = 'DC Healthcare Alliance'
    private = 'private'
    uninsured = 'uninsured'


class Coverage(StrEnum):
    """What matching uses. Alliance/private take the low-cost route plus a cost question."""
    medicaid = 'medicaid'
    uninsured = 'uninsured'
    other = 'other'


class ProviderGender(StrEnum):
    woman = 'woman'
    man = 'man'
    no_preference = 'no preference'


class Urgency(StrEnum):
    routine = 'routine'
    soon = 'soon'
    urgent = 'urgent'


class State(StrEnum):
    DC = 'DC'
    MD = 'MD'
    VA = 'VA'
    other = 'other'


class Tier(StrEnum):
    A = 'A'  # speaks her language, in DC, coverage matches
    B = 'B'  # speaks her language, outside DC or cost to confirm
    C = 'C'  # in DC, coverage matches, interpreter needed


class Mode(StrEnum):
    live = 'live'
    scripted = 'scripted'
    rules_only = 'rules_only'


class Fact(StrEnum):
    speaks_client_language = 'speaks_client_language'
    in_dc = 'in_dc'
    accepts_medicaid = 'accepts_medicaid'
    sliding_fee = 'sliding_fee'
    payment_assistance = 'payment_assistance'
    public_funds = 'public_funds'
    in_person = 'in_person'
    telehealth = 'telehealth'
    trauma_program = 'trauma_program'
    ptsd_program = 'ptsd_program'
    domestic_violence_program = 'domestic_violence_program'
    serves_age_group = 'serves_age_group'
    within_3_miles = 'within_3_miles'


class Question(StrEnum):
    woman_clinician = 'woman_clinician'
    interpreter = 'interpreter'
    dari_speaker = 'dari_speaker'
    confirm_dc_medicaid = 'confirm_dc_medicaid'
    confirm_cost = 'confirm_cost'
    waitlist = 'waitlist'
    minor_consent = 'minor_consent'
    perinatal = 'perinatal'
    childcare = 'childcare'


# ---------- case ----------
class Insurance(Strict):
    type: InsuranceType
    plan: str | None = None


class Household(Strict):
    size: int = Field(ge=1)
    monthly_income_usd: int = Field(ge=0)


class Child(Strict):
    age: int = Field(ge=0, le=17)


class Preferences(Strict):
    provider_gender: ProviderGender = ProviderGender.no_preference
    interpreter_ok: bool = True
    trauma_informed: bool | None = None


class Caseworker(Strict):
    name: str
    email: str
    notes: str = ''


class Case(Strict):
    id: str = Field(pattern=r'^case-\d{3}$')
    synthetic: bool
    first_name: str
    last_name: str
    age: int = Field(ge=0, le=120)
    address: str
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    phone: str
    languages: list[str] = Field(min_length=1)
    english_level: EnglishLevel
    has_phone: bool
    phone_type: str | None = None
    has_computer: bool
    care_mode_needed: CareMode
    care_mode_note: str | None = None
    transportation_options: list[str] = []
    has_car: bool
    immigration_status: str
    insurance: Insurance
    snap: bool = False
    household: Household
    pregnant: bool = False
    pregnancy_weeks: int | None = Field(default=None, ge=0, le=45)
    children: list[Child] = []
    childcare_during_appointments: Literal['needed', 'not_needed'] | None = None
    school: str | None = None
    guardian: str | None = None
    needs_mental_health_care: bool
    mental_health_concerns: str = ''
    preferences: Preferences = Preferences()
    urgency: Urgency
    caseworker: Caseworker

    @model_validator(mode='after')
    def _consistent(self):
        if self.pregnancy_weeks is not None and not self.pregnant:
            raise ValueError('pregnancy_weeks set but pregnant is false')
        if self.care_mode_needed == CareMode.telehealth and not (self.has_phone or self.has_computer):
            raise ValueError('telehealth needs a phone or computer')
        return self

    @property
    def coverage(self):
        return {InsuranceType.dc_medicaid: Coverage.medicaid,
                InsuranceType.uninsured: Coverage.uninsured}.get(self.insurance.type, Coverage.other)


# ---------- provider ----------
class Ages(Strict):
    children_adolescents: bool
    young_adults: bool
    adults: bool
    seniors: bool


class Programs(Strict):
    trauma: bool
    ptsd: bool
    domestic_violence: bool
    young_adults: bool
    children_sed: bool
    co_occurring: bool


class Payment(Strict):
    medicaid: bool
    state_plan_other_than_medicaid: bool
    cash_self_pay: bool
    sliding_fee: bool
    payment_assistance: bool
    public_funds: bool
    accepted: list[str]


class Source(Strict):
    name: str
    url: str = Field(pattern=r'^https://')
    retrieved: str
    distance_from_dc_center_mi: float | None = None


class Provider(Strict):
    id: str = Field(pattern=r'^samhsa-')
    name: str
    address: str
    zip: str
    state: str = Field(pattern=r'^[A-Z]{2}$')
    lat: float | None
    lng: float | None
    location_unknown: bool
    out_of_area: bool
    phone: str
    intake_phone: str | None
    hotline: str | None
    website: str
    operator: str
    facility_type: str | None
    settings: list[str]
    in_person_outpatient: bool
    telehealth: bool
    languages: list[str]
    sign_language: bool
    other_languages_unspecified: bool
    ages: Ages
    programs: Programs
    therapies: list[str]
    payment: Payment
    emergency_services: list[str]
    woman_clinician_available: None  # SAMHSA has no such field; must stay unknown
    interpreter_services: None
    source: Source
    raw_services: dict[str, str]

    @model_validator(mode='after')
    def _location(self):
        if not self.location_unknown and (self.lat is None or self.lng is None):
            raise ValueError('location known but no coordinates')
        return self


# ---------- MatchResult (handoff to transportation) ----------
class Text(Strict):
    code: str
    text: str


class FactRef(Text):
    code: Fact


class QuestionRef(Text):
    code: Question


class PredicateOut(Strict):
    name: str
    passed: bool | None
    evidence_ids: list[str]


class DecisionOut(Strict):
    record_id: str
    eligible: Literal[True]
    rule_version: str
    data_version: str
    predicates: list[PredicateOut]
    tier: Tier


class TierBasis(Strict):
    language_match: bool
    in_dc: bool
    coverage_match: bool


class PickSource(Strict):
    name: str
    url: str
    retrieved: str


class Pick(Strict):
    rank: int = Field(ge=1)
    provider_id: str
    name: str
    tier: Tier
    address: str
    state: str
    lat: float | None
    lng: float | None
    distance_mi: float | None = Field(default=None, ge=0)
    phone: str
    intake_phone: str | None
    website: str
    languages: list[str]
    telehealth: bool
    facts: list[FactRef] = Field(min_length=1)
    tier_basis: TierBasis
    why: str | None  # model-written, unchecked
    questions: list[QuestionRef] = Field(min_length=1)
    extra_questions: list[str] = []  # model-written, unchecked
    decision: DecisionOut
    source: PickSource

    @model_validator(mode='after')
    def _consistent(self):
        if self.decision.record_id != self.provider_id or self.decision.tier != self.tier:
            raise ValueError('pick does not match its decision')
        return self


class Needs(Strict):
    case_id: str
    languages: list[str]
    english_level: EnglishLevel
    age: int
    age_groups: list[Literal['children_adolescents', 'young_adults', 'adults']]
    minor: bool
    coverage: Coverage
    care_mode: CareMode
    needs_in_person: bool
    trauma_informed: bool
    provider_gender: ProviderGender
    interpreter_ok: bool
    pregnant: bool
    childcare_needed: bool
    has_car: bool
    transportation: list[str]
    concerns: str
    urgency: Urgency


class Counts(Strict):
    A: int = Field(ge=0)
    B: int = Field(ge=0)
    C: int = Field(ge=0)
    excluded: int = Field(ge=0)


class Stage(Strict):
    stage: str
    profile: str | None
    run_id: str | None
    status: str  # runtime status (complete/partial/error) or 'skipped'
    reason: str | None
    requests: int = Field(ge=0)
    tools: int = Field(ge=0)


class BudgetUsed(Strict):
    requests: int = Field(ge=0)
    tools: int = Field(ge=0)


class MatchResult(Strict):
    version: Literal['match-result-v1']
    correlation_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,64}$')
    case_id: str
    synthetic: bool
    date: str
    mode: Mode
    fallback_reason: str | None
    model: str | None
    prompt_version: str | None
    rule_version: str
    data_version: str
    needs: Needs
    counts: Counts
    picks: list[Pick]
    not_chosen_note: str | None
    unchecked_fields: list[str]
    stages: list[Stage]
    budget_used: BudgetUsed

    @model_validator(mode='after')
    def _consistent(self):
        ids = [p.provider_id for p in self.picks]
        if len(ids) != len(set(ids)):
            raise ValueError('duplicate provider in picks')
        if [p.rank for p in self.picks] != list(range(1, len(self.picks) + 1)):
            raise ValueError('ranks must be 1..n in order')
        if self.needs.case_id != self.case_id:
            raise ValueError('needs belong to another case')
        if self.mode == Mode.rules_only:
            if self.model or self.prompt_version or any(p.why or p.extra_questions for p in self.picks):
                raise ValueError('rules_only result carries model output')
        elif not (self.model and self.prompt_version) or self.fallback_reason:
            raise ValueError('agent result needs model and prompt version and no fallback')
        if self.needs.needs_in_person and any(p.lat is None or p.lng is None for p in self.picks):
            raise ValueError('in-person pick without coordinates')
        return self


def load_match_result(path):
    """How the transportation stage reads a handoff. Raises on any contract break."""
    return MatchResult.model_validate_json(Path(path).read_text())
