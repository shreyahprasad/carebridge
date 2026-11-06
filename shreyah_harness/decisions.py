"""Decision evidence contracts, not a business-rule engine or model eligibility judge."""
from dataclasses import dataclass
from .guardrails import canonical


@dataclass(frozen=True)
class Predicate:
    name: str
    passed: bool | None
    evidence_ids: tuple = ()

    def __post_init__(self):
        object.__setattr__(self, 'evidence_ids', tuple(self.evidence_ids))
        if not isinstance(self.name, str) or not self.name or (self.passed is not None and type(self.passed) is not bool):
            raise ValueError('invalid predicate')
        if any(not isinstance(x, str) or not x for x in self.evidence_ids): raise ValueError('invalid evidence id')
        if self.passed is True and not self.evidence_ids: raise ValueError('positive predicate needs evidence')


def decision(record_id, predicates, *, rule_version, data_version):
    predicates = tuple(predicates)
    if not predicates or any(not isinstance(p, Predicate) for p in predicates) or len({p.name for p in predicates}) != len(predicates):
        raise ValueError('unique predicates required')
    if any(not isinstance(v, str) or not v for v in (record_id, rule_version, data_version)): raise ValueError('decision versions required')
    return dict(record_id=record_id, eligible=all(p.passed is True for p in predicates),
                rule_version=rule_version, data_version=data_version,
                predicates=[dict(name=p.name, passed=p.passed, evidence_ids=list(p.evidence_ids)) for p in predicates])


def validate_selection(output, decisions):
    """Exact eligibility set. Ranking, if desired, is a separate app operation."""
    if not isinstance(output, list) or any(not isinstance(x, str) for x in output) or len(output) != len(set(output)):
        return False
    return set(output) == {d['record_id'] for d in decisions if d['eligible'] is True}


def grounded_fields(output, expected, *, required_questions=()):
    """Enforce exact factual fields/questions; prose needs calibrated semantic review."""
    if not isinstance(output, dict) or any(k not in output or canonical(output[k]) != canonical(v) for k, v in expected.items()):
        return False
    questions = output.get('questions', [])
    return isinstance(questions, list) and all(q in questions for q in required_questions)
