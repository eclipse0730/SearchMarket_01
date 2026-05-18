from __future__ import annotations

import argparse
import re
from html import escape
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_README = ROOT_DIR / "README.md"
DEFAULT_OUTPUT = ROOT_DIR / "docs" / "readme.html"


_CODE_SPAN_RE = re.compile(r"`([^`]+)`")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def _inline_markdown(text: str) -> str:
    parts: list[str] = []
    pos = 0
    for match in _CODE_SPAN_RE.finditer(text):
        parts.append(_format_inline_text(text[pos:match.start()]))
        parts.append(f"<code>{escape(match.group(1))}</code>")
        pos = match.end()
    parts.append(_format_inline_text(text[pos:]))
    return "".join(parts)


def _format_inline_text(text: str) -> str:
    rendered = escape(text)
    rendered = _LINK_RE.sub(
        lambda m: f'<a href="{escape(m.group(2), quote=True)}">{m.group(1)}</a>',
        rendered,
    )
    rendered = _BOLD_RE.sub(r"<strong>\1</strong>", rendered)
    return rendered


def _slugify(text: str, used: dict[str, int]) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    if not slug:
        slug = "section"
    count = used.get(slug, 0) + 1
    used[slug] = count
    return slug if count == 1 else f"{slug}-{count}"


def _split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_table_separator(line: str) -> bool:
    if "|" not in line:
        return False
    cells = _split_table_row(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def _render_table(lines: list[str]) -> str:
    header = _split_table_row(lines[0])
    rows = [_split_table_row(line) for line in lines[2:]]
    html = ["<div class=\"table-wrap\"><table>", "<thead><tr>"]
    html.extend(f"<th>{_inline_markdown(cell)}</th>" for cell in header)
    html.append("</tr></thead>")
    if rows:
        html.append("<tbody>")
        for row in rows:
            html.append("<tr>")
            html.extend(f"<td>{_inline_markdown(cell)}</td>" for cell in row)
            html.append("</tr>")
        html.append("</tbody>")
    html.append("</table></div>")
    return "\n".join(html)


def render_readme_html(markdown: str) -> str:
    lines = markdown.splitlines()
    used_slugs: dict[str, int] = {}
    body: list[str] = []
    paragraph: list[str] = []
    list_items: list[str] = []
    code_lines: list[str] | None = None
    code_lang = ""
    i = 0

    def flush_paragraph() -> None:
        if paragraph:
            body.append(f"<p>{_inline_markdown(' '.join(paragraph))}</p>")
            paragraph.clear()

    def flush_list() -> None:
        if list_items:
            body.append("<ul>")
            body.extend(f"<li>{item}</li>" for item in list_items)
            body.append("</ul>")
            list_items.clear()

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if code_lines is not None:
            if stripped.startswith("```"):
                class_attr = f' class="language-{escape(code_lang, quote=True)}"' if code_lang else ""
                body.append(f"<pre><code{class_attr}>{escape(chr(10).join(code_lines))}</code></pre>")
                code_lines = None
                code_lang = ""
            else:
                code_lines.append(line)
            i += 1
            continue

        if stripped.startswith("```"):
            flush_paragraph()
            flush_list()
            code_lines = []
            code_lang = stripped[3:].strip()
            i += 1
            continue

        if not stripped:
            flush_paragraph()
            flush_list()
            i += 1
            continue

        if "|" in stripped and i + 1 < len(lines) and _is_table_separator(lines[i + 1]):
            flush_paragraph()
            flush_list()
            table_lines = [line, lines[i + 1]]
            i += 2
            while i < len(lines) and "|" in lines[i].strip():
                table_lines.append(lines[i])
                i += 1
            body.append(_render_table(table_lines))
            continue

        if stripped.startswith("#"):
            marker, _, title = stripped.partition(" ")
            if set(marker) == {"#"} and 1 <= len(marker) <= 3 and title:
                flush_paragraph()
                flush_list()
                level = len(marker)
                heading_id = _slugify(title, used_slugs)
                body.append(f'<h{level} id="{heading_id}">{_inline_markdown(title)}</h{level}>')
                i += 1
                continue

        if stripped.startswith("- "):
            flush_paragraph()
            list_items.append(_inline_markdown(stripped[2:]))
            i += 1
            continue

        flush_list()
        paragraph.append(stripped)
        i += 1

    flush_paragraph()
    flush_list()
    if code_lines is not None:
        body.append(f"<pre><code>{escape(chr(10).join(code_lines))}</code></pre>")

    return "\n".join(body)


def build_readme_html(readme_path: Path = DEFAULT_README, output_path: Path = DEFAULT_OUTPUT) -> Path:
    markdown = readme_path.read_text(encoding="utf-8")
    body = render_readme_html(markdown)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_page_html(body), encoding="utf-8")
    return output_path


def _page_html(body: str) -> str:
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Stock MA Scanner README</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f8fa;
      --panel: #ffffff;
      --text: #1f2328;
      --muted: #59636e;
      --border: #d0d7de;
      --accent: #0969da;
      --code-bg: #f6f8fa;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans KR", Roboto, sans-serif;
      line-height: 1.6;
    }}
    main {{
      width: min(100% - 32px, 980px);
      margin: 32px auto;
      padding: 32px;
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
    }}
    h1, h2, h3 {{ line-height: 1.25; margin: 24px 0 12px; }}
    h1 {{ margin-top: 0; padding-bottom: 12px; border-bottom: 1px solid var(--border); }}
    h2 {{ padding-bottom: 8px; border-bottom: 1px solid var(--border); }}
    p, ul, pre, .table-wrap {{ margin: 0 0 16px; }}
    ul {{ padding-left: 24px; }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    code {{
      padding: 2px 5px;
      border-radius: 5px;
      background: var(--code-bg);
      font-family: ui-monospace, SFMono-Regular, SFMono, Consolas, "Liberation Mono", Menlo, monospace;
      font-size: 0.92em;
    }}
    pre {{
      overflow-x: auto;
      padding: 16px;
      border-radius: 8px;
      background: var(--code-bg);
      border: 1px solid var(--border);
    }}
    pre code {{ padding: 0; background: transparent; }}
    .table-wrap {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.95rem; }}
    th, td {{ padding: 8px 10px; border: 1px solid var(--border); text-align: left; vertical-align: top; }}
    th {{ background: var(--code-bg); font-weight: 600; }}
    @media (max-width: 640px) {{
      main {{ width: 100%; margin: 0; padding: 20px; border-width: 0; border-radius: 0; }}
    }}
  </style>
</head>
<body>
  <main>
{body}
  </main>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Build docs/readme.html from README.md.")
    parser.add_argument("--readme", type=Path, default=DEFAULT_README)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    path = build_readme_html(args.readme, args.output)
    print(f"readme html: {path}")


if __name__ == "__main__":
    main()
