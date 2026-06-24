import re
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

from google.adk.agents import LlmAgent, SequentialAgent

from config import (
    GEMINI_EDITOR_MODEL,
    GEMINI_MODEL,
    GEMINI_RESEARCHER_MODEL,
    LLM_BACKEND,
    LOOKBACK_WINDOW,
    OLLAMA_BASE_URL,
    OLLAMA_EDITOR_MODEL,
    OLLAMA_RESEARCHER_MODEL,
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


def _ensure_state_defaults(callback_context):
    state = getattr(callback_context, "state", None)
    if state is None:
        return None
    defaults = {
        "regulatory_findings": "no qualifying items today",
        "competitor_findings": "no qualifying items today",
        "market_findings": "no qualifying items today",
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


def _publish_callback(callback_context):
    try:
        from render import render_email, write_output

        state = getattr(callback_context, "state", {}) or {}
        brief_md = state.get("brief_md", "") if hasattr(state, "get") else ""
        if not brief_md:
            print("publisher, no brief_md in session state, skipping render")
            return None

        cleaned_md = enforce_voice_rules(brief_md)
        date_str = datetime.now(tz=timezone.utc).astimezone().strftime("%B %d, %Y")
        html = render_email(cleaned_md, date_str, issue=99)
        path = write_output(html, date_str)
        url = f"file://{Path(path).resolve()}"
        print(f"publisher, rendered to {path}, opening in browser")
        webbrowser.open(url)

        try:
            from slack import SLACK_WEBHOOK_URL, post_to_slack

            if SLACK_WEBHOOK_URL:
                ok, detail = post_to_slack(cleaned_md, date_str, issue=99)
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


def _researcher_model():
    if LLM_BACKEND == "ollama":
        from google.adk.models.lite_llm import LiteLlm

        return LiteLlm(
            model=f"ollama_chat/{OLLAMA_RESEARCHER_MODEL}",
            api_base=OLLAMA_BASE_URL,
        )
    return GEMINI_RESEARCHER_MODEL


def _editor_model():
    if LLM_BACKEND == "ollama":
        from google.adk.models.lite_llm import LiteLlm

        return LiteLlm(
            model=f"ollama_chat/{OLLAMA_EDITOR_MODEL}",
            api_base=OLLAMA_BASE_URL,
        )
    return GEMINI_EDITOR_MODEL


def _researcher_tools():
    if LLM_BACKEND == "ollama":
        from tools import fetch_url, web_search

        return [web_search, fetch_url]
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


def _researcher(name: str, focus: str, output_key: str, mandatory_queries: list[str]) -> LlmAgent:
    if LLM_BACKEND == "ollama":
        steps = "\n".join(
            f"STEP {i + 1}. Call web_search with query: {q!r}. Wait for the result before moving on."
            for i, q in enumerate(mandatory_queries)
        )
        n = len(mandatory_queries)
        synth_step = (
            f"STEP {n + 1}. After all {n} web_search calls complete, optionally call fetch_url on up to three of the most promising result URLs to read the full article. "
            f"STEP {n + 2}. Write your findings as a markdown bulleted list, using ONLY URLs that appeared in your actual search results above. Each bullet is one sentence ending with a [Publication name](real URL) link."
        )
        tool_instr = f"""MANDATORY PROTOCOL. You MUST execute every step below in order. Do not skip any step. Do not write your final answer until ALL {n} web_search calls have completed.

{steps}
{synth_step}

DO NOT respond with 'no qualifying items today' unless every one of the {n} web_search calls above returned 'No results found.' or 'Search failed,'. If even ONE search returned real results, you MUST write findings based on those results."""
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
        tools=_researcher_tools(),
        output_key=output_key,
    )


regulatory_researcher = _researcher(
    name="regulatory_researcher",
    focus=(
        "US state and federal sweepstakes regulation. State bills, attorney "
        "general enforcement, cease and desist letters, court rulings, gaming "
        "board actions."
    ),
    output_key="regulatory_findings",
    mandatory_queries=[
        "state sweepstakes casino ban 2026",
        "attorney general sweepstakes cease and desist 2026",
        "Illinois Gaming Board sweepstakes cease and desist",
        "Mississippi Iowa Oklahoma sweepstakes legislation 2026",
        "Tennessee sweepstakes attorney general 2026",
        "California AB 831 sweepstakes",
    ],
)


competitor_researcher = _researcher(
    name="competitor_researcher",
    focus=(
        f"Moves by named sweepstakes operators including {_OPERATORS}. "
        "Product launches, state market entry or exit, promotional changes, "
        "lawsuits naming the operator, partnership announcements, fundraising news."
    ),
    output_key="competitor_findings",
    mandatory_queries=[
        "VGW Chumba LuckyLand news 2026",
        "Stake.us sweepstakes news 2026",
        "McLuck sweepstakes news 2026",
        "Pulsz High 5 sweepstakes news 2026",
        "sweepstakes operator state exit 2026",
        "WOW Vegas Funrize Hello Millions news 2026",
    ],
)


market_researcher = _researcher(
    name="market_researcher",
    focus=(
        "Broader sweepstakes market signals. Revenue estimates, GGR, market "
        "size data, M&A, supplier moves, payment processor exposure, "
        "class action filings, industry trade press analysis."
    ),
    output_key="market_findings",
    mandatory_queries=[
        "sweepstakes casino market size 2026",
        "sweepstakes class action lawsuit 2026",
        "sweepstakes payment processor liability 2026",
        "sweeps coin redemption volume 2026",
        "social casino revenue trend 2026",
        "sweepstakes industry M&A acquisition 2026",
    ],
)


research_team = SequentialAgent(
    name="research_team",
    description="Sequential sweepstakes intel research across regulatory, competitor, and market focus areas",
    sub_agents=[regulatory_researcher, competitor_researcher, market_researcher],
)


editor = LlmAgent(
    name="editor",
    model=_editor_model(),
    description="Assembles the final intel daily brief from the research team output",
    before_agent_callback=_ensure_state_defaults,
    instruction=f"""You are the editor of the LuckyHands Intel Daily brief.

You receive three research outputs in session state.
{{regulatory_findings}}
{{competitor_findings}}
{{market_findings}}

Your job. Build one brief that follows this exact structure. Preserve as much specific detail as possible from the research input. Goal is a longer, denser, more useful brief, not a short summary.

# LuckyHands Intel Daily

## Top story
Two paragraphs. Four to eight sentences. Pick the single most important item across all three research streams. Lead with the concrete fact (state name, operator name, dollar amount, date). Then explain the implication for LuckyHands stakeholders. Include at least one source link inline using the publication name as the link text, like [Gambling Insider](https://example.com). If the top story is regulatory, end with the sentence, Verify with counsel before acting on any item in this section.

## Regulatory and legal
Include EVERY qualifying regulatory item from the research input, up to eight items. Each one starts with either ACTION or WATCH in caps, then the state code or jurisdiction (e.g. IL, CA, MS, federal), then two or three sentences on what happened and why it matters to LuckyHands, then a source link as [Publication name](real URL from research input).

## Competitor moves
Include EVERY qualifying competitor item from the research input, up to eight items. Each one starts with the operator name, then one or two sentences on what changed, then a source link as [Publication name](url).

## Market and product signals
Three to six items. Each item is one or two sentences with a source link. Cover market size data, sentiment shifts, payment processor moves, App Store rank changes, M&A, anything else from market_findings.

## On our radar
Lower confidence items. Each one starts with `WARNING, single source.` followed by one sentence and a source link with publication name.

## Footer
Reply to this email with corrections. Corrections train the next brief.
Not legal advice. Verify any regulatory item with counsel before acting on it.

Hard rules.
Every URL you write must come from one of the three research input strings. Copy URLs verbatim from the research input. Never write a URL that is not in the research input.
If a research section returned `no qualifying items today`, write the same phrase under the matching brief heading. Do NOT invent generic placeholder content.
Source link text must be the actual publication name, never just the word Source.

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

You are given the draft brief in session state at {brief_md}, and the three research outputs at {regulatory_findings}, {competitor_findings}, {market_findings}.

Your job. Find any URL or factual claim in the brief that does NOT appear in one of the research input strings. Flag each one.

Format.
If everything looks supported, return exactly the string, All claims supported by research.
Otherwise return a markdown bullet list. Each bullet starts with FLAG and gives a short quote of the unsupported claim or invented URL.

Voice. Plain English. Do not worry about apostrophes or hyphens, a post process handles those.""",
    output_key="verification_note",
    after_agent_callback=_publish_callback,
)


newsletter_pipeline = SequentialAgent(
    name="newsletter_pipeline",
    description="Daily sweepstakes intel newsletter pipeline. Sequential research then editorial assembly then fact check.",
    sub_agents=[research_team, editor, verifier],
)
