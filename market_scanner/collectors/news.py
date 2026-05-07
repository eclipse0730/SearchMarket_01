from __future__ import annotations

import argparse
import hashlib
import html
import os
import re
import xml.etree.ElementTree as ET
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse

import psycopg
import requests
from psycopg.types.json import Jsonb

from market_scanner.config.markets import MARKETS
from market_scanner.progress import progress_line
from market_scanner.storage.db import connect, finish_run, home_market_key


_DEFAULT_MAX_SYMBOLS = 50
_DEFAULT_ITEMS_PER_SYMBOL = 3
_DEFAULT_LOOKBACK_DAYS = 3
_DEFAULT_WORKERS = 4
_REQUEST_TIMEOUT = 8
_FINNHUB_BASE_URL = "https://finnhub.io/api/v1/company-news"
_DEFAULT_RSS_FEED_URLS = (
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US",
)
_USER_AGENT = "SearchMarket/1.0 (+https://github.com/)"


@dataclass(frozen=True)
class NewsTarget:
    instrument_id: int
    symbol: str
    name: str
    rank_no: int | None
    composite_score: float | None


@dataclass(frozen=True)
class NewsArticle:
    source_provider: str
    external_id: str | None
    url: str
    title: str
    publisher: str | None
    published_at: datetime | None
    summary: str | None
    language_code: str
    raw_payload: dict[str, Any]
    relevance_score: float


@dataclass(frozen=True)
class NewsFetchResult:
    target: NewsTarget
    provider: str
    articles: list[NewsArticle]
    error: str | None = None


def _date_from_arg(date_str: str | None) -> date:
    return datetime.strptime(date_str, "%Y%m%d").date() if date_str else date.today()


def _provider_names(provider: str) -> list[str]:
    normalized = provider.lower().strip()
    if normalized in {"all", "auto"}:
        return ["finnhub", "rss"]
    if normalized in {"finnhub", "rss"}:
        return [normalized]
    raise ValueError(f"Unsupported news provider: {provider}")


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_timestamp(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = parsedate_to_datetime(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _stable_external_id(provider: str, url: str, title: str) -> str:
    digest = hashlib.sha1(f"{provider}|{url}|{title}".encode("utf-8")).hexdigest()
    return digest[:20]


def _rss_feed_urls() -> tuple[str, ...]:
    configured = os.getenv("NEWS_RSS_FEED_URLS", "").strip()
    if not configured:
        return _DEFAULT_RSS_FEED_URLS
    return tuple(part.strip() for part in configured.split(";") if part.strip())


def _select_news_targets(
    conn: psycopg.Connection,
    market_key: str,
    trade_date: date,
    universe_key: str | None,
    max_symbols: int,
) -> list[NewsTarget]:
    effective_universe = universe_key or market_key
    rows = conn.execute(
        """
        WITH latest_run AS (
            SELECT COALESCE(
                (
                    SELECT run_id
                    FROM market_snapshots
                    WHERE market_key = %s AND universe_key = %s AND trade_date = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                ),
                (
                    SELECT run_id
                    FROM collection_runs
                    WHERE run_type = 'scan'
                      AND market_key = %s
                      AND universe_key = %s
                      AND trade_date = %s
                      AND status = 'success'
                    ORDER BY finished_at DESC NULLS LAST, started_at DESC
                    LIMIT 1
                )
            ) AS run_id
        )
        SELECT i.instrument_id, i.symbol, COALESCE(NULLIF(i.name_en, ''), i.symbol),
               sr.rank_no, sr.composite_score
        FROM scan_results sr
        JOIN latest_run lr ON lr.run_id = sr.run_id
        JOIN instruments i ON i.instrument_id = sr.instrument_id
        WHERE sr.universe_key = %s AND sr.trade_date = %s
        ORDER BY sr.rank_no NULLS LAST, sr.composite_score DESC NULLS LAST, i.symbol
        LIMIT %s
        """,
        (
            home_market_key(market_key),
            effective_universe,
            trade_date,
            home_market_key(market_key),
            effective_universe,
            trade_date,
            effective_universe,
            trade_date,
            max(0, max_symbols),
        ),
    ).fetchall()
    return [
        NewsTarget(
            instrument_id=int(row[0]),
            symbol=str(row[1]),
            name=str(row[2]),
            rank_no=row[3],
            composite_score=float(row[4]) if row[4] is not None else None,
        )
        for row in rows
    ]


def _recent_scan_scopes(conn: psycopg.Connection, market_key: str, limit: int = 10) -> list[tuple[date, str, int]]:
    rows = conn.execute(
        """
        SELECT trade_date, universe_key, COUNT(*) AS row_count
        FROM scan_results
        WHERE market_key = %s
        GROUP BY trade_date, universe_key
        ORDER BY trade_date DESC, universe_key
        LIMIT %s
        """,
        (home_market_key(market_key), limit),
    ).fetchall()
    return [(row[0], str(row[1]), int(row[2] or 0)) for row in rows]


def _fetch_finnhub_news(target: NewsTarget, start_date: date, end_date: date, items_per_symbol: int) -> NewsFetchResult:
    token = os.getenv("FINNHUB_API_KEY", "").strip()
    if not token:
        return NewsFetchResult(target, "finnhub", [], "missing FINNHUB_API_KEY")
    try:
        response = requests.get(
            _FINNHUB_BASE_URL,
            params={
                "symbol": target.symbol,
                "from": start_date.isoformat(),
                "to": end_date.isoformat(),
                "token": token,
            },
            headers={"User-Agent": _USER_AGENT},
            timeout=_REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        return NewsFetchResult(target, "finnhub", [], type(exc).__name__)

    if not isinstance(payload, list):
        return NewsFetchResult(target, "finnhub", [], "unexpected_payload")

    articles: list[NewsArticle] = []
    seen: set[str] = set()
    for item in payload:
        if not isinstance(item, dict):
            continue
        title = _clean_text(item.get("headline"))
        url = str(item.get("url") or "").strip()
        if not title or not url or url in seen:
            continue
        seen.add(url)
        published_at = _parse_timestamp(item.get("datetime"))
        external_id = str(item.get("id") or "").strip() or _stable_external_id("finnhub", url, title)
        articles.append(
            NewsArticle(
                source_provider="finnhub",
                external_id=external_id,
                url=url,
                title=title,
                publisher=_clean_text(item.get("source")) or None,
                published_at=published_at,
                summary=_clean_text(item.get("summary")) or None,
                language_code="en",
                raw_payload=item,
                relevance_score=1.0,
            )
        )
        if len(articles) >= items_per_symbol:
            break
    return NewsFetchResult(target, "finnhub", articles)


def _xml_text(element: ET.Element, child_name: str) -> str:
    for child in list(element):
        if child.tag.split("}")[-1] == child_name:
            return _clean_text(child.text)
    return ""


def _rss_link(element: ET.Element) -> str:
    link = _xml_text(element, "link")
    if link:
        return link
    for child in list(element):
        if child.tag.split("}")[-1] == "link":
            href = child.attrib.get("href")
            if href:
                return href.strip()
    return ""


def _rss_items(payload: bytes) -> list[ET.Element]:
    root = ET.fromstring(payload)
    return [element for element in root.iter() if element.tag.split("}")[-1] == "item"]


def _publisher_from_url(url: str) -> str | None:
    netloc = urlparse(url).netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc or None


def _fetch_rss_news(target: NewsTarget, start_date: date, end_date: date, items_per_symbol: int) -> NewsFetchResult:
    articles: list[NewsArticle] = []
    seen: set[str] = set()
    last_error: str | None = None
    for template in _rss_feed_urls():
        url = template.format(symbol=target.symbol, name=target.name)
        try:
            response = requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=_REQUEST_TIMEOUT)
            response.raise_for_status()
            items = _rss_items(response.content)
        except Exception as exc:
            last_error = type(exc).__name__
            continue

        for item in items:
            title = _xml_text(item, "title")
            link = _rss_link(item)
            if not title or not link or link in seen:
                continue
            published_at = _parse_timestamp(_xml_text(item, "pubDate") or _xml_text(item, "updated"))
            if published_at is not None and published_at.date() < start_date:
                continue
            if published_at is not None and published_at.date() > end_date:
                continue
            seen.add(link)
            summary = _xml_text(item, "description") or _xml_text(item, "summary")
            external_id = _xml_text(item, "guid") or _stable_external_id("rss", link, title)
            articles.append(
                NewsArticle(
                    source_provider="rss",
                    external_id=external_id,
                    url=link,
                    title=title,
                    publisher=_xml_text(item, "source") or _publisher_from_url(link),
                    published_at=published_at,
                    summary=summary or None,
                    language_code="en",
                    raw_payload={
                        "feed_url": url,
                        "guid": external_id,
                        "symbol": target.symbol,
                    },
                    relevance_score=0.8,
                )
            )
            if len(articles) >= items_per_symbol:
                return NewsFetchResult(target, "rss", articles)
    return NewsFetchResult(target, "rss", articles, None if articles else last_error)


def _fetch_provider_news(
    target: NewsTarget,
    provider: str,
    start_date: date,
    end_date: date,
    items_per_symbol: int,
) -> NewsFetchResult:
    if provider == "finnhub":
        return _fetch_finnhub_news(target, start_date, end_date, items_per_symbol)
    if provider == "rss":
        return _fetch_rss_news(target, start_date, end_date, items_per_symbol)
    return NewsFetchResult(target, provider, [], "unsupported_provider")


def _create_news_run(
    conn: psycopg.Connection,
    market_key: str,
    universe_key: str | None,
    trade_date: date,
    provider: str,
    requested_count: int,
    params: dict[str, Any],
) -> str:
    row = conn.execute(
        """
        INSERT INTO collection_runs (
            run_type, market_key, universe_key, trade_date, source_provider, status, requested_count, params
        )
        VALUES ('news', %s, %s, %s, %s, 'running', %s, %s)
        RETURNING run_id
        """,
        (
            home_market_key(market_key),
            universe_key or market_key,
            trade_date,
            provider,
            requested_count,
            Jsonb(params),
        ),
    ).fetchone()
    return str(row[0])


def _upsert_news_article(
    conn: psycopg.Connection,
    target: NewsTarget,
    article: NewsArticle,
) -> int:
    row = conn.execute(
        """
        INSERT INTO news_items (
            source_provider, external_id, url, title, publisher, published_at,
            summary, language_code, raw_payload
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (url) DO UPDATE SET
            source_provider = CASE
                WHEN news_items.source_provider = EXCLUDED.source_provider THEN news_items.source_provider
                WHEN position(EXCLUDED.source_provider in news_items.source_provider) > 0 THEN news_items.source_provider
                ELSE news_items.source_provider || '+' || EXCLUDED.source_provider
            END,
            title = EXCLUDED.title,
            publisher = COALESCE(EXCLUDED.publisher, news_items.publisher),
            published_at = COALESCE(EXCLUDED.published_at, news_items.published_at),
            summary = COALESCE(EXCLUDED.summary, news_items.summary),
            language_code = COALESCE(EXCLUDED.language_code, news_items.language_code),
            raw_payload = news_items.raw_payload || jsonb_build_object(
                EXCLUDED.source_provider, EXCLUDED.raw_payload
            ),
            collected_at = now()
        RETURNING news_id
        """,
        (
            article.source_provider,
            article.external_id,
            article.url,
            article.title,
            article.publisher,
            article.published_at,
            article.summary,
            article.language_code,
            Jsonb({article.source_provider: article.raw_payload}),
        ),
    ).fetchone()
    news_id = int(row[0])
    conn.execute(
        """
        INSERT INTO instrument_news (instrument_id, news_id, relevance_score)
        VALUES (%s, %s, %s)
        ON CONFLICT (instrument_id, news_id) DO UPDATE SET
            relevance_score = GREATEST(
                COALESCE(instrument_news.relevance_score, 0),
                COALESCE(EXCLUDED.relevance_score, 0)
            )
        """,
        (target.instrument_id, news_id, article.relevance_score),
    )
    return news_id


def run_fetch(
    market_key: str,
    date_str: str | None = None,
    universe_key: str | None = None,
    *,
    max_symbols: int = _DEFAULT_MAX_SYMBOLS,
    items_per_symbol: int = _DEFAULT_ITEMS_PER_SYMBOL,
    lookback_days: int = _DEFAULT_LOOKBACK_DAYS,
    workers: int = _DEFAULT_WORKERS,
    provider: str = "all",
    explicit_url: str | None = None,
) -> int:
    if home_market_key(market_key) != "us":
        raise ValueError("News fetch currently supports the US market only.")

    trade_date = _date_from_arg(date_str)
    start_date = trade_date - timedelta(days=max(0, lookback_days))
    providers = _provider_names(provider)
    provider_label = "+".join(providers)

    with connect(explicit_url) as conn:
        targets = _select_news_targets(conn, market_key, trade_date, universe_key, max_symbols)
        if not targets:
            effective_universe = universe_key or market_key
            print(
                f"  news fetch [{market_key}/{effective_universe}]: "
                f"no scan_results targets for {trade_date.isoformat()}"
            )
            recent_scopes = _recent_scan_scopes(conn, market_key)
            if recent_scopes:
                print("  recent scan_results scopes:")
                for scope_date, scope_universe, row_count in recent_scopes:
                    print(f"    {scope_date:%Y-%m-%d}  universe={scope_universe}  rows={row_count}")
                print("  rerun with a matching --date and --universe, or run the scan stage first.")
            else:
                print("  no scan_results found for this market. Run the scan stage first.")
            return 0

        tasks = [(target, provider_name) for target in targets for provider_name in providers]
        run_id = _create_news_run(
            conn,
            market_key,
            universe_key,
            trade_date,
            provider_label,
            len(tasks),
            {
                "mode": "db",
                "providers": providers,
                "max_symbols": max_symbols,
                "items_per_symbol": items_per_symbol,
                "lookback_days": lookback_days,
                "start_date": start_date.isoformat(),
                "end_date": trade_date.isoformat(),
            },
        )

        worker_count = max(1, min(workers, len(tasks)))
        print(
            f"  news fetch [{market_key}/{universe_key or market_key}] "
            f"{len(targets)} symbols providers={provider_label} workers={worker_count} run_id={run_id}"
        )

        submitted = 0
        processed = 0
        stored = 0
        failed = 0
        error_samples: list[dict[str, Any]] = []

        def print_progress(force: bool = False) -> None:
            if not force and processed % max(1, len(tasks) // 100) != 0:
                return
            print(
                progress_line(
                    processed,
                    len(tasks),
                    queued=submitted,
                    active=submitted - processed,
                    stored=stored,
                    failed=failed,
                ),
                end="",
                flush=True,
            )

        def handle_result(result: NewsFetchResult) -> None:
            nonlocal processed, stored, failed
            processed += 1
            if result.error:
                failed += 1
                if len(error_samples) < 30:
                    error_samples.append(
                        {"symbol": result.target.symbol, "provider": result.provider, "reason": result.error}
                    )
                print_progress(force=True)
                return
            for article in result.articles:
                _upsert_news_article(conn, result.target, article)
                stored += 1
            print_progress()

        print_progress(force=True)
        if worker_count == 1:
            for target, provider_name in tasks:
                submitted += 1
                handle_result(_fetch_provider_news(target, provider_name, start_date, trade_date, items_per_symbol))
        else:
            task_iter = iter(tasks)
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                pending: dict[Any, tuple[NewsTarget, str]] = {}

                def submit_next() -> bool:
                    nonlocal submitted
                    try:
                        target, provider_name = next(task_iter)
                    except StopIteration:
                        return False
                    future = executor.submit(
                        _fetch_provider_news,
                        target,
                        provider_name,
                        start_date,
                        trade_date,
                        items_per_symbol,
                    )
                    pending[future] = (target, provider_name)
                    submitted += 1
                    return True

                for _ in range(worker_count):
                    if not submit_next():
                        break
                print_progress(force=True)

                while pending:
                    done, _ = wait(pending, timeout=1, return_when=FIRST_COMPLETED)
                    if not done:
                        print_progress(force=True)
                        continue
                    for future in done:
                        target, provider_name = pending.pop(future)
                        try:
                            handle_result(future.result())
                        except Exception as exc:
                            processed += 1
                            failed += 1
                            if len(error_samples) < 30:
                                error_samples.append(
                                    {
                                        "symbol": target.symbol,
                                        "provider": provider_name,
                                        "reason": type(exc).__name__,
                                    }
                                )
                            print_progress(force=True)
                        submit_next()

        print_progress(force=True)
        print()
        status = "success" if not failed else ("partial" if stored else "failed")
        finish_run(
            conn,
            run_id,
            status=status,
            success_count=stored,
            failed_count=failed,
            skipped_count=0,
            params={"processed_tasks": processed},
            error_samples=error_samples,
        )
        print(f"  news fetch [{market_key}] done: stored={stored} failed={failed} status={status}")
        return stored


def main() -> None:
    parser = argparse.ArgumentParser(description="US stock news collector.")
    parser.add_argument("--database-url", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    fetch_p = sub.add_parser("fetch", help="Fetch US stock news into PostgreSQL.")
    fetch_p.add_argument("--market", required=True, choices=sorted(MARKETS))
    fetch_p.add_argument("--universe", default=None)
    fetch_p.add_argument("--date", default=None, help="Target scan date YYYYMMDD.")
    fetch_p.add_argument("--max-symbols", type=int, default=_DEFAULT_MAX_SYMBOLS)
    fetch_p.add_argument("--items-per-symbol", type=int, default=_DEFAULT_ITEMS_PER_SYMBOL)
    fetch_p.add_argument("--lookback-days", type=int, default=_DEFAULT_LOOKBACK_DAYS)
    fetch_p.add_argument("--workers", type=int, default=_DEFAULT_WORKERS)
    fetch_p.add_argument("--provider", choices=["all", "auto", "finnhub", "rss"], default="all")

    args = parser.parse_args()
    if args.command == "fetch":
        run_fetch(
            args.market,
            args.date,
            args.universe,
            max_symbols=max(0, args.max_symbols),
            items_per_symbol=max(1, args.items_per_symbol),
            lookback_days=max(0, args.lookback_days),
            workers=max(1, args.workers),
            provider=args.provider,
            explicit_url=args.database_url,
        )


if __name__ == "__main__":
    main()
