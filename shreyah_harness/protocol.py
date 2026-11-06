"""Explicit Messages capabilities. No SDK dependency and no alternate dispatcher."""
import base64
import copy
from dataclasses import dataclass
import re

from .guardrails import canonical


@dataclass(frozen=True)
class RequestOptions:
    effort: str | None = None
    thinking: str | None = None
    thinking_budget: int | None = None
    cache: bool = False
    max_continuations: int = 2

    def __post_init__(self):
        if self.effort not in {None, 'low', 'medium', 'high', 'xhigh', 'max'}:
            raise ValueError('unsupported effort')
        if self.thinking not in {None, 'adaptive', 'enabled', 'disabled'}:
            raise ValueError('unsupported thinking mode')
        if self.thinking == 'enabled':
            if type(self.thinking_budget) is not int or self.thinking_budget < 1024:
                raise ValueError('manual thinking needs a budget of at least 1024')
        elif self.thinking_budget is not None:
            raise ValueError('thinking budget requires enabled thinking')
        if type(self.cache) is not bool or type(self.max_continuations) is not int or not 0 <= self.max_continuations <= 10:
            raise ValueError('invalid request limits')

    def request(self, max_tokens):
        value = {}
        if self.effort:
            value['output_config'] = {'effort': self.effort}
        if self.thinking:
            value['thinking'] = {'type': self.thinking}
            if self.thinking_budget is not None:
                if self.thinking_budget >= max_tokens:
                    raise ValueError('thinking budget must leave space for output')
                value['thinking']['budget_tokens'] = self.thinking_budget
        if self.cache:
            value['cache_control'] = {'type': 'ephemeral'}
        return value


@dataclass(frozen=True)
class ServerTool:
    """Host-authorized research only; local grants do not govern server execution."""
    name: str
    version: str
    max_uses: int = 2
    allowed_domains: tuple = ()
    max_content_tokens: int = 6000

    def __post_init__(self):
        versions = {'web_search': {'web_search_20250305'}, 'web_fetch': {'web_fetch_20250910'}}
        object.__setattr__(self, 'allowed_domains', tuple(self.allowed_domains))
        if self.version not in versions.get(self.name, set()):
            raise ValueError('unreviewed server tool version')
        if type(self.max_uses) is not int or not 1 <= self.max_uses <= 10:
            raise ValueError('invalid server use limit')
        if type(self.max_content_tokens) is not int or not 1 <= self.max_content_tokens <= 100000:
            raise ValueError('invalid fetch token bound')
        if any(not isinstance(d, str) or not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?', d) for d in self.allowed_domains):
            raise ValueError('invalid domain allowlist')

    def definition(self):
        result = {'name': self.name, 'type': self.version, 'max_uses': self.max_uses}
        if self.allowed_domains:
            result['allowed_domains'] = list(self.allowed_domains)
        if self.name == 'web_fetch':
            result.update(citations={'enabled': True}, max_content_tokens=self.max_content_tokens)
        return result


def native_content(blocks):
    """Validate bounded inline text/images/PDF. Binary disclosure needs host approval."""
    if not isinstance(blocks, (list, tuple)) or len(blocks) > 20:
        raise ValueError('invalid native content')
    result = copy.deepcopy(list(blocks))
    for block in result:
        if not isinstance(block, dict):
            raise ValueError('invalid content block')
        kind = block.get('type')
        if kind == 'text':
            if set(block) != {'type', 'text'} or not isinstance(block['text'], str):
                raise ValueError('invalid text block')
        elif kind in {'image', 'document'}:
            if set(block) != {'type', 'source'}:
                raise ValueError('only inline attachment sources supported')
            src = block['source']
            if not isinstance(src, dict) or set(src) != {'type', 'media_type', 'data'} or src['type'] != 'base64':
                raise ValueError('only inline base64 supported')
            media = {'image': {'image/jpeg', 'image/png', 'image/gif', 'image/webp'}, 'document': {'application/pdf'}}
            if src['media_type'] not in media[kind] or not isinstance(src['data'], str) or len(src['data']) > 800000:
                raise ValueError('unsupported attachment type/size')
            if not base64.b64decode(src['data'], validate=True):
                raise ValueError('empty attachment')
        else:
            raise ValueError('unsupported input content')
    canonical(result)
    return result


def protected(value):
    """Protocol blobs and approved attachments must not be transformed by policies."""
    found = []
    def visit(item):
        if isinstance(item, dict):
            if item.get('type') in {'thinking', 'redacted_thinking', 'image', 'document', 'server_tool_use',
                                    'web_search_tool_result', 'web_fetch_tool_result'}:
                found.append(copy.deepcopy(item))
            else:
                for v in item.values(): visit(v)
        elif isinstance(item, list):
            for v in item: visit(v)
    visit(value)
    return found


def validate_response(content, server_names, thinking):
    allowed = {'text', 'tool_use'}
    if thinking:
        allowed |= {'thinking', 'redacted_thinking'}
    if server_names:
        allowed |= {'server_tool_use'}
        allowed |= {name + '_tool_result' for name in server_names}
    if not isinstance(content, list) or any(not isinstance(b, dict) or b.get('type') not in allowed for b in content):
        raise ValueError('unsupported content')
    for block in content:
        if block['type'] == 'text':
            if not isinstance(block.get('text'), str) or not isinstance(block.get('citations', []), list) or any(not isinstance(c, dict) for c in block.get('citations', [])):
                raise ValueError('invalid text/citations')
        if block['type'] == 'redacted_thinking' and not isinstance(block.get('data'), str):
            raise ValueError('invalid redacted thinking')
        if block['type'] == 'server_tool_use' and block.get('name') not in server_names:
            raise ValueError('unregistered server tool')
        if block['type'] == 'thinking' and (not isinstance(block.get('thinking'), str) or not isinstance(block.get('signature'), str)):
            raise ValueError('invalid thinking')


@dataclass(frozen=True)
class AgentProfile:
    """Canonical snapshot; mutable caller dictionaries cannot change a profile."""
    name: str
    version: str
    model: str
    prompt: str
    prompt_version: str
    output_schema_json: str
    options: RequestOptions = RequestOptions()
    tools: tuple = ()
    grants: tuple | None = None
    rules: tuple = ()
    server_names: tuple = ()

    def __post_init__(self):
        for v in (self.name, self.version, self.model, self.prompt_version):
            if not isinstance(v, str) or not v: raise ValueError('profile identity required')
        from .guardrails import strict_json
        from .runtime import _schema
        _schema(strict_json(self.output_schema_json))
        if not isinstance(self.options, RequestOptions): raise ValueError('invalid profile options')
        object.__setattr__(self, 'tools', tuple(copy.deepcopy(self.tools)))
        object.__setattr__(self, 'server_names', tuple(self.server_names))
        object.__setattr__(self, 'rules', tuple(self.rules))
        if self.grants is not None: object.__setattr__(self, 'grants', tuple(self.grants))

    def run(self, runtime, create, *, task, **execution):
        from .guardrails import strict_json
        # Execution controls cannot silently override profile identity or permissions.
        if set(execution) - {'budget', 'stream', 'retryable', 'max_tokens', 'output_retries', 'native_schema', 'content', 'validate_output'}:
            raise ValueError('profile override forbidden')
        result = runtime.run(create, model=self.model, prompt=self.prompt, prompt_version=self.prompt_version,
                             task=task, tools=self.tools, grants=self.grants, rules=self.rules,
                             output_schema=strict_json(self.output_schema_json), options=self.options, server_names=self.server_names, profile={"name": self.name, "version": self.version}, **execution)
        return result
