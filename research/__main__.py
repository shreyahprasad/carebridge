"""CLI: python -m research "<topic>" [--live] [--types training_clinic,community_org]

--demo (default): scripted agents + fixture pages, no network, no cost.
--live: real Claude agents with web search/fetch (paid). Needs ANTHROPIC_API_KEY.
Live source checks connect directly to the cited sites, so run this from your own
terminal, not the Claude Code sandbox.
"""
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from .config import RESOURCE_TYPES, load_env, model
from . import pipeline


def main(argv=None):
    parser = argparse.ArgumentParser(prog='python -m research', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('topic')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--demo', action='store_true', help='scripted, offline (default)')
    mode.add_argument('--live', action='store_true', help='real agents + web (paid)')
    parser.add_argument('--types', help='comma list of: ' + ', '.join(RESOURCE_TYPES))
    args = parser.parse_args(argv)
    types = args.types.split(',') if args.types else None
    load_env()

    if args.live:
        if not os.environ.get('ANTHROPIC_API_KEY'):
            parser.error('ANTHROPIC_API_KEY missing (add it to .env)')
        from shreyah_harness.research import Fetcher, FetchPolicy
        from shreyah_harness.runtime import anthropic_client
        client = anthropic_client(timeout=180)
        fetcher = Fetcher(FetchPolicy(max_bytes=2_000_000, timeout=15, requests_per_domain=10))
        try:
            report = pipeline.run(args.topic, client.messages.create, fetcher.fetch, model=model(), types=types,
                                  log=lambda m: print(m, file=sys.stderr))
        finally:
            client.close()
    else:
        from .scripted import fixture_fetch, scripted_model
        out = Path(tempfile.mkdtemp(prefix='carebridge-research-demo-'))
        print(f'DEMO (scripted, fixture pages) -> {out}', file=sys.stderr)
        report = pipeline.run(args.topic, scripted_model(), fixture_fetch, model='scripted-demo', types=types,
                              out_dir=out, log=lambda m: print(m, file=sys.stderr))
    print(json.dumps({'counts': report['counts'], 'stages': report['stages']}, indent=2))
    return 0 if all(s['status'] == 'complete' for s in report['stages']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
