from __future__ import annotations


def progress_line(
    completed: int,
    total: int,
    *,
    width: int = 20,
    indent: str = "    ",
    **counts: int,
) -> str:
    pct = (completed / total * 100) if total > 0 else 0.0
    safe_completed = max(0, min(completed, total))
    filled = min(width, int(width * safe_completed / total)) if total > 0 else 0
    bar = "■" * filled + "□" * (width - filled)
    suffix = " ".join(f"{key}={value}" for key, value in counts.items())
    return (
        f"\r{indent}[{bar}] "
        f"{completed}/{total} {pct:5.1f}%"
        + (f" {suffix}" if suffix else "")
    )
