from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

if sys.platform != "win32":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from datasheet.domain import FIXED_SECURITIES, FetchResult, QuoteSnapshot
from datasheet.storage import Storage
from datasheet.ui import MainWindow


def main() -> int:
    output = Path(sys.argv[1] if len(sys.argv) > 1 else "preview")
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    font_family = "PingFang SC" if sys.platform == "darwin" else "Microsoft YaHei UI"
    app.setFont(QFont(font_family, 9))
    with tempfile.TemporaryDirectory() as directory:
        window = MainWindow(Storage(Path(directory)), auto_refresh=False)
        window.setAttribute(Qt.WA_DontShowOnScreen, True)
        snapshots = {}
        prices = [3955.58, 14779.40, 3804.70, 52508.27, 7543.59, 26107.01, 6834.69, 798.41]
        changes = [-0.29, -0.97, -1.21, 0.54, 0.18, 0.32, -6.17, -3.74]
        preview_names = {"IDX.KR.KOSPI": "코스피", "IDX.KR.KOSDAQ": "코스닥"}
        for security, price, change in zip(FIXED_SECURITIES, prices, changes):
            snapshots[security.key] = QuoteSnapshot(
                security.key,
                preview_names.get(security.key, security.name),
                last=price,
                change=price * change / 100,
                change_pct=change,
                open=price * 0.997,
                high=price * 1.006,
                low=price * 0.992,
                prev_close=price / (1 + change / 100),
                volume=576_209_492,
                amount=122_629_826_989,
                quote_time=datetime.now().astimezone(),
                source="预览数据",
            )
        window._refresh_succeeded(FetchResult(snapshots, "东方财富+腾讯"))
        window.show()
        app.processEvents()
        window.grab().save(str(output / "preview-full.png"))
        window._set_compact(True, save=False)
        app.processEvents()
        window.grab().save(str(output / "preview-compact.png"))
        window._exiting = True
        window.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
