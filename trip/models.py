"""Typed contracts for the trip stage (pydantic, extra='forbid').

TripPlan is checked before it is returned or written. The match result is read
only through match.models.MatchResult (see workflow.check_handoff).
"""
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from match.models import Mode, Stage, BudgetUsed, Strict, Tier


class Grade(StrEnum):
    """Reachability, best first. Thresholds are in reach.THRESHOLDS (contracts.md)."""
    walk = 'walk'
    one_bus = 'one_bus'
    drive = 'drive'
    hard = 'hard'
    unknown = 'unknown'  # no location (telehealth-only pick)
    not_realistic = 'not_realistic'


GRADE_ORDER = list(Grade)


class Program(StrEnum):
    """Every transportation record in data/research/programs.json."""
    nemt_amerihealth = 'nemt-amerihealth-caritas-dc'
    nemt_medstar = 'nemt-medstar-family-choice-dc'
    nemt_ffs = 'nemt-medicaid-ffs'
    nemt_hscsn = 'nemt-hscsn'
    metro_lift = 'wmata-metro-lift'
    kids_ride_free = 'dc-kids-ride-free'
    metroaccess = 'wmata-metroaccess'
    transport_dc = 'transport-dc'


NEMT = {Program.nemt_amerihealth, Program.nemt_medstar, Program.nemt_ffs, Program.nemt_hscsn}


class Use(StrEnum):
    likely = 'likely'              # rules say it applies to this trip
    if_confirmed = 'if_confirmed'  # applies only if the linked question comes back yes


class TripQuestion(StrEnum):
    provider_dc_medicaid_enrolled = 'provider_dc_medicaid_enrolled'
    kids_ride_free_medical = 'kids_ride_free_medical'
    travel_help = 'travel_help'
    child_on_trip = 'child_on_trip'
    book_ride_ahead = 'book_ride_ahead'


class SourceRef(Strict):
    url: str = Field(pattern=r'^https://')
    title: str


class Benefit(Strict):
    """A program she can use (case-level). Research data, not independently verified."""
    program_id: Program
    name: str
    how_to_access: str
    phone: str | None
    notes: list[str]  # rule-derived booking notes (lead time, limits)
    sources: list[SourceRef] = Field(min_length=1)
    confidence: Literal['high', 'medium', 'low']
    verify: Literal['Research data, not independently verified. Confirm before relying on it.']
    decision: dict


class BenefitUse(Strict):
    program_id: Program
    use: Use
    question: TripQuestion | None = None

    @model_validator(mode='after')
    def _q(self):
        if (self.use == Use.if_confirmed) != (self.question is not None):
            raise ValueError('if_confirmed needs exactly one question')
        return self


class QuestionText(Strict):
    code: TripQuestion
    text: str


class PlanStop(Strict):
    order: int = Field(ge=1)
    match_rank: int = Field(ge=1)
    provider_id: str
    name: str
    address: str
    state: str
    tier: Tier
    distance_mi: float | None
    grade: Grade
    grade_basis: str
    time_estimate: str | None  # labeled estimate, no live routing
    benefits: list[BenefitUse]
    steps: list[str] | None          # model-written, unchecked; None in rules_only
    tell_client: str | None          # model-written, unchecked
    questions: list[QuestionText]
    extra_questions: list[str] = []  # model-written, unchecked


class TripPlan(Strict):
    version: Literal['trip-plan-v1']
    correlation_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,64}$')
    case_id: str
    synthetic: bool
    date: str
    mode: Mode
    fallback_reason: str | None
    model: str | None
    prompt_version: str | None
    rule_version: str
    programs_version: str
    match_mode: Mode
    match_result_version: Literal['match-result-v1']
    thresholds: dict
    benefits: list[Benefit]
    plans: list[PlanStop]
    unchecked_fields: list[str]
    stages: list[Stage]
    budget_used: BudgetUsed

    @model_validator(mode='after')
    def _consistent(self):
        eligible = {b.program_id for b in self.benefits}
        for s in self.plans:
            if not {u.program_id for u in s.benefits} <= eligible:
                raise ValueError('plan uses a benefit she is not eligible for')
            if s.state != 'DC' and any(u.program_id in NEMT and u.use == Use.likely for u in s.benefits):
                raise ValueError('NEMT claimed as likely for an out-of-DC provider')
        if [s.order for s in self.plans] != list(range(1, len(self.plans) + 1)):
            raise ValueError('order must be 1..n')
        if len({s.provider_id for s in self.plans}) != len(self.plans):
            raise ValueError('duplicate provider in plans')
        keys = [(GRADE_ORDER.index(s.grade), s.match_rank) for s in self.plans]
        if keys != sorted(keys):
            raise ValueError('plans must be ordered by grade then match rank')
        if self.mode == Mode.rules_only:
            if self.model or self.prompt_version or any(s.steps or s.tell_client or s.extra_questions for s in self.plans):
                raise ValueError('rules_only plan carries model output')
        elif not (self.model and self.prompt_version) or self.fallback_reason:
            raise ValueError('agent plan needs model and prompt version and no fallback')
        return self
