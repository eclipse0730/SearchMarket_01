from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


UniverseLoader = Callable[[], list[str]]
MetadataLoader = Callable[[], dict[str, "StaticTickerMeta"]]
QuoteUrlBuilder = Callable[[str], str]
DisplaySymbolBuilder = Callable[[str], str]


@dataclass(frozen=True)
class StaticTickerMeta:
    name_en: str
    name_local: str
    sector: str
    description: str


@dataclass(frozen=True)
class ScanSettings:
    ma_periods: tuple[int, ...] = (60, 120, 240)
    threshold_pct: float = 2.0
    history_period: str = "2y"
    min_history_buffer: int = 10
    max_workers: int = 8
    output_dir: Path = Path("refactor_outputs")


@dataclass(frozen=True)
class MarketDefinition:
    key: str
    label: str
    output_prefix: str
    currency_symbol: str
    price_decimals: int
    universe_loader: UniverseLoader
    metadata_loader: MetadataLoader
    quote_url_builder: QuoteUrlBuilder
    display_symbol_builder: DisplaySymbolBuilder = lambda symbol: symbol
    sector_aliases: dict[str, str] = field(default_factory=dict)
    notes: str = ""


@dataclass
class ScanRecord:
    symbol: str
    display_symbol: str
    name_en: str
    name_local: str
    sector: str
    description: str
    price: float | None
    change_pct: float | None
    rsi: float | None
    high_52w: float | None
    low_52w: float | None
    from_high_pct: float | None
    volume_ratio: float | None
    trailing_pe: float | None
    target_price: float | None
    upside_pct: float | None
    trend: str
    trend_score: int
    ma_values: dict[int, float | None] = field(default_factory=dict)
    ma_diff_pct: dict[int, float | None] = field(default_factory=dict)
    near_flags: dict[int, bool] = field(default_factory=dict)
