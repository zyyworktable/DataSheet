from __future__ import annotations

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from .domain import QuoteSnapshot, Security


CHINA_TZ = ZoneInfo("Asia/Shanghai")
US_TZ = ZoneInfo("America/New_York")
KOREA_TZ = ZoneInfo("Asia/Seoul")


def market_now(region: str, now_utc: datetime | None = None) -> datetime:
    now_utc = now_utc or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    zones = {"CN": CHINA_TZ, "US": US_TZ, "KR": KOREA_TZ}
    return now_utc.astimezone(zones.get(region, timezone.utc))


def session_state(region: str, now_utc: datetime | None = None) -> str:
    local = market_now(region, now_utc)
    if local.weekday() >= 5:
        return "休市"

    current = local.time().replace(tzinfo=None)
    if region == "CN":
        if current < time(9, 30):
            return "未开盘"
        if current <= time(11, 30):
            return "交易中"
        if current < time(13, 0):
            return "午休"
        if current <= time(15, 0):
            return "交易中"
        return "已收盘"

    if region == "KR":
        if current < time(9, 0):
            return "未开盘"
        if current <= time(15, 30):
            return "交易中"
        return "已收盘"

    if current < time(9, 30):
        return "未开盘"
    if current <= time(16, 0):
        return "交易中"
    return "已收盘"


def is_market_open(region: str, now_utc: datetime | None = None) -> bool:
    return session_state(region, now_utc) == "交易中"


def display_state(
    security: Security,
    snapshot: QuoteSnapshot | None,
    online: bool,
    now_utc: datetime | None = None,
) -> str:
    if not online:
        return "离线"
    if snapshot is None:
        return "无数据"
    state = session_state(security.region, now_utc)
    if state == "交易中" and snapshot and snapshot.quote_time:
        zones = {"CN": CHINA_TZ, "US": US_TZ, "KR": KOREA_TZ}
        quote_local = snapshot.quote_time.astimezone(zones[security.region])
        if quote_local.date() < market_now(security.region, now_utc).date():
            return "未更新"
    return state


def recommended_interval_ms(
    securities: list[Security],
    open_seconds: int = 3,
    closed_seconds: int = 30,
    now_utc: datetime | None = None,
) -> int:
    if any(is_market_open(item.region, now_utc) for item in securities):
        return max(1, open_seconds) * 1000
    return max(5, closed_seconds) * 1000
