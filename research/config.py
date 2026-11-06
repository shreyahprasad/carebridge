"""Trusted host configuration for the research workflow.

Profiles, budgets and resource types live here, never in task input or model
output. Changing a prompt means bumping its version so datasets stay traceable.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / 'data'
DB_PATH = DATA / 'research' / 'evidence.sqlite'
SCOPE = 'carebridge-research'

RESOURCE_TYPES = {
    'training_clinic': 'University psychology/counseling training clinics and psychiatry residency clinics offering low-cost or sliding-scale care',
    'pro_bono_network': 'Pro bono clinician networks, including forensic psychological evaluations for asylum seekers',
    'community_org': 'Community or ethnic/language-specific organizations offering mental health support to immigrants',
    'survivor_program': 'Programs for survivors of torture, war trauma or gender-based violence',
}

# Claims the specialists may make. Anything not listed is rejected by schema.
CLAIM_FIELDS = (
    'description', 'services', 'cost', 'eligibility', 'serves_immigrants', 'languages',
    'women_focus', 'telehealth', 'how_to_access', 'phone', 'address', 'website',
)

# Open search (owner decision 2026-11-06): any domain may be searched; trust is
# earned by re-fetch + quote check + verifier. Only registration-restricted
# suffixes are institutional; .org/.com etc. can be registered by anyone, so
# their resources stay needs_review for a human even when every claim checks out.
INSTITUTIONAL_SUFFIXES = ('.gov', '.edu', '.mil')

# Shared workflow budget (one correlation id across every stage).
BUDGET = dict(max_requests=60, max_tools=80, max_retries=2, seconds=1200)
SEARCH_USES = 5     # web_search per specialist request
FETCH_USES = 5      # web_fetch per specialist request
MAX_RESOURCES_PER_TYPE = 4
SOURCE_TEXT_LIMIT = 20000   # chars of a snapshot shown to the verifier


def load_env(path=ROOT / '.env'):
    """Read KEY=VALUE lines into os.environ without overriding real env."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def model():
    return os.environ.get('CLAUDE_MODEL', 'claude-sonnet-5-5')
