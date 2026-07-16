import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from datasheet.domain import QuoteSnapshot
from datasheet.storage import Storage
from datasheet.ui import MainWindow


class UiSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_window_and_compact_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            window = MainWindow(Storage(Path(directory)), auto_refresh=False)
            self.assertEqual(window.model.rowCount(), 8)
            window._set_compact(True, save=False)
            self.assertTrue(window.table.isColumnHidden(0))
            self.assertFalse(window.table.isColumnHidden(2))
            window._exiting = True
            window.close()

    def test_quote_cells_do_not_use_rise_or_fall_colors(self):
        with tempfile.TemporaryDirectory() as directory:
            window = MainWindow(Storage(Path(directory)), auto_refresh=False)
            security = window.model.securities[0]
            window.model.apply_snapshots(
                {
                    security.key: QuoteSnapshot(
                        security.key,
                        name=security.name,
                        last=100.0,
                        change=1.0,
                        change_pct=1.0,
                    )
                }
            )
            price_cell = window.model.index(0, 3)
            self.assertIsNone(window.model.data(price_cell, Qt.ForegroundRole))
            self.assertIsNone(window.model.data(price_cell, Qt.BackgroundRole))
            window._exiting = True
            window.close()


if __name__ == "__main__":
    unittest.main()
