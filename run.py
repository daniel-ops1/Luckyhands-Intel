import asyncio
import os
import sys
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

from config import (
    APP_NAME,
    DEFAULT_USER_ID,
    GOOGLE_API_KEY,
    LOOKBACK_WINDOW,
    RECIPIENT_EMAIL,
)
from render import render_email, write_output, write_qa


def _date_str() -> str:
    from dates import us_date_long
    return us_date_long()


def _issue_number(success: bool) -> int:
    """Return the issue number for this run.

    Production: maintained by .issue_counter, incremented on success.
    Test override: set INTEL_DAILY_ISSUE_OVERRIDE to use a fixed issue (e.g. 0
    for a smoke test) without bumping the persistent counter.
    """
    override = os.getenv("INTEL_DAILY_ISSUE_OVERRIDE", "").strip()
    if override != "":
        try:
            return int(override)
        except ValueError:
            pass

    state_file = Path(__file__).parent / ".issue_counter"
    current = 0
    if state_file.exists():
        try:
            current = int(state_file.read_text().strip())
        except ValueError:
            current = 0
    if success:
        current += 1
        state_file.write_text(str(current))
    return current


async def _run_pipeline(date_str: str) -> tuple[str, str, dict]:
    from config import (
        EDITOR_BACKEND,
        GEMINI_EDITOR_MODEL,
        OLLAMA_BASE_URL,
        OLLAMA_EDITOR_MODEL,
        OLLAMA_RESEARCHER_MODEL,
        RESEARCHER_BACKEND,
    )

    needs_gemini = EDITOR_BACKEND == "gemini" or RESEARCHER_BACKEND == "gemini"
    needs_ollama = EDITOR_BACKEND == "ollama" or RESEARCHER_BACKEND == "ollama"

    if needs_gemini and not GOOGLE_API_KEY:
        raise RuntimeError(
            "Gemini editor or researcher requested but GOOGLE_API_KEY is not set. "
            "Get a free key at https://aistudio.google.com/apikey and put it in .env"
        )

    if needs_ollama:
        import httpx

        try:
            httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3.0).raise_for_status()
        except Exception as exc:
            raise RuntimeError(
                f"Ollama is not reachable at {OLLAMA_BASE_URL}. "
                f"Install Ollama from https://ollama.com, start it, and pull the models. "
                f"`ollama pull {OLLAMA_RESEARCHER_MODEL}` "
                f"`ollama pull {OLLAMA_EDITOR_MODEL}`. "
                f"Underlying error, {exc}"
            )

    researcher_label = OLLAMA_RESEARCHER_MODEL if RESEARCHER_BACKEND == "ollama" else GEMINI_EDITOR_MODEL
    editor_label = OLLAMA_EDITOR_MODEL if EDITOR_BACKEND == "ollama" else GEMINI_EDITOR_MODEL
    print(f"researcher backend={RESEARCHER_BACKEND}/{researcher_label}, editor backend={EDITOR_BACKEND}/{editor_label}")

    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    from agents import newsletter_pipeline

    session_service = InMemorySessionService()
    session = await session_service.create_session(
        app_name=APP_NAME,
        user_id=DEFAULT_USER_ID,
        session_id=f"run_{date_str.replace(', ', '_').replace(' ', '_')}",
    )

    runner = Runner(
        agent=newsletter_pipeline,
        app_name=APP_NAME,
        session_service=session_service,
    )

    seed_message = types.Content(
        role="user",
        parts=[
            types.Part(
                text=(
                    f"Today is {date_str}. Lookback window {LOOKBACK_WINDOW}. "
                    "Research and assemble the LuckyHands Intel Daily brief for today."
                )
            )
        ],
    )

    print("running ADK pipeline. parallel researchers, then editor, then verifier.")
    last_author = None
    async for event in runner.run_async(
        user_id=DEFAULT_USER_ID,
        session_id=session.id,
        new_message=seed_message,
    ):
        if event.author != last_author:
            print(f"  step, {event.author}")
            last_author = event.author

    final = await session_service.get_session(
        app_name=APP_NAME,
        user_id=DEFAULT_USER_ID,
        session_id=session.id,
    )
    state = final.state if final else {}
    brief_md = state.get("brief_md", "")
    verification = state.get("verification_note", "")

    if not brief_md:
        regulatory = state.get("regulatory_findings", "no qualifying items today")
        competitor = state.get("competitor_findings", "no qualifying items today")
        market = state.get("market_findings", "no qualifying items today")
        brief_md = (
            f"# LuckyHands Intel Daily, {date_str}\n\n"
            f"## Top story\n\nResearch did not surface a single top story today.\n\n"
            f"## Regulatory and legal\n\n{regulatory}\n\n"
            f"## Competitor moves\n\n{competitor}\n\n"
            f"## Market and product signals\n\n{market}\n\n"
            f"## On our radar\n\nno qualifying items today\n\n"
            f"## Footer\n\nReply to this thread with corrections. They train the next brief.\n"
            "Not legal advice. Verify any regulatory item with counsel before acting on it.\n"
        )
    findings = {
        k: state.get(k, "") for k in (
            "regulatory_findings",
            "competitor_findings",
            "market_findings",
            "legiscan_findings",
            "rss_findings",
            "federal_register_findings",
            "courtlistener_findings",
            "sentiment_findings",
        )
    }
    return brief_md, verification, findings


def _subject_from_md(brief_md: str, date_str: str) -> str:
    lines = brief_md.splitlines()
    in_top = False
    headline = ""
    for line in lines:
        if line.strip().startswith("## Top story"):
            in_top = True
            continue
        if in_top and line.strip().startswith("##"):
            break
        if in_top and line.strip():
            headline = line.strip()
            break
    headline = headline.split(". ")[0]
    if len(headline) > 70:
        headline = headline[:67] + "..."
    return f"LH Intel, {date_str}, {headline}" if headline else f"LH Intel, {date_str}"


def cmd_build(open_after: bool = False, send_after: bool = False) -> None:
    import time

    date_str = _date_str()
    last_exc = None
    brief_md = verification = None
    findings = {}
    for attempt in range(5):
        try:
            brief_md, verification, findings = asyncio.run(_run_pipeline(date_str))
            break
        except BaseException as exc:
            msg = repr(exc) + " " + str(exc)
            transient = "503" in msg and "UNAVAILABLE" in msg
            if transient and attempt < 4:
                wait = 2 ** attempt * 5
                print(f"gemini returned 503, retrying in {wait}s (attempt {attempt + 1}/5)")
                time.sleep(wait)
                last_exc = exc
                continue
            raise
    if brief_md is None:
        raise last_exc if last_exc else RuntimeError("pipeline failed after 5 attempts")

    from agents import _sanitize_brief, enforce_voice_rules
    from dates import us_date_slug

    sanitized_md, _sanitize_warnings = _sanitize_brief(brief_md, findings)
    cleaned_md = enforce_voice_rules(sanitized_md)

    issue = _issue_number(success=True)
    html = render_email(cleaned_md, date_str, issue)
    out_path = write_output(html, date_str)
    qa_path = write_qa(verification, cleaned_md, date_str)
    md_path = out_path.parent / f"brief_pipeline_{us_date_slug()}.md"
    md_path.write_text(cleaned_md, encoding="utf-8")
    print(f"wrote {out_path}")
    print(f"wrote {qa_path}")
    print(f"wrote {md_path}")

    if open_after:
        url = f"file://{out_path.resolve()}"
        print(f"opening {url} in browser")
        webbrowser.open(url)

    if send_after:
        from send import send_email

        subject = _subject_from_md(brief_md, date_str)
        send_email(subject, html)


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "preview"
    if cmd == "build":
        cmd_build(open_after=False, send_after=False)
    elif cmd == "preview":
        cmd_build(open_after=True, send_after=False)
    elif cmd == "send":
        cmd_build(open_after=False, send_after=True)
    elif cmd == "slack":
        os.environ["INTEL_DAILY_NO_BROWSER"] = "1"
        cmd_build(open_after=False, send_after=False)
    else:
        print("usage, python run.py [build|preview|send|slack]")
        print("  build    run ADK pipeline, write HTML, no browser, no email")
        print("  preview  run ADK pipeline, write HTML, open in browser, no email")
        print("  send     run ADK pipeline, write HTML, send email to recipient")
        print("  slack    run ADK pipeline, post brief to Slack channel, no browser, no email")
        sys.exit(1)


if __name__ == "__main__":
    main()
