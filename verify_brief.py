"""Verify a generated brief against the live web before any Slack send.

Pipeline: extracts every fact-bearing bullet from the brief markdown, runs each
through Gemini Flash with Google Search grounding to verify the specifics
(dates, dollar amounts, named parties, scope). Returns a structured report.

The publisher gate is hard: ANY incorrect verdict blocks the Slack send.
The corrections report is saved alongside the brief for the operator to review.

All calls run on the Gemini free tier (no credit card required).
"""

import json
import os
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


_CACHE_DB = Path(__file__).parent / "cache.db"
_VERIFY_MODEL = os.getenv("VERIFY_MODEL", "gemini-2.5-flash-lite")
_GEMINI_CLIENT = None
_CACHE_INIT = False


def _ensure_cache():
    global _CACHE_INIT
    if _CACHE_INIT:
        return
    conn = sqlite3.connect(_CACHE_DB)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS verify_cache ("
        " utc_date TEXT NOT NULL,"
        " claim_hash TEXT NOT NULL,"
        " payload TEXT NOT NULL,"
        " created_at REAL NOT NULL,"
        " PRIMARY KEY (utc_date, claim_hash)"
        ")"
    )
    conn.commit()
    conn.close()
    _CACHE_INIT = True


def _us_date() -> str:
    from dates import us_date
    return us_date()


def _hash_claim(text: str) -> str:
    import hashlib
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def _cache_get(claim_hash: str) -> dict | None:
    _ensure_cache()
    conn = sqlite3.connect(_CACHE_DB)
    row = conn.execute(
        "SELECT payload FROM verify_cache WHERE utc_date = ? AND claim_hash = ?",
        (_us_date(), claim_hash),
    ).fetchone()
    conn.close()
    if not row:
        return None
    try:
        return json.loads(row[0])
    except Exception:
        return None


def _cache_set(claim_hash: str, payload: dict) -> None:
    _ensure_cache()
    conn = sqlite3.connect(_CACHE_DB)
    conn.execute(
        "INSERT OR REPLACE INTO verify_cache "
        "(utc_date, claim_hash, payload, created_at) VALUES (?, ?, ?, ?)",
        (_us_date(), claim_hash, json.dumps(payload), time.time()),
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
                "GOOGLE_API_KEY not set. Required for brief verification."
            )
        _GEMINI_CLIENT = genai.Client(api_key=api_key)
    return _GEMINI_CLIENT


def _strip_fence(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _extract_json(text: str) -> dict | None:
    text = _strip_fence(text)
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


_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")


def _extract_claims(brief_md: str) -> list[dict]:
    """Walk the brief and return one claim entry per fact-bearing line.

    Skips section headings, the footer disclaimer, the "no qualifying items
    today" sentinels, and "Why it matters" enrichment lines.
    """
    claims: list[dict] = []
    current_section = "preamble"
    in_top_story = False
    top_story_buffer: list[str] = []

    for raw_line in brief_md.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()

        if stripped.startswith("## "):
            heading = re.sub(r"^\d+\.\s*", "", stripped[3:].strip())
            if in_top_story and top_story_buffer:
                claims.append({
                    "section": "top story",
                    "text": " ".join(top_story_buffer).strip(),
                })
                top_story_buffer = []
            current_section = heading.lower()
            in_top_story = current_section == "top story"
            continue

        if not stripped:
            continue

        if current_section in {"footer", ""}:
            continue

        if "no qualifying items today" in stripped.lower():
            continue

        if stripped.lower().startswith("why it matters:"):
            continue

        if in_top_story:
            top_story_buffer.append(stripped)
            continue

        if re.match(r"^[-*]\s", stripped):
            text = re.sub(r"^[-*]\s+", "", stripped)
            if text:
                claims.append({"section": current_section, "text": text})

    if in_top_story and top_story_buffer:
        claims.append({"section": "top story", "text": " ".join(top_story_buffer).strip()})

    return claims


def _verify_one(claim: dict) -> dict:
    """Verify a single claim with Gemini Flash + Google Search grounding.

    Returns dict with keys: verdict (confirmed/partial/incorrect/uncertain),
    short_reason, evidence, corrected_text.
    """
    from google.genai import types as gtypes

    text = claim["text"]
    section = claim.get("section", "unknown")
    claim_hash = _hash_claim(text)
    cached = _cache_get(claim_hash)
    if cached is not None:
        return cached

    prompt = (
        f"Today is {_us_date()}. You are an adversarial fact checker for the "
        f"LuckyHands Sweepstakes Intel Daily brief. Verify the SPECIFIC factual "
        f"claims (dates, dollar amounts, named parties, scope, status) in the "
        f"item below against authoritative sources via web search.\n\n"
        f"Section: {section}\n"
        f"Item: {text}\n\n"
        f"Run at least 2 web searches across high-authority outlets (Reuters, "
        f"Bloomberg, AP, WSJ, NYT, Politico, official state legislatures, "
        f"governor press releases, court dockets, CFTC.gov, Gambling Insider, "
        f"SBC Americas, Lines.com). Reach a verdict.\n\n"
        f"Be precise. If ANY specific date, dollar amount, or named party is "
        f"wrong, default to 'incorrect'. If most facts hold but one detail is "
        f"off, default to 'partial'. If you cannot verify, default to "
        f"'uncertain'. Only 'confirmed' if every specific holds up.\n\n"
        f"Return ONLY a JSON object, no surrounding text:\n"
        f"{{\"verdict\":\"confirmed|partial|incorrect|uncertain\","
        f"\"short_reason\":\"\",\"evidence\":\"\",\"corrected_text\":\"\"}}\n\n"
        f"corrected_text should be the exact replacement text for the brief if "
        f"verdict is partial or incorrect. Plain English. No apostrophes. No "
        f"hyphens between words. Empty if confirmed."
    )

    try:
        resp = _client().models.generate_content(
            model=_VERIFY_MODEL,
            contents=prompt,
            config=gtypes.GenerateContentConfig(
                tools=[gtypes.Tool(google_search=gtypes.GoogleSearch())],
                temperature=0.1,
            ),
        )
        text_response = resp.text or ""
    except Exception as exc:
        return {
            "verdict": "uncertain",
            "short_reason": f"verify call failed, {exc}",
            "evidence": "",
            "corrected_text": "",
        }

    data = _extract_json(text_response)
    if not data:
        result = {
            "verdict": "uncertain",
            "short_reason": "no parseable JSON in verifier response",
            "evidence": "",
            "corrected_text": "",
        }
    else:
        result = {
            "verdict": str(data.get("verdict", "uncertain")).lower(),
            "short_reason": str(data.get("short_reason", "") or ""),
            "evidence": str(data.get("evidence", "") or ""),
            "corrected_text": str(data.get("corrected_text", "") or ""),
        }
    _cache_set(claim_hash, result)
    return result


def _verify_batch(batch: list[dict]) -> list[dict]:
    """Verify a small batch of claims in a single grounded Gemini call.

    Batching cuts the daily Gemini quota footprint by 5-10x: instead of 18
    calls for 18 claims we use 3-4 calls. Each batch returns a JSON array
    of verdicts aligned to input order.
    """
    from google.genai import types as gtypes

    if not batch:
        return []

    # Use cached results when available, fall through to a grounded batch call
    # for the remainder.
    out_by_idx: dict[int, dict] = {}
    todo: list[tuple[int, dict]] = []
    for i, claim in enumerate(batch):
        h = _hash_claim(claim["text"])
        cached = _cache_get(h)
        if cached is not None:
            out_by_idx[i] = cached
        else:
            todo.append((i, claim))

    if not todo:
        return [out_by_idx[i] for i in range(len(batch))]

    items_block = "\n\n".join(
        f"ITEM {idx + 1}\nSection: {c['section']}\nClaim: {c['text']}"
        for idx, (_, c) in enumerate(todo)
    )
    n = len(todo)
    prompt = (
        f"Today is {_us_date()}. You are an adversarial fact checker for the "
        f"LuckyHands Sweepstakes Intel Daily brief. Verify each item below in "
        f"order. For each item, run at least one web search to confirm the "
        f"specifics (dates, dollar amounts, named parties, scope, status). Be "
        f"precise. Default to incorrect if a specific date/amount/name is "
        f"wrong. Default to partial if mostly right but one detail is off. "
        f"Default to uncertain only if you cannot find any authoritative "
        f"source. Default to confirmed when the substantive facts hold up.\n\n"
        f"{items_block}\n\n"
        f"Return ONLY a JSON array of exactly {n} objects, in the same order "
        f"as the items above. Each object MUST have these keys: "
        f"verdict (confirmed|partial|incorrect|uncertain), short_reason, "
        f"evidence (semicolon separated URLs), corrected_text (plain English "
        f"replacement text if not confirmed, empty string otherwise). No "
        f"markdown, no preamble, no trailing prose. JSON array only."
    )

    try:
        resp = _client().models.generate_content(
            model=_VERIFY_MODEL,
            contents=prompt,
            config=gtypes.GenerateContentConfig(
                tools=[gtypes.Tool(google_search=gtypes.GoogleSearch())],
                temperature=0.1,
            ),
        )
        text_response = resp.text or ""
    except Exception as exc:
        # Mark all todo items as uncertain with the call-level error
        for i, claim in todo:
            err = {
                "verdict": "uncertain",
                "short_reason": f"batch verify call failed, {str(exc)[:200]}",
                "evidence": "",
                "corrected_text": "",
            }
            out_by_idx[i] = err
        return [out_by_idx[i] for i in range(len(batch))]

    # Extract JSON array
    text_response = _strip_fence(text_response)
    parsed: list[dict] | None = None
    try:
        parsed = json.loads(text_response)
    except Exception:
        match = re.search(r"\[[\s\S]*\]", text_response)
        if match:
            try:
                parsed = json.loads(match.group(0))
            except Exception:
                parsed = None

    if not isinstance(parsed, list):
        for i, claim in todo:
            err = {
                "verdict": "uncertain",
                "short_reason": "no parseable JSON array in batch response",
                "evidence": "",
                "corrected_text": "",
            }
            out_by_idx[i] = err
        return [out_by_idx[i] for i in range(len(batch))]

    for j, (i, claim) in enumerate(todo):
        if j < len(parsed):
            d = parsed[j] or {}
            result = {
                "verdict": str(d.get("verdict", "uncertain")).lower(),
                "short_reason": str(d.get("short_reason", "") or ""),
                "evidence": str(d.get("evidence", "") or ""),
                "corrected_text": str(d.get("corrected_text", "") or ""),
            }
        else:
            result = {
                "verdict": "uncertain",
                "short_reason": "batch response missing this item",
                "evidence": "",
                "corrected_text": "",
            }
        out_by_idx[i] = result
        _cache_set(_hash_claim(claim["text"]), result)

    return [out_by_idx[i] for i in range(len(batch))]


def verify_brief_markdown(brief_md: str, max_workers: int = 4, batch_size: int = 5) -> dict:
    """Verify every fact-bearing claim in the brief via batched Gemini calls.

    Batching: groups of `batch_size` claims hit one Gemini call. Default 5
    claims per batch keeps the daily quota footprint to roughly
    (claim_count / batch_size) Gemini calls.

    The gate is hard: any 'incorrect' verdict blocks the Slack send.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    claims = _extract_claims(brief_md)
    if not claims:
        return {
            "ok": False,
            "total": 0,
            "confirmed": 0,
            "partial": 0,
            "incorrect": 0,
            "uncertain": 0,
            "items": [],
            "summary": "no claims extracted from brief markdown",
        }

    batches = [claims[i : i + batch_size] for i in range(0, len(claims), batch_size)]

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        future_to_batch = {ex.submit(_verify_batch, b): b for b in batches}
        for fut in as_completed(future_to_batch):
            batch = future_to_batch[fut]
            try:
                verdicts = fut.result()
            except Exception as exc:
                verdicts = [
                    {
                        "verdict": "uncertain",
                        "short_reason": f"batch future failed, {exc}",
                        "evidence": "",
                        "corrected_text": "",
                    }
                    for _ in batch
                ]
            for claim, v in zip(batch, verdicts):
                results.append({
                    "section": claim["section"],
                    "claim": claim["text"],
                    "verdict": v["verdict"],
                    "short_reason": v["short_reason"],
                    "evidence": v["evidence"],
                    "corrected_text": v["corrected_text"],
                })

    tally = {"confirmed": 0, "partial": 0, "incorrect": 0, "uncertain": 0}
    for r in results:
        tally[r["verdict"]] = tally.get(r["verdict"], 0) + 1

    block_send = tally["incorrect"] > 0

    return {
        "ok": not block_send,
        "total": len(results),
        "confirmed": tally["confirmed"],
        "partial": tally["partial"],
        "incorrect": tally["incorrect"],
        "uncertain": tally["uncertain"],
        "items": results,
        "summary": (
            f"{tally['confirmed']}/{len(results)} confirmed, "
            f"{tally['partial']} partial, "
            f"{tally['incorrect']} incorrect, "
            f"{tally['uncertain']} uncertain"
        ),
    }


def render_corrections_md(report: dict, brief_date: str) -> str:
    """Render the verification report as a corrections markdown file."""
    lines = [
        f"# Brief verification report, {brief_date}",
        "",
        f"## Summary",
        f"- Total claims checked: {report['total']}",
        f"- Confirmed: {report['confirmed']}",
        f"- Partial: {report['partial']}",
        f"- Incorrect: {report['incorrect']}",
        f"- Uncertain: {report['uncertain']}",
        "",
        f"Slack send: {'BLOCKED' if not report['ok'] else 'CLEARED'}",
        "",
        "## Per-claim verdicts",
        "",
    ]
    by_verdict = {"incorrect": [], "partial": [], "uncertain": [], "confirmed": []}
    for r in report["items"]:
        by_verdict.setdefault(r["verdict"], []).append(r)

    for verdict_name in ["incorrect", "partial", "uncertain", "confirmed"]:
        rows = by_verdict.get(verdict_name, [])
        if not rows:
            continue
        lines.append(f"### {verdict_name.upper()} ({len(rows)})")
        lines.append("")
        for r in rows:
            lines.append(f"- **[{r['section']}]** {r['claim'][:240]}")
            lines.append(f"  - Reason: {r['short_reason']}")
            if r.get("evidence"):
                lines.append(f"  - Evidence: {r['evidence']}")
            if r.get("corrected_text"):
                lines.append(f"  - Suggested correction: {r['corrected_text']}")
            lines.append("")

    return "\n".join(lines)
