from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pandas as pd

from market_scanner.markets import MARKETS
from market_scanner.models import MarketDefinition, ScanSettings
from market_scanner.news import collect_news_cache
from market_scanner.pipeline import scan_market, write_html, write_markdown
from market_scanner.translator import translate_scan_csv

DATA_DIR = Path("data")

# Flat-file path conventions for known markets (backward compat).
# New markets fall through to the generic pattern below.
_COMPAT_PREFIXES: dict[str, tuple[str, str, str]] = {
    "us":     ("Data",       "Analysis",       "Report"),
    "kospi":  ("Data_Kospi", "Analysis_Kospi", "Report_Kospi"),
    "kosdaq": ("Data_Kosdaq","Analysis_Kosdaq","Report_Kosdaq"),
}


def compat_paths(market_key: str, date_str: str) -> dict[str, Path]:
    if market_key in _COMPAT_PREFIXES:
        data_pfx, md_pfx, html_pfx = _COMPAT_PREFIXES[market_key]
    else:
        label = market_key.title().replace("-", "")
        data_pfx, md_pfx, html_pfx = f"Data_{label}", f"Analysis_{label}", f"Report_{label}"
    return {
        "csv":  DATA_DIR / f"{data_pfx}_{date_str}.csv",
        "md":   Path(f"{md_pfx}_{date_str}.md"),
        "html": Path(f"{html_pfx}_{date_str}.html"),
    }


def _legacy_csv_path(path: Path) -> Path:
    return Path(path.name)


def _existing_csv_path(path: Path) -> Path:
    if path.exists():
        return path
    legacy_path = _legacy_csv_path(path)
    if legacy_path.exists():
        return legacy_path
    return path


def compat_market(market_key: str) -> MarketDefinition:
    return MARKETS[market_key]


def run_scan_stage_with_settings(
    market_key: str,
    date_str: str,
    settings: ScanSettings,
) -> tuple[MarketDefinition, pd.DataFrame, dict[str, Path]]:
    market, _, frame = scan_market(market_key, settings)
    paths = compat_paths(market_key, date_str)
    paths["csv"].parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(paths["csv"], index=False, encoding="utf-8-sig")
    return market, frame, paths


def load_frame(market_key: str, date_str: str) -> tuple[MarketDefinition, pd.DataFrame, dict[str, Path]]:
    market = compat_market(market_key)
    paths = compat_paths(market_key, date_str)
    frame = pd.read_csv(_existing_csv_path(paths["csv"]), encoding="utf-8-sig")
    return market, frame, paths


def run_analysis_stage(market_key: str, date_str: str, frame: pd.DataFrame | None = None) -> tuple[str, dict[str, Path]]:
    market = compat_market(market_key)
    paths = compat_paths(market_key, date_str)
    settings = ScanSettings(output_dir=Path("."))
    if frame is None:
        frame = pd.read_csv(_existing_csv_path(paths["csv"]), encoding="utf-8-sig")
    markdown = write_markdown(frame, market, settings, date_str, paths["md"])
    return markdown, paths


def run_render_stage(
    market_key: str,
    date_str: str,
    frame: pd.DataFrame | None = None,
    markdown: str | None = None,
) -> dict[str, Path]:
    market = compat_market(market_key)
    paths = compat_paths(market_key, date_str)
    settings = ScanSettings(output_dir=Path("."))
    if frame is None:
        frame = pd.read_csv(_existing_csv_path(paths["csv"]), encoding="utf-8-sig")
    if markdown is None:
        markdown = paths["md"].read_text(encoding="utf-8") if paths["md"].exists() else ""
    write_html(frame, market, settings, date_str, markdown, paths["html"])
    return paths


def run_translate_stage(market_key: str, date_str: str) -> bool:
    market = compat_market(market_key)
    paths = compat_paths(market_key, date_str)
    return translate_scan_csv(_existing_csv_path(paths["csv"]), market.sector_aliases)


def run_news_stage(
    market_key: str,
    date_str: str,
    *,
    max_symbols: int = 50,
    items_per_symbol: int = 3,
    max_workers: int = 4,
) -> tuple[int, Path]:
    _, frame, _ = load_frame(market_key, date_str)
    return collect_news_cache(
        frame,
        market_key,
        date_str,
        max_symbols=max_symbols,
        items_per_symbol=items_per_symbol,
        max_workers=max_workers,
    )


def ensure_csv_exists(market_key: str, date_str: str) -> Path:
    path = compat_paths(market_key, date_str)["csv"]
    existing_path = _existing_csv_path(path)
    if not existing_path.exists():
        raise FileNotFoundError(f"Missing scan output: {path}")
    return existing_path


def setup_scheduler(script_name: str, task_name: str, run_time: str = "08:05") -> None:
    script = os.path.abspath(script_name)
    python = sys.executable
    cmd = (
        f'schtasks /create /tn "{task_name}" '
        f'/tr "\\"{python}\\" \\"{script}\\"" '
        f'/sc daily /st {run_time} /f'
    )
    try:
        subprocess.run(cmd, shell=True, check=True, capture_output=True)
        print(f"  scheduler set: daily {run_time}")
        print(f"  task: {task_name}")
    except subprocess.CalledProcessError as exc:
        print(f"  scheduler failed: {exc}")
