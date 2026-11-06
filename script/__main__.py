"""CLI: python -m script case-001 [--all [--live | --rules-only]] [--out DIR]

default: build the call script from data/runs/match/ and trip/<case>-latest.json (what the
         page shows). Instant, offline, no AI. Writes data/runs/script/<case>-latest.json.
--all:   run provider match, trip plan and call script together (scripted agents unless
         --live or --rules-only). --live is paid and needs ANTHROPIC_API_KEY; run it from
         your own terminal. --all results go to data/runs/ with --live, else a temp folder
         unless --out is given.
"""
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from research.config import ROOT, load_env, model

from match import rules
from trip.workflow import HandoffError
from .workflow import run_workflow, script_from_latest


def summary(s):
    return {'correlation_id': s['correlation_id'], 'match_mode': s['match_mode'], 'trip_mode': s['trip_mode'],
            'client_summary': s['client_summary'],
            'calls': [{'order': c['order'], 'name': c['name'], 'phone': c['intake_phone'] or c['phone'],
                       'grade': c['grade'], 'questions': [q['code'] for q in c['questions']],
                       'after_call': [a['code'] for a in c['after_call']]} for c in s['calls']],
            'skipped': [f"{k['name']}: {k['reason']}" for k in s['skipped']], 'path': s.get('path')}


def main(argv=None):
    parser = argparse.ArgumentParser(prog='python -m script', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('case_id')
    parser.add_argument('--all', action='store_true', help='run match, trip and script together')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--live', action='store_true', help='with --all: real Claude agents (paid)')
    mode.add_argument('--rules-only', action='store_true', help='with --all: no agents')
    parser.add_argument('--out', help='runs folder (match/, trip/, script/ inside it); default data/runs')
    args = parser.parse_args(argv)
    if (args.live or args.rules_only) and not args.all:
        parser.error('--live and --rules-only need --all')
    cases = rules.load_cases()
    if args.case_id not in cases:
        parser.error(f'unknown case; choose from {", ".join(cases)}')
    case = cases[args.case_id]
    log = lambda m: print(m, file=sys.stderr)

    if not args.all:
        runs = Path(args.out) if args.out else ROOT / 'data' / 'runs'
        try:
            s = script_from_latest(case, runs, log=log)
        except FileNotFoundError as e:
            print(f'No match or trip plan yet ({e.filename}). Run: python -m script {case.id} --all', file=sys.stderr)
            return 2
        except HandoffError as e:
            print(f'Match and trip files do not fit together: {e}. Rerun with --all.', file=sys.stderr)
            return 2
        except ValueError:
            print(f'Match or trip file is not valid JSON. Rerun: python -m script {case.id} --all', file=sys.stderr)
            return 2
        print(json.dumps(summary(s), indent=2, ensure_ascii=False))
        return 0

    load_env()
    base = Path(args.out) if args.out else (ROOT / 'data' / 'runs' if args.live
                                            else Path(tempfile.mkdtemp(prefix='carebridge-script-')))
    dirs = dict(match_out=base / 'match', trip_out=base / 'trip', out_dir=base / 'script', log=log)
    if args.live:
        if not os.environ.get('ANTHROPIC_API_KEY'):
            parser.error('ANTHROPIC_API_KEY missing (add it to .env)')
        from shreyah_harness.runtime import anthropic_client
        client = anthropic_client(timeout=120)
        try:
            m, t, s = run_workflow(case, client.messages.create, model=model(), live=True, **dirs)
        finally:
            client.close()
    elif args.rules_only:
        m, t, s = run_workflow(case, None, model=None, **dirs)
    else:
        from trip.scripted import scripted_workflow
        m, t, s = run_workflow(case, scripted_workflow(), model='scripted-demo', **dirs)
    print(json.dumps(summary(s), indent=2, ensure_ascii=False))
    ok = args.rules_only or (m['mode'] != 'rules_only' and t['mode'] != 'rules_only')
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
