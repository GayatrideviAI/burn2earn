import unittest

from predictor import engine


def bales(**over):
    reading = {"residue_type": "paddy", "moisture_look": "damp", "size_confidence": "high",
               "shape": "round", "count": 100, "count_low": 90, "count_high": 110,
               "length_cm": 75, "width_cm": 50}
    reading.update(over)
    return reading


class BaleTests(unittest.TestCase):
    def test_round_bales_match_hand_calculation(self):
        r = engine.estimate("bales", bales())
        # 75 cm x 50 cm round bale = 0.1473 m3; x 95 kg/m3 = 14.0 kg; x 100 = 1.40 t
        self.assertAlmostEqual(r["straw_tonnes"]["likely"], 1.40, delta=0.02)
        dry = 1.40 * 0.8
        self.assertAlmostEqual(r["cbg_tonnes"]["likely"], dry / (10 * 0.85), delta=0.005)
        self.assertAlmostEqual(r["pellet_tonnes"]["likely"], dry * 0.93 / 0.9, delta=0.01)

    def test_range_brackets_the_likely_value(self):
        r = engine.estimate("bales", bales())
        for key in ("straw_tonnes", "cbg_tonnes", "pellet_tonnes"):
            q = r[key]
            self.assertLess(q["low"], q["likely"])
            self.assertLess(q["likely"], q["high"])

    def test_lower_confidence_gives_a_wider_range(self):
        sure = engine.estimate("bales", bales(size_confidence="high"))["cbg_tonnes"]
        unsure = engine.estimate("bales", bales(size_confidence="low"))["cbg_tonnes"]
        self.assertGreater(unsure["high"] - unsure["low"], sure["high"] - sure["low"])

    def test_known_bale_weight_replaces_size_and_density(self):
        r = engine.estimate("bales", bales(length_cm=None, width_cm=None), known_bale_kg="20")
        self.assertAlmostEqual(r["straw_tonnes"]["likely"], 2.0, delta=0.01)

    def test_wetter_straw_gives_less_output(self):
        dry = engine.estimate("bales", bales(moisture_look="dry"))["cbg_tonnes"]["likely"]
        wet = engine.estimate("bales", bales(moisture_look="wet"))["cbg_tonnes"]["likely"]
        self.assertGreater(dry, wet)

    def test_rectangular_bales_need_height(self):
        with self.assertRaises(engine.BadReading):
            engine.estimate("bales", bales(shape="rectangular"))
        r = engine.estimate("bales", bales(shape="rectangular", height_cm=40, width_cm=50, length_cm=90))
        self.assertGreater(r["straw_tonnes"]["likely"], 0)

    def test_nonsense_readings_are_rejected(self):
        for bad in ({"count": 0}, {"count": "many"}, {"count": 10**6}, {"length_cm": -5}, {"width_cm": 1e9}):
            with self.assertRaises(engine.BadReading, msg=str(bad)):
                engine.estimate("bales", bales(**bad))

    def test_odd_bale_weight_warns(self):
        r = engine.estimate("bales", bales(length_cm=300, width_cm=300))
        self.assertTrue(any("unusual" in w for w in r["warnings"]))

    def test_unknown_straw_and_moisture_warn(self):
        r = engine.estimate("bales", bales(residue_type="unknown", moisture_look="unknown"))
        self.assertEqual(len(r["warnings"]), 2)

    def test_count_range_is_used(self):
        wide = engine.estimate("bales", bales(count_low=50, count_high=200))["cbg_tonnes"]
        narrow = engine.estimate("bales", bales(count_low=99, count_high=101))["cbg_tonnes"]
        self.assertGreater(wide["high"], narrow["high"])


class RevenueTests(unittest.TestCase):
    def test_straw_income_is_tonnes_times_price(self):
        r = engine.estimate("bales", bales())
        self.assertAlmostEqual(r["revenue_rs"]["straw"]["likely"], r["straw_tonnes"]["likely"] * 1250, delta=20)

    def test_carbon_matches_hand_calculation(self):
        r = engine.estimate("bales", bales())
        dry = r["straw_tonnes"]["likely"] * 0.8
        self.assertAlmostEqual(r["co2e_tonnes"]["likely"], dry * 0.074, delta=0.002)
        self.assertAlmostEqual(r["revenue_rs"]["carbon"]["likely"], r["co2e_tonnes"]["likely"] * 850, delta=15)

    def test_total_is_straw_plus_carbon_and_ordered(self):
        t = engine.estimate("bales", bales())["revenue_rs"]
        self.assertAlmostEqual(t["total"]["likely"], t["straw"]["likely"] + t["carbon"]["likely"], delta=20)
        self.assertLess(t["total"]["low"], t["total"]["likely"])
        self.assertLess(t["total"]["likely"], t["total"]["high"])

    def test_farmer_share_scales_carbon_only(self):
        full = engine.estimate("bales", bales())["revenue_rs"]
        half = engine.estimate("bales", bales(), carbon_share=0.5)["revenue_rs"]
        self.assertEqual(half["straw"], full["straw"])
        self.assertAlmostEqual(half["carbon"]["likely"], full["carbon"]["likely"] / 2, delta=10)


class FieldTests(unittest.TestCase):
    def reading(self, **over):
        r = {"residue_type": "paddy", "moisture_look": "dry",
             "field": {"area_acres": 2, "area_low": 1.5, "area_high": 2.5,
                       "coverage_fraction": 0.8, "coverage_low": 0.6, "coverage_high": 1}}
        r["field"].update(over)
        return r

    def test_field_straw_is_area_times_cover_times_yield(self):
        r = engine.estimate("field", self.reading())
        self.assertAlmostEqual(r["straw_tonnes"]["likely"], 2 * 0.8 * 2.8, delta=0.01)

    def test_field_range_is_wider_than_bale_range(self):
        field = engine.estimate("field", self.reading())["cbg_tonnes"]
        bale = engine.estimate("bales", bales())["cbg_tonnes"]
        self.assertGreater(field["high"] / field["low"], bale["high"] / bale["low"])

    def test_bad_field_values(self):
        for bad in ({"area_acres": 0}, {"area_acres": 9999}, {"coverage_fraction": 5}):
            with self.assertRaises(engine.BadReading):
                engine.estimate("field", self.reading(**bad))

    def test_unknown_mode(self):
        with self.assertRaises(engine.BadReading):
            engine.estimate("sky", {})


if __name__ == "__main__":
    unittest.main()
