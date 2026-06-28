import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from config import RECIPIENT_EMAIL


_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent),
    autoescape=select_autoescape(["html"]),
)


_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)")
_BADGE = re.compile(r"^(ACTION|WATCH|WARNING)(,)?", re.IGNORECASE)


def _inline(text: str) -> str:
    text = _LINK.sub(r'<a href="\2">\1</a>', text)
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    text = _ITALIC.sub(r"<em>\1</em>", text)
    return text


def _badge_html(line: str) -> str:
    m = _BADGE.match(line)
    if not m:
        return line
    word = m.group(1).upper()
    klass = {
        "ACTION": "badge badge-action",
        "WATCH": "badge badge-watch",
        "WARNING": "badge badge-warning",
    }[word]
    return f'<span class="{klass}">{word}</span>' + line[m.end():]


def _markdown_to_html(md: str) -> str:
    out = []
    buffer = []

    def flush_buffer():
        if not buffer:
            return
        for line in buffer:
            if not line.strip():
                continue
            line_with_badge = _badge_html(line)
            out.append(f'<div class="item">{_inline(line_with_badge)}</div>')
        buffer.clear()

    in_para = False
    para_lines = []

    def flush_para():
        nonlocal in_para
        if para_lines:
            out.append("<p>" + " ".join(_inline(l) for l in para_lines) + "</p>")
            para_lines.clear()
        in_para = False

    section_type = None
    paragraph_sections = {"top story", "footer", "1. top story", "9. footer"}

    for raw in md.splitlines():
        line = raw.rstrip()
        if not line.strip():
            flush_buffer()
            flush_para()
            continue
        if line.startswith("# "):
            flush_buffer()
            flush_para()
            out.append(f"<h1>{_inline(line[2:].strip())}</h1>")
            section_type = None
        elif line.startswith("## "):
            flush_buffer()
            flush_para()
            heading = line[3:].strip()
            out.append(f"<h2>{_inline(heading)}</h2>")
            section_type = heading.lower()
        else:
            stripped = line.lstrip()
            is_paragraph_section = section_type in paragraph_sections
            if is_paragraph_section and not _BADGE.match(stripped):
                flush_buffer()
                in_para = True
                para_lines.append(stripped)
            else:
                flush_para()
                buffer.append(stripped)

    flush_buffer()
    flush_para()
    return "\n".join(out)


def render_email(brief_md: str, date_str: str, issue: int) -> str:
    body_html = _markdown_to_html(brief_md)
    template = _env.get_template("template.html")
    return template.render(
        body_html=body_html,
        date_str=date_str,
        issue=issue,
        recipient=RECIPIENT_EMAIL,
    )


def write_output(html: str, date_str: str) -> Path:
    out_dir = Path(__file__).parent / "output"
    out_dir.mkdir(exist_ok=True)
    slug = date_str.replace(", ", "_").replace(" ", "_")
    path = out_dir / f"brief_{slug}.html"
    path.write_text(html, encoding="utf-8")
    return path


def write_qa(verify_note: str, brief_md: str, date_str: str) -> Path:
    out_dir = Path(__file__).parent / "output"
    out_dir.mkdir(exist_ok=True)
    slug = date_str.replace(", ", "_").replace(" ", "_")
    path = out_dir / f"qa_{slug}.md"
    path.write_text(
        f"# QA notes for {date_str}\n\n## Verification pass\n\n{verify_note}\n\n"
        f"## Source markdown\n\n```markdown\n{brief_md}\n```\n",
        encoding="utf-8",
    )
    return path
