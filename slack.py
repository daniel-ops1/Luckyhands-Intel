import os
import re

import httpx
from dotenv import load_dotenv

load_dotenv()


SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
SLACK_CHANNEL = os.getenv("SLACK_CHANNEL", "")
SLACK_USERNAME = os.getenv("SLACK_USERNAME", "LuckyHands Intel Daily")
SLACK_ICON_EMOJI = os.getenv("SLACK_ICON_EMOJI", ":newspaper:")


def _md_link_to_slack(text: str) -> str:
    return re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"<\2|\1>", text)


def _md_bold_to_slack(text: str) -> str:
    text = re.sub(r"\*\*([^*]+)\*\*", r"*\1*", text)
    return text


def _to_mrkdwn(text: str) -> str:
    text = _md_link_to_slack(text)
    text = _md_bold_to_slack(text)
    return text


def _is_footer_heading(heading: str | None) -> bool:
    if not heading:
        return False
    return "footer" in heading.lower()


def _et_timestamp() -> str:
    """Production timestamp in ET, e.g. 'Sun, June 29 2026 at 4:12am ET'."""
    try:
        from dates import US_TZ
        from datetime import datetime
        now = datetime.now(tz=US_TZ)
        return now.strftime("%a, %B %d %Y at %-I:%M%p ET")
    except Exception:
        from datetime import datetime
        return datetime.now().strftime("%a, %B %d %Y at %-I:%M%p")


def md_to_blocks(brief_md: str, date_str: str, issue: int | str = "") -> list[dict]:
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"LuckyHands Intel Daily  ·  {date_str}"},
        }
    ]
    issue_label = ""
    produced_at = _et_timestamp()
    if issue == 0 or issue == "0":
        issue_label = (
            f"*Issue 0 of LuckyHands Daily Intel* (test)  ·  Produced {produced_at}"
        )
    elif issue:
        issue_label = (
            f"*Issue {issue} of LuckyHands Daily Intel*  ·  Produced {produced_at}"
        )
    if issue_label:
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": issue_label}],
            }
        )
    blocks.append({"type": "divider"})

    lines = brief_md.split("\n")
    section_lines: list[str] = []
    current_heading: str | None = None
    footer_text_parts: list[str] = []

    def flush():
        nonlocal section_lines, current_heading, footer_text_parts
        if current_heading is None and not section_lines:
            return

        if _is_footer_heading(current_heading):
            footer_text_parts.extend(l.strip() for l in section_lines if l.strip())
            section_lines = []
            current_heading = None
            return

        if current_heading:
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*{current_heading}*"},
                }
            )
        body_lines = [l for l in section_lines if l.strip()]
        spaced: list[str] = []
        for ln in body_lines:
            if spaced and ln.lstrip().startswith(("-", "*")) and not spaced[-1].lstrip().startswith(("-", "*")):
                spaced.append("")
            elif spaced and ln.lstrip().startswith(("-", "*")):
                spaced.append("")
            spaced.append(ln)
        body = "\n".join(spaced)
        if body:
            body = _to_mrkdwn(body)
            for chunk_start in range(0, len(body), 2900):
                blocks.append(
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": body[chunk_start : chunk_start + 2900]},
                    }
                )
        blocks.append({"type": "divider"})
        section_lines = []
        current_heading = None

    for raw in lines:
        stripped = raw.strip()
        if stripped.startswith("# "):
            flush()
            current_heading = stripped[2:].strip()
        elif stripped.startswith("## "):
            flush()
            current_heading = stripped[3:].strip()
        else:
            section_lines.append(raw)
    flush()

    if blocks and blocks[-1].get("type") == "divider":
        blocks.pop()

    blocks.append({"type": "divider"})
    if footer_text_parts:
        footer_text = " ".join(footer_text_parts)
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"_{_to_mrkdwn(footer_text)}_"}],
            }
        )
    issue_for_footer = ""
    if issue == 0 or issue == "0":
        issue_for_footer = "Issue 0 (test)"
    elif issue:
        issue_for_footer = f"Issue {issue}"
    footer_meta = f"_LuckyHands Daily Intel  ·  {issue_for_footer}  ·  Produced {produced_at}_"
    if not issue_for_footer:
        footer_meta = f"_LuckyHands Daily Intel  ·  Produced {produced_at}_"
    blocks.append(
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": footer_meta}],
        }
    )
    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        f":memo: Reply to this thread with corrections. They train the next brief.  "
                        f"·  :scales: Not legal advice. Verify any regulatory item with counsel before acting."
                    ),
                }
            ],
        }
    )

    return blocks


def post_to_slack(brief_md: str, date_str: str, issue: int | str = "") -> tuple[bool, str]:
    if not SLACK_WEBHOOK_URL:
        return False, "SLACK_WEBHOOK_URL not set"

    blocks = md_to_blocks(brief_md, date_str, issue)
    payload: dict = {
        "blocks": blocks,
        "text": f"LuckyHands Intel Daily, {date_str}",
        "username": SLACK_USERNAME,
        "icon_emoji": SLACK_ICON_EMOJI,
    }
    if SLACK_CHANNEL:
        payload["channel"] = SLACK_CHANNEL

    try:
        resp = httpx.post(SLACK_WEBHOOK_URL, json=payload, timeout=15.0)
        if resp.status_code >= 400:
            return False, f"Slack returned {resp.status_code}, {resp.text[:200]}"
        return True, "ok"
    except Exception as exc:
        return False, f"Slack post failed, {exc}"
