import os
import re
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

from google.adk.agents import LlmAgent, SequentialAgent

from config import (
    EDITOR_BACKEND,
    GEMINI_EDITOR_MODEL,
    GEMINI_MODEL,
    GEMINI_RESEARCHER_MODEL,
    LLM_BACKEND,
    LOOKBACK_WINDOW,
    OLLAMA_BASE_URL,
    OLLAMA_EDITOR_MODEL,
    OLLAMA_RESEARCHER_MODEL,
    RESEARCHER_BACKEND,
)


_APOSTROPHE_CHARS = ["’", "‘", "'", "`"]
_HYPHEN_CHARS = ["‐", "‑", "‒", "-"]
_EM_DASH_CHARS = ["—", "–"]
_URL_PATTERN = re.compile(r"https?://\S+|\b\w+\.\w{2,}(?:/\S*)?")


def enforce_voice_rules(text: str) -> str:
    if not text:
        return text

    placeholders: dict[str, str] = {}

    def _stash_url(match: re.Match) -> str:
        token = f"\x00URL{len(placeholders)}\x00"
        placeholders[token] = match.group(0)
        return token

    def _stash_link_target(match: re.Match) -> str:
        token = f"\x00LNK{len(placeholders)}\x00"
        placeholders[token] = match.group(0)
        return token

    text = re.sub(r"\(https?://[^)]+\)", _stash_link_target, text)
    text = _URL_PATTERN.sub(_stash_url, text)

    for ch in _APOSTROPHE_CHARS:
        text = text.replace(ch, "")
    for ch in _HYPHEN_CHARS:
        text = re.sub(rf"(\w){re.escape(ch)}(\w)", r"\1 \2", text)
    for ch in _EM_DASH_CHARS:
        text = text.replace(ch, ". ")

    for token, original in placeholders.items():
        text = text.replace(token, original)

    text = re.sub(r"\.\s+\.\s+", ". ", text)
    return text


_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
_LINK_STOPWORDS = {
    "the", "magazine", "news", "media", "online", "post", "report",
    "today", "daily", "weekly", "press", "release", "com", "net", "org",
    "source", "official",
}


def _normalize_publication(text: str) -> str:
    words = re.findall(r"[a-z0-9]+", text.lower())
    words = [w for w in words if w not in _LINK_STOPWORDS and len(w) >= 2]
    return "".join(words)


def _normalize_host(url: str) -> str:
    m = re.match(r"https?://([^/]+)", url)
    if not m:
        return ""
    host = m.group(1).lower()
    if host.startswith("www."):
        host = host[4:]
    parts = host.split(".")
    if len(parts) >= 2:
        host = "".join(parts[:-1])
    else:
        host = parts[0]
    return host


def check_link_integrity(md: str) -> list[str]:
    """Flag markdown links where [text] is not present in the URL host.

    Returns a list of warning strings. Catches the hallucination mode where the
    model writes a publication name but pulls a URL from a different source.
    """
    warnings: list[str] = []
    if not md:
        return warnings
    for m in _LINK_RE.finditer(md):
        pub_text = m.group(1).strip()
        url = m.group(2)
        if pub_text.lower() == "source":
            continue
        pub_norm = _normalize_publication(pub_text)
        host_norm = _normalize_host(url)
        if not pub_norm or not host_norm:
            continue
        if pub_norm in host_norm or host_norm in pub_norm:
            continue
        warnings.append(f"link mismatch, [{pub_text}]({url}) host {host_norm} does not match pub {pub_norm}")
    return warnings


_LOW_QUALITY_SOURCE_HOSTS = (
    "sweepskings.com",
    "casinorankr.com",
    "supplychaindigital.com",
    "stockmarketsignal.com",
    "newspatrolling.com",
    "casinonews.io",
    "rotowire.com",
    "bonusbell.com",
    "sweepedia.com",
    "tech-insider.org",
    "kotaku.com",
    "yardbarker.com",
    "g-mnews.com",
    "everything-pr.com",
    "winthelottery.com",
    "bitcoinchaser.com",
    "brightsideofnews.com",
    "coinranking.com",
)


_TOPIC_RELEVANCE_TOKENS = (
    "sweepstakes", "sweeps", "social casino", "dual currency", "stake.us",
    "chumba", "mcluck", "luckyland", "global poker", "vgw", "pulsz",
    "high 5", "wow vegas", "funrize", "hello millions", "fortune coins",
    "modo", "fliff", "legendz", "sportzino", "crown coins", "mega bonanza",
    "geocomply", "xpoint", "sightline", "trustly", "polymarket", "kalshi",
    "novig", "robinhood event", "forecastex", "casino", "gambling",
    "gaming board", "gaming commission", "attorney general", " ag ",
    "cease and desist", "racketeering", "online gaming", "online gambling",
    "internet gambling", "internet gaming", "wager", "lottery",
    "fincen", "ftc ", "irs ", "cftc", "treasury", "court", "lawsuit",
    "class action", "ruling", "injunction", "settlement",
)


_KNOWN_DATE_CORRECTIONS = [
    (
        re.compile(
            r"(LD\s*2007|Maine\s+sweepstakes|ME\s+LD2007)[^.\n]{0,200}?(August\s+1,?\s*2026|Aug\s+1,?\s*2026|August\s+1st,?\s*2026)",
            re.IGNORECASE,
        ),
        "ME LD2007 effective date wrong (August 1 2026), correct value is mid July 2026 after April 6 2026 signing",
    ),
]


def _apply_known_date_corrections(md: str) -> tuple[str, list[str]]:
    """Last line of defense. Replaces known wrong dates with the right ones.

    Replaces 'August 1, 2026' (in the context of Maine LD 2007 only) with
    'mid July 2026, signed by Governor Mills on April 6 2026'.
    """
    warnings: list[str] = []
    out = md

    def _replace_maine(m: re.Match) -> str:
        warnings.append(
            "ME LD2007 effective date corrected from August 1 2026 to mid July 2026"
        )
        prefix = m.group(0).split(m.group(2))[0]
        return prefix + "mid July 2026 (signed by Governor Mills April 6 2026, Public Law 2025 Chapter 645)"

    pattern, _desc = _KNOWN_DATE_CORRECTIONS[0]
    out = pattern.sub(_replace_maine, out)
    return out, warnings


def _sanitize_brief(md: str, state: dict) -> tuple[str, list[str]]:
    """Deterministic post process that catches hallucinated URLs and off topic items.

    Returns (cleaned_md, list_of_warnings).
    """
    warnings: list[str] = []
    if not md:
        return md, warnings

    # Build the corpus of authoritative URLs across all primary source streams
    all_findings = " ".join(
        str(state.get(k, "") or "") for k in (
            "regulatory_findings",
            "competitor_findings",
            "market_findings",
            "legiscan_findings",
            "rss_findings",
            "federal_register_findings",
            "courtlistener_findings",
            "sentiment_findings",
        )
    )

    out_lines: list[str] = []
    current_section: str | None = None
    for raw_line in md.splitlines():
        line = raw_line
        stripped = line.strip()

        if stripped.startswith("## "):
            raw_section = stripped[3:].strip().lower()
            current_section = re.sub(r"^\d+\.\s*", "", raw_section).strip()
            out_lines.append(raw_line)
            continue
        if stripped.startswith("# "):
            current_section = None
            out_lines.append(raw_line)
            continue

        link_match = _LINK_RE.search(line)
        if link_match:
            url = link_match.group(2)
            base_url = url.split("?")[0].rstrip("/")
            if base_url not in all_findings and url not in all_findings:
                warnings.append(f"dropping line, URL {url} not in any research input")
                continue
            url_host = _normalize_host(url)
            if any(host in url.lower() for host in _LOW_QUALITY_SOURCE_HOSTS):
                warnings.append(f"dropping line, low quality source host in {url}")
                continue

            if current_section in {"top story", "on our radar"}:
                hay = line.lower()
                if not any(t in hay for t in _TOPIC_RELEVANCE_TOKENS):
                    warnings.append(f"dropping line, {current_section} line lacks sweepstakes topic tokens, {line[:100]}")
                    continue

        out_lines.append(raw_line)

    cleaned_md = "\n".join(out_lines)
    corrected_md, date_warnings = _apply_known_date_corrections(cleaned_md)
    warnings.extend(date_warnings)
    return corrected_md, warnings


def _ensure_state_defaults(callback_context):
    state = getattr(callback_context, "state", None)
    if state is None:
        return None
    defaults = {
        "regulatory_findings": "no qualifying items today",
        "competitor_findings": "no qualifying items today",
        "market_findings": "no qualifying items today",
        "legiscan_findings": "no qualifying legislative items today",
        "rss_findings": "no qualifying RSS items today",
        "federal_register_findings": "no qualifying Federal Register items today",
        "courtlistener_findings": "no qualifying CourtListener filings today",
        "brief_md": "",
        "verification_note": "",
    }
    for k, v in defaults.items():
        if hasattr(state, "get"):
            current = state.get(k)
        else:
            current = None
        if current is None or current == "":
            try:
                state[k] = v
            except Exception:
                pass
    return None


def _primary_source_pull(callback_context):
    try:
        from primary_sources import primary_source_pull_callback
        return primary_source_pull_callback(callback_context)
    except Exception as exc:
        print(f"[primary_source] callback failed, {exc}")
    return None


def _publish_callback(callback_context):
    try:
        from render import render_email, write_output

        state = getattr(callback_context, "state", {}) or {}
        brief_md = state.get("brief_md", "") if hasattr(state, "get") else ""
        if not brief_md:
            print("publisher, no brief_md in session state, skipping render")
            return None

        sanitized_md, sanitize_warnings = _sanitize_brief(brief_md, state if hasattr(state, "get") else {})
        if sanitize_warnings:
            print(f"[sanitize] {len(sanitize_warnings)} items dropped or flagged")
            for w in sanitize_warnings[:10]:
                print(f"  - {w}")
        cleaned_md = enforce_voice_rules(sanitized_md)

        link_warnings = check_link_integrity(cleaned_md)
        if link_warnings:
            print(f"[link_check] {len(link_warnings)} potential link mismatches in brief")
            for w in link_warnings[:10]:
                print(f"  - {w}")
            try:
                from dates import us_date_slug
                date_slug = us_date_slug()
                out_dir = Path(__file__).parent / "output"
                out_dir.mkdir(exist_ok=True)
                (out_dir / f"link_warnings_{date_slug}.txt").write_text(
                    "\n".join(link_warnings), encoding="utf-8"
                )
            except Exception:
                pass

        from dates import us_date_long
        date_str = us_date_long()
        issue_num = _current_issue_number()
        html = render_email(cleaned_md, date_str, issue=issue_num)
        path = write_output(html, date_str)
        url = f"file://{Path(path).resolve()}"
        if os.getenv("INTEL_DAILY_NO_BROWSER", "").strip() in {"1", "true", "True", "yes"}:
            print(f"publisher, rendered to {path}, headless mode, skipping browser open")
        else:
            print(f"publisher, rendered to {path}, opening in browser")
            webbrowser.open(url)

        try:
            from slack import SLACK_WEBHOOK_URL, post_to_slack
            from verify_brief import render_corrections_md, verify_brief_markdown

            no_slack = os.getenv("INTEL_DAILY_NO_SLACK", "").strip() in {"1", "true", "True", "yes"}
            skip_verify = os.getenv("INTEL_DAILY_SKIP_VERIFY", "").strip() in {"1", "true", "True", "yes"}

            if not skip_verify:
                print("publisher, verifying every brief claim against the live web")
                started = time.time()
                report = verify_brief_markdown(cleaned_md, max_workers=4)
                print(
                    f"publisher, verify done in {time.time() - started:.1f}s, "
                    f"{report['summary']}"
                )
                corrections_md = render_corrections_md(report, date_str)
                try:
                    out_dir = Path(__file__).parent / "output"
                    out_dir.mkdir(exist_ok=True)
                    from dates import us_date_slug
                    corr_path = out_dir / f"verify_report_{us_date_slug()}.md"
                    corr_path.write_text(corrections_md, encoding="utf-8")
                    print(f"publisher, wrote verify report to {corr_path}")
                except Exception as exc:
                    print(f"publisher, failed to write verify report, {exc}")

                if not report["ok"]:
                    print(
                        f"publisher, BLOCKING Slack send, {report['incorrect']} "
                        f"incorrect claims found. Inspect the verify report."
                    )
                    return None
            else:
                print("publisher, INTEL_DAILY_SKIP_VERIFY set, bypassing verify gate")

            if no_slack:
                print("publisher, INTEL_DAILY_NO_SLACK set, skipping Slack post")
            elif SLACK_WEBHOOK_URL:
                ok, detail = post_to_slack(cleaned_md, date_str, issue=issue_num)
                if ok:
                    print(f"publisher, posted to Slack")
                else:
                    print(f"publisher, Slack post skipped, {detail}")
            else:
                print("publisher, SLACK_WEBHOOK_URL not set, skipping Slack")
        except Exception as exc:
            print(f"publisher, Slack post failed, {exc}")
    except Exception as exc:
        print(f"publisher callback failed, {exc}")
    return None


_LLM_TIMEOUT_S = int(os.getenv("LLM_TIMEOUT_S", "1200"))


def _current_issue_number() -> int:
    """Read the issue number for display. Same logic as run._issue_number but
    non-incrementing (used in publisher_callback which runs after run.py has
    already updated the counter)."""
    override = os.getenv("INTEL_DAILY_ISSUE_OVERRIDE", "").strip()
    if override != "":
        try:
            return int(override)
        except ValueError:
            pass
    state_file = Path(__file__).parent / ".issue_counter"
    if state_file.exists():
        try:
            return int(state_file.read_text().strip())
        except ValueError:
            return 0
    return 0


def _researcher_model():
    if RESEARCHER_BACKEND == "ollama":
        from google.adk.models.lite_llm import LiteLlm

        return LiteLlm(
            model=f"ollama_chat/{OLLAMA_RESEARCHER_MODEL}",
            api_base=OLLAMA_BASE_URL,
            timeout=_LLM_TIMEOUT_S,
        )
    return GEMINI_RESEARCHER_MODEL


def _editor_model():
    if EDITOR_BACKEND == "ollama":
        from google.adk.models.lite_llm import LiteLlm

        return LiteLlm(
            model=f"ollama_chat/{OLLAMA_EDITOR_MODEL}",
            api_base=OLLAMA_BASE_URL,
            timeout=_LLM_TIMEOUT_S,
            temperature=0.1,
            top_p=0.8,
            seed=42,
            num_ctx=24576,
        )
    return GEMINI_EDITOR_MODEL


def _search_tool_for_intent(intent: str = "auto"):
    if RESEARCHER_BACKEND != "ollama":
        return None
    from tools import web_search, web_search_news, web_search_semantic
    if intent == "news":
        return web_search_news
    if intent == "semantic":
        return web_search_semantic
    return web_search


def _researcher_tools(intent: str = "auto"):
    if RESEARCHER_BACKEND == "ollama":
        from tools import fetch_url
        return [_search_tool_for_intent(intent), fetch_url]
    from google.adk.tools import google_search
    return [google_search]


VOICE_RULES = """Voice rules.
Plain English, casual, short sentences.
Active voice. No marketing language. No filler.
Stake.us style domain names are fine.
A deterministic post process strips apostrophes, hyphens, and em dashes after you write, so do not waste effort enforcing those."""


URL_DISCIPLINE = """Hard rule on URLs. Every URL you write MUST come from an actual web_search or fetch_url result you ran in THIS conversation. Copy URLs verbatim. Never edit, shorten, or guess. If you do not have a real URL for a claim, do NOT write a URL, write the publication name in plain text instead. Hallucinated URLs will be caught by the post process and the whole brief will be rejected."""


_OPERATORS = (
    "Stake.us, McLuck, Chumba, LuckyLand, Global Poker, VGW, Pulsz, High 5, "
    "Fortune Coins, Modo, Fliff, Funrize, Legendz, WOW Vegas, Hello Millions, "
    "Sportzino, Crown Coins, Mega Bonanza"
)


def _researcher(
    name: str,
    focus: str,
    output_key: str,
    mandatory_queries: list[str],
    dynamic_context_keys: list[str] | None = None,
    intent: str = "auto",
) -> LlmAgent:
    dynamic_context_keys = dynamic_context_keys or []
    search_tool_fn = _search_tool_for_intent(intent)
    tool_name_for_prompt = search_tool_fn.__name__ if search_tool_fn else "web_search"

    if RESEARCHER_BACKEND == "ollama":
        steps = "\n".join(
            f"STEP {i + 1}. Call {tool_name_for_prompt} with query: {q!r}. Wait for the result before moving on."
            for i, q in enumerate(mandatory_queries)
        )
        n = len(mandatory_queries)
        followup_block = ""
        if dynamic_context_keys:
            placeholders = "\n".join(f"{{{k}}}" for k in dynamic_context_keys)
            followup_block = (
                f"\nSTEP {n + 1}. Read the primary source data below from session state.\n"
                f"{placeholders}\n"
                f"From that data, identify the top 3 most active bills by recency, across any state. For each of those 3 bills, call {tool_name_for_prompt} with a query in the format STATE_CODE BILL_NUMBER sweepstakes (substituting the actual values, e.g. LA HB53 sweepstakes). Run all 3 follow up searches before moving to the synthesis step.\n"
            )
            synth_step_n = n + 3
        else:
            synth_step_n = n + 2

        synth_block = (
            f"STEP {synth_step_n - 1}. After all the web_search calls complete (mandatory plus follow up if applicable), optionally call fetch_url on up to three of the most promising result URLs to read the full article.\n"
            f"STEP {synth_step_n}. Write your findings as a markdown bulleted list, using ONLY URLs that appeared in your actual search results above. Each bullet is one sentence ending with a [Publication name](real URL) link."
        )

        tool_instr = f"""MANDATORY PROTOCOL. You MUST execute every step below in order. Do not skip any step. Do not write your final answer until ALL mandatory web_search calls have completed.

{steps}
{followup_block}{synth_block}

DO NOT respond with 'no qualifying items today' unless every one of the web_search calls above returned 'No results found.' or 'Search failed,'. If even ONE search returned real results, you MUST write findings based on those results."""
    else:
        tool_instr = "Use the google_search tool to run targeted queries. Run at least six queries across different angles."

    instruction = f"""You are the {name} for the LuckyHands Intel Daily brief.

Your focus.
{focus}

Lookback window. {LOOKBACK_WINDOW}.

{tool_instr}

Output format. Return a markdown list. One bullet per finding. Each bullet has this shape exactly.

- One sentence describing what happened, written in plain English. [Publication name](real URL from your search results)

Aim for as many qualifying items as you genuinely found, ideally six to twelve. Quality over count.

{URL_DISCIPLINE}

{VOICE_RULES}"""

    return LlmAgent(
        name=name,
        model=_researcher_model(),
        description=focus,
        instruction=instruction,
        tools=_researcher_tools(intent),
        output_key=output_key,
    )


def _current_year() -> int:
    from dates import us_year
    return us_year()


regulatory_researcher = _researcher(
    name="regulatory_researcher",
    focus=(
        "US state and federal sweepstakes regulation news context. Attorney general "
        "enforcement, cease and desist announcements, court rulings, gaming board "
        "advisories, federal regulator actions (FinCEN, FTC, IRS, CFTC, Treasury), "
        "tribal coalition activity, and trade press analysis. Note. The exact "
        "legislative bill universe is already surfaced by LegiScan and flows "
        "directly to the editor downstream. Your role is to find news commentary, "
        "court rulings, and enforcement actions that the bill data alone cannot "
        "capture."
    ),
    output_key="regulatory_findings",
    mandatory_queries=[
        f"state attorney general sweepstakes lawsuit cease and desist {_current_year()}",
        f"Kentucky Coleman lawsuit VGW Kalshi Polymarket Franklin Circuit {_current_year()}",
        f"California AB 831 sweepstakes enforcement signed effective {_current_year()}",
        f"federal court sweepstakes ruling injunction TRO {_current_year()}",
        f"CFTC prediction market preemption suit state Minnesota Kentucky {_current_year()}",
        f"NACA Polymarket lawsuit DC Superior Court deceptive marketing {_current_year()}",
        f"FinCEN FTC sweepstakes payment processor enforcement {_current_year()}",
        f"state gaming commission sweepstakes advisory letter {_current_year()}",
        f"Michigan judge Kalshi prediction market ruling {_current_year()}",
        f"Illinois Gaming Board sweepstakes cease and desist {_current_year()}",
    ],
    intent="news",
)


competitor_researcher = _researcher(
    name="competitor_researcher",
    focus=(
        f"Moves by named sweepstakes operators including {_OPERATORS}. "
        "Product launches, state market entry or exit, promotional changes, "
        "lawsuits naming the operator, partnership announcements, fundraising news, "
        "leadership changes, M&A, brand rebrands, App Store rank shifts. "
        "Also payment processor (Sightline, Trustly, Worldpay, Stripe, Nuvei) and "
        "geolocation vendor (GeoComply, Xpoint) moves where they affect sweepstakes "
        "operators. Include KYC and identity vendors (Sumsub, Jumio, Veriff)."
    ),
    output_key="competitor_findings",
    mandatory_queries=[
        f"VGW Chumba LuckyLand Global Poker sweepstakes {_current_year()}",
        f"Stake.us McLuck state exit sweepstakes {_current_year()}",
        f"Pulsz High 5 Fortune Coins Funrize sweepstakes news {_current_year()}",
        f"Modo Fliff Legendz Sportzino sweepstakes operator {_current_year()}",
        f"Crown Coins Mega Bonanza Hello Millions WOW Vegas {_current_year()}",
        f"Indiana sweepstakes operator exit list HB 1052 {_current_year()}",
        f"Iowa sweepstakes operator exit SF 2289 {_current_year()}",
        f"Maine LD 2007 sweepstakes operator exit {_current_year()}",
        f"GeoComply Xpoint Sightline sweepstakes vendor partnership {_current_year()}",
        f"sweepstakes operator security breach hack frontend vendor {_current_year()}",
    ],
    intent="semantic",
)


market_researcher = _researcher(
    name="market_researcher",
    focus=(
        "Broader sweepstakes market signals. Revenue estimates from Eilers and "
        "Krejcik, Vixio, Gambling Insider analyst notes, GGR data, M&A, supplier "
        "moves, payment processor exposure, class action filings, prediction "
        "markets sibling beat (Kalshi, Polymarket, Novig, Robinhood Event "
        "Contracts, ForecastEx), tribal opposition, industry trade press analysis. "
        "Also: App Store DAU shifts, distressed operator closures and small operator "
        "consolidation, fundraising rounds, industry conferences (SBC Summit, ICE)."
    ),
    output_key="market_findings",
    mandatory_queries=[
        f"Eilers Krejcik sweepstakes revenue forecast {_current_year()}",
        f"sweepstakes casino market size revenue Vixio {_current_year()}",
        f"sweepstakes industry M&A acquisition funding {_current_year()}",
        f"Kalshi Polymarket valuation funding round trading volume {_current_year()}",
        f"prediction markets CFTC state preemption suit ruling {_current_year()}",
        f"Meta Arena prediction market app Zuckerberg Polymarket Kalshi {_current_year()}",
        f"sweepstakes operator closure shutdown consolidation {_current_year()}",
        f"sweepstakes payment processor Visa Mastercard MCC {_current_year()}",
        f"Polymarket NACA lawsuit DC Superior deceptive marketing {_current_year()}",
        f"Polymarket CFTC investigation marketing influencer probe {_current_year()}",
    ],
    intent="auto",
)


research_team = SequentialAgent(
    name="research_team",
    description="Sequential sweepstakes intel research across regulatory, competitor, and market focus areas",
    sub_agents=[regulatory_researcher, competitor_researcher, market_researcher],
    before_agent_callback=_primary_source_pull,
)


editor = LlmAgent(
    name="editor",
    model=_editor_model(),
    description="Assembles the final intel daily brief from the research team output",
    before_agent_callback=_ensure_state_defaults,
    instruction=f"""You are the editor of the LuckyHands Intel Daily brief.

You receive seven research outputs in session state.

LLM research streams.
{{regulatory_findings}}
{{competitor_findings}}
{{market_findings}}

Primary source pulls (deterministic free APIs, treat as ground truth).
{{legiscan_findings}}
{{rss_findings}}
{{federal_register_findings}}
{{courtlistener_findings}}

CRITICAL DATA PRESERVATION RULES. Read these carefully, they prevent the most common failure modes.

Rule 1. Status terminology. When LegiScan or any primary source uses a specific bill status phrase, preserve it verbatim and use it correctly.
- "PASSED to be enacted" means the bill is SIGNED INTO LAW. Do NOT say "pending enactment".
- "Chaptered" means signed and law.
- "Sent to the Governor" means awaiting signature.
- "Effective date" followed by a date means the bill is law and enforceable on that date.

Rule 2. Title preservation. If a bill title or LegiScan summary uses a specific term like "online sweepstakes" or "dual currency", use that exact term in your output. Do NOT generalize "online sweepstakes" to "online gambling".

Rule 3. Specifics over summary. If LegiScan or a research finding includes a bill number, an effective date, a dollar amount, a person name, a scope detail (e.g. "raises max fines from twenty thousand to one hundred thousand dollars"), INCLUDE those specifics in your output. Do not paraphrase down to "tightens penalties".

Rule 4. AUTHORITATIVE field discipline. If a LegiScan bullet contains the word "AUTHORITATIVE:" followed by a description, that description is the verified ground truth for that bill. You MUST use those facts verbatim, including governor signing dates, effective dates, penalty amounts, codification numbers, and any redirect to a different bill number (e.g. if AUTHORITATIVE says "provisions enacted via SF4760", write the story around SF4760 not the original bill number). Never invent or override AUTHORITATIVE facts.

Rule 5. Polymarket and Kalshi framing. Both Polymarket and Kalshi are CFTC regulated derivatives or event contract exchanges in the US. Do NOT describe either as an "unlicensed platform". When covering NACA v Polymarket or similar litigation, frame around the actual cause of action (e.g. DC Consumer Protection Procedures Act for deceptive marketing), not licensure status.

PRIORITIZATION RULES.

Priority A. Sweepstakes first. The brief is the LuckyHands Sweepstakes Intel Daily. Sweepstakes core news (named operators, sweeps coins, dual currency, social casino bans) gets top priority in the Top story.

Priority B. Prediction markets is a sibling beat. Stories about Kalshi, Polymarket, Novig, Robinhood Event Contracts, ForecastEx belong in On our radar or a short Market signals mention, NOT in Top story unless no sweepstakes news exists in the inputs.

DEDUPLICATION RULE. The same underlying event must appear in only ONE section of the brief. If Polymarket lawsuit is the Top story, do not also put it in Market signals or On our radar. Pick the highest impact section and put it there.

QUALITY BAR. These items do NOT belong in any brief, drop them silently.
- Affiliate promo codes ("Use code HANDLE for fifteen dollar bonus").
- Sports event tie in promos (World Cup match bonuses, NBA Finals codes).
- Generic operator marketing announcements with no news angle.
- The same event coverage from three different sources, cite once.

Your job. Build one brief that follows this EXACT fixed template. Every section is mandatory. If a section has no qualifying items today, write the literal phrase `no qualifying items today` under that heading, never invent filler. Goal is a comprehensive, dense, useful brief that covers the full sweepstakes intel waterfront.

# LuckyHands Intel Daily

## 1. Top story
Two paragraphs, 4 to 8 sentences. The single most important sweepstakes-relevant event of the day. Lead with the concrete fact (state, operator, bill number, dollar amount, named person). Then implications for LuckyHands stakeholders. End with one source link as [Publication](url). If regulatory, end with the sentence `Verify with counsel before acting on any item in this section.`

## 2. Legislative scoreboard
One bullet per bill in legiscan_findings, no exceptions, in order of impact (signed bills first, then pending). Format each bullet as:

- **STATE BILLNUMBER** — STATUS, effective EFFECTIVE_DATE. SCOPE in one sentence (mention dual currency, penalty range, AG authority, codification when present). [Authoritative](url) [LegiScan](url)

Rules:
- Use AUTHORITATIVE block facts verbatim for status, effective date, scope. Never invent.
- Status values: Signed, Pending, Vetoed, Dead, Veto Override, Awaiting Governor.
- If effective date is unknown, write "TBD".
- If a bill was enacted via another bill number per AUTHORITATIVE, write the story around the enacted bill number (e.g. SF4760 not HF4437).

## 3. Enforcement and litigation
Pull from regulatory_findings AND courtlistener_findings. Include EVERY qualifying item, up to 8 bullets. Each starts with ACTION or WATCH in caps, then jurisdiction (state code, federal agency), then 2 to 3 sentences on what happened and implications for LuckyHands. Source link inline.
Categories to surface when present:
- State AG cease-and-desist, lawsuits, advisories
- Federal regulator actions (FinCEN, FTC, CFTC, Treasury, IRS)
- Court rulings, motions, injunctions, class action filings
- Gaming commission advisories

## 4. Competitor moves
Up to 8 items from competitor_findings or rss_findings. REAL operator news only:
- State market entry or exit
- Named lawsuits against operators
- Product launches, leadership changes, fundraising, M&A
- App Store rank shifts
- Vendor or sports league partnerships
- Brand rebrands or platform shifts
Each bullet starts with the operator name in bold, then 1 to 2 sentences, then source link. DROP affiliate promo codes, sports tie-in bonuses, generic marketing posts.

## 5. Vendor and infrastructure
Up to 5 items. Payment processors (Sightline, Trustly, Worldpay, Stripe), geolocation (GeoComply, Xpoint), KYC/identity (Jumio, Sumsub), game studios. Each: vendor name, what changed, source link. If nothing today, write `no qualifying items today`.

## 6. Market and product signals
Up to 5 items. Eilers and Krejcik estimates, GGR data, industry M&A, payment processor exposure, App Store DAU shifts, analyst notes. DO NOT duplicate the Top story event.

## 7. Prediction markets (sibling beat)
Up to 4 items. Kalshi, Polymarket, Novig, Robinhood Event Contracts, ForecastEx, CFTC actions. Frame around actual cause of action (see Rule 5 above re Polymarket/Kalshi as CFTC regulated). If nothing today, write `no qualifying items today`.

## 8. On our radar
2 to 4 lower-confidence items. Each starts with `WARNING, single source.` then one sentence and source link. DO NOT duplicate items already in earlier sections.

## 9. Footer
Reply to this thread with corrections. They train the next brief.
Not legal advice. Verify any regulatory item with counsel before acting on it.

Hard rules.
- Every URL must come from one of the seven research input strings (regulatory_findings, competitor_findings, market_findings, legiscan_findings, rss_findings, federal_register_findings, courtlistener_findings) or from a LegiScan AUTHORITATIVE block. Copy URLs verbatim. Never invent or guess URLs.
- Source link text must be the actual publication name, never just the word Source. For LegiScan rows, the source link text is LegiScan; for Authoritative grounded URLs, use the publication name in the URL host (e.g. [Maine.gov](maine.gov url) or [Gambling Insider](gamblinginsider.com url)).
- If a research section returned `no qualifying items today`, the corresponding template section gets the same phrase.

{URL_DISCIPLINE}

{VOICE_RULES}""",
    output_key="brief_md",
)


verifier = LlmAgent(
    name="verifier",
    model=_editor_model(),
    description="Fact checks the brief against the research findings, internal QA only",
    before_agent_callback=_ensure_state_defaults,
    instruction="""You are the internal fact checker for the LuckyHands Intel Daily brief.

You are given the draft brief in session state at {brief_md}, and seven research outputs at {regulatory_findings}, {competitor_findings}, {market_findings}, {legiscan_findings}, {rss_findings}, {federal_register_findings}, {courtlistener_findings}.

Your job. Six checks.

Check 1. URL provenance. Every URL in the brief must appear verbatim in one of the seven research input strings. Flag any URL that is not in the research inputs.

Check 2. Link integrity. For every markdown link [Publication name](url), the publication name in the link text MUST roughly match the URL host. Example of a valid link, [Gambling Insider](https://www.gamblinginsider.com/article/123). Example of an INVALID link, [Reuters](https://lawandcrime.com/article) where the link text says Reuters but the URL host is lawandcrime.com. Flag every invalid link.

Check 3. Claim grounding. Every factual claim (state name, date, dollar amount, named person, bill number) must be supported by at least one research finding. Flag claims not supported.

Check 4. Status terminology. If the brief uses LegiScan status phrases like "PASSED to be enacted" or "Chaptered" or "Sent to the Governor", make sure the brief interprets them correctly. PASSED to be enacted means SIGNED INTO LAW, not pending. Chaptered means LAW. Sent to the Governor means awaiting signature. Flag any item where the brief says "pending enactment" or similar when the underlying status is actually signed.

Check 5. Deduplication. The same underlying event must NOT appear in more than one section of the brief. Flag any duplicate. Example, if Polymarket lawsuit appears in Top story AND Market signals AND On our radar, flag it.

Check 6. Sweepstakes adjacency. The brief is the LuckyHands Sweepstakes Intel Daily. Prediction markets (Kalshi, Polymarket, Novig, Robinhood Event Contracts) is a sibling beat that should only lead Top story if no sweepstakes story exists in the inputs. Flag if Top story is prediction markets while sweepstakes news exists in the inputs.

Format.
If everything passes all six checks, return exactly the string, All checks pass.
Otherwise return a markdown bullet list. Each bullet starts with FLAG and gives a short quote of the issue.

Voice. Plain English. Do not worry about apostrophes or hyphens, a post process handles those.""",
    output_key="verification_note",
    after_agent_callback=_publish_callback,
)


newsletter_pipeline = SequentialAgent(
    name="newsletter_pipeline",
    description="Daily sweepstakes intel newsletter pipeline. Sequential research then editorial assembly then fact check.",
    sub_agents=[research_team, editor, verifier],
)
