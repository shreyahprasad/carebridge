"""Deterministic source checks: re-fetch a cited page, store a hashed snapshot,
and confirm the cited excerpt really appears on it. No model involved."""
from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import urlsplit

from .config import INSTITUTIONAL_SUFFIXES

_TRANSLATE = str.maketrans({'‘': "'", '’': "'", '“': '"', '”': '"',
                            '–': '-', '—': '-', ' ': ' ', '…': '...'})


class _Text(HTMLParser):
    SKIP = {'script', 'style', 'noscript', 'svg', 'template'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in {'p', 'br', 'li', 'div', 'h1', 'h2', 'h3', 'h4', 'tr', 'section'}:
            self.parts.append(' ')

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def normalize(text):
    text = unicodedata.normalize('NFKC', text).translate(_TRANSLATE)
    return re.sub(r'\s+', ' ', text).strip()


def page_text(content, media_type):
    if media_type == 'text/html':
        parser = _Text()
        parser.feed(content)
        content = ' '.join(parser.parts)
    return normalize(content)


def find_excerpt(text, excerpt):
    """Return the page's own span matching the excerpt (case-insensitive), or None."""
    needle = normalize(excerpt)
    if len(needle) < 12:
        return None  # too short to prove anything
    i = text.casefold().find(needle.casefold())
    return text[i:i + len(needle)] if i >= 0 else None


# ---------- link policy (checked before any host fetch) ----------
BLOCKED_HOSTS = {
    # URL shorteners / redirectors hide the real destination.
    'bit.ly', 'tinyurl.com', 't.co', 'goo.gl', 'ow.ly', 'is.gd', 'buff.ly', 'rebrand.ly', 'cutt.ly', 'lnkd.in',
    # Paste and file hosts: anyone can publish anything.
    'pastebin.com', 'paste.ee', 'ghostbin.com', 'hastebin.com', 'justpaste.it', 'rentry.co',
    'drive.google.com', 'docs.google.com', 'dropbox.com', 'mega.nz', 'wetransfer.com', 'mediafire.com',
}


def canonical_url(url):
    parts = urlsplit(url.strip())
    host = (parts.hostname or '').lower().removeprefix('www.')
    return f"{parts.scheme.lower()}://{host}{parts.path.rstrip('/') or ''}{'?' + parts.query if parts.query else ''}"


def link_policy(url):
    """Return None if the cited URL may be fetched, else a reason code."""
    parts = urlsplit(url)
    host = (parts.hostname or '').lower().removeprefix('www.')
    if parts.scheme != 'https':
        return 'link_not_https'
    if not host or parts.username or parts.password or (parts.port not in (None, 443)):
        return 'link_malformed'
    if any(host == b or host.endswith('.' + b) for b in BLOCKED_HOSTS):
        return 'link_blocked_host'
    if re.fullmatch(r'[\d.]+|\[[0-9a-f:]+\]', host):
        return 'link_raw_ip'
    return None


# ---------- injection scan (deterministic, on every stored snapshot) ----------
INJECTION_PATTERNS = {
    'override_instructions': r'\b(ignore|disregard|forget|override)\b.{0,40}\b(previous|prior|above|earlier|all|system)\b.{0,20}\b(instructions?|prompts?)',
    'addresses_ai': r'\b(you are (now )?(an?|the) (ai|assistant|model|llm|chatbot)|as an ai\b|(ai|llm|language model|assistant)s?,? (must|should|please))',
    'verdict_manipulation': r'\b(mark|label|rate|treat|consider)\b.{0,40}\b(as )?(supported|verified|true|approved|accepted)\b',
    'role_markers': r'(<\s*/?\s*(system|assistant|instructions?)\s*>|\[\s*(system|inst)\s*\]|\bsystem prompt\b)',
    'hidden_task': r'\b(new|updated|additional) (task|instructions?|directive)s?\s*:',
}


def scan_injection(text):
    """Labels of injection-like patterns found. Detection is heuristic: it flags
    pages for human review; it never makes a page trusted."""
    return sorted(label for label, pattern in INJECTION_PATTERNS.items() if re.search(pattern, text, re.I))


def trust_tier(url):
    host = (urlsplit(url).hostname or '').lower()
    return 'institutional' if host.endswith(INSTITUTIONAL_SUFFIXES) else 'needs_review'


def check_sources(urls, fetch, evidence):
    """Fetch each unique URL once. Returns {url: {status, source_id?, text?, error?}}.

    `fetch(url) -> {url, content, media_type}` is trusted host code (the harness
    Fetcher in production: public addresses only, bounded size/time/redirects).
    """
    results = {}
    for url in dict.fromkeys(urls):
        try:
            page = fetch(url)
            text = page_text(page['content'], page['media_type'])
            if not text:
                raise ValueError('empty page')
            source_id = evidence.snapshot(url, text)
            stored = evidence.source(source_id)['content']
            results[url] = {'status': 'fetched', 'source_id': source_id, 'text': stored,
                            'injection': scan_injection(stored)}
        except Exception as exc:  # recorded, never fatal: claim becomes needs_review
            results[url] = {'status': 'unreachable', 'error': type(exc).__name__ + ': ' + str(exc)[:120]}
    return results
