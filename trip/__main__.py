"""CLI: python -m trip case-001 [--live | --rules-only] [--out DIR]

Runs provider match then trip plan with one Runtime, Budget and correlation id.
default: scripted agents, offline, no cost (labeled "scripted").
--live: real Claude agents (paid, up to 6 requests). Needs ANTHROPIC_API_KEY; run from your own terminal.
--rules-only: no agents.
Live results go to data/runs/match/ and data/runs/trip/; others to a temp folder unless --out is given.
"""
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from research.config import ROOT, load_env, model

from match import rules
from .workflow import run_workflow


def main(argv=None):
    parser = argparse.ArgumentParser(prog='python -m trip', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('case_id')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--live', action='store_true', help='real Claude agents (paid)')
    mode.add_argument('--rules-only', action='store_true', help='no agents')
    parser.add_argument('--out', help='folder for results (match/ and trip/ inside it)')
    args = parser.parse_args(argv)
    cases = rules.load_cases()
    if args.case_id not in cases:
        parser.error(f'unknown case; choose from {", ".join(cases)}')
    case = cases[args.case_id]
    load_env()
    log = lambda m: print(m, file=sys.stderr)
    base = Path(args.out) if args.out else (ROOT / 'data' / 'runs' if args.live
                                            else Path(tempfile.mkdtemp(prefix='carebridge-trip-')))
    dirs = dict(match_out=base / 'match', out_dir=base / 'trip', log=log)

    if args.live:
        if not os.environ.get('ANTHROPIC_API_KEY'):
            parser.error('ANTHROPIC_API_KEY missing (add it to .env)')
        from shreyah_harness.runtime import anthropic_client
        client = anthropic_client(timeout=120)
        try:
            m, t = run_workflow(case, client.messages.create, model=model(), live=True, **dirs)
        finally:
            client.close()
    elif args.rules_only:
        m, t = run_workflow(case, None, model=None, **dirs)
    else:
        from .scripted import scripted_workflow
        m, t = run_workflow(case, scripted_workflow(), model='scripted-demo', **dirs)

    print(json.dumps({
        'correlation_id': t['correlation_id'], 'match_mode': t['match_mode'], 'trip_mode': t['mode'],
        'fallback_reason': t['fallback_reason'], 'benefits': [b['program_id'] for b in t['benefits']],
        'plans': [{'order': s['order'], 'match_rank': s['match_rank'], 'name': s['name'], 'state': s['state'],
                   'distance_mi': s['distance_mi'], 'grade': s['grade'],
                   'benefits': [f"{u['program_id']} ({u['use']})" for u in s['benefits']],
                   'questions': [q['code'] for q in s['questions']], 'steps': s['steps'],
                   'tell_client': s['tell_client']} for s in t['plans']],
        'stages': t['stages'], 'budget_used': t['budget_used'],
        'match_path': m.get('path'), 'trip_path': t.get('path')}, indent=2, ensure_ascii=False))
    ok = args.rules_only or (m['mode'] != 'rules_only' and t['mode'] != 'rules_only')
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
