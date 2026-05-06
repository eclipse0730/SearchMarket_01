from __future__ import annotations


def progress_bar(completed: int, total: int, width: int = 20) -> str:
    if total <= 0:
        return "□" * width
    safe_completed = max(0, min(completed, total))
    filled = min(width, int(width * safe_completed / total))
    return "■" * filled + "□" * (width - filled)
