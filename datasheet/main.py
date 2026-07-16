from __future__ import annotations

import ctypes
import json
import multiprocessing
import sys
import tempfile
import traceback
from pathlib import Path

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from .storage import Storage
from .ui import MainWindow, create_app_icon


def live_smoke(output_path: Path) -> int:
    from .domain import FIXED_SECURITIES
    from .providers import QuoteService
    from .symbols import parse_security

    securities = [
        *FIXED_SECURITIES,
        parse_security("600519"),
        parse_security("AAPL"),
        parse_security("005930.KR"),
    ]
    result = QuoteService().fetch(securities)
    payload = {
        "source": result.source,
        "quotes": {
            item.key: {
                "name": result.snapshots[item.key].name,
                "last": result.snapshots[item.key].last,
            }
            for item in securities
            if item.key in result.snapshots
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if len(payload["quotes"]) == len(securities) else 2


def main() -> int:
    multiprocessing.freeze_support()
    if "--live-smoke" in sys.argv:
        index = sys.argv.index("--live-smoke")
        if index + 1 >= len(sys.argv):
            return 2
        output_path = Path(sys.argv[index + 1])
        try:
            return live_smoke(output_path)
        except Exception as exc:
            try:
                error_path = output_path.with_suffix(output_path.suffix + ".error.txt")
                error_path.parent.mkdir(parents=True, exist_ok=True)
                error_path.write_text(
                    f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}",
                    encoding="utf-8",
                )
            except OSError:
                pass
            return 1

    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("DataSheet.MarketMonitor.1")
        except (AttributeError, OSError):
            pass

    app = QApplication(sys.argv)
    app.setApplicationName("DataSheet")
    app.setApplicationDisplayName("数据工作台")
    app.setOrganizationName("DataSheet")
    app.setWindowIcon(create_app_icon())
    app.setStyle("Fusion")
    font_family = "PingFang SC" if sys.platform == "darwin" else "Microsoft YaHei UI"
    app.setFont(QFont(font_family, 9))
    app.setQuitOnLastWindowClosed(False)

    if "--smoke-test" in sys.argv:
        with tempfile.TemporaryDirectory() as directory:
            window = MainWindow(Storage(Path(directory)), auto_refresh=False)
            window._exiting = True
            window.close()
        return 0

    window = MainWindow(Storage())
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
