import os
import re

import httpx


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


def md_to_blocks(brief_md: str, date_str: str, issue: int | str = "") -> list[dict]:
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"LuckyHands Intel Daily, {date_str}"},
        }
    ]
    if issue:
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": f"Issue {issue}  ·  Local ADK pipeline  ·  qwen2.5 14b"}
                ],
            }
        )
    blocks.append({"type": "divider"})

    lines = brief_md.split("\n")
    section_lines: list[str] = []
    current_heading: str | None = None

    def flush():
        nonlocal section_lines, current_heading
        if current_heading is None and not section_lines:
            return
        if current_heading:
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*{current_heading}*"},
                }
            )
        body = "\n".join(l for l in section_lines if l.strip())
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

    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Not legal advice. Reply with corrections, they train the next brief.",
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
