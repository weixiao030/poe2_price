import importlib.util
import json
import sys
import unittest
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "\u7269\u4ef7\u8865\u4e01"
    / "tools"
    / "build_poe2scout_price_patch.py"
)


def load_price_module():
    spec = importlib.util.spec_from_file_location("price_patch_quality", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class PoecurrencyQualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.price_patch = load_price_module()

    def test_normalizer_retains_quality_fields_and_aliases(self):
        normalized = self.price_patch.normalize_poecurrency_summary(
            {
                "value": [
                    {
                        "name": "\u901a\u8d27\u4ed3\u5e93",
                        "data": [
                            {
                                "name": "\u6d4b\u8bd5\u7269\u54c1",
                                "englishName": "Test Item",
                                "latestDateTime": "2026-07-10 15:00:00",
                                "prevBuy1Datetime": "2026-07-10 14:00:00",
                                "buyAvgYesterday": 12,
                                "sellAvgYesterday": 10,
                                "buyAvgRatio": 1.2,
                                "sellAvgRatio": 0.8,
                                "anomalyCount": 3,
                                "hasError": True,
                                "errorInfo": "OCR",
                            }
                        ],
                    }
                ]
            }
        )

        item = normalized[0]["items"][0]
        self.assertEqual(item["engname"], "Test Item")
        self.assertEqual(item["latest_datetime"], "2026-07-10 15:00:00")
        self.assertEqual(item["prev_buy1_datetime"], "2026-07-10 14:00:00")
        self.assertEqual(item["buy_avg_yesterday"], 12)
        self.assertEqual(item["sell_avg_yesterday"], 10)
        self.assertEqual(item["buy_avg_ratio"], 1.2)
        self.assertEqual(item["sell_avg_ratio"], 0.8)
        self.assertEqual(item["anomaly_count"], 3)
        self.assertIs(item["error"], True)
        self.assertEqual(item["error_info"], "OCR")

    def test_yesterday_average_is_only_last_resort(self):
        fallback_price, fallback_field = self.price_patch.poecurrency_item_price(
            {
                "latest_buy1": 0,
                "latest_sell1": 0,
                "buy_avg": 0,
                "sell_avg": 0,
                "prev_buy1": 0,
                "buy_avg_yesterday": 9,
                "sell_avg_yesterday": 16,
            }
        )
        current_price, current_field = self.price_patch.poecurrency_item_price(
            {
                "latest_buy1": 5,
                "latest_sell1": 0,
                "buy_avg": 0,
                "sell_avg": 0,
                "buy_avg_yesterday": 90,
                "sell_avg_yesterday": 160,
            }
        )

        self.assertEqual(fallback_price, Decimal("12"))
        self.assertEqual(
            fallback_field,
            "geo_buy_avg_yesterday_sell_avg_yesterday",
        )
        self.assertEqual(current_price, Decimal("5"))
        self.assertEqual(current_field, "latest_buy1_only")

    def test_quality_report_is_serializable_and_does_not_drop_stale_prices(self):
        summary = [
            {
                "category_label": "\u901a\u8d27\u4ed3\u5e93",
                "items": [
                    {
                        "item_name": "\u795e\u5723\u77f3",
                        "engname": "Divine Orb",
                        "latest_buy1": 300,
                        "currency_unit": "e",
                        "latest_datetime": "2026-07-10 15:00:00",
                    },
                    {
                        "item_name": "\u5361\u5170\u5fb7\u7684\u9b54\u955c",
                        "engname": "Mirror of Kalandra",
                        "latest_buy1": 2,
                        "currency_unit": "d",
                        "latest_datetime": "2026-07-09 12:00:00",
                        "prev_buy1_datetime": "2026-07-09 11:00:00",
                        "buy_avg_yesterday": 1.8,
                        "sell_avg_yesterday": 2.2,
                        "buy_avg_ratio": 1.1,
                        "sell_avg_ratio": 0.9,
                        "anomaly_count": 2,
                        "error": False,
                    },
                    {
                        "item_name": "\u9519\u8bef\u6761\u76ee",
                        "latest_buy1": 0,
                        "currency_unit": "e",
                        "latest_datetime": "not-a-time",
                        "error": True,
                        "error_info": "OCR",
                    },
                    {
                        "item_name": "\u672a\u77e5\u5355\u4f4d",
                        "latest_buy1": 9,
                        "currency_unit": "chaos",
                        "e": 999,
                    },
                    {
                        "item_name": "\u7f3a\u7701\u5d07\u9ad8\u5355\u4f4d",
                        "latest_buy1": 7,
                    },
                ],
            }
        ]
        now = datetime(2026, 7, 10, 16, 0, tzinfo=timezone(timedelta(hours=8)))

        prices, quality = self.price_patch.collect_poecurrency_observations_with_quality(
            summary,
            now=now,
        )

        mirror = prices[self.price_patch.poecurrency_api_id("\u5361\u5170\u5fb7\u7684\u9b54\u955c")]
        default_unit = prices[self.price_patch.poecurrency_api_id("\u7f3a\u7701\u5d07\u9ad8\u5355\u4f4d")]
        self.assertEqual(mirror.price_exalted, Decimal("600"))
        self.assertEqual(mirror.english_name, "Mirror of Kalandra")
        self.assertEqual(mirror.source_timestamp, "2026-07-09 12:00:00")
        self.assertEqual(mirror.source_metadata["anomaly_count"], 2)
        self.assertEqual(mirror.source_metadata["buy_avg_ratio"], 1.1)
        self.assertIn("anomaly", mirror.quality_flags)
        self.assertIn("stale", mirror.quality_flags)
        self.assertEqual(default_unit.price_exalted, Decimal("7"))
        self.assertIn("unit_defaulted", default_unit.quality_flags)
        self.assertNotIn(
            self.price_patch.poecurrency_api_id("\u672a\u77e5\u5355\u4f4d"),
            prices,
        )

        self.assertEqual(quality["item_count"], 5)
        self.assertEqual(quality["observation_count"], 3)
        self.assertEqual(quality["error_items"], 1)
        self.assertEqual(quality["anomaly_items"], 1)
        self.assertEqual(quality["anomaly_total"], 2)
        self.assertEqual(quality["unknown_unit_items"], 1)
        self.assertEqual(quality["unknown_units"], ["chaos"])
        self.assertEqual(quality["missing_unit_items"], 1)
        self.assertEqual(quality["stale_items"], 1)
        self.assertEqual(quality["invalid_timestamp_items"], 1)
        self.assertEqual(
            quality["source_timestamp_min"],
            "2026-07-09T11:00:00+08:00",
        )
        self.assertEqual(
            quality["source_timestamp_max"],
            "2026-07-10T15:00:00+08:00",
        )
        json.dumps(quality, ensure_ascii=False)

    def test_localized_match_precedes_english_alias_then_alias_fills_gap(self):
        pairs = [
            self.price_patch.BaseItemPair(
                "Metadata/Items/LocalizedWins",
                "Different English Name",
                "\u4e2d\u6587\u4f18\u5148",
            ),
            self.price_patch.BaseItemPair(
                "Metadata/Items/EnglishFallback",
                "English Alias",
                "\u53e6\u4e00\u4e2a\u4e2d\u6587\u540d",
            ),
        ]
        prices = {
            "localized": self.price_patch.PriceObservation(
                api_id="localized",
                en_name="\u4e2d\u6587\u4f18\u5148",
                english_name="English Alias",
                category="cn:test",
                price_exalted=Decimal("10"),
                value_traded=Decimal("0"),
                source_pair="test/localized",
                display_price="10.00E",
            ),
            "alias": self.price_patch.PriceObservation(
                api_id="alias",
                en_name="\u6ca1\u6709\u672c\u5730\u5bf9\u5e94\u540d",
                english_name="English Alias",
                category="cn:test",
                price_exalted=Decimal("9"),
                value_traded=Decimal("0"),
                source_pair="test/alias",
                display_price="9.00E",
            ),
        }
        quality = {}

        rows, missing = self.price_patch.match_cn_prices_to_base_items(
            prices,
            pairs,
            quality=quality,
        )

        self.assertEqual(missing, [])
        self.assertEqual(
            {row["api_id"]: row["metadata_path"] for row in rows},
            {
                "localized": "Metadata/Items/LocalizedWins",
                "alias": "Metadata/Items/EnglishFallback",
            },
        )
        self.assertEqual(quality["localized_name_matches"], 1)
        self.assertEqual(quality["english_alias_matches"], 1)

    def test_cn_matching_keeps_all_same_name_metadata_aliases(self):
        pairs = [
            self.price_patch.BaseItemPair(
                "Metadata/Items/Currency/RitualPinnacleKey",
                "Head of the King",
                "國王首級",
            ),
            self.price_patch.BaseItemPair(
                "Metadata/Items/Quest/RitualPinnacleKeyQuest",
                "Head of the King",
                "國王首級",
            ),
        ]
        prices = {
            "king": self.price_patch.PriceObservation(
                api_id="king",
                en_name="國王首級",
                category="cn:test",
                price_exalted=Decimal("100"),
                value_traded=Decimal("1"),
                source_pair="test/localized",
                display_price="1.00D",
            )
        }

        rows, missing = self.price_patch.match_cn_prices_to_base_items(
            prices,
            pairs,
        )

        self.assertEqual(missing, [])
        self.assertEqual(
            {row["metadata_path"] for row in rows},
            {
                "Metadata/Items/Currency/RitualPinnacleKey",
                "Metadata/Items/Quest/RitualPinnacleKeyQuest",
            },
        )

    def test_cn_matching_uses_english_alias_to_resolve_translation_collision(self):
        pairs = [
            self.price_patch.BaseItemPair(
                "Metadata/Items/Gems/SkillGemDespair",
                "Despair",
                "絕望",
            ),
            self.price_patch.BaseItemPair(
                "Metadata/Items/Gem/SupportGemDesperation",
                "Desperation",
                "絕望",
            ),
        ]
        prices = {
            "desperation": self.price_patch.PriceObservation(
                api_id="desperation",
                en_name="絕望",
                english_name="Desperation",
                category="cn:test",
                price_exalted=Decimal("100"),
                value_traded=Decimal("1"),
                source_pair="test/localized",
                display_price="1.00D",
            )
        }

        rows, missing = self.price_patch.match_cn_prices_to_base_items(
            prices,
            pairs,
        )

        self.assertEqual(missing, [])
        self.assertEqual(
            [row["metadata_path"] for row in rows],
            ["Metadata/Items/Gem/SupportGemDesperation"],
        )

    def test_empty_category_is_reported_separately(self):
        prices, quality = self.price_patch.collect_poecurrency_observations_with_quality(
            [
                {"category_label": "空分类", "items": []},
                {
                    "category_label": "通货仓库",
                    "items": [
                        {
                            "item_name": "神圣石",
                            "engname": "Divine Orb",
                            "currency_unit": "e",
                            "latest_buy1": 400,
                        }
                    ],
                },
            ]
        )

        self.assertIn("divine", prices)
        self.assertEqual(quality["empty_categories"], ["空分类"])
        self.assertEqual(
            quality["category_stats"],
            [
                {"category": "空分类", "items": 0, "status": "empty"},
                {"category": "通货仓库", "items": 1, "status": "ok"},
            ],
        )

    def test_fresh_clean_duplicate_beats_higher_stale_error_price(self):
        now = datetime(2026, 7, 10, 16, 0, tzinfo=timezone(timedelta(hours=8)))
        prices, _quality = self.price_patch.collect_poecurrency_observations_with_quality(
            [
                {
                    "category_label": "通货仓库",
                    "items": [
                        {
                            "item_name": "神圣石",
                            "currency_unit": "e",
                            "latest_buy1": 300,
                            "latest_datetime": "2026-07-10 15:00:00",
                        },
                        {
                            "item_name": "神圣石",
                            "currency_unit": "e",
                            "latest_buy1": 900,
                            "latest_datetime": "2026-07-01 15:00:00",
                            "error": True,
                            "error_info": "stale OCR",
                        },
                        {
                            "item_name": "测试通货",
                            "currency_unit": "e",
                            "latest_buy1": 5,
                            "latest_datetime": "2026-07-10 15:00:00",
                        },
                        {
                            "item_name": "测试通货",
                            "currency_unit": "e",
                            "latest_buy1": 50,
                            "latest_datetime": "2026-07-01 15:00:00",
                            "error": True,
                            "error_info": "stale",
                        },
                    ],
                }
            ],
            now=now,
        )

        self.assertEqual(prices["divine"].price_exalted, Decimal("300"))
        test_id = self.price_patch.poecurrency_api_id("测试通货")
        self.assertEqual(prices[test_id].price_exalted, Decimal("5"))
        self.assertNotIn("stale", prices[test_id].quality_flags)


if __name__ == "__main__":
    unittest.main()
