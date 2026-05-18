"""DB 테이블 가이드 페이지 (site/db-admin/index.html).

docs/database_table_guide.md를 읽어 HTML로 렌더링합니다.
MD를 수정한 뒤 `uv run python Search.py site db_admin`을 실행하면 HTML이 동기화됩니다.
"""
from __future__ import annotations

import re
from html import escape
from pathlib import Path

from market_scanner.reports.site import layout

_GUIDE_PATH = Path(__file__).resolve().parents[4] / "docs" / "database_table_guide.md"


def _inline(text: str) -> str:
    text = escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"`([^`]+)`", r'<code class="ic">\1</code>', text)
    return text


def _parse_blocks(text: str) -> list[dict]:
    lines = text.splitlines()
    blocks: list[dict] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Code block
        if stripped.startswith("```"):
            lang = stripped[3:].strip()
            i += 1
            code_lines = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1
            blocks.append({"type": "code", "lang": lang, "content": "\n".join(code_lines)})
            continue

        # H1
        if line.startswith("# ") and not line.startswith("## "):
            blocks.append({"type": "h1", "content": line[2:].strip()})
            i += 1
            continue

        # H2
        if line.startswith("## "):
            blocks.append({"type": "h2", "content": line[3:].strip()})
            i += 1
            continue

        # Table
        if stripped.startswith("|"):
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i].strip())
                i += 1
            if len(table_lines) >= 2:
                headers = [c.strip() for c in table_lines[0].split("|")[1:-1]]
                rows = []
                for tl in table_lines[2:]:
                    cells = [c.strip() for c in tl.split("|")[1:-1]]
                    if any(cells):
                        rows.append(cells)
                blocks.append({"type": "table", "headers": headers, "rows": rows})
            continue

        # Unordered list
        if re.match(r"^[-*]\s", stripped):
            items = []
            while i < len(lines) and re.match(r"^[-*]\s", lines[i].strip()):
                items.append(re.sub(r"^[-*]\s+", "", lines[i].strip()))
                i += 1
            blocks.append({"type": "ul", "items": items})
            continue

        # Ordered list
        if re.match(r"^\d+\.", stripped):
            items = []
            while i < len(lines) and re.match(r"^\d+\.", lines[i].strip()):
                items.append(re.sub(r"^\d+\.\s*", "", lines[i].strip()))
                i += 1
            blocks.append({"type": "ol", "items": items})
            continue

        # Empty line
        if not stripped:
            i += 1
            continue

        # Paragraph
        para_lines = []
        while i < len(lines):
            l = lines[i]
            ls = l.strip()
            if not ls:
                break
            if ls.startswith("#") or ls.startswith("|") or ls.startswith("```"):
                break
            if re.match(r"^[-*]\s", ls) or re.match(r"^\d+\.", ls):
                break
            para_lines.append(ls)
            i += 1
        if para_lines:
            blocks.append({"type": "p", "content": " ".join(para_lines)})

    return blocks


def _blocks_to_html(blocks: list[dict]) -> tuple[str, list[tuple[str, str]]]:
    parts: list[str] = []
    toc: list[tuple[str, str]] = []
    h2_count = 0

    for block in blocks:
        t = block["type"]

        if t == "h1":
            continue  # 페이지 title 태그에서 사용

        if t == "h2":
            anchor = f"s{h2_count}"
            h2_count += 1
            toc.append((anchor, block["content"]))
            parts.append(f'<h2 class="db-h2" id="{anchor}">{_inline(block["content"])}</h2>')

        elif t == "p":
            parts.append(f'<p class="db-p">{_inline(block["content"])}</p>')

        elif t == "ul":
            items_html = "".join(f"<li>{_inline(item)}</li>" for item in block["items"])
            parts.append(f'<ul class="db-ul">{items_html}</ul>')

        elif t == "ol":
            items_html = "".join(f"<li>{_inline(item)}</li>" for item in block["items"])
            parts.append(f'<ol class="db-ol">{items_html}</ol>')

        elif t == "table":
            headers = block["headers"]
            rows = block["rows"]
            th_html = "".join(f"<th>{_inline(h)}</th>" for h in headers)
            rows_html = "".join(
                "<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in cells) + "</tr>"
                for cells in rows
            )
            parts.append(
                f'<div class="db-table-wrap">'
                f'<table class="db-table t"><thead><tr>{th_html}</tr></thead>'
                f"<tbody>{rows_html}</tbody></table></div>"
            )

        elif t == "code":
            lang = escape(block.get("lang", ""))
            content = escape(block["content"])
            parts.append(f'<pre class="db-code"><code class="lang-{lang}">{content}</code></pre>')

    return "".join(parts), toc


_STYLES = """<style>
main { width: min(82%, calc(100% - 2rem)); max-width: none; }
.db-meta { color: var(--muted); font-size: 12px; margin-bottom: 1.25rem; padding-bottom: 0.75rem; border-bottom: 1px solid var(--border); }
.db-layout { display: grid; grid-template-columns: 200px minmax(0, 1fr); gap: 18px; align-items: start; }
.db-toc { position: sticky; top: 68px; background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 10px; max-height: calc(100vh - 88px); overflow-y: auto; }
.db-toc-title { color: var(--muted); font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: .06em; padding: 2px 4px 7px; }
.db-toc a { display: block; padding: 4px 7px; border-radius: 5px; color: var(--muted); font-size: 11.5px; text-decoration: none; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.db-toc a:hover { color: var(--text); background: var(--panel-2); text-decoration: none; }
.db-content { min-width: 0; }
.db-h2 { font-size: 1rem; font-weight: 700; margin: 2rem 0 0.5rem; border-left: 3px solid var(--accent); padding-left: 10px; scroll-margin-top: 72px; }
.db-h2:first-child { margin-top: 0; }
.db-p { color: var(--text); line-height: 1.68; margin: 0.35rem 0 0.7rem; font-size: 0.875rem; }
.db-ul, .db-ol { color: var(--text); line-height: 1.75; padding-left: 1.35rem; margin: 0.2rem 0 0.75rem; font-size: 0.875rem; }
.db-ul li, .db-ol li { margin-bottom: 0.15rem; }
.db-table-wrap { overflow-x: auto; margin-bottom: 1rem; border-radius: 6px; border: 1px solid var(--border); }
.db-table { border-collapse: collapse; font-size: 0.78rem; width: 100%; table-layout: fixed; }
.db-table th { background: rgba(17,31,50,.9); color: var(--muted); font-weight: 500; padding: 6px 10px; text-align: left; border-bottom: 1px solid var(--border); overflow: hidden; }
.db-table th:first-child { width: 45%; }
.db-table td { padding: 5px 10px; border-bottom: 1px solid rgba(148,163,184,.1); text-align: left; overflow-wrap: anywhere; vertical-align: top; }
.db-table td:first-child { color: var(--accent); font-family: ui-monospace, "SFMono-Regular", Menlo, monospace; font-size: 0.74rem; }
.db-table tr:last-child td { border-bottom: none; }
.db-table tr:hover td { background: var(--panel-2); }
.db-code { background: rgba(7,16,28,.72); border: 1px solid var(--border); border-radius: 7px; padding: 12px 14px; overflow-x: auto; font-size: 11.5px; line-height: 1.55; margin: 0.25rem 0 1rem; color: #cdd9ea; font-family: ui-monospace, "SFMono-Regular", Menlo, monospace; }
code.ic { background: rgba(17,31,50,.85); border: 1px solid var(--border); border-radius: 3px; padding: 1px 5px; font-size: 0.82em; font-family: ui-monospace, "SFMono-Regular", Menlo, monospace; color: var(--accent); }
@media (max-width: 760px) {
  .db-layout { grid-template-columns: 1fr; }
  .db-toc { position: static; max-height: none; }
}
</style>"""


def render() -> str:
    if not _GUIDE_PATH.exists():
        body = (
            _STYLES
            + '<div class="db-layout"><div class="db-content">'
            '<p class="db-p">database_table_guide.md 파일을 찾을 수 없습니다.</p>'
            "</div></div>"
        )
        return layout.render_page(
            title="DB 테이블 가이드", depth=1, body_html=body, nav_active="db_admin"
        )

    text = _GUIDE_PATH.read_text(encoding="utf-8")
    blocks = _parse_blocks(text)
    content_html, toc = _blocks_to_html(blocks)

    # 상단 메타 정보 (Last updated 추출)
    last_updated = ""
    for line in text.splitlines():
        if line.startswith("Last updated:"):
            last_updated = line.strip()
            break

    meta_html = ""
    if last_updated:
        meta_html = (
            f'<div class="db-meta">'
            f'{escape(last_updated)} · 원본: <code class="ic">docs/database_table_guide.md</code>'
            f" · 수정 후 <code class=\"ic\">uv run python Search.py site db_admin</code> 으로 재생성</div>"
        )

    toc_links = "\n".join(
        f'<a href="#{anchor}">{escape(label)}</a>' for anchor, label in toc
    )

    body = (
        _STYLES
        + meta_html
        + f'<div class="db-layout">'
        f'<aside class="db-toc"><div class="db-toc-title">테이블 목록</div>{toc_links}</aside>'
        f'<div class="db-content">{content_html}</div>'
        f"</div>"
    )

    return layout.render_page(
        title="DB 테이블 가이드",
        depth=1,
        body_html=body,
        nav_active="db_admin",
        main_class="main-wide",
    )
