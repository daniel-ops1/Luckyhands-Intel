import os
import random
import re
import time
from urllib.parse import unquote

import httpx
from bs4 import BeautifulSoup


_DDG_LITE_URL = "https://lite.duckduckgo.com/lite/"
_DDG_HTML_URL = "https://html.duckduckgo.com/html/"
_BRAVE_API_URL = "https://api.search.brave.com/res/v1/web/search"

_USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0 Safari/537.36",
]

_MIN_INTERVAL_S = float(os.getenv("WEB_SEARCH_MIN_INTERVAL_S", "8"))
_BRAVE_API_KEY = os.getenv("BRAVE_API_KEY", "")
_TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

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


def _brave_search(query: str) -> list[dict]:
    if not _BRAVE_API_KEY:
        return []
    try:
        resp = httpx.get(
            _BRAVE_API_URL,
            params={"q": query, "count": 10},
            headers={
                "X-Subscription-Token": _BRAVE_API_KEY,
                "Accept": "application/json",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("web", {}).get("results", [])
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("description", ""),
            }
            for r in results
            if r.get("url", "").startswith("http")
        ]
    except Exception as exc:
        print(f"[web_search] Brave failed, {exc}")
        return []


def _tavily_search(query: str) -> list[dict]:
    if not _TAVILY_API_KEY:
        return []
    try:
        resp = httpx.post(
            "https://api.tavily.com/search",
            json={
                "api_key": _TAVILY_API_KEY,
                "query": query,
                "max_results": 10,
            },
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
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


def web_search(query: str) -> str:
    """Search the public web for current information.

    Use this when you need recent news, regulatory actions, court rulings,
    operator announcements, or any current event information.

    Backend priority is Brave Search if BRAVE_API_KEY is set, then Tavily if
    TAVILY_API_KEY is set, then DuckDuckGo Lite. A throttle prevents rapid
    fire calls that would trigger anti scraping.

    Args:
        query: A natural language search query, like
            "California sweepstakes casino bill 2026" or
            "Illinois Gaming Board cease and desist sweepstakes".

    Returns:
        A markdown formatted list of up to 10 results. Each result has a
        title, URL, and short snippet. Returns "No results found." if all
        backends fail.
    """
    print(f"[web_search] query, {query!r}")

    if query in _search_cache:
        print(f"[web_search] cache hit for {query!r}")
        return _search_cache[query]

    if _BRAVE_API_KEY:
        results = _brave_search(query)
        if results:
            text = _format(results, query, "Brave")
            _search_cache[query] = text
            return text

    if _TAVILY_API_KEY:
        results = _tavily_search(query)
        if results:
            text = _format(results, query, "Tavily")
            _search_cache[query] = text
            return text

    _throttle()
    results = _ddg_search(query)
    if results:
        text = _format(results, query, "DDG")
        _search_cache[query] = text
        return text

    return "No results found."


def _format(results: list[dict], query: str, backend: str) -> str:
    print(f"[web_search] {backend} returned {len(results)} results for {query!r}")
    rows = [
        f"- {r['title']}\n  URL, {r['url']}\n  {r['snippet']}"
        for r in results[:10]
    ]
    return "\n\n".join(rows)


def fetch_url(url: str) -> str:
    """Fetch the readable text content of a public web page.

    Use this after web_search when you want to read the actual article
    body for an item, not just the snippet. Useful for verifying claims
    or pulling specific details like dates, dollar amounts, or quotes.

    Args:
        url: A full http or https URL.

    Returns:
        Plain text, up to 6000 characters of the article body. Strips
        navigation, ads, footers, and scripts. Returns an error message
        string if the fetch fails.
    """
    print(f"[fetch_url] {url!r}")
    try:
        resp = httpx.get(url, headers=_headers(), follow_redirects=True, timeout=20.0)
        resp.raise_for_status()
    except Exception as exc:
        print(f"[fetch_url] FAILED, {exc}")
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
    print(f"[fetch_url] returned {len(text)} chars from {url!r}")
    return text[:6000]
