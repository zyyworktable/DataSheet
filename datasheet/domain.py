from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class Security:
    key: str
    region: str
    exchange: str
    code: str
    name: str = ""
    kind: str = "stock"
    fixed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Security":
        return cls(
            key=str(value["key"]),
            region=str(value["region"]),
            exchange=str(value["exchange"]),
            code=str(value["code"]),
            name=str(value.get("name", "")),
            kind=str(value.get("kind", "stock")),
            fixed=bool(value.get("fixed", False)),
        )


@dataclass(slots=True)
class QuoteSnapshot:
    security_key: str
    name: str = ""
    last: float | None = None
    change: float | None = None
    change_pct: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    prev_close: float | None = None
    volume: float | None = None
    amount: float | None = None
    quote_time: datetime | None = None
    source: str = ""
    price_session: str = "常规"

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["quote_time"] = self.quote_time.isoformat() if self.quote_time else None
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "QuoteSnapshot":
        quote_time = value.get("quote_time")
        return cls(
            security_key=str(value["security_key"]),
            name=str(value.get("name", "")),
            last=_optional_float(value.get("last")),
            change=_optional_float(value.get("change")),
            change_pct=_optional_float(value.get("change_pct")),
            open=_optional_float(value.get("open")),
            high=_optional_float(value.get("high")),
            low=_optional_float(value.get("low")),
            prev_close=_optional_float(value.get("prev_close")),
            volume=_optional_float(value.get("volume")),
            amount=_optional_float(value.get("amount")),
            quote_time=datetime.fromisoformat(quote_time) if quote_time else None,
            source=str(value.get("source", "")),
            price_session=str(value.get("price_session", "常规")),
        )


@dataclass(slots=True)
class FetchResult:
    snapshots: dict[str, QuoteSnapshot]
    source: str
    failed_regions: tuple[str, ...] = ()


def _optional_float(value: Any) -> float | None:
    if value is None or value == "" or value == "-":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


FIXED_SECURITIES: tuple[Security, ...] = (
    Security("IDX.CN.SHCOMP", "CN", "SH", "000001", "上证指数", "index", True),
    Security("IDX.CN.SZCOMP", "CN", "SZ", "399001", "深证成指", "index", True),
    Security("IDX.CN.CHINEXT", "CN", "SZ", "399006", "创业板指", "index", True),
    Security("IDX.US.DJI", "US", "US", ".DJI", "道琼斯", "index", True),
    Security("IDX.US.SPX", "US", "US", ".INX", "标普 500", "index", True),
    Security("IDX.US.IXIC", "US", "US", ".IXIC", "纳斯达克综合", "index", True),
    Security("IDX.KR.KOSPI", "KR", "KR", "KOSPI", "KOSPI", "index", True),
    Security("IDX.KR.KOSDAQ", "KR", "KR", "KOSDAQ", "KOSDAQ", "index", True),
)
