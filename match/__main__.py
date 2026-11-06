"""CLI: python -m match case-001 [--live | --rules-only] [--out DIR]

default: scripted provider-match agent, offline, no cost (labeled "scripted").
--live: real Claude agent (paid). Needs ANTHROPIC_API_KEY; run from your own terminal.
--rules-only: no agent; tier then distance.
Results go to data/runs/match/ (live) or a temp folder (scripted/rules-only) unless --out is given.
"""
import argparse
import json
import os
import sys
import tempfile

from research.config import ROOT, load_env, model

from . import rules
from .workflow import run_match


def main(argv=None):
    parser = argparse.ArgumentParser(prog='python -m match', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('case_id')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--live', action='store_true', help='real Claude agent (paid)')
    mode.add_argument('--rules-only', action='store_true', help='no agent')
    parser.add_argument('--out', help='folder for the MatchResult JSON')
    args = parser.parse_args(argv)
    cases = rules.load_cases()
    if args.case_id not in cases:
        parser.error(f'unknown case; choose from {", ".join(cases)}')
    case = cases[args.case_id]
    load_env()
    log = lambda m: print(m, file=sys.stderr)

    if args.live:
        if not os.environ.get('ANTHROPIC_API_KEY'):
            parser.error('ANTHROPIC_API_KEY missing (add it to .env)')
        from shreyah_harness.runtime import anthropic_client
        out = args.out or ROOT / 'data' / 'runs' / 'match'
        client = anthropic_client(timeout=120)
        try:
            report = run_match(case, client.messages.create, model=model(), live=True, out_dir=out, log=log)
        finally:
            client.close()
    else:
        out = args.out or tempfile.mkdtemp(prefix='carebridge-match-')
        if args.rules_only:
            report = run_match(case, None, model=None, out_dir=out, log=log)
        else:
            from .scripted import scripted_model
            report = run_match(case, scripted_model(), model='scripted-demo', out_dir=out, log=log)

    print(json.dumps({
        'mode': report['mode'], 'fallback_reason': report['fallback_reason'], 'counts': report['counts'],
        'picks': [{'rank': p['rank'], 'tier': p['tier'], 'name': p['name'], 'distance_mi': p['distance_mi'],
                   'facts': [f['code'] for f in p['facts']], 'questions': [q['code'] for q in p['questions']],
                   'why': p['why']} for p in report['picks']],
        'stages': report['stages'], 'path': report.get('path')}, indent=2, ensure_ascii=False))
    return 0 if report['mode'] != 'rules_only' or args.rules_only else 1


if __name__ == '__main__':
    raise SystemExit(main())
