import unittest
from datetime import datetime, timezone

from datasheet.domain import FIXED_SECURITIES
from datasheet.sessions import recommended_interval_ms, session_state


class SessionTests(unittest.TestCase):
    def test_china_open_and_lunch(self):
        self.assertEqual(session_state("CN", datetime(2026, 7, 15, 1, 30, tzinfo=timezone.utc)), "交易中")
        self.assertEqual(session_state("CN", datetime(2026, 7, 15, 4, 0, tzinfo=timezone.utc)), "午休")
        self.assertEqual(session_state("CN", datetime(2026, 7, 15, 6, 0, tzinfo=timezone.utc)), "交易中")

    def test_us_summer_and_winter_dst(self):
        self.assertEqual(session_state("US", datetime(2026, 7, 15, 13, 30, tzinfo=timezone.utc)), "交易中")
        self.assertEqual(session_state("US", datetime(2026, 1, 15, 14, 30, tzinfo=timezone.utc)), "交易中")

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


if __name__ == "__main__":
    unittest.main()
