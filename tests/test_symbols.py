import unittest

from datasheet.symbols import SymbolError, infer_cn_exchange, parse_security


class SymbolTests(unittest.TestCase):
    def test_infers_mainland_exchanges(self):
        self.assertEqual(parse_security("600519").key, "CN.SH.600519")
        self.assertEqual(parse_security("000001").key, "CN.SZ.000001")
        self.assertEqual(parse_security("920000").key, "CN.BJ.920000")

    def test_accepts_suffix_and_prefix_forms(self):
        self.assertEqual(parse_security("600519.sh").key, "CN.SH.600519")
        self.assertEqual(parse_security("SZ000001").key, "CN.SZ.000001")
        self.assertEqual(parse_security("920000.BJ").key, "CN.BJ.920000")

    def test_accepts_us_tickers(self):
        self.assertEqual(parse_security("aapl").key, "US.AAPL")
        self.assertEqual(parse_security("BRK.B").key, "US.BRK.B")

    def test_accepts_korean_tickers_without_stealing_cn_codes(self):
        self.assertEqual(parse_security("005930.KR").key, "KR.005930")
        self.assertEqual(parse_security("005930.KS").key, "KR.005930")
        self.assertEqual(parse_security("KR:005930").key, "KR.005930")
        self.assertEqual(parse_security("005930").key, "CN.SZ.005930")

    def test_rejects_bad_symbols(self):
        for value in ("", "123", "AAPL!", "600519.HK"):
            with self.subTest(value=value), self.assertRaises(SymbolError):
                parse_security(value)


if __name__ == "__main__":
    unittest.main()
