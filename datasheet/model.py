from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QFont

from .domain import QuoteSnapshot, Security
from .sessions import CHINA_TZ, KOREA_TZ, US_TZ, display_state
from .symbols import display_code


class QuoteTableModel(QAbstractTableModel):
    HEADERS = (
        "市场",
        "代码",
        "名称",
        "最新价",
        "涨跌额",
        "涨跌幅",
        "今开",
        "最高",
        "最低",
        "昨收",
        "成交量",
        "成交额",
        "行情时间",
        "状态",
    )
    COMPACT_COLUMNS = {2, 3, 5}

    def __init__(
        self,
        securities: list[Security] | None = None,
        snapshots: dict[str, QuoteSnapshot] | None = None,
    ) -> None:
        super().__init__()
        self.securities = securities or []
        self.snapshots = snapshots or {}
        self.online = False
        self.failed_regions: set[str] = set()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.securities)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return self.HEADERS[section]
        return section + 1

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        security = self.securities[index.row()]
        snapshot = self.snapshots.get(security.key)
        column = index.column()

        if role == Qt.DisplayRole:
            return self._display_value(security, snapshot, column)
        if role == Qt.TextAlignmentRole:
            if column in {0, 1, 2, 12, 13}:
                return Qt.AlignVCenter | (Qt.AlignLeft if column == 2 else Qt.AlignCenter)
            return Qt.AlignVCenter | Qt.AlignRight
        if role == Qt.FontRole and security.fixed:
            font = QFont()
            font.setWeight(QFont.DemiBold)
            return font
        if role == Qt.ToolTipRole:
            source = snapshot.source if snapshot else "尚无数据"
            price_session = snapshot.price_session if snapshot else "—"
            return f"{security.name or security.code}\n行情来源：{source}\n价格阶段：{price_session}"
        return None

    def _display_value(
        self, security: Security, snapshot: QuoteSnapshot | None, column: int
    ) -> str:
        values = {
            0: "指数" if security.kind == "index" else {"CN": "A股", "US": "美股", "KR": "韩股"}.get(security.region, security.region),
            1: display_code(security),
            2: (snapshot.name if snapshot and snapshot.name else security.name) or security.code,
            3: _price(snapshot.last if snapshot else None),
            4: _signed(snapshot.change if snapshot else None),
            5: _percent(snapshot.change_pct if snapshot else None),
            6: _price(snapshot.open if snapshot else None),
            7: _price(snapshot.high if snapshot else None),
            8: _price(snapshot.low if snapshot else None),
            9: _price(snapshot.prev_close if snapshot else None),
            10: _large_number(snapshot.volume if snapshot else None),
            11: _large_number(
                snapshot.amount if snapshot else None,
                currency_symbol={"CN": "¥", "US": "$", "KR": "₩"}.get(security.region, ""),
            ),
            12: _quote_time(snapshot.quote_time if snapshot else None, security.region),
            13: display_state(
                security,
                snapshot,
                self.online and security.region not in self.failed_regions,
            ),
        }
        return values[column]

    def set_securities(self, securities: list[Security]) -> None:
        self.beginResetModel()
        self.securities = list(securities)
        self.endResetModel()

    def apply_snapshots(
        self,
        snapshots: dict[str, QuoteSnapshot],
        online: bool = True,
        failed_regions: tuple[str, ...] = (),
    ) -> None:
        self.snapshots.update(snapshots)
        self.online = online
        self.failed_regions = set(failed_regions)
        if self.securities:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self.securities) - 1, len(self.HEADERS) - 1),
            )

    def set_online(self, online: bool) -> None:
        if self.online == online:
            return
        self.online = online
        if not online:
            self.failed_regions.clear()
        if self.securities:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self.securities) - 1, len(self.HEADERS) - 1),
            )

    def refresh_states(self) -> None:
        if self.securities:
            self.dataChanged.emit(self.index(0, 13), self.index(len(self.securities) - 1, 13))


def _price(value: float | None) -> str:
    return "—" if value is None else f"{value:,.2f}"


def _signed(value: float | None) -> str:
    return "—" if value is None else f"{value:+,.2f}"


def _percent(value: float | None) -> str:
    return "—" if value is None else f"{value:+.2f}%"


def _large_number(value: float | None, currency_symbol: str = "") -> str:
    if value is None:
        return "—"
    absolute = abs(value)
    if absolute >= 100_000_000:
        text = f"{value / 100_000_000:.2f}亿"
    elif absolute >= 10_000:
        text = f"{value / 10_000:.2f}万"
    else:
        text = f"{value:,.0f}"
    return f"{currency_symbol}{text}" if currency_symbol else text


def _quote_time(value: datetime | None, region: str) -> str:
    if value is None:
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    zone = {"CN": CHINA_TZ, "US": US_TZ, "KR": KOREA_TZ}.get(region, timezone.utc)
    return value.astimezone(zone).strftime("%m-%d %H:%M:%S")
