import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from datasheet.domain import QuoteSnapshot
from datasheet.storage import Storage
from datasheet.symbols import parse_security


class StorageTests(unittest.TestCase):
    def test_round_trip_watchlist_settings_and_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = Storage(Path(directory))
            security = parse_security("AAPL")
            storage.save_watchlist([security])
            settings = storage.settings()
            settings["compact"] = True
            storage.save_settings(settings)
            snapshot = QuoteSnapshot(
                security.key,
                name="Apple",
                last=123.45,
                quote_time=datetime(2026, 7, 15, tzinfo=timezone.utc),
                price_session="盘前",
            )
            storage.save_cache({security.key: snapshot})

            reopened = Storage(Path(directory))
            self.assertEqual(reopened.watchlist()[0].key, "US.AAPL")
            self.assertTrue(reopened.settings()["compact"])
            self.assertEqual(reopened.cache()["US.AAPL"].last, 123.45)
            self.assertEqual(reopened.cache()["US.AAPL"].price_session, "盘前")


if __name__ == "__main__":
    unittest.main()
