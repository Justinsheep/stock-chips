import unittest

from chips import exits


def series(closes, inst=None, code="A"):
    """依收盤價產生 {日期: {代號: [開盤, 收盤, 法人]}};開盤 = 前一天收盤。"""
    cal = [f"d{i:02d}" for i in range(len(closes))]
    prices = {}
    for i, c in enumerate(closes):
        o = closes[i - 1] if i else c
        prices[cal[i]] = {code: [o, c, (inst or [1] * len(closes))[i]]}
    return cal, prices


class SimulateTest(unittest.TestCase):
    def test_fixed_hold_exits_at_close(self):
        cal, px = series([10, 10, 11, 12, 13, 14, 15])
        t = exits.simulate("A", 0, cal, px, {"max_hold": 3})
        self.assertEqual((t["entryDate"], t["exitDate"], t["exit"], t["held"]), ("d01", "d03", 12, 3))
        self.assertEqual(t["reasons"], ["持有滿 3 日"])

    def test_stop_loss_exits_next_open(self):
        cal, px = series([10, 10, 9.5, 9.0, 8.5, 8.0])
        t = exits.simulate("A", 0, cal, px, {"stop": -7.0, "max_hold": 20})
        self.assertEqual(t["signalDate"], "d03")        # 9.0 / 10 = -10%
        self.assertEqual((t["exitDate"], t["exit"]), ("d04", 9.0))
        self.assertTrue(t["reasons"][0].startswith("停損"))

    def test_inst_sell_needs_consecutive_days(self):
        cal, px = series([10] * 8, inst=[1, 1, -1, 1, -1, -1, 1, 1])
        t = exits.simulate("A", 0, cal, px, {"inst_days": 2, "max_hold": 20})
        self.assertEqual(t["signalDate"], "d05")

    def test_signal_on_last_day_is_exiting(self):
        cal, px = series([10, 10, 9])
        t = exits.simulate("A", 0, cal, px, {"stop": -7.0})
        self.assertEqual(t["status"], "exiting")
        self.assertIsNone(t["exit"])

    def test_open_trade_marks_to_close(self):
        cal, px = series([10, 10, 11])
        t = exits.simulate("A", 0, cal, px, {"stop": -7.0})
        self.assertEqual(t["status"], "open")
        self.assertEqual(t["ret"], 10.0)

    def test_price_reset_skips_trade(self):
        cal, px = series([60, 62, 16.2, 17.8, 19.5])   # 減資後重新定價:第 2 天開盤 16.2,前一天收 62
        px["d02"]["A"][0] = 16.2
        self.assertTrue(exits.price_reset("A", cal, px, 1, 4))
        self.assertIsNone(exits.simulate("A", 0, cal, px, {"max_hold": 3}))
        cal, px = series([60, 62, 66, 60])              # 一般漲跌
        self.assertFalse(exits.price_reset("A", cal, px, 1, 3))

    def test_no_entry_day_yet(self):
        cal, px = series([10])
        self.assertIsNone(exits.simulate("A", 0, cal, px, {}))


if __name__ == "__main__":
    unittest.main()
