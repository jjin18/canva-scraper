"""
Canva Collaboration Pain Scraper
Run locally: python scraper/canva_scraper.py (from repo root)
Opens results in browser as a clean page with direct quotes + source links.

Install first:
  pip install requests beautifulsoup4 google-play-scraper
"""

import json, os, re, time, webbrowser, datetime
from html import escape
from collections import Counter

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("Run: pip install requests beautifulsoup4")
    exit(1)

# Observable friction / pain (avoid bare “review” — matches everything).
_FRICTION_PHRASES = [
    "difficulty", "difficulties", "frustrat", "frustrating", "confus", "confusing", "confused",
    "bottleneck", "messy", "chaos", "nightmare", "scattered",
    "lost track", "out of sync", "unsynced", "duplicate work", "duplicated",
    "version control", "wrong version", "which version", "old version",
    "back and forth", "back-and-forth", "slow", "tedious",
    "difficult", "hard to", "can't ", "cannot ", "couldn't ",
    "broken", "doesn't work", "does not work", "not intuitive", "unclear",
    "disappoint", "lacking", "missing", "wish ", "problem ", " problems",
    "permission", "access issue", "locked out",
]

_SOFT_FRICTION = [
    "issue with", "issues with", "struggle", "struggling", "annoying", "annoyed",
    "waste of time", "time-consuming", "time consuming", "inefficient",
]

# Light collaboration / work context (widens recall; paired with pain in scoring).
_COLLAB_LIGHT = [
    ("collaborat", 3),
    ("team", 2),
    ("teams", 2),
    ("sharing", 2),
    ("share with", 2),
    ("together", 2),
    ("everyone", 2),
    ("group", 2),
    ("project", 2),
    ("presentation", 2),
    ("meeting", 2),
    ("colleague", 3),
    ("coworker", 3),
    ("client", 2),
    ("feedback", 2),
    ("comment", 2),
    ("assign", 2),
    ("template", 2),
    ("brand", 2),
]

# Extra pain tokens for recall (short reviews).
_EXTRA_PAIN = [
    "glitch", "bug", "bugs", "error", "crash", "hate", "worst", "terrible", "awful",
    "disappoint", "annoying", "annoyed", "useless", "sucks", "bad ", " worse",
    "not good", "isn't good", "isnt good", "doesn't help", "waste",
]

# Weighted dimensions: real reviews rarely say “enterprise + stakeholder + pain” in one line.
_BIZ_WEIGHTED = [
    ("canva enterprise", 6),
    ("canva for teams", 6),
    ("canva pro", 4),
    ("business plan", 5),
    ("enterprise plan", 5),
    ("enterprise subscription", 5),
    ("enterprise license", 5),
    ("brand kit", 5),
    ("brand template", 4),
    ("brand control", 4),
    ("workspace", 4),
    ("single sign-on", 4),
    ("sso integration", 4),
    ("saml", 4),
    ("team admin", 4),
    ("org admin", 4),
    ("seat management", 4),
    ("license management", 4),
    ("folder permission", 3),
    ("role-based", 3),
    ("b2b", 4),
    ("organization-wide", 4),
    ("organisation-wide", 4),
    ("company-wide", 4),
    ("teams plan", 4),
    ("team plan", 4),
    ("agency", 4),
    ("our client", 3),
    ("clients ", 3),
    ("our company", 3),
    ("our organization", 3),
    ("our organisation", 3),
]

_MULTI_WEIGHTED = [
    ("integration", 4),
    ("third-party", 4),
    ("third party", 4),
    ("non-profit", 4),
    ("nonprofit", 3),
    ("charity", 3),
    ("parish", 3),
    ("bulletin", 3),
    ("stakeholder", 6),
    ("stakeholders", 6),
    ("cross-functional", 6),
    ("cross functional", 6),
    ("cross-team", 5),
    ("cross team", 5),
    ("approval process", 5),
    ("approval workflow", 5),
    ("chain of approval", 6),
    ("multiple departments", 5),
    ("different departments", 4),
    ("client approval", 5),
    ("legal approval", 5),
    ("brand team", 4),
    ("marketing team", 4),
    ("creative team", 4),
    ("multiple people", 5),
    ("several people", 4),
    ("too many people", 4),
    ("rounds of feedback", 5),
    ("conflicting feedback", 5),
    ("feedback loop", 4),
    ("sign-off", 4),
    ("sign off", 4),
    ("handoff", 4),
    ("hand-off", 4),
    ("design review", 4),
    ("review cycle", 4),
]

_PAIN_WEIGHTED = (
    [(p, 3) for p in _FRICTION_PHRASES]
    + [(p, 2) for p in _SOFT_FRICTION]
    + [(p, 2) for p in _EXTRA_PAIN]
)


def clean(text):
    return re.sub(r'\s+', ' ', text or '').strip()


def _uniq_preserve(seq):
    seen = set()
    out = []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _weighted_hits(t, weighted_pairs):
    """Longest-first substring matches; each phrase matched at most once."""
    t = t.lower()
    pairs = sorted(weighted_pairs, key=lambda x: len(x[0]), reverse=True)
    hits = []
    score = 0
    masked = t
    for phrase, w in pairs:
        if phrase in masked:
            hits.append(phrase.strip())
            score += w
            masked = masked.replace(phrase, " ", 1)
    return score, _uniq_preserve(hits)


def _strong_biz_anchor(t):
    tl = t.lower()
    return any(
        x in tl
        for x in (
            "enterprise",
            "canva for teams",
            "canva enterprise",
            "brand kit",
            "workspace",
            "sso",
            "saml",
            "team admin",
            "org admin",
            "seat",
            "b2b",
            "organization-wide",
            "company-wide",
        )
    )


def _strong_multi_anchor(t):
    tl = t.lower()
    if any(
        x in tl
        for x in (
            "stakeholder",
            "cross-functional",
            "cross functional",
            "cross-team",
            "approval process",
            "approval workflow",
            "multiple people",
            "several people",
            "too many people",
            "chain of approval",
            "client approval",
            "multiple departments",
        )
    ):
        return True
    if re.search(r"(?<!dis)approvals?\b", tl, re.I):
        return True
    if re.search(r"\bstakeholders?\b", tl, re.I):
        return True
    if re.search(r"\bintegration\b", tl, re.I) and re.search(
        r"\b(canva|partner|vendor|third|workflow|api)\b", tl, re.I
    ):
        return True
    return False


def _regex_multi_boost(tl):
    """Word-boundary boosts for approval / stakeholder language (substring lists miss these)."""
    score = 0
    hits = []
    if re.search(r"(?<!dis)approvals?\b", tl, re.I):
        score += 4
        hits.append("approval")
    if re.search(r"\bstakeholders?\b", tl, re.I):
        score += 5
        hits.append("stakeholder-word")
    if re.search(r"\bfeedback\b", tl, re.I) and re.search(
        r"\b(team|everyone|multiple|client|manager|boss|brand)\b", tl, re.I
    ):
        score += 3
        hits.append("feedback+org")
    if re.search(r"\bteams?\b", tl, re.I) and re.search(
        r"\b(canva|design|project|brand|client|collaborat|share)\w*", tl, re.I
    ):
        score += 3
        hits.append("teams+context")
    return score, hits


def is_relevant(text, source_hint=None):
    """
    Collaboration / work / team context + friction. Intentionally broad — tune lists above to tighten.

    source_hint: 'gplay' | 'appstore' for store listings (review text is implicitly about Canva).
    """
    t = clean(text)
    if len(t) < 40:
        return False, []

    biz_score, biz_hits = _weighted_hits(t, _BIZ_WEIGHTED)
    multi_score, multi_hits = _weighted_hits(t, _MULTI_WEIGHTED)
    collab_score, collab_hits = _weighted_hits(t, _COLLAB_LIGHT)
    pain_score, pain_hits = _weighted_hits(t, _PAIN_WEIGHTED)

    tl = t.lower()
    rm_s, rm_h = _regex_multi_boost(tl)
    multi_score += rm_s
    multi_hits.extend(rm_h)

    if "canva" in tl and any(
        x in tl for x in ("for teams", "teams plan", "team plan", "brand kit", "workspace")
    ):
        biz_score += 5
        biz_hits.append("canva+b2b")
    if any(x in tl for x in ("our agency", "our client", "our company", "our organization")):
        biz_score += 3
        biz_hits.append("org-context")

    # Score without store-listing bonuses — otherwise almost every Play review clears “work” thresholds.
    biz_before_store = biz_score

    # Store reviews are always about the Canva product — tag + small score for HTML chips only.
    if source_hint in ("gplay", "appstore"):
        biz_score += 2
        biz_hits.append("store:canva-app")
        if re.search(
            r"\b(team|teams|business|company|client|clients|brand|work|marketing|agency|office|org)\b",
            tl,
            re.I,
        ):
            biz_score += 1
            biz_hits.append("store:biz-vocab")

    biz_hits = _uniq_preserve(biz_hits)
    multi_hits = _uniq_preserve(multi_hits + collab_hits)
    pain_hits = _uniq_preserve(pain_hits)

    work_gate = biz_before_store + multi_score + collab_score
    work = biz_score + multi_score + collab_score
    total_gate = work_gate + pain_score

    strong_biz = _strong_biz_anchor(t) or biz_before_store >= 4
    strong_multi = _strong_multi_anchor(t) or multi_score >= 4
    has_pain = pain_score >= 2 or any(
        p in tl
        for p in (
            "frustrat",
            "confus",
            "messy",
            "broken",
            "difficult",
            "slow",
            "nightmare",
            "glitch",
            "bug",
            "error",
            "hate",
            "worst",
            "terrible",
            "annoy",
            "disappoint",
        )
    )

    # Narrow “enterprise + multi-stakeholder” tier (optional high precision).
    tier_strict = strong_biz and strong_multi and has_pain and biz_before_store >= 2 and multi_score >= 2

    # Broad tiers (primary paths for volume) — use work_gate so store boosts don’t auto-pass.
    tier_sum = total_gate >= 10 and pain_score >= 2 and work_gate >= 4
    tier_pain_work = pain_score >= 3 and work_gate >= 4
    tier_mild = pain_score >= 2 and work_gate >= 6
    tier_soft = pain_score >= 2 and work_gate >= 5 and len(t) >= 70

    # App / Play: always Canva-related, but don’t let “template/brand” alone pass with weak pain.
    _strong_neg = re.search(
        r"\b(frustrat|confus|bug|bugs|error|crash|hate|worst|terrible|awful|broken|slow|annoy|disappoint|glitch|nightmare|useless|sucks|horrible|pathetic)\w*",
        tl,
        re.I,
    )
    tier_store = (
        source_hint in ("gplay", "appstore")
        and len(t) >= 55
        and (
            (pain_score >= 3 and work_gate >= 2)
            or (pain_score >= 2 and work_gate >= 7)
            or (pain_score >= 2 and _strong_neg is not None)
        )
    )

    ok = (
        tier_strict
        or tier_sum
        or tier_pain_work
        or tier_mild
        or tier_soft
        or tier_store
    )

    if not ok:
        return False, []

    tags = (
        [f"biz:{x}" for x in biz_hits[:5]]
        + [f"multi:{x}" for x in multi_hits[:5]]
        + [f"pain:{x}" for x in pain_hits[:6]]
    )
    return True, _uniq_preserve(tags)[:14]

results = []

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                  'AppleWebKit/537.36 (KHTML, like Gecko) '
                  'Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}

# ── SOURCE 1: Google Play Store ───────────────────────────────────────────────
print("📱 Google Play Store...")
try:
    from google_play_scraper import reviews, Sort
    gplay, _ = reviews(
        'com.canva.editor', lang='en', country='us',
        sort=Sort.MOST_RELEVANT, count=500
    )
    n = 0
    for r in gplay:
        text = clean(r.get('content', ''))
        ok, hits = is_relevant(text, 'gplay')
        if ok and len(text) > 60:
            results.append({
                'source': 'Google Play',
                'rating': r.get('score'),
                'date': str(r.get('at', ''))[:10],
                'text': text,
                'url': 'https://play.google.com/store/apps/details?id=com.canva.editor&showAllReviews=true',
                'author': r.get('userName', 'Anonymous'),
                'keywords': hits,
            })
            n += 1
    print(f"  ✓ {n} relevant reviews from {len(gplay)} scraped")
except Exception as e:
    print(f"  ✗ {e}")

# ── SOURCE 2: App Store (via RSS) ─────────────────────────────────────────────
print("🍎 App Store (RSS)...")
try:
    # Apple provides public RSS feeds for app reviews
    app_id = "897446215"  # Canva app ID
    n = 0
    for page in range(1, 6):
        url = f"https://itunes.apple.com/us/rss/customerreviews/page={page}/id={app_id}/sortby=mostrecent/json"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code != 200:
            break
        data = resp.json()
        entries = data.get('feed', {}).get('entry', [])
        if not entries:
            break
        for entry in entries:
            if isinstance(entry, dict):
                text = clean(entry.get('content', {}).get('label', ''))
                title = clean(entry.get('title', {}).get('label', ''))
                rating = entry.get('im:rating', {}).get('label', '')
                author = entry.get('author', {}).get('name', {}).get('label', 'Anonymous')
                combined = f"{title}. {text}"
                ok, hits = is_relevant(combined, 'appstore')
                if ok and len(combined) > 60:
                    results.append({
                        'source': 'App Store',
                        'rating': int(rating) if rating.isdigit() else None,
                        'date': '',
                        'text': combined[:600],
                        'url': f'https://apps.apple.com/us/app/canva-design-photo-video/id{app_id}',
                        'author': author,
                        'keywords': hits,
                    })
                    n += 1
        time.sleep(0.5)
    print(f"  ✓ {n} relevant reviews")
except Exception as e:
    print(f"  ✗ {e}")

# ── SOURCE 3: Reddit ──────────────────────────────────────────────────────────
print("🔴 Reddit...")
REDDIT_HEADERS = {**HEADERS, 'User-Agent': 'CanvaResearchScript/1.0'}
subreddits_queries = [
    ('canva',          'enterprise brand kit approval'),
    ('canva',          'Canva for Teams workflow'),
    ('canva',          'stakeholder approval frustrating'),
    ('canva',          'admin permission seat'),
    ('graphic_design', 'Canva enterprise team'),
    ('marketing',      'Canva approval workflow client'),
    ('sysadmin',       'Canva SSO SAML'),
    ('ITManagers',     'Canva enterprise'),
]
seen = set()
n = 0
for sub, q in subreddits_queries:
    url = (f"https://www.reddit.com/r/{sub}/search.json"
           f"?q={requests.utils.quote(q)}&restrict_sr=1&sort=relevance&limit=50&t=all")
    try:
        resp = requests.get(url, headers=REDDIT_HEADERS, timeout=10)
        if resp.status_code != 200:
            continue
        posts = resp.json().get('data', {}).get('children', [])
        for post in posts:
            d = post.get('data', {})
            pid = d.get('id')
            if pid in seen: continue
            seen.add(pid)
            title = clean(d.get('title', ''))
            body  = clean(d.get('selftext', ''))
            combined = f"{title}. {body}"
            ok, hits = is_relevant(combined)
            if ok and len(combined) > 80:
                results.append({
                    'source': f'Reddit r/{sub}',
                    'rating': None,
                    'date': str(datetime.datetime.fromtimestamp(d.get('created_utc', 0)))[:10],
                    'text': combined[:700],
                    'url': f"https://reddit.com{d.get('permalink', '')}",
                    'author': d.get('author', 'u/unknown'),
                    'keywords': hits,
                    'upvotes': d.get('score', 0),
                })
                n += 1
                # Grab top comments too
                c_url = f"https://www.reddit.com{d.get('permalink')}.json?limit=5"
                try:
                    cr = requests.get(c_url, headers=REDDIT_HEADERS, timeout=8)
                    if cr.status_code == 200:
                        cdata = cr.json()
                        if len(cdata) > 1:
                            for comment in cdata[1].get('data',{}).get('children',[])[:4]:
                                cb = clean(comment.get('data',{}).get('body',''))
                                cok, chits = is_relevant(cb)
                                if cok and len(cb) > 60:
                                    results.append({
                                        'source': f'Reddit r/{sub} [comment]',
                                        'rating': None,
                                        'date': str(datetime.datetime.fromtimestamp(
                                            comment.get('data',{}).get('created_utc',0)))[:10],
                                        'text': cb[:500],
                                        'url': f"https://reddit.com{d.get('permalink', '')}",
                                        'author': comment.get('data',{}).get('author','u/unknown'),
                                        'keywords': chits,
                                    })
                                    n += 1
                    time.sleep(0.3)
                except: pass
        time.sleep(1.5)
    except Exception as e:
        print(f"  ✗ r/{sub}: {e}")
print(f"  ✓ {n} relevant posts/comments")

# ── SOURCE 4: Capterra ────────────────────────────────────────────────────────
print("📊 Capterra...")
n = 0
for page in range(1, 8):
    url = f"https://www.capterra.com/p/168956/Canva/#reviews?page={page}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=12)
        soup = BeautifulSoup(resp.text, 'html.parser')
        # Try several selectors Capterra uses
        blocks = (soup.find_all('div', attrs={'data-testid': re.compile(r'review')}) or
                  soup.find_all('div', class_=re.compile(r'e1xzmg0j|review-text|nb4m8s', re.I)) or
                  soup.select('article[class*="review"]'))
        for block in blocks:
            text = clean(block.get_text(separator=' '))
            if len(text) < 80: continue
            ok, hits = is_relevant(text)
            if ok:
                # Try to find rating
                r_el = block.find(attrs={'aria-label': re.compile(r'\d.*star', re.I)})
                rating = None
                if r_el:
                    m = re.search(r'(\d)', r_el.get('aria-label',''))
                    if m: rating = int(m.group(1))
                results.append({
                    'source': 'Capterra',
                    'rating': rating,
                    'date': '',
                    'text': text[:600],
                    'url': f'https://www.capterra.com/p/168956/Canva/#reviews?page={page}',
                    'author': '',
                    'keywords': hits,
                })
                n += 1
        time.sleep(1.5)
    except Exception as e:
        print(f"  ✗ Capterra page {page}: {e}")
print(f"  ✓ {n} relevant reviews")

# ── SOURCE 5: Trustpilot (embedded __NEXT_DATA__ JSON — HTML selectors break often) ──
print("⭐ Trustpilot...")
n = 0
_tp_seen = set()
for page in range(1, 8):
    url = f"https://www.trustpilot.com/review/canva.com?page={page}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=12)
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>([^<]+)</script>', resp.text)
        if not m:
            time.sleep(1.5)
            continue
        payload = json.loads(m.group(1))
        pp = payload.get("props", {}).get("pageProps", {})
        chunks = []
        for key in ("reviews", "relevantReviews", "aiSummaryReviews"):
            chunks.extend(pp.get(key) or [])
        for entry in chunks:
            if not isinstance(entry, dict):
                continue
            text = clean(entry.get("text") or entry.get("body") or "")
            if len(text) < 80:
                continue
            sig = text[:140]
            if sig in _tp_seen:
                continue
            _tp_seen.add(sig)
            ok, hits = is_relevant(text)
            if ok:
                results.append({
                    'source': 'Trustpilot',
                    'rating': entry.get("rating"),
                    'date': str(entry.get("dates", {}).get("experienceDate", "") or "")[:10],
                    'text': text[:800],
                    'url': f'https://www.trustpilot.com/review/canva.com?page={page}',
                    'author': (entry.get("consumer") or {}).get("displayName", "") or "",
                    'keywords': hits,
                })
                n += 1
        time.sleep(1.5)
    except Exception as e:
        print(f"  ✗ Trustpilot page {page}: {e}")
print(f"  ✓ {n} relevant reviews")

# ── SOURCE 6: Product Hunt ────────────────────────────────────────────────────
print("🚀 Product Hunt...")
n = 0
ph_urls = [
    "https://www.producthunt.com/products/canva/reviews",
    "https://www.producthunt.com/posts/canva-for-teams",
]
for url in ph_urls:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=12)
        soup = BeautifulSoup(resp.text, 'html.parser')
        for el in soup.find_all(['p', 'div'], class_=re.compile(r'review|comment|body|text', re.I)):
            text = clean(el.get_text())
            if len(text) < 80: continue
            ok, hits = is_relevant(text)
            if ok:
                results.append({
                    'source': 'Product Hunt',
                    'rating': None,
                    'date': '',
                    'text': text[:500],
                    'url': url,
                    'author': '',
                    'keywords': hits,
                })
                n += 1
        time.sleep(1)
    except Exception as e:
        print(f"  ✗ PH: {e}")
print(f"  ✓ {n} relevant reviews")

# ── SOURCE 7: G2 ─────────────────────────────────────────────────────────────
print("⭐ G2...")
n = 0
for page in range(1, 8):
    url = f"https://www.g2.com/products/canva/reviews?page={page}"
    try:
        resp = requests.get(url, headers={
            **HEADERS,
            'Accept': 'text/html',
            'Referer': 'https://www.g2.com/',
        }, timeout=12)
        soup = BeautifulSoup(resp.text, 'html.parser')
        # G2 uses itemprop="review" or class patterns
        blocks = (soup.find_all(itemprop='review') or
                  soup.find_all('div', class_=re.compile(r'review-text|formatted-text', re.I)) or
                  soup.select('[data-content]'))
        for block in blocks:
            text = clean(block.get_text(separator=' '))
            if len(text) < 80: continue
            ok, hits = is_relevant(text)
            if ok:
                results.append({
                    'source': 'G2',
                    'rating': None,
                    'date': '',
                    'text': text[:600],
                    'url': f'https://www.g2.com/products/canva/reviews?page={page}',
                    'author': '',
                    'keywords': hits,
                })
                n += 1
        time.sleep(2)
    except Exception as e:
        print(f"  ✗ G2 page {page}: {e}")
print(f"  ✓ {n} relevant reviews")

# ── DEDUPLICATE ───────────────────────────────────────────────────────────────
seen_texts = set()
deduped = []
for r in results:
    sig = r['text'][:120]
    if sig not in seen_texts:
        seen_texts.add(sig)
        deduped.append(r)
results = deduped

# Score by keyword count
results.sort(key=lambda x: len(x['keywords']), reverse=True)

# Keyword frequency
all_kw = []
for r in results:
    all_kw.extend(r['keywords'])
kw_freq = Counter(all_kw).most_common(20)

print(f"\n{'='*55}")
print(f"TOTAL: {len(results)} relevant quotes across all sources")
print(f"{'='*55}")
print("\nTop pain keywords:")
for kw, n in kw_freq[:10]:
    print(f"  {kw:<25} {n}")

# ── RENDER HTML ───────────────────────────────────────────────────────────────
source_colors = {
    'Google Play':   '#01875f',
    'App Store':     '#0071e3',
    'Trustpilot':    '#00b67a',
    'Capterra':      '#ff6c2f',
    'G2':            '#ff492c',
    'Product Hunt':  '#da552f',
}

def src_color(src):
    for k, v in source_colors.items():
        if k in src: return v
    return '#666'  # Reddit default

def stars(n):
    if n is None: return ''
    return '★' * int(n) + '☆' * (5 - int(n))

def _unknown_tag_pretty(t):
    """Last segment only, no colons — e.g. canva-app → Canva app, teams+context → Teams context."""
    tail = t.split(":")[-1]
    tail = tail.replace("+", " ").replace("_", " ")
    parts = re.split(r"[\s-]+", tail)
    parts = [p for p in parts if p]
    out = []
    for p in parts:
        pl = p.lower().rstrip("'")
        if pl in ("cant",) or p.lower() == "can't":
            out.append("can't")
        elif pl in ("couldnt",) or "couldn" in pl:
            out.append("couldn't")
        elif pl in ("wont",) or p.lower() == "won't":
            out.append("won't")
        elif len(p) > 1:
            out.append(p[0].upper() + p[1:].lower())
        else:
            out.append(p.upper())
    return " ".join(out) if out else t


def readable_tag(tag):
    """Plain English only — never show raw keys like biz:store:canva-app on the page."""
    t = " ".join((tag or "").split()).strip()
    if not t:
        return ""

    # Curated labels (high-traffic). No internal-style prefixes in the visible text.
    exact = {
        "biz:store:canva-app": "Mobile app store listing",
        "biz:store:biz-vocab": "Uses work or business words",
        "biz:canva+b2b": "Canva Teams / B2B hint",
        "biz:org-context": "Company / organization",
        "biz:workspace": "Workspace",
        "multi:teams+context": "Team + design or project work",
        "multi:team": "Team",
        "multi:project": "Project",
        "multi:template": "Templates",
        "multi:brand": "Brand",
        "multi:presentation": "Presentations",
        "multi:together": "Together / group",
        "multi:feedback+org": "Feedback (work context)",
        "multi:approval": "Approval",
        "multi:collaborat": "Collaboration",
        "multi:sharing": "Sharing",
        "multi:stakeholder-word": "Stakeholders",
        "multi:client": "Clients",
        "multi:comment": "Comments",
        "multi:assign": "Assigning",
        "multi:meeting": "Meetings",
        "multi:colleague": "Colleagues",
        "multi:coworker": "Coworkers",
        "multi:everyone": "Everyone / whole group",
        "multi:group": "Group",
        "tag:teams+context": "Team context (auto-tagged)",
        "tag:team": "Team (auto-tagged)",
        "tag:collab+work": "Collaboration + work (auto-tagged)",
        "pain:problem": "Problem",
        "pain:problems": "Problems",
        "pain:terrible": "Terrible",
        "pain:cannot": "Cannot (blocked)",
        "pain:can't": "Can’t / blocked",
        "pain:couldn't": "Couldn’t",
        "pain:error": "Errors",
        "pain:bug": "Bug",
        "pain:bugs": "Bugs",
        "pain:disappoint": "Disappointed",
        "pain:difficult": "Difficult",
        "pain:difficulty": "Difficulty",
        "pain:difficulties": "Difficulties",
        "pain:frustrat": "Frustrated",
        "pain:frustrating": "Frustrating",
        "pain:confus": "Confusing",
        "pain:confusing": "Confusing",
        "pain:confused": "Confused",
        "pain:slow": "Slow",
        "pain:crash": "Crashes",
        "pain:glitch": "Glitches",
        "pain:broken": "Broken",
        "pain:hate": "Hate (strong negative)",
        "pain:worst": "Worst",
        "pain:nightmare": "Nightmare",
        "pain:useless": "Useless",
        "pain:sucks": "Strong negative",
        "pain:annoying": "Annoying",
        "pain:annoyed": "Annoyed",
        "pain:missing": "Missing",
        "pain:lacking": "Lacking",
        "pain:issues with": "Issues",
        "pain:issue with": "Issue",
        "pain:time consuming": "Time-consuming",
        "pain:time-consuming": "Time-consuming",
        "pain:inefficient": "Inefficient",
        "pain:struggle": "Struggling",
        "pain:struggling": "Struggling",
        "pain:waste of time": "Waste of time",
        "pain:permission": "Permissions",
        "pain:access issue": "Access issues",
        "pain:locked out": "Locked out",
        "pain:back-and-forth": "Back-and-forth",
        "pain:back and forth": "Back and forth",
        "pain:duplicate work": "Duplicate work",
        "pain:version control": "Version control",
        "pain:wrong version": "Wrong version",
        "pain:which version": "Which version",
        "pain:old version": "Old version",
        "pain:out of sync": "Out of sync",
        "pain:unsynced": "Unsynced",
        "pain:duplicate": "Duplicate",
        "pain:duplicated": "Duplicated",
        "pain:tedious": "Tedious",
        "pain:hard to": "Hard to use",
        "pain:doesn't work": "Doesn’t work",
        "pain:does not work": "Does not work",
        "pain:not intuitive": "Not intuitive",
        "pain:unclear": "Unclear",
        "pain:wish": "Wish / want",
        "pain:chaos": "Chaos",
        "pain:bottleneck": "Bottleneck",
        "pain:messy": "Messy",
        "pain:scattered": "Scattered",
        "pain:lost track": "Lost track",
        "pain:horrible": "Horrible",
        "pain:pathetic": "Pathetic",
        "pain:worse": "Worse",
        "pain:bad": "Bad",
        "pain:awful": "Awful",
        "pain:not good": "Not good",
        "pain:isn't good": "Not good",
        "pain:isnt good": "Not good",
        "pain:doesn't help": "Doesn’t help",
        "pain:waste": "Waste",
    }

    if t in exact:
        return exact[t]

    return _unknown_tag_pretty(t)


def freq_label_short(label: str, max_chars: int = 16) -> str:
    """Chart labels only: max length so rows don’t clump."""
    if not label:
        return ""
    if len(label) <= max_chars:
        return label
    return label[: max_chars - 1] + "…"


def best_sentence(text, keywords):
    """Return the single most keyword-dense sentence."""
    flat = [k.split(":", 1)[-1].strip() if ":" in k else k for k in keywords]
    sentences = [s.strip() for s in re.split(r'[.!?]', text) if len(s.strip()) > 40]
    if not sentences:
        return text[:300]
    scored = sorted(
        sentences,
        key=lambda s: sum(1 for k in flat if k and k in s.lower()),
        reverse=True,
    )
    return scored[0]

kw_max = kw_freq[0][1] if kw_freq else 1

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Canva Collaboration Pain — {len(results)} quotes</title>
<style>
  :root {{
    --bg: #f4f2ee;
    --card: #ffffff;
    --text: #1a1a1a;
    --muted: #6b6b6b;
    --border: #e2ddd4;
    --accent: #b83232;
    --sans: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
    --serif: "Iowan Old Style", "Palatino Linotype", Palatino, Georgia, serif;
  }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: var(--serif); background: var(--bg); color: var(--text); margin: 0; padding: 0; line-height: 1.5; }}
  .page {{ max-width: 920px; margin: 0 auto; padding: 2rem 1.25rem 3rem; }}
  h1 {{ font-size: clamp(1.75rem, 4vw, 2.35rem); font-weight: 700; line-height: 1.2; margin: 0 0 0.75rem; font-family: var(--sans); }}
  .subtitle {{ font-size: 0.95rem; color: var(--muted); line-height: 1.55; margin: 0 0 1.75rem; max-width: 42rem; font-family: var(--sans); }}
  .sticky-tools {{
    position: sticky; top: 0; z-index: 20;
    background: rgba(244, 242, 238, 0.92);
    backdrop-filter: blur(10px);
    -webkit-backdrop-filter: blur(10px);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 0.75rem 1rem;
    margin-bottom: 1.5rem;
    box-shadow: 0 4px 24px rgba(0,0,0,.06);
    font-family: var(--sans);
  }}
  .sticky-tools-inner {{ display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem 0.75rem; }}
  .filter-buttons {{ display: flex; flex-wrap: wrap; gap: 0.35rem; align-items: center; }}
  .filter-btn {{
    padding: 0.4rem 0.85rem; border-radius: 999px; border: 1px solid var(--border);
    background: var(--card); font-size: 0.78rem; cursor: pointer; font-weight: 500;
    font-family: var(--sans); color: var(--text);
  }}
  .filter-btn:hover {{ background: #f8f6f2; }}
  .filter-btn.active {{ background: #222; color: #fff; border-color: #222; }}
  .search-row {{
    display: flex; flex: 1; min-width: min(100%, 12rem); align-items: stretch;
    gap: 0.5rem; max-width: 100%;
  }}
  .search-input {{
    flex: 1; min-width: 0;
    padding: 0.55rem 1rem;
    border: 1px solid var(--border);
    border-radius: 999px;
    font-size: 0.85rem;
    background: var(--card);
    font-family: var(--sans);
  }}
  .search-input:focus {{ outline: none; border-color: #999; box-shadow: 0 0 0 3px rgba(0,0,0,.06); }}
  .search-submit {{
    flex-shrink: 0;
    padding: 0.55rem 1.15rem;
    border-radius: 999px;
    border: 1px solid #222;
    background: #222;
    color: #fff;
    font-size: 0.82rem;
    font-weight: 600;
    font-family: var(--sans);
    cursor: pointer;
  }}
  .search-submit:hover {{ background: #333; border-color: #333; }}
  .search-submit:focus-visible {{ outline: 2px solid var(--accent); outline-offset: 2px; }}
  .total-count {{ font-size: 0.8rem; color: var(--muted); width: 100%; margin-top: 0.35rem; }}
  .freq-section {{
    background: var(--card); border: 1px solid var(--border); border-radius: 12px;
    padding: 1.25rem 1.25rem 1rem; margin-bottom: 1.75rem;
    box-shadow: 0 2px 12px rgba(0,0,0,.04);
  }}
  .freq-section h2 {{
    font-size: 0.95rem; font-family: var(--sans); font-weight: 600; margin: 0 0 1rem; color: #333;
  }}
  .freq-row {{
    display: grid;
    grid-template-columns: 16ch minmax(0, 1fr) 2.5rem;
    align-items: center;
    gap: 0.75rem 1rem;
    margin-bottom: 0.65rem;
  }}
  .freq-label {{
    font-family: var(--sans); font-size: 0.75rem; font-weight: 500; color: #333;
    width: 16ch; max-width: 16ch;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    line-height: 1.3; letter-spacing: 0.01em;
  }}
  .freq-track {{ height: 6px; background: #ebe6de; border-radius: 4px; overflow: hidden; min-width: 0; }}
  .freq-fill {{ height: 100%; background: linear-gradient(90deg, #c94a4a, var(--accent)); border-radius: 4px; }}
  .freq-n {{ font-family: var(--sans); font-size: 0.72rem; color: var(--muted); text-align: right; font-variant-numeric: tabular-nums; }}
  .entries {{ margin-top: 0.5rem; }}
  .entry {{
    background: var(--card); border: 1px solid var(--border); border-radius: 12px;
    padding: 1.25rem 1.35rem; margin-bottom: 1rem;
    box-shadow: 0 2px 12px rgba(0,0,0,.04);
  }}
  .entry-code {{ font-family: var(--sans); font-size: 0.65rem; font-weight: 700; color: #aaa; letter-spacing: 0.1em; margin-bottom: 0.35rem; }}
  .entry-title {{ font-size: 1.1rem; font-weight: 700; margin-bottom: 0.2rem; font-family: var(--sans); }}
  .entry-meta {{ font-size: 0.8rem; color: var(--muted); font-family: var(--sans); margin-bottom: 0.65rem; }}
  blockquote {{ border-left: 3px solid var(--accent); margin: 0; padding: 0.25rem 0 0.25rem 1rem; }}
  blockquote p {{ font-size: 0.95rem; color: #6d2a2a; font-style: italic; line-height: 1.65; margin: 0; }}
  .attribution {{ font-family: var(--sans); font-size: 0.76rem; color: var(--muted); margin-top: 0.65rem; }}
  .attribution a {{ color: #5a6d8c; text-decoration: none; }}
  .attribution a:hover {{ text-decoration: underline; }}
  .kw-tags {{ display: flex; gap: 0.4rem; flex-wrap: wrap; margin-top: 0.85rem; }}
  .kw-tag {{
    font-family: var(--sans); font-size: 0.68rem; background: #f0ebe3;
    color: #444; padding: 0.25rem 0.55rem; border-radius: 6px; cursor: default;
    border: 1px solid #e5dfd4;
  }}
</style>
</head>
<body>
<div class="page">
  <h1>Scraped {len(results)} quotes.<br>Team, work &amp; collaboration angles.</h1>
  <p class="subtitle">
    Broad filter: quotes score on <strong>work / team / collaboration language</strong> (team, project, brand,
    feedback, clients, etc.) plus <strong>friction</strong> (bugs, confusion, delays, billing, support).
    Strong enterprise hits are still tagged in the keyword chips. Tune lists at the top of the scraper to narrow.
    Sources: Google Play, App Store, Reddit, Capterra, Trustpilot, Product Hunt, G2.
  </p>

  <div class="freq-section">
    <h2>Top tags across all {len(results)} quotes</h2>
"""
for kw, count in kw_freq:
    pct = int((count / kw_max) * 100)
    full_label = readable_tag(kw)
    short_label = freq_label_short(full_label, 16)
    kw_show = escape(short_label)
    kw_tip = escape(f"{full_label} — {kw}")
    html += f"""    <div class="freq-row">
      <span class="freq-label" title="{kw_tip}">{kw_show}</span>
      <div class="freq-track"><div class="freq-fill" style="width:{pct}%"></div></div>
      <span class="freq-n">{count}</span>
    </div>
"""

html += f"""  </div>

  <div class="sticky-tools" id="filterBar">
    <div class="sticky-tools-inner">
    <div class="filter-buttons">
    <button type="button" class="filter-btn active" data-src="all" onclick="setSource('all')">All</button>
"""
for src in sorted(set(r['source'] for r in results)):
    safe = src.replace(' ', '_').replace('/', '_').replace('[', '').replace(']', '')
    html += f'    <button type="button" class="filter-btn" data-src="{safe}" onclick="setSource(\'{safe}\')">{src}</button>\n'

html += f"""    </div>
    <form class="search-row" id="quoteSearchForm" action="#" method="get" role="search" aria-label="Search quotes">
      <input type="search" id="quoteSearch" class="search-input" name="q" placeholder="Search quotes, authors, sources…" autocomplete="off" aria-label="Search all quotes" />
      <button type="submit" class="search-submit" id="searchSubmitBtn">Search</button>
    </form>
    </div>
    <div class="total-count" id="totalCount">Showing {len(results)} quotes</div>
  </div>

  <div class="entries">
"""

search_texts = []
for i, r in enumerate(results):
    code = f"Q{str(i+1).zfill(3)}"
    src = r['source']
    color = src_color(src)
    safe_src = src.replace(' ', '_').replace('/', '_').replace('[', '').replace(']', '')
    rating_str = stars(r['rating']) if r['rating'] else ''
    date_str = r['date'] if r['date'] else ''
    author_str = r['author'] if r['author'] else ''
    
    best = best_sentence(r['text'], r['keywords'])
    blob = ' '.join(
        f"{code} {src} {author_str} {r['text']} {' '.join(r['keywords'])} "
        f"{' '.join(readable_tag(k) for k in r['keywords'])}".split()
    )
    search_texts.append(blob)
    tag_spans = []
    for k in r['keywords'][:8]:
        lab = escape(readable_tag(k))
        tip = escape(k)
        tag_spans.append(f'<span class="kw-tag" title="{tip}">{lab}</span>')
    tags = ''.join(tag_spans)

    attr_parts = []
    if author_str: attr_parts.append(author_str)
    if date_str: attr_parts.append(date_str)
    if rating_str: attr_parts.append(rating_str)
    attr_str = ' · '.join(attr_parts)

    html += f"""  <div class="entry" data-source="{safe_src}" data-idx="{i}">
    <div class="entry-code">{code}</div>
    <div class="entry-title" style="color:{color};">{src}</div>
    <div class="entry-meta">{attr_str}</div>
    <blockquote><p>{best}</p></blockquote>
    <div class="attribution">
      {'<a href="' + r['url'] + '" target="_blank">View source →</a>' if r['url'] else ''}
    </div>
    <div class="kw-tags">{tags}</div>
  </div>
"""

html += """  </div>

"""

_search_json = json.dumps(search_texts, ensure_ascii=False)
_search_json = _search_json.replace("<", "\\u003c")
html += f'<script type="application/json" id="search-data">{_search_json}</script>\n'

html += """
<script>
(function() {
  var SEARCH = [];
  try {
    var sd = document.getElementById('search-data');
    if (sd && sd.textContent) SEARCH = JSON.parse(sd.textContent);
  } catch (err) { console.error('search-data parse', err); }
  window.__filterSource = 'all';
  function applyFilters() {
    var src = window.__filterSource || 'all';
    var inp = document.getElementById('quoteSearch');
    var q = (inp && inp.value ? inp.value : '').trim().toLowerCase();
    var count = 0;
    document.querySelectorAll('.entry').forEach(function(e) {
      var okSrc = (src === 'all' || e.getAttribute('data-source') === src);
      var idx = parseInt(e.getAttribute('data-idx'), 10);
      if (isNaN(idx) || idx < 0 || idx >= SEARCH.length) {
        idx = -1;
      }
      var hay = (idx >= 0 && SEARCH[idx] != null ? String(SEARCH[idx]) : '').toLowerCase();
      var okQ = !q || hay.indexOf(q) !== -1;
      var show = okSrc && okQ;
      e.style.display = show ? 'block' : 'none';
      if (show) count++;
    });
    var tc = document.getElementById('totalCount');
    if (tc) tc.textContent = 'Showing ' + count + ' quotes';
  }
  window.applyFilters = applyFilters;
  window.setSource = function(src) {
    window.__filterSource = src;
    document.querySelectorAll('.filter-btn').forEach(function(b) {
      b.classList.toggle('active', b.getAttribute('data-src') === src);
    });
    applyFilters();
  };
  var form = document.getElementById('quoteSearchForm');
  var inp = document.getElementById('quoteSearch');
  if (form) {
    form.addEventListener('submit', function(e) {
      e.preventDefault();
      applyFilters();
    });
  }
  if (inp) {
    inp.addEventListener('input', applyFilters);
  }
  applyFilters();
})();
</script>
</div>
</body>
</html>"""

# Write HTML/JSON under ../site/ (Vercel Root Directory = site — no Python on deploy).
_scraper_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.dirname(_scraper_dir)
_out_dir = os.path.join(_repo_root, "site")
os.makedirs(_out_dir, exist_ok=True)
_out_index = os.path.join(_out_dir, "index.html")
_out_legacy = os.path.join(_out_dir, "canva_quotes.html")
for path in (_out_index, _out_legacy):
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)

_out_json = os.path.join(_out_dir, "canva_quotes.json")
with open(_out_json, "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2, default=str)

print(f"\n✅ Saved {len(results)} quotes → index.html (+ canva_quotes.html)")
print("✅ Raw JSON → canva_quotes.json")
if not os.environ.get("CANVA_NO_BROWSER") and not os.environ.get("CI"):
    print("\n🌐 Opening in browser...")
    webbrowser.open(f"file://{_out_index}")
