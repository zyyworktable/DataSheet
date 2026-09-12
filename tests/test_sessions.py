import unittest
from datetime import datetime, timezone

from datasheet.domain import FIXED_SECURITIES
from datasheet.sessions import display_state, recommended_interval_ms, session_state
from datasheet.symbols import parse_security
from datasheet.domain import QuoteSnapshot


class SessionTests(unittest.TestCase):
    def test_china_open_and_lunch(self):
        self.assertEqual(session_state("CN", datetime(2026, 7, 15, 1, 30, tzinfo=timezone.utc)), "交易中")
        self.assertEqual(session_state("CN", datetime(2026, 7, 15, 4, 0, tzinfo=timezone.utc)), "午休")
        self.assertEqual(session_state("CN", datetime(2026, 7, 15, 6, 0, tzinfo=timezone.utc)), "交易中")

    def test_us_summer_and_winter_dst(self):
        self.assertEqual(session_state("US", datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)), "盘前")
        self.assertEqual(session_state("US", datetime(2026, 7, 15, 13, 30, tzinfo=timezone.utc)), "交易中")
        self.assertEqual(session_state("US", datetime(2026, 7, 15, 22, 0, tzinfo=timezone.utc)), "盘后")
        self.assertEqual(session_state("US", datetime(2026, 1, 15, 13, 0, tzinfo=timezone.utc)), "盘前")
        self.assertEqual(session_state("US", datetime(2026, 1, 15, 14, 30, tzinfo=timezone.utc)), "交易中")
        self.assertEqual(session_state("US", datetime(2026, 1, 15, 23, 0, tzinfo=timezone.utc)), "盘后")

    def test_us_extended_state_requires_matching_fresh_price(self):
        security = parse_security("AAPL")
        now = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
        regular = QuoteSnapshot(security.key, last=100, quote_time=now, price_session="常规")
        premarket = QuoteSnapshot(security.key, last=101, quote_time=now, price_session="盘前")
        self.assertEqual(display_state(security, regular, True, now), "盘前待更新")
        self.assertEqual(display_state(security, premarket, True, now), "盘前")

    def test_korea_regular_session(self):
        self.assertEqual(session_state("KR", datetime(2026, 7, 16, 0, 0, tzinfo=timezone.utc)), "交易中")
        self.assertEqual(session_state("KR", datetime(2026, 7, 16, 6, 31, tzinfo=timezone.utc)), "已收盘")

    def test_refresh_interval_tracks_any_open_market(self):
        self.assertEqual(
            recommended_interval_ms(list(FIXED_SECURITIES), 3, 30, datetime(2026, 7, 15, 1, 30, tzinfo=timezone.utc)),
            3000,
        )
        self.assertEqual(
            recommended_interval_ms(list(FIXED_SECURITIES), 3, 30, datetime(2026, 7, 18, 1, 30, tzinfo=timezone.utc)),
            30000,
        )
        self.assertEqual(
            recommended_interval_ms(
                [parse_security("AAPL")],
                3,
                30,
                datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc),
            ),
            3000,
        )
        self.assertEqual(
            recommended_interval_ms(
                [item for item in FIXED_SECURITIES if item.region == "US"],
                3,
                30,
                datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc),
            ),
            30000,
        )


if __name__ == "__main__":
    unittest.main()
