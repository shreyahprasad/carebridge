"""Research workflow: coordinator -> specialists -> source check -> verifier -> dataset.

Acceptance rule (deterministic, app-owned): a claim enters the dataset as a fact
only if (1) its cited page was re-fetched by the host, (2) the excerpt is found
verbatim on that page, and (3) the verifier agent judged it supported. Anything
else is kept in `review` with the reason, never silently dropped or promoted.
"""
from datetime import date
import json
import os
import re
from uuid import uuid4

from shreyah_harness.evidence import Evidence
from shreyah_harness.guardrails import Policy, SensitiveData
from shreyah_harness.runtime import Budget, Runtime
from shreyah_harness.storage import Storage, UsageLedger

from . import agents
from .config import BUDGET, DATA, RESOURCE_TYPES, SCOPE
from .sources import check_sources, find_excerpt, trust_tier

ACCEPT_POLICY = 'quote-found+verifier-supported-v1'
VERIFY_BATCH = 20

# Research topics are generic. Client identifiers must never reach web search.
_CLIENT_DATA = [
    (r'[\w.+-]+@[\w-]+\.[\w.]+', 'email address'),
    (r'\b\d{3}[-. )]*\d{3}[-. ]*\d{4}\b', 'phone number'),
    (r'\b\d{3}-\d{2}-\d{4}\b', 'SSN'),
    (r'\bA[- ]?\d{8,9}\b', 'A-number'),
    (r'\b\d{1,5}\s+\w+(\s\w+)*\s(street|st|avenue|ave|road|rd|place|pl)\b', 'street address'),
]


def check_topic(topic):
    if not isinstance(topic, str) or not 10 <= len(topic) <= 500:
        raise ValueError('topic must be 10-500 characters')
    for pattern, label in _CLIENT_DATA:
        if re.search(pattern, topic, re.I):
            raise ValueError(f'topic looks like it contains client data ({label}); research topics must be generic')


def slug(text):
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')[:80]


def _stage(trace, stage, result):
    run = result['run']
    trace.append({'stage': stage, 'profile': run.get('profile', {}).get('name'), 'run_id': run['run_id'],
                  'status': run['status'], 'reason': run['reason'], 'requests': run['requests'], 'tools': run['tools']})
    return run['status'] == 'complete'


def run(topic, create, fetch, *, model, types=None, db_path=None, out_dir=None, log=print):
    check_topic(topic)
    allowed = list(types or RESOURCE_TYPES)
    if not set(allowed) <= set(RESOURCE_TYPES):
        raise ValueError('unknown resource type')
    correlation_id = uuid4().hex[:12]
    out_dir = out_dir or DATA / 'research'
    out_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_path or out_dir / 'evidence.sqlite'
    secrets = tuple(v for v in [os.environ.get('ANTHROPIC_API_KEY')] if v)
    privacy = SensitiveData(secrets=secrets)
    budget = Budget(**BUDGET)
    trace = []

    with Storage(str(db_path), scope=SCOPE, privacy=privacy) as storage:
        runtime = Runtime(actor='carebridge-research', policy=Policy(privacy=privacy),
                          server_tools=agents.SERVER_TOOLS, ledger=UsageLedger(storage))
        evidence = Evidence(storage)

        # 1. Coordinator plans (no tools).
        def valid_plan(out):
            kinds = [t['resource_type'] for t in out['tasks']]
            if len(kinds) != len(set(kinds)) or not set(kinds) <= set(allowed):
                raise ValueError('plan must use each allowed type at most once')
        log(f'[{correlation_id}] coordinator: planning "{topic}"')
        plan = agents.coordinator(model).run(runtime, create, task={'topic': topic, 'allowed_types': allowed},
                                             budget=budget, validate_output=valid_plan, output_retries=1)
        if not _stage(trace, 'plan', plan):
            return _finish(out_dir, topic, correlation_id, model, trace, [], {}, budget, storage, log)

        # 2. Specialists search the web, one type at a time (shared budget).
        found = []
        for task in plan['output']['tasks']:
            kind = task['resource_type']
            log(f'[{correlation_id}] specialist {kind}: {task["focus"][:80]}')
            result = agents.specialist(model).run(
                runtime, create, task={'resource_type': kind, 'type_description': RESOURCE_TYPES[kind], 'focus': task['focus']},
                budget=budget, max_tokens=8000, output_retries=1)
            if _stage(trace, f'specialist:{kind}', result):
                for res in result['output']['resources']:
                    found.append({**res, 'resource_type': kind})

        # 3. Host re-fetches every cited page and checks each excerpt.
        claims = []
        resources = {}
        for res in found:
            rid = f"{res['resource_type']}-{slug(res['organization'] + ' ' + res['name'])}"
            resources.setdefault(rid, {'id': rid, 'name': res['name'], 'organization': res['organization'],
                                       'resource_type': res['resource_type']})
            for c in res['claims']:
                claims.append({**c, 'claim_id': f'c{len(claims) + 1}', 'resource_id': rid,
                               'organization': res['organization']})
        log(f'[{correlation_id}] source check: {len(claims)} claims, {len({c["source_url"] for c in claims})} pages')
        pages = check_sources([c['source_url'] for c in claims], fetch, evidence)
        for c in claims:
            page = pages[c['source_url']]
            if page['status'] != 'fetched':
                c['check'] = 'source_unreachable'
                c['check_detail'] = page['error']
            else:
                span = find_excerpt(page['text'], c['excerpt'])
                c['check'] = 'quote_found' if span else 'quote_not_found'
                c['span'], c['source_id'] = span, page['source_id']

        # 4. Verifier judges quote-found claims against stored snapshots only.
        to_verify = [c for c in claims if c['check'] == 'quote_found']
        snapshots = {p['source_id']: p['text'] for p in pages.values() if p['status'] == 'fetched'}
        verdicts = {}
        for i in range(0, len(to_verify), VERIFY_BATCH):
            batch = to_verify[i:i + VERIFY_BATCH]
            expected = {c['claim_id'] for c in batch}

            def valid_verdicts(out, expected=expected):
                if {v['claim_id'] for v in out['verdicts']} != expected or len(out['verdicts']) != len(expected):
                    raise ValueError('exactly one verdict per claim required')
            log(f'[{correlation_id}] verifier: {len(batch)} claims')
            result = agents.verifier(model, snapshots).run(
                runtime, create, budget=budget, max_tokens=4000, output_retries=1, validate_output=valid_verdicts,
                task={'claims': [{k: c[k] for k in ('claim_id', 'organization', 'field', 'value', 'excerpt', 'source_id')}
                                 for c in batch]})
            if _stage(trace, f'verifier:{i // VERIFY_BATCH + 1}', result):
                verdicts.update({v['claim_id']: v for v in result['output']['verdicts']})

        # 5. Evidence store: observe every claim, accept only quote+supported.
        storage.import_records(resources.values(), identify=lambda r: r['id'], version=correlation_id,
                               validate=lambda r: bool(r['id']))
        for c in claims:
            v = verdicts.get(c['claim_id'])
            c['verdict'] = v['verdict'] if v else None
            c['verdict_reason'] = v['reason'] if v else None
            if c['check'] == 'quote_found':
                status = {'supported': 'supported', 'unsupported': 'conflicting'}.get(c['verdict'], 'needs_review')
                obs = evidence.observe(record_id=c['resource_id'], record_version=correlation_id, field=c['field'],
                                       value=c['value'], source_id=c['source_id'], excerpt=c['span'],
                                       extractor='specialist-v1', validator='verifier-v1', status=status)
                if status == 'supported':
                    span = c['span']
                    c['acceptance_id'] = evidence.accept(obs, policy=ACCEPT_POLICY, reviewer='research-verifier-v1',
                                                         validate=lambda o, span=span: o['excerpt'] == span)
            else:
                evidence.observe(record_id=c['resource_id'], record_version=correlation_id, field=c['field'],
                                 value=None, extractor='specialist-v1', validator='host-source-check-v1', status='unknown')
        return _finish(out_dir, topic, correlation_id, model, trace, claims, resources, budget, storage, log)


def _finish(out_dir, topic, correlation_id, model, trace, claims, resources, budget, storage, log):
    today = date.today().isoformat()
    dataset = []
    for rid, res in resources.items():
        mine = [c for c in claims if c['resource_id'] == rid]
        accepted = [c for c in mine if c.get('acceptance_id')]
        fields = {}
        for c in accepted:
            fields.setdefault(c['field'], []).append({
                'value': c['value'], 'source_url': c['source_url'], 'excerpt': c['span'],
                'trust': trust_tier(c['source_url']), 'acceptance_id': c['acceptance_id'], 'checked': today})
        review = [{'field': c['field'], 'value': c['value'], 'source_url': c['source_url'], 'excerpt': c['excerpt'],
                   'reason': c['check'] if c['check'] != 'quote_found' else f"verifier: {c['verdict'] or 'no verdict'}",
                   'detail': c.get('check_detail') or c.get('verdict_reason')} for c in mine if not c.get('acceptance_id')]
        trust = {trust_tier(c['source_url']) for c in accepted}
        dataset.append({**res, 'status': 'verified' if accepted and trust == {'institutional'} else 'needs_review',
                        'fields': fields, 'review': review,
                        'unknown_ask_on_call': ['woman clinician available', 'interpreter for client language', 'current waitlist']})
    report = {'topic': topic, 'correlation_id': correlation_id, 'model': model, 'date': today,
              'acceptance_policy': ACCEPT_POLICY, 'stages': trace,
              'budget_used': {'requests': budget.requests, 'tools': budget.tools},
              'usage': storage and UsageLedger(storage).summary(),
              'counts': {'resources': len(dataset), 'claims': len(claims),
                         'accepted': sum(1 for c in claims if c.get('acceptance_id')),
                         'quote_not_found': sum(1 for c in claims if c.get('check') == 'quote_not_found'),
                         'source_unreachable': sum(1 for c in claims if c.get('check') == 'source_unreachable')},
              'resources': dataset}
    run_path = out_dir / 'runs' / f'{today}-{correlation_id}.json'
    run_path.parent.mkdir(parents=True, exist_ok=True)
    run_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    merged = _merge(out_dir / 'supplemental_resources.json', dataset)
    log(f'[{correlation_id}] done: {report["counts"]} -> {run_path.name}; dataset now {merged} resources')
    return report


def _merge(path, dataset):
    current = {r['id']: r for r in json.loads(path.read_text())} if path.exists() else {}
    for r in dataset:
        current[r['id']] = r
    path.write_text(json.dumps(sorted(current.values(), key=lambda r: r['id']), indent=2, ensure_ascii=False) + '\n')
    return len(current)
