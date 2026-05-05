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
    max_workers: int = 3
    symbol_limit: int | None = None
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

