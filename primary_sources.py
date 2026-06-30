"""Primary source pulls. Free APIs that surface signal without burning Tavily or Exa credits.

Currently includes LegiScan for state legislation across all 50 states plus Congress.
RSS feeds and CourtListener live alongside in future expansions.
"""

import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()


LEGISCAN_API_KEY = os.getenv("LEGISCAN_API_KEY", "")
LEGISCAN_BASE_URL = "https://api.legiscan.com/"
COURTLISTENER_TOKEN = os.getenv("COURTLISTENER_API_TOKEN", "")

TIER_1_STATES = ["IL", "OK", "IA", "MD", "IN", "ME", "LA", "MN", "TN", "MS"]
TIER_2_STATES = ["CA", "NY", "NJ", "TX", "FL", "OH", "MA", "VA", "WA"]
TIER_3_STATES = [
    "AL", "AK", "AZ", "AR", "CO", "CT", "DE", "GA", "HI", "ID",
    "KS", "KY", "MI", "MO", "MT", "NE", "NV", "NH", "NM", "NC",
    "ND", "OR", "PA", "RI", "SC", "SD", "UT", "VT", "WV", "WI",
    "WY", "DC",
]

SWEEPSTAKES_KEYWORDS = [
    "sweepstakes",
    "sweeps",
    "social casino",
    "dual currency",
    "promotional sweepstakes",
]


_CACHE_DB = Path(__file__).parent / "cache.db"
_CACHE_INITIALIZED = False


def _ensure_cache():
    global _CACHE_INITIALIZED
    if _CACHE_INITIALIZED:
        return
    conn = sqlite3.connect(_CACHE_DB)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS legiscan_cache ("
        " utc_date TEXT NOT NULL,"
        " op TEXT NOT NULL,"
        " params TEXT NOT NULL,"
        " payload TEXT NOT NULL,"
        " created_at REAL NOT NULL,"
        " PRIMARY KEY (utc_date, op, params)"
        ")"
    )
    conn.commit()
    conn.close()
    _CACHE_INITIALIZED = True


def _utc_date() -> str:
    """Day key used for cache. Uses US Eastern (the brief's business timezone)."""
    from dates import us_date
    return us_date()


def _cache_get(op: str, params_key: str) -> dict | None:
    _ensure_cache()
    conn = sqlite3.connect(_CACHE_DB)
    row = conn.execute(
        "SELECT payload FROM legiscan_cache WHERE utc_date = ? AND op = ? AND params = ?",
        (_utc_date(), op, params_key),
    ).fetchone()
    conn.close()
    if not row:
        return None
    try:
        return json.loads(row[0])
    except Exception:
        return None


def _cache_set(op: str, params_key: str, payload: dict) -> None:
    _ensure_cache()
    conn = sqlite3.connect(_CACHE_DB)
    conn.execute(
        "INSERT OR REPLACE INTO legiscan_cache (utc_date, op, params, payload, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (_utc_date(), op, params_key, json.dumps(payload), time.time()),
    )
    conn.commit()
    conn.close()


def _ledger(calls: int = 1) -> None:
    try:
        from tools import _ledger_record
        _ledger_record("legiscan", calls)
    except Exception:
        pass


def _legiscan_call(op: str, **kwargs) -> dict:
    if not LEGISCAN_API_KEY:
        return {}
    params_key = json.dumps(kwargs, sort_keys=True)
    cached = _cache_get(op, params_key)
    if cached is not None:
        return cached

    params = {"key": LEGISCAN_API_KEY, "op": op, **kwargs}
    try:
        resp = httpx.get(LEGISCAN_BASE_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        _ledger(1)
        _cache_set(op, params_key, data)
        return data
    except Exception as exc:
        print(f"[legiscan] {op} {kwargs} failed, {exc}")
        return {}


def search_state(
    state: str,
    keyword: str,
    year: int | None = None,
    top_n: int = 3,
    min_relevance: int = 50,
) -> list[dict]:
    """Search LegiScan for a keyword in a state. Returns up to top_n results
    above min_relevance, in LegiScan native relevance order.
    """
    year = year or datetime.now().year
    data = _legiscan_call("search", state=state, query=keyword, year=year)
    if data.get("status") != "OK":
        return []
    section = data.get("searchresult", {})
    indexed: list[tuple[str, dict]] = []
    for k, v in section.items():
        if k == "summary" or not isinstance(v, dict):
            continue
        if not v.get("bill_id"):
            continue
        try:
            idx = int(k)
        except (TypeError, ValueError):
            continue
        indexed.append((idx, v))
    indexed.sort(key=lambda x: x[0])

    bills: list[dict] = []
    for _, v in indexed:
        rel = int(v.get("relevance", 0) or 0)
        if rel < min_relevance:
            continue
        bills.append({
            "bill_id": v.get("bill_id"),
            "bill_number": v.get("bill_number", ""),
            "title": v.get("title", ""),
            "state": v.get("state", state),
            "url": v.get("url", ""),
            "last_action": v.get("last_action", ""),
            "last_action_date": v.get("last_action_date", ""),
            "relevance": rel,
            "matched_keyword": keyword,
        })
        if len(bills) >= top_n:
            break
    return bills


def _normalize_bill_number(num: str) -> str:
    return "".join((num or "").upper().split())


_PROVISION_OFF_TOPIC_TOKENS = (
    "poker card room", "card room", "social card game", "social card games",
    "pinochle", "gin rummy", "bridge", "euchre", "cribbage", "dominoes",
    "checkers", "chess", "backgammon", "pool table", "darts",
    "horse race", "horse racing", "racetrack", "pari mutuel",
    "tribal compact", "tribal gaming compact",
    "raffle", "charitable bingo", "bingo hall",
)


_PROVISION_ON_TOPIC_TOKENS = (
    "sweepstakes", "sweeps", "social casino", "dual currency",
    "prediction market", "event contract", "online sweepstakes",
    "online gambling", "online gaming", "online casino", "internet gaming",
    "virtual currency", "gold coin", "sweeps coin",
    "payment processor", "money transmission",
    "ag enforcement", "attorney general",
)


def _provisions_look_sweepstakes_relevant(text: str) -> bool:
    """Strict post-grounding relevance check on key_provisions text.

    If the grounded scope only mentions brick-and-mortar / off-topic gambling
    terms with no online sweepstakes nexus, drop regardless of grounding's
    own is_sweepstakes_relevant verdict (which sometimes guesses true on
    anything gambling-adjacent).
    """
    t = (text or "").lower()
    if not t:
        return True
    has_on = any(tok in t for tok in _PROVISION_ON_TOPIC_TOKENS)
    has_off = any(tok in t for tok in _PROVISION_OFF_TOPIC_TOKENS)
    if has_off and not has_on:
        return False
    return True


def _enrich_bill_with_grounding(state: str, num: str, title: str) -> tuple[str, str]:
    """Live-ground authoritative facts for a bill via Gemini + Google Search.

    Returns (authoritative_summary, source_url). Empty strings if grounding
    fails. Returns ("OFF_TOPIC", "") if the grounded facts say the bill is
    not actually sweepstakes-relevant or the bill is dead with no enactment
    vehicle (no point putting noise in the scoreboard).
    """
    try:
        from grounding import format_bill_authoritative, ground_bill_facts
    except Exception as exc:
        print(f"[primary_source] grounding import failed, {exc}")
        return ("", "")

    facts = ground_bill_facts(state, _normalize_bill_number(num), title or "")
    if not facts:
        return ("", "")
    if not facts.get("is_sweepstakes_relevant", True):
        return ("OFF_TOPIC", "")
    if not _provisions_look_sweepstakes_relevant(facts.get("key_provisions", "")):
        return ("OFF_TOPIC", "")
    status = (facts.get("status") or "").lower()
    enacted_via = facts.get("enacted_via") or ""
    if status in {"dead", "vetoed"} and not enacted_via:
        return ("OFF_TOPIC", "")
    summary = format_bill_authoritative(facts)
    return (summary, facts.get("source_url", "") or "")


_OFF_TOPIC_TITLE_TOKENS = (
    "epa", "air quality", "water quality", "highway", "transportation",
    "transit", "vehicle", "school", "education", "healthcare", "medicaid",
    "medicare", "infrastructure", "agriculture", "agricultural", "farm",
    "pesticide", "veteran", "firearm", "weapon", "abortion", "election",
    "voting", "redistricting", "marijuana", "cannabis", "alcohol",
    "tobacco", "vape", "telecom", "broadband", "energy", "utility",
    "appropriation", "appropriations", "audit", "ethics commission",
    "pension", "retirement", "civil service",
    "poker card room", "card room", "card rooms", "social card game",
    "social card games", "pinochle", "gin rummy", "bridge", "euchre",
    "cribbage", "dominoes", "checkers", "chess", "backgammon",
    "pari mutuel", "horse racing", "racetrack", "horse race",
    "bingo hall", "charitable bingo", "raffle",
)


_ON_TOPIC_TITLE_TOKENS = (
    "sweepstakes", "sweeps", "social casino", "dual currency",
    "promotional sweepstakes", "internet gambling", "online gambling",
    "online casino", "online gaming", "internet gaming", "casino",
    "wager", "wagering", "gambling", "skill game", "lottery",
    "gaming control board", "gaming commission", "racketeering",
    "money transmission", "payment processor",
)


def _looks_sweepstakes_relevant(title: str) -> bool:
    """Filter that drops bills that match a keyword peripherally.

    Requires at least one explicit on topic token AND no obvious off topic
    token in the title. Money transmission stays in only if title also
    mentions gaming or gambling. Anything generic gets dropped.
    """
    t = (title or "").lower()
    if not t:
        return False
    if any(off in t for off in _OFF_TOPIC_TITLE_TOKENS):
        if any(on in t for on in ("sweepstakes", "sweeps", "social casino", "online gaming", "online gambling", "online casino", "internet gambling", "internet gaming")):
            return True
        return False
    return any(on in t for on in _ON_TOPIC_TITLE_TOKENS)


def pull_sweepstakes_bills(
    states: list[str] | None = None,
    keywords: list[str] | None = None,
    max_bills: int = 12,
) -> tuple[str, int]:
    """Pull sweepstakes related bills across the given states.

    Returns a tuple of (markdown summary, query_count).
    """
    if not LEGISCAN_API_KEY:
        return ("LegiScan disabled, no LEGISCAN_API_KEY set.", 0)

    states = states or (TIER_1_STATES + TIER_2_STATES)
    keywords = keywords or SWEEPSTAKES_KEYWORDS

    all_bills: list[dict] = []
    seen: set[int] = set()
    query_count = 0

    for state in states:
        for kw in keywords:
            bills = search_state(state, kw, top_n=3, min_relevance=60)
            query_count += 1
            for b in bills:
                bid = b.get("bill_id")
                if bid is None or bid in seen:
                    continue
                if not _looks_sweepstakes_relevant(b.get("title", "")):
                    continue
                seen.add(bid)
                all_bills.append(b)

    if not all_bills:
        return (
            "no qualifying legislative items today across LegiScan covered states",
            query_count,
        )

    all_bills.sort(
        key=lambda x: (x.get("relevance") or 0, x.get("last_action_date") or ""),
        reverse=True,
    )

    lines: list[str] = []
    for b in all_bills[:max_bills]:
        state = b.get("state", "")
        num = b.get("bill_number", "")
        title = (b.get("title") or "").strip()[:160]
        date = b.get("last_action_date", "")
        action = (b.get("last_action") or "").strip()[:90]
        url = b.get("url", "")
        authoritative, auth_url = _enrich_bill_with_grounding(state, num, title)
        if authoritative == "OFF_TOPIC":
            print(f"[primary_source] grounding dropped {state} {num} as off-topic")
            continue
        if authoritative:
            link_target = auth_url or url
            link_label = "Authoritative" if auth_url else "LegiScan"
            bullet = (
                f"- {state} {num}, {title}. AUTHORITATIVE: {authoritative} "
                f"LegiScan last action {date} ({action}). "
                f"[{link_label}]({link_target}) [LegiScan]({url})"
            )
        else:
            bullet = (
                f"- {state} {num}, {title}. Last action {date} ({action}). "
                f"[LegiScan]({url})"
            )
        lines.append(bullet)

    return ("\n".join(lines), query_count)


_RSS_FEEDS = [
    ("SBC Americas", "https://sbcamericas.com/feed/"),
    ("iGaming Business North America", "https://igamingbusiness.com/news/feed/"),
    ("CDC Gaming Reports", "https://cdcgaming.com/feed/"),
    ("Legal Sports Report", "https://www.legalsportsreport.com/feed/"),
    ("Gambling News", "https://gamblingnews.com/feed/"),
    ("Sports Handle", "https://sportshandle.com/feed/"),
    ("Casino.org News", "https://www.casino.org/news/feed/"),
    ("Bonus.com", "https://www.bonus.com/news/feed/"),
    ("PlayUSA", "https://www.playusa.com/feed/"),
    ("iGaming NEXT", "https://igamingnext.com/feed/"),
]

_RSS_SWEEP_TOKENS = (
    "sweepstakes", "sweeps", "social casino", "dual currency", "promotional",
    "stake.us", "chumba", "vgw", "mcluck", "pulsz", "high 5", "wow vegas",
    "funrize", "hello millions", "fortune coins", "modo", "fliff", "legendz",
    "sportzino", "crown coins", "mega bonanza", "global poker", "luckyland",
    "prediction market", "kalshi", "polymarket", "novig",
    "event contract", "geocomply", "xpoint", "sightline",
)


_RSS_HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 LuckyHandsIntel/0.2",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}


def _rss_relevant(text: str) -> bool:
    t = (text or "").lower()
    if not t:
        return False
    return any(s in t for s in _RSS_SWEEP_TOKENS)


def pull_rss_trade_press(max_items: int = 10, lookback_hours: int = 48) -> tuple[str, int]:
    """Pull recent sweepstakes related stories from trade press RSS feeds.

    Returns (markdown summary, feed_count).
    """
    try:
        import feedparser
    except ImportError:
        return ("RSS layer disabled, feedparser not installed.", 0)

    cutoff_ts = time.time() - lookback_hours * 3600
    items: list[dict] = []
    feeds_pulled = 0

    for source_name, url in _RSS_FEEDS:
        try:
            resp = httpx.get(
                url, headers=_RSS_HTTP_HEADERS, follow_redirects=True, timeout=15
            )
            if resp.status_code != 200:
                print(f"[rss] {source_name} returned {resp.status_code}")
                continue
            parsed = feedparser.parse(resp.text)
            if not parsed.entries:
                continue
            feeds_pulled += 1
        except Exception as exc:
            print(f"[rss] {source_name} failed, {exc}")
            continue

        for entry in parsed.entries[:50]:
            title = (entry.get("title") or "").strip()
            link = (entry.get("link") or "").strip()
            summary = (entry.get("summary") or entry.get("description") or "")[:300]
            published = entry.get("published_parsed") or entry.get("updated_parsed")
            ts = time.mktime(published) if published else 0
            if ts and ts < cutoff_ts:
                continue
            haystack = title + " " + summary
            if not _rss_relevant(haystack):
                continue
            if not link.startswith("http"):
                continue
            items.append({
                "source": source_name,
                "title": title,
                "url": link,
                "summary": summary,
                "ts": ts,
            })

    if not items:
        return ("no qualifying RSS items today across trade press feeds", feeds_pulled)

    items.sort(key=lambda x: x.get("ts", 0), reverse=True)

    lines: list[str] = []
    seen_urls: set[str] = set()
    for it in items:
        if it["url"] in seen_urls:
            continue
        seen_urls.add(it["url"])
        bullet = f"- {it['title']}. [{it['source']}]({it['url']})"
        lines.append(bullet)
        if len(lines) >= max_items:
            break

    return ("\n".join(lines), feeds_pulled)


def pull_federal_register(max_items: int = 6, lookback_days: int = 14) -> tuple[str, int]:
    """Pull recent Federal Register entries matching sweepstakes related terms.

    Returns (markdown summary, request_count).
    """
    request_count = 0
    queries = [
        "sweepstakes",
        "promotional sweepstakes",
        "online gambling sweepstakes",
    ]
    items: list[dict] = []
    seen: set[str] = set()

    for q in queries:
        params = {
            "conditions[term]": q,
            "conditions[publication_date][gte]": (
                datetime.now(tz=timezone.utc).date().isoformat()
            ),
            "order": "newest",
            "per_page": 10,
        }
        params["conditions[publication_date][gte]"] = (
            datetime.fromtimestamp(time.time() - lookback_days * 86400, tz=timezone.utc)
            .date()
            .isoformat()
        )
        try:
            resp = httpx.get(
                "https://www.federalregister.gov/api/v1/articles.json",
                params=params,
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
            request_count += 1
        except Exception as exc:
            print(f"[fedreg] query {q!r} failed, {exc}")
            continue

        for r in data.get("results", []):
            url = r.get("html_url", "")
            if not url or url in seen:
                continue
            seen.add(url)
            items.append({
                "title": r.get("title", ""),
                "agency_names": r.get("agency_names") or [],
                "url": url,
                "type": r.get("type", ""),
                "publication_date": r.get("publication_date", ""),
            })

    if not items:
        return ("no qualifying Federal Register items today", request_count)

    items.sort(key=lambda x: x.get("publication_date", ""), reverse=True)

    lines: list[str] = []
    for it in items[:max_items]:
        title = (it.get("title") or "").strip()[:160]
        agencies = ", ".join(it.get("agency_names") or [])
        date = it.get("publication_date", "")
        rtype = it.get("type", "")
        url = it.get("url", "")
        lines.append(
            f"- {date} {rtype}, {title} (agency: {agencies}). [Federal Register]({url})"
        )

    return ("\n".join(lines), request_count)


_COURTLISTENER_QUERIES = [
    "sweepstakes",
    "VGW Chumba",
    "Stake.us",
    "social casino dual currency",
    "online gambling sweepstakes",
]


_COURTLISTENER_RELEVANCE_TOKENS = (
    "sweepstakes", "sweeps", "social casino", "vgw", "virtual gaming worlds",
    "chumba", "luckyland", "global poker", "stake.us", "mcluck", "pulsz",
    "high 5", "wow vegas", "funrize", "hello millions", "fortune coins",
    "modo", "fliff", "legendz", "sportzino", "crown coins", "mega bonanza",
    "dual currency", "promotional sweepstakes", "internet sweepstakes",
    "kalshi", "polymarket",
)


def _courtlistener_relevant(case_name: str, snippet: str) -> bool:
    hay = f"{case_name} {snippet}".lower()
    return any(t in hay for t in _COURTLISTENER_RELEVANCE_TOKENS)


def pull_courtlistener(max_items: int = 6, lookback_days: int = 14) -> tuple[str, int]:
    """Pull recent court filings matching sweepstakes related queries via CourtListener REST API.

    Returns (markdown summary, query_count).
    """
    if not COURTLISTENER_TOKEN:
        return ("CourtListener disabled, no COURTLISTENER_API_TOKEN set.", 0)

    cutoff_date = (
        datetime.fromtimestamp(time.time() - lookback_days * 86400, tz=timezone.utc)
        .date()
        .isoformat()
    )

    items: list[dict] = []
    seen: set[str] = set()
    query_count = 0

    for q in _COURTLISTENER_QUERIES:
        try:
            resp = httpx.get(
                "https://www.courtlistener.com/api/rest/v4/search/",
                params={
                    "q": q,
                    "type": "o",
                    "order_by": "dateFiled desc",
                    "filed_after": cutoff_date,
                },
                headers={"Authorization": f"Token {COURTLISTENER_TOKEN}"},
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
            query_count += 1
            try:
                from tools import _ledger_record
                _ledger_record("courtlistener", 1)
            except Exception:
                pass
        except Exception as exc:
            print(f"[courtlistener] query {q!r} failed, {exc}")
            continue

        for r in data.get("results", []):
            cluster_id = r.get("cluster_id") or r.get("id")
            case_name = r.get("caseName", "")
            snippet = (r.get("snippet") or "")[:240]
            if not _courtlistener_relevant(case_name, snippet):
                continue
            key = f"{cluster_id}:{case_name}"
            if key in seen:
                continue
            seen.add(key)

            absolute_url = r.get("absolute_url") or ""
            url = (
                f"https://www.courtlistener.com{absolute_url}"
                if absolute_url and not absolute_url.startswith("http")
                else absolute_url
            )
            items.append({
                "caseName": case_name,
                "court": r.get("court", "") or r.get("court_id", ""),
                "dateFiled": r.get("dateFiled", "") or r.get("date_filed", ""),
                "url": url,
                "snippet": snippet,
                "matched_query": q,
            })

    if not items:
        return ("no qualifying CourtListener filings today", query_count)

    items.sort(key=lambda x: x.get("dateFiled", ""), reverse=True)

    lines: list[str] = []
    for it in items[:max_items]:
        name = (it.get("caseName") or "").strip()[:160]
        date = it.get("dateFiled", "")
        court = it.get("court", "")[:60]
        url = it.get("url", "")
        lines.append(
            f"- {date}, {name} ({court}). [CourtListener]({url})"
        )

    return ("\n".join(lines), query_count)


_REDDIT_SUBS = [
    "sweepstakescasino",
    "socialcasino",
]


_OPERATOR_APP_NAMES = [
    "Chumba Casino",
    "LuckyLand Slots",
    "Global Poker",
    "Pulsz Social Casino",
    "Stake.us",
    "McLuck",
    "WOW Vegas",
    "Funrize Social Casino",
    "High 5 Casino",
    "Fortune Coins Casino",
    "Hello Millions",
    "Crown Coins Casino",
    "Modo.us Sweeps",
]


def pull_reddit_sweeps(max_items: int = 12) -> tuple[str, int]:
    """Top posts of the week from sweepstakes related subreddits.

    Returns (markdown summary, subreddit count).
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        "Accept": "application/json,text/html",
        "Accept-Language": "en-US,en;q=0.9",
    }
    items: list[dict] = []
    sub_count = 0
    for sub in _REDDIT_SUBS:
        data = None
        for host in ("old.reddit.com", "www.reddit.com"):
            try:
                resp = httpx.get(
                    f"https://{host}/r/{sub}/top.json",
                    params={"t": "week", "limit": 15},
                    headers=headers,
                    follow_redirects=True,
                    timeout=15,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    sub_count += 1
                    break
                print(f"[reddit] {host}/r/{sub} returned {resp.status_code}")
            except Exception as exc:
                print(f"[reddit] {host}/r/{sub} failed, {exc}")
        if data is None:
            continue

        for child in data.get("data", {}).get("children", []):
            d = child.get("data", {})
            title = (d.get("title") or "").strip()
            if not title:
                continue
            score = d.get("score", 0)
            num_comments = d.get("num_comments", 0)
            permalink = d.get("permalink", "")
            url = f"https://www.reddit.com{permalink}" if permalink else d.get("url", "")
            if not url.startswith("http"):
                continue
            items.append({
                "subreddit": sub,
                "title": title,
                "score": score,
                "comments": num_comments,
                "url": url,
            })

    if not items:
        return ("no qualifying Reddit posts this week", sub_count)

    items.sort(key=lambda x: (x.get("score") or 0) + (x.get("comments") or 0) * 2, reverse=True)

    lines: list[str] = []
    for it in items[:max_items]:
        title = it["title"][:160]
        sub = it["subreddit"]
        score = it.get("score", 0)
        comments = it.get("comments", 0)
        url = it["url"]
        lines.append(
            f"- r/{sub}, {title} ({score} upvotes, {comments} comments). [Reddit]({url})"
        )

    return ("\n".join(lines), sub_count)


def pull_app_store_signals() -> tuple[str, int]:
    """iTunes Search endpoint for each named operator iOS app.
    Returns rating and review counts. Useful as weekly sentiment proxy.
    """
    items: list[dict] = []
    request_count = 0
    for name in _OPERATOR_APP_NAMES:
        try:
            resp = httpx.get(
                "https://itunes.apple.com/search",
                params={
                    "term": name,
                    "entity": "software",
                    "country": "us",
                    "limit": 3,
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            request_count += 1
        except Exception as exc:
            print(f"[itunes] {name} failed, {exc}")
            continue

        results = data.get("results", [])
        if not results:
            continue
        best = None
        name_lower = name.lower()
        for r in results:
            track = (r.get("trackName") or "").lower()
            seller = (r.get("sellerName") or "").lower()
            if name_lower.split()[0] in track or name_lower.split()[0] in seller:
                best = r
                break
        if best is None:
            best = results[0]
        items.append({
            "operator": name,
            "track_name": best.get("trackName", ""),
            "rating_avg": best.get("averageUserRating"),
            "rating_count": best.get("userRatingCount"),
            "version": best.get("version"),
            "release": (best.get("currentVersionReleaseDate") or "")[:10],
            "url": best.get("trackViewUrl", ""),
        })

    if not items:
        return ("no qualifying App Store signals this week", request_count)

    items.sort(key=lambda x: (x.get("rating_count") or 0), reverse=True)

    lines: list[str] = []
    for it in items:
        op = it["operator"]
        track = it.get("track_name", "")
        ravg = it.get("rating_avg")
        rcount = it.get("rating_count") or 0
        ver = it.get("version") or "?"
        rel = it.get("release") or "?"
        url = it.get("url", "")
        if not url or not isinstance(ravg, (int, float)) or rcount == 0:
            continue
        avg_str = f"{ravg:.2f}"
        lines.append(
            f"- {op} ({track}), rating {avg_str} across {rcount} reviews, version {ver} released {rel}. [App Store]({url})"
        )

    if not lines:
        return ("no qualifying App Store signals this week", request_count)
    return ("\n".join(lines), request_count)


def _is_friday_utc() -> bool:
    return datetime.now(tz=timezone.utc).weekday() == 4


def primary_source_pull_callback(callback_context):
    """ADK before_agent_callback that populates session state with primary source findings.

    Writes legiscan_findings, rss_findings, and federal_register_findings into state.
    Runs before the three research subagents.
    """
    state = getattr(callback_context, "state", None)
    if state is None:
        return None

    write = lambda k, v: state.__setitem__(k, v) if not (hasattr(state, "get") and state.get(k)) else None

    if not (hasattr(state, "get") and state.get("legiscan_findings")):
        print("[primary_source] LegiScan pull starting")
        started = time.time()
        summary, count = pull_sweepstakes_bills()
        print(f"[primary_source] LegiScan done in {time.time()-started:.1f}s, {count} queries")
        try:
            state["legiscan_findings"] = summary
        except Exception as exc:
            print(f"[primary_source] legiscan write failed, {exc}")

    if not (hasattr(state, "get") and state.get("rss_findings")):
        print("[primary_source] RSS trade press pull starting")
        started = time.time()
        summary, count = pull_rss_trade_press()
        print(f"[primary_source] RSS done in {time.time()-started:.1f}s, {count} feeds")
        try:
            state["rss_findings"] = summary
        except Exception as exc:
            print(f"[primary_source] rss write failed, {exc}")

    if not (hasattr(state, "get") and state.get("federal_register_findings")):
        print("[primary_source] Federal Register pull starting")
        started = time.time()
        summary, count = pull_federal_register()
        print(f"[primary_source] Federal Register done in {time.time()-started:.1f}s, {count} queries")
        try:
            state["federal_register_findings"] = summary
        except Exception as exc:
            print(f"[primary_source] fedreg write failed, {exc}")

    if not (hasattr(state, "get") and state.get("courtlistener_findings")):
        print("[primary_source] CourtListener pull starting")
        started = time.time()
        summary, count = pull_courtlistener()
        print(f"[primary_source] CourtListener done in {time.time()-started:.1f}s, {count} queries")
        try:
            state["courtlistener_findings"] = summary
        except Exception as exc:
            print(f"[primary_source] courtlistener write failed, {exc}")

    weekly_force = os.getenv("INTEL_DAILY_FORCE_SENTIMENT", "").strip() in {"1", "true", "True", "yes"}
    if (_is_friday_utc() or weekly_force) and not (hasattr(state, "get") and state.get("sentiment_findings")):
        print("[primary_source] Reddit + App Store sentiment pull starting (Friday or forced)")
        started = time.time()
        reddit_sum, reddit_subs = pull_reddit_sweeps()
        app_sum, app_count = pull_app_store_signals()
        combined = (
            "Reddit weekly top posts.\n" + reddit_sum +
            "\n\nApp Store rating snapshot.\n" + app_sum
        )
        print(f"[primary_source] sentiment done in {time.time()-started:.1f}s, "
              f"{reddit_subs} subreddits, {app_count} apps")
        try:
            state["sentiment_findings"] = combined
        except Exception as exc:
            print(f"[primary_source] sentiment write failed, {exc}")

    return None
