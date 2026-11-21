"""Bounded public Reddit community feeds; no login or invented engagement.

Fresh feed entries are candidates, never proof of relevance. All still pass
the product-specific semantic and unresolved-need gates before display.
"""
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import hashlib
import re
import threading
import time
import xml.etree.ElementTree as ET

import httpx

ATOM = '{http://www.w3.org/2005/Atom}'
_lock = threading.Lock()
_cache = {}
_retry_after = 0.0


class FeedUnavailable(RuntimeError):
    pass


class PostText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def parse_feed(xml, now=None):
    from live_discovery import post_identity, plain_excerpt
    if len(xml.encode()) > 750_000 or '<!DOCTYPE' in xml.upper() or '<!ENTITY' in xml.upper():
        raise ValueError('Unsupported public feed.')
    now = now or datetime.now(timezone.utc)
    results = []
    root = ET.fromstring(xml)
    for entry in root.findall(ATOM+'entry')[:25]:
        link = next((link.get('href', '') for link in entry.findall(ATOM+'link') if link.get('rel', 'alternate') == 'alternate'), '')
        identity = post_identity(link)
        if not identity or identity[0] != 'Reddit':
            continue
        # Atom updated can be an edit. Recency must use original publication.
        try:
            published = datetime.fromisoformat(entry.findtext(ATOM+'published', '').replace('Z', '+00:00'))
            if published.tzinfo is None:
                continue
            if not now-timedelta(days=30) <= published <= now+timedelta(hours=1):
                continue
        except ValueError:
            continue
        title = entry.findtext(ATOM+'title', '').strip()[:400]
        content = entry.findtext(ATOM+'content', '')
        # The feed adds author/link/comment controls after the original body.
        content = re.split(r'(?i)submitted by|&#32;submitted', content, maxsplit=1)[0]
        parser = PostText()
        parser.feed(content)
        summary = plain_excerpt(' '.join(parser.parts), title)[:8000]
        if len(title) < 8 or len(summary) < 30:
            continue
        category = entry.find(ATOM+'category')
        community = category.get('term', '') if category is not None else ''
        author = entry.findtext(ATOM+'author/'+ATOM+'name', '')
        results.append({
            'id': 'live-'+hashlib.sha256(identity[1].encode()).hexdigest()[:20],
            'platform': 'Reddit', 'kind': 'Discussion', 'url': identity[1],
            'title': title, 'summary': summary, 'author': author or ('r/'+community),
            'community': 'r/'+community if community else '',
            'published_at': published.isoformat(), 'section': 'conversations',
            'competitor': False, 'tone': 'cream', 'matched_terms': [],
            'evidence': {'type': 'original_platform_post', 'provider': 'reddit_public_feed',
                         'engagement_verified': False, 'excerpt': False},
        })
    return results


def fetch_recent(community):
    global _retry_after
    from research_retrieval import connect
    if not re.fullmatch(r'[A-Za-z0-9_]{2,40}', community):
        raise ValueError('Invalid community name.')
    key = community.lower()
    # Serialize requests so concurrent projects cannot create a feed burst.
    with _lock:
        now = time.monotonic()
        cached = _cache.get(key)
        if cached and now-cached[0] < 900:
            return [dict(item) for item in cached[1]]
        with connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS community_feed_cache(community TEXT PRIMARY KEY,data TEXT,checked REAL)')
            db.execute('CREATE TABLE IF NOT EXISTS community_feed_state(name TEXT PRIMARY KEY,value REAL)')
            stored = db.execute('SELECT data FROM community_feed_cache WHERE community=? AND checked>?', (key,time.time()-900)).fetchone()
            retry = db.execute("SELECT value FROM community_feed_state WHERE name='retry_after'").fetchone()
        if stored:
            import json
            return json.loads(stored[0])
        if now < _retry_after or retry and time.time() < retry[0]:
            raise FeedUnavailable('Public community feeds are temporarily rate-limited.')
        response = httpx.get('https://www.reddit.com/r/'+community+'/new/.rss',
                             params={'limit': 25}, timeout=8, follow_redirects=False,
                             headers={'User-Agent': 'OutloudResearch/0.1 (public feed reader)'})
        if response.status_code in (403, 429):
            delay = response.headers.get('retry-after', '')
            seconds = max(60, min(3600, int(delay) if delay.isdigit() else 300))
            _retry_after = now+seconds
            with connect() as db:
                db.execute("INSERT OR REPLACE INTO community_feed_state VALUES('retry_after',?)", (time.time()+seconds,))
            raise FeedUnavailable('Public community feeds are temporarily unavailable.')
        response.raise_for_status()
        results = parse_feed(response.text)
        import json
        with connect() as db:
            db.execute('INSERT OR REPLACE INTO community_feed_cache VALUES(?,?,?)', (key,json.dumps(results),time.time()))
            db.execute('DELETE FROM community_feed_cache WHERE checked<?', (time.time()-86400,))
        if len(_cache) >= 100:
            _cache.pop(next(iter(_cache)))
        _cache[key] = (time.monotonic(), results)
        return [dict(item) for item in results]
