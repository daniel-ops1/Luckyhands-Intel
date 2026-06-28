"""Interactive publisher for the LuckyHands Intel Daily brief.

Flow:
  1. Locate the latest brief markdown in output/
  2. Verify every fact-bearing claim against the live web via Gemini Flash + Google Search
  3. Show the brief and the verify report to the operator in the terminal
  4. Prompt: approve, cancel, or improve
       y = post to Slack
       n = cancel, do nothing
       i = apply the verify report corrections via Gemini, re-verify, re-prompt
  5. Repeat until the operator approves or cancels

The improve loop iterates without re-running the slow research pipeline, so
corrections cycles are fast (a few seconds per pass).
"""

import os
import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


PROJECT_DIR = Path(__file__).parent
OUTPUT_DIR = PROJECT_DIR / "output"


# ---------- ANSI colors ----------

class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    UNDER = "\033[4m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    GREY = "\033[90m"


def hr(char: str = "=", color: str = C.CYAN) -> str:
    return f"{color}{char * 70}{C.RESET}"


# ---------- brief discovery + display ----------

def find_latest_brief_md() -> Path | None:
    """Prefer a workflow-assembled brief, fall back to the pipeline brief_md state if absent."""
    if not OUTPUT_DIR.exists():
        return None
    candidates: list[Path] = []
    candidates += sorted(OUTPUT_DIR.glob("brief_corrected_*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    candidates += sorted(OUTPUT_DIR.glob("brief_pipeline_*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    candidates += sorted(OUTPUT_DIR.glob("brief_workflow_*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def pretty_markdown(md: str, width: int = 100) -> str:
    """Light terminal-friendly markdown formatter."""
    lines: list[str] = []
    for raw in md.splitlines():
        line = raw.rstrip()
        if line.startswith("# "):
            lines.append(f"\n{C.BOLD}{C.CYAN}{line[2:].strip()}{C.RESET}")
            lines.append(f"{C.CYAN}{'=' * min(len(line[2:].strip()), width)}{C.RESET}")
        elif line.startswith("## "):
            lines.append(f"\n{C.BOLD}{C.YELLOW}{line[3:].strip()}{C.RESET}")
            lines.append(f"{C.YELLOW}{'-' * min(len(line[3:].strip()), width)}{C.RESET}")
        elif line.startswith("### "):
            lines.append(f"\n{C.BOLD}{line[4:].strip()}{C.RESET}")
        elif re.match(r"^\s*- ", line) or re.match(r"^\s*\* ", line):
            content = re.sub(r"^\s*[-*]\s+", "", line)
            content = re.sub(r"\*\*([^*]+)\*\*", f"{C.BOLD}\\1{C.RESET}", content)
            content = re.sub(
                r"\[([^\]]+)\]\((https?://[^)]+)\)",
                f"{C.CYAN}[\\1]{C.RESET}{C.GREY}(\\2){C.RESET}",
                content,
            )
            lines.append(f"  • {content}")
        elif line.strip().lower().startswith("why it matters:"):
            content = re.sub(r"^\s*", "", line)
            lines.append(f"    {C.GREEN}{content}{C.RESET}")
        elif line.strip():
            content = re.sub(r"\*\*([^*]+)\*\*", f"{C.BOLD}\\1{C.RESET}", line)
            content = re.sub(
                r"\[([^\]]+)\]\((https?://[^)]+)\)",
                f"{C.CYAN}[\\1]{C.RESET}{C.GREY}(\\2){C.RESET}",
                content,
            )
            lines.append(content)
        else:
            lines.append("")
    return "\n".join(lines)


def show_brief(brief_md: str, date_str: str) -> None:
    print(hr())
    print(f"{C.BOLD}{C.CYAN}  LUCKYHANDS INTEL DAILY  ·  {date_str}{C.RESET}")
    print(hr())
    print(pretty_markdown(brief_md))
    print()


def show_verify_report(report: dict, date_str: str) -> None:
    print(hr("=", C.YELLOW))
    print(f"{C.BOLD}{C.YELLOW}  VERIFY REPORT  ·  {date_str}{C.RESET}")
    print(hr("=", C.YELLOW))
    s = report["summary"]
    incorrect = report.get("incorrect", 0)
    partial = report.get("partial", 0)
    uncertain = report.get("uncertain", 0)
    overall_color = C.GREEN if incorrect == 0 and partial <= 2 else C.RED
    print(f"  Tally: {overall_color}{s}{C.RESET}")
    print()

    by_verdict: dict[str, list[dict]] = {}
    for r in report["items"]:
        by_verdict.setdefault(r["verdict"], []).append(r)

    label_color = {
        "incorrect": C.RED,
        "partial": C.YELLOW,
        "uncertain": C.MAGENTA,
        "confirmed": C.GREEN,
    }
    for verdict in ("incorrect", "partial", "uncertain", "confirmed"):
        rows = by_verdict.get(verdict, [])
        if not rows:
            continue
        col = label_color.get(verdict, C.RESET)
        print(f"  {col}{C.BOLD}{verdict.upper()} ({len(rows)}){C.RESET}")
        # Only show details for non-confirmed by default
        if verdict == "confirmed":
            for r in rows:
                print(f"    {C.GREEN}OK{C.RESET}  [{r['section']}] {r['claim'][:140]}")
        else:
            for r in rows:
                print(f"    {col}-{C.RESET}  [{r['section']}] {r['claim'][:160]}")
                if r.get("short_reason"):
                    print(f"        {C.GREY}why: {r['short_reason'][:240]}{C.RESET}")
                if r.get("corrected_text"):
                    print(f"        {C.CYAN}fix: {r['corrected_text'][:300]}{C.RESET}")
        print()


# ---------- prompt ----------

def prompt_choice() -> str:
    print(hr("=", C.CYAN))
    print(f"  {C.BOLD}Approve this brief for Slack?{C.RESET}")
    print(f"  {C.GREEN}y{C.RESET}es     post the brief to Slack now")
    print(f"  {C.RED}n{C.RESET}o      cancel, do not send")
    print(f"  {C.YELLOW}i{C.RESET}mprove apply the verify report corrections via Gemini, re-verify, re-prompt")
    print(hr("=", C.CYAN))
    while True:
        try:
            choice = input(f"  {C.BOLD}choice >{C.RESET} ").strip().lower()
        except EOFError:
            return "no"
        if choice in {"y", "yes"}:
            return "yes"
        if choice in {"n", "no", "q", "quit", "cancel"}:
            return "no"
        if choice in {"i", "improve", "fix"}:
            return "improve"
        print(f"  {C.YELLOW}Please type y, n, or i{C.RESET}")


# ---------- corrections agent ----------

def apply_corrections(brief_md: str, verify_report_md: str) -> str | None:
    """Use Gemini Flash to apply the verify report's corrections to the brief."""
    try:
        from google import genai
        from google.genai import types as gtypes
    except Exception as exc:
        print(f"{C.RED}google.genai unavailable, {exc}{C.RESET}")
        return None

    api_key = os.getenv("GOOGLE_API_KEY", "").strip()
    if not api_key:
        print(f"{C.RED}GOOGLE_API_KEY not set, cannot run improve loop{C.RESET}")
        return None

    client = genai.Client(api_key=api_key)
    prompt = (
        "You are the editor of the LuckyHands Sweepstakes Intel Daily brief.\n\n"
        "Apply ONLY the corrections in the verify report to the brief. Preserve all "
        "confirmed content verbatim. Preserve the 9-section template structure. "
        "Preserve every Why it matters line. Do NOT remove items unless the verify "
        "report explicitly says to drop them.\n\n"
        "Voice rules: plain English, short sentences, no apostrophes, no hyphens "
        "between words, no em dashes. Stake.us style domain dots are fine.\n\n"
        "CURRENT BRIEF:\n"
        f"{brief_md}\n\n"
        "VERIFY REPORT WITH SUGGESTED FIXES:\n"
        f"{verify_report_md}\n\n"
        "Return ONLY the corrected brief in plain markdown. No code fences. No "
        "preamble. Start with the # LuckyHands Intel Daily heading."
    )

    try:
        resp = client.models.generate_content(
            model=os.getenv("CORRECTION_MODEL", "gemini-2.5-flash"),
            contents=prompt,
            config=gtypes.GenerateContentConfig(temperature=0.1),
        )
        text = resp.text or ""
    except Exception as exc:
        print(f"{C.RED}Correction call failed, {exc}{C.RESET}")
        return None

    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:markdown|md)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text or None


# ---------- main ----------

def main() -> int:
    from dates import us_date_long, us_date_slug
    from verify_brief import render_corrections_md, verify_brief_markdown
    from agents import enforce_voice_rules

    brief_path = find_latest_brief_md()
    if brief_path is None:
        print(
            f"{C.RED}No brief markdown found in {OUTPUT_DIR}.{C.RESET}\n"
            f"Run the pipeline first via ./intel_daily.sh (which generates a "
            f"workflow brief or pipeline brief), then re-run python intel_publish.py."
        )
        return 1

    brief_md = brief_path.read_text(encoding="utf-8")
    print(f"{C.GREY}Loaded brief: {brief_path}{C.RESET}")

    pass_idx = 0
    while True:
        pass_idx += 1
        date_str = us_date_long()

        # Render the brief
        show_brief(brief_md, date_str)

        # Verify the brief
        print(hr("=", C.YELLOW))
        print(f"  {C.BOLD}Verifying brief against the live web (pass {pass_idx})...{C.RESET}")
        print(hr("=", C.YELLOW))
        start = time.time()
        report = verify_brief_markdown(brief_md, max_workers=6)
        elapsed = time.time() - start
        print(f"  {C.GREY}Verify done in {elapsed:.1f}s{C.RESET}\n")

        # Save the verify report
        verify_md = render_corrections_md(report, date_str)
        slug = us_date_slug()
        verify_path = OUTPUT_DIR / f"verify_report_{slug}_pass{pass_idx}.md"
        verify_path.write_text(verify_md, encoding="utf-8")
        print(f"{C.GREY}Saved verify report to {verify_path}{C.RESET}\n")

        # Show the verify summary
        show_verify_report(report, date_str)

        # Prompt
        choice = prompt_choice()

        if choice == "yes":
            try:
                from slack import SLACK_WEBHOOK_URL, post_to_slack
            except Exception as exc:
                print(f"{C.RED}slack module import failed, {exc}{C.RESET}")
                return 2
            if not SLACK_WEBHOOK_URL:
                print(f"{C.RED}SLACK_WEBHOOK_URL not set in .env{C.RESET}")
                return 3
            cleaned = enforce_voice_rules(brief_md)
            from agents import _current_issue_number
            issue_num = _current_issue_number()
            ok, detail = post_to_slack(cleaned, date_str, issue=issue_num)
            if ok:
                print(f"\n{C.GREEN}{C.BOLD}Posted to Slack.{C.RESET}")
                # Save a final approved copy
                approved_path = OUTPUT_DIR / f"brief_approved_{slug}.md"
                approved_path.write_text(brief_md, encoding="utf-8")
                print(f"{C.GREY}Approved brief archived to {approved_path}{C.RESET}")
                return 0
            print(f"\n{C.RED}Slack post failed, {detail}{C.RESET}")
            return 4

        if choice == "no":
            print(f"\n{C.YELLOW}Cancelled. Brief NOT sent to Slack.{C.RESET}")
            print(f"  Brief file:  {brief_path}")
            print(f"  Verify file: {verify_path}")
            return 0

        # improve
        if report["incorrect"] == 0 and report["partial"] == 0 and report["uncertain"] == 0:
            print(f"\n{C.GREEN}Nothing to improve, brief is already clean.{C.RESET}")
            continue

        print(f"\n  {C.YELLOW}Applying corrections via Gemini Flash...{C.RESET}")
        start = time.time()
        new_brief = apply_corrections(brief_md, verify_md)
        if not new_brief:
            print(f"{C.RED}Correction step returned empty. Keeping current brief.{C.RESET}")
            continue
        elapsed = time.time() - start
        print(f"  {C.GREY}Corrections applied in {elapsed:.1f}s{C.RESET}")
        brief_md = new_brief
        ts = int(time.time())
        new_path = OUTPUT_DIR / f"brief_corrected_{slug}_pass{pass_idx}_{ts}.md"
        new_path.write_text(brief_md, encoding="utf-8")
        brief_path = new_path
        print(f"  {C.GREY}Saved corrected brief to {new_path}{C.RESET}\n")
        # Loop back to verify + prompt


if __name__ == "__main__":
    sys.exit(main())
