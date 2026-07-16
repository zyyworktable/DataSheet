from __future__ import annotations

import base64
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QAction, QColor, QCloseEvent, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSystemTrayIcon,
    QTabWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from .domain import FIXED_SECURITIES, FetchResult, QuoteSnapshot, Security
from .model import QuoteTableModel
from .providers import ProviderError, QuoteService
from .sessions import recommended_interval_ms
from .storage import Storage
from .symbols import SymbolError, display_code, parse_security


APP_STYLE = """
QMainWindow, QWidget { background: #ffffff; color: #202020; font-size: 13px; }
QPushButton { background: #f3f3f3; border: 1px solid #bdbdbd; border-radius: 4px; padding: 6px 12px; }
QPushButton:hover { background: #e8e8e8; }
QPushButton:pressed { background: #dddddd; }
QPushButton#primaryButton { background: #ececec; border-color: #909090; color: #111111; }
QLineEdit, QSpinBox, QListWidget { border: 1px solid #bdbdbd; border-radius: 3px; padding: 5px; background: #ffffff; }
QTableView { border: 1px solid #c8c8c8; gridline-color: #d4d4d4; alternate-background-color: #fafafa; selection-background-color: #dedede; selection-color: #111111; }
QHeaderView::section { background: #f1f1f1; border: 0; border-right: 1px solid #c8c8c8; border-bottom: 1px solid #bdbdbd; padding: 7px 5px; font-weight: 600; }
QTabWidget::pane { border: 1px solid #c8c8c8; border-top: 0; }
QTabBar::tab { background: #f1f1f1; border: 1px solid #c8c8c8; padding: 7px 18px; }
QTabBar::tab:selected { background: #ffffff; border-top: 2px solid #505050; }
QLabel#title { font-size: 16px; font-weight: 600; }
QLabel#muted { color: #606060; }
QFrame#toolbar { background: #f8f8f8; border-bottom: 1px solid #c8c8c8; }
"""


class WorkerSignals(QObject):
    succeeded = Signal(object)
    failed = Signal(str)


class FetchTask(QRunnable):
    def __init__(self, service: QuoteService, securities: list[Security]) -> None:
        super().__init__()
        self.service = service
        self.securities = securities
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = self.service.fetch(self.securities)
        except Exception as exc:
            try:
                self.signals.failed.emit(str(exc))
            except RuntimeError:
                # The application may have closed while a network request was finishing.
                pass
            return
        try:
            self.signals.succeeded.emit(result)
        except RuntimeError:
            pass


class MainWindow(QMainWindow):
    def __init__(
        self,
        storage: Storage,
        service: QuoteService | None = None,
        auto_refresh: bool = True,
    ) -> None:
        super().__init__()
        self.storage = storage
        self.service = service or QuoteService()
        self.settings = self.storage.settings()
        self.watchlist = self.storage.watchlist()
        self.snapshots = self.storage.cache()
        self._online = False
        self._source = "—"
        self._refresh_in_progress = False
        self._refresh_pending = False
        self._exiting = False
        self._last_cache_save = 0.0
        self._normal_geometry: bytes | None = None
        self.thread_pool = QThreadPool.globalInstance()

        self.setWindowTitle("数据工作台")
        self.setWindowIcon(create_app_icon())
        self.setStyleSheet(APP_STYLE)
        self._build_ui()
        self._build_tray()
        self._apply_saved_geometry()
        self._apply_always_on_top(bool(self.settings.get("always_on_top", False)), save=False)
        self._set_compact(bool(self.settings.get("compact", False)), save=False)

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.timeout.connect(self.refresh_quotes)
        self.state_timer = QTimer(self)
        self.state_timer.setInterval(30_000)
        self.state_timer.timeout.connect(self.model.refresh_states)
        self.state_timer.start()
        if auto_refresh:
            QTimer.singleShot(150, self.refresh_quotes)

    @property
    def securities(self) -> list[Security]:
        return [*FIXED_SECURITIES, *self.watchlist]

    def _build_ui(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        toolbar = QFrame(objectName="toolbar")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(14, 9, 12, 9)
        icon_label = QLabel()
        icon_label.setPixmap(create_app_icon().pixmap(24, 24))
        toolbar_layout.addWidget(icon_label)
        self.title_label = QLabel("数据工作台", objectName="title")
        toolbar_layout.addWidget(self.title_label)
        toolbar_layout.addStretch()
        self.mode_button = QPushButton("紧凑模式")
        self.mode_button.clicked.connect(self.toggle_compact)
        toolbar_layout.addWidget(self.mode_button)
        self.refresh_button = QPushButton("立即刷新")
        self.refresh_button.clicked.connect(self.refresh_quotes)
        toolbar_layout.addWidget(self.refresh_button)
        self.settings_button = QPushButton("设置")
        self.settings_button.clicked.connect(self.open_settings)
        toolbar_layout.addWidget(self.settings_button)
        layout.addWidget(toolbar)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_overview_tab(), "数据总览")
        self.tabs.addTab(self._build_watchlist_tab(), "自选管理")
        self.tabs.addTab(self._build_settings_tab(), "设置")
        layout.addWidget(self.tabs)
        self.setCentralWidget(central)

    def _build_overview_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 9, 10, 10)
        layout.setSpacing(7)

        self.status_row = QWidget()
        status_layout = QHBoxLayout(self.status_row)
        status_layout.setContentsMargins(2, 0, 2, 0)
        self.connection_label = QLabel("数据状态：正在连接")
        self.source_label = QLabel("来源：—")
        self.updated_label = QLabel("更新时间：—")
        status_layout.addWidget(self.connection_label)
        status_layout.addSpacing(18)
        status_layout.addWidget(self.source_label)
        status_layout.addStretch()
        status_layout.addWidget(self.updated_label)
        layout.addWidget(self.status_row)

        self.model = QuoteTableModel(self.securities, self.snapshots)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(True)
        self.table.setSortingEnabled(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setDefaultSectionSize(29)
        self.table.horizontalHeader().setMinimumSectionSize(58)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        layout.addWidget(self.table)

        footer = QLabel("公共行情源可能存在延迟，仅用于个人行情查看。", objectName="muted")
        layout.addWidget(footer)
        return page

    def _build_watchlist_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 15, 16, 16)
        title = QLabel("自选清单", objectName="title")
        layout.addWidget(title)
        hint = QLabel(
            "支持 600519、600519.SH、AAPL、005930.KR（韩股）或 KR:005930。",
            objectName="muted",
        )
        layout.addWidget(hint)

        add_row = QHBoxLayout()
        self.symbol_input = QLineEdit()
        self.symbol_input.setPlaceholderText("输入 A 股、美股或韩股代码")
        self.symbol_input.returnPressed.connect(self.add_symbol)
        add_row.addWidget(self.symbol_input)
        add_button = QPushButton("添加", objectName="primaryButton")
        add_button.clicked.connect(self.add_symbol)
        add_row.addWidget(add_button)
        layout.addLayout(add_row)
        self.symbol_message = QLabel("")
        layout.addWidget(self.symbol_message)

        self.watchlist_widget = QListWidget()
        self.watchlist_widget.setSelectionMode(QAbstractItemView.SingleSelection)
        layout.addWidget(self.watchlist_widget)
        button_row = QHBoxLayout()
        up_button = QPushButton("上移")
        down_button = QPushButton("下移")
        delete_button = QPushButton("删除")
        up_button.clicked.connect(lambda: self.move_watchlist(-1))
        down_button.clicked.connect(lambda: self.move_watchlist(1))
        delete_button.clicked.connect(self.remove_symbol)
        button_row.addWidget(up_button)
        button_row.addWidget(down_button)
        button_row.addStretch()
        button_row.addWidget(delete_button)
        layout.addLayout(button_row)
        self._rebuild_watchlist()
        return page

    def _build_settings_tab(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.addWidget(QLabel("显示与刷新", objectName="title"))
        form = QFormLayout()
        form.setHorizontalSpacing(22)
        form.setVerticalSpacing(14)

        self.refresh_spin = QSpinBox()
        self.refresh_spin.setRange(3, 60)
        self.refresh_spin.setSuffix(" 秒")
        self.refresh_spin.setValue(int(self.settings.get("refresh_seconds", 3)))
        self.refresh_spin.valueChanged.connect(self._settings_changed)
        form.addRow("交易时段刷新", self.refresh_spin)

        self.closed_refresh_spin = QSpinBox()
        self.closed_refresh_spin.setRange(10, 300)
        self.closed_refresh_spin.setSuffix(" 秒")
        self.closed_refresh_spin.setValue(int(self.settings.get("closed_refresh_seconds", 30)))
        self.closed_refresh_spin.valueChanged.connect(self._settings_changed)
        form.addRow("闭市刷新", self.closed_refresh_spin)

        self.topmost_check = QCheckBox("窗口保持在其他窗口上方")
        self.topmost_check.setChecked(bool(self.settings.get("always_on_top", False)))
        self.topmost_check.toggled.connect(self._topmost_toggled)
        form.addRow("窗口置顶", self.topmost_check)

        self.autostart_check = QCheckBox("登录系统后自动启动")
        self.autostart_check.setChecked(bool(self.settings.get("autostart", False)))
        self.autostart_check.toggled.connect(self._autostart_toggled)
        form.addRow("开机启动", self.autostart_check)
        outer.addLayout(form)
        outer.addSpacing(12)
        outer.addWidget(QLabel("行情源", objectName="title"))
        outer.addWidget(
            QLabel(
                "A股/美股：东方财富 → 腾讯　　韩股：Naver → Yahoo　　失败后自动切换",
                objectName="muted",
            )
        )
        outer.addStretch()
        disclaimer = QLabel(
            "本工具不提供交易功能。公共行情接口没有服务等级保证；如需商业使用或交易所级行情，请更换授权数据源。",
            objectName="muted",
        )
        disclaimer.setWordWrap(True)
        outer.addWidget(disclaimer)
        return page

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(create_app_icon(), self)
        self.tray.setToolTip("数据工作台")
        menu = QMenu()
        show_action = QAction("显示/隐藏", self)
        show_action.triggered.connect(self.toggle_visibility)
        mode_action = QAction("切换完整/紧凑模式", self)
        mode_action.triggered.connect(self.toggle_compact)
        refresh_action = QAction("立即刷新", self)
        refresh_action.triggered.connect(self.refresh_quotes)
        exit_action = QAction("退出", self)
        exit_action.triggered.connect(self.exit_application)
        menu.addAction(show_action)
        menu.addAction(mode_action)
        menu.addAction(refresh_action)
        menu.addSeparator()
        menu.addAction(exit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()

    def _apply_saved_geometry(self) -> None:
        geometry = self.settings.get("normal_geometry")
        if geometry:
            try:
                decoded = base64.b64decode(geometry)
                self.restoreGeometry(decoded)
                self._normal_geometry = decoded
                return
            except (ValueError, TypeError):
                pass
        self.resize(960, 600)

    @Slot()
    def refresh_quotes(self) -> None:
        if self._refresh_in_progress:
            self._refresh_pending = True
            return
        self.refresh_timer.stop()
        self._refresh_in_progress = True
        self.refresh_button.setEnabled(False)
        task = FetchTask(self.service, self.securities)
        task.signals.succeeded.connect(self._refresh_succeeded)
        task.signals.failed.connect(self._refresh_failed)
        self.thread_pool.start(task)

    @Slot(object)
    def _refresh_succeeded(self, result: FetchResult) -> None:
        self._refresh_in_progress = False
        self.refresh_button.setEnabled(True)
        self._online = True
        self._source = result.source
        self.snapshots.update(result.snapshots)
        self.model.apply_snapshots(
            result.snapshots,
            online=True,
            failed_regions=result.failed_regions,
        )
        if result.failed_regions:
            labels = {"CN": "A股", "US": "美股", "KR": "韩股"}
            failed = "、".join(labels.get(item, item) for item in result.failed_regions)
            self.connection_label.setText(f"数据状态：部分离线（{failed}）")
        else:
            self.connection_label.setText("数据状态：正常")
        self.connection_label.setStyleSheet("")
        self.source_label.setText(f"来源：{result.source}")
        self.updated_label.setText(f"更新时间：{datetime.now():%H:%M:%S}")
        self._update_watchlist_names()
        if time.monotonic() - self._last_cache_save >= 30:
            self.storage.save_cache(self.snapshots)
            self._last_cache_save = time.monotonic()
        self._schedule_next_refresh()

    @Slot(str)
    def _refresh_failed(self, message: str) -> None:
        self._refresh_in_progress = False
        self.refresh_button.setEnabled(True)
        self._online = False
        self.model.set_online(False)
        self.connection_label.setText("数据状态：离线 / 数据可能过期")
        self.connection_label.setStyleSheet("")
        self.updated_label.setText(f"最后尝试：{datetime.now():%H:%M:%S}")
        self.connection_label.setToolTip(message)
        self._schedule_next_refresh()

    def _schedule_next_refresh(self) -> None:
        if self._refresh_pending:
            self._refresh_pending = False
            QTimer.singleShot(0, self.refresh_quotes)
            return
        interval = recommended_interval_ms(
            self.securities,
            int(self.settings.get("refresh_seconds", 3)),
            int(self.settings.get("closed_refresh_seconds", 30)),
        )
        self.refresh_timer.start(interval)

    @Slot()
    def add_symbol(self) -> None:
        try:
            security = parse_security(self.symbol_input.text())
        except SymbolError as exc:
            self.symbol_message.setStyleSheet("")
            self.symbol_message.setText(str(exc))
            return
        if any(item.key == security.key for item in self.securities):
            self.symbol_message.setStyleSheet("")
            self.symbol_message.setText("该证券已经在清单中")
            return
        self.watchlist.append(security)
        self.storage.save_watchlist(self.watchlist)
        self.model.set_securities(self.securities)
        self._rebuild_watchlist(select=len(self.watchlist) - 1)
        self.symbol_input.clear()
        self.symbol_message.setStyleSheet("")
        self.symbol_message.setText("已添加，正在获取名称和行情")
        self.refresh_quotes()

    @Slot()
    def remove_symbol(self) -> None:
        row = self.watchlist_widget.currentRow()
        if not 0 <= row < len(self.watchlist):
            return
        self.watchlist.pop(row)
        self.storage.save_watchlist(self.watchlist)
        self.model.set_securities(self.securities)
        self._rebuild_watchlist(select=min(row, len(self.watchlist) - 1))

    def move_watchlist(self, direction: int) -> None:
        row = self.watchlist_widget.currentRow()
        target = row + direction
        if not (0 <= row < len(self.watchlist) and 0 <= target < len(self.watchlist)):
            return
        self.watchlist[row], self.watchlist[target] = self.watchlist[target], self.watchlist[row]
        self.storage.save_watchlist(self.watchlist)
        self.model.set_securities(self.securities)
        self._rebuild_watchlist(select=target)

    def _rebuild_watchlist(self, select: int = -1) -> None:
        self.watchlist_widget.clear()
        for security in self.watchlist:
            snapshot = self.snapshots.get(security.key)
            name = snapshot.name if snapshot and snapshot.name else security.name
            suffix = f"　{name}" if name else ""
            self.watchlist_widget.addItem(f"{display_code(security)}{suffix}")
        if 0 <= select < self.watchlist_widget.count():
            self.watchlist_widget.setCurrentRow(select)

    def _update_watchlist_names(self) -> None:
        selected = self.watchlist_widget.currentRow()
        changed = False
        for index, security in enumerate(self.watchlist):
            snapshot = self.snapshots.get(security.key)
            if snapshot and snapshot.name and snapshot.name != security.name:
                self.watchlist[index] = Security(
                    security.key,
                    security.region,
                    security.exchange,
                    security.code,
                    snapshot.name,
                    security.kind,
                    security.fixed,
                )
                changed = True
        if changed:
            self.storage.save_watchlist(self.watchlist)
            self.model.set_securities(self.securities)
            self._rebuild_watchlist(selected)

    @Slot()
    def toggle_compact(self) -> None:
        self._set_compact(not bool(self.settings.get("compact", False)), save=True)

    def _set_compact(self, compact: bool, save: bool) -> None:
        if compact:
            if not bool(self.settings.get("compact", False)) and self.isVisible():
                self._normal_geometry = bytes(self.saveGeometry())
            self.tabs.setCurrentIndex(0)
            self.tabs.tabBar().hide()
            self.status_row.hide()
            self.settings_button.hide()
            self.title_label.setText("数据表")
            self.mode_button.setText("完整模式")
            for column in range(self.model.columnCount()):
                self.table.setColumnHidden(column, column not in QuoteTableModel.COMPACT_COLUMNS)
            self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
            self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
            self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
            self.setMinimumSize(300, 360)
            self.resize(340, 500)
        else:
            self.setMinimumSize(760, 480)
            self.tabs.tabBar().show()
            self.status_row.show()
            self.settings_button.show()
            self.title_label.setText("数据工作台")
            self.mode_button.setText("紧凑模式")
            for column in range(self.model.columnCount()):
                self.table.setColumnHidden(column, False)
                self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeToContents)
            self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Interactive)
            self.table.setColumnWidth(2, 130)
            self.table.setColumnWidth(13, 82)
            if self._normal_geometry:
                self.restoreGeometry(self._normal_geometry)
            elif self.width() < 760:
                self.resize(960, 600)
        self.settings["compact"] = compact
        if save:
            self._save_settings()

    @Slot()
    def open_settings(self) -> None:
        if bool(self.settings.get("compact", False)):
            self._set_compact(False, save=True)
        self.tabs.setCurrentIndex(2)

    @Slot()
    def _settings_changed(self) -> None:
        self.settings["refresh_seconds"] = self.refresh_spin.value()
        self.settings["closed_refresh_seconds"] = self.closed_refresh_spin.value()
        self._save_settings()
        if not self._refresh_in_progress:
            self._schedule_next_refresh()

    @Slot(bool)
    def _topmost_toggled(self, enabled: bool) -> None:
        self._apply_always_on_top(enabled, save=True)

    def _apply_always_on_top(self, enabled: bool, save: bool) -> None:
        geometry = self.saveGeometry()
        self.setWindowFlag(Qt.WindowStaysOnTopHint, enabled)
        self.restoreGeometry(geometry)
        if self.isVisible():
            self.show()
        self.settings["always_on_top"] = enabled
        if save:
            self._save_settings()

    @Slot(bool)
    def _autostart_toggled(self, enabled: bool) -> None:
        try:
            set_autostart(enabled)
        except OSError as exc:
            self.autostart_check.blockSignals(True)
            self.autostart_check.setChecked(not enabled)
            self.autostart_check.blockSignals(False)
            QMessageBox.warning(self, "无法修改开机启动", str(exc))
            return
        self.settings["autostart"] = enabled
        self._save_settings()

    def _save_settings(self) -> None:
        if not bool(self.settings.get("compact", False)):
            self._normal_geometry = bytes(self.saveGeometry())
        if self._normal_geometry:
            self.settings["normal_geometry"] = base64.b64encode(self._normal_geometry).decode("ascii")
        self.storage.save_settings(self.settings)

    def toggle_visibility(self) -> None:
        if self.isVisible() and not self.isMinimized():
            self.hide()
        else:
            self.showNormal()
            self.raise_()
            self.activateWindow()

    @Slot(QSystemTrayIcon.ActivationReason)
    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in {QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick}:
            self.toggle_visibility()

    @Slot()
    def exit_application(self) -> None:
        self._exiting = True
        self._save_settings()
        self.storage.save_cache(self.snapshots)
        self.tray.hide()
        QApplication.quit()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._exiting or not QSystemTrayIcon.isSystemTrayAvailable():
            self.exit_application()
            event.accept()
            return
        self._save_settings()
        self.hide()
        event.ignore()


def create_app_icon() -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor("#555555"))
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(5, 5, 54, 54, 8, 8)
    painter.setPen(QPen(QColor("#ffffff"), 3))
    for position in (22, 39):
        painter.drawLine(position, 12, position, 52)
        painter.drawLine(12, position, 52, position)
    painter.end()
    return QIcon(pixmap)


def set_autostart(enabled: bool) -> None:
    if sys.platform == "darwin":
        import plistlib

        launch_agents = Path.home() / "Library" / "LaunchAgents"
        plist_path = launch_agents / "com.datasheet.marketmonitor.plist"
        if enabled:
            if getattr(sys, "frozen", False):
                arguments = [sys.executable]
            else:
                project_root = Path(__file__).resolve().parents[1]
                arguments = [sys.executable, str(project_root / "run_datasheet.py")]
            launch_agents.mkdir(parents=True, exist_ok=True)
            temporary = plist_path.with_suffix(".tmp")
            temporary.write_bytes(
                plistlib.dumps(
                    {
                        "Label": "com.datasheet.marketmonitor",
                        "ProgramArguments": arguments,
                        "RunAtLoad": True,
                    }
                )
            )
            os.replace(temporary, plist_path)
        else:
            plist_path.unlink(missing_ok=True)
        return
    if os.name != "nt":
        raise OSError("开机启动目前仅支持 Windows 和 macOS")
    import winreg

    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            if getattr(sys, "frozen", False):
                command = f'"{sys.executable}"'
            else:
                project_root = Path(__file__).resolve().parents[1]
                command = f'"{sys.executable}" "{project_root / "run_datasheet.py"}"'
            winreg.SetValueEx(key, "DataSheet", 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, "DataSheet")
            except FileNotFoundError:
                pass
