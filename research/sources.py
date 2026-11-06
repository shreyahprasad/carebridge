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
            results[url] = {'status': 'fetched', 'source_id': source_id,
                            'text': evidence.source(source_id)['content']}
        except Exception as exc:  # recorded, never fatal: claim becomes needs_review
            results[url] = {'status': 'unreachable', 'error': type(exc).__name__ + ': ' + str(exc)[:120]}
    return results
