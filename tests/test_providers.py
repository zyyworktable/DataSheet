import json
import unittest
from unittest.mock import patch

from datasheet.domain import QuoteSnapshot
from datasheet.providers import (
    EastmoneyProvider,
    NaverKoreaProvider,
    ProviderError,
    QuoteService,
    TencentProvider,
    YahooKoreaProvider,
)
from datasheet.symbols import parse_security


class FakeResponse:
    def __init__(self, data: bytes):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.data


class ProviderParserTests(unittest.TestCase):
    def test_eastmoney_json_parser(self):
        payload = {
            "data": {
                "diff": [
                    {
                        "f2": 1450.0,
                        "f3": 1.2,
                        "f4": 17.19,
                        "f5": 1000,
                        "f6": 1_450_000,
                        "f12": "600519",
                        "f13": 1,
                        "f14": "贵州茅台",
                        "f15": 1460,
                        "f16": 1420,
                        "f17": 1430,
                        "f18": 1432.81,
                        "f124": 1_752_562_400,
                    }
                ]
            }
        }
        response = FakeResponse(json.dumps(payload).encode("utf-8"))
        with patch("urllib.request.urlopen", return_value=response):
            result = EastmoneyProvider().fetch([parse_security("600519")])
        self.assertEqual(result["CN.SH.600519"].name, "贵州茅台")
        self.assertEqual(result["CN.SH.600519"].change_pct, 1.2)

    def test_tencent_gbk_parser(self):
        parts = [""] * 39
        parts[0] = "1"
        parts[1] = "贵州茅台"
        parts[2] = "600519"
        parts[3] = "1450.00"
        parts[4] = "1432.81"
        parts[5] = "1430.00"
        parts[30] = "20260715143000"
        parts[31] = "17.19"
        parts[32] = "1.20"
        parts[33] = "1460.00"
        parts[34] = "1420.00"
        parts[36] = "1000"
        parts[37] = "145"
        body = f'v_sh600519="{"~".join(parts)}";\n'.encode("gbk")
        with patch("urllib.request.urlopen", return_value=FakeResponse(body)):
            result = TencentProvider().fetch([parse_security("600519")])
        snapshot = result["CN.SH.600519"]
        self.assertEqual(snapshot.last, 1450.0)
        self.assertEqual(snapshot.amount, 1_450_000)

    def test_naver_korean_stock_parser(self):
        payload = {
            "datas": [
                {
                    "itemCode": "005930",
                    "stockName": "삼성전자",
                    "closePriceRaw": "255500",
                    "compareToPreviousClosePriceRaw": "-24000",
                    "fluctuationsRatioRaw": "-8.59",
                    "openPriceRaw": "264500",
                    "highPriceRaw": "265500",
                    "lowPriceRaw": "255000",
                    "accumulatedTradingVolumeRaw": "7538150",
                    "accumulatedTradingValueRaw": "1960512000000",
                    "localTradedAt": "2026-07-16T10:12:42+09:00",
                }
            ]
        }
        response = FakeResponse(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        with patch("urllib.request.urlopen", return_value=response):
            result = NaverKoreaProvider().fetch([parse_security("005930.KR")])
        snapshot = result["KR.005930"]
        self.assertEqual(snapshot.name, "삼성전자")
        self.assertEqual(snapshot.last, 255500)
        self.assertEqual(snapshot.prev_close, 279500)
        self.assertEqual(snapshot.amount, 1_960_512_000_000)

    def test_yahoo_korean_stock_parser(self):
        payload = {
            "chart": {
                "result": [
                    {
                        "meta": {
                            "shortName": "SamsungElec",
                            "regularMarketPrice": 258000,
                            "previousClose": 279500,
                            "regularMarketDayHigh": 265500,
                            "regularMarketDayLow": 256000,
                            "regularMarketVolume": 6221096,
                            "regularMarketTime": 1784163162,
                        },
                        "indicators": {"quote": [{"open": [265500, 264000]}]},
                    }
                ]
            }
        }
        response = FakeResponse(json.dumps(payload).encode("utf-8"))
        with patch("urllib.request.urlopen", return_value=response):
            result = YahooKoreaProvider().fetch([parse_security("005930.KR")])
        snapshot = result["KR.005930"]
        self.assertEqual(snapshot.last, 258000)
        self.assertEqual(snapshot.open, 265500)
        self.assertAlmostEqual(snapshot.change_pct, -7.692307, places=5)


class StubProvider:
    def __init__(self, name, outcomes):
        self.name = name
        self.outcomes = list(outcomes)
        self.calls = 0

    def fetch(self, securities):
        self.calls += 1
        outcome = self.outcomes.pop(0) if self.outcomes else self.outcomes
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FailoverTests(unittest.TestCase):
    def test_switches_after_two_primary_failures(self):
        security = parse_security("AAPL")
        snapshot = QuoteSnapshot(security.key, name="Apple", last=100)
        primary = StubProvider("主源", [ProviderError("down"), ProviderError("down")])
        backup = StubProvider("备源", [{security.key: snapshot}] * 3)
        service = QuoteService(primary, backup)

        self.assertEqual(service.fetch([security]).source, "备源")
        self.assertEqual(service.fetch([security]).source, "备源")
        self.assertEqual(service.fetch([security]).source, "备源")
        self.assertEqual(primary.calls, 2)
        self.assertEqual(backup.calls, 3)


if __name__ == "__main__":
    unittest.main()
