#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hashlib
import http.client
import json
import math
import os
import re
import socket
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
KOLS_FILE = ROOT / "kols.txt"
REPORT_DIR = ROOT / "reports"
STATE_DIR = ROOT / "state"
CACHE_DIR = ROOT / "cache"
TRANSLATION_CACHE = CACHE_DIR / "translations.json"
TWEET_STORE = CACHE_DIR / "tweets.json"
SENT_STATE = CACHE_DIR / "sent.json"
MARKET_STATE = CACHE_DIR / "market.json"
US_MACRO_STATE = CACHE_DIR / "us_macro_calendar.json"
TELEGRAM_MESSAGE_LIMIT = 3900
TELEGRAM_SECTION_SEPARATOR_WIDTH = 51
TELEGRAM_SECTION_SEPARATOR = "━" * TELEGRAM_SECTION_SEPARATOR_WIDTH
TELEGRAM_VISUAL_GAP = "\u200b"
TELEGRAM_SEND_RETRIES = 3
TELEGRAM_RETRY_BASE_SECONDS = 2.0
TELEGRAM_RETRY_MAX_SECONDS = 30.0
TELEGRAM_RETRYABLE_HTTP_CODES = frozenset({429})
STABLECOIN_API_URL = "https://stablecoins.llama.fi/stablecoins?includePrices=true"
ETHEREUM_STAKING_URL = "https://ethereum.org/zh/staking/"
COINGECKO_MARKET_CHART_URL = (
    "https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart"
    "?vs_currency=usd&days=2"
)
COINGECKO_GLOBAL_URL = "https://api.coingecko.com/api/v3/global"
COINGECKO_DERIVATIVES_URL = "https://api.coingecko.com/api/v3/derivatives"
COIN_METRICS_ASSET_METRICS_URL = (
    "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
)
DEFILLAMA_DEX_VOLUME_URL = (
    "https://api.llama.fi/overview/dexs"
    "?excludeTotalDataChart=true&excludeTotalDataChartBreakdown=true"
)
COINGLASS_HYPERLIQUID_LIQUIDATION_URL = (
    "https://www.coinglass.com/zh/hyperliquid-liquidation-map"
)
COINGLASS_HYPERLIQUID_LONG_SHORT_RATIO_URL = (
    "https://www.coinglass.com/zh/pro/futures/hyperliquid-long-short-ratio"
)
COINGLASS_MARKET_OVERVIEW_URL = "https://www.coinglass.com/zh"
COINGLASS_BALANCE_URL = "https://www.coinglass.com/zh/Balance"
FARSIDE_BITCOIN_ETF_FLOW_URL = "https://farside.co.uk/bitcoin-etf-flow-all-data/"
FARSIDE_ETHEREUM_ETF_FLOW_URL = "https://farside.co.uk/ethereum-etf-flow-all-data/"
US_TREASURY_DEBT_URL = (
    "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/"
    "v2/accounting/od/debt_to_penny"
    "?fields=record_date,tot_pub_debt_out_amt&sort=-record_date&format=json"
    "&page%5Bnumber%5D=1&page%5Bsize%5D=2"
)
US_TREASURY_YIELD_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
    "?data=daily_treasury_yield_curve&field_tdr_date_value={year}"
)
BLS_RELEASE_SCHEDULE_URL = "https://www.bls.gov/schedule/{year}/home.htm"
FOMC_CALENDAR_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
BLS_MACRO_RELEASE_FALLBACKS = {
    2026: {
        "非农": ((9, 4, 8, 30), (10, 2, 8, 30), (11, 6, 8, 30), (12, 4, 8, 30)),
        "CPI": ((9, 11, 8, 30), (10, 14, 8, 30), (11, 10, 8, 30), (12, 10, 8, 30)),
    },
}
US_MACRO_CALENDAR_LABELS = frozenset({"非农", "CPI", "美联储决议"})
US_MACRO_CALENDAR_DISPLAY_LABELS = {"非农": "非农/失业率"}
US_MACRO_CALENDAR_CACHE_VERSION = 1
US_MACRO_CALENDAR_CACHE_TTL_SECONDS = 24 * 60 * 60
US_MACRO_CALENDAR_FAILURE_COOLDOWN_SECONDS = 24 * 60 * 60
STRATEGY_PURCHASES_URL = "https://www.strategy.com/purchases"
BITMINE_INVESTOR_RELATIONS_URL = "https://www.bitminetech.io/investor-relations"
STABLECOIN_TIMEOUT_SECONDS = 15
MARKET_HTTP_RETRIES = 2
MARKET_RETRY_BASE_SECONDS = 2.0
MARKET_SUMMARY_CACHE_TTL_SECONDS = 600
MARKET_SUMMARY_FAILURE_COOLDOWN_SECONDS = 900
MARKET_SUMMARY_CACHE_VERSION = 18
STRATEGY_BTC_CACHE_VERSION = 2
# Migration seed for caches created before Strategy had its own record.
STRATEGY_BTC_LAST_VALID = {
    "record_date": "2026-08-10",
    "holdings_as_of": "2026-08-23",
    "verified_date": "2026-08-25",
    "holdings": 840447,
    "change": -1690,
    "average_price": 75385.0,
    "total_cost_millions": 63357.0,
}
MARKET_SNAPSHOT_RETENTION_DAYS = 8
COINGLASS_CACHE_TTL_SECONDS = 600
COINGLASS_FAILURE_COOLDOWN_SECONDS = 900
COINGLASS_CACHE_VERSION = 4
COINGLASS_PAGE_WAIT_SECONDS = 20
COINGLASS_LIQUIDATION_LEVEL_LIMIT = 2
COINGLASS_LIQUIDATION_DISTANCE_LIMIT_PERCENT = 10.0
SPOT_ETF_FLOW_CACHE_TTL_SECONDS = 3600
SPOT_ETF_FLOW_FAILURE_COOLDOWN_SECONDS = 1800
SPOT_ETF_FLOW_CACHE_VERSION = 4
SPOT_ETF_FLOW_DISPLAY_DAYS = 3
SPOT_ETF_FLOW_SUMMARY_DAYS = 5
MIN_SCROLL_ROUNDS = 3
PAGE_RENDER_ERROR = "X page did not render its main content"
X_RATE_LIMIT_ERROR = "X returned an error or rate-limit page"
X_AUTHENTICATION_REQUIRED_ERROR = "X authentication required"
X_VERIFICATION_REQUIRED_ERROR = "X verification required"
RECOVERABLE_X_PAGE_ERRORS = (
    PAGE_RENDER_ERROR,
    X_RATE_LIMIT_ERROR,
    X_AUTHENTICATION_REQUIRED_ERROR,
    X_VERIFICATION_REQUIRED_ERROR,
)
ACCOUNT_UNAVAILABLE_ERROR = "X account unavailable"
GLOBAL_PAGE_DEFERRED_ERROR = "X scan deferred after global page failure"
RECOVERY_TOTAL_BUDGET_SECONDS = 90.0
RECOVERY_QUIET_SECONDS = 60.0
GLOBAL_PAGE_FAILURE_STREAK = 2
RECOVERY_ATTEMPT_CAP_SECONDS = 8.0
RECOVERY_MIN_ATTEMPT_SECONDS = 3.0
SEARCH_FALLBACK_TOTAL_BUDGET_SECONDS = 180.0
MAX_PLANNED_X_PAGE_LOADS_PER_RUN = 88
MAX_SEARCH_FALLBACK_SCROLLS = 2
# Keep the fast readiness polling introduced after 08-22, but require a short
# settle window so a partially mounted X page is not scraped too early.
X_PAGE_MIN_SETTLE_MS = 1200
X_SCROLL_MIN_SETTLE_MS = 250
RENAME_STATUS_CANDIDATES = 3
UNAVAILABLE_REMOVAL_DAYS = 7
UNAVAILABLE_RECHECK_INTERVAL_DAYS = 7
TRANSLATION_RETRIES = 1
TRANSLATION_HTTP_TIMEOUT_SECONDS = 12
TRANSLATION_WORKERS = 2
TRANSLATION_TOTAL_BUDGET_SECONDS = 120.0
TRANSLATION_BATCH_PAUSE_SECONDS = 0.25
LEGACY_TRANSLATION_LIMIT = 4500
TRANSLATION_VERSION = 2
# Keep the encoded GET request below Google's practical URL limit.
TRANSLATION_CHUNK_LIMIT = 1600
CN_TZ = dt.timezone(dt.timedelta(hours=8))


class RecoveryBudgetExceeded(RuntimeError):
    pass


class RecoveryBudget:
    def __init__(self, limit_seconds: float) -> None:
        self.limit_seconds = max(0.0, float(limit_seconds))
        self.started_at_monotonic = time.monotonic()

    @property
    def spent_seconds(self) -> float:
        return min(
            self.limit_seconds,
            max(0.0, time.monotonic() - self.started_at_monotonic),
        )

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, self.limit_seconds - self.spent_seconds)

    def deadline(self) -> float:
        remaining = self.remaining_seconds
        if remaining <= 0:
            raise RecoveryBudgetExceeded("X recovery budget exhausted")
        return self.started_at_monotonic + self.limit_seconds

    def sleep(self, seconds: float) -> None:
        delay = max(0.0, float(seconds))
        if delay <= 0:
            return
        if self.remaining_seconds <= delay:
            raise RecoveryBudgetExceeded("X recovery budget exhausted")
        time.sleep(delay)


class TelegramIPv4HTTPSConnection(http.client.HTTPSConnection):
    def connect(self) -> None:
        if self._tunnel_host:
            return super().connect()
        addresses = socket.getaddrinfo(self.host, self.port, socket.AF_INET, socket.SOCK_STREAM)
        last_error: OSError | None = None
        for _, _, _, _, sockaddr in addresses:
            sock = None
            try:
                sock = socket.create_connection(sockaddr, self.timeout, source_address=self.source_address)
                self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
                return
            except OSError as exc:
                last_error = exc
                if sock is not None:
                    sock.close()
        if last_error is not None:
            raise last_error
        raise OSError(f"no IPv4 address for {self.host}")


class TelegramIPv4HTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(
            TelegramIPv4HTTPSConnection,
            req,
            context=self._context,
        )


TELEGRAM_OPENER = urllib.request.build_opener(TelegramIPv4HTTPSHandler())


class NextDataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.in_next_data = False
        self.chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script" and dict(attrs).get("id") == "__NEXT_DATA__":
            self.in_next_data = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self.in_next_data:
            self.in_next_data = False

    def handle_data(self, data: str) -> None:
        if self.in_next_data:
            self.chunks.append(data)


class HTMLTextLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.text_parts: list[str] = []
        self.links: list[tuple[str, str]] = []
        self.current_href = ""
        self.current_link_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self.current_href = str(dict(attrs).get("href") or "")
            self.current_link_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.current_href:
            link_text = " ".join("".join(self.current_link_parts).split())
            self.links.append((link_text, self.current_href))
            self.current_href = ""
            self.current_link_parts = []

    def handle_data(self, data: str) -> None:
        self.text_parts.append(data)
        if self.current_href:
            self.current_link_parts.append(data)

    def text(self) -> str:
        return " ".join("".join(self.text_parts).split())


class HTMLTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self.current_table: list[list[str]] | None = None
        self.current_row: list[str] | None = None
        self.current_cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table" and self.current_table is None:
            self.current_table = []
        elif tag == "tr" and self.current_table is not None:
            self.current_row = []
        elif tag in {"th", "td"} and self.current_row is not None:
            self.current_cell = []
        elif tag == "br" and self.current_cell is not None:
            self.current_cell.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"th", "td"} and self.current_cell is not None:
            if self.current_row is not None:
                self.current_row.append(" ".join("".join(self.current_cell).split()))
            self.current_cell = None
        elif tag == "tr" and self.current_row is not None:
            if self.current_table is not None and self.current_row:
                self.current_table.append(self.current_row)
            self.current_row = None
        elif tag == "table" and self.current_table is not None:
            if self.current_table:
                self.tables.append(self.current_table)
            self.current_table = None

    def handle_data(self, data: str) -> None:
        if self.current_cell is not None:
            self.current_cell.append(data)


def cn_now() -> dt.datetime:
    return dt.datetime.now(CN_TZ)


def fetch_market_json(url: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "x-kol-watch"},
    )
    for attempt in range(MARKET_HTTP_RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=STABLECOIN_TIMEOUT_SECONDS) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt >= MARKET_HTTP_RETRIES:
                raise
            retry_after = None
            if exc.headers is not None:
                raw_retry_after = exc.headers.get("Retry-After")
                try:
                    retry_after = float(raw_retry_after)
                except (TypeError, ValueError):
                    retry_after = None
            delay = max(
                retry_after or 0.0,
                MARKET_RETRY_BASE_SECONDS * (2**attempt),
            )
            print(
                f"[market-rate-limit] retry {attempt + 1}/{MARKET_HTTP_RETRIES} "
                f"after {delay:.1f}s: {urllib.parse.urlsplit(url).netloc}",
                file=sys.stderr,
            )
            time.sleep(delay)


def fetch_stablecoin_supply() -> dict[str, dict[str, float]]:
    payload = fetch_market_json(STABLECOIN_API_URL)
    assets = payload.get("peggedAssets", [])
    by_symbol = {
        str(asset.get("symbol") or "").upper(): asset
        for asset in assets
        if isinstance(asset, dict)
    }
    result: dict[str, dict[str, float]] = {}
    for symbol in ("USDT", "USDC"):
        asset = by_symbol.get(symbol, {})
        current = float(asset.get("circulating", {}).get("peggedUSD"))
        previous = float(asset.get("circulatingPrevDay", {}).get("peggedUSD"))
        chain_deltas: dict[str, float] = {}
        chain_circulating = asset.get("chainCirculating", {})
        if isinstance(chain_circulating, dict):
            for chain, item in chain_circulating.items():
                if not isinstance(item, dict):
                    continue
                try:
                    chain_current = float(item.get("current", {}).get("peggedUSD"))
                    chain_previous = float(item.get("circulatingPrevDay", {}).get("peggedUSD"))
                except (AttributeError, TypeError, ValueError):
                    continue
                if math.isfinite(chain_current) and math.isfinite(chain_previous):
                    chain_deltas[str(chain)] = chain_current - chain_previous
        result[symbol] = {
            "current": current,
            "delta": current - previous,
            "chain_deltas": chain_deltas,
        }
    return result


def fetch_eth_staking_metrics() -> dict[str, float]:
    request = urllib.request.Request(
        ETHEREUM_STAKING_URL,
        headers={"Accept": "text/html", "User-Agent": "x-kol-watch"},
    )
    with urllib.request.urlopen(request, timeout=STABLECOIN_TIMEOUT_SECONDS) as response:
        page = response.read().decode("utf-8", "replace")

    def metric_value(*labels: str) -> str:
        for label in labels:
            pattern = (
                r"<code\b[^>]*>\s*([^<]+?)\s*</code>"
                r"\s*<div\b[^>]*>(?:(?!<code\b)[\s\S])*?"
                + re.escape(label)
            )
            match = re.search(pattern, page, re.IGNORECASE)
            if match:
                return re.sub(r"\s+", " ", match.group(1)).strip()

        parser = HTMLTextLinkParser()
        parser.feed(page)
        visible_text = parser.text()
        number = r"[\d,]+(?:\.\d+)?(?:[KMB])?"
        for label in labels:
            for fallback_pattern in (
                rf"({number})\s*[%％]?\s*(?:ETH\s*)?{re.escape(label)}",
                rf"{re.escape(label)}\s*({number})",
            ):
                fallback_match = re.search(fallback_pattern, visible_text, re.IGNORECASE)
                if fallback_match:
                    return fallback_match.group(1)
        raise ValueError(f"missing Ethereum staking metric: {labels[0]}")

    def metric_number(value: str) -> float:
        cleaned = value.replace(",", "").strip()
        multiplier = 1.0
        if cleaned[-1:].upper() in {"K", "M", "B"}:
            multiplier = {"K": 1e3, "M": 1e6, "B": 1e9}[cleaned[-1].upper()]
            cleaned = cleaned[:-1]
        return float(cleaned) * multiplier

    raw_total = metric_value("质押的 ETH 总量", "Total ETH staked").rstrip("%")
    raw_percent = metric_value(
        "已质押的 ETH 百分比", "Percent of ETH staked"
    ).rstrip("%")
    raw_apr = metric_value("当前 APR", "Current APR").rstrip("%")
    try:
        total = metric_number(raw_total)
        percent = metric_number(raw_percent)
        apr = metric_number(raw_apr)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"invalid Ethereum staking metrics: {raw_total!r}, {raw_percent!r}, {raw_apr!r}"
        ) from exc
    if not all(math.isfinite(value) for value in (total, percent, apr)):
        raise ValueError("non-finite Ethereum staking metrics")
    if total <= 0 or not 0 <= percent <= 100 or apr < 0:
        raise ValueError("out-of-range Ethereum staking metrics")
    return {"total": total, "percent": percent, "apr": apr}


def fetch_us_treasury_debt() -> dict[str, Any]:
    payload = fetch_market_json(US_TREASURY_DEBT_URL)
    rows = payload.get("data", [])
    if not isinstance(rows, list) or len(rows) < 2:
        raise ValueError("missing US Treasury debt records")
    current_row, previous_row = rows[:2]
    try:
        current = float(current_row["tot_pub_debt_out_amt"])
        previous = float(previous_row["tot_pub_debt_out_amt"])
        record_date = dt.date.fromisoformat(str(current_row["record_date"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("invalid US Treasury debt record") from exc
    if not math.isfinite(current) or not math.isfinite(previous) or current <= 0 or previous <= 0:
        raise ValueError("out-of-range US Treasury debt record")
    return {
        "current": current,
        "delta": current - previous,
        "record_date": record_date,
    }


def fetch_us_treasury_yields() -> dict[str, Any]:
    year = cn_now().year
    request = urllib.request.Request(
        US_TREASURY_YIELD_URL.format(year=year),
        headers={"Accept": "application/xml", "User-Agent": "x-kol-watch"},
    )
    with urllib.request.urlopen(request, timeout=STABLECOIN_TIMEOUT_SECONDS) as response:
        root = ET.fromstring(response.read())
    namespaces = {
        "atom": "http://www.w3.org/2005/Atom",
        "m": "http://schemas.microsoft.com/ado/2007/08/dataservices/metadata",
    }
    records: list[dict[str, Any]] = []
    for entry in root.findall("atom:entry", namespaces):
        properties = entry.find("atom:content/m:properties", namespaces)
        if properties is None:
            continue
        values = {element.tag.rsplit("}", 1)[-1]: element.text for element in properties}
        try:
            record = {
                "record_date": dt.datetime.fromisoformat(str(values["NEW_DATE"])).date(),
                "2y": float(values["BC_2YEAR"]),
                "5y": float(values["BC_5YEAR"]),
                "10y": float(values["BC_10YEAR"]),
                "30y": float(values["BC_30YEAR"]),
            }
        except (KeyError, TypeError, ValueError):
            continue
        yields = (record["2y"], record["5y"], record["10y"], record["30y"])
        if all(math.isfinite(value) and 0 <= value <= 100 for value in yields):
            records.append(record)
    if not records:
        raise ValueError("missing US Treasury yield records")
    return max(records, key=lambda item: item["record_date"])


def us_eastern_release_time(release_date: dt.date, hour: int, minute: int) -> dt.datetime:
    first_march = dt.date(release_date.year, 3, 1)
    second_sunday_march = first_march + dt.timedelta(
        days=(6 - first_march.weekday()) % 7 + 7
    )
    first_november = dt.date(release_date.year, 11, 1)
    first_sunday_november = first_november + dt.timedelta(
        days=(6 - first_november.weekday()) % 7
    )
    offset_hours = -4 if second_sunday_march <= release_date < first_sunday_november else -5
    eastern = dt.timezone(dt.timedelta(hours=offset_hours))
    return dt.datetime.combine(
        release_date,
        dt.time(hour, minute),
        tzinfo=eastern,
    ).astimezone(CN_TZ)


def parse_bls_macro_schedule(page: str, now: dt.datetime) -> dict[str, dt.datetime]:
    parser = HTMLTableParser()
    parser.feed(page)
    release_names = {
        "Consumer Price Index": "CPI",
        "Employment Situation": "非农",
    }
    month_numbers = {
        name: number
        for number, name in enumerate((
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
        ), 1)
    }
    upcoming: dict[str, dt.datetime] = {}
    for table in parser.tables:
        for row in table:
            if len(row) < 3:
                continue
            release_name = " ".join(row[2:])
            label = next((
                short_name
                for prefix, short_name in release_names.items()
                if release_name.startswith(prefix)
            ), "")
            if not label:
                continue
            date_match = re.search(
                r"(January|February|March|April|May|June|July|August|"
                r"September|October|November|December)\s+(\d{1,2}),\s+(\d{4})",
                row[0],
            )
            time_match = re.search(r"(\d{1,2}):(\d{2})\s*(AM|PM)", row[1], re.IGNORECASE)
            if date_match is None or time_match is None:
                continue
            hour = int(time_match.group(1)) % 12
            if time_match.group(3).upper() == "PM":
                hour += 12
            release_date = dt.date(
                int(date_match.group(3)),
                month_numbers[date_match.group(1)],
                int(date_match.group(2)),
            )
            release_at = us_eastern_release_time(release_date, hour, int(time_match.group(2)))
            if release_at < now:
                continue
            existing = upcoming.get(label)
            if existing is None or release_at < existing:
                upcoming[label] = release_at
    if not upcoming:
        raise ValueError("missing upcoming BLS macro releases")
    return upcoming


def bls_macro_schedule_fallback(now: dt.datetime) -> dict[str, dt.datetime]:
    upcoming: dict[str, dt.datetime] = {}
    for year, releases in BLS_MACRO_RELEASE_FALLBACKS.items():
        for label, entries in releases.items():
            candidates = [
                us_eastern_release_time(dt.date(year, month, day), hour, minute)
                for month, day, hour, minute in entries
            ]
            future = [release_at for release_at in candidates if release_at >= now]
            if future:
                upcoming[label] = min(future)
    return upcoming


def parse_fomc_calendar(page: str, now: dt.datetime) -> dt.datetime:
    parser = HTMLTextLinkParser()
    parser.feed(page)
    text = parser.text()
    month_pattern = (
        r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
        r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
    )
    month_numbers = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }
    upcoming: list[dt.datetime] = []
    for year in (now.year, now.year + 1):
        marker = re.search(rf"\b{year}\s+FOMC Meetings\b", text)
        if marker is None:
            continue
        next_marker = re.search(r"\b\d{4}\s+FOMC Meetings\b", text[marker.end():])
        section_end = marker.end() + next_marker.start() if next_marker else len(text)
        section = text[marker.end():section_end]
        for match in re.finditer(
            rf"\b({month_pattern})(?:/({month_pattern}))?\s+(\d{{1,2}})-(\d{{1,2}})",
            section,
        ):
            start_month = month_numbers[match.group(1)[:3].lower()]
            end_month = month_numbers[(match.group(2) or match.group(1))[:3].lower()]
            decision_year = year + (1 if end_month < start_month else 0)
            try:
                decision_date = dt.date(decision_year, end_month, int(match.group(4)))
            except ValueError:
                continue
            decision_at = us_eastern_release_time(decision_date, 14, 0)
            if decision_at >= now:
                upcoming.append(decision_at)
    if not upcoming:
        raise ValueError("missing upcoming FOMC decision")
    return min(upcoming)


def fetch_us_macro_page(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/140.0.0.0 Safari/537.36"
            ),
        },
    )
    with urllib.request.urlopen(request, timeout=STABLECOIN_TIMEOUT_SECONDS) as response:
        return response.read().decode("utf-8", "replace")


def future_macro_calendar(
    calendar: dict[str, dt.datetime],
    now: dt.datetime,
) -> dict[str, dt.datetime]:
    return {
        label: release_at
        for label, release_at in calendar.items()
        if label in US_MACRO_CALENDAR_LABELS
        and isinstance(release_at, dt.datetime)
        and release_at >= now
    }


def load_us_macro_calendar_cache() -> tuple[
    dict[str, dt.datetime],
    dt.datetime | None,
    dt.datetime | None,
]:
    state = load_json(US_MACRO_STATE, {})
    if not isinstance(state, dict) or state.get("version") != US_MACRO_CALENDAR_CACHE_VERSION:
        return {}, None, None
    raw_snapshot = state.get("snapshot")
    snapshot: dict[str, dt.datetime] = {}
    if isinstance(raw_snapshot, dict):
        for label, value in raw_snapshot.items():
            if label not in US_MACRO_CALENDAR_LABELS:
                continue
            parsed = parse_cache_timestamp(value)
            if parsed is not None:
                snapshot[label] = parsed.astimezone(CN_TZ)
    return (
        snapshot,
        parse_cache_timestamp(state.get("captured_at")),
        parse_cache_timestamp(state.get("failed_at")),
    )


def save_us_macro_calendar_cache(
    calendar: dict[str, dt.datetime],
    success: bool,
) -> None:
    state = load_json(US_MACRO_STATE, {})
    if not isinstance(state, dict) or state.get("version") != US_MACRO_CALENDAR_CACHE_VERSION:
        state = {"version": US_MACRO_CALENDAR_CACHE_VERSION}
    state["snapshot"] = {
        label: release_at.astimezone(CN_TZ).isoformat(timespec="minutes")
        for label, release_at in calendar.items()
        if label in US_MACRO_CALENDAR_LABELS and isinstance(release_at, dt.datetime)
    }
    if success:
        state["captured_at"] = cn_now().isoformat(timespec="seconds")
        state.pop("failed_at", None)
    else:
        state["failed_at"] = cn_now().isoformat(timespec="seconds")
    save_json(US_MACRO_STATE, state)


def fetch_bls_macro_calendar(now: dt.datetime) -> dict[str, dt.datetime]:
    try:
        calendar = parse_bls_macro_schedule(
            fetch_us_macro_page(BLS_RELEASE_SCHEDULE_URL.format(year=now.year)),
            now,
        )
    except ValueError:
        calendar = {}
    if {"非农", "CPI"}.issubset(calendar):
        return calendar
    try:
        next_year = parse_bls_macro_schedule(
            fetch_us_macro_page(BLS_RELEASE_SCHEDULE_URL.format(year=now.year + 1)),
            now,
        )
    except (OSError, ValueError, TypeError):
        next_year = {}
    for label, release_at in next_year.items():
        current = calendar.get(label)
        if current is None or release_at < current:
            calendar[label] = release_at
    if not calendar:
        raise ValueError("missing upcoming BLS macro releases")
    return calendar


def fetch_us_macro_calendar() -> dict[str, dt.datetime]:
    now = cn_now()
    cached, captured_at, failed_at = load_us_macro_calendar_cache()
    calendar = bls_macro_schedule_fallback(now)
    calendar.update(future_macro_calendar(cached, now))
    if (
        captured_at is not None
        and US_MACRO_CALENDAR_LABELS.issubset(calendar)
        and 0 <= (now - captured_at).total_seconds() < US_MACRO_CALENDAR_CACHE_TTL_SECONDS
    ):
        return calendar
    if (
        failed_at is not None
        and calendar
        and 0 <= (now - failed_at).total_seconds() < US_MACRO_CALENDAR_FAILURE_COOLDOWN_SECONDS
    ):
        print("[us-macro-cache] refresh cooldown active", file=sys.stderr)
        return calendar

    errors: list[Exception] = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        bls_future = executor.submit(fetch_bls_macro_calendar, now)
        fomc_future = executor.submit(
            lambda: parse_fomc_calendar(fetch_us_macro_page(FOMC_CALENDAR_URL), now)
        )
        try:
            calendar.update(bls_future.result())
        except (OSError, ValueError, TypeError) as exc:
            errors.append(exc)
        try:
            calendar["美联储决议"] = fomc_future.result()
        except (OSError, ValueError, TypeError) as exc:
            errors.append(exc)
    calendar = future_macro_calendar(calendar, now)
    if not calendar:
        raise errors[0] if errors else ValueError("missing US macro calendar")
    save_us_macro_calendar_cache(calendar, success=not errors)
    if errors:
        print("[us-macro-cache] using cached or fallback schedule", file=sys.stderr)
    return calendar


def us_macro_calendar_lines(calendar: dict[str, dt.datetime]) -> list[str]:
    scheduled = sorted(
        (
            (release_at, label)
            for label, release_at in calendar.items()
            if isinstance(release_at, dt.datetime)
        ),
        key=lambda item: item[0],
    )
    lines = ["美国宏观日程"]
    entries = [
        f"{US_MACRO_CALENDAR_DISPLAY_LABELS.get(label, label)} "
        f"{release_at.strftime('%m-%d %H:%M')}"
        for release_at, label in scheduled
    ]
    lines.extend(" | ".join(entries[index:index + 2]) for index in range(0, len(entries), 2))
    return lines if entries else []


def fetch_strategy_btc() -> dict[str, Any]:
    request = urllib.request.Request(
        STRATEGY_PURCHASES_URL,
        headers={"Accept": "text/html", "User-Agent": "x-kol-watch"},
    )
    with urllib.request.urlopen(request, timeout=STABLECOIN_TIMEOUT_SECONDS) as response:
        page = response.read().decode("utf-8", "replace")
    parser = NextDataParser()
    parser.feed(page)
    if not parser.chunks:
        raise ValueError("missing Strategy structured data")
    payload = json.loads("".join(parser.chunks))
    rows = payload.get("props", {}).get("pageProps", {}).get("bitcoinData", [])
    if not isinstance(rows, list):
        raise ValueError("invalid Strategy purchase records")
    records: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("_in_progress") is True:
            continue
        try:
            record = {
                "record_date": dt.date.fromisoformat(str(row["date_of_purchase"])),
                "holdings": int(float(row["btc_holdings"])),
                "change": int(float(row["count"])),
                "average_price": float(row["average_price"]),
                "total_cost_millions": float(row["total_acquisition_cost"]),
            }
        except (KeyError, TypeError, ValueError):
            continue
        numeric = (
            record["holdings"],
            record["change"],
            record["average_price"],
            record["total_cost_millions"],
        )
        if (
            all(math.isfinite(value) for value in numeric)
            and record["holdings"] > 0
            and record["average_price"] > 0
            and record["total_cost_millions"] > 0
        ):
            records.append(record)
    if not records:
        raise ValueError("missing complete Strategy purchase record")
    latest = max(records, key=lambda item: item["record_date"])
    latest["holdings_as_of"] = max(
        latest["record_date"],
        dt.date.fromisoformat(STRATEGY_BTC_LAST_VALID["holdings_as_of"]),
    )
    latest["verified_date"] = cn_now().date()
    return latest


def normalize_strategy_btc_record(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}

    def parse_date(raw: Any) -> dt.date:
        if isinstance(raw, dt.datetime):
            return raw.date()
        if isinstance(raw, dt.date):
            return raw
        return dt.date.fromisoformat(str(raw))

    try:
        record = {
            "record_date": parse_date(value["record_date"]),
            "holdings_as_of": parse_date(value["holdings_as_of"]),
            "verified_date": parse_date(value["verified_date"]),
            "holdings": int(value["holdings"]),
            "change": int(value["change"]),
            "average_price": float(value["average_price"]),
            "total_cost_millions": float(value["total_cost_millions"]),
        }
    except (KeyError, TypeError, ValueError, OverflowError):
        return {}
    numeric = (
        record["holdings"],
        record["change"],
        record["average_price"],
        record["total_cost_millions"],
    )
    if (
        not all(math.isfinite(number) for number in numeric)
        or record["holdings"] <= 0
        or record["average_price"] <= 0
        or record["total_cost_millions"] <= 0
        or record["record_date"] > record["verified_date"]
        or record["record_date"] > record["holdings_as_of"]
        or record["holdings_as_of"] > record["verified_date"]
    ):
        return {}
    return record


def save_strategy_btc_cache(record: dict[str, Any]) -> None:
    normalized = normalize_strategy_btc_record(record)
    if not normalized:
        raise ValueError("invalid Strategy cache record")
    state = load_json(MARKET_STATE, {"version": 1, "snapshots": {}})
    if not isinstance(state, dict):
        state = {"version": 1, "snapshots": {}}
    state["version"] = 1
    state["strategy_btc"] = {
        "version": STRATEGY_BTC_CACHE_VERSION,
        "record_date": normalized["record_date"].isoformat(),
        "holdings_as_of": normalized["holdings_as_of"].isoformat(),
        "verified_date": normalized["verified_date"].isoformat(),
        "holdings": normalized["holdings"],
        "change": normalized["change"],
        "average_price": normalized["average_price"],
        "total_cost_millions": normalized["total_cost_millions"],
    }
    save_json(MARKET_STATE, state)


def load_strategy_btc_cache() -> dict[str, Any]:
    state = load_json(MARKET_STATE, {"version": 1, "snapshots": {}})
    if not isinstance(state, dict):
        state = {"version": 1, "snapshots": {}}
    cache = state.get("strategy_btc")
    if isinstance(cache, dict) and cache.get("version") == STRATEGY_BTC_CACHE_VERSION:
        record = normalize_strategy_btc_record(cache)
        if record:
            return record
    return normalize_strategy_btc_record(STRATEGY_BTC_LAST_VALID)


def fetch_bitmine_eth() -> dict[str, Any]:
    request = urllib.request.Request(
        BITMINE_INVESTOR_RELATIONS_URL,
        headers={"Accept": "text/html", "User-Agent": "x-kol-watch"},
    )
    with urllib.request.urlopen(request, timeout=STABLECOIN_TIMEOUT_SECONDS) as response:
        investor_page = response.read().decode("utf-8", "replace")
    investor_parser = HTMLTextLinkParser()
    investor_parser.feed(investor_page)
    release_url = next((
        urllib.parse.urljoin(BITMINE_INVESTOR_RELATIONS_URL, href)
        for text, href in investor_parser.links
        if "ETH Holdings Reach" in text and href
    ), "")
    if not release_url:
        raise ValueError("missing BitMine ETH holdings release")

    request = urllib.request.Request(
        release_url,
        headers={"Accept": "text/html", "User-Agent": "x-kol-watch"},
    )
    with urllib.request.urlopen(request, timeout=STABLECOIN_TIMEOUT_SECONDS) as response:
        release_page = response.read().decode("utf-8", "replace")
    release_parser = HTMLTextLinkParser()
    release_parser.feed(release_page)
    text = release_parser.text()

    patterns = {
        "holdings": r"crypto holdings are comprised of ([\d,]+) ETH\b",
        "change": r"past week, we acquired ([\d,]+)\s+ETH\b",
        "supply_percent": r"ETH holdings are ([\d.]+)% of the ETH supply",
        "staked": r"total staked ETH stands at ([\d,]+)",
    }
    matches = {key: re.search(pattern, text, re.IGNORECASE) for key, pattern in patterns.items()}
    date_match = re.search(
        r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.\s+"
        r"(\d{1,2}),\s+(\d{4})\s+/PRNewswire/",
        text,
        re.IGNORECASE,
    )
    if any(match is None for match in matches.values()) or date_match is None:
        raise ValueError("incomplete BitMine ETH holdings release")
    try:
        record_date = dt.datetime.strptime(
            f"{date_match.group(1)} {date_match.group(2)} {date_match.group(3)}",
            "%b %d %Y",
        ).date()
        holdings = int(matches["holdings"].group(1).replace(",", ""))
        change = int(matches["change"].group(1).replace(",", ""))
        supply_percent = float(matches["supply_percent"].group(1))
        staked = int(matches["staked"].group(1).replace(",", ""))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("invalid BitMine ETH holdings release") from exc
    if (
        holdings <= 0
        or change < 0
        or not 0 < supply_percent <= 100
        or staked <= 0
        or staked > holdings
    ):
        raise ValueError("out-of-range BitMine ETH holdings release")
    return {
        "record_date": record_date,
        "holdings": holdings,
        "change": change,
        "supply_percent": supply_percent,
        "staked": staked,
    }


def parse_etf_flow_millions(value: str) -> float | None:
    cleaned = value.replace("\xa0", " ").strip()
    if cleaned in {"", "-", "–", "—"}:
        return None
    negative = cleaned.startswith("(") and cleaned.endswith(")")
    if negative:
        cleaned = cleaned[1:-1]
    cleaned = re.sub(r"[$,\s]", "", cleaned)
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", cleaned):
        return None
    result = float(cleaned)
    if negative:
        result = -result
    return result if math.isfinite(result) else None


def parse_farside_etf_flow_html(page: str) -> dict[str, Any]:
    parser = HTMLTableParser()
    parser.feed(page)
    month_numbers = {
        "jan": 1,
        "feb": 2,
        "mar": 3,
        "apr": 4,
        "may": 5,
        "jun": 6,
        "jul": 7,
        "aug": 8,
        "sep": 9,
        "oct": 10,
        "nov": 11,
        "dec": 12,
    }
    for table in parser.tables:
        header_index = next((
            index
            for index, row in enumerate(table)
            if row
            and row[-1].strip().lower() == "total"
            and row[0].strip().lower() in {"", "date"}
        ), None)
        if header_index is None:
            continue
        records: list[dict[str, Any]] = []
        for row in table[header_index + 1:]:
            if len(row) < 2:
                continue
            label = row[0].strip()
            total = parse_etf_flow_millions(row[-1])
            if label.lower() == "total":
                continue
            date_match = re.fullmatch(r"(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})", label)
            if date_match is None or total is None:
                continue
            published_fund_values = [
                parse_etf_flow_millions(value)
                for value in row[1:-1]
            ]
            if not any(value is not None for value in published_fund_values):
                continue
            has_published_flow = total != 0 or any(
                value != 0 for value in published_fund_values if value is not None
            )
            month = month_numbers.get(date_match.group(2).lower())
            if month is None:
                continue
            try:
                record_date = dt.date(
                    int(date_match.group(3)),
                    month,
                    int(date_match.group(1)),
                )
            except ValueError:
                continue
            records.append({
                "record_date": record_date.isoformat(),
                "flow_millions": total,
                "_has_published_flow": has_published_flow,
            })
        records.sort(key=lambda item: item["record_date"], reverse=True)
        while records and not records[0]["_has_published_flow"]:
            records.pop(0)
        for record in records:
            record.pop("_has_published_flow", None)
        if len(records) >= SPOT_ETF_FLOW_SUMMARY_DAYS:
            return {
                "records": records[:SPOT_ETF_FLOW_SUMMARY_DAYS],
            }
    raise ValueError("missing Farside ETF flow table")


def fetch_farside_etf_flow(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"Accept": "text/html", "User-Agent": "x-kol-watch"},
    )
    with urllib.request.urlopen(request, timeout=STABLECOIN_TIMEOUT_SECONDS) as response:
        page = response.read().decode("utf-8", "replace")
    return parse_farside_etf_flow_html(page)


def fetch_spot_etf_flows_live() -> dict[str, Any]:
    return {
        "BTC": fetch_farside_etf_flow(FARSIDE_BITCOIN_ETF_FLOW_URL),
        "ETH": fetch_farside_etf_flow(FARSIDE_ETHEREUM_ETF_FLOW_URL),
    }


def fetch_stablecoin_volumes() -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    for symbol, coin_id in (("USDT", "tether"), ("USDC", "usd-coin")):
        history = fetch_market_json(COINGECKO_MARKET_CHART_URL.format(coin_id=coin_id))
        points = history.get("total_volumes", [])
        valid_points = [
            (float(point[0]), float(point[1]))
            for point in points
            if isinstance(point, list) and len(point) >= 2
        ]
        if not valid_points:
            raise ValueError(f"missing CoinGecko volume history for {symbol}")
        latest_ms = max(point[0] for point in valid_points)
        current = max(valid_points, key=lambda point: point[0])[1]
        target_ms = latest_ms - 24 * 60 * 60 * 1000
        previous = min(valid_points, key=lambda point: abs(point[0] - target_ms))[1]
        delta = current - previous
        result[symbol] = {
            "current": current,
            "delta": delta,
            "percent": delta / previous * 100 if previous else 0.0,
        }
    if set(result) != {"USDT", "USDC"}:
        raise ValueError("missing USDT or USDC CoinGecko volume")
    return result


def fetch_global_volume() -> dict[str, float]:
    payload = fetch_market_json(COINGECKO_GLOBAL_URL)
    data = payload.get("data", {})
    current = float(data.get("total_volume", {}).get("usd"))
    percent = float(data.get("volume_change_percentage_24h_usd"))
    market_cap = float(data.get("total_market_cap", {}).get("usd"))
    market_cap_percent = float(data.get("market_cap_change_percentage_24h_usd"))
    market_cap_percentage = data.get("market_cap_percentage", {})
    btc_dominance = float(market_cap_percentage.get("btc"))
    eth_dominance = float(market_cap_percentage.get("eth"))
    divisor = 1 + percent / 100
    if divisor <= 0:
        raise ValueError("invalid CoinGecko global volume change")
    if not all(math.isfinite(value) for value in (
        current,
        percent,
        market_cap,
        market_cap_percent,
        btc_dominance,
        eth_dominance,
    )):
        raise ValueError("non-finite CoinGecko global data")
    if current < 0 or market_cap <= 0 or not 0 <= btc_dominance <= 100 or not 0 <= eth_dominance <= 100:
        raise ValueError("out-of-range CoinGecko global data")
    previous = current / divisor
    return {
        "current": current,
        "delta": current - previous,
        "percent": percent,
        "market_cap": market_cap,
        "market_cap_percent": market_cap_percent,
        "btc_dominance": btc_dominance,
        "eth_dominance": eth_dominance,
    }


def fetch_chain_activity() -> dict[str, Any]:
    query = urllib.parse.urlencode({
        "assets": "btc,eth",
        "metrics": "TxCnt",
        "frequency": "1d",
        "limit_per_asset": "8",
        "paging_from": "end",
        "ignore_forbidden_errors": "true",
        "ignore_unsupported_errors": "true",
    })
    payload = fetch_market_json(f"{COIN_METRICS_ASSET_METRICS_URL}?{query}")
    rows = payload.get("data", []) if isinstance(payload, dict) else []
    by_asset: dict[str, dict[dt.date, dict[str, float]]] = {
        asset: {} for asset in ("btc", "eth")
    }
    for row in rows:
        if not isinstance(row, dict):
            continue
        asset = str(row.get("asset") or "").lower()
        if asset not in by_asset:
            continue
        try:
            record_date = dt.date.fromisoformat(str(row.get("time") or "")[:10])
            transactions = float(row.get("TxCnt"))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(transactions) or transactions <= 0:
            continue
        by_asset[asset][record_date] = {
            "transactions": transactions,
        }
    common_dates = set.intersection(*(set(records) for records in by_asset.values()))
    if len(common_dates) < 8:
        raise ValueError("missing Coin Metrics chain activity history")
    recent_dates = sorted(common_dates)[-8:]
    previous_dates = recent_dates[:-1]
    previous_date, record_date = recent_dates[-2:]
    today = dt.datetime.now(dt.timezone.utc).date()
    if not 0 <= (today - record_date).days <= 3:
        raise ValueError("stale Coin Metrics chain activity")
    return {
        "record_date": record_date,
        "assets": {
            asset: {
                **by_asset[asset][record_date],
                "percent": (
                    by_asset[asset][record_date]["transactions"]
                    / by_asset[asset][previous_date]["transactions"]
                    - 1
                ) * 100,
                "seven_day_average_percent": (
                    by_asset[asset][record_date]["transactions"]
                    / (
                        sum(
                            by_asset[asset][date]["transactions"]
                            for date in previous_dates
                        )
                        / len(previous_dates)
                    )
                    - 1
                ) * 100,
            }
            for asset in ("btc", "eth")
        },
    }


def fetch_derivatives_volume() -> float:
    payload = fetch_market_json(COINGECKO_DERIVATIVES_URL)
    if not isinstance(payload, list):
        raise ValueError("invalid CoinGecko derivatives response")
    total = 0.0
    valid = 0
    for market in payload:
        if not isinstance(market, dict):
            continue
        try:
            volume = float(market.get("volume_24h"))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(volume) or volume < 0:
            continue
        total += volume
        valid += 1
    if not valid:
        raise ValueError("missing CoinGecko derivatives volume")
    return total


def fetch_dex_volume() -> dict[str, float]:
    payload = fetch_market_json(DEFILLAMA_DEX_VOLUME_URL)
    current = float(payload.get("total24h"))
    previous = float(payload.get("total48hto24h"))
    if current < 0 or previous <= 0:
        raise ValueError("invalid DefiLlama DEX volume")
    delta = current - previous
    return {
        "current": current,
        "delta": delta,
        "percent": delta / previous * 100,
    }


def previous_derivatives_volume(day: str) -> float | None:
    state = load_json(MARKET_STATE, {"version": 1, "snapshots": {}})
    snapshots = state.get("snapshots", {}) if isinstance(state, dict) else {}
    if not isinstance(snapshots, dict):
        return None
    previous = snapshots.get(day)
    if not isinstance(previous, dict):
        return None
    try:
        value = float(previous.get("derivatives_volume"))
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value >= 0 else None


def save_derivatives_snapshot(day: str, value: float) -> None:
    state = load_json(MARKET_STATE, {"version": 1, "snapshots": {}})
    if not isinstance(state, dict):
        state = {"version": 1, "snapshots": {}}
    snapshots = state.get("snapshots")
    if not isinstance(snapshots, dict):
        snapshots = {}
    snapshots.setdefault(day, {})
    if not isinstance(snapshots[day], dict):
        snapshots[day] = {}
    snapshots[day]["derivatives_volume"] = value
    snapshots[day]["captured_at"] = cn_now().isoformat(timespec="seconds")
    keep = sorted(snapshots)[-MARKET_SNAPSHOT_RETENTION_DAYS:]
    state["version"] = 1
    state["snapshots"] = {key: snapshots[key] for key in keep}
    save_json(MARKET_STATE, state)


def previous_eth_staking_total(day: str) -> float | None:
    state = load_json(MARKET_STATE, {"version": 1, "snapshots": {}})
    snapshots = state.get("snapshots", {}) if isinstance(state, dict) else {}
    if not isinstance(snapshots, dict):
        return None
    previous = snapshots.get(day)
    if not isinstance(previous, dict):
        return None
    try:
        value = float(previous.get("eth_staking_total"))
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value >= 0 else None


def save_eth_staking_snapshot(day: str, metrics: dict[str, float]) -> None:
    state = load_json(MARKET_STATE, {"version": 1, "snapshots": {}})
    if not isinstance(state, dict):
        state = {"version": 1, "snapshots": {}}
    snapshots = state.get("snapshots")
    if not isinstance(snapshots, dict):
        snapshots = {}
    snapshots.setdefault(day, {})
    if not isinstance(snapshots[day], dict):
        snapshots[day] = {}
    snapshots[day]["eth_staking_total"] = metrics["total"]
    snapshots[day]["eth_staking_percent"] = metrics["percent"]
    snapshots[day]["eth_staking_apr"] = metrics["apr"]
    snapshots[day]["captured_at"] = cn_now().isoformat(timespec="seconds")
    keep = sorted(snapshots)[-MARKET_SNAPSHOT_RETENTION_DAYS:]
    state["version"] = 1
    state["snapshots"] = {key: snapshots[key] for key in keep}
    save_json(MARKET_STATE, state)


def parse_cache_timestamp(value: Any) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=CN_TZ)


def load_market_summary_cache() -> tuple[str, dt.datetime | None, dt.datetime | None]:
    state = load_json(MARKET_STATE, {"version": 1, "snapshots": {}})
    cache = state.get("summary_cache", {}) if isinstance(state, dict) else {}
    if not isinstance(cache, dict):
        return "", None, None
    if cache.get("version") != MARKET_SUMMARY_CACHE_VERSION:
        return "", None, None
    summary = str(cache.get("summary") or "").strip()
    captured = parse_cache_timestamp(cache.get("captured_at"))
    failed = parse_cache_timestamp(cache.get("failed_at"))
    if not summary:
        return "", captured, failed
    return summary, captured, failed


def save_market_summary_cache(summary: str) -> None:
    state = load_json(MARKET_STATE, {"version": 1, "snapshots": {}})
    if not isinstance(state, dict):
        state = {"version": 1, "snapshots": {}}
    state["version"] = 1
    state["summary_cache"] = {
        "version": MARKET_SUMMARY_CACHE_VERSION,
        "summary": summary,
        "captured_at": cn_now().isoformat(timespec="seconds"),
    }
    save_json(MARKET_STATE, state)


def save_market_summary_failure() -> None:
    state = load_json(MARKET_STATE, {"version": 1, "snapshots": {}})
    if not isinstance(state, dict):
        state = {"version": 1, "snapshots": {}}
    cache = state.get("summary_cache")
    if not isinstance(cache, dict) or cache.get("version") != MARKET_SUMMARY_CACHE_VERSION:
        cache = {}
    cache["version"] = MARKET_SUMMARY_CACHE_VERSION
    cache["failed_at"] = cn_now().isoformat(timespec="seconds")
    state["version"] = 1
    state["summary_cache"] = cache
    save_json(MARKET_STATE, state)


def load_coinglass_cache() -> tuple[
    dict[str, Any] | None,
    dt.datetime | None,
    dt.datetime | None,
]:
    state = load_json(MARKET_STATE, {"version": 1, "snapshots": {}})
    cache = state.get("coinglass", {}) if isinstance(state, dict) else {}
    if not isinstance(cache, dict):
        return None, None, None
    if cache.get("version") != COINGLASS_CACHE_VERSION:
        return None, None, None
    snapshot = cache.get("snapshot")
    if not isinstance(snapshot, dict):
        snapshot = None
    return (
        snapshot,
        parse_cache_timestamp(cache.get("captured_at")),
        parse_cache_timestamp(cache.get("failed_at")),
    )


def save_coinglass_cache(snapshot: dict[str, Any]) -> None:
    state = load_json(MARKET_STATE, {"version": 1, "snapshots": {}})
    if not isinstance(state, dict):
        state = {"version": 1, "snapshots": {}}
    state["version"] = 1
    state["coinglass"] = {
        "version": COINGLASS_CACHE_VERSION,
        "snapshot": snapshot,
        "captured_at": cn_now().isoformat(timespec="seconds"),
    }
    state.pop("hyperliquid_liquidation", None)
    state.pop("coinglass_market_structure", None)
    save_json(MARKET_STATE, state)


def save_coinglass_failure() -> None:
    state = load_json(MARKET_STATE, {"version": 1, "snapshots": {}})
    if not isinstance(state, dict):
        state = {"version": 1, "snapshots": {}}
    cache = state.get("coinglass")
    if not isinstance(cache, dict) or cache.get("version") != COINGLASS_CACHE_VERSION:
        cache = {}
    cache["version"] = COINGLASS_CACHE_VERSION
    cache["failed_at"] = cn_now().isoformat(timespec="seconds")
    state["version"] = 1
    state["coinglass"] = cache
    save_json(MARKET_STATE, state)


def load_spot_etf_flow_cache() -> tuple[
    dict[str, Any] | None,
    dt.datetime | None,
    dt.datetime | None,
]:
    state = load_json(MARKET_STATE, {"version": 1, "snapshots": {}})
    cache = state.get("spot_etf_flows", {}) if isinstance(state, dict) else {}
    if not isinstance(cache, dict):
        return None, None, None
    if cache.get("version") != SPOT_ETF_FLOW_CACHE_VERSION:
        return None, None, None
    snapshot = cache.get("snapshot")
    if not isinstance(snapshot, dict):
        snapshot = None
    return (
        snapshot,
        parse_cache_timestamp(cache.get("captured_at")),
        parse_cache_timestamp(cache.get("failed_at")),
    )


def save_spot_etf_flow_cache(snapshot: dict[str, Any]) -> None:
    state = load_json(MARKET_STATE, {"version": 1, "snapshots": {}})
    if not isinstance(state, dict):
        state = {"version": 1, "snapshots": {}}
    state["version"] = 1
    state["spot_etf_flows"] = {
        "version": SPOT_ETF_FLOW_CACHE_VERSION,
        "snapshot": snapshot,
        "captured_at": cn_now().isoformat(timespec="seconds"),
    }
    save_json(MARKET_STATE, state)


def save_spot_etf_flow_failure() -> None:
    state = load_json(MARKET_STATE, {"version": 1, "snapshots": {}})
    if not isinstance(state, dict):
        state = {"version": 1, "snapshots": {}}
    cache = state.get("spot_etf_flows")
    if not isinstance(cache, dict) or cache.get("version") != SPOT_ETF_FLOW_CACHE_VERSION:
        cache = {}
    cache["version"] = SPOT_ETF_FLOW_CACHE_VERSION
    cache["failed_at"] = cn_now().isoformat(timespec="seconds")
    state["version"] = 1
    state["spot_etf_flows"] = cache
    save_json(MARKET_STATE, state)


def fetch_spot_etf_flow_snapshot() -> dict[str, Any]:
    cached, captured_at, failed_at = load_spot_etf_flow_cache()
    now = cn_now()

    def stale_cached_snapshot() -> dict[str, Any]:
        if cached is None:
            return {}
        result = dict(cached)
        result["_stale"] = True
        if captured_at is not None:
            result["_captured_at"] = captured_at.isoformat(timespec="seconds")
        return result

    if cached is not None and captured_at is not None:
        cache_age = (now - captured_at).total_seconds()
        if 0 <= cache_age < SPOT_ETF_FLOW_CACHE_TTL_SECONDS:
            return cached
    if failed_at is not None and cached is not None:
        failure_age = (now - failed_at).total_seconds()
        if 0 <= failure_age < SPOT_ETF_FLOW_FAILURE_COOLDOWN_SECONDS:
            print("[spot-etf-cache] refresh cooldown; using last snapshot", file=sys.stderr)
            return stale_cached_snapshot()
    try:
        snapshot = fetch_spot_etf_flows_live()
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        save_spot_etf_flow_failure()
        print(f"[spot-etf-error] {type(exc).__name__}: {exc}", file=sys.stderr)
        if cached is not None:
            print("[spot-etf-cache] using last successful snapshot", file=sys.stderr)
            return stale_cached_snapshot()
        return {}
    save_spot_etf_flow_cache(snapshot)
    return snapshot


def compact_percent(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".") + "%"


def compact_usd_price(value: float) -> str:
    return f"${value:,.0f}" if value >= 100 else f"${value:,.4f}".rstrip("0").rstrip(".")


def liquidation_level_text(level: dict[str, Any]) -> str:
    return (
        f"{compact_usd_price(float(level['price']))}"
        f"（{float(level['distance_percent']):+.2f}%｜"
        f"强度 {float(level['intensity']):,.0f} BTC）"
    )


def signed_yi(value: float) -> str:
    return f"{'+' if value >= 0 else ''}{value / 1e8:.2f}亿"


def signed_etf_yi(value_millions: float) -> str:
    value = value_millions / 100
    if value > 0:
        return f"+{value:.2f}"
    if value < 0:
        return f"{value:.2f}"
    return "0.00"


def spot_etf_summary_lines(snapshot: dict[str, Any]) -> list[str]:
    heading = "现货ETF资金流（亿美元）"
    if snapshot.get("_stale"):
        captured_at = parse_cache_timestamp(snapshot.get("_captured_at"))
        if captured_at is not None:
            heading = f"现货ETF资金流（亿美元，缓存 {captured_at.strftime('%m-%d %H:%M')}）"
    lines = [heading]
    five_day_parts: list[str] = []
    for symbol in ("BTC", "ETH"):
        asset = snapshot.get(symbol)
        if not isinstance(asset, dict):
            return []
        records = asset.get("records")
        if not isinstance(records, list) or len(records) < SPOT_ETF_FLOW_SUMMARY_DAYS:
            return []
        daily_parts: list[str] = []
        five_day_total = 0.0
        for index, record in enumerate(records[:SPOT_ETF_FLOW_SUMMARY_DAYS]):
            if not isinstance(record, dict):
                return []
            try:
                record_date = dt.date.fromisoformat(str(record["record_date"]))
                flow = float(record["flow_millions"])
            except (KeyError, TypeError, ValueError):
                return []
            if not math.isfinite(flow):
                return []
            if index < SPOT_ETF_FLOW_DISPLAY_DAYS:
                daily_parts.append(f"{record_date.strftime('%m-%d')} {signed_etf_yi(flow)}")
            five_day_total += flow
        lines.append(f"{symbol} " + " | ".join(daily_parts))
        five_day_parts.append(f"{symbol} {signed_etf_yi(five_day_total)}")
    lines.append("5日合计 " + " | ".join(five_day_parts))
    return lines


def chain_delta_text(delta: float, net: bool = False) -> str:
    if delta > 0:
        action = "净增" if net else "增加"
    elif delta < 0:
        action = "净减" if net else "减少"
    else:
        action = "无变化"
    return f"{action} {signed_yi(delta)}"


def visible_yi_change(value: float) -> bool:
    return f"{abs(value) / 1e8:.2f}" != "0.00"


def compact_btc_change(value: float) -> str:
    if abs(value) >= 1e4:
        return f"{value / 1e4:+.2f}万枚"
    return f"{value:+,.0f}枚"


def is_telegram_section_separator(line: str) -> bool:
    return bool(re.fullmatch(r"━{16,}", line))


def market_summary_with_separators(lines: list[str]) -> list[str]:
    section_headings = {
        "市场现货（亿美元）",
        "市场合约（亿美元）",
        "Hyperliquid清算价（BTC）",
        "美国国债",
        "ETH 质押",
        "稳定币",
        "现货ETF资金流（亿美元）",
        "Strategy（微策略）",
        "美国宏观日程",
    }
    separated: list[str] = []
    for raw_line in lines:
        line = raw_line.replace("（CoinGecko）", "")
        if is_telegram_section_separator(line):
            continue
        if (
            line in section_headings
            or line.startswith("链上确认交易（截至 ")
            or line.startswith("Hyperliquid清算价（BTC，缓存 ")
            or line.startswith("现货ETF资金流（亿美元，缓存 ")
        ) and separated:
            separated.append(TELEGRAM_SECTION_SEPARATOR)
        separated.append(line)
    return separated


def refresh_cached_summary_etf(
    summary: str,
    summary_captured_at: dt.datetime | None,
) -> str:
    snapshot, captured_at, _ = load_spot_etf_flow_cache()
    if snapshot is None or captured_at is None:
        return summary
    if summary_captured_at is not None and captured_at <= summary_captured_at:
        return summary
    etf_lines = spot_etf_summary_lines(snapshot)
    if not etf_lines:
        return summary
    lines = summary.splitlines()
    start = next(
        (
            index
            for index, line in enumerate(lines)
            if line == "现货ETF资金流（亿美元）"
            or line.startswith("现货ETF资金流（亿美元，缓存 ")
        ),
        None,
    )
    if start is None:
        return summary
    end = next(
        (
            index
            for index in range(start + 1, len(lines))
            if is_telegram_section_separator(lines[index])
        ),
        len(lines),
    )
    return "\n".join(lines[:start] + etf_lines + lines[end:]).strip()


def normalize_stablecoin_summary_labels(summary: str) -> str:
    return (
        summary.replace("链变化 ", "链上流通量变化 ")
        .replace("净增发", "净增")
        .replace("净销毁", "净减")
    )


def summary_blocks(summary: str) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in summary.splitlines():
        if is_telegram_section_separator(line):
            if current:
                blocks.append(current)
                current = []
            continue
        current.append(line)
    if current:
        blocks.append(current)
    return blocks


def summary_block_key(block: list[str]) -> str:
    if not block:
        return ""
    key = re.sub(r"（缓存\s+\d{2}-\d{2}\s+\d{2}:\d{2}）$", "", block[0])
    key = re.sub(r"（亿美元，缓存\s+\d{2}-\d{2}\s+\d{2}:\d{2}）$", "（亿美元）", key)
    key = re.sub(r"（BTC，缓存\s+\d{2}-\d{2}\s+\d{2}:\d{2}）$", "（BTC）", key)
    return key


def merge_partial_market_summary(
    current_summary: str,
    cached_summary: str,
    cached_at: dt.datetime | None,
) -> str:
    current_blocks = summary_blocks(current_summary)
    cached_blocks = summary_blocks(cached_summary)
    if not cached_blocks:
        return current_summary
    current_by_key = {
        summary_block_key(block): block
        for block in current_blocks
        if summary_block_key(block)
    }
    cached_suffix = ""
    if cached_at is not None:
        cached_suffix = f"（缓存 {cached_at.strftime('%m-%d %H:%M')}）"
    merged: list[list[str]] = []
    used: set[str] = set()
    for cached_block in cached_blocks:
        key = summary_block_key(cached_block)
        block = current_by_key.get(key)
        if block is None:
            block = list(cached_block)
            if cached_suffix and block:
                block[0] = f"{block[0]}{cached_suffix}"
        else:
            used.add(key)
        merged.append(block)
    for current_block in current_blocks:
        if summary_block_key(current_block) not in used and summary_block_key(current_block) not in {
            summary_block_key(block) for block in cached_blocks
        }:
            merged.append(current_block)
    return f"\n{TELEGRAM_SECTION_SEPARATOR}\n".join(
        "\n".join(block).strip() for block in merged if block
    ).strip()


def fetch_stablecoin_summary() -> str:
    cached_summary, cached_at, failed_at = load_market_summary_cache()
    cached_summary = normalize_stablecoin_summary_labels(cached_summary)
    cached_summary = refresh_cached_summary_etf(cached_summary, cached_at)
    now = cn_now()
    if cached_at is not None:
        cache_age = (now - cached_at).total_seconds()
        if 0 <= cache_age < MARKET_SUMMARY_CACHE_TTL_SECONDS:
            return cached_summary
    if failed_at is not None and cached_summary:
        failure_age = (now - failed_at).total_seconds()
        if 0 <= failure_age < MARKET_SUMMARY_FAILURE_COOLDOWN_SECONDS:
            print("[market-cache] refresh cooldown active", file=sys.stderr)
            return cached_summary

    dex_volume: dict[str, float] = {}
    global_volume: dict[str, float] = {}
    derivatives_volume: dict[str, float] = {}
    chain_activity: dict[str, Any] = {}
    coinglass_snapshot: dict[str, Any] = {}
    hyperliquid_liquidation: dict[str, Any] = {}
    coinglass_market_structure: dict[str, Any] = {}
    eth_staking: dict[str, float] = {}
    us_treasury_debt: dict[str, Any] = {}
    us_treasury_yields: dict[str, Any] = {}
    spot_etf_flows: dict[str, Any] = {}
    etf_lines: list[str] = []
    strategy_btc: dict[str, Any] = {}
    bitmine_eth: dict[str, Any] = {}
    us_macro_calendar: dict[str, dt.datetime] = {}
    supply: dict[str, dict[str, float]] = {}
    volumes: dict[str, dict[str, float]] = {}
    derivatives_snapshot: float | None = None
    eth_staking_snapshot: dict[str, float] | None = None
    market_fetch_failed = False
    market_errors = (OSError, ValueError, TypeError, KeyError, AttributeError, json.JSONDecodeError)
    previous_day = (cn_now().date() - dt.timedelta(days=1)).isoformat()
    try:
        previous_derivatives = previous_derivatives_volume(previous_day)
        previous_eth_staking = previous_eth_staking_total(previous_day)
    except market_errors as exc:
        market_fetch_failed = True
        previous_derivatives = None
        previous_eth_staking = None
        print(f"[market-snapshot-error] {type(exc).__name__}: {exc}", file=sys.stderr)
    source_jobs = {
        "dex_volume": (fetch_dex_volume, market_errors, "dex-volume", True),
        "global_volume": (fetch_global_volume, market_errors, "global-volume", True),
        "chain_activity": (
            fetch_chain_activity,
            market_errors,
            "chain-activity",
            False,
        ),
        "derivatives_current": (fetch_derivatives_volume, market_errors, "derivatives-volume", True),
        "eth_staking_current": (fetch_eth_staking_metrics, market_errors, "eth-staking", True),
        "us_treasury_debt": (fetch_us_treasury_debt, market_errors, "us-treasury-debt", True),
        "us_treasury_yields": (
            fetch_us_treasury_yields,
            (*market_errors, ET.ParseError),
            "us-treasury-yield",
            True,
        ),
        "supply": (fetch_stablecoin_supply, market_errors, "stablecoin-supply", True),
        "volumes": (fetch_stablecoin_volumes, market_errors, "stablecoin-volume", True),
        "strategy_btc": (fetch_strategy_btc, market_errors, "strategy-btc", False),
        "us_macro_calendar": (
            fetch_us_macro_calendar,
            market_errors,
            "us-macro-calendar",
            False,
        ),
        "bitmine_eth": (
            fetch_bitmine_eth,
            (OSError, ValueError, TypeError, KeyError, AttributeError),
            "bitmine-eth",
            False,
        ),
    }
    fetched: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {
            name: executor.submit(job[0])
            for name, job in source_jobs.items()
        }
        try:
            coinglass_snapshot = fetch_coinglass_snapshot()
            hyperliquid_liquidation = coinglass_snapshot
            market_structure = coinglass_snapshot.get("market_structure")
            if isinstance(market_structure, dict):
                coinglass_market_structure = dict(market_structure)
                if coinglass_snapshot.get("_stale"):
                    coinglass_market_structure["_stale"] = True
                    if coinglass_snapshot.get("_captured_at"):
                        coinglass_market_structure["_captured_at"] = (
                            coinglass_snapshot["_captured_at"]
                        )
        except Exception as exc:
            print(
                f"[coinglass-cache-error] {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
        try:
            spot_etf_flows = fetch_spot_etf_flow_snapshot()
            etf_lines = spot_etf_summary_lines(spot_etf_flows)
            if not etf_lines:
                raise ValueError("incomplete spot ETF flow snapshot")
        except Exception as exc:
            market_fetch_failed = True
            print(f"[spot-etf-cache-error] {type(exc).__name__}: {exc}", file=sys.stderr)
        for name, future in futures.items():
            _, errors, label, required = source_jobs[name]
            try:
                fetched[name] = future.result()
            except errors as exc:
                if required:
                    market_fetch_failed = True
                print(f"[{label}-error] {type(exc).__name__}: {exc}", file=sys.stderr)

    dex_volume = fetched.get("dex_volume", {})
    global_volume = fetched.get("global_volume", {})
    chain_activity = fetched.get("chain_activity", {})
    strategy_btc = fetched.get("strategy_btc", {})
    if strategy_btc:
        try:
            save_strategy_btc_cache(strategy_btc)
        except market_errors as exc:
            print(f"[strategy-btc-cache-error] {type(exc).__name__}: {exc}", file=sys.stderr)
    else:
        try:
            strategy_btc = load_strategy_btc_cache()
            if strategy_btc:
                verified_date = strategy_btc["verified_date"].isoformat()
                print(
                    f"[strategy-btc-cache] using last verified record from {verified_date}",
                    file=sys.stderr,
                )
        except market_errors as exc:
            print(f"[strategy-btc-cache-error] {type(exc).__name__}: {exc}", file=sys.stderr)
    bitmine_eth = fetched.get("bitmine_eth", {})
    us_macro_calendar = fetched.get("us_macro_calendar", {})
    supply = fetched.get("supply", {})
    volumes = fetched.get("volumes", {})
    us_treasury_debt = fetched.get("us_treasury_debt", {})
    us_treasury_yields = fetched.get("us_treasury_yields", {})
    if "derivatives_current" in fetched:
        current = float(fetched["derivatives_current"])
        derivatives_volume = {"current": current}
        if previous_derivatives is not None:
            delta = current - previous_derivatives
            derivatives_volume["delta"] = delta
            derivatives_volume["percent"] = (
                delta / previous_derivatives * 100 if previous_derivatives else 0.0
            )
        derivatives_snapshot = current
    if "eth_staking_current" in fetched:
        current_staking = dict(fetched["eth_staking_current"])
        eth_staking = current_staking
        if previous_eth_staking is not None:
            eth_staking["delta"] = current_staking["total"] - previous_eth_staking
        eth_staking_snapshot = current_staking

    today = cn_now().date().isoformat()
    if derivatives_snapshot is not None:
        save_derivatives_snapshot(today, derivatives_snapshot)
    if eth_staking_snapshot is not None:
        save_eth_staking_snapshot(today, eth_staking_snapshot)

    market_lines: list[str] = []
    spot_lines: list[str] = []
    if global_volume or coinglass_market_structure:
        market_lines.append("加密市场")
        if global_volume:
            market_lines.append(
                f"总市值 {global_volume['market_cap'] / 1e12:.2f}万亿美元 | "
                f"24H {global_volume['market_cap_percent']:+.2f}%"
            )
        if coinglass_market_structure:
            dominance_line = (
                f"BTC占比 {coinglass_market_structure['btc_dominance']:.2f}% | "
                f"24H {coinglass_market_structure['btc_dominance_change_24h']:+.2f}%"
            )
            if global_volume:
                dominance_line += f" | ETH占比 {global_volume['eth_dominance']:.2f}%"
            market_lines.extend([
                dominance_line,
                f"交易所BTC {coinglass_market_structure['exchange_balance'] / 1e4:.2f}万枚 | "
                f"24H {compact_btc_change(coinglass_market_structure['exchange_balance_change_24h'])} | "
                f"7D {compact_btc_change(coinglass_market_structure['exchange_balance_change_7d'])} | "
                f"30D {compact_btc_change(coinglass_market_structure['exchange_balance_change_30d'])}",
            ])
        elif global_volume:
            market_lines.append(
                f"BTC占比 {global_volume['btc_dominance']:.2f}% | "
                f"ETH占比 {global_volume['eth_dominance']:.2f}%"
            )
        spot_lines.append(
            f"全网 {global_volume['current'] / 1e8:.2f}亿 | "
            f"{signed_yi(global_volume['delta'])}（{global_volume['percent']:+.2f}%）"
        )
    if dex_volume:
        spot_lines.append(
            f"DEX {dex_volume['current'] / 1e8:.2f}亿 | "
            f"{signed_yi(dex_volume['delta'])}（{dex_volume['percent']:+.2f}%）"
        )
    if global_volume and dex_volume:
        cex_current = global_volume["current"] - dex_volume["current"]
        cex_delta = global_volume["delta"] - dex_volume["delta"]
        cex_previous = cex_current - cex_delta
        if cex_current >= 0 and cex_previous > 0:
            spot_lines.append(
                f"CEX估算 {cex_current / 1e8:.2f}亿 | "
                f"{signed_yi(cex_delta)}（{cex_delta / cex_previous * 100:+.2f}%）"
            )
    if spot_lines:
        market_lines.extend(["市场现货（亿美元）", *spot_lines])
    if derivatives_volume:
        futures_text = f"全网 {derivatives_volume['current'] / 1e8:.2f}亿"
        if "delta" in derivatives_volume:
            futures_text += (
                f" | {signed_yi(derivatives_volume['delta'])}"
                f"（{derivatives_volume['percent']:+.2f}%）"
            )
        market_lines.extend(["市场合约（亿美元）", futures_text])
    if chain_activity:
        record_date = chain_activity["record_date"].strftime("%m-%d")
        assets = chain_activity["assets"]
        market_lines.extend([
            f"链上确认交易（截至 {record_date}）",
            f"BTC {assets['btc']['transactions'] / 1e4:.2f}万笔 | "
            f"24H {assets['btc']['percent']:+.2f}% | "
            f"较前7日均 {assets['btc']['seven_day_average_percent']:+.2f}%",
            f"ETH {assets['eth']['transactions'] / 1e4:.2f}万笔 | "
            f"24H {assets['eth']['percent']:+.2f}% | "
            f"较前7日均 {assets['eth']['seven_day_average_percent']:+.2f}%",
        ])
    if hyperliquid_liquidation:
        liquidation_heading = "Hyperliquid清算价（BTC）"
        if hyperliquid_liquidation.get("_stale"):
            captured_at = parse_cache_timestamp(hyperliquid_liquidation.get("_captured_at"))
            if captured_at is not None:
                liquidation_heading = (
                    "Hyperliquid清算价（BTC，缓存 "
                    f"{captured_at.strftime('%m-%d %H:%M')}）"
                )
        long_lines = [
            f"多头 {liquidation_level_text(level)}"
            for level in hyperliquid_liquidation.get("long_levels", [])
            if isinstance(level, dict)
        ]
        short_lines = [
            f"空头 {liquidation_level_text(level)}"
            for level in hyperliquid_liquidation.get("short_levels", [])
            if isinstance(level, dict)
        ]
        if long_lines and short_lines:
            liquidation_lines = [
                liquidation_heading,
                f"现价 {compact_usd_price(float(hyperliquid_liquidation['current_price']))}",
                *long_lines,
                *short_lines,
            ]
            ratio = hyperliquid_liquidation.get("long_short_ratio")
            if isinstance(ratio, dict):
                long_users = int(ratio["long_users"])
                short_users = int(ratio["short_users"])
                total_users = long_users + short_users
                long_percent = long_users / total_users * 100
                short_percent = short_users / total_users * 100
                ratio_value = float(ratio["ratio"])
                if long_users > short_users:
                    crowding = "多单人数占优"
                elif short_users > long_users:
                    crowding = "空单人数占优"
                else:
                    crowding = "人数相当"
                liquidation_lines.extend([
                    "持仓人数多空比（1天）",
                    f"多单 {long_users:,}（{long_percent:.2f}%） | "
                    f"空单 {short_users:,}（{short_percent:.2f}%）",
                    f"多空比 {ratio_value:.2f}（{crowding}）",
                ])
            market_lines.extend(liquidation_lines)
    treasury_lines: list[str] = []
    if us_treasury_debt:
        record_date = us_treasury_debt["record_date"].strftime("%m-%d")
        treasury_lines.extend([
            "美国国债",
            f"债务总额 {us_treasury_debt['current'] / 1e12:.2f}万亿美元 | "
            f"较前值 {signed_yi(us_treasury_debt['delta'])}美元（{record_date}）",
        ])
        if us_treasury_yields:
            yield_date = us_treasury_yields["record_date"].strftime("%m-%d")
            treasury_lines.extend([
                f"收益率（截至 {yield_date}）",
                f"2年 {us_treasury_yields['2y']:.2f}% | 5年 {us_treasury_yields['5y']:.2f}%",
                f"10年 {us_treasury_yields['10y']:.2f}% | 30年 {us_treasury_yields['30y']:.2f}%",
            ])
    if eth_staking:
        staking_lines = [f"质押量 {eth_staking['total'] / 1e4:.2f}万枚"]
        if "delta" in eth_staking and f"{abs(eth_staking['delta']) / 1e4:.2f}" != "0.00":
            staking_lines[0] += f" | 较昨日 {eth_staking['delta'] / 1e4:+.2f}万枚"
        staking_lines.append(
            f"比例 {compact_percent(eth_staking['percent'])} | APR {compact_percent(eth_staking['apr'])}"
        )
        market_lines.extend(["ETH 质押", *staking_lines])
    stablecoin_lines: list[str] = []
    stablecoin_sections: list[str] = []
    for symbol in ("USDT", "USDC"):
        fields: list[str] = []
        chain_fields: list[str] = []
        if symbol in supply:
            item = supply[symbol]
            fields.append(f"流通 {item['current'] / 1e8:.2f}亿 | {signed_yi(item['delta'])}")
            chain_deltas = item.get("chain_deltas", {})
            if isinstance(chain_deltas, dict):
                tracked_delta = 0.0
                for label, chain in (("TRX链", "Tron"), ("ETH链", "Ethereum")):
                    if chain not in chain_deltas:
                        continue
                    delta = float(chain_deltas[chain])
                    tracked_delta += delta
                    if visible_yi_change(delta):
                        chain_fields.append(f"{label}{chain_delta_text(delta, net=True)}")
                if chain_deltas:
                    other_delta = float(item["delta"]) - tracked_delta
                    if visible_yi_change(other_delta):
                        chain_fields.append(f"其他链{chain_delta_text(other_delta, net=True)}")
            if chain_fields:
                fields.append("链上流通量变化 " + " | ".join(chain_fields))
        if symbol in volumes:
            item = volumes[symbol]
            fields.append(
                f"现货成交 {item['current'] / 1e8:.2f}亿 | "
                f"{signed_yi(item['delta'])}（{item['percent']:+.2f}%）"
            )
        if fields:
            fields[0] = f"{symbol}{fields[0]}"
            if stablecoin_sections:
                stablecoin_sections.append(TELEGRAM_VISUAL_GAP)
            stablecoin_sections.extend(fields)
    if stablecoin_sections:
        stablecoin_lines.extend(["稳定币", *stablecoin_sections])
    strategy_lines: list[str] = []
    if strategy_btc:
        record_date = strategy_btc["record_date"].strftime("%m-%d")
        holdings_as_of = strategy_btc["holdings_as_of"].strftime("%m-%d")
        strategy_lines.extend([
            "Strategy（微策略）",
            f"BTC持仓 {strategy_btc['holdings']:,}枚 | 持仓截至 {holdings_as_of}",
            f"上次变化 {strategy_btc['change']:+,}枚（{record_date}）",
            f"平均成本 ${strategy_btc['average_price']:,.0f}/枚 | "
            f"累计成本 {strategy_btc['total_cost_millions'] / 100:.2f}亿美元",
        ])
    macro_lines = us_macro_calendar_lines(us_macro_calendar)
    bitmine_lines: list[str] = []
    if bitmine_eth:
        record_date = bitmine_eth["record_date"].strftime("%m-%d")
        bitmine_lines.extend([
            "BitMine（BMNR）",
            f"ETH持仓 {bitmine_eth['holdings'] / 1e4:.2f}万枚 | "
            f"持仓变化 {bitmine_eth['change'] / 1e4:+.2f}万枚（{record_date}披露）",
            f"供应占比 {compact_percent(bitmine_eth['supply_percent'])} | "
            f"已质押 {bitmine_eth['staked'] / 1e4:.2f}万枚",
        ])
    summary = "\n".join(
        market_summary_with_separators(
            market_lines
            + stablecoin_lines
            + etf_lines
            + strategy_lines
            + bitmine_lines
            + macro_lines
            + treasury_lines
        )
    )
    if market_fetch_failed:
        if cached_summary:
            summary = merge_partial_market_summary(summary, cached_summary, cached_at)
            print("[market-cache] merged current modules with cached failures", file=sys.stderr)
        elif not summary:
            print("[market-cache] no current or cached market data", file=sys.stderr)
            return ""
        return summary
    if summary:
        save_market_summary_cache(summary)
    return summary


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def parse_kols(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = re.sub(r"^\d+[.)]\s*", "", line)
        parts = [p.strip() for p in line.split("|")]
        handle_match = re.search(r"@([A-Za-z0-9_]{1,32})", line)
        if not handle_match:
            continue
        handle = "@" + handle_match.group(1)
        key = handle.lower()
        if key in seen:
            continue
        seen.add(key)
        name = parts[0] if parts else handle
        note = parts[2] if len(parts) >= 3 else ""
        rows.append({"name": name, "handle": handle, "note": note})
    return rows


def canonical_handle(value: Any) -> str:
    match = re.fullmatch(r"@?([A-Za-z0-9_]{1,32})", str(value or "").strip())
    return "@" + match.group(1) if match else ""


def resolve_handle_alias(handle: str, aliases: dict[str, Any]) -> str:
    start = canonical_handle(handle)
    mapping = {
        source.lower(): target
        for key, value in aliases.items()
        if (source := canonical_handle(key)) and (target := canonical_handle(value))
    }
    current = start
    seen: set[str] = set()
    while current and current.lower() in mapping:
        key = current.lower()
        if key in seen:
            return start
        seen.add(key)
        target = mapping[key]
        if target.lower() == key:
            return current
        current = target
    return current or start


def apply_handle_aliases(kols: list[dict[str, str]]) -> list[dict[str, str]]:
    store = load_json(TWEET_STORE, {"version": 1, "tweets": {}}, strict=True)
    aliases = store.get("handle_aliases", {})
    if not isinstance(aliases, dict):
        raise RuntimeError("invalid handle_aliases in tweets.json")
    resolved: list[dict[str, str]] = []
    for kol in kols:
        row = dict(kol)
        configured = row["handle"]
        current = resolve_handle_alias(configured, aliases)
        if current.lower() != configured.lower():
            row["configured_handle"] = configured
            row["handle"] = current
        resolved.append(row)
    return resolved


def apply_unavailable_recheck_policy(
    kols: list[dict[str, str]],
    force_recheck: bool = False,
) -> list[dict[str, str]]:
    if force_recheck:
        return kols
    store = load_json(TWEET_STORE, {"version": 1, "tweets": {}}, strict=True)
    statuses = store.get("kol_status", {})
    if not isinstance(statuses, dict):
        raise RuntimeError("invalid kol_status in tweets.json")
    today = cn_now().date()
    for kol in kols:
        identity = canonical_handle(kol.get("configured_handle") or kol.get("handle"))
        status = statuses.get(identity.lower(), {}) if identity else {}
        if not isinstance(status, dict):
            continue
        if status.get("unavailable_reason") != "suspended":
            continue
        if int(status.get("unavailable_days") or 0) < UNAVAILABLE_REMOVAL_DAYS:
            continue
        next_recheck_text = str(status.get("next_recheck_date") or "")
        try:
            next_recheck_date = dt.date.fromisoformat(next_recheck_text)
        except ValueError:
            last_unavailable_text = str(status.get("last_unavailable_date") or "")
            try:
                last_unavailable_date = dt.date.fromisoformat(last_unavailable_text)
            except ValueError:
                last_unavailable_date = today
            next_recheck_date = last_unavailable_date + dt.timedelta(
                days=UNAVAILABLE_RECHECK_INTERVAL_DAYS
            )
        if today >= next_recheck_date:
            continue
        kol["auto_recheck_paused"] = True
        kol["unavailable_days"] = int(status.get("unavailable_days") or 0)
        kol["next_recheck_date"] = next_recheck_date.isoformat()
        kol["unavailable_reason"] = "suspended"
        kol["auto_action"] = "recheck_until_reactivated"
    return kols


def cookies_from_env() -> list[dict[str, Any]]:
    auth = os.environ.get("X_AUTH", "").strip()
    ct0 = os.environ.get("X_CT0", "").strip()
    if not auth or not ct0:
        raise RuntimeError("missing X_AUTH or X_CT0")
    cookies = []
    for domain in [".x.com", "x.com", ".twitter.com", "twitter.com"]:
        cookies.append({
            "name": "auth_token",
            "value": auth,
            "domain": domain,
            "path": "/",
            "httpOnly": True,
            "secure": True,
            "sameSite": "None",
        })
        cookies.append({
            "name": "ct0",
            "value": ct0,
            "domain": domain,
            "path": "/",
            "httpOnly": False,
            "secure": True,
            "sameSite": "None",
        })
    return cookies


def route_static_assets(route: Any) -> None:
    req = route.request
    if req.resource_type in {"image", "media", "font"}:
        route.abort()
        return
    route.continue_()


EXTRACT_JS = r"""
({handle, cutoffMs, maxItems}) => {
  const clean = s => (s || '').replace(/\s+/g, ' ').trim();
  const out = [];
  const seen = new Set();
  const articleKeys = new Set();
  for (const art of Array.from(document.querySelectorAll('article'))) {
    const timeEl = art.querySelector('time');
    const datetime = timeEl ? timeEl.getAttribute('datetime') : '';
    const ms = datetime ? Date.parse(datetime) : NaN;
    const timeLink = timeEl ? timeEl.closest('a[href*="/status/"]') : null;
    let link = timeLink ? (timeLink.getAttribute('href') || '') : '';
    if (!link) {
      for (const a of Array.from(art.querySelectorAll('a[href*="/status/"]'))) {
        const href = a.getAttribute('href') || '';
        if (href.includes('/status/')) { link = href; break; }
      }
    }
    if (link.startsWith('/')) link = 'https://x.com' + link;
    const articleKey = link || datetime || clean(art.innerText || art.textContent || '').slice(0, 120);
    if (articleKey) articleKeys.add(articleKey);
    if (!Number.isFinite(ms) || ms < cutoffMs) continue;
    const textNode = art.querySelector('[data-testid="tweetText"]');
    const text = clean(textNode ? (textNode.innerText || textNode.textContent || '') : '');
    if (!text) continue;
    const externalUrls = Array.from(textNode.querySelectorAll('a[href]'))
      .map(a => a.href || '')
      .filter(href => /^https?:\/\//i.test(href) &&
        !/^https?:\/\/(?:[^/]+\.)?(?:x\.com|twitter\.com)\//i.test(href));
    const key = link || `${handle}:${datetime}:${text.slice(0, 80)}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({
      handle,
      text,
      url: link,
      external_urls: Array.from(new Set(externalUrls)),
      created_at: datetime,
      created_at_ms: ms
    });
  }
  out.sort((a, b) => b.created_at_ms - a.created_at_ms);
  return { rows: out.slice(0, maxItems), articleKeys: Array.from(articleKeys) };
}
"""

EXPAND_TWEETS_JS = r"""
() => {
  const buttons = Array.from(document.querySelectorAll(
    'article button[data-testid="tweet-text-show-more-link"]'
  )).filter(button => button.closest('article')?.querySelector('[data-testid="tweetText"]'));
  for (const button of buttons) button.click();
  return buttons.length;
}
"""

PAGE_HEALTH_JS = r"""
() => {
  const path = (location.pathname || '').toLowerCase();
  const rawText = (document.body?.innerText || '').slice(0, 5000);
  const text = rawText.toLowerCase();
  const has = values => values.some(value => text.includes(value));
  const hasMain = Boolean(document.querySelector('main, [data-testid="primaryColumn"]'));
  const hasTimeline = Boolean(document.querySelector(
    '[data-testid="primaryColumn"], article, section[aria-label*="Timeline"], section[aria-label*="时间线"]'
  ));
  const unavailableStateTexts = Array.from(document.querySelectorAll(
    '[data-testid="empty_state_header_text"], [data-testid="empty_state_body_text"]'
  )).map(node => (node.innerText || node.textContent || '').replace(/\s+/g, ' ').trim().toLowerCase());
  const stateMatches = values => unavailableStateTexts.some(stateText =>
    values.some(value => stateText === value || stateText.startsWith(value))
  );
  const accountMissing = stateMatches([
    "this account doesn't exist", '此账号不存在'
  ]);
  const accountSuspended = stateMatches([
    'account suspended', '账号已被冻结'
  ]);
  const verificationRequired =
    path.includes('/account/access') ||
    path.includes('/i/flow/account-access') ||
    path.includes('/i/flow/verify') ||
    path.includes('/i/flow/challenge') ||
    Boolean(document.querySelector(
      'iframe[src*="arkoselabs"], iframe[src*="captcha"], [data-testid="ocfEnterTextTextInput"]'
    )) ||
    (!hasMain && has([
      'authenticate your account', 'verify your identity', 'confirm your identity',
      'prove you are human', 'complete the following actions', 'suspicious activity',
      '验证你的身份', '确认你的身份', '验证您的身份',
      '确认您的身份', '请完成以下操作', '可疑活动'
    ]));
  return {
    loginRequired: path.includes('/i/flow/login') || path === '/login' ||
      Boolean(document.querySelector('input[autocomplete="username"]')),
    verificationRequired,
    errorPage: Boolean(document.querySelector('[data-testid="error-detail"]')) ||
      ((!hasMain || !hasTimeline) && has([
        'rate limit exceeded', 'something went wrong', 'try reloading',
        'verify you are human', 'unusual activity', 'automated requests',
        'temporarily limited', '超过频率限制', '出错了，请尝试重新加载',
        '请验证您是人类', '异常活动', '自动请求', '暂时受到限制'
      ])),
    accountUnavailable: accountMissing || accountSuspended,
    accountUnavailableReason: accountSuspended ? 'suspended' : accountMissing ? 'missing' : '',
    hasMain,
    hasTimeline,
    path,
    title: (document.title || '').slice(0, 160),
    textSample: rawText.replace(/\s+/g, ' ').trim().slice(0, 300)
  };
}
"""

COINGLASS_LIQUIDATION_OPTION_JS = r"""
() => {
  const element = document.querySelector('.echarts-for-react');
  if (!element) return null;
  const reactKey = Object.keys(element).find(key => key.startsWith('__reactFiber$'));
  let fiber = reactKey ? element[reactKey] : null;
  let option = null;
  for (let index = 0; fiber && index < 18; index += 1, fiber = fiber.return) {
    const props = fiber.memoizedProps || {};
    if (props.option && Array.isArray(props.option.series)) {
      option = props.option;
      break;
    }
  }
  if (!option) return null;
  const prices = Array.isArray(option.xAxis) && Array.isArray(option.xAxis[0]?.data)
    ? option.xAxis[0].data
    : [];
  const currentSeries = option.series.find(series => series?.markLine?.data?.length);
  const currentIndex = Number(currentSeries?.markLine?.data?.[0]?.xAxis);
  const currentPrice = Number(prices[currentIndex]);
  const points = name => {
    const series = option.series.find(item => item?.name === name && item?.type === 'bar');
    const data = Array.isArray(series?.data) ? series.data : [];
    return data.map((raw, index) => ({
      price: Number(prices[index]),
      intensity: Number(typeof raw === 'number' ? raw : raw?.value)
    })).filter(point => Number.isFinite(point.price) && point.price > 0 &&
      Number.isFinite(point.intensity) && point.intensity > 0);
  };
  return {
    symbol: 'BTC',
    current_price: currentPrice,
    long_points: points('多单'),
    short_points: points('空单')
  };
}
"""

COINGLASS_LONG_SHORT_RATIO_JS = r"""
() => {
  const nodes = Array.from(document.querySelectorAll('*'));
  const valueFor = label => {
    const labelNode = nodes.find(node =>
      node.children.length === 0 && (node.textContent || '').trim() === label
    );
    const valueText = labelNode?.parentElement?.lastElementChild?.textContent || '';
    return Number(valueText.replace(/,/g, '').trim());
  };
  return {
    interval: 'day',
    long_users: valueFor('多单人数'),
    short_users: valueFor('空单人数'),
    ratio: valueFor('人数多空比')
  };
}
"""

COINGLASS_MARKET_STRUCTURE_JS = r"""
() => {
  const leafTexts = href => {
    const link = document.querySelector(`a.card-link[href="${href}"]`);
    if (!link) return [];
    return Array.from(link.querySelectorAll('*'))
      .filter(node => node.children.length === 0)
      .map(node => (node.textContent || '').trim())
      .filter(Boolean);
  };
  const dominance = leafTexts('/zh/pro/i/MarketCap');
  const hasLabel = dominance.some(text =>
    text.includes('BTC') && text.includes('市值占比')
  );
  const percentages = dominance.filter(text =>
    /^[+-]?\d+(?:\.\d+)?%$/.test(text.replace(/,/g, ''))
  );
  if (!hasLabel || percentages.length !== 2) {
    return {dominance_change: '', dominance: ''};
  }
  return {
    dominance_change: percentages[0],
    dominance: percentages[1]
  };
}
"""

COINGLASS_BALANCE_TOTAL_JS = r"""
() => {
  const rows = Array.from(document.querySelectorAll('table tr'));
  const total = rows.find(row =>
    Array.from(row.querySelectorAll('td')).some(cell =>
      (cell.textContent || '').trim() === '总计'
    )
  );
  if (!total) return null;
  const cells = Array.from(total.querySelectorAll('td'))
    .map(cell => (cell.textContent || '').trim());
  if (cells.length < 6) return null;
  return {
    balance: cells[cells.length - 4],
    balance_change_24h: cells[cells.length - 3],
    balance_change_7d: cells[cells.length - 2],
    balance_change_30d: cells[cells.length - 1]
  };
}
"""

STATUS_AUTHOR_JS = r"""
statusId => {
  const statusPath = `/status/${statusId}`;
  const article = Array.from(document.querySelectorAll('article')).find(node =>
    Array.from(node.querySelectorAll('a[href*="/status/"]')).some(link =>
      (link.getAttribute('href') || '').split('?')[0].endsWith(statusPath)
    )
  );
  const userName = article?.querySelector('[data-testid="User-Name"]');
  if (!userName) return '';
  for (const link of Array.from(userName.querySelectorAll('a[href]'))) {
    const path = (link.getAttribute('href') || '').split('?')[0].replace(/\/$/, '');
    const match = path.match(/^\/([A-Za-z0-9_]{1,32})$/);
    if (match) return `@${match[1]}`;
  }
  return '';
}
"""


def record_page_health(
    diagnostics: dict[str, Any] | None,
    phase: str,
    health: dict[str, Any],
) -> None:
    if diagnostics is None:
        return
    diagnostics["page_health"] = {
        "phase": phase,
        "path": str(health.get("path") or "")[:200],
        "title": str(health.get("title") or "")[:160],
        "text_sample": str(health.get("textSample") or "")[:300],
        "login_required": bool(health.get("loginRequired")),
        "error_page": bool(health.get("errorPage")),
        "account_unavailable": bool(health.get("accountUnavailable")),
        "account_unavailable_reason": str(
            health.get("accountUnavailableReason") or ""
        )[:40],
        "has_main": bool(health.get("hasMain")),
    }


def recovery_timeout_ms(default_ms: int, deadline_monotonic: float | None) -> int:
    if deadline_monotonic is None:
        return default_ms
    remaining_ms = int((deadline_monotonic - time.monotonic()) * 1000)
    if remaining_ms <= 0:
        raise RecoveryBudgetExceeded("X recovery budget exhausted")
    return max(1, min(default_ms, remaining_ms))


def recovery_wait_for_timeout(
    page: Any,
    wait_ms: int,
    deadline_monotonic: float | None,
) -> None:
    bounded_ms = recovery_timeout_ms(wait_ms, deadline_monotonic)
    page.wait_for_timeout(bounded_ms)
    if bounded_ms < wait_ms:
        raise RecoveryBudgetExceeded("X recovery budget exhausted")


def wait_for_x_page_ready(
    page: Any,
    wait_ms: int,
    deadline_monotonic: float | None,
) -> None:
    """Wait only until X exposes a usable state, up to the configured cap."""
    bounded_ms = recovery_timeout_ms(wait_ms, deadline_monotonic)
    started = time.monotonic()
    ready_at: float | None = None
    while True:
        health = page.evaluate(PAGE_HEALTH_JS)
        if any(
            health.get(key)
            for key in ("loginRequired", "errorPage", "accountUnavailable")
        ):
            return
        if health.get("hasMain"):
            if ready_at is None:
                ready_at = time.monotonic()
            settled_ms = int((time.monotonic() - ready_at) * 1000)
            if settled_ms >= min(X_PAGE_MIN_SETTLE_MS, bounded_ms):
                return
        else:
            ready_at = None
        elapsed_ms = int((time.monotonic() - started) * 1000)
        remaining_ms = bounded_ms - elapsed_ms
        if remaining_ms <= 0:
            return
        page.wait_for_timeout(min(200, remaining_ms))


def wait_for_x_scroll_content(
    page: Any,
    wait_ms: int,
    previous_article_count: int,
    deadline_monotonic: float | None,
) -> None:
    """Wait for lazy-loaded articles, returning early when the DOM advances."""
    bounded_ms = recovery_timeout_ms(wait_ms, deadline_monotonic)
    started = time.monotonic()
    min_settle_ms = min(X_SCROLL_MIN_SETTLE_MS, bounded_ms)
    while True:
        article_count = int(
            page.evaluate("() => document.querySelectorAll('article').length") or 0
        )
        elapsed_ms = int((time.monotonic() - started) * 1000)
        if article_count > previous_article_count and elapsed_ms >= min_settle_ms:
            return
        remaining_ms = bounded_ms - elapsed_ms
        if remaining_ms <= 0:
            return
        page.wait_for_timeout(min(150, remaining_ms))


def ensure_x_page_healthy(
    page: Any,
    account_page: bool = False,
    diagnostics: dict[str, Any] | None = None,
    phase: str = "page",
    deadline_monotonic: float | None = None,
) -> None:
    recovery_timeout_ms(30_000, deadline_monotonic)
    health = page.evaluate(PAGE_HEALTH_JS)
    if not health.get("hasMain") and not any(
        health.get(key)
        for key in (
            "loginRequired",
            "verificationRequired",
            "errorPage",
            "accountUnavailable",
        )
    ):
        page.reload(
            wait_until="domcontentloaded",
            timeout=recovery_timeout_ms(45_000, deadline_monotonic),
        )
        recovery_wait_for_timeout(page, 2500, deadline_monotonic)
        health = page.evaluate(PAGE_HEALTH_JS)
    if health.get("loginRequired"):
        record_page_health(diagnostics, phase, health)
        raise RuntimeError(X_AUTHENTICATION_REQUIRED_ERROR)
    if health.get("verificationRequired"):
        record_page_health(diagnostics, phase, health)
        raise RuntimeError(X_VERIFICATION_REQUIRED_ERROR)
    if health.get("errorPage"):
        record_page_health(diagnostics, phase, health)
        raise RuntimeError(X_RATE_LIMIT_ERROR)
    if account_page and health.get("accountUnavailable"):
        record_page_health(diagnostics, phase, health)
        raise RuntimeError(ACCOUNT_UNAVAILABLE_ERROR)
    if not health.get("hasMain"):
        record_page_health(diagnostics, phase, health)
        raise RuntimeError(PAGE_RENDER_ERROR)


def new_x_context(browser: Any, cookies: list[dict[str, Any]]) -> Any:
    context = browser.new_context(locale="zh-CN", timezone_id="Asia/Shanghai")
    context.route("**/*", route_static_assets)
    context.add_cookies(cookies)
    return context


def chromium_launch_env() -> dict[str, str]:
    env = dict(os.environ)
    env["CHROME_LOG_FILE"] = os.devnull
    return env


def chromium_log_file_arg() -> str:
    return f"--log-file={os.devnull}"


def cleanup_chromium_debug_log() -> None:
    path = ROOT / "debug.log"
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError as exc:
        print(
            f"[chromium-log-cleanup] skipped {path.name}: {type(exc).__name__}: {exc}",
            file=sys.stderr,
            flush=True,
        )


def select_liquidation_levels(
    points: Any,
    current_price: float,
    direction: str,
) -> list[dict[str, float]]:
    candidates: list[dict[str, float]] = []
    if not isinstance(points, list):
        return candidates
    for point in points:
        if not isinstance(point, dict):
            continue
        try:
            price = float(point.get("price"))
            intensity = float(point.get("intensity"))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(price) or not math.isfinite(intensity) or price <= 0 or intensity <= 0:
            continue
        distance_percent = (price / current_price - 1) * 100
        if direction == "long" and distance_percent >= 0:
            continue
        if direction == "short" and distance_percent <= 0:
            continue
        candidates.append({
            "price": price,
            "intensity": intensity,
            "distance_percent": distance_percent,
        })
    nearby = [
        point
        for point in candidates
        if abs(point["distance_percent"]) <= COINGLASS_LIQUIDATION_DISTANCE_LIMIT_PERCENT
    ]
    ranked = nearby or candidates
    strongest = sorted(
        ranked,
        key=lambda point: point["intensity"],
        reverse=True,
    )[:COINGLASS_LIQUIDATION_LEVEL_LIMIT]
    return sorted(strongest, key=lambda point: abs(point["distance_percent"]))


def normalize_hyperliquid_liquidation(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("missing CoinGlass liquidation chart data")
    try:
        current_price = float(raw.get("current_price"))
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid CoinGlass current price") from exc
    if not math.isfinite(current_price) or current_price <= 0:
        raise ValueError("out-of-range CoinGlass current price")
    long_levels = select_liquidation_levels(raw.get("long_points"), current_price, "long")
    short_levels = select_liquidation_levels(raw.get("short_points"), current_price, "short")
    if not long_levels or not short_levels:
        raise ValueError("missing CoinGlass long or short liquidation levels")
    return {
        "symbol": "BTC",
        "current_price": current_price,
        "long_levels": long_levels,
        "short_levels": short_levels,
    }


def normalize_hyperliquid_long_short_ratio(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("missing CoinGlass long-short ratio data")
    try:
        long_users = int(float(raw.get("long_users")))
        short_users = int(float(raw.get("short_users")))
        ratio = float(raw.get("ratio"))
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid CoinGlass long-short ratio data") from exc
    if long_users <= 0 or short_users <= 0 or not math.isfinite(ratio) or ratio <= 0:
        raise ValueError("out-of-range CoinGlass long-short ratio data")
    calculated_ratio = long_users / short_users
    if abs(ratio - calculated_ratio) > max(0.02, calculated_ratio * 0.02):
        raise ValueError("inconsistent CoinGlass long-short ratio data")
    return {
        "interval": "day",
        "long_users": long_users,
        "short_users": short_users,
        "ratio": ratio,
    }


def normalize_coinglass_market_structure(raw: Any) -> dict[str, float]:
    if not isinstance(raw, dict):
        raise ValueError("missing CoinGlass market structure data")

    def parse_number(value: Any, suffix: str = "") -> float:
        text = str(value or "").strip().replace(",", "")
        if suffix and text.endswith(suffix):
            text = text[:-len(suffix)].strip()
        return float(text)

    try:
        dominance = parse_number(raw.get("dominance"), "%")
        dominance_change = parse_number(raw.get("dominance_change"), "%")
        balance_text = str(raw.get("balance") or "").strip()
        balance_multiplier = 1e4 if balance_text.endswith("万") else 1.0
        balance = parse_number(balance_text, "万") * balance_multiplier
        balance_change_24h = parse_number(raw.get("balance_change_24h"))
        balance_change_7d = parse_number(raw.get("balance_change_7d"))
        balance_change_30d = parse_number(raw.get("balance_change_30d"))
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid CoinGlass market structure data") from exc
    balance_changes = (balance_change_24h, balance_change_7d, balance_change_30d)
    values = (dominance, dominance_change, balance, *balance_changes)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("non-finite CoinGlass market structure data")
    if (
        not 0 <= dominance <= 100
        or balance <= 0
        or any(abs(change) > balance for change in balance_changes)
    ):
        raise ValueError("out-of-range CoinGlass market structure data")
    return {
        "btc_dominance": dominance,
        "btc_dominance_change_24h": dominance_change,
        "exchange_balance": balance,
        "exchange_balance_change_24h": balance_change_24h,
        "exchange_balance_change_7d": balance_change_7d,
        "exchange_balance_change_30d": balance_change_30d,
    }


def fetch_coinglass_live() -> dict[str, Any]:
    try:
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        from playwright.async_api import async_playwright
    except Exception as exc:
        raise RuntimeError("missing playwright for CoinGlass pages") from exc

    async def collect_snapshot() -> dict[str, Any]:
        chrome_path = os.environ.get("CHROME_PATH", "").strip() or None
        async with async_playwright() as playwright:
            launch_kwargs: dict[str, Any] = {
                "headless": True,
                "args": [
                    "--disable-gpu",
                    "--disable-logging",
                    chromium_log_file_arg(),
                    "--no-first-run",
                    "--no-default-browser-check",
                ],
                "env": chromium_launch_env(),
            }
            if chrome_path:
                launch_kwargs["executable_path"] = chrome_path
            browser = await playwright.chromium.launch(**launch_kwargs)
            try:
                if sys.platform.startswith("win"):
                    user_agent_platform = "Windows NT 10.0; Win64; x64"
                elif sys.platform == "darwin":
                    user_agent_platform = "Macintosh; Intel Mac OS X 10_15_7"
                else:
                    user_agent_platform = "X11; Linux x86_64"
                user_agent = (
                    f"Mozilla/5.0 ({user_agent_platform}) AppleWebKit/537.36 "
                    f"(KHTML, like Gecko) Chrome/{browser.version} Safari/537.36"
                )
                context = await browser.new_context(
                    locale="zh-CN",
                    timezone_id="Asia/Shanghai",
                    user_agent=user_agent,
                    extra_http_headers={"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
                )
                try:
                    async def route_assets(route: Any) -> None:
                        if route.request.resource_type in {"image", "media", "font"}:
                            await route.abort()
                        else:
                            await route.continue_()

                    await context.route("**/*", route_assets)

                    async def read_page(url: str, script: str, ready_key: str) -> Any:
                        page = await context.new_page()
                        deadline = time.monotonic() + COINGLASS_PAGE_WAIT_SECONDS
                        try:
                            try:
                                await page.goto(
                                    url,
                                    wait_until="domcontentloaded",
                                    timeout=15_000,
                                )
                            except PlaywrightTimeoutError:
                                pass
                            raw: Any = None
                            while time.monotonic() < deadline:
                                raw = await page.evaluate(script)
                                if isinstance(raw, dict) and raw.get(ready_key):
                                    return raw
                                await page.wait_for_timeout(500)
                            raise ValueError(f"CoinGlass page data timeout: {ready_key}")
                        finally:
                            await page.close()

                    liquidation_raw, ratio_raw, market_raw, balance_raw = await asyncio.gather(
                        read_page(
                            COINGLASS_HYPERLIQUID_LIQUIDATION_URL,
                            COINGLASS_LIQUIDATION_OPTION_JS,
                            "current_price",
                        ),
                        read_page(
                            COINGLASS_HYPERLIQUID_LONG_SHORT_RATIO_URL,
                            COINGLASS_LONG_SHORT_RATIO_JS,
                            "long_users",
                        ),
                        read_page(
                            COINGLASS_MARKET_OVERVIEW_URL,
                            COINGLASS_MARKET_STRUCTURE_JS,
                            "dominance",
                        ),
                        read_page(
                            COINGLASS_BALANCE_URL,
                            COINGLASS_BALANCE_TOTAL_JS,
                            "balance",
                        ),
                    )
                    snapshot = normalize_hyperliquid_liquidation(liquidation_raw)
                    snapshot["long_short_ratio"] = normalize_hyperliquid_long_short_ratio(
                        ratio_raw
                    )
                    snapshot["market_structure"] = normalize_coinglass_market_structure({
                        **market_raw,
                        **balance_raw,
                    })
                    return snapshot
                finally:
                    await context.close()
            finally:
                try:
                    await browser.close()
                finally:
                    cleanup_chromium_debug_log()

    return asyncio.run(collect_snapshot())


def fetch_coinglass_snapshot() -> dict[str, Any]:
    cached, captured_at, failed_at = load_coinglass_cache()
    now = cn_now()

    def stale_cached_snapshot() -> dict[str, Any]:
        if cached is None:
            return {}
        result = dict(cached)
        result["_stale"] = True
        if captured_at is not None:
            result["_captured_at"] = captured_at.isoformat(timespec="minutes")
        return result

    if cached is not None and captured_at is not None:
        cache_age = (now - captured_at).total_seconds()
        if 0 <= cache_age < COINGLASS_CACHE_TTL_SECONDS:
            return cached
    if failed_at is not None:
        failure_age = (now - failed_at).total_seconds()
        if 0 <= failure_age < COINGLASS_FAILURE_COOLDOWN_SECONDS:
            if cached is not None:
                print("[coinglass-cache] refresh cooldown; using last snapshot", file=sys.stderr)
                return stale_cached_snapshot()
            return {}
    started_at = time.monotonic()
    try:
        snapshot = fetch_coinglass_live()
    except Exception as exc:
        save_coinglass_failure()
        print(
            f"[coinglass-error] {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        if cached is not None:
            print("[coinglass-cache] using last successful snapshot", file=sys.stderr)
            return stale_cached_snapshot()
        return {}
    save_coinglass_cache(snapshot)
    market_structure = snapshot["market_structure"]
    print(
        f"[coinglass] BTC current={snapshot['current_price']:.2f} "
        f"long={len(snapshot['long_levels'])} short={len(snapshot['short_levels'])} "
        f"ratio={snapshot['long_short_ratio']['ratio']:.4f} "
        f"dominance={market_structure['btc_dominance']:.2f}% "
        f"balance={market_structure['exchange_balance']:.2f} "
        f"elapsed={time.monotonic() - started_at:.1f}s",
        file=sys.stderr,
    )
    return snapshot


def scrape_handle_url(
    page: Any,
    handle: str,
    url: str,
    account_page: bool,
    cutoff_ms: int,
    limit: int,
    scrolls: int,
    page_wait_ms: int,
    scroll_wait_ms: int,
    diagnostics: dict[str, Any] | None,
    merged: dict[str, dict[str, Any]],
    deadline_monotonic: float | None = None,
) -> None:
    page.goto(
        url,
        wait_until="domcontentloaded",
        timeout=recovery_timeout_ms(45_000, deadline_monotonic),
    )
    wait_for_x_page_ready(page, page_wait_ms, deadline_monotonic)
    ensure_x_page_healthy(
        page,
        account_page=account_page,
        diagnostics=diagnostics,
        phase="profile" if account_page else "search_fallback",
        deadline_monotonic=deadline_monotonic,
    )
    unchanged_rounds = 0
    visible_article_keys: set[str] = set()
    for round_index in range(scrolls + 1):
        recovery_timeout_ms(30_000, deadline_monotonic)
        expanded = int(page.evaluate(EXPAND_TWEETS_JS) or 0)
        if expanded:
            recovery_wait_for_timeout(page, 250, deadline_monotonic)
        payload = page.evaluate(EXTRACT_JS, {"handle": handle, "cutoffMs": cutoff_ms, "maxItems": limit * 2})
        rows = payload.get("rows", [])
        current_article_keys = {str(key) for key in payload.get("articleKeys", []) if key}
        new_article_keys = current_article_keys - visible_article_keys
        visible_article_keys.update(current_article_keys)
        for row in rows:
            key = str(row.get("url") or f"{handle}:{row.get('created_at')}:{row.get('text','')[:80]}")
            merged[key] = row
        if diagnostics is not None:
            diagnostics["scroll_rounds"] += 1
        if account_page and diagnostics is not None:
            diagnostics["profile_tweets"] = len(merged)
        if len(merged) >= limit:
            break
        if not new_article_keys:
            unchanged_rounds += 1
        else:
            unchanged_rounds = 0
        if unchanged_rounds >= 2 and round_index + 1 >= MIN_SCROLL_ROUNDS:
            if diagnostics is not None:
                diagnostics["early_stops"] += 1
            break
        if round_index >= scrolls:
            break
        page.mouse.wheel(0, 1800)
        wait_for_x_scroll_content(
            page,
            scroll_wait_ms,
            len(current_article_keys),
            deadline_monotonic,
        )


def scrape_handle(
    page: Any,
    handle: str,
    hours: int,
    limit: int,
    scrolls: int,
    page_wait_ms: int,
    scroll_wait_ms: int,
    search_fallback: bool,
    diagnostics: dict[str, Any] | None = None,
    deadline_monotonic: float | None = None,
) -> list[dict[str, Any]]:
    clean_handle = handle.lstrip("@")
    if diagnostics is not None:
        diagnostics.setdefault("profile_tweets", 0)
        diagnostics.setdefault("search_fallback_used", False)
        diagnostics.setdefault("scroll_rounds", 0)
        diagnostics.setdefault("early_stops", 0)
    cutoff_ms = int((dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)).timestamp() * 1000)
    urls = [
        f"https://x.com/{urllib.parse.quote(clean_handle)}",
        "https://x.com/search?" + urllib.parse.urlencode({"q": f"from:{clean_handle}", "src": "typed_query", "f": "live"}),
    ]
    if not search_fallback:
        urls = urls[:1]
    merged: dict[str, dict[str, Any]] = {}
    for url_index, url in enumerate(urls):
        if url_index > 0 and merged:
            break
        if url_index > 0 and diagnostics is not None:
            diagnostics["search_fallback_used"] = True
        if len(merged) >= limit:
            break
        try:
            scrape_handle_url(
                page,
                handle,
                url,
                url_index == 0,
                cutoff_ms,
                limit,
                scrolls,
                page_wait_ms,
                scroll_wait_ms,
                diagnostics,
                merged,
                deadline_monotonic,
            )
        except Exception as exc:
            if url_index == 0:
                raise
            if diagnostics is not None:
                diagnostics["search_fallback_error"] = f"{type(exc).__name__}: {exc}"
                diagnostics["search_fallback_failed"] = True
            print(
                f"[search-fallback-skip] {handle} error={type(exc).__name__}: {exc}",
                file=sys.stderr,
                flush=True,
            )
            break
    rows = sorted(merged.values(), key=lambda x: x.get("created_at_ms", 0), reverse=True)
    return rows[:limit]


def scrape_handle_search_fallback(
    page: Any,
    handle: str,
    hours: int,
    limit: int,
    scrolls: int,
    page_wait_ms: int,
    scroll_wait_ms: int,
    diagnostics: dict[str, Any],
    deadline_monotonic: float | None = None,
) -> list[dict[str, Any]]:
    clean_handle = handle.lstrip("@")
    cutoff_ms = int(
        (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)).timestamp()
        * 1000
    )
    diagnostics["search_fallback_used"] = True
    merged: dict[str, dict[str, Any]] = {}
    url = "https://x.com/search?" + urllib.parse.urlencode(
        {"q": f"from:{clean_handle}", "src": "typed_query", "f": "live"}
    )
    scrape_handle_url(
        page,
        handle,
        url,
        False,
        cutoff_ms,
        limit,
        scrolls,
        page_wait_ms,
        scroll_wait_ms,
        diagnostics,
        merged,
        deadline_monotonic,
    )
    rows = sorted(
        merged.values(),
        key=lambda item: item.get("created_at_ms", 0),
        reverse=True,
    )
    return rows[:limit]


def fmt_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    minutes, sec = divmod(seconds, 60)
    if minutes:
        return f"{minutes}m{sec:02d}s"
    return f"{sec}s"


def rescan_page_render_failures(
    browser: Any,
    cookies: list[dict[str, Any]],
    results: list[dict[str, Any]],
    hours: int,
    limit: int,
    page_wait_ms: int,
    scroll_wait_ms: int,
    recovery_budget: RecoveryBudget,
) -> None:
    pending_items = [
        item
        for item in results
        if item.get("status") == "error"
        and (
            item.get("diagnostics", {}).get("deferred_recovery")
            or str(item.get("error") or "").endswith(RECOVERABLE_X_PAGE_ERRORS)
        )
    ]
    if not pending_items:
        return
    for item in pending_items:
        diagnostics = item.setdefault("diagnostics", {})
        diagnostics.setdefault("recovery_original_error", str(item.get("error") or ""))
    print(
        f"[x-deferred-recovery] queued={len(pending_items)} "
        "mode=shared-profile-only "
        f"budget_remaining={recovery_budget.remaining_seconds:.1f}s",
        file=sys.stderr,
        flush=True,
    )
    context = None
    home_diagnostics: dict[str, Any] = {}
    try:
        deadline_monotonic = recovery_budget.deadline()
        context = new_x_context(browser, cookies)
        page = context.new_page()
        page.goto(
            "https://x.com/home",
            wait_until="domcontentloaded",
            timeout=recovery_timeout_ms(45_000, deadline_monotonic),
        )
        recovery_wait_for_timeout(
            page,
            max(page_wait_ms, 5000),
            deadline_monotonic,
        )
        ensure_x_page_healthy(
            page,
            diagnostics=home_diagnostics,
            phase="recovery_home_probe",
            deadline_monotonic=deadline_monotonic,
        )
    except Exception as exc:
        probe_error = f"{type(exc).__name__}: {exc}"
        for item in pending_items:
            diagnostics = item.setdefault("diagnostics", {})
            diagnostics["fresh_context_recovered"] = False
            diagnostics["recovery_home_probe_error"] = probe_error
            diagnostics["recovery_home_probe_diagnostics"] = home_diagnostics
            diagnostics["recovery_budget_spent_seconds"] = round(
                recovery_budget.spent_seconds,
                3,
            )
            if isinstance(exc, RecoveryBudgetExceeded):
                diagnostics["recovery_budget_exhausted"] = True
        print(
            f"[x-deferred-recovery] home probe failed "
            f"error={probe_error}",
            file=sys.stderr,
            flush=True,
        )
        if context is not None:
            context.close()
            context = None
        return
    else:
        for item in pending_items:
            diagnostics = item.setdefault("diagnostics", {})
            diagnostics["recovery_home_probe_healthy"] = True
        print(
            f"[x-deferred-recovery] home probe healthy "
            f"budget_remaining={recovery_budget.remaining_seconds:.1f}s",
            file=sys.stderr,
            flush=True,
        )

    try:
        for item_index, item in enumerate(pending_items):
            handle = str(item.get("handle") or "")
            started = time.time()
            retry_diagnostics: dict[str, Any] = {
                "profile_tweets": 0,
                "search_fallback_used": False,
                "scroll_rounds": 0,
                "early_stops": 0,
            }
            diagnostics = item.setdefault("diagnostics", {})
            remaining_seconds = recovery_budget.remaining_seconds
            if remaining_seconds < RECOVERY_MIN_ATTEMPT_SECONDS:
                for pending_item in pending_items[item_index:]:
                    pending_diagnostics = pending_item.setdefault("diagnostics", {})
                    pending_diagnostics["recovery_budget_exhausted"] = True
                    pending_diagnostics["recovery_budget_spent_seconds"] = round(
                        recovery_budget.spent_seconds,
                        3,
                    )
                print(
                    f"[x-deferred-recovery] remaining={len(pending_items) - item_index} "
                    f"deferred; budget_remaining={remaining_seconds:.1f}s",
                    file=sys.stderr,
                    flush=True,
                )
                break
            attempt_seconds = min(RECOVERY_ATTEMPT_CAP_SECONDS, remaining_seconds)
            diagnostics["fresh_context_retry"] = int(
                diagnostics.get("fresh_context_retry") or 0
            ) + 1
            diagnostics["page_retries"] = int(diagnostics.get("page_retries") or 0) + 1
            diagnostics["recovery_attempted"] = True
            diagnostics["recovery_budget_limit_seconds"] = recovery_budget.limit_seconds
            diagnostics["recovery_quiet_seconds"] = RECOVERY_QUIET_SECONDS
            diagnostics["recovery_profile_only"] = True
            print(
                f"[x-deferred-recovery] {handle} start "
                f"mode=profile-only attempt_budget={attempt_seconds:.1f}s",
                file=sys.stderr,
                flush=True,
            )
            try:
                deadline_monotonic = min(
                    recovery_budget.deadline(),
                    time.monotonic() + attempt_seconds,
                )
                tweets = scrape_handle(
                    page,
                    handle,
                    hours,
                    limit,
                    0,
                    page_wait_ms,
                    scroll_wait_ms,
                    False,
                    retry_diagnostics,
                    deadline_monotonic,
                )
            except Exception as exc:
                diagnostics["fresh_context_recovered"] = False
                diagnostics["fresh_context_error"] = f"{type(exc).__name__}: {exc}"
                diagnostics["fresh_context_diagnostics"] = retry_diagnostics
                if isinstance(exc, RecoveryBudgetExceeded):
                    diagnostics["recovery_attempt_timed_out"] = True
                print(
                    f"[x-deferred-recovery] {handle} failed "
                    f"{time.time() - started:.1f}s error={type(exc).__name__}: {exc}",
                    file=sys.stderr,
                    flush=True,
                )
            else:
                diagnostics["fresh_context_recovered"] = True
                diagnostics["fresh_context_diagnostics"] = retry_diagnostics
                item["status"] = "ok"
                item["error"] = ""
                item["tweets"] = tweets
                print(
                    f"[x-deferred-recovery] {handle} recovered tweets={len(tweets)} "
                    f"{time.time() - started:.1f}s",
                    file=sys.stderr,
                    flush=True,
                )
            finally:
                diagnostics["recovery_budget_spent_seconds"] = round(
                    recovery_budget.spent_seconds,
                    3,
                )
    finally:
        if context is not None:
            context.close()


def scrape_all(
    kols: list[dict[str, str]],
    hours: int,
    limit: int,
    scrolls: int,
    headless: bool,
    page_wait_ms: int,
    scroll_wait_ms: int,
    search_fallback: bool,
) -> tuple[list[dict[str, Any]], dict[str, float]]:
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright
    except Exception as exc:
        raise RuntimeError("missing playwright; run: python -m pip install playwright && python -m playwright install chromium") from exc

    cookies = cookies_from_env()
    chrome_path = os.environ.get("CHROME_PATH", "").strip() or None
    results: list[dict[str, Any]] = []
    phase_timings: dict[str, float] = {}
    scan_started = time.monotonic()
    recovery_budget: RecoveryBudget | None = None
    with sync_playwright() as p:
        launch_args = [
            "--disable-gpu",
            "--disable-logging",
            chromium_log_file_arg(),
            "--no-first-run",
            "--no-default-browser-check",
        ]
        launch_kwargs: dict[str, Any] = {
            "headless": headless,
            "args": launch_args,
            "env": chromium_launch_env(),
        }
        if chrome_path:
            launch_kwargs["executable_path"] = chrome_path
        browser = p.chromium.launch(**launch_kwargs)
        try:
            context = new_x_context(browser, cookies)
            try:
                page = context.new_page()
                page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=45_000)
                page.wait_for_timeout(1500)
                ensure_x_page_healthy(page)
                print(
                    f"[x-home] url={page.url} title={page.title()[:80]}",
                    file=sys.stderr,
                    flush=True,
                )
                total_kols = len(kols)
                planned_profile_loads = sum(
                    1 for kol in kols if not kol.get("auto_recheck_paused")
                )
                durations: list[float] = []
                profile_started = time.monotonic()
                page_failure_streak = 0
                for index, kol in enumerate(kols, 1):
                    handle = kol["handle"]
                    if kol.get("auto_recheck_paused"):
                        next_recheck_date = str(kol.get("next_recheck_date") or "")
                        print(
                            f"[scan {index}/{total_kols}] {handle} paused "
                            f"next_recheck={next_recheck_date}",
                            file=sys.stderr,
                            flush=True,
                        )
                        results.append({
                            **kol,
                            "status": "paused",
                            "error": "",
                            "tweets": [],
                            "diagnostics": {
                                "profile_tweets": 0,
                                "search_fallback_used": False,
                                "scroll_rounds": 0,
                                "early_stops": 0,
                                "page_retries": 0,
                                "rename_checks": 0,
                                "auto_recheck_paused": True,
                            },
                        })
                        continue
                    started = time.time()
                    print(f"[scan {index}/{total_kols}] {handle} start", file=sys.stderr, flush=True)
                    diagnostics: dict[str, Any] = {
                        "profile_tweets": 0,
                        "search_fallback_used": False,
                        "scroll_rounds": 0,
                        "early_stops": 0,
                        "page_retries": 0,
                        "rename_checks": 0,
                    }
                    rename_attempted = False
                    final_page_error = False
                    while True:
                        try:
                            tweets = scrape_handle(
                                page,
                                handle,
                                hours,
                                limit,
                                scrolls,
                                page_wait_ms,
                                scroll_wait_ms,
                                False,
                                diagnostics,
                            )
                        except Exception as exc:
                            if str(exc) == ACCOUNT_UNAVAILABLE_ERROR and not rename_attempted:
                                rename_attempted = True
                                try:
                                    renamed_handle, checked = recover_renamed_handle(page, handle, page_wait_ms)
                                    diagnostics["rename_checks"] = checked
                                    if renamed_handle:
                                        record_handle_alias(handle, renamed_handle)
                                except Exception as recovery_exc:
                                    diagnostics["rename_error"] = f"{type(recovery_exc).__name__}: {recovery_exc}"
                                    renamed_handle = ""
                                if renamed_handle:
                                    previous_handle = handle
                                    kol.setdefault("configured_handle", previous_handle)
                                    kol["handle"] = renamed_handle
                                    handle = renamed_handle
                                    diagnostics["renamed_from"] = previous_handle
                                    diagnostics["renamed_to"] = renamed_handle
                                    print(
                                        f"[account-renamed] {previous_handle} -> {renamed_handle} verified; retrying",
                                        file=sys.stderr,
                                        flush=True,
                                    )
                                    continue
                                print(
                                    f"[account-rename-unresolved] {handle} cached_statuses={diagnostics['rename_checks']}",
                                    file=sys.stderr,
                                    flush=True,
                                )
                            recoverable_page_error = str(exc) in RECOVERABLE_X_PAGE_ERRORS or isinstance(
                                exc,
                                PlaywrightTimeoutError,
                            )
                            tweets = []
                            status = "error"
                            error = f"{type(exc).__name__}: {exc}"
                            final_page_error = recoverable_page_error
                            diagnostics["deferred_recovery"] = recoverable_page_error
                            page_failure_streak = (
                                page_failure_streak + 1
                                if recoverable_page_error
                                else 0
                            )
                        else:
                            status = "ok"
                            error = ""
                            page_failure_streak = 0
                        break
                    search_fallback_error = str(
                        diagnostics.get("search_fallback_error") or ""
                    )
                    search_fallback_page_error = bool(
                        diagnostics.get("search_fallback_failed")
                        and search_fallback_error.endswith(RECOVERABLE_X_PAGE_ERRORS)
                    )
                    global_page_failure = (
                        page_failure_streak >= GLOBAL_PAGE_FAILURE_STREAK
                        or search_fallback_page_error
                    )
                    global_page_reason = (
                        "page_error"
                        if final_page_error
                        else "search_fallback_error"
                        if search_fallback_page_error
                        else ""
                    )
                    if search_fallback_page_error and status == "ok":
                        status = "error"
                        error = search_fallback_error
                        tweets = []
                        diagnostics["deferred_recovery"] = True
                    elapsed = time.time() - started
                    durations.append(elapsed)
                    avg = sum(durations) / len(durations)
                    eta = fmt_duration(avg * (total_kols - index))
                    retry_suffix = f" retries={diagnostics['page_retries']}" if diagnostics["page_retries"] else ""
                    suffix = f"{retry_suffix} error={error}" if error else retry_suffix
                    print(
                        f"[scan {index}/{total_kols}] {handle} {status} tweets={len(tweets)} {elapsed:.1f}s eta={eta}{suffix}",
                        file=sys.stderr,
                        flush=True,
                    )
                    results.append({
                        **kol,
                        "status": status,
                        "error": error,
                        "tweets": tweets,
                        "diagnostics": diagnostics,
                    })
                    if global_page_failure:
                        remaining_kols = kols[index:]
                        diagnostics["global_page_breaker_triggered"] = True
                        diagnostics["global_page_breaker_reason"] = global_page_reason
                        for pending_kol in remaining_kols:
                            if pending_kol.get("auto_recheck_paused"):
                                results.append({
                                    **pending_kol,
                                    "status": "paused",
                                    "error": "",
                                    "tweets": [],
                                    "diagnostics": {
                                        "profile_tweets": 0,
                                        "search_fallback_used": False,
                                        "scroll_rounds": 0,
                                        "early_stops": 0,
                                        "page_retries": 0,
                                        "rename_checks": 0,
                                        "auto_recheck_paused": True,
                                    },
                                })
                                continue
                            results.append({
                                **pending_kol,
                                "status": "error",
                                "error": f"RuntimeError: {GLOBAL_PAGE_DEFERRED_ERROR}",
                                "tweets": [],
                                "diagnostics": {
                                    "profile_tweets": 0,
                                    "search_fallback_used": False,
                                    "scroll_rounds": 0,
                                    "early_stops": 0,
                                    "page_retries": 0,
                                    "rename_checks": 0,
                                    "deferred_recovery": True,
                                    "global_page_deferred": True,
                                    "global_page_trigger_handle": handle,
                                    "global_page_trigger_reason": global_page_reason,
                                },
                            })
                        print(
                            f"[x-global-page-breaker] trigger={handle} "
                            f"reason={global_page_reason} "
                            f"queued={1 + len(remaining_kols)}",
                            file=sys.stderr,
                            flush=True,
                        )
                        break
                    recycle_reason = (
                        "search_fallback_error"
                        if diagnostics.get("search_fallback_failed")
                        else ""
                    )
                    if recycle_reason and index < total_kols:
                        diagnostics["context_recycled_after_error"] = True
                        diagnostics["context_recycle_reason"] = recycle_reason
                        print(
                            f"[x-context-recycle] {handle} reason={recycle_reason} "
                            "continuing=true",
                            file=sys.stderr,
                            flush=True,
                        )
                        replacement_context = new_x_context(browser, cookies)
                        context.close()
                        context = replacement_context
                        page = context.new_page()
                phase_timings["x_profiles"] = time.monotonic() - profile_started
                profile_page_failure = any(
                    item.get("diagnostics", {}).get("global_page_breaker_triggered")
                    for item in results
                )
                fallback_started = time.monotonic()
                if search_fallback and not profile_page_failure:
                    fallback_items = [
                        item
                        for item in results
                        if item.get("status") == "ok" and not item.get("tweets")
                    ]
                    fallback_limit = max(
                        0,
                        MAX_PLANNED_X_PAGE_LOADS_PER_RUN
                        - planned_profile_loads
                        - 1,
                    )
                    if fallback_items:
                        rotation_step = max(1, fallback_limit)
                        rotation_offset = (
                            cn_now().toordinal() * rotation_step
                        ) % len(fallback_items)
                        fallback_items = (
                            fallback_items[rotation_offset:]
                            + fallback_items[:rotation_offset]
                        )
                    selected_fallbacks = fallback_items[:fallback_limit]
                    deferred_fallbacks = fallback_items[fallback_limit:]
                    for item in deferred_fallbacks:
                        item.setdefault("diagnostics", {})[
                            "search_fallback_deferred"
                        ] = True
                    fallback_scrolls = min(scrolls, MAX_SEARCH_FALLBACK_SCROLLS)
                    print(
                        f"[search-fallback-plan] candidates={len(fallback_items)} "
                        f"selected={len(selected_fallbacks)} "
                        f"deferred={len(deferred_fallbacks)} "
                        f"page_budget={MAX_PLANNED_X_PAGE_LOADS_PER_RUN} "
                        f"scrolls={fallback_scrolls}",
                        file=sys.stderr,
                        flush=True,
                    )
                    total_fallbacks = len(selected_fallbacks)
                    fallback_budget = RecoveryBudget(
                        SEARCH_FALLBACK_TOTAL_BUDGET_SECONDS
                    )
                    for fallback_index, item in enumerate(selected_fallbacks, 1):
                        handle = str(item.get("handle") or "")
                        diagnostics = item.setdefault("diagnostics", {})
                        if fallback_budget.remaining_seconds < 2.0:
                            for pending_item in selected_fallbacks[fallback_index - 1:]:
                                pending_item.setdefault("diagnostics", {})[
                                    "search_fallback_deferred"
                                ] = True
                            print(
                                f"[search-fallback-budget] exhausted "
                                f"remaining={total_fallbacks - fallback_index + 1}",
                                file=sys.stderr,
                                flush=True,
                            )
                            break
                        started = time.time()
                        print(
                            f"[search-fallback {fallback_index}/{total_fallbacks}] "
                            f"{handle} start",
                            file=sys.stderr,
                            flush=True,
                        )
                        try:
                            tweets = scrape_handle_search_fallback(
                                page,
                                handle,
                                hours,
                                limit,
                                fallback_scrolls,
                                page_wait_ms,
                                scroll_wait_ms,
                                diagnostics,
                                fallback_budget.deadline(),
                            )
                        except Exception as exc:
                            fallback_error = f"{type(exc).__name__}: {exc}"
                            diagnostics["search_fallback_error"] = fallback_error
                            diagnostics["search_fallback_failed"] = True
                            budget_exhausted = (
                                isinstance(exc, RecoveryBudgetExceeded)
                                or fallback_budget.remaining_seconds < 1.0
                            )
                            if budget_exhausted:
                                diagnostics["search_fallback_budget_exhausted"] = True
                                for pending_item in selected_fallbacks[fallback_index:]:
                                    pending_item.setdefault("diagnostics", {})[
                                        "search_fallback_deferred"
                                    ] = True
                                print(
                                    f"[search-fallback-budget] exhausted "
                                    f"remaining={total_fallbacks - fallback_index}",
                                    file=sys.stderr,
                                    flush=True,
                                )
                                break
                            recoverable_page_error = (
                                str(exc) in RECOVERABLE_X_PAGE_ERRORS
                                or isinstance(exc, PlaywrightTimeoutError)
                            )
                            print(
                                f"[search-fallback {fallback_index}/{total_fallbacks}] "
                                f"{handle} failed {time.time() - started:.1f}s "
                                f"error={fallback_error}",
                                file=sys.stderr,
                                flush=True,
                            )
                            if recoverable_page_error:
                                diagnostics["search_fallback_breaker_triggered"] = True
                                for pending_item in selected_fallbacks[fallback_index:]:
                                    pending_item.setdefault("diagnostics", {})[
                                        "search_fallback_deferred"
                                    ] = True
                                print(
                                    f"[x-search-fallback-breaker] trigger={handle} "
                                    f"remaining={total_fallbacks - fallback_index}",
                                    file=sys.stderr,
                                    flush=True,
                                )
                                break
                            continue
                        item["tweets"] = tweets
                        print(
                            f"[search-fallback {fallback_index}/{total_fallbacks}] "
                            f"{handle} ok tweets={len(tweets)} "
                            f"{time.time() - started:.1f}s",
                            file=sys.stderr,
                            flush=True,
                        )
                    print(
                        f"[search-fallback-budget] "
                        f"spent={fallback_budget.spent_seconds:.1f}s "
                        f"limit={fallback_budget.limit_seconds:.0f}s",
                        file=sys.stderr,
                        flush=True,
                    )
                phase_timings["x_fallback"] = time.monotonic() - fallback_started
            finally:
                context.close()
            has_deferred_recovery = any(
                item.get("status") == "error"
                and (
                    item.get("diagnostics", {}).get("deferred_recovery")
                    or str(item.get("error") or "").endswith(RECOVERABLE_X_PAGE_ERRORS)
                )
                for item in results
            )
            recovery_started = time.monotonic()
            if has_deferred_recovery:
                browser.close()
                recovery_budget = RecoveryBudget(RECOVERY_TOTAL_BUDGET_SECONDS)
                print(
                    f"[x-deferred-recovery] quiet start "
                    f"seconds={RECOVERY_QUIET_SECONDS:.0f}",
                    file=sys.stderr,
                    flush=True,
                )
                recovery_budget.sleep(RECOVERY_QUIET_SECONDS)
                browser = p.chromium.launch(**launch_kwargs)
                print(
                    f"[x-deferred-recovery] quiet complete; browser restarted "
                    f"budget_remaining={recovery_budget.remaining_seconds:.1f}s",
                    file=sys.stderr,
                    flush=True,
                )
                rescan_page_render_failures(
                    browser,
                    cookies,
                    results,
                    hours,
                    limit,
                    page_wait_ms,
                    scroll_wait_ms,
                    recovery_budget,
                )
            phase_timings["x_recovery"] = time.monotonic() - recovery_started
        finally:
            try:
                browser.close()
            finally:
                cleanup_chromium_debug_log()
    if recovery_budget is not None:
        print(
            f"[x-recovery-budget] spent={recovery_budget.spent_seconds:.1f}s "
            f"limit={recovery_budget.limit_seconds:.0f}s",
            file=sys.stderr,
            flush=True,
        )
    phase_timings["x_total"] = time.monotonic() - scan_started
    return results, phase_timings


def scan_summary(results: list[dict[str, Any]]) -> dict[str, int]:
    unavailable = sum(
        1
        for item in results
        if str(item.get("error") or "").endswith(ACCOUNT_UNAVAILABLE_ERROR)
    )
    recovery_deferred = sum(
        1
        for item in results
        if item.get("status") == "error"
        and item.get("diagnostics", {}).get("global_page_deferred")
        and not item.get("diagnostics", {}).get("recovery_attempted")
    )
    errors = sum(
        1
        for item in results
        if item.get("status") == "error"
        and not str(item.get("error") or "").endswith(ACCOUNT_UNAVAILABLE_ERROR)
        and not (
            item.get("diagnostics", {}).get("global_page_deferred")
            and not item.get("diagnostics", {}).get("recovery_attempted")
        )
    )
    paused = sum(1 for item in results if item.get("status") == "paused")
    success = sum(1 for item in results if item.get("status") == "ok")
    active = sum(1 for item in results if item.get("tweets"))
    fallback_used = sum(
        1
        for item in results
        if item.get("diagnostics", {}).get("search_fallback_used")
    )
    fallback_hits = sum(
        1
        for item in results
        if item.get("diagnostics", {}).get("search_fallback_used") and item.get("tweets")
    )
    fallback_deferred = sum(
        1
        for item in results
        if item.get("diagnostics", {}).get("search_fallback_deferred")
    )
    scroll_rounds = sum(
        int(item.get("diagnostics", {}).get("scroll_rounds") or 0)
        for item in results
    )
    early_stops = sum(
        int(item.get("diagnostics", {}).get("early_stops") or 0)
        for item in results
    )
    page_retries = sum(
        int(item.get("diagnostics", {}).get("page_retries") or 0)
        for item in results
    )
    return {
        "total": len(results),
        "success": success,
        "errors": errors,
        "paused": paused,
        "active": active,
        "no_recent": sum(
            1
            for item in results
            if item.get("status") == "ok" and not item.get("tweets")
        ),
        "fallback_used": fallback_used,
        "fallback_hits": fallback_hits,
        "fallback_deferred": fallback_deferred,
        "scroll_rounds": scroll_rounds,
        "early_stops": early_stops,
        "page_retries": page_retries,
        "fresh_context_retries": sum(
            int(item.get("diagnostics", {}).get("fresh_context_retry") or 0)
            for item in results
        ),
        "fresh_context_recovered": sum(
            1
            for item in results
            if item.get("diagnostics", {}).get("fresh_context_recovered") is True
        ),
        "renamed": sum(1 for item in results if item.get("diagnostics", {}).get("renamed_to")),
        "unavailable": unavailable,
        "recovery_deferred": recovery_deferred,
        "pending_removal": sum(1 for item in results if item.get("pending_removal")),
    }


def ensure_scan_deliverable(
    results: list[dict[str, Any]],
    summary: dict[str, int],
) -> None:
    failed_count = sum(1 for item in results if item.get("status") == "error")
    if failed_count and summary["success"] == 0:
        raise RuntimeError(
            f"X scan produced no successful KOLs ({failed_count}/{len(results)} failed); "
            "report generation and Telegram delivery were stopped"
        )


def normalize_translation_source(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def translation_signal_text(text: str) -> str:
    source = normalize_translation_source(text)
    source = re.sub(r"(?:https?://|www\.)\s*\S+", "", source, flags=re.IGNORECASE)
    return re.sub(r"\b0x[0-9A-Fa-f]{8,}\b", "", source)


def has_english_phrase(text: str) -> bool:
    for segment in re.split(r"[\u4e00-\u9fff]+", translation_signal_text(text)):
        words = re.findall(r"[A-Za-z][A-Za-z'-]*", segment)
        if len(words) >= 3 and sum(len(word) for word in words) >= 12:
            return True
    return False


def is_mostly_english(text: str) -> bool:
    source = translation_signal_text(text)
    letters = re.findall(r"[A-Za-z]", source)
    han = re.findall(r"[\u4e00-\u9fff]", source)
    return len(letters) >= 20 and (
        not han or len(letters) >= len(han) * 4 or has_english_phrase(source)
    )


def load_json(path: Path, default: Any, *, strict: bool = False) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        if strict:
            raise RuntimeError(f"invalid JSON state: {path.name} ({type(exc).__name__})") from exc
        return default


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def cached_status_ids(handle: str, limit: int = RENAME_STATUS_CANDIDATES) -> list[str]:
    target = canonical_handle(handle).lower()
    store = load_json(TWEET_STORE, {"version": 1, "tweets": {}}, strict=True)
    tweets = store.get("tweets", {})
    if not isinstance(tweets, dict):
        raise RuntimeError("invalid tweets in tweets.json")
    records = sorted(
        (row for row in tweets.values() if isinstance(row, dict)),
        key=lambda row: int(row.get("created_at_ms") or 0),
        reverse=True,
    )
    status_ids: list[str] = []
    for row in records:
        if canonical_handle(row.get("handle")).lower() != target:
            continue
        match = re.search(
            r"https?://(?:www\.)?(?:x|twitter)\.com/([A-Za-z0-9_]{1,32})/status/(\d+)",
            str(row.get("url") or ""),
            flags=re.IGNORECASE,
        )
        if not match or ("@" + match.group(1)).lower() != target:
            continue
        status_id = match.group(2)
        if status_id not in status_ids:
            status_ids.append(status_id)
        if len(status_ids) >= limit:
            break
    return status_ids


def recover_renamed_handle(page: Any, handle: str, page_wait_ms: int) -> tuple[str, int]:
    status_ids = cached_status_ids(handle)
    for status_id in status_ids:
        try:
            page.goto(f"https://x.com/i/status/{status_id}", wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_timeout(page_wait_ms)
            ensure_x_page_healthy(page)
            candidate = canonical_handle(page.evaluate(STATUS_AUTHOR_JS, status_id))
            if not candidate or candidate.lower() == handle.lower():
                continue
            page.goto(
                f"https://x.com/{urllib.parse.quote(candidate.lstrip('@'))}",
                wait_until="domcontentloaded",
                timeout=45_000,
            )
            page.wait_for_timeout(page_wait_ms)
            ensure_x_page_healthy(page, account_page=True)
            return candidate, len(status_ids)
        except Exception:
            continue
    return "", len(status_ids)


def record_handle_alias(old_handle: str, new_handle: str) -> None:
    old_handle = canonical_handle(old_handle)
    new_handle = canonical_handle(new_handle)
    store = load_json(TWEET_STORE, {"version": 1, "tweets": {}}, strict=True)
    aliases = store.setdefault("handle_aliases", {})
    if not isinstance(aliases, dict):
        raise RuntimeError("invalid handle_aliases in tweets.json")
    aliases[old_handle.lower()] = new_handle
    save_json(TWEET_STORE, store)


def update_kol_status(results: list[dict[str, Any]]) -> None:
    store = load_json(TWEET_STORE, {"version": 1, "tweets": {}}, strict=True)
    statuses = store.get("kol_status", {})
    if not isinstance(statuses, dict):
        raise RuntimeError("invalid kol_status in tweets.json")
    today = cn_now().date()
    changed = False
    for item in results:
        identity = canonical_handle(item.get("configured_handle") or item.get("handle"))
        if not identity:
            continue
        key = identity.lower()
        if item.get("status") == "ok":
            if key in statuses:
                statuses.pop(key)
                changed = True
            continue
        if not str(item.get("error") or "").endswith(ACCOUNT_UNAVAILABLE_ERROR):
            continue
        previous = statuses.get(key, {})
        if not isinstance(previous, dict):
            previous = {}
        unavailable_reason = str(
            item.get("diagnostics", {})
            .get("page_health", {})
            .get("account_unavailable_reason")
            or previous.get("unavailable_reason")
            or "unknown"
        )
        first_unavailable_text = str(previous.get("first_unavailable_date") or "")
        try:
            first_unavailable_date = dt.date.fromisoformat(first_unavailable_text)
        except ValueError:
            last_unavailable_text = str(previous.get("last_unavailable_date") or "")
            try:
                last_unavailable_date = dt.date.fromisoformat(last_unavailable_text)
            except ValueError:
                last_unavailable_date = today
            previous_days = max(1, int(previous.get("unavailable_days") or 1))
            first_unavailable_date = last_unavailable_date - dt.timedelta(
                days=previous_days - 1
            )
        days = max(1, (today - first_unavailable_date).days + 1)
        pending_removal = days >= UNAVAILABLE_REMOVAL_DAYS
        recheck_interval = (
            UNAVAILABLE_RECHECK_INTERVAL_DAYS
            if unavailable_reason == "suspended" and pending_removal
            else 1
        )
        next_recheck_date = today + dt.timedelta(days=recheck_interval)
        auto_action = (
            "resolve_rename_then_recheck"
            if unavailable_reason == "missing"
            else "recheck_until_reactivated"
        )
        current = {
            "handle": identity,
            "current_handle": canonical_handle(item.get("handle")),
            "unavailable_days": days,
            "first_unavailable_date": first_unavailable_date.isoformat(),
            "last_unavailable_date": today.isoformat(),
            "next_recheck_date": next_recheck_date.isoformat(),
            "pending_removal": pending_removal,
            "unavailable_reason": unavailable_reason,
            "auto_action": auto_action,
        }
        if statuses.get(key) != current:
            statuses[key] = current
            changed = True
        item["unavailable_days"] = days
        item["next_recheck_date"] = next_recheck_date.isoformat()
        item["pending_removal"] = pending_removal
        item["unavailable_reason"] = unavailable_reason
        item["auto_action"] = auto_action
    if changed:
        store["kol_status"] = statuses
        save_json(TWEET_STORE, store)


def prune_daily_outputs() -> None:
    for folder, pattern in [(REPORT_DIR, "*.md"), (STATE_DIR, "*.json")]:
        if not folder.exists():
            continue
        by_day: dict[str, list[Path]] = {}
        for path in folder.glob(pattern):
            match = re.match(r"^(\d{8})(?:-\d{6})?\.(?:md|json)$", path.name)
            if not match:
                continue
            by_day.setdefault(match.group(1), []).append(path)
        for day, paths in by_day.items():
            preferred = folder / f"{day}{Path(pattern).suffix}"
            keep = preferred if preferred in paths else max(paths, key=lambda p: p.stat().st_mtime)
            for path in paths:
                if path != keep:
                    path.unlink(missing_ok=True)


def tweet_id(tweet: dict[str, Any]) -> str:
    url = str(tweet.get("url") or "").strip()
    if "/status/" in url:
        return url.rstrip("/").split("/status/", 1)[1].split("?", 1)[0]
    seed = "|".join([
        str(tweet.get("handle") or ""),
        str(tweet.get("created_at") or ""),
        str(tweet.get("text") or "")[:160],
    ])
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def update_tweet_store(results: list[dict[str, Any]], stamp: str) -> dict[str, Any]:
    store = load_json(TWEET_STORE, {"version": 1, "tweets": {}}, strict=True)
    tweets = store.setdefault("tweets", {})
    now = dt.datetime.now().isoformat(timespec="seconds")
    added = 0
    updated = 0
    for item in results:
        for tw in item.get("tweets", []):
            tid = tweet_id(tw)
            existing = tweets.get(tid)
            tweet_text = str(tw.get("text") or "")
            existing_text = str((existing or {}).get("text") or "")
            existing_translation = (
                str((existing or {}).get("translation_zh") or "")
                if existing_text == tweet_text
                else ""
            )
            external_urls = [
                str(url).strip()
                for url in tw.get("external_urls", [])
                if str(url).strip().startswith(("http://", "https://"))
            ]
            record = {
                "id": tid,
                "handle": item.get("handle", ""),
                "name": item.get("name", ""),
                "note": item.get("note", ""),
                "created_at": tw.get("created_at", ""),
                "created_at_ms": tw.get("created_at_ms", 0),
                "text": tweet_text,
                "translation_zh": tw.get("translation_zh") or existing_translation,
                "url": tw.get("url", ""),
                "external_urls": external_urls or list((existing or {}).get("external_urls") or []),
                "last_seen_at": now,
                "last_run": stamp,
            }
            if existing:
                record["first_seen_at"] = existing.get("first_seen_at", now)
                record["seen_count"] = int(existing.get("seen_count", 1)) + 1
                tweets[tid] = {**existing, **record}
                updated += 1
            else:
                record["first_seen_at"] = now
                record["seen_count"] = 1
                tweets[tid] = record
                added += 1
    store["updated_at"] = now
    store["total"] = len(tweets)
    store["last_run"] = stamp
    save_json(TWEET_STORE, store)
    return {"store": str(TWEET_STORE), "total": len(tweets), "added": added, "updated": updated}


def translate_tweet_store(limit: int, priority_ids: set[str] | None = None) -> dict[str, int]:
    store = load_json(TWEET_STORE, {"version": 1, "tweets": {}}, strict=True)
    tweets = store.get("tweets", {})
    priority_ids = priority_ids or set()
    rows = sorted(
        tweets.values(),
        key=lambda row: (
            str(row.get("id") or "") in priority_ids,
            row.get("created_at_ms", 0),
        ),
        reverse=True,
    )
    priority_needed = sum(
        1
        for row in rows
        if str(row.get("id") or "") in priority_ids
        and translation_needed(row)
    )
    translated = 0
    skipped = 0
    failed = 0
    selected: list[dict[str, Any]] = []
    for row in rows:
        row_id = str(row.get("id") or "")
        if limit > 0 and len(selected) >= limit and row_id not in priority_ids:
            break
        if not translation_needed(row):
            skipped += 1
            continue
        selected.append(row)

    translation_cache = load_json(TRANSLATION_CACHE, {}, strict=True)
    pending_by_key: dict[str, dict[str, Any]] = {}
    cache_changed = False
    for row in selected:
        key, translation_source, source_language = translation_request(
            str(row.get("text") or "")
        )
        cached = str(translation_cache.get(key) or "")
        if cached:
            row["translation_zh"] = cached
            row["translation_version"] = TRANSLATION_VERSION
            row.pop("translation_error", None)
            translated += 1
            continue
        pending = pending_by_key.setdefault(key, {
            "key": key,
            "translation_source": translation_source,
            "source_language": source_language,
            "rows": [],
        })
        pending["rows"].append(row)

    pending_items = list(pending_by_key.values())
    translation_budget = RecoveryBudget(TRANSLATION_TOTAL_BUDGET_SECONDS)
    processed_items = 0
    with ThreadPoolExecutor(max_workers=TRANSLATION_WORKERS) as executor:
        for offset in range(0, len(pending_items), TRANSLATION_WORKERS):
            if translation_budget.remaining_seconds < 1.0:
                break
            batch = pending_items[offset:offset + TRANSLATION_WORKERS]
            futures = [
                (
                    item,
                    executor.submit(
                        translate_source_to_zh,
                        str(item["translation_source"]),
                        str(item["source_language"]),
                    ),
                )
                for item in batch
            ]
            for item, future in futures:
                item_rows = list(item["rows"])
                try:
                    translation = future.result()
                    if not translation:
                        raise ValueError("empty translation")
                except Exception as exc:
                    failed += len(item_rows)
                    for row in item_rows:
                        row["translation_error"] = f"{type(exc).__name__}: {exc}"
                    first_row = item_rows[0]
                    print(
                        f"[translation-error] id={first_row.get('id') or '?'} "
                        f"handle={first_row.get('handle') or '?'} "
                        f"rows={len(item_rows)} type={type(exc).__name__} "
                        f"detail={str(exc)[:120]}",
                        file=sys.stderr,
                        flush=True,
                    )
                else:
                    translation_cache[str(item["key"])] = translation
                    cache_changed = True
                    for row in item_rows:
                        row["translation_zh"] = translation
                        row["translation_version"] = TRANSLATION_VERSION
                        row.pop("translation_error", None)
                    translated += len(item_rows)
                processed_items += 1
            if (
                offset + TRANSLATION_WORKERS < len(pending_items)
                and translation_budget.remaining_seconds > TRANSLATION_BATCH_PAUSE_SECONDS
            ):
                time.sleep(TRANSLATION_BATCH_PAUSE_SECONDS)
    if cache_changed:
        save_json(TRANSLATION_CACHE, translation_cache)
    deferred = sum(
        len(item["rows"])
        for item in pending_items[processed_items:]
    )
    print(
        f"[translation-budget] spent={translation_budget.spent_seconds:.1f}s "
        f"limit={translation_budget.limit_seconds:.0f}s deferred={deferred}",
        file=sys.stderr,
        flush=True,
    )
    store["updated_at"] = dt.datetime.now().isoformat(timespec="seconds")
    save_json(TWEET_STORE, store)
    priority_pending = sum(
        1
        for row in rows
        if str(row.get("id") or "") in priority_ids
        and translation_needed(row)
    )
    return {
        "translated": translated,
        "skipped": skipped,
        "failed": failed,
        "deferred": deferred,
        "priority_needed": priority_needed,
        "priority_pending": priority_pending,
    }


def apply_store_translations(results: list[dict[str, Any]]) -> None:
    store = load_json(TWEET_STORE, {"version": 1, "tweets": {}}, strict=True)
    tweets = store.get("tweets", {})
    for item in results:
        for tw in item.get("tweets", []):
            record = tweets.get(tweet_id(tw))
            if record and record.get("translation_zh"):
                tw["translation_zh"] = record["translation_zh"]
                if record.get("translation_version"):
                    tw["translation_version"] = record["translation_version"]


def translation_needed(row: dict[str, Any]) -> bool:
    text = str(row.get("text") or "")
    if not is_mostly_english(text):
        return False
    if not row.get("translation_zh"):
        return True
    source = URL_RE.sub("", normalize_translation_source(text)).strip()
    return (
        len(source) > LEGACY_TRANSLATION_LIMIT
        and int(row.get("translation_version") or 0) < TRANSLATION_VERSION
    )


def split_translation_source(text: str, limit: int = TRANSLATION_CHUNK_LIMIT) -> list[str]:
    remaining = text.strip()
    chunks: list[str] = []
    while len(remaining) > limit:
        window = remaining[:limit + 1]
        candidates = [
            match.end()
            for match in re.finditer(r"\n{2,}|\n|(?<=[.!?。！？；;])\s+", window)
            if limit // 2 <= match.end() <= limit
        ]
        split_at = max(candidates) if candidates else limit
        chunk = remaining[:split_at].strip()
        if not chunk:
            chunk = remaining[:limit]
            split_at = limit
        chunks.append(chunk)
        remaining = remaining[split_at:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


def translate_chunk_to_zh(text: str, source_language: str) -> str:
    endpoints = (
        (
            "https://translate.googleapis.com/translate_a/single",
            {"client": "gtx", "sl": source_language, "tl": "zh-CN", "dt": "t"},
        ),
        (
            "https://clients5.google.com/translate_a/t",
            {"client": "dict-chrome-ex", "sl": source_language, "tl": "zh-CN"},
        ),
    )
    last_error: Exception | None = None
    for endpoint, params in endpoints:
        query = urllib.parse.urlencode({**params, "q": text})
        url = endpoint + "?" + query
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        for attempt in range(TRANSLATION_RETRIES + 1):
            try:
                with urllib.request.urlopen(
                    request,
                    timeout=TRANSLATION_HTTP_TIMEOUT_SECONDS,
                ) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                if endpoint.endswith("/single"):
                    parts = data[0] if isinstance(data, list) and data else []
                    translation = "".join(
                        part[0]
                        for part in parts
                        if isinstance(part, list) and part and part[0]
                    )
                else:
                    translation = data[0] if isinstance(data, list) and data else ""
                if translation:
                    return str(translation).strip()
                raise ValueError("empty translation response")
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code not in {400, 408, 425, 429, 500, 502, 503, 504}:
                    break
                if attempt < TRANSLATION_RETRIES:
                    time.sleep(1 + attempt)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
                last_error = exc
                if attempt < TRANSLATION_RETRIES:
                    time.sleep(1 + attempt)
    if last_error is not None:
        raise last_error
    raise RuntimeError("translation endpoints unavailable")


def translation_request(text: str) -> tuple[str, str, str]:
    source = normalize_translation_source(text).strip()
    translation_source = URL_RE.sub("", source).strip()
    if not translation_source:
        raise ValueError("empty translation source")
    # Mixed Chinese/English posts must use auto-detection; forcing sl=en can
    # make Google's endpoint reject otherwise valid long Chinese posts.
    source_language = "auto"
    cache_source = f"v{TRANSLATION_VERSION}\0{source_language}\0{translation_source}"
    key = hashlib.sha256(cache_source.encode("utf-8")).hexdigest()
    return key, translation_source, source_language


def translate_source_to_zh(translation_source: str, source_language: str) -> str:
    return "\n\n".join(
        translated_chunk
        for chunk in split_translation_source(translation_source)
        if (translated_chunk := translate_chunk_to_zh(chunk, source_language))
    )


def translate_to_zh(text: str) -> str:
    cache = load_json(TRANSLATION_CACHE, {}, strict=True)
    key, translation_source, source_language = translation_request(text)
    if key in cache:
        return str(cache[key])
    translated = translate_source_to_zh(translation_source, source_language)
    cache[key] = translated
    save_json(TRANSLATION_CACHE, cache)
    time.sleep(0.2)
    return translated


def fmt_time(value: str) -> str:
    if not value:
        return ""
    try:
        d = dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(dt.timezone(dt.timedelta(hours=8)))
        return d.strftime("%m-%d %H:%M")
    except Exception:
        return value


URL_RE = re.compile(
    r"https?://\s*\S+|www\.\S+|(?<![A-Za-z0-9@])(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}/\S+",
    re.IGNORECASE,
)


def clean_report_text(text: str) -> str:
    replacements = {
        "It's unwise to fade $MSTR": "不宜看空 $MSTR",
        "He's down 709K at the moment. Track this whale with Hyperbot:": "该鲸鱼目前浮亏约 70.9 万美元：",
        "Track this whale with Hyperbot:": "在 Hyperbot 追踪该鲸鱼：",
        "Address:": "地址：",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = re.sub(
        r"\s*[-—]{20,}\s*#\s*Bitget.*$",
        "",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = re.sub(
        r"\s*#\s*Bitget\s*来了就是\s*VIP[！!].*$",
        "",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = URL_RE.sub("", text)
    text = re.sub(r"\b(?:x\.com|twitter\.com)\s*/\s*\S+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"地址[:：]\s*\S+(?:\s*…)?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bs/\d+\S*(?:\s*…)?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:y|ss|dress|ost|announcement/detail|proposal)/\S+(?:\s*…)?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"(?<![A-Za-z0-9])(?:[A-Za-z0-9._~-]+/)+[A-Za-z0-9._~-]+\.(?:html?|php)(?:\?\S*)?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\S+\?(?:activeTab|_dp|utm_|ref=)\S*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"感谢\s+@\w+\s+作为.*?赞助商。?", "", text)
    text = re.sub(r"\b0x[0-9a-f]{10,}(?:[.#/][\w.-]+)?(?:\s*…|\s*\.\.\.)?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b[0-9a-f]{24,}(?:[.#/][\w.-]+)?(?:\s*…|\s*\.\.\.)?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b[1-9A-HJ-NP-Za-km-z]{32,}(?:[.#/][\w.-]+)?(?:\s*…|\s*\.\.\.)?", "", text)
    text = re.sub(r"\s+(?=[，。！？、；：,.!?;:])", "", text)
    text = re.sub(r"(?:\s*…|\s*\.\.\.)\s*$", "", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def tweet_link_lines(tweet: dict[str, Any]) -> list[str]:
    stored_urls = tweet.get("external_urls")
    candidates = list(stored_urls) if isinstance(stored_urls, list) else []
    candidates.extend(re.findall(r"https?://\S+|www\.\S+", str(tweet.get("text") or ""), re.IGNORECASE))
    urls: list[str] = []
    for raw in candidates:
        url = str(raw).strip().rstrip(".,!?;:，。！？；：)]}）】")
        if url.lower().startswith("www."):
            url = "https://" + url
        host = (urllib.parse.urlsplit(url).hostname or "").lower()
        if host in {"t.co", "www.t.co"}:
            continue
        if url.startswith(("http://", "https://")) and url not in urls:
            urls.append(url)
    return [f"链接：{url}" for url in urls]


def trim_text(text: str, limit: int) -> str:
    if limit <= 0 or len(text) <= limit:
        return text
    head = text[:limit]
    min_pos = max(40, int(limit * 0.55))
    for mark in ["。", "！", "？", ". ", "! ", "? ", "；", ";", "，", ","]:
        pos = head.rfind(mark)
        if pos >= min_pos:
            return head[:pos + len(mark)].rstrip(" ，,。:：;；") + "..."
    return head.rstrip(" ，,。:：;；") + "..."


def compact_text(text: str, limit: int) -> str:
    text = clean_report_text(text).replace("\n", " ")
    text = re.sub(r"^\s*(刚刚消息|刚刚|BREAKING|JUST IN)\s*[:：]\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^\s*\d+\s*/\s*", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if limit > 0 and len(text) > limit:
        return trim_text(text, limit)
    return text


def headline_text(text: str, limit: int) -> str:
    text = compact_text(text, limit=0)
    text = re.sub(r"^(消息|新闻|快讯)\s*[:：]\s*", "", text)
    parts = re.split(r"(?<=[。！？!?])\s+|[；;]\s*", text)
    text = parts[0].strip() if parts and parts[0].strip() else text
    if limit > 0 and len(text) > limit:
        return trim_text(text, limit)
    return text


def build_report(results: list[dict[str, Any]], hours: int) -> str:
    now = cn_now().strftime("%m-%d %H:%M")
    total = sum(len(x.get("tweets", [])) for x in results)
    lines = [
        f"X KOL {hours}H | {len(results)}人 | {total}条 | {now}",
        "",
    ]
    for item in results:
        tweets = item.get("tweets", [])
        if not tweets:
            continue
        lines.append(f"## {item.get('name')} {item.get('handle')}")
        for index, tw in enumerate(tweets, 1):
            body = clean_report_text(str(tw.get("translation_zh") or tw.get("text") or ""))
            if tw.get("translation_zh"):
                original = clean_report_text(str(tw.get("text", "")))
                if original:
                    body = f"{body}\n原文：{original}"
            when = fmt_time(str(tw.get("created_at", "")))
            lines.append("")
            lines.append(f"{index}. {when}")
            lines.append(body)
            lines.extend(tweet_link_lines(tw))
        lines.append("")
    if total == 0:
        lines.append("最近 24 小时没有抓到可读推文。")
    return "\n".join(lines).strip() + "\n"


IMPORTANT_TERMS = [
    "btc", "bitcoin", "eth", "ethereum", "sol", "hype", "mstr", "strategy",
    "etf", "fed", "fomc", "降息", "加息", "资金", "流入", "流出", "储备",
    "抄底", "止盈", "回踩", "突破", "空单", "多单", "杠杆", "爆仓",
    "链上", "巨鲸", "持仓", "资金费率", "稳定币", "监管", "安全", "漏洞",
    "攻击", "洗钱", "lazarus", "drainer", "hack", "exploit", "blackrock",
    "coinbase", "whale", "钱包", "转移", "gold", "黄金", "oil", "石油",
    "伊朗", "霍尔木兹", "制裁", "openai", "ai", "模型", "cursor", "google",
]

LOW_SIGNAL_TERMS = [
    "世界杯", "阿根廷", "埃及", "就你", "朋友圈", "亏麻了", "心都要碎了",
    "不能按时完成任务", "做事方法", "马斯克说，传统媒体", "了解更多",
    "track the address", "not looking so good", "current meta",
]
HARD_LOW_SIGNAL_TERMS = [
    "下载coinbase", "做个三明治", "法律条款", "资本有风险", "交易竞赛",
    "瓜分", "抽奖", "门票", "报名成功", "活动页面", "现在申购",
    "立即开始", "交易赚币", "折价买币奖池", "观赛季", "看球",
    "女团", "德州", "竞猜区", "奖池", "赞助。有观点",
]
TOKEN_ONLY_TERMS = {
    "btc", "bitcoin", "eth", "ethereum", "sol", "hype", "mstr",
    "crypto", "比特币", "加密", "加密货币",
    "$btc", "$eth", "$sol", "$hype", "$mstr",
}
EXCLUDED_TELEGRAM_TERMS = ["slowmist", "慢雾"]
FOCUS_SOURCE_TERMS = [
    "coindesk", "coinmarketcap", "lookonchain", "spot on chain", "whale alert",
    "wublockchain", "吴说", "arkham", "nansen", "peckshield", "hyperbot",
    "ethereum foundation", "binance", "币安", "okx", "coinbase",
    "openai", "sam altman", "sundar pichai",
]
DEFAULT_FOCUS_PER_KOL = 6


def tweet_body(tweet: dict[str, Any], limit: int) -> str:
    override = str(tweet.get("_body") or "")
    if override:
        return compact_text(override, limit)
    return compact_text(str(tweet.get("translation_zh") or tweet.get("text") or ""), limit)


def tweet_time_text(tweet: dict[str, Any]) -> str:
    return fmt_time(str(tweet.get("created_at", ""))).split(" ", 1)[-1]


def text_has_term(text: str, term: str) -> bool:
    blob = str(text or "").lower()
    needle = str(term or "").lower()
    if not needle:
        return False
    if re.fullmatch(r"[a-z0-9 ]+", needle):
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", blob))
    return needle in blob


def row_signal_score(row: dict[str, Any]) -> int:
    tweet = row["tweet"]
    body = tweet_body(tweet, 900)
    score = 0
    score += sum(2 for term in IMPORTANT_TERMS if text_has_term(body, term))
    score -= sum(3 for term in LOW_SIGNAL_TERMS if text_has_term(body, term))
    if len(body) < 12:
        score -= 4
    if "$" in body:
        score += 2
    if str(tweet.get("_thread_count") or ""):
        score += 2
    return score


def has_important_signal(text: str) -> bool:
    return "$" in text or any(text_has_term(text, term) for term in IMPORTANT_TERMS)


def is_focus_row(row: dict[str, Any]) -> bool:
    body = tweet_body(row["tweet"], 900)
    source = f"{row.get('name', '')} {row.get('handle', '')}".lower()
    return has_important_signal(body) or any(term in source for term in FOCUS_SOURCE_TERMS) or row_signal_score(row) > 0


def is_token_only_text(text: str) -> bool:
    token_text = re.sub(r"[#＃$＄]", "", text.strip().lower())
    token_text = re.sub(r"[，,。.!！?？；;：:、/|()\[\]【】]+", " ", token_text)
    tokens = [token for token in re.split(r"\s+", token_text) if token]
    return bool(tokens) and len(tokens) <= 5 and all(token in TOKEN_ONLY_TERMS for token in tokens)


def is_low_signal_row(row: dict[str, Any]) -> bool:
    body = tweet_body(row["tweet"], 900)
    compact = re.sub(r"\s+", " ", body).strip()
    lower = compact.lower()
    if not compact:
        return True
    if is_token_only_text(compact):
        return True
    if any(text_has_term(lower, term) for term in HARD_LOW_SIGNAL_TERMS):
        return True
    if any(text_has_term(lower, term) for term in LOW_SIGNAL_TERMS):
        return not has_important_signal(compact)
    cjk = sum("\u4e00" <= ch <= "\u9fff" for ch in compact)
    letters = sum(ch.isascii() and ch.isalpha() for ch in compact)
    if letters >= 8 and cjk == 0 and len(compact) <= 40 and not has_important_signal(compact):
        return True
    if re.fullmatch(r"\d+\s*[-.)/]\s*[A-Za-z0-9_.-]{1,20}", compact) and not has_important_signal(compact):
        return True
    if len(compact) <= 8 and not has_important_signal(compact):
        return True
    if len(compact) <= 24 and not has_important_signal(compact) and not re.search(r"\d", compact):
        return True
    return False


def is_excluded_telegram_row(row: dict[str, Any]) -> bool:
    body = tweet_body(row["tweet"], 900).lower()
    return any(text_has_term(body, term) for term in EXCLUDED_TELEGRAM_TERMS)


def telegram_row_sort_key(row: dict[str, Any]) -> tuple[int, int]:
    kol_order = int(row.get("_kol_order", 999999))
    tweet_time = int(row.get("tweet", {}).get("created_at_ms") or 0)
    return (kol_order, -tweet_time)


def telegram_rows(results: list[dict[str, Any]], per_kol: int, include_low_signal: bool) -> list[dict[str, Any]]:
    active = [x for x in results if x.get("tweets")]
    rows: list[dict[str, Any]] = []
    for kol_order, item in enumerate(active):
        tweets = item.get("tweets", [])
        name = str(item.get("name") or item.get("handle") or "").strip()
        handle = str(item.get("handle") or "").strip()
        qualified: list[dict[str, Any]] = []
        for tw in tweets:
            row = {"name": name, "handle": handle, "tweet": tw, "_kol_order": kol_order}
            if is_excluded_telegram_row(row):
                continue
            if include_low_signal or not is_low_signal_row(row):
                qualified.append(row)
        rows.extend(qualified[:per_kol] if per_kol > 0 else qualified)
    rows.sort(key=telegram_row_sort_key)
    return rows


def merge_thread_rows(rows: list[dict[str, Any]], tweet_chars: int) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = {}
    order: list[tuple[str, str]] = []
    for row in rows:
        tweet = row["tweet"]
        author_key = str(row.get("handle") or row.get("name") or "").lower()
        created_ms = int(tweet.get("created_at_ms") or 0)
        minute_key = str(created_ms // 60_000) if created_ms else str(tweet.get("created_at") or "")[:16]
        key = (author_key, minute_key)
        if key not in buckets:
            order.append(key)
            buckets[key] = []
        buckets[key].append(row)

    merged: list[dict[str, Any]] = []
    for key in order:
        group = buckets[key]
        if len(group) < 2:
            merged.extend(group)
            continue
        bodies = [tweet_body(row["tweet"], 160) for row in group if tweet_body(row["tweet"], 160)]
        raw_bodies = [
            str(row["tweet"].get("text") or row["tweet"].get("translation_zh") or "")
            for row in group
        ]
        numbered = sum(1 for body in raw_bodies if re.match(r"^\s*\d+\s*/", body))
        if numbered < 2:
            merged.extend(group)
            continue
        first = dict(group[0]["tweet"])
        parts = []
        for body in bodies[:5]:
            head = headline_text(body, max(70, tweet_chars // 2))
            if head and head not in parts:
                parts.append(head)
        first["_thread_count"] = len(group)
        first["_body"] = f"thread {len(group)}条合并：" + "；".join(parts)
        merged.append({
            "name": group[0]["name"],
            "handle": group[0].get("handle", ""),
            "tweet": first,
            "_kol_order": group[0].get("_kol_order", 999999),
        })
    merged.sort(key=telegram_row_sort_key)
    return merged


def focus_rows(rows: list[dict[str, Any]], tweet_chars: int, limit: int, per_kol: int) -> list[dict[str, Any]]:
    merged = [row for row in merge_thread_rows(rows, tweet_chars) if is_focus_row(row)]
    merged.sort(key=telegram_row_sort_key)
    if per_kol > 0:
        counts: dict[tuple[str, str], int] = {}
        capped: list[dict[str, Any]] = []
        for row in merged:
            key = (str(row.get("name") or ""), str(row.get("handle") or ""))
            if counts.get(key, 0) >= per_kol:
                continue
            counts[key] = counts.get(key, 0) + 1
            capped.append(row)
        merged = capped
    return merged[:limit] if limit > 0 else merged


def telegram_section(number: int, row: dict[str, Any], tweet_chars: int, show_name: bool = True) -> str:
    tw = row["tweet"]
    body = tweet_body(tw, tweet_chars)
    if not body:
        return ""
    when = tweet_time_text(tw)
    name = str(row.get("name") or row.get("handle") or "").strip() or "unknown"
    handle = str(row.get("handle") or "").strip()
    author = name
    if show_name and handle and handle not in author:
        author = f"{author} {handle}"
    title = f"{number}. {author} | {when}" if show_name else f"{number}. {when}"
    return "\n".join([title, body, *tweet_link_lines(tw)])


def telegram_kol_blocks(rows: list[dict[str, Any]], tweet_chars: int, style: str) -> list[dict[str, Any]]:
    if style not in {"digest", "list"}:
        raise ValueError(f"unsupported Telegram style: {style}")
    blocks: list[dict[str, Any]] = []
    number = 1
    if style == "digest":
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in rows:
            key = (str(row.get("name") or ""), str(row.get("handle") or ""))
            grouped.setdefault(key, []).append(row)
        for (name, handle), group in grouped.items():
            author = name or handle or "unknown"
            if handle and handle not in author:
                author = f"{author} {handle}"
            sections: list[str] = []
            for row in group:
                section = telegram_section(number, row, tweet_chars, show_name=False)
                if section:
                    sections.append(section)
                    number += 1
            if sections:
                blocks.append({"title": author, "sections": sections, "count": len(sections)})
        return blocks
    for row in rows:
        section = telegram_section(number, row, tweet_chars, show_name=True)
        if not section:
            continue
        blocks.append({"title": "", "sections": [section], "count": 1})
        number += 1
    return blocks


def block_text(title: str, sections: list[str], continued: bool = False) -> str:
    if not title:
        return "\n\n".join(sections)
    suffix = " 续" if continued else ""
    return "\n\n".join([f"## {title}{suffix}", *sections])


def pack_telegram_blocks(blocks: list[dict[str, Any]], group_size: int) -> list[list[dict[str, Any]]]:
    max_items = group_size if group_size > 0 else sum(int(block.get("count") or 0) for block in blocks)
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_count = 0
    for block in blocks:
        if not block.get("sections"):
            continue
        title = str(block["title"])
        sections = list(block["sections"])
        sent = 0
        while sent < len(sections):
            group_limit = max_items
            if current_count >= group_limit:
                groups.append(current)
                current = []
                current_count = 0
                group_limit = max_items
            room = group_limit - current_count if group_limit > 0 else len(sections) - sent
            take = min(room, len(sections) - sent)
            continued = sent > 0
            text = block_text(title, sections[sent:sent + take], continued=continued)
            current.append({"text": text, "count": take})
            current_count += take
            sent += take
    if current:
        groups.append(current)
    return groups or [[]]


def build_market_report(
    hours: int,
    stablecoin_summary: str,
    total_pages: int = 1,
    mode: str = "full",
    generated_at: str = "",
) -> str:
    mode_suffix = " 重点" if mode == "focus" else ""
    now = generated_at or cn_now().strftime("%m-%d %H:%M")
    if total_pages > 1:
        header = f"市场全景 {hours}H{mode_suffix} | 第1/{total_pages}页 | {now}"
    else:
        header = f"市场全景 {hours}H{mode_suffix} | {now}"
    lines = [header]
    if stablecoin_summary:
        lines.extend(market_summary_with_separators(stablecoin_summary.splitlines()))
    return "\n".join(lines).strip() + "\n"


def build_telegram_reports(
    results: list[dict[str, Any]],
    hours: int,
    tweet_chars: int,
    per_kol: int,
    style: str,
    group_size: int,
    mode: str = "full",
    focus_limit: int = 0,
    focus_per_kol: int = DEFAULT_FOCUS_PER_KOL,
    include_low_signal: bool = False,
    stablecoin_summary: str = "",
) -> list[str]:
    active = [x for x in results if x.get("tweets")]
    summary = scan_summary(results)
    rows = telegram_rows(active, per_kol, include_low_signal)
    if mode == "focus":
        rows = focus_rows(rows, tweet_chars, focus_limit, focus_per_kol)
    now = cn_now().strftime("%m-%d %H:%M")
    selected_kol_title = "重点KOL" if mode == "focus" else "展示KOL"
    active_kol_label = f"{len(active)}/{len(results)}"
    scan_error_count = summary["errors"]
    unavailable_kol_count = summary["unavailable"] + summary["paused"]
    renamed_handles = [
        f"{item['configured_handle']}->{item['handle']}"
        for item in results
        if item.get("configured_handle")
        and str(item.get("configured_handle")).lower() != str(item.get("handle")).lower()
    ]
    unavailable_handles = []
    for item in results:
        if not str(item.get("error") or "").endswith(ACCOUNT_UNAVAILABLE_ERROR):
            continue
        reason = str(item.get("unavailable_reason") or "")
        action = "自动查改名" if reason == "missing" else "自动复查"
        unavailable_handles.append(
            f"{str(item.get('handle') or '').strip()}"
            f"({int(item.get('unavailable_days') or 1)}/"
            f"{UNAVAILABLE_REMOVAL_DAYS}，{action})"
        )
    unavailable_line = f"不可用KOL:{'、'.join(unavailable_handles)}" if unavailable_handles else ""
    renamed_line = f"账号改名:{'、'.join(renamed_handles)}" if renamed_handles else ""
    paused_handles = []
    for item in results:
        if item.get("status") != "paused":
            continue
        next_recheck_date = str(item.get("next_recheck_date") or "")
        display_date = next_recheck_date[5:] if len(next_recheck_date) == 10 else next_recheck_date
        paused_handles.append(
            f"{str(item.get('handle') or '').strip()}（下次复查 {display_date}）"
        )
    paused_line = f"封号暂停:{'、'.join(paused_handles)}" if paused_handles else ""
    fallback_used = summary["fallback_used"]
    fallback_deferred = summary["fallback_deferred"]
    fallback_total = fallback_used + fallback_deferred
    fallback_line = ""
    if fallback_total:
        fallback_line = f"搜索回退:{fallback_used}/{fallback_total}"
        if fallback_deferred:
            fallback_line += f"（延后{fallback_deferred}）"
    page_issue_handles = [
        str(item.get("handle") or "").strip()
        for item in results
        if item.get("status") == "error"
        and not (
            item.get("diagnostics", {}).get("global_page_deferred")
            and not item.get("diagnostics", {}).get("recovery_attempted")
        )
        and (
            item.get("diagnostics", {}).get("deferred_recovery")
            or str(item.get("error") or "").endswith(RECOVERABLE_X_PAGE_ERRORS)
        )
    ]
    scan_issue_handles = [
        str(item.get("handle") or "").strip()
        for item in results
        if item.get("status") == "error"
        and not str(item.get("error") or "").endswith(ACCOUNT_UNAVAILABLE_ERROR)
        and not item.get("diagnostics", {}).get("deferred_recovery")
        and not str(item.get("error") or "").endswith(RECOVERABLE_X_PAGE_ERRORS)
    ]
    page_issue_line = f"页面异常:{'、'.join(page_issue_handles)}" if page_issue_handles else ""
    scan_issue_line = f"扫描异常:{'、'.join(scan_issue_handles)}" if scan_issue_handles else ""
    recovery_deferred_line = (
        f"恢复延后:{summary['recovery_deferred']}"
        if summary["recovery_deferred"]
        else ""
    )
    status_lines = [
        line
        for line in (
            renamed_line,
            unavailable_line,
            paused_line,
            fallback_line,
            page_issue_line,
            scan_issue_line,
            recovery_deferred_line,
        )
        if line
    ]
    status_header = " | ".join(status_lines)
    if not rows:
        empty_text = "最近 24 小时有推文，但没有内容通过当前筛选。" if active else "最近 24 小时没有抓到可读推文。"
        market_report = build_market_report(
            hours,
            stablecoin_summary,
            mode=mode,
            generated_at=now,
        )
        status_text = f"状态 | {status_header}\n\n" if status_header else ""
        return [market_report.rstrip() + f"\n\n{status_text}{empty_text}\n"]

    blocks = telegram_kol_blocks(rows, tweet_chars, style)
    display_total = sum(int(block.get("count") or 0) for block in blocks)
    display_kol_count = len({
        (str(row.get("name") or "").strip(), str(row.get("handle") or "").strip())
        for row in rows
    })
    groups = pack_telegram_blocks(blocks, group_size)
    total_pages = len(groups) + 1
    reports = [build_market_report(
        hours,
        stablecoin_summary,
        total_pages=total_pages,
        mode=mode,
        generated_at=now,
    )]
    mode_suffix = " 重点" if mode == "focus" else ""

    for page_number, group in enumerate(groups, 2):
        group_count = sum(int(part.get("count") or 0) for part in group)
        if page_number == 2:
            header = f"KOL推文 {hours}H{mode_suffix} | 第{page_number}/{total_pages}页 | {now}"
            stats_line = (
                f"KOL扫描 正常{summary['success']} | 不可用{unavailable_kol_count} | "
                f"失败{scan_error_count} | 活跃{active_kol_label} | "
                f"{selected_kol_title} {display_kol_count} | 总推文 {display_total} | 本页 {group_count}"
            )
            lines = [header, stats_line]
        else:
            header = (
                f"KOL推文 {hours}H{mode_suffix} | 第{page_number}/{total_pages}页 | "
                f"总推文 {display_total} | 本页 {group_count} | {now}"
            )
            lines = [header]
        if page_number == 2 and status_header:
            lines.append(f"状态 | {status_header}")
        for part in group:
            lines.extend(["", str(part.get("text") or "").strip()])
        reports.append("\n".join(lines).strip() + "\n")
    return reports


def build_telegram_report(
    results: list[dict[str, Any]],
    hours: int,
    tweet_chars: int,
    per_kol: int,
    style: str,
    group_size: int = 20,
    mode: str = "full",
    focus_limit: int = 0,
    focus_per_kol: int = DEFAULT_FOCUS_PER_KOL,
    include_low_signal: bool = False,
    stablecoin_summary: str = "",
) -> str:
    return "\n---\n\n".join(
        report.strip()
        for report in build_telegram_reports(
            results,
            hours,
            tweet_chars,
            per_kol,
            style,
            group_size,
            mode,
            focus_limit,
            focus_per_kol,
            include_low_signal,
            stablecoin_summary,
        )
    ) + "\n"


def cached_results(limit: int, hours: int, handles: str = "") -> list[dict[str, Any]]:
    store = load_json(TWEET_STORE, {"tweets": {}}, strict=True)
    wanted = {"@" + x.strip().lstrip("@").lower() for x in handles.split(",") if x.strip()}
    aliases = store.get("handle_aliases", {})
    if not isinstance(aliases, dict):
        raise RuntimeError("invalid handle_aliases in tweets.json")
    configured = wanted or {row["handle"].lower() for row in parse_kols(KOLS_FILE)}
    allowed: set[str] = set()
    for handle in configured:
        canonical = canonical_handle(handle)
        if not canonical:
            continue
        allowed.add(canonical.lower())
        allowed.add(resolve_handle_alias(canonical, aliases).lower())
    cutoff_ms = int((dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)).timestamp() * 1000)
    rows = sorted(store.get("tweets", {}).values(), key=lambda x: x.get("created_at_ms", 0), reverse=True)
    rows_24h = []
    handles_24h = set()
    for row in rows:
        if int(row.get("created_at_ms") or 0) < cutoff_ms:
            continue
        handle = str(row.get("handle") or "")
        if handle.lower() not in allowed:
            continue
        rows_24h.append(row)
        handles_24h.add(handle.lower())
    selected = rows_24h[:limit] if limit > 0 else rows_24h
    grouped: dict[str, dict[str, Any]] = {}
    for row in selected:
        handle = str(row.get("handle") or "")
        item = grouped.setdefault(handle, {
            "name": row.get("name", ""),
            "handle": handle,
            "note": row.get("note", ""),
            "_total_24h": sum(1 for x in rows_24h if str(x.get("handle") or "").lower() == handle.lower()),
            "_global_total_24h": len(rows_24h),
            "_global_kol_24h": len(handles_24h),
            "tweets": [],
        })
        item["tweets"].append(row)
    return list(grouped.values())


def split_message(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    continuation = "（续）\n"
    chunk_limit = limit - len(continuation)
    chunks: list[str] = []
    remaining = text.strip()
    while len(remaining) > chunk_limit:
        chunk_count = (len(remaining) + chunk_limit - 1) // chunk_limit
        target = (len(remaining) + chunk_count - 1) // chunk_count
        before = remaining.rfind("\n\n", 0, target + 1)
        after = remaining.find("\n\n", target)
        candidates = [pos for pos in (before, after) if target // 2 <= pos <= chunk_limit]
        separator_len = 2
        if not candidates:
            before = remaining.rfind("\n", 0, target + 1)
            after = remaining.find("\n", target)
            candidates = [pos for pos in (before, after) if target // 2 <= pos <= chunk_limit]
            separator_len = 1
        split_at = min(candidates, key=lambda pos: abs(pos - target)) if candidates else target
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at + separator_len:] if candidates else remaining[split_at:]
    if remaining:
        chunks.append(remaining)
    return [chunk if index == 0 else continuation + chunk for index, chunk in enumerate(chunks)] or [text]


def telegram_retry_delay(attempt: int, body: str = "", headers: Any = None) -> float:
    retry_after = headers.get("Retry-After") if headers is not None else None
    if retry_after is None:
        try:
            payload = json.loads(body)
        except (TypeError, ValueError):
            payload = {}
        parameters = payload.get("parameters")
        if isinstance(parameters, dict):
            retry_after = parameters.get("retry_after")
    try:
        if retry_after is not None:
            return max(0.0, min(TELEGRAM_RETRY_MAX_SECONDS, float(retry_after)))
    except (TypeError, ValueError):
        pass
    return min(TELEGRAM_RETRY_MAX_SECONDS, TELEGRAM_RETRY_BASE_SECONDS * (2 ** attempt))


def telegram_send_chunk(chunk: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise RuntimeError("missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")
    if token.startswith("TELEGRAM_BOT_TOKEN=") or token.startswith("@") or not re.fullmatch(r"\d+:[A-Za-z0-9_-]{20,}", token):
        raise RuntimeError("invalid TELEGRAM_BOT_TOKEN secret: put only the token value, not the bot name or TELEGRAM_BOT_TOKEN=...")
    if chat_id.startswith("TELEGRAM_CHAT_ID="):
        raise RuntimeError("invalid TELEGRAM_CHAT_ID secret: put only the chat id value, not TELEGRAM_CHAT_ID=...")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": chunk,
        "disable_web_page_preview": "true",
    }).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/x-www-form-urlencoded"})
    body = ""
    for attempt in range(TELEGRAM_SEND_RETRIES + 1):
        try:
            with TELEGRAM_OPENER.open(req, timeout=30) as resp:
                body = resp.read().decode("utf-8", errors="replace")
            break
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code not in TELEGRAM_RETRYABLE_HTTP_CODES or attempt >= TELEGRAM_SEND_RETRIES:
                hint = " check TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID secrets" if exc.code in {400, 401, 403} else ""
                uncertainty = " send result is uncertain; not retrying" if exc.code in {408, 425, 500, 502, 503, 504} else ""
                raise RuntimeError(f"telegram HTTP {exc.code}:{hint}{uncertainty} response={body}") from exc
            delay = telegram_retry_delay(attempt, body, exc.headers)
            print(
                f"[telegram-retry] HTTP {exc.code} attempt={attempt + 1}/{TELEGRAM_SEND_RETRIES} delay={delay:.1f}s",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(delay)
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"telegram network error; send result is uncertain; not retrying: {exc}") from exc
    data = json.loads(body)
    if not data.get("ok"):
        raise RuntimeError(f"telegram send failed: {body}")


def telegram_send(text: str) -> None:
    for chunk in split_message(text):
        telegram_send_chunk(chunk)


def telegram_report_row_count(report: str) -> int:
    for line in report.splitlines()[:3]:
        match = re.search(r"(?:本页:|本页\s+|本组:|本组\s+)(\d+)", line)
        if match:
            return int(match.group(1))
    if report.startswith("市场全景 "):
        return 0
    raise RuntimeError("Telegram report header is missing its row count")


def telegram_send_reports(reports: list[str]) -> dict[str, int]:
    rows = sum(telegram_report_row_count(report) for report in reports)
    for report in reports:
        telegram_send(report)
    return {"groups": len(reports), "rows": rows}


def telegram_report_timestamp_normalized(report: str) -> str:
    return re.sub(
        r"(?m)^([^\n]* \| )\d{2}-\d{2} \d{2}:\d{2}(?= \||$)",
        r"\1<generated-at>",
        report,
        count=1,
    )


def telegram_report_is_summary_heading(line: str) -> bool:
    return line.startswith((
        "市场 | ",
        "加密市场",
        "市场现货",
        "市场合约",
        "链上确认交易（截至 ",
        "Hyperliquid清算价",
        "美国国债",
        "ETH 质押",
        "稳定币",
        "现货ETF资金流",
        "Strategy（微策略）",
        "美国宏观日程",
        "稳定币 | ",
        "稳定币流通量 | ",
        "口径：",
    )) or line.strip() in {"USDT", "USDC"}


def telegram_report_without_market_summary(report: str) -> str:
    lines = report.splitlines()
    metadata_end = len(lines)
    for index in range(1, len(lines)):
        if not lines[index].strip():
            metadata_end = index
            break
    kept = lines[:1]
    in_summary = False
    for line in lines[1:metadata_end]:
        if is_telegram_section_separator(line):
            continue
        if telegram_report_is_summary_heading(line):
            in_summary = True
            continue
        if in_summary:
            continue
        kept.append(line)
    kept.extend(lines[metadata_end:])
    return "\n".join(kept)


def telegram_report_summary_lines(report: str) -> list[str]:
    lines = report.splitlines()
    summary: list[str] = []
    for line in lines[1:]:
        if not line.strip():
            break
        if line == "KOL 推文":
            break
        if is_telegram_section_separator(line):
            continue
        if telegram_report_is_summary_heading(line):
            summary.append(line)
        elif summary:
            summary.append(line)
    return summary


def telegram_reports_fingerprint(reports: list[str]) -> str:
    normalized: list[str] = []
    for report in reports:
        report = telegram_report_timestamp_normalized(report)
        # Market data is refreshed on every run and must not invalidate a
        # Telegram resume record created before or after that refresh.
        report = telegram_report_without_market_summary(report)
        normalized.append(report + "\n")
    payload = "\n\0\n".join(normalized).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def telegram_report_legacy_summary_line(report: str) -> str:
    summary = telegram_report_summary_lines(report)
    if not summary:
        return ""
    if len(summary) == 1 and summary[0].startswith(("市场 | ", "稳定币 | ", "稳定币流通量 | ")):
        return summary[0]

    sections: dict[str, list[str]] = {}
    section = ""
    for line in summary:
        if telegram_report_is_summary_heading(line):
            if line.startswith("加密市场"):
                section = "加密市场"
            elif line.startswith("市场现货"):
                section = "市场现货"
            elif line.startswith("市场合约"):
                section = "市场合约"
            elif line.startswith("口径："):
                section = "口径"
            else:
                section = line.strip()
            sections.setdefault(section, [])
        elif section:
            sections[section].append(line.strip())

    parts: list[str] = []
    replacements = (
        ("全网（CEX+DEX）24H成交", "全网现货24H成交（CEX+DEX）"),
        ("DEX 24H成交", "DEX现货24H成交"),
        ("CEX 24H成交（估算）", "CEX现货24H成交（估算）"),
        ("全网24H成交", "全网合约24H成交"),
    )
    parts.extend(sections.get("加密市场", []))
    for line in sections.get("市场现货", []):
        for old, new in replacements[:3]:
            line = line.replace(old, new)
        parts.append(line)
    for line in sections.get("市场合约", []):
        parts.append(line.replace("全网24H成交", "全网合约24H成交"))
    for symbol in ("USDT", "USDC"):
        fields = []
        symbol_lines = list(sections.get(symbol, []))
        symbol_lines.extend(
            line.removeprefix(symbol)
            for line in sections.get("稳定币", [])
            if line.startswith(symbol)
        )
        for line in symbol_lines:
            if not line.startswith(("流通量 ", "流通 ", "24H现货成交 ", "现货成交 ", "现货24H成交 ")):
                continue
            line = line.replace("流通量 ", "流通")
            line = line.replace("流通 ", "流通")
            line = line.replace("24H现货成交 ", "全市场现货24H成交")
            line = line.replace("现货成交 ", "全市场现货24H成交")
            line = line.replace("现货24H成交 ", "全市场现货24H成交")
            fields.append(line)
        if fields:
            parts.append(f"{symbol} " + " ".join(fields))
    if sections.get("Strategy（微策略）"):
        parts.append("Strategy（微策略） " + " ".join(sections["Strategy（微策略）"]))
    if sections.get("美国国债"):
        parts.append("美国国债 " + " ".join(sections["美国国债"]))
    return "市场 | " + " | ".join(parts) if parts else ""


def telegram_legacy_report(report: str, include_summary: bool) -> str:
    lines = report.splitlines()
    metadata_end = next((index for index, line in enumerate(lines[1:], 1) if not line.strip()), len(lines))
    header = lines[0] if lines else ""
    stats_line = next(
        (line for line in lines[1:metadata_end] if line.startswith(("KOL扫描 ", "扫描 "))),
        "",
    )
    timestamp_match = re.search(r" \| (\d{2}-\d{2} \d{2}:\d{2})(?: \|.*)?$", header)
    stats_match = re.match(
        r"(?:KOL扫描|扫描) 正常(\d+) \| 不可用(\d+) \| 失败(\d+) \| 活跃(\d+)/(\d+) \| "
        r"((?:展示KOL|重点KOL)) (\d+) \| (?:总推文|推文) (\d+) \| (?:本页|本组) (\d+)$",
        stats_line,
    )
    if timestamp_match and stats_match:
        header = (
            f"{header[:timestamp_match.start()]} | "
            f"扫描KOL:{stats_match.group(1)}/{stats_match.group(5)} | "
            f"扫描失败:{stats_match.group(3)} | "
            f"活跃KOL:{stats_match.group(4)}/{stats_match.group(5)} | "
            f"{stats_match.group(6)}:{stats_match.group(7)} | "
            f"推文:{stats_match.group(8)} | 本组:{stats_match.group(9)} | "
            f"{timestamp_match.group(1)}"
        )
    summary = []
    if include_summary:
        legacy_summary = telegram_report_legacy_summary_line(report)
        if legacy_summary:
            summary = [legacy_summary]
    statuses: list[str] = []
    for line in lines[1:metadata_end]:
        if line.startswith("状态 | "):
            statuses.extend(
                status
                for status in line.removeprefix("状态 | ").split(" | ")
                if status.startswith(("账号改名:", "不可用KOL:", "封号暂停:"))
            )
        elif line.startswith(("账号改名:", "不可用KOL:", "封号暂停:")):
            statuses.append(line)
    return "\n".join([header, *summary, *statuses, *lines[metadata_end:]]) + "\n"


def telegram_previous_market_label_report(report: str) -> str:
    lines = report.splitlines()
    if len(lines) < 2:
        return report
    header_match = re.fullmatch(
        r"市场全景 (\d+)H( 重点)? \| 第(\d+)/(\d+)页 \| (.+)",
        lines[0],
    )
    if not header_match:
        return report
    previous_mode = "重点" if header_match.group(2) else "全景"
    lines[0] = (
        f"加密市场 {header_match.group(1)}H {previous_mode} | "
        f"第{header_match.group(3)}/{header_match.group(4)}页 | {header_match.group(5)}"
    )
    suffix = "\n" if report.endswith("\n") else ""
    return "\n".join(lines) + suffix


def telegram_previous_label_report(report: str) -> str:
    report = telegram_previous_market_label_report(report)
    lines = report.splitlines()
    if len(lines) < 2:
        return report
    header_match = re.fullmatch(
        r"加密市场 (\d+)H (全景|重点) \| 第(\d+)/(\d+)页 \| (.+)",
        lines[0],
    )
    stats_match = re.fullmatch(
        r"KOL扫描 正常(\d+) \| 不可用(\d+) \| 失败(\d+) \| 活跃(\d+)/(\d+) \| "
        r"((?:展示KOL|重点KOL)) (\d+) \| 总推文 (\d+) \| 本页 (\d+)",
        lines[1],
    )
    if not header_match or not stats_match:
        return report
    previous_mode = "全量" if header_match.group(2) == "全景" else "重点"
    lines[0] = (
        f"X KOL {header_match.group(1)}H {previous_mode} | "
        f"组:{header_match.group(3)}/{header_match.group(4)} | {header_match.group(5)}"
    )
    lines[1] = (
        f"扫描 {stats_match.group(1)}/{stats_match.group(5)}"
        f"（失败{stats_match.group(3)}） | "
        f"活跃 {stats_match.group(4)}/{stats_match.group(5)} | "
        f"{stats_match.group(6)} {stats_match.group(7)} | "
        f"推文 {stats_match.group(8)} | 本组 {stats_match.group(9)}"
    )
    suffix = "\n" if report.endswith("\n") else ""
    return "\n".join(lines) + suffix


def telegram_reports_legacy_fingerprints(reports: list[str]) -> set[str]:
    fingerprints = {
        telegram_reports_fingerprint([
            telegram_previous_market_label_report(report)
            for report in reports
        ]),
        telegram_reports_fingerprint([
            telegram_previous_label_report(report)
            for report in reports
        ])
    }
    for include_summary in (True, False):
        normalized = [telegram_report_timestamp_normalized(telegram_legacy_report(report, include_summary)) for report in reports]
        payload = "\n\0\n".join(normalized).encode("utf-8")
        fingerprints.add(hashlib.sha256(payload).hexdigest())
    return fingerprints


def stablecoin_summary_from_reports(reports: list[str]) -> str:
    for report in reports[:1]:
        summary = telegram_report_summary_lines(report)
        if summary:
            return "\n".join(summary)
    return ""


def apply_stablecoin_summary(reports: list[str], summary: str) -> list[str]:
    if not reports:
        return reports
    updated = list(reports)
    lines = updated[0].splitlines()
    metadata_end = next((index for index, line in enumerate(lines[1:], 1) if not line.strip()), len(lines))
    kept = [lines[0]]
    in_summary = False
    for line in lines[1:metadata_end]:
        if is_telegram_section_separator(line):
            continue
        if telegram_report_is_summary_heading(line):
            in_summary = True
            continue
        if in_summary:
            continue
        kept.append(line)
    kept.extend(lines[metadata_end:])
    lines = kept
    if summary:
        insert_at = 1
        while insert_at < len(lines) and lines[insert_at].startswith(("KOL扫描 ", "扫描 ", "状态 | ", "账号改名:", "不可用KOL:", "封号暂停:", "搜索回退:", "扫描异常:", "页面异常:")):
            insert_at += 1
        summary_lines = market_summary_with_separators(summary.splitlines())
        summary_block = list(summary_lines)
        if telegram_report_row_count(updated[0]) > 0:
            summary_block.extend([TELEGRAM_SECTION_SEPARATOR, "KOL 推文"])
        lines[insert_at:insert_at] = summary_block
    updated[0] = "\n".join(lines).rstrip() + "\n"
    return updated


def telegram_report_chunks(reports: list[str]) -> list[dict[str, Any]]:
    physical: list[dict[str, Any]] = []
    for group_index, report in enumerate(reports):
        chunks = split_message(report)
        rows = telegram_report_row_count(report)
        for chunk_index, chunk in enumerate(chunks):
            group_last = chunk_index + 1 == len(chunks)
            physical.append({
                "text": chunk,
                "group_index": group_index,
                "group_last": group_last,
                "rows": rows if group_last else 0,
            })
    return physical


def scheduled_send_key(args: argparse.Namespace) -> str:
    override = str(getattr(args, "send_once_key", "") or "").strip()
    if not override:
        override = os.environ.get("X_KOL_SEND_ONCE_KEY", "").strip()
    if override:
        return override
    event_name = os.environ.get("GITHUB_EVENT_NAME", "").strip()
    if event_name not in {"schedule", "workflow_dispatch"}:
        return ""
    if event_name == "workflow_dispatch":
        run_id = os.environ.get("GITHUB_RUN_ID", "").strip()
        if not run_id:
            return ""
        return ":".join(["manual", run_id, f"{args.hours}h", args.telegram_mode])
    return ":".join([
        cn_now().strftime("%Y%m%d"),
        f"{args.hours}h",
        args.telegram_mode,
    ])


def telegram_send_reports_once(reports: list[str], args: argparse.Namespace) -> dict[str, int]:
    key = scheduled_send_key(args)
    if not key:
        return telegram_send_reports(reports)
    state = load_json(SENT_STATE, {"version": 2, "sent": {}}, strict=True)
    sent = state.setdefault("sent", {})
    existing = sent.get(key)
    if existing and "completed_groups" not in existing:
        print(f"scheduled send skipped: already sent key={key}")
        return {"groups": 0, "rows": 0, "skipped": 1}
    if existing:
        stored_summary = str(existing.get("stablecoin_summary") or "")
        reports = apply_stablecoin_summary(reports, stored_summary)
    fingerprint = telegram_reports_fingerprint(reports)
    legacy_fingerprints = telegram_reports_legacy_fingerprints(reports)
    physical = telegram_report_chunks(reports)
    total_chunks = len(physical)
    record = existing or {
        "created_at": cn_now().isoformat(timespec="seconds"),
        "fingerprint": fingerprint,
        "total_groups": len(reports),
        "total_chunks": total_chunks,
        "completed_groups": 0,
        "completed_chunks": 0,
        "rows": 0,
        "completed": False,
        "stablecoin_summary": stablecoin_summary_from_reports(reports),
    }
    if record.get("completed"):
        print(f"scheduled send skipped: already sent key={key}")
        return {"groups": 0, "rows": 0, "skipped": 1}
    if record.get("fingerprint") != fingerprint:
        if record.get("fingerprint") in legacy_fingerprints:
            record["fingerprint"] = fingerprint
        else:
            raise RuntimeError("scheduled report changed after a partial send; refusing to resend")
    if int(record.get("total_groups") or 0) != len(reports):
        raise RuntimeError("scheduled report changed after a partial send; refusing to resend")
    completed_groups = int(record.get("completed_groups") or 0)
    if completed_groups < 0 or completed_groups > len(reports):
        raise RuntimeError("invalid Telegram send progress")
    if "completed_chunks" in record:
        completed_chunks = int(record.get("completed_chunks") or 0)
    else:
        completed_chunks = sum(len(split_message(report)) for report in reports[:completed_groups])
        record["completed_chunks"] = completed_chunks
    stored_total_chunks = record.get("total_chunks")
    if stored_total_chunks is None:
        stored_total_chunks = total_chunks
        record["total_chunks"] = total_chunks
    else:
        stored_total_chunks = int(stored_total_chunks)
        if stored_total_chunks != total_chunks:
            if completed_chunks:
                raise RuntimeError("scheduled report chunk layout changed after a partial send; refusing to resend")
            record["total_chunks"] = total_chunks
    if completed_chunks < 0 or completed_chunks > total_chunks:
        raise RuntimeError("invalid Telegram chunk progress")
    derived_completed_groups = sum(
        1 for item in physical[:completed_chunks] if item["group_last"]
    )
    if derived_completed_groups != completed_groups:
        raise RuntimeError("inconsistent Telegram group and chunk progress")
    sent[key] = record
    state["version"] = 3
    save_json(SENT_STATE, state)

    sent_groups = 0
    sent_rows = 0
    resumed_chunks = completed_chunks
    for index in range(completed_chunks, total_chunks):
        item = physical[index]
        telegram_send_chunk(str(item["text"]))
        record["completed_chunks"] = index + 1
        if item["group_last"]:
            rows = int(item["rows"])
            sent_groups += 1
            sent_rows += rows
            record["completed_groups"] = int(item["group_index"]) + 1
            record["rows"] = int(record.get("rows") or 0) + rows
        record["updated_at"] = cn_now().isoformat(timespec="seconds")
        record["completed"] = index + 1 == total_chunks
        if record["completed"]:
            record["sent_at"] = record["updated_at"]
        save_json(SENT_STATE, state)
    return {
        "groups": sent_groups,
        "rows": sent_rows,
        "resumed_from": completed_groups,
        "resumed_chunks": resumed_chunks,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--limit", type=int, default=8, help="max tweets per KOL")
    ap.add_argument("--max-kols", type=int, default=0, help="test only: scan first N KOLs")
    ap.add_argument("--handles", default="", help="comma-separated handles for testing, e.g. @OpenAI,@saylor")
    ap.add_argument("--scrolls", type=int, default=6)
    ap.add_argument("--page-wait-ms", type=int, default=2500)
    ap.add_argument("--scroll-wait-ms", type=int, default=900)
    ap.add_argument("--search-fallback", action=argparse.BooleanOptionalAction, default=True, help="try X search only when profile page has no recent tweets")
    ap.add_argument("--headed", action="store_true", help="show browser")
    ap.add_argument("--send", action="store_true", help="send report to Telegram")
    ap.add_argument("--no-send", action="store_true", help="do not send Telegram after a live scan")
    ap.add_argument("--market-only", action="store_true", help="build only the market overview; never scan KOLs")
    ap.add_argument("--send-once-key", default="", help="explicit idempotency key for Telegram sending")
    ap.add_argument("--no-translate", action="store_true")
    ap.add_argument("--translate-cache", action="store_true", help="translate missing English tweets in cache only")
    ap.add_argument(
        "--translate-limit",
        type=int,
        default=20,
        help="target translations per run; current scan is always completed even above it; 0 means no limit",
    )
    ap.add_argument("--cache-recent", type=int, default=0, help="print recent tweets from local cache, no web scan")
    ap.add_argument("--telegram-chars", type=int, default=0, help="max chars per tweet in Telegram; 0 keeps full text")
    ap.add_argument("--telegram-per-kol", type=int, default=0, help="max tweets per KOL in Telegram; 0 means no limit")
    ap.add_argument("--telegram-group-size", type=int, default=20, help="max tweets per Telegram message group; 0 means one group")
    ap.add_argument("--telegram-style", choices=["digest", "list"], default="list")
    ap.add_argument("--telegram-mode", choices=["full", "focus"], default="full", help="full sends all selected tweets; focus filters noisy tweets and merges threads")
    ap.add_argument("--telegram-focus-limit", type=int, default=0, help="max tweets/thread summaries in focus mode; 0 means no limit")
    ap.add_argument("--telegram-focus-per-kol", type=int, default=DEFAULT_FOCUS_PER_KOL, help="max focus rows per KOL; 0 means no per-KOL cap")
    ap.add_argument("--include-low-signal", action="store_true", help="include short replies, CTA text, and low-signal tweets in Telegram output")
    ap.add_argument("--telegram-preview", action="store_true", help="print Telegram compact format")
    ap.add_argument("--dry-run", action="store_true", help="parse config only")
    args = ap.parse_args()
    live_scan_send = not args.no_send

    load_dotenv(ROOT / ".env")
    if args.market_only:
        stablecoin_summary = fetch_stablecoin_summary()
        if not stablecoin_summary:
            raise RuntimeError("market overview is unavailable")
        report = build_market_report(args.hours, stablecoin_summary)
        if args.telegram_preview or not args.send or args.no_send:
            print(report)
        if args.send and not args.no_send:
            stats = telegram_send_reports_once([report], args)
            print(f"sent groups={stats['groups']} rows={stats['rows']}")
        return 0
    if args.cache_recent > 0:
        results = cached_results(args.cache_recent, args.hours, args.handles)
        stablecoin_summary = fetch_stablecoin_summary() if args.telegram_preview or (args.send and not args.no_send) else ""
        if args.telegram_preview:
            report = build_telegram_report(
                results,
                args.hours,
                args.telegram_chars,
                args.telegram_per_kol,
                args.telegram_style,
                args.telegram_group_size,
                args.telegram_mode,
                args.telegram_focus_limit,
                args.telegram_focus_per_kol,
                args.include_low_signal,
                stablecoin_summary,
            )
            print(report)
        elif args.send:
            report = ""
        else:
            report = build_report(results, args.hours)
            print(report)
        if args.send and not args.no_send:
            reports = build_telegram_reports(
                results,
                args.hours,
                args.telegram_chars,
                args.telegram_per_kol,
                args.telegram_style,
                args.telegram_group_size,
                args.telegram_mode,
                args.telegram_focus_limit,
                args.telegram_focus_per_kol,
                args.include_low_signal,
                stablecoin_summary,
            )
            stats = telegram_send_reports_once(reports, args)
            print(f"sent groups={stats['groups']} rows={stats['rows']}")
        return 0
    if args.translate_cache:
        stats = translate_tweet_store(args.translate_limit)
        print(json.dumps({"cache": str(TWEET_STORE), **stats}, ensure_ascii=False))
        return 0

    kols = apply_handle_aliases(parse_kols(KOLS_FILE))
    if args.dry_run:
        print(json.dumps({"ok": True, "kols": len(kols), "sample": kols[:5]}, ensure_ascii=False, indent=2))
        return 0
    if not kols:
        raise RuntimeError(f"no KOLs found: {KOLS_FILE}")
    if args.handles.strip():
        wanted = {"@" + x.strip().lstrip("@").lower() for x in args.handles.split(",") if x.strip()}
        kols = [
            x for x in kols
            if x["handle"].lower() in wanted
            or str(x.get("configured_handle") or "").lower() in wanted
        ]
        if not kols:
            raise RuntimeError(f"no matching handles: {args.handles}")
    if args.max_kols > 0:
        kols = kols[:args.max_kols]
    kols = apply_unavailable_recheck_policy(
        kols,
        force_recheck=bool(args.handles.strip()),
    )

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    run_started = time.monotonic()
    phase_timings: dict[str, float] = {}
    phase_started = time.monotonic()
    results, x_phase_timings = scrape_all(
        kols,
        args.hours,
        args.limit,
        args.scrolls,
        headless=not args.headed,
        page_wait_ms=args.page_wait_ms,
        scroll_wait_ms=args.scroll_wait_ms,
        search_fallback=args.search_fallback,
    )
    phase_timings["x_scan"] = time.monotonic() - phase_started
    phase_timings.update(x_phase_timings)
    update_kol_status(results)
    summary = scan_summary(results)
    print(json.dumps({"scan": summary}, ensure_ascii=False))
    for item in results:
        if item.get("status") == "error":
            category = (
                "scan-unavailable"
                if str(item.get("error") or "").endswith(ACCOUNT_UNAVAILABLE_ERROR)
                else "scan-error"
            )
            print(
                f"[{category}] {item.get('handle', '')} {item.get('error', '')}",
                file=sys.stderr,
            )

    ensure_scan_deliverable(results, summary)

    stamp = cn_now().strftime("%Y%m%d-%H%M%S")
    day = cn_now().strftime("%Y%m%d")
    store_stats = update_tweet_store(results, stamp)
    translate_stats = {
        "translated": 0,
        "skipped": 0,
        "failed": 0,
        "deferred": 0,
        "priority_needed": 0,
        "priority_pending": 0,
    }
    phase_started = time.monotonic()
    if not args.no_translate:
        current_tweet_ids = {
            tweet_id(tw)
            for item in results
            for tw in item.get("tweets", [])
        }
        translate_stats = translate_tweet_store(args.translate_limit, current_tweet_ids)
        apply_store_translations(results)
    phase_timings["translation"] = time.monotonic() - phase_started
    save_json(STATE_DIR / f"{day}.json", {"hours": args.hours, "store": store_stats, "results": results})
    report = build_report(results, args.hours)
    report_path = REPORT_DIR / f"{day}.md"
    report_path.write_text(report, encoding="utf-8")
    prune_daily_outputs()
    print(str(report_path))
    print(json.dumps({"store": store_stats, "translate": translate_stats}, ensure_ascii=False))
    if args.send or live_scan_send:
        phase_started = time.monotonic()
        stablecoin_summary = fetch_stablecoin_summary()
        phase_timings["market"] = time.monotonic() - phase_started
        reports = build_telegram_reports(
            results,
            args.hours,
            args.telegram_chars,
            args.telegram_per_kol,
            args.telegram_style,
            args.telegram_group_size,
            args.telegram_mode,
            args.telegram_focus_limit,
            args.telegram_focus_per_kol,
            args.include_low_signal,
            stablecoin_summary,
        )
        phase_started = time.monotonic()
        stats = telegram_send_reports_once(reports, args)
        phase_timings["telegram"] = time.monotonic() - phase_started
        print(f"sent groups={stats['groups']} rows={stats['rows']}")
    phase_timings["total"] = time.monotonic() - run_started
    print(json.dumps({
        "timing_seconds": {
            key: round(value, 1)
            for key, value in phase_timings.items()
        },
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
