import datetime as dt
import unittest

from chips import daily, perf, score


def stock(code, market="上市", inst=0, foreign=0, trust=0, vol=2_000_000, close=50.0):
    return {"name": f"S{code}", "market": market, "close": close, "open": close, "diff": 1.0,
            "vol": vol, "foreign": foreign, "trust": trust, "dealer": 0.0, "inst": inst}


class ScoreTest(unittest.TestCase):
    def test_pct_rank_ties_share_rank(self):
        self.assertEqual(score.pct_rank([3, 1, 2, 2]), [1.0, 0.0, 0.5, 0.5])
        self.assertEqual(score.pct_rank([5]), [0.0])

    def test_streak_stops_at_first_non_buy(self):
        self.assertEqual(score.streak([5, 3, -1, 4]), 2)
        self.assertEqual(score.streak([0, 3]), 0)

    def test_big_score_clamps(self):
        self.assertEqual(score.big_score(1.5), 1.0)
        self.assertEqual(score.big_score(-2), 0.0)
        self.assertEqual(score.big_score(0), 0.5)
        self.assertEqual(score.big_score(None), 0.5)

    def test_build_rows_filters_liquidity_price_and_etf(self):
        day = {"1111": stock("1111"), "2222": stock("2222", vol=500_000),
               "3333": stock("3333", close=9.5), "0050": stock("0050")}
        rows = score.build_rows([day] * 5)
        self.assertEqual([r["code"] for r in rows], ["1111"])

    def test_score_market_requires_net_buy_and_ranks(self):
        day = {"1111": stock("1111", inst=500_000, foreign=400_000),
               "2222": stock("2222", inst=100_000, foreign=100_000),
               "3333": stock("3333", inst=-300_000)}
        rows = score.build_rows([day] * 5)
        picks = score.score_market(rows, {"1111": -200}, False, lambda c: (60.0, 1.0))
        self.assertEqual([p["code"] for p in picks], ["1111", "2222"])
        self.assertEqual(picks[0]["rank"], 1)
        self.assertIn("外資連買5日", picks[0]["tags"])
        self.assertIn("大戶增持", picks[0]["tags"])
        self.assertIn("融資大減", picks[0]["tags"])
        self.assertEqual(picks[0]["parts"]["big"], 25)

    def test_margin_missing_rescales_to_100(self):
        day = {"1111": stock("1111", inst=500_000, foreign=1, trust=1), "2222": stock("2222", inst=-1)}
        rows = score.build_rows([day] * 5)
        p = score.score_market(rows, {}, True, lambda c: (None, 1.0))[0]
        self.assertEqual(p["parts"]["margin"], 0)
        self.assertAlmostEqual(p["score"], 100, places=0)
        self.assertIsNone(p["marginChg"])

    def test_weak_signals(self):
        day = {"1111": stock("1111", foreign=-1_000_000), "2222": stock("2222")}
        rows = [{"instNet": -1}, {"instNet": -1}, {"instNet": 5}]
        w = score.weak_signals(rows, {"chgPct": -1.2}, day, "上市")
        self.assertTrue(w["weak"])
        w = score.weak_signals([{"instNet": 5}], {"chgPct": 0.3}, day, "上市")
        self.assertFalse(w["weak"])


class WeeksTest(unittest.TestCase):
    def test_pick_weeks_strict_skips_same_day(self):
        weeks = ["20261002", "20261008", "20261016"]
        d = dt.date(2026, 10, 16)
        self.assertEqual(daily.pick_weeks(weeks, d, False), ("20261016", "20261008"))
        self.assertEqual(daily.pick_weeks(weeks, d, True), ("20261008", "20261002"))
        self.assertEqual(daily.pick_weeks(weeks, dt.date(2026, 9, 1), False), (None, None))


class PerfTest(unittest.TestCase):
    def test_trade_return_uses_next_open(self):
        cal = ["d0", "d1", "d2"]
        prices = {"d0": {"A": [10, 10]}, "d1": {"A": [11, 12]}, "d2": {"A": [12, 13.2]}}
        self.assertAlmostEqual(perf.trade_return(prices, cal, 0, "A", 1), 12 / 11 - 1)
        self.assertAlmostEqual(perf.trade_return(prices, cal, 0, "A", 2), 13.2 / 11 - 1)
        self.assertIsNone(perf.trade_return(prices, cal, 0, "A", 5))
        self.assertIsNone(perf.trade_return(prices, cal, 0, "B", 1))


if __name__ == "__main__":
    unittest.main()
