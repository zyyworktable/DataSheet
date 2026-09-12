from __future__ import annotations

import json
import re
import ssl
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Iterable

from .domain import FetchResult, QuoteSnapshot, Security
from .sessions import CHINA_TZ, KOREA_TZ, US_TZ, market_now, session_state


# Import and initialize SSL before urllib builds its default opener. PyInstaller
# otherwise cannot always infer the dynamic HTTPS handler used by urllib.
_SSL_CONTEXT = ssl.create_default_context()
_LOCAL_SSL_CONTEXT = ssl._create_unverified_context()


class ProviderError(RuntimeError):
    pass


def _float(value: Any) -> float | None:
    if value in (None, "", "-"):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _chunks(values: list[Security], size: int) -> Iterable[list[Security]]:
    for offset in range(0, len(values), size):
        yield values[offset : offset + size]


class EastmoneyProvider:
    name = "东方财富"
    endpoint = "https://push2.eastmoney.com/api/qt/ulist.np/get"

    def fetch(self, securities: list[Security]) -> dict[str, QuoteSnapshot]:
        snapshots: dict[str, QuoteSnapshot] = {}
        for batch in _chunks(securities, 35):
            snapshots.update(self._fetch_batch(batch))
        if securities and not snapshots:
            raise ProviderError("东方财富未返回有效行情")
        return snapshots

    def _fetch_batch(self, securities: list[Security]) -> dict[str, QuoteSnapshot]:
        candidates: list[str] = []
        lookup: dict[tuple[str, str], str] = {}
        for security in securities:
            for market, code in self._provider_codes(security):
                candidates.append(f"{market}.{code}")
                lookup[(market, code.upper())] = security.key

        params = urllib.parse.urlencode(
            {
                "fltt": "2",
                "invt": "2",
                "fields": "f2,f3,f4,f5,f6,f12,f13,f14,f15,f16,f17,f18,f124",
                "secids": ",".join(candidates),
            }
        )
        request = urllib.request.Request(
            f"{self.endpoint}?{params}",
            headers={"User-Agent": "Mozilla/5.0 DataSheet/1.0", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=6, context=_SSL_CONTEXT) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # urllib exposes several platform-specific errors
            raise ProviderError(f"东方财富连接失败：{exc}") from exc

        rows = ((payload or {}).get("data") or {}).get("diff") or []
        if isinstance(rows, dict):
            rows = list(rows.values())
        result: dict[str, QuoteSnapshot] = {}
        for row in rows:
            market = str(row.get("f13", ""))
            code = str(row.get("f12", "")).upper()
            key = lookup.get((market, code))
            if not key:
                continue
            timestamp = _float(row.get("f124"))
            quote_time = datetime.fromtimestamp(timestamp, timezone.utc) if timestamp else None
            result[key] = QuoteSnapshot(
                security_key=key,
                name=str(row.get("f14") or ""),
                last=_float(row.get("f2")),
                change=_float(row.get("f4")),
                change_pct=_float(row.get("f3")),
                open=_float(row.get("f17")),
                high=_float(row.get("f15")),
                low=_float(row.get("f16")),
                prev_close=_float(row.get("f18")),
                volume=_float(row.get("f5")),
                amount=_float(row.get("f6")),
                quote_time=quote_time,
                source=self.name,
            )
        return result

    @staticmethod
    def _provider_codes(security: Security) -> list[tuple[str, str]]:
        fixed = {
            "IDX.CN.SHCOMP": [("1", "000001")],
            "IDX.CN.SZCOMP": [("0", "399001")],
            "IDX.CN.CHINEXT": [("0", "399006")],
            "IDX.US.DJI": [("100", "DJIA")],
            "IDX.US.SPX": [("100", "SPX")],
            "IDX.US.IXIC": [("100", "IXIC")],
        }
        if security.key in fixed:
            return fixed[security.key]
        if security.region == "CN":
            return [("1" if security.exchange == "SH" else "0", security.code)]
        return [(market, security.code) for market in ("105", "106", "107")]


class TencentProvider:
    name = "腾讯"
    endpoint = "https://qt.gtimg.cn/q="

    def fetch(self, securities: list[Security]) -> dict[str, QuoteSnapshot]:
        snapshots: dict[str, QuoteSnapshot] = {}
        for batch in _chunks(securities, 55):
            snapshots.update(self._fetch_batch(batch))
        if securities and not snapshots:
            raise ProviderError("腾讯未返回有效行情")
        return snapshots

    def _fetch_batch(self, securities: list[Security]) -> dict[str, QuoteSnapshot]:
        lookup: dict[str, Security] = {}
        for security in securities:
            query_code = self._provider_code(security)
            lookup[query_code.upper()] = security
        query = ",".join(self._provider_code(item) for item in securities)
        request = urllib.request.Request(
            f"{self.endpoint}{query}",
            headers={
                "User-Agent": "Mozilla/5.0 DataSheet/1.0",
                "Referer": "https://stockapp.finance.qq.com/",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=6, context=_SSL_CONTEXT) as response:
                text = response.read().decode("gbk", errors="replace")
        except Exception as exc:
            raise ProviderError(f"腾讯连接失败：{exc}") from exc

        result: dict[str, QuoteSnapshot] = {}
        for line in text.splitlines():
            if "=" not in line:
                continue
            variable, raw_value = line.split("=", 1)
            query_code = variable.removeprefix("v_").upper()
            security = lookup.get(query_code)
            if not security:
                continue
            value = raw_value.strip().strip(";\r\n").strip('"')
            parts = value.split("~")
            if len(parts) < 38 or not parts[1]:
                continue
            quote_time = self._parse_time(parts[30], security.region)
            amount = _float(parts[37])
            if amount is not None and security.region == "CN":
                amount *= 10_000
            result[security.key] = QuoteSnapshot(
                security_key=security.key,
                name=parts[1],
                last=_float(parts[3]),
                change=_float(parts[31]),
                change_pct=_float(parts[32]),
                open=_float(parts[5]),
                high=_float(parts[33]),
                low=_float(parts[34]),
                prev_close=_float(parts[4]),
                volume=_float(parts[36]),
                amount=amount,
                quote_time=quote_time,
                source=self.name,
            )
        return result

    @staticmethod
    def _provider_code(security: Security) -> str:
        fixed = {
            "IDX.CN.SHCOMP": "sh000001",
            "IDX.CN.SZCOMP": "sz399001",
            "IDX.CN.CHINEXT": "sz399006",
            "IDX.US.DJI": "us.DJI",
            "IDX.US.SPX": "us.INX",
            "IDX.US.IXIC": "us.IXIC",
        }
        if security.key in fixed:
            return fixed[security.key]
        if security.region == "CN":
            return f"{security.exchange.lower()}{security.code}"
        return f"us{security.code}"

    @staticmethod
    def _parse_time(value: str, region: str) -> datetime | None:
        if not value:
            return None
        try:
            if region == "CN":
                parsed = datetime.strptime(value, "%Y%m%d%H%M%S")
                return parsed.replace(tzinfo=CHINA_TZ)
            parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
            return parsed.replace(tzinfo=US_TZ)
        except ValueError:
            return None


class YahooUSExtendedProvider:
    """Fetches batched US pre-market and after-hours trades from Yahoo Spark."""

    name = "Yahoo扩展时段"
    endpoint = "https://query1.finance.yahoo.com/v7/finance/spark"

    def fetch(self, securities: list[Security]) -> dict[str, QuoteSnapshot]:
        equities = [
            item for item in securities if item.region == "US" and item.kind != "index"
        ]
        snapshots: dict[str, QuoteSnapshot] = {}
        for batch in _chunks(equities, 40):
            snapshots.update(self._fetch_batch(batch))
        if equities and not snapshots:
            raise ProviderError("Yahoo未返回有效的美股扩展时段行情")
        return snapshots

    def _fetch_batch(self, securities: list[Security]) -> dict[str, QuoteSnapshot]:
        provider_codes = {
            security.code.replace(".", "-").upper(): security for security in securities
        }
        params = urllib.parse.urlencode(
            {
                "symbols": ",".join(provider_codes),
                "range": "1d",
                "interval": "1m",
                "indicators": "close",
                "includeTimestamps": "true",
                "includePrePost": "true",
            }
        )
        request = urllib.request.Request(
            f"{self.endpoint}?{params}",
            headers={"User-Agent": "Mozilla/5.0 DataSheet/1.0", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=8, context=_SSL_CONTEXT) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise ProviderError(f"Yahoo美股扩展行情连接失败：{exc}") from exc

        rows = ((payload or {}).get("spark") or {}).get("result") or []
        result: dict[str, QuoteSnapshot] = {}
        for row in rows:
            security = provider_codes.get(str(row.get("symbol") or "").upper())
            responses = row.get("response") or []
            if not security or not responses:
                continue
            response = responses[0] or {}
            meta = response.get("meta") or {}
            timestamps = response.get("timestamp") or []
            quote_rows = ((response.get("indicators") or {}).get("quote") or [{}])
            closes = (quote_rows[0] or {}).get("close") or []
            latest = next(
                (
                    (int(timestamp), _float(price))
                    for timestamp, price in reversed(list(zip(timestamps, closes)))
                    if timestamp and _float(price) is not None
                ),
                None,
            )
            if not latest:
                continue
            timestamp, last = latest
            price_session = self._price_session(timestamp, meta.get("currentTradingPeriod") or {})
            if price_session not in {"盘前", "盘后"}:
                continue
            previous = _float(meta.get("previousClose") or meta.get("chartPreviousClose"))
            change = last - previous if previous is not None else None
            change_pct = change / previous * 100 if change is not None and previous else None
            result[security.key] = QuoteSnapshot(
                security_key=security.key,
                name=str(meta.get("longName") or meta.get("shortName") or security.name),
                last=last,
                change=change,
                change_pct=change_pct,
                prev_close=previous,
                quote_time=datetime.fromtimestamp(timestamp, timezone.utc),
                source=f"Yahoo{price_session}",
                price_session=price_session,
            )
        return result

    @staticmethod
    def _price_session(timestamp: int, periods: dict[str, Any]) -> str | None:
        for field, label in (("pre", "盘前"), ("post", "盘后")):
            period = periods.get(field) or {}
            start = int(period.get("start") or 0)
            end = int(period.get("end") or 0)
            if start <= timestamp <= end and start < end:
                return label
        return None


class IBKROvernightProvider:
    """Reads US overnight quotes from an authenticated local IBKR gateway.

    The OVERNIGHT venue is deliberately requested explicitly.  IBKR documents
    that its prices differ from regular SMART-routed market data.  This class
    is quote-only and never calls order, account or credential endpoints.
    """

    name = "IBKR隔夜"
    fields = "31,55,70,71,82,83,84,86,87,7295,7296,7635,7059"

    def __init__(
        self,
        base_url: str = "https://localhost:5000/v1/api",
        timeout: float = 2.0,
        retry_seconds: float = 30.0,
    ) -> None:
        parsed = urllib.parse.urlsplit(base_url)
        if parsed.scheme != "https" or (parsed.hostname or "").lower() not in {
            "localhost",
            "127.0.0.1",
            "::1",
        }:
            raise ValueError("IBKR 网关地址必须是本机 HTTPS 地址")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retry_seconds = retry_seconds
        self._conids: dict[str, int] = {}
        self._retry_after = 0.0

    def fetch(self, securities: list[Security]) -> dict[str, QuoteSnapshot]:
        equities = [
            item for item in securities if item.region == "US" and item.kind != "index"
        ]
        if not equities:
            return {}
        if time.monotonic() < self._retry_after:
            raise ProviderError("IBKR 本地网关未连接")
        try:
            snapshots = self._fetch(equities)
            self._retry_after = 0.0
            return snapshots
        except ProviderError:
            self._retry_after = time.monotonic() + self.retry_seconds
            raise

    def _fetch(self, securities: list[Security]) -> dict[str, QuoteSnapshot]:
        status = self._read_json("/iserver/auth/status")
        if not status.get("authenticated") or status.get("connected") is False:
            raise ProviderError("IBKR 本地网关尚未登录")

        self._resolve_conids(securities)
        available = [item for item in securities if item.key in self._conids]
        if not available:
            raise ProviderError("IBKR 未识别这些美股代码")

        conid_ex = [f"{self._conids[item.key]}@OVERNIGHT" for item in available]
        rows = self._snapshot(conid_ex)
        if not any(self._row_has_price(row) for row in rows):
            # The first Client Portal snapshot request subscribes the stream;
            # a short second request obtains the populated fields.
            time.sleep(0.2)
            rows = self._snapshot(conid_ex)

        lookup: dict[str, Security] = {}
        for security in available:
            conid = self._conids[security.key]
            lookup[str(conid)] = security
            lookup[f"{conid}@OVERNIGHT"] = security

        result: dict[str, QuoteSnapshot] = {}
        for row in rows:
            key = str(row.get("conidEx") or row.get("conid") or "")
            security = lookup.get(key) or lookup.get(key.split("@", 1)[0])
            if not security:
                continue
            last = _ibkr_float(row.get("31"))
            price_kind = "成交价"
            if last is None:
                last = _ibkr_float(row.get("7635"))
                price_kind = "标记价"
            if last is None:
                bid = _ibkr_float(row.get("84"))
                ask = _ibkr_float(row.get("86"))
                if bid is not None and ask is not None:
                    last = (bid + ask) / 2
                    price_kind = "买卖中间价"
            if last is None:
                continue

            previous = _ibkr_float(row.get("7296"))
            change = _ibkr_float(row.get("82"))
            change_pct = _ibkr_float(row.get("83"))
            if change is None and previous is not None:
                change = last - previous
            if change_pct is None and change is not None and previous:
                change_pct = change / previous * 100

            updated = _ibkr_float(row.get("_updated"))
            if updated:
                timestamp = updated / 1000 if updated > 100_000_000_000 else updated
                quote_time = datetime.fromtimestamp(timestamp, timezone.utc)
            else:
                quote_time = datetime.now(timezone.utc)
            source = self.name if price_kind == "成交价" else f"{self.name}（{price_kind}）"
            result[security.key] = QuoteSnapshot(
                security_key=security.key,
                name=security.name,
                last=last,
                change=change,
                change_pct=change_pct,
                open=_ibkr_float(row.get("7295")),
                high=_ibkr_float(row.get("70")),
                low=_ibkr_float(row.get("71")),
                prev_close=previous,
                volume=_ibkr_float(row.get("87")),
                quote_time=quote_time,
                source=source,
                price_session="隔夜",
            )
        if not result:
            raise ProviderError("IBKR 隔夜行情尚无有效价格")
        return result

    def _resolve_conids(self, securities: list[Security]) -> None:
        missing = [item for item in securities if item.key not in self._conids]
        if not missing:
            return
        payload = self._read_json(
            "/trsrv/stocks", {"symbols": ",".join(item.code for item in missing)}
        )
        by_code = {item.code.upper(): item for item in missing}
        for code, descriptions in (payload or {}).items():
            security = by_code.get(str(code).upper())
            if not security:
                continue
            candidates: list[dict[str, Any]] = []
            for description in descriptions or []:
                if str(description.get("assetClass") or "").upper() != "STK":
                    continue
                candidates.extend(description.get("contracts") or [])
            us_candidates = [row for row in candidates if row.get("isUS") is True]
            selected = (us_candidates or candidates or [None])[0]
            if selected and selected.get("conid") is not None:
                self._conids[security.key] = int(selected["conid"])

    def _snapshot(self, conids: list[str]) -> list[dict[str, Any]]:
        payload = self._read_json(
            "/iserver/marketdata/snapshot",
            {"conids": ",".join(conids), "fields": self.fields},
        )
        return payload if isinstance(payload, list) else []

    def _read_json(self, path: str, params: dict[str, str] | None = None) -> Any:
        query = urllib.parse.urlencode(params or {})
        url = f"{self.base_url}{path}" + (f"?{query}" if query else "")
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "DataSheet/1.2", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self.timeout, context=_LOCAL_SSL_CONTEXT
            ) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise ProviderError(f"IBKR 本地网关连接失败：{exc}") from exc

    @staticmethod
    def _row_has_price(row: dict[str, Any]) -> bool:
        return any(_ibkr_float(row.get(field)) is not None for field in ("31", "7635", "84"))


def _ibkr_float(value: Any) -> float | None:
    """Parses IBKR values such as C123.45, 1.2K and +0.31%."""

    if value in (None, "", "-"):
        return None
    text = str(value).strip().replace(",", "")
    match = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", text)
    if not match:
        return None
    try:
        number = float(match.group(0))
    except ValueError:
        return None
    suffix = text[match.end() :].lstrip().upper()[:1]
    factor = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}.get(suffix, 1)
    return number * factor


class NaverKoreaProvider:
    name = "Naver"
    stock_endpoint = "https://polling.finance.naver.com/api/realtime/domestic/stock/{}"
    index_endpoint = "https://polling.finance.naver.com/api/realtime/domestic/index/{}"
    minimum_poll_seconds = 6.5

    def __init__(self) -> None:
        self._cache: dict[str, QuoteSnapshot] = {}
        self._last_fetch = 0.0

    def fetch(self, securities: list[Security]) -> dict[str, QuoteSnapshot]:
        now = time.monotonic()
        missing = [item for item in securities if item.key not in self._cache]
        if not missing and now - self._last_fetch < self.minimum_poll_seconds:
            return {item.key: self._cache[item.key] for item in securities}

        result: dict[str, QuoteSnapshot] = {}
        stocks = [item for item in securities if item.kind != "index"]
        indexes = [item for item in securities if item.kind == "index"]
        for batch in _chunks(stocks, 50):
            codes = ",".join(item.code for item in batch)
            payload = self._read_json(self.stock_endpoint.format(codes))
            lookup = {item.code: item for item in batch}
            for row in payload.get("datas") or []:
                security = lookup.get(str(row.get("itemCode", "")))
                if security:
                    result[security.key] = self._parse_row(security, row)

        for security in indexes:
            payload = self._read_json(self.index_endpoint.format(security.code))
            rows = payload.get("datas") or []
            if rows:
                result[security.key] = self._parse_row(security, rows[0])

        if securities and not result:
            raise ProviderError("Naver 未返回有效韩股行情")
        self._cache.update(result)
        self._last_fetch = now
        return {item.key: self._cache[item.key] for item in securities if item.key in self._cache}

    def _read_json(self, url: str) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 DataSheet/1.1",
                "Referer": "https://m.stock.naver.com/",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=7, context=_SSL_CONTEXT) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise ProviderError(f"Naver 连接失败：{exc}") from exc

    def _parse_row(self, security: Security, row: dict[str, Any]) -> QuoteSnapshot:
        last = _float(row.get("closePriceRaw") or row.get("closePrice"))
        change = _float(
            row.get("compareToPreviousClosePriceRaw") or row.get("compareToPreviousClosePrice")
        )
        previous = last - change if last is not None and change is not None else None
        quote_time = None
        if row.get("localTradedAt"):
            try:
                quote_time = datetime.fromisoformat(str(row["localTradedAt"]))
            except ValueError:
                pass
        return QuoteSnapshot(
            security_key=security.key,
            name=str(row.get("stockName") or security.name or security.code),
            last=last,
            change=change,
            change_pct=_float(row.get("fluctuationsRatioRaw") or row.get("fluctuationsRatio")),
            open=_float(row.get("openPriceRaw") or row.get("openPrice")),
            high=_float(row.get("highPriceRaw") or row.get("highPrice")),
            low=_float(row.get("lowPriceRaw") or row.get("lowPrice")),
            prev_close=previous,
            volume=_float(
                row.get("accumulatedTradingVolumeRaw") or row.get("accumulatedTradingVolume")
            ),
            amount=_float(
                row.get("accumulatedTradingValueRaw") or row.get("accumulatedTradingValue")
            ),
            quote_time=quote_time,
            source=self.name,
        )


class YahooKoreaProvider:
    name = "Yahoo"
    endpoint = "https://query1.finance.yahoo.com/v8/finance/chart/{}?interval=1m&range=1d"

    def fetch(self, securities: list[Security]) -> dict[str, QuoteSnapshot]:
        result: dict[str, QuoteSnapshot] = {}
        for security in securities:
            for symbol in self._symbols(security):
                snapshot = self._fetch_symbol(security, symbol)
                if snapshot:
                    result[security.key] = snapshot
                    break
        if securities and not result:
            raise ProviderError("Yahoo 未返回有效韩股行情")
        return result

    def _fetch_symbol(self, security: Security, symbol: str) -> QuoteSnapshot | None:
        url = self.endpoint.format(urllib.parse.quote(symbol, safe=""))
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 DataSheet/1.1", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=7, context=_SSL_CONTEXT) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception:
            return None
        chart = payload.get("chart") or {}
        rows = chart.get("result") or []
        if not rows:
            return None
        row = rows[0]
        meta = row.get("meta") or {}
        last = _float(meta.get("regularMarketPrice"))
        previous = _float(meta.get("previousClose") or meta.get("chartPreviousClose"))
        if last is None:
            return None
        change = last - previous if previous is not None else None
        change_pct = change / previous * 100 if change is not None and previous else None
        quote = ((row.get("indicators") or {}).get("quote") or [{}])[0]
        open_price = _float(meta.get("regularMarketOpen")) or _first_number(quote.get("open"))
        timestamp = _float(meta.get("regularMarketTime"))
        return QuoteSnapshot(
            security_key=security.key,
            name=str(meta.get("shortName") or meta.get("longName") or security.name or security.code),
            last=last,
            change=change,
            change_pct=change_pct,
            open=open_price,
            high=_float(meta.get("regularMarketDayHigh")),
            low=_float(meta.get("regularMarketDayLow")),
            prev_close=previous,
            volume=_float(meta.get("regularMarketVolume")),
            amount=None,
            quote_time=datetime.fromtimestamp(timestamp, timezone.utc) if timestamp else None,
            source=self.name,
        )

    @staticmethod
    def _symbols(security: Security) -> list[str]:
        fixed = {"IDX.KR.KOSPI": ["^KS11"], "IDX.KR.KOSDAQ": ["^KQ11"]}
        if security.key in fixed:
            return fixed[security.key]
        return [f"{security.code}.KS", f"{security.code}.KQ"]


def _first_number(values: Any) -> float | None:
    if not isinstance(values, list):
        return None
    for value in values:
        number = _float(value)
        if number is not None:
            return number
    return None


class FailoverQuoteService:
    """Stateful primary/backup provider with five-minute primary recovery."""

    def __init__(self, primary, backup) -> None:
        self.primary = primary
        self.backup = backup
        self._lock = threading.Lock()
        self._primary_failures = 0
        self._backup_mode_until = 0.0

    def fetch(self, securities: list[Security]) -> FetchResult:
        with self._lock:
            now = time.monotonic()
            if now < self._backup_mode_until:
                snapshots = self.backup.fetch(securities)
                return FetchResult(snapshots, self.backup.name)

            try:
                primary_result = self.primary.fetch(securities)
                self._primary_failures = 0
                self._backup_mode_until = 0.0
            except ProviderError as primary_error:
                self._primary_failures += 1
                if self._primary_failures >= 2:
                    self._backup_mode_until = now + 300
                try:
                    backup_result = self.backup.fetch(securities)
                    return FetchResult(backup_result, self.backup.name)
                except ProviderError as backup_error:
                    raise ProviderError(f"双行情源均不可用；{primary_error}；{backup_error}") from backup_error

            missing = [item for item in securities if item.key not in primary_result]
            if not missing:
                return FetchResult(primary_result, self.primary.name)
            try:
                secondary = self.backup.fetch(missing)
                primary_result.update(secondary)
                source = f"{self.primary.name}+{self.backup.name}"
            except ProviderError:
                source = f"{self.primary.name}（部分）"
            return FetchResult(primary_result, source)


class QuoteService:
    """Routes regions independently and overlays US extended-hours quotes."""

    def __init__(
        self, primary=None, backup=None, us_extended=None, us_overnight=None
    ) -> None:
        # Optional arguments preserve the small injectable surface used by tests.
        self._single = FailoverQuoteService(primary, backup) if primary and backup else None
        self._global = FailoverQuoteService(EastmoneyProvider(), TencentProvider())
        self._korea = FailoverQuoteService(NaverKoreaProvider(), YahooKoreaProvider())
        self._us_extended = us_extended or YahooUSExtendedProvider()
        self._us_overnight = us_overnight or IBKROvernightProvider()

    def fetch(self, securities: list[Security]) -> FetchResult:
        if self._single:
            return self._single.fetch(securities)

        groups = (
            (("CN", "US"), self._global, [item for item in securities if item.region in {"CN", "US"}]),
            (("KR",), self._korea, [item for item in securities if item.region == "KR"]),
        )
        snapshots: dict[str, QuoteSnapshot] = {}
        sources: list[str] = []
        failed_regions: list[str] = []
        errors: list[str] = []
        for regions, service, items in groups:
            if not items:
                continue
            try:
                result = service.fetch(items)
                snapshots.update(result.snapshots)
                sources.append(result.source)
            except ProviderError as exc:
                failed_regions.extend(regions)
                errors.append(str(exc))
        us_equities = [
            item for item in securities if item.region == "US" and item.kind != "index"
        ]
        us_state = session_state("US")
        if us_equities and us_state in {"隔夜", "隔夜收盘"}:
            try:
                overnight = self._us_overnight.fetch(us_equities)
                applied = False
                for security in us_equities:
                    supplemental = overnight.get(security.key)
                    if not supplemental:
                        continue
                    snapshots[security.key] = _merge_extended(
                        snapshots.get(security.key), supplemental
                    )
                    applied = True
                sources.append("IBKR隔夜" if applied else "IBKR隔夜待数据")
            except ProviderError as exc:
                # Regular-session prices remain visible, but the row status and
                # source make clear that there is no live overnight connection.
                sources.append("IBKR隔夜未连接")
                errors.append(str(exc))
        elif us_equities and us_state != "交易中":
            try:
                extended = self._us_extended.fetch(us_equities)
                current_us_date = market_now("US").date()
                applied_sessions: list[str] = []
                for security in us_equities:
                    supplemental = extended.get(security.key)
                    if not supplemental or not supplemental.quote_time:
                        continue
                    if us_state in {"盘前", "盘后"}:
                        quote_date = supplemental.quote_time.astimezone(US_TZ).date()
                        if supplemental.price_session != us_state or quote_date != current_us_date:
                            continue
                    snapshots[security.key] = _merge_extended(
                        snapshots.get(security.key), supplemental
                    )
                    applied_sessions.append(supplemental.price_session)
                for price_session in dict.fromkeys(applied_sessions):
                    sources.append(f"Yahoo{price_session}")
            except ProviderError as exc:
                if us_state in {"盘前", "盘后"}:
                    failed_regions.append("US")
                    errors.append(str(exc))
        if not snapshots:
            raise ProviderError("；".join(errors) or "没有可查询的证券")
        source = "｜".join(dict.fromkeys(sources))
        if failed_regions:
            source += "｜部分市场离线"
        return FetchResult(snapshots, source, tuple(dict.fromkeys(failed_regions)))


def _merge_extended(
    base: QuoteSnapshot | None, supplemental: QuoteSnapshot
) -> QuoteSnapshot:
    if base is None:
        return supplemental
    use_overnight_fields = supplemental.price_session == "隔夜"
    return QuoteSnapshot(
        security_key=base.security_key,
        name=supplemental.name or base.name,
        last=supplemental.last,
        change=supplemental.change,
        change_pct=supplemental.change_pct,
        open=supplemental.open if use_overnight_fields and supplemental.open is not None else base.open,
        high=supplemental.high if use_overnight_fields and supplemental.high is not None else base.high,
        low=supplemental.low if use_overnight_fields and supplemental.low is not None else base.low,
        prev_close=base.prev_close or supplemental.prev_close,
        volume=supplemental.volume if use_overnight_fields and supplemental.volume is not None else base.volume,
        amount=base.amount,
        quote_time=supplemental.quote_time,
        source=f"{base.source}+{supplemental.source}" if base.source else supplemental.source,
        price_session=supplemental.price_session,
    )
