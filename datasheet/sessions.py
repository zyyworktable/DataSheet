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
    current = local.time().replace(tzinfo=None)
    if region == "US":
        weekday = local.weekday()
        # IBKR's OVERNIGHT venue opens Sunday-Thursday at 20:00 ET and
        # closes the following weekday at 03:50 ET.  This has to be checked
        # before the generic weekend rule because Sunday evening is active.
        if weekday == 6:
            return "隔夜" if current >= time(20, 0) else "休市"
        if weekday == 5:
            return "休市"
        if current < time(3, 50):
            return "隔夜"
        if current < time(4, 0):
            return "隔夜收盘"
        if current < time(9, 30):
            return "盘前"
        if current <= time(16, 0):
            return "交易中"
        if current < time(20, 0):
            return "盘后"
        return "隔夜" if weekday < 4 else "已收盘"

    if local.weekday() >= 5:
        return "休市"

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

    return "休市"


def is_market_open(region: str, now_utc: datetime | None = None) -> bool:
    return session_state(region, now_utc) in {"隔夜", "盘前", "交易中", "盘后"}


def is_security_active(security: Security, now_utc: datetime | None = None) -> bool:
    state = session_state(security.region, now_utc)
    if security.region == "US" and security.kind != "index":
        return state in {"隔夜", "盘前", "交易中", "盘后"}
    return state == "交易中"


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
    if security.region == "US" and security.kind == "index":
        state = {
            "隔夜": "已收盘",
            "隔夜收盘": "已收盘",
            "盘前": "未开盘",
            "盘后": "已收盘",
        }.get(state, state)
    active_states = {"交易中"}
    if security.region == "US" and security.kind != "index":
        active_states.update({"隔夜", "盘前", "盘后"})
        if state == "隔夜" and snapshot.price_session != "隔夜":
            return "隔夜待连接"
        if state == "隔夜收盘":
            return "隔夜收盘" if snapshot.price_session == "隔夜" else "隔夜待连接"
        if state in {"盘前", "盘后"} and snapshot.price_session != state:
            return f"{state}待更新"
    if state in active_states and snapshot.quote_time:
        # The overnight session crosses midnight, so comparing calendar dates
        # would incorrectly mark a valid pre-midnight trade as stale.
        if security.region == "US" and state == "隔夜":
            return state
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
    if any(is_security_active(item, now_utc) for item in securities):
        return max(1, open_seconds) * 1000
    return max(5, closed_seconds) * 1000
