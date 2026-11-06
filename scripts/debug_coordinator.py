"""Diagnostic: run the coordinator once and print each response block type + first 200 chars.
Usage: .venv/bin/python scripts/debug_coordinator.py "<topic>"  (2 small paid requests)"""
import sys, json
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent))
from research.config import load_env, model, RESOURCE_TYPES
load_env()
from shreyah_harness.runtime import Runtime, Budget, anthropic_client
from research import agents
client = anthropic_client(timeout=60)
def create(**kw):
    r = client.messages.create(**kw)
    d = r.model_dump(mode='json', exclude_none=True)
    print('REQUEST keys:', sorted(k for k in kw if k not in ('messages','system')), '| tools:', [t.get('name') for t in kw.get('tools', [])], file=sys.stderr)
    for b in d['content']:
        print('  BLOCK', b['type'], repr((b.get('text') or b.get('thinking') or '')[:200]), file=sys.stderr)
    print('  stop:', d.get('stop_reason'), file=sys.stderr)
    return d
rt = Runtime(server_tools=agents.SERVER_TOOLS)
res = agents.coordinator(model()).run(rt, create, task={'topic': sys.argv[1], 'allowed_types': ['training_clinic']}, budget=Budget(max_requests=3), output_retries=1, max_tokens=4000)
print(res['run']['status'], res['run']['reason'], res['output'])
print('model:', model(), file=sys.stderr)
