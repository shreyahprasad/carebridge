"""Reusable deterministic protections and optional, explicitly registered classifiers.

Rules receive trusted runtime context and copied data, never authority from text.
This library is an execution boundary for cooperative Python, not an OS sandbox.
"""
from dataclasses import dataclass, field
import copy
import hashlib
import json
import re
import threading
import time
from uuid import uuid4


EVENTS = frozenset({'before_model_call', 'after_model_response', 'before_tool_execution',
                    'after_tool_execution', 'before_external_action', 'before_final_response',
                    'on_agent_error'})


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def strict_json(text):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError('duplicate JSON key')
            value[key] = item
        return value
    def invalid(_):
        raise ValueError('nonfinite JSON number')
    return json.loads(text, object_pairs_hook=pairs, parse_constant=invalid)


@dataclass(frozen=True)
class Decision:
    outcome: str = 'allow'
    code: str = 'allowed'
    value: object = None

    def __post_init__(self):
        if self.outcome not in {'allow', 'deny', 'redact', 'require_approval', 'retry'}:
            raise ValueError('unknown guardrail outcome')
        # Audit reasons are identifiers, never classifier explanations or input text.
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', self.code):
            raise ValueError('guardrail code must be a safe identifier')


@dataclass(frozen=True)
class Rule:
    name: str
    events: frozenset
    check: object

    def __post_init__(self):
        object.__setattr__(self, 'events', frozenset(self.events))
        if not self.events or not self.events <= EVENTS or not callable(self.check):
            raise ValueError('invalid guardrail registration')
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', self.name):
            raise ValueError('rule name must be a safe identifier')


@dataclass(frozen=True)
class SensitiveData:
    """Known secrets and configurable patterns; PII is opt-in, not guessed.

    Default patterns intentionally cover credential formats, not every secret.
    Matching keys/values are redacted recursively; action arguments are blocked.
    """
    secrets: tuple = ()
    patterns: tuple = (
        r'\bsk-ant-[A-Za-z0-9_-]{16,}\b',
        r'\b(?:sk-proj-|sk-)[A-Za-z0-9_-]{24,}\b',
        r'\b(?:ghp_|github_pat_)[A-Za-z0-9_]{20,}\b',
        r'\bAKIA[A-Z0-9]{16}\b',
        r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
    )
    sensitive_keys: frozenset = frozenset({'api_key', 'apikey', 'password', 'secret',
                                          'access_token', 'refresh_token', 'authorization',
                                          'credential', 'credentials', 'private_key'})

    def __post_init__(self):
        if isinstance(self.secrets, str) or isinstance(self.patterns, str) or isinstance(self.sensitive_keys, str):
            raise ValueError('sensitive-data configuration requires sequences, not a string')
        object.__setattr__(self, 'secrets', tuple(self.secrets))
        object.__setattr__(self, 'patterns', tuple(self.patterns))
        object.__setattr__(self, 'sensitive_keys', frozenset(self.sensitive_keys))
        if any(not isinstance(s, str) or not s for s in self.secrets):
            raise ValueError('known secrets must be nonempty strings')
        if any(not isinstance(k, str) or not k for k in self.sensitive_keys):
            raise ValueError('sensitive field names must be nonempty strings')
        for pattern in self.patterns:
            if not isinstance(pattern, str):
                raise ValueError('patterns must be strings')
            re.compile(pattern)

    def redact(self, value):
        if isinstance(value, str):
            # JSON tool results/finals in text blocks still need key-based checks.
            if value.lstrip().startswith(('{', '[')):
                try:
                    decoded = strict_json(value)
                    redacted = self.redact(decoded)
                    if canonical(decoded) != canonical(redacted):
                        value = canonical(redacted)
                except (ValueError, TypeError, RecursionError):
                    pass
            for secret in sorted(self.secrets, key=len, reverse=True):
                value = value.replace(secret, '[REDACTED]')
            for pattern in self.patterns:
                value = re.sub(pattern, '[REDACTED]', value)
            return value
        if isinstance(value, dict):
            return {self.redact(k): '[REDACTED]' if isinstance(k, str) and k.lower() in self.sensitive_keys
                    else self.redact(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.redact(item) for item in value]
        return value

    def contains(self, value):
        return canonical(value) != canonical(self.redact(value))

    def rule(self):
        def check(context, value):
            safe = self.redact(value)
            if canonical(safe) == canonical(value):
                return Decision()
            if context.event in {'before_tool_execution', 'before_external_action'}:
                return Decision('deny', 'sensitive_action_arguments')
            return Decision('redact', 'sensitive_data_redacted', safe)
        return Rule('sensitive_data', EVENTS - {'on_agent_error'}, check)


def redact_phi(text, patterns=(r'\bMRN-\d{8}\b',)):
    """Example configurable identifier filter, NOT comprehensive PHI detection."""
    return SensitiveData(patterns=patterns, sensitive_keys=frozenset()).redact(text)


def safety_guardrail(classifier, *, events=('before_model_call', 'before_final_response')):
    """Adapt a trusted classifier returning {unsafe: bool, reason?: str}.

    Reasons are not put in audit logs. Classifier exceptions/invalid results fail
    closed in the runtime. Prefer a bounded local classifier; network classifiers
    must enforce their own timeout and must receive only redacted data.
    """
    def check(context, value):
        result = classifier(copy.deepcopy(value))
        if not isinstance(result, dict) or type(result.get('unsafe')) is not bool:
            raise ValueError('invalid classifier result')
        return Decision('deny', 'unsafe_content') if result['unsafe'] else Decision()
    return Rule('safety_classifier', frozenset(events), check)


@dataclass(frozen=True)
class Grant:
    """Exact tool/resource match or explicit '*'; risk must match exactly."""
    tool: str = '*'
    resource: str = '*'
    risk: str = 'read'

    def __post_init__(self):
        if any(not isinstance(v, str) or not v for v in (self.tool, self.resource)) or self.risk not in {'read', 'write', 'destructive', 'sensitive', 'unknown'}:
            raise ValueError('invalid trusted permission grant')

    def allows(self, tool, resource, risk):
        return self.risk == risk and self.tool in {'*', tool} and self.resource in {'*', resource}


@dataclass(frozen=True)
class Policy:
    rules: tuple = ()
    privacy: SensitiveData = field(default_factory=SensitiveData)
    version: str = '1'
    max_payload_bytes: int = 1_000_000

    def __post_init__(self):
        object.__setattr__(self, 'rules', tuple(self.rules))
        if not isinstance(self.privacy, SensitiveData) or not isinstance(self.version, str) or not self.version:
            raise ValueError('policy requires privacy configuration and a version')
        if any(not isinstance(r, Rule) for r in self.rules):
            raise ValueError('policies require Rules')
        if type(self.max_payload_bytes) is not int or self.max_payload_bytes < 1:
            raise ValueError('positive payload bound required')


@dataclass(frozen=True)
class GuardContext:
    event: str
    actor: str
    run_id: str
    parent_id: str | None
    tool: str | None = None
    resource: str | None = None
    risk: str | None = None


@dataclass(frozen=True)
class Action:
    actor: str
    scope: str
    tool: str
    resource: str
    risk: str
    tool_version: str
    policy_version: str
    arguments_json: str

    @property
    def fingerprint(self):
        return hashlib.sha256(canonical(self.__dict__).encode()).hexdigest()

    @property
    def arguments(self):
        return strict_json(self.arguments_json)


class ApprovalStore:
    """Trusted UI issues short-lived, single-use grants for an exact Action.

    Memory-only by default. Store is never supplied to the model or tools.
    Durable workflow applications must implement durable approval storage and
    service-side idempotency before promising crash recovery/exactly-once writes.
    """
    def __init__(self):
        self._grants = {}
        self._lock = threading.Lock()

    def issue(self, action, *, seconds=300):
        if not 0 < seconds <= 3600:
            raise ValueError('approval lifetime must be within one hour')
        token = uuid4().hex
        with self._lock:
            self._grants[token] = (action.fingerprint, time.monotonic() + seconds)
        return token

    def consume(self, token, action):
        with self._lock:
            grant = self._grants.pop(token, None)
        return grant is not None and grant[0] == action.fingerprint and grant[1] > time.monotonic()
