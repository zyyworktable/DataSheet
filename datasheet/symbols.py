from __future__ import annotations

import re

from .domain import Security


class SymbolError(ValueError):
    pass


_CN_SUFFIX = re.compile(r"^(?P<code>\d{6})\.(?P<exchange>SH|SS|SZ|BJ)$", re.I)
_CN_PREFIX = re.compile(r"^(?P<exchange>SH|SZ|BJ)(?P<code>\d{6})$", re.I)
_KR_SUFFIX = re.compile(r"^(?P<code>\d{6})\.(?P<exchange>KR|KS|KQ)$", re.I)
_KR_PREFIX = re.compile(r"^(?:KR:|KR)(?P<code>\d{6})$", re.I)
_US_SYMBOL = re.compile(r"^[A-Z][A-Z0-9.-]{0,11}$")


def parse_security(text: str) -> Security:
    raw = "".join(text.strip().upper().split())
    if not raw:
        raise SymbolError("请输入股票代码")

    korea = _KR_SUFFIX.fullmatch(raw) or _KR_PREFIX.fullmatch(raw)
    if korea:
        return Security(f"KR.{korea.group('code')}", "KR", "KR", korea.group("code"))

    suffix = _CN_SUFFIX.fullmatch(raw)
    if suffix:
        exchange = suffix.group("exchange").upper().replace("SS", "SH")
        return _cn_security(suffix.group("code"), exchange)

    prefix = _CN_PREFIX.fullmatch(raw)
    if prefix:
        return _cn_security(prefix.group("code"), prefix.group("exchange").upper())

    if raw.isdigit():
        if len(raw) != 6:
            raise SymbolError("A 股代码应为 6 位数字")
        return _cn_security(raw, infer_cn_exchange(raw))

    raw = raw.removeprefix("US:").removeprefix("US") if raw.startswith("US:") else raw
    if _US_SYMBOL.fullmatch(raw):
        return Security(f"US.{raw}", "US", "US", raw)

    raise SymbolError("无法识别该代码，请输入 600519、AAPL 或 005930.KR")


def infer_cn_exchange(code: str) -> str:
    # The app targets A-shares and common exchange-traded funds. Explicit suffixes
    # remain available for uncommon instruments whose prefixes are ambiguous.
    if code.startswith(("4", "8", "92")):
        return "BJ"
    if code.startswith(("5", "6")):
        return "SH"
    return "SZ"


def _cn_security(code: str, exchange: str) -> Security:
    if exchange not in {"SH", "SZ", "BJ"}:
        raise SymbolError("不支持的 A 股交易所")
    return Security(f"CN.{exchange}.{code}", "CN", exchange, code)


def display_code(security: Security) -> str:
    if security.kind == "index":
        return security.code
    if security.region == "CN":
        return f"{security.code}.{security.exchange}"
    if security.region == "KR":
        return f"{security.code}.KR"
    return security.code
