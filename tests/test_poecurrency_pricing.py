import importlib.util
import sys
import unittest
from decimal import Decimal
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "\u7269\u4ef7\u8865\u4e01"
    / "tools"
    / "build_poe2scout_price_patch.py"
)


def load_price_module():
    spec = importlib.util.spec_from_file_location("price_patch", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class PoecurrencyPricingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.price_patch = load_price_module()

    def test_latest_buy_price_wins_over_avg_price(self):
        price, field = self.price_patch.poecurrency_item_price(
            {
                "item_name": "Kalandra's Mirror",
                "buy_avg": 1721.62962962963,
                "sell_avg": 0,
                "latest_buy1": 15000,
                "latest_sell1": 0,
            }
        )

        self.assertEqual(price, Decimal("15000"))
        self.assertEqual(field, "latest_buy1_only")

    def test_avg_price_is_fallback_when_latest_price_is_missing(self):
        price, field = self.price_patch.poecurrency_item_price(
            {
                "buy_avg": 1721.62962962963,
                "sell_avg": 0,
                "latest_buy1": 0,
                "latest_sell1": 0,
            }
        )

        self.assertEqual(price, Decimal("1721.62962962963"))
        self.assertEqual(field, "buy_avg_only")

    def test_latest_spread_keeps_conservative_side(self):
        price, field = self.price_patch.poecurrency_item_price(
            {
                "buy_avg": 76.6,
                "sell_avg": 65.9,
                "latest_buy1": 73,
                "latest_sell1": 9,
            }
        )

        self.assertEqual(price, Decimal("9"))
        self.assertEqual(field, "latest_sell1_conservative_spread_gt_5x")


if __name__ == "__main__":
    unittest.main()
