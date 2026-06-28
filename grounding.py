"""Dynamic fact grounding via Gemini Flash + Google Search.

Replaces the prior static KNOWN_BILL_FACTS dict. Each daily run grounds bill
status, signing dates, effective dates, codification, and key provisions
against the live web. Results cache for the UTC day to keep call counts low.

All calls run on the Gemini free tier (no credit card required).
"""

import json
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


_CACHE_DB = Path(__file__).parent / "cache.db"
_CACHE_INITIALIZED = False
_GEMINI_CLIENT = None
_GROUND_MODEL = os.getenv("GROUNDING_MODEL", "gemini-2.5-flash-lite")


def _ensure_cache():
    global _CACHE_INITIALIZED
    if _CACHE_INITIALIZED:
        return
    conn = sqlite3.connect(_CACHE_DB)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS grounding_cache ("
        " utc_date TEXT NOT NULL,"
        " key TEXT NOT NULL,"
        " payload TEXT NOT NULL,"
        " created_at REAL NOT NULL,"
        " PRIMARY KEY (utc_date, key)"
        ")"
    )
    conn.commit()
    conn.close()
    _CACHE_INITIALIZED = True


def _utc_date() -> str:
    """Day key used for cache. Renamed for legacy reasons but uses US Eastern."""
    from dates import us_date
    return us_date()


def _cache_get(key: str) -> dict | None:
    _ensure_cache()
    conn = sqlite3.connect(_CACHE_DB)
    row = conn.execute(
        "SELECT payload FROM grounding_cache WHERE utc_date = ? AND key = ?",
        (_utc_date(), key),
    ).fetchone()
    conn.close()
    if not row:
        return None
    try:
        return json.loads(row[0])
    except Exception:
        return None


def _cache_set(key: str, payload: dict) -> None:
    _ensure_cache()
    conn = sqlite3.connect(_CACHE_DB)
    conn.execute(
        "INSERT OR REPLACE INTO grounding_cache "
        "(utc_date, key, payload, created_at) VALUES (?, ?, ?, ?)",
        (_utc_date(), key, json.dumps(payload), time.time()),
    )
    conn.commit()
    conn.close()


def _client():
    global _GEMINI_CLIENT
    if _GEMINI_CLIENT is None:
        from google import genai
        api_key = os.getenv("GOOGLE_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError(
                "GOOGLE_API_KEY not set. Required for grounding. "
                "Get a free key at https://aistudio.google.com/apikey"
            )
        _GEMINI_CLIENT = genai.Client(api_key=api_key)
    return _GEMINI_CLIENT


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _extract_json(text: str) -> dict | None:
    text = _strip_code_fence(text or "")
    try:
        return json.loads(text)
    except Exception:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group(0))
        except Exception:
            return None
    return None


def _call_grounded(prompt: str) -> str:
    from google.genai import types as gtypes

    try:
        resp = _client().models.generate_content(
            model=_GROUND_MODEL,
            contents=prompt,
            config=gtypes.GenerateContentConfig(
                tools=[gtypes.Tool(google_search=gtypes.GoogleSearch())],
                temperature=0.1,
            ),
        )
        return resp.text or ""
    except Exception as exc:
        print(f"[grounding] Gemini call failed, {exc}")
        return ""


def ground_bill_facts(state: str, bill_number: str, title: str) -> dict | None:
    """Live-ground authoritative facts about a single bill.

    Returns dict with keys:
      status                - signed | pending | dead | vetoed | unknown
      signing_date          - YYYY-MM-DD or empty string
      effective_date        - YYYY-MM-DD or YYYY-MM-DD approx or empty string
      codification          - Public Law / Chapter / Session Law ref or empty
      key_provisions        - 1-2 sentence summary of scope and penalties
      source_url            - authoritative URL
      is_sweepstakes_relevant - true | false
      enacted_via           - alternate bill number if rolled into another bill, empty string otherwise
    """
    state = (state or "").upper().strip()
    bill_number = (bill_number or "").upper().strip().replace(" ", "")
    if not state or not bill_number:
        return None

    cache_key = f"bill:{state}:{bill_number}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    today = _utc_date()
    prompt = (
        f"Today is {today}. Search the web and return current authoritative facts "
        f"about this US state legislative bill.\n\n"
        f"State: {state}\n"
        f"Bill Number: {bill_number}\n"
        f"Bill Title: {title or '(unknown)'}\n\n"
        f"Find each of these. Use the verified current state of the bill.\n"
        f"1. status. One of: signed, pending, dead, vetoed, unknown.\n"
        f"   - If the standalone bill died BUT its provisions were folded into "
        f"another bill that was signed and enacted, set status to \"signed\" and "
        f"fill enacted_via with that bill number. Example: if MN HF4437 standalone "
        f"failed but its prediction market ban substance is now law via SF4760, "
        f"the status here is signed and enacted_via is SF4760.\n"
        f"   - If carried over to next session (e.g. Virginia continued to 2027), "
        f"use \"pending\" with a note about the carryover in key_provisions.\n"
        f"   - Only use \"dead\" if the bill failed AND no companion or omnibus "
        f"absorbed its substance.\n"
        f"2. signing_date if signed (YYYY-MM-DD). Empty string if unknown. If "
        f"enacted_via another bill, give that other bill's signing date.\n"
        f"3. effective_date or operative date (YYYY-MM-DD). For Maine bills with no "
        f"emergency clause, this is roughly 90 days post-adjournment. If enacted "
        f"via another bill, give that other bill's effective date.\n"
        f"4. codification reference (e.g. Public Law 2025 Chapter 645, Act 123, "
        f"Session Law). Empty string if not codified.\n"
        f"5. key_provisions in 1 to 2 short sentences. Mention specifics: penalty "
        f"ranges, scope (dual currency, online gaming, payment processors), AG "
        f"enforcement authority. If enacted_via another bill, describe the enacted "
        f"version's actual provisions, not the standalone version.\n"
        f"6. source_url. Prefer the official state legislature page for the "
        f"ENACTED bill (e.g. revisor.mn.gov SF4760 page if HF4437 was absorbed), "
        f"or governor press release, or major trade press (Gambling Insider, SBC "
        f"Americas, Lines.com, Gaming America).\n"
        f"7. is_sweepstakes_relevant. STRICT criteria: true ONLY if the bill "
        f"explicitly targets online sweepstakes games, social casino operators, "
        f"dual currency systems, prediction market wagers, online casino/gaming "
        f"providers using internet, or payment processors for those operators. "
        f"Set FALSE for: brick and mortar poker rooms, social card games (pinochle, "
        f"gin rummy, bridge, euchre, hearts, cribbage, dominoes, checkers, chess, "
        f"backgammon, pool, darts), pari mutuel horse racing, tribal compact "
        f"updates that do not touch sweepstakes, lottery rule tweaks not related "
        f"to sweepstakes, generic gambling code cleanup with no online sweepstakes "
        f"nexus.\n"
        f"8. enacted_via. Bill number of an OMNIBUS or COMPANION bill that absorbed "
        f"this bill's substance and was signed. Empty string if standalone or if no "
        f"enactment vehicle exists. Crucial example: MN HF4437 was absorbed into "
        f"SF4760, so for HF4437 set enacted_via=SF4760.\n\n"
        f"Return ONLY a single JSON object with these exact keys, no markdown, no "
        f"surrounding text:\n"
        f"{{\"status\":\"\",\"signing_date\":\"\",\"effective_date\":\"\","
        f"\"codification\":\"\",\"key_provisions\":\"\",\"source_url\":\"\","
        f"\"is_sweepstakes_relevant\":true,\"enacted_via\":\"\"}}"
    )

    text = _call_grounded(prompt)
    data = _extract_json(text)
    if not data:
        print(f"[grounding] bill {state} {bill_number}: no parseable JSON in response")
        return None

    out = {
        "status": str(data.get("status", "") or "").lower(),
        "signing_date": str(data.get("signing_date", "") or ""),
        "effective_date": str(data.get("effective_date", "") or ""),
        "codification": str(data.get("codification", "") or ""),
        "key_provisions": str(data.get("key_provisions", "") or ""),
        "source_url": str(data.get("source_url", "") or ""),
        "is_sweepstakes_relevant": bool(data.get("is_sweepstakes_relevant", True)),
        "enacted_via": str(data.get("enacted_via", "") or ""),
    }
    _cache_set(cache_key, out)
    return out


def ground_event_facts(headline: str, hint: str = "") -> dict | None:
    """Live-ground authoritative facts about a recent news event.

    Used for lawsuits, AG actions, court rulings, M&A, and operator moves
    where the static LegiScan flow doesn't cover.

    Returns dict with keys:
      verified_date         - YYYY-MM-DD or empty
      venue                 - court / agency / forum
      named_parties         - comma separated list
      summary               - 1-2 sentence authoritative summary
      authoritative_url     - best source URL
      is_sweepstakes_relevant - true / false
    """
    if not headline:
        return None

    cache_key = f"event:{re.sub(r'[^a-z0-9]+', '-', headline.lower())[:80]}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    today = _utc_date()
    prompt = (
        f"Today is {today}. Search the web for the most authoritative current "
        f"information about this news event.\n\n"
        f"Headline or claim: {headline}\n"
        f"Additional context: {hint or '(none)'}\n\n"
        f"Return each of:\n"
        f"1. verified_date in YYYY-MM-DD format. The actual event date (filing, "
        f"signing, ruling, announcement). NOT the article publish date.\n"
        f"2. venue (court name, agency, forum). Empty if not applicable.\n"
        f"3. named_parties involved.\n"
        f"4. summary in 1-2 sentences with specific facts (amounts, dates, scope).\n"
        f"5. authoritative_url. Prefer a high-authority outlet: Reuters, Bloomberg, "
        f"AP, WSJ, Politico, NYTimes, WaPo, official court docket, agency press "
        f"release, or sweepstakes-industry authorities (Gambling Insider, SBC "
        f"Americas, Lines.com).\n"
        f"6. is_sweepstakes_relevant true if event touches online sweepstakes, "
        f"social casino operators, dual currency models, online gaming, payment "
        f"processors, or prediction markets. Otherwise false.\n\n"
        f"Return ONLY a single JSON object with these exact keys, no markdown:\n"
        f"{{\"verified_date\":\"\",\"venue\":\"\",\"named_parties\":\"\","
        f"\"summary\":\"\",\"authoritative_url\":\"\","
        f"\"is_sweepstakes_relevant\":true}}"
    )

    text = _call_grounded(prompt)
    data = _extract_json(text)
    if not data:
        print(f"[grounding] event {headline[:60]}: no parseable JSON in response")
        return None

    out = {
        "verified_date": str(data.get("verified_date", "") or ""),
        "venue": str(data.get("venue", "") or ""),
        "named_parties": str(data.get("named_parties", "") or ""),
        "summary": str(data.get("summary", "") or ""),
        "authoritative_url": str(data.get("authoritative_url", "") or ""),
        "is_sweepstakes_relevant": bool(data.get("is_sweepstakes_relevant", True)),
    }
    _cache_set(cache_key, out)
    return out


def format_bill_authoritative(facts: dict) -> str:
    """Format a grounded bill facts dict into a one line AUTHORITATIVE summary."""
    if not facts:
        return ""
    parts: list[str] = []
    status = (facts.get("status") or "").lower()
    if status == "signed":
        sd = facts.get("signing_date") or ""
        parts.append(f"Signed into law{' on ' + sd if sd else ''}.")
    elif status == "vetoed":
        parts.append("Vetoed by the governor.")
    elif status == "dead":
        parts.append("Bill died in the legislature.")
    elif status == "pending":
        parts.append("Pending in the legislature.")

    eff = facts.get("effective_date") or ""
    if eff:
        parts.append(f"Effective {eff}.")

    cod = facts.get("codification") or ""
    if cod:
        parts.append(f"Codified as {cod}.")

    kp = facts.get("key_provisions") or ""
    if kp:
        parts.append(kp.strip())

    enacted_via = facts.get("enacted_via") or ""
    if enacted_via:
        parts.append(f"Provisions enacted via {enacted_via}.")

    return " ".join(p for p in parts if p).strip()
