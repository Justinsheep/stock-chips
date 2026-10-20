import unittest

from chips import levels


class LevelsTest(unittest.TestCase):
    def test_round_tick(self):
        self.assertEqual(levels.round_tick(48.37), 48.35)
        self.assertEqual(levels.round_tick(48.37, down=False), 48.4)
        self.assertEqual(levels.round_tick(523.4), 523.0)
        self.assertEqual(levels.round_tick(9.876), 9.87)

    def test_daytrade_both_hit_counts_as_stop(self):
        # 開 100、高 103、低 98:停利 2%、停損 1% 都碰到 → 保守算停損
        self.assertEqual(levels._dt_trade("long", [100, 101, 0, 103, 98], 1.0, 2, 1), -1)
        self.assertEqual(levels._dt_trade("long", [100, 101, 0, 103, 99.5], 1.0, 2, 1), 2)
        self.assertAlmostEqual(levels._dt_trade("long", [100, 101, 0, 101.5, 99.5], 1.0, 2, 1), 1.0)
        # 做空:跌到停利、漲到停損
        self.assertEqual(levels._dt_trade("short", [100, 99, 0, 100.5, 97.9], 1.0, 2, 1), 2)
        self.assertEqual(levels._dt_trade("short", [100, 99, 0, 101.2, 97.9], 1.0, 2, 1), -1)

    def test_swing_fill_rules(self):
        cal = ["d0", "d1", "d2", "d3", "d4", "d5"]
        prices = {d: {"A": [100, 100, 0, 101, 99]} for d in cal}
        prices["d1"]["A"] = [99.5, 100, 0, 101, 98.5]     # 隔天最低 98.5
        prices["d5"]["A"] = [100, 110, 0, 111, 99]        # 第 5 天收 110
        k = {"close": 100}
        ok, r = levels._swing_trade("A", 0, cal, prices, "收盤價 −1%", k)   # 掛 99,開 99.5 > 99,最低碰到 → 99 成交
        self.assertTrue(ok)
        self.assertAlmostEqual(r, (110 / 99 - 1) * 100)
        ok, r = levels._swing_trade("A", 0, cal, prices, "收盤價 −2%", k)   # 掛 98 沒碰到
        self.assertFalse(ok)
        ok, r = levels._swing_trade("A", 0, cal, prices, "隔天開盤買(基準)", k)
        self.assertAlmostEqual(r, (110 / 99.5 - 1) * 100)


if __name__ == "__main__":
    unittest.main()
