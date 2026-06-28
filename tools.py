import json
import os
import random
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()


_CACHE_DB = Path(__file__).parent / "cache.db"
_CACHE_DB_INITIALIZED = False


def _ensure_cache():
    global _CACHE_DB_INITIALIZED
    if _CACHE_DB_INITIALIZED:
        return
    conn = sqlite3.connect(_CACHE_DB)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS search_cache ("
        " utc_date TEXT NOT NULL,"
        " query TEXT NOT NULL,"
        " backend TEXT NOT NULL,"
        " payload TEXT NOT NULL,"
        " created_at REAL NOT NULL,"
        " PRIMARY KEY (utc_date, query)"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS fetch_cache ("
        " utc_date TEXT NOT NULL,"
        " url TEXT NOT NULL,"
        " payload TEXT NOT NULL,"
        " created_at REAL NOT NULL,"
        " PRIMARY KEY (utc_date, url)"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS budget_ledger ("
        " utc_month TEXT NOT NULL,"
        " backend TEXT NOT NULL,"
        " calls INTEGER NOT NULL DEFAULT 0,"
        " updated_at REAL NOT NULL,"
        " PRIMARY KEY (utc_month, backend)"
        ")"
    )
    conn.commit()
    conn.close()
    _CACHE_DB_INITIALIZED = True


_BUDGET_CAPS = {
    "tavily": int(os.getenv("TAVILY_MONTHLY_CAP", "1000")),
    "exa": int(os.getenv("EXA_MONTHLY_CAP", "1500")),
    "legiscan": int(os.getenv("LEGISCAN_MONTHLY_CAP", "30000")),
    "courtlistener": int(os.getenv("COURTLISTENER_DAILY_CAP", "125")),
}


def _utc_month() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m")


def _ledger_record(backend: str, calls: int = 1) -> None:
    try:
        _ensure_cache()
        conn = sqlite3.connect(_CACHE_DB)
        month = _utc_month()
        conn.execute(
            "INSERT INTO budget_ledger (utc_month, backend, calls, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(utc_month, backend) DO UPDATE SET calls = calls + excluded.calls, updated_at = excluded.updated_at",
            (month, backend, calls, time.time()),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        print(f"[ledger] record failed, {exc}")


def get_ledger() -> dict:
    _ensure_cache()
    conn = sqlite3.connect(_CACHE_DB)
    month = _utc_month()
    rows = conn.execute(
        "SELECT backend, calls FROM budget_ledger WHERE utc_month = ?",
        (month,),
    ).fetchall()
    conn.close()
    out: dict[str, dict] = {}
    for backend, calls in rows:
        cap = _BUDGET_CAPS.get(backend, 0)
        pct = round(100 * calls / cap, 1) if cap else 0.0
        out[backend] = {"calls": calls, "cap": cap, "pct": pct}
    return out


def _budget_exceeded(backend: str, threshold: float = 0.8) -> bool:
    cap = _BUDGET_CAPS.get(backend, 0)
    if not cap:
        return False
    _ensure_cache()
    conn = sqlite3.connect(_CACHE_DB)
    row = conn.execute(
        "SELECT calls FROM budget_ledger WHERE utc_month = ? AND backend = ?",
        (_utc_month(), backend),
    ).fetchone()
    conn.close()
    if not row:
        return False
    return row[0] >= cap * threshold


def _utc_date() -> str:
    """Day key used for caches. Uses US Eastern (the brief's business timezone)."""
    from dates import us_date
    return us_date()


def _cache_get_search(query: str) -> str | None:
    _ensure_cache()
    conn = sqlite3.connect(_CACHE_DB)
    row = conn.execute(
        "SELECT payload FROM search_cache WHERE utc_date = ? AND query = ?",
        (_utc_date(), query),
    ).fetchone()
    conn.close()
    return row[0] if row else None


def _cache_set_search(query: str, backend: str, payload: str) -> None:
    _ensure_cache()
    conn = sqlite3.connect(_CACHE_DB)
    conn.execute(
        "INSERT OR REPLACE INTO search_cache (utc_date, query, backend, payload, created_at) VALUES (?, ?, ?, ?, ?)",
        (_utc_date(), query, backend, payload, time.time()),
    )
    conn.commit()
    conn.close()


def _cache_get_fetch(url: str) -> str | None:
    _ensure_cache()
    conn = sqlite3.connect(_CACHE_DB)
    row = conn.execute(
        "SELECT payload FROM fetch_cache WHERE utc_date = ? AND url = ?",
        (_utc_date(), url),
    ).fetchone()
    conn.close()
    return row[0] if row else None


def _cache_set_fetch(url: str, payload: str) -> None:
    _ensure_cache()
    conn = sqlite3.connect(_CACHE_DB)
    conn.execute(
        "INSERT OR REPLACE INTO fetch_cache (utc_date, url, payload, created_at) VALUES (?, ?, ?, ?)",
        (_utc_date(), url, payload, time.time()),
    )
    conn.commit()
    conn.close()


_DDG_LITE_URL = "https://lite.duckduckgo.com/lite/"
_DDG_HTML_URL = "https://html.duckduckgo.com/html/"

_USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0 Safari/537.36",
]

_MIN_INTERVAL_S = float(os.getenv("WEB_SEARCH_MIN_INTERVAL_S", "8"))
_TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
_EXA_API_KEY = os.getenv("EXA_API_KEY", "")
_JINA_READER_URL = "https://r.jina.ai/"

_last_call_ts = 0.0
_search_cache: dict[str, str] = {}


def _headers():
    return {
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }


def _throttle():
    global _last_call_ts
    now = time.time()
    elapsed = now - _last_call_ts
    if elapsed < _MIN_INTERVAL_S:
        wait = _MIN_INTERVAL_S - elapsed
        print(f"[web_search] throttling, sleeping {wait:.1f}s")
        time.sleep(wait)
    _last_call_ts = time.time()


def _resolve_ddg(href: str) -> str:
    if href.startswith("//"):
        href = "https:" + href
    if "duckduckgo.com/l/" in href or href.startswith("/l/"):
        m = re.search(r"uddg=([^&]+)", href)
        if m:
            return unquote(m.group(1))
    if not href.startswith("http"):
        href = "https://" + href.lstrip("/")
    return href


def _parse_lite(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    trs = soup.find_all("tr")
    out: list[dict] = []
    i = 0
    while i < len(trs):
        link = trs[i].find("a")
        if not link:
            i += 1
            continue
        title = link.get_text(" ", strip=True)
        title = re.sub(r"^\d+\.\s*", "", title)
        if title.endswith("Ad"):
            i += 3
            continue
        href = _resolve_ddg(link.get("href", ""))
        snippet = trs[i + 1].get_text(" ", strip=True) if i + 1 < len(trs) else ""
        url_display = trs[i + 2].get_text(" ", strip=True) if i + 2 < len(trs) else ""
        if not href.startswith("http") and url_display:
            href = "https://" + url_display.split()[0]
        if title and href.startswith("http"):
            out.append({"title": title, "url": href, "snippet": snippet})
        i += 3
    return out


def _parse_html(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[dict] = []
    for r in soup.select(".result")[:10]:
        title_el = r.select_one(".result__title a")
        snippet_el = r.select_one(".result__snippet")
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        href = _resolve_ddg(title_el.get("href", ""))
        snippet = snippet_el.get_text(" ", strip=True) if snippet_el else ""
        if href.startswith("http"):
            out.append({"title": title, "url": href, "snippet": snippet})
    return out


def _tavily_search(query: str, topic: str = "news", days: int = 2) -> list[dict]:
    if not _TAVILY_API_KEY:
        return []
    try:
        payload = {
            "api_key": _TAVILY_API_KEY,
            "query": query,
            "max_results": 10,
            "search_depth": "basic",
            "country": "united states",
        }
        if topic == "news":
            payload["topic"] = "news"
            payload["days"] = days
        else:
            payload["topic"] = "general"
        resp = httpx.post(
            "https://api.tavily.com/search",
            json=payload,
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        _ledger_record("tavily", 1)
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("content", ""),
            }
            for r in data.get("results", [])
            if r.get("url", "").startswith("http")
        ]
    except Exception as exc:
        print(f"[web_search] Tavily failed, {exc}")
        return []


_exa_last_call_ts = 0.0
_EXA_MIN_INTERVAL_S = 1.1


def _exa_throttle():
    global _exa_last_call_ts
    now = time.time()
    elapsed = now - _exa_last_call_ts
    if elapsed < _EXA_MIN_INTERVAL_S:
        wait = _EXA_MIN_INTERVAL_S - elapsed
        time.sleep(wait)
    _exa_last_call_ts = time.time()


def _exa_search(query: str) -> list[dict]:
    if not _EXA_API_KEY:
        return []
    try:
        _exa_throttle()
        resp = httpx.post(
            "https://api.exa.ai/search",
            headers={
                "x-api-key": _EXA_API_KEY,
                "Content-Type": "application/json",
            },
            json={
                "query": query,
                "type": "auto",
                "numResults": 10,
                "contents": {"highlights": True},
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        _ledger_record("exa", 1)
        out: list[dict] = []
        for r in data.get("results", []):
            url = r.get("url", "")
            if not url.startswith("http"):
                continue
            highlights = r.get("highlights") or []
            snippet = " ... ".join(h.strip() for h in highlights if h)[:600]
            if not snippet:
                snippet = (r.get("text") or "")[:600]
            out.append({
                "title": r.get("title", "") or url,
                "url": url,
                "snippet": snippet,
            })
        return out
    except Exception as exc:
        print(f"[web_search] Exa failed, {exc}")
        return []


def _ddg_search(query: str) -> list[dict]:
    last_status = None
    for endpoint, parser in [(_DDG_LITE_URL, _parse_lite), (_DDG_HTML_URL, _parse_html)]:
        try:
            resp = httpx.post(
                endpoint,
                data={"q": query, "kl": "us-en"},
                headers=_headers(),
                follow_redirects=True,
                timeout=20.0,
            )
            last_status = resp.status_code
            if resp.status_code == 202:
                print(f"[web_search] {endpoint} returned 202 anomaly")
                continue
            resp.raise_for_status()
            results = parser(resp.text)
            if results:
                return results
            print(f"[web_search] {endpoint} parsed 0 results")
        except Exception as exc:
            print(f"[web_search] {endpoint} failed, {exc}")
            continue
    print(f"[web_search] all DDG endpoints exhausted, last status {last_status}")
    return []


_FRESH_TOKENS = (
    "cease and desist", "press release", "filed", "signed", "veto", "introduces",
    "this week", "today", "yesterday", "breaking", "update",
    "ruling", "lawsuit", "enforcement", "advisory", "letter",
    "ag ", "attorney general", "fincen", "ftc", "irs", "cftc",
    "gaming board", "gaming commission", "lottery board",
)

_SEMANTIC_TOKENS = (
    "similar to", "compare", "emerging", "market size", "ggr",
    "trend", "analysis", "landscape", "overview", "ecosystem",
    "ranking", "comparison",
)


def _pick_backend(query: str, intent: str | None = None) -> str:
    if intent in ("news", "entity", "fresh"):
        return "tavily"
    if intent in ("semantic", "discovery", "concept"):
        return "exa"
    q = query.lower()
    if any(t in q for t in _FRESH_TOKENS):
        return "tavily"
    if any(t in q for t in _SEMANTIC_TOKENS):
        return "exa"
    return "tavily"


def _try_tavily(query: str) -> str | None:
    if not _TAVILY_API_KEY:
        return None
    results = _tavily_search(query)
    if results:
        return _format(results, query, "Tavily")
    return None


def _try_exa(query: str) -> str | None:
    if not _EXA_API_KEY:
        return None
    results = _exa_search(query)
    if results:
        return _format(results, query, "Exa")
    return None


def _try_ddg(query: str) -> str | None:
    _throttle()
    results = _ddg_search(query)
    if results:
        return _format(results, query, "DDG")
    return None


def _route(query: str, intent: str | None = None) -> str:
    print(f"[web_search] query, {query!r}, intent={intent or 'auto'}")

    if query in _search_cache:
        print(f"[web_search] memory cache hit for {query!r}")
        return _search_cache[query]

    persisted = _cache_get_search(query)
    if persisted:
        print(f"[web_search] disk cache hit for {query!r}")
        _search_cache[query] = persisted
        return persisted

    primary = _pick_backend(query, intent)
    backend_log = f"primary={primary}"

    if primary == "tavily":
        text = _try_tavily(query)
        if text:
            _search_cache[query] = text
            _cache_set_search(query, "tavily", text)
            return text
        text = _try_exa(query)
        if text:
            print(f"[web_search] {backend_log} miss, exa secondary returned results")
            _search_cache[query] = text
            _cache_set_search(query, "exa", text)
            return text
    else:
        text = _try_exa(query)
        if text:
            _search_cache[query] = text
            _cache_set_search(query, "exa", text)
            return text
        text = _try_tavily(query)
        if text:
            print(f"[web_search] {backend_log} miss, tavily secondary returned results")
            _search_cache[query] = text
            _cache_set_search(query, "tavily", text)
            return text

    text = _try_ddg(query)
    if text:
        print(f"[web_search] both primary backends empty, ddg fallback returned results")
        _search_cache[query] = text
        _cache_set_search(query, "ddg", text)
        return text

    return "No results found."


def web_search(query: str) -> str:
    """Search the public web. Auto routes to Tavily for news / entity queries,
    Exa for semantic / discovery queries, DDG fallback. Use this for general queries.

    Args:
        query: A natural language search query.

    Returns:
        A markdown formatted list of up to 10 results, or "No results found.".
    """
    return _route(query, intent=None)


def web_search_news(query: str) -> str:
    """Search for fresh news with Tavily. Best for state AG actions, press releases,
    court filings, cease and desist letters, and any event happening this week.

    Args:
        query: A natural language search query about recent news.

    Returns:
        A markdown formatted list of up to 10 results, or "No results found.".
    """
    return _route(query, intent="news")


def web_search_semantic(query: str) -> str:
    """Search with Exa neural semantic ranking. Best for named entity polling
    (named operators, named vendors), emerging trends, market sizing, and queries
    where keyword match is weaker than concept match.

    Args:
        query: A natural language search query.

    Returns:
        A markdown formatted list of up to 10 results, or "No results found.".
    """
    return _route(query, intent="semantic")


def _format(results: list[dict], query: str, backend: str) -> str:
    print(f"[web_search] {backend} returned {len(results)} results for {query!r}")
    rows = [
        f"- {r['title']}\n  URL, {r['url']}\n  {r['snippet']}"
        for r in results[:10]
    ]
    return "\n\n".join(rows)


def _jina_reader_fetch(url: str) -> str | None:
    try:
        resp = httpx.get(
            f"{_JINA_READER_URL}{url}",
            headers={
                "Accept": "text/plain",
                "X-Return-Format": "markdown",
            },
            timeout=20.0,
            follow_redirects=True,
        )
        if resp.status_code == 429:
            print("[fetch_url] Jina Reader returned 429 (rate limit), falling back")
            return None
        resp.raise_for_status()
        text = resp.text.strip()
        if text and len(text) > 100:
            print(f"[fetch_url] Jina Reader returned {len(text)} chars")
            return text[:6000]
        return None
    except Exception as exc:
        print(f"[fetch_url] Jina Reader failed, {exc}, falling back")
        return None


def fetch_url(url: str) -> str:
    """Fetch the readable text content of a public web page.

    Use this after web_search when you want to read the actual article
    body for an item, not just the snippet. Useful for verifying claims
    or pulling specific details like dates, dollar amounts, or quotes.

    Backed by Jina Reader (free, no key) which returns clean markdown of any
    URL, falling back to direct httpx plus BeautifulSoup if Jina is rate
    limited.

    Args:
        url: A full http or https URL.

    Returns:
        Plain text up to 6000 chars, or an error message if both backends fail.
    """
    print(f"[fetch_url] {url!r}")

    cached = _cache_get_fetch(url)
    if cached:
        print(f"[fetch_url] disk cache hit, {len(cached)} chars")
        return cached

    text = _jina_reader_fetch(url)
    if text:
        _cache_set_fetch(url, text)
        return text

    try:
        resp = httpx.get(url, headers=_headers(), follow_redirects=True, timeout=20.0)
        resp.raise_for_status()
    except Exception as exc:
        print(f"[fetch_url] direct fetch FAILED, {exc}")
        return f"Fetch failed, {exc}"

    content_type = resp.headers.get("content-type", "").lower()
    if "xml" in content_type or "rss" in content_type:
        return f"This URL returns XML or RSS feed, not an article. Use web_search to find the readable article URL instead."

    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "aside", "iframe", "form", "header", "noscript"]):
        tag.decompose()
    container = (
        soup.select_one("article")
        or soup.select_one("main")
        or soup.select_one("[role=main]")
        or soup.body
    )
    if not container:
        print(f"[fetch_url] empty container for {url!r}")
        return "Empty page."
    paragraphs = container.find_all(["p", "h1", "h2", "h3", "li"])
    text = "\n".join(
        p.get_text(" ", strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 30
    )
    if not text:
        print(f"[fetch_url] no readable text for {url!r}")
        return "No readable content found."
    truncated = text[:6000]
    _cache_set_fetch(url, truncated)
    print(f"[fetch_url] direct fetch returned {len(truncated)} chars (cached)")
    return truncated
