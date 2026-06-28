import importlib.util
import json
import sys
import unittest
import zipfile
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


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

    def minimal_price_map(self):
        return {
            "divine": self.price_patch.PriceObservation(
                api_id="divine",
                en_name="Divine Orb",
                category="currency",
                price_exalted=Decimal("100"),
                value_traded=Decimal("0"),
                source_pair="test",
            )
        }

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

        self.assertEqual(price, Decimal("73"))
        self.assertEqual(field, "latest_buy1_closest_to_geo_buy_avg_sell_avg_spread_gt_5x")

    def test_latest_spread_uses_average_reference_when_available(self):
        price, field = self.price_patch.poecurrency_item_price(
            {
                "buy_avg": 56.808571428571426,
                "sell_avg": 30.705238095238094,
                "latest_buy1": 2.6,
                "latest_sell1": 242,
                "currency_unit": "d",
            }
        )

        self.assertEqual(price.quantize(Decimal("0.0001")), Decimal("2.5084"))
        self.assertEqual(field, "geo_latest_buy1_latest_sell1_d_digit_shift_100x")

    def test_latest_spread_falls_back_to_average_when_both_sides_are_far(self):
        price, field = self.price_patch.poecurrency_item_price(
            {
                "buy_avg": 56.808571428571426,
                "sell_avg": 30.705238095238094,
                "latest_buy1": 2.6,
                "latest_sell1": 2400,
                "currency_unit": "d",
            }
        )

        self.assertEqual(price.quantize(Decimal("0.0001")), Decimal("41.7651"))
        self.assertEqual(field, "geo_buy_avg_sell_avg_latest_spread_avg_fallback")

    def test_poecurrency_summary_accepts_wrapped_response_and_field_aliases(self):
        class FakeClient:
            def get_json(self, _url):
                return {
                    "value": [
                        {
                            "name": "通货仓库",
                            "data": [
                                {
                                    "name": "神圣石",
                                    "latest_buy": 300,
                                    "latest_sell": 295,
                                    "unit": "e",
                                }
                            ],
                        }
                    ],
                    "Count": 1,
                }

        summary = self.price_patch.fetch_poecurrency_summary(
            FakeClient(), "https://example.invalid/summary"
        )

        self.assertEqual(summary[0]["category_label"], "通货仓库")
        self.assertEqual(summary[0]["items"][0]["item_name"], "神圣石")
        self.assertEqual(summary[0]["items"][0]["latest_buy1"], 300)
        self.assertEqual(summary[0]["items"][0]["latest_sell1"], 295)

    def test_collect_observations_accepts_wrapped_response(self):
        best = self.price_patch.collect_poecurrency_observations(
            {
                "value": [
                    {
                        "name": "通货仓库",
                        "data": [
                            {
                                "name": "神圣石",
                                "latest_buy": 300,
                                "unit": "e",
                            },
                            {
                                "name": "测试物品",
                                "latest_buy": 2,
                                "unit": "d",
                            },
                        ],
                    }
                ],
                "Count": 1,
            }
        )

        row = best[self.price_patch.poecurrency_api_id("测试物品")]
        self.assertEqual(row.price_exalted, Decimal("600"))
        self.assertIn("d_to_e@300", row.source_pair)

    def test_error_flag_uses_average_before_realtime_quotes(self):
        price, field = self.price_patch.poecurrency_item_price(
            {
                "buy_avg": 54,
                "sell_avg": 13,
                "latest_buy1": 2,
                "latest_sell1": 1,
                "prev_buy1": 247,
                "error": True,
                "error_info": "价格出现剧烈波动, 可能为OCR识别故障",
            }
        )

        self.assertEqual(price.quantize(Decimal("0.0001")), Decimal("26.4953"))
        self.assertEqual(field, "geo_buy_avg_sell_avg_error_fallback")

    def test_error_flag_falls_back_to_average(self):
        price, field = self.price_patch.poecurrency_item_price(
            {
                "buy_avg": 80,
                "sell_avg": 60,
                "latest_buy1": 1,
                "latest_sell1": 1,
                "error": True,
            }
        )

        self.assertEqual(price.quantize(Decimal("0.0001")), Decimal("69.2820"))
        self.assertEqual(field, "geo_buy_avg_sell_avg_error_fallback")

    def test_error_flag_falls_back_to_previous_buy_only_without_average(self):
        price, field = self.price_patch.poecurrency_item_price(
            {
                "buy_avg": 0,
                "sell_avg": 0,
                "latest_buy1": 2.3,
                "latest_sell1": 225,
                "prev_buy1": 240,
                "error": True,
            }
        )

        self.assertEqual(price, Decimal("240"))
        self.assertEqual(field, "prev_buy1_error_fallback")

    def test_nightmare_simulacrum_ocr_error_does_not_use_prev_buy(self):
        best = self.price_patch.collect_poecurrency_observations(
            [
                {
                    "category_label": "通货仓库",
                    "items": [
                        {
                            "item_name": "神圣石",
                            "latest_buy1": 316,
                            "latest_sell1": 314,
                            "currency_unit": "e",
                        }
                    ],
                },
                {
                    "category_label": "梦魇拟像",
                    "items": [
                        {
                            "item_name": "梦魇拟像",
                            "buy_avg": 38.84230769230769,
                            "sell_avg": 34.817692307692305,
                            "latest_buy1": 2.3,
                            "latest_sell1": 225,
                            "prev_buy1": 240,
                            "error": True,
                            "error_info": "价格出现剧烈波动, 可能为OCR识别故障",
                            "currency_unit": "d",
                        }
                    ],
                },
            ]
        )

        divine = self.price_patch.divine_price_exalted(best)
        self.price_patch.apply_display_prices(best, divine)
        row = best[self.price_patch.poecurrency_api_id("梦魇拟像")]

        self.assertEqual(divine, Decimal("316"))
        self.assertEqual(row.display_price, "2.27D")
        self.assertIn("d_digit_shift_100x", row.source_pair)
        self.assertNotIn("prev_buy1", row.source_pair)

    def test_divine_ratio_uses_latest_buy1(self):
        price, field = self.price_patch.poecurrency_divine_price(
            {
                "item_name": "神圣石",
                "buy_avg": 320,
                "sell_avg": 275,
                "latest_buy1": 279,
                "latest_sell1": 275,
            }
        )

        self.assertEqual(price, Decimal("279"))
        self.assertEqual(field, "latest_buy1_divine_ratio")

    def test_divine_ratio_falls_back_when_latest_buy_is_ocr_outlier(self):
        price, field = self.price_patch.poecurrency_divine_price(
            {
                "item_name": "神圣石",
                "buy_avg": 316,
                "sell_avg": 314,
                "latest_buy1": 31.6,
                "latest_sell1": 314,
                "prev_buy1": 322,
                "currency_unit": "e",
            }
        )

        self.assertEqual(price, Decimal("314"))
        self.assertEqual(field, "latest_sell1_divine_spread_fallback")

    def test_divine_ratio_uses_average_when_latest_buy_outlier_has_no_sell(self):
        price, field = self.price_patch.poecurrency_divine_price(
            {
                "item_name": "神圣石",
                "buy_avg": 316,
                "sell_avg": 314,
                "latest_buy1": 31.6,
                "latest_sell1": 0,
                "currency_unit": "e",
            }
        )

        self.assertEqual(price, Decimal("316"))
        self.assertEqual(field, "buy_avg_divine_latest_outlier_fallback")

    def test_stale_error_can_still_extract_average_price(self):
        price, field = self.price_patch.poecurrency_item_price(
            {
                "buy_avg": 12,
                "sell_avg": 10,
                "latest_buy1": 0,
                "latest_sell1": 0,
                "error": True,
                "error_info": "数据已过时超过24h",
                "currency_unit": "e",
            }
        )

        self.assertEqual(price.quantize(Decimal("0.0001")), Decimal("10.9545"))
        self.assertEqual(field, "geo_buy_avg_sell_avg_error_fallback")

    def test_ocr_error_without_average_can_still_extract_previous_buy(self):
        price, field = self.price_patch.poecurrency_item_price(
            {
                "buy_avg": 0,
                "sell_avg": 0,
                "latest_buy1": 0,
                "latest_sell1": 0,
                "prev_buy1": 8,
                "error": True,
                "error_info": "价格出现剧烈波动, 可能为OCR识别故障",
                "currency_unit": "e",
            }
        )

        self.assertEqual(price, Decimal("8"))
        self.assertEqual(field, "prev_buy1_error_fallback")

    def test_ocr_error_without_any_price_is_skipped(self):
        best = self.price_patch.collect_poecurrency_observations(
            [
                {
                    "category_label": "通货仓库",
                    "items": [
                        {
                            "item_name": "神圣石",
                            "latest_buy1": 316,
                            "currency_unit": "e",
                        },
                        {
                            "item_name": "空价格测试",
                            "buy_avg": 0,
                            "sell_avg": 0,
                            "latest_buy1": 0,
                            "latest_sell1": 0,
                            "prev_buy1": 0,
                            "error": True,
                            "currency_unit": "e",
                        },
                    ],
                }
            ]
        )

        self.assertNotIn(self.price_patch.poecurrency_api_id("空价格测试"), best)

    def test_currency_unit_d_is_converted_to_exalted(self):
        best = self.price_patch.collect_poecurrency_observations(
            [
                {
                    "category_label": "通货仓库",
                    "items": [
                        {
                            "item_name": "神圣石",
                            "latest_buy1": 291,
                            "latest_sell1": 290,
                            "currency_unit": "e",
                        },
                        {
                            "item_name": "完美崇高石",
                            "latest_buy1": 4.5,
                            "latest_sell1": 0,
                            "currency_unit": "d",
                        },
                    ],
                }
            ]
        )

        row = best[self.price_patch.poecurrency_api_id("完美崇高石")]
        self.assertEqual(row.price_exalted, Decimal("1309.5"))
        self.assertIn("d_to_e@291", row.source_pair)

    def test_explicit_e_field_wins_over_display_unit(self):
        best = self.price_patch.collect_poecurrency_observations(
            [
                {
                    "category_label": "通货仓库",
                    "items": [
                        {
                            "item_name": "神圣石",
                            "latest_buy1": 291,
                            "currency_unit": "e",
                        },
                        {
                            "item_name": "测试物品",
                            "latest_buy1": 4.5,
                            "currency_unit": "d",
                            "display": "4.5D",
                            "e": 1234,
                        },
                    ],
                }
            ]
        )

        row = best[self.price_patch.poecurrency_api_id("测试物品")]
        self.assertEqual(row.price_exalted, Decimal("1234"))
        self.assertIn("e_api_exalted/e", row.source_pair)

    def test_high_value_outlier_uses_poe2scout_reference(self):
        primary = [
            {
                "metadata_path": "Metadata/Items/Currency/CurrencyMirror",
                "name": "卡兰德的魔镜",
                "price": "54.15D",
                "new_name": "",
                "en_name": "",
                "api_id": "cn:卡兰德的魔镜",
                "price_exalted": "15000",
                "source_pair": "poecurrency.top/通货仓库/latest_buy1_only",
            }
        ]
        fallback = [
            {
                "metadata_path": "Metadata/Items/Currency/CurrencyMirror",
                "name": "卡兰德的魔镜",
                "price": "4264.31D",
                "new_name": "",
                "en_name": "Mirror of Kalandra",
                "api_id": "mirror",
                "price_exalted": "1485969.32261415",
                "source_pair": "Mirror of Kalandra / Divine Orb",
            }
        ]

        rows, count = self.price_patch.apply_high_value_reference_rows(
            primary=primary,
            fallback=fallback,
            primary_divine_exalted=Decimal("277"),
            fallback_divine_exalted=Decimal("348.46629697"),
            min_divine=Decimal("10"),
            max_ratio=Decimal("5"),
        )

        self.assertEqual(count, 1)
        self.assertEqual(rows[0]["price"], "4264.31D")
        self.assertIn("high_value_reference=poe2scout", rows[0]["source_pair"])

    def test_high_value_reference_keeps_close_cn_price(self):
        primary = [
            {
                "metadata_path": "Metadata/Items/Foo",
                "name": "普通高价物",
                "price": "20.00D",
                "new_name": "",
                "en_name": "",
                "api_id": "cn:普通高价物",
                "price_exalted": "5580",
                "source_pair": "poecurrency.top/foo",
            }
        ]
        fallback = [
            {
                "metadata_path": "Metadata/Items/Foo",
                "name": "普通高价物",
                "price": "24.00D",
                "new_name": "",
                "en_name": "Foo",
                "api_id": "foo",
                "price_exalted": "8363.19112728",
                "source_pair": "Foo / Divine Orb",
            }
        ]

        rows, count = self.price_patch.apply_high_value_reference_rows(
            primary=primary,
            fallback=fallback,
            primary_divine_exalted=Decimal("279"),
            fallback_divine_exalted=Decimal("348.46629697"),
            min_divine=Decimal("10"),
            max_ratio=Decimal("5"),
        )

        self.assertEqual(count, 0)
        self.assertEqual(rows[0]["price"], "20.00D")

    def test_high_value_reference_requires_high_poe2scout_price(self):
        primary = [
            {
                "metadata_path": "Metadata/Items/LocalExpensive",
                "name": "国服偏贵物",
                "price": "14.00D",
                "new_name": "",
                "en_name": "",
                "api_id": "cn:国服偏贵物",
                "price_exalted": "3906",
                "source_pair": "poecurrency.top/foo",
            }
        ]
        fallback = [
            {
                "metadata_path": "Metadata/Items/LocalExpensive",
                "name": "国服偏贵物",
                "price": "2.00D",
                "new_name": "",
                "en_name": "Local Expensive",
                "api_id": "local-expensive",
                "price_exalted": "696.93259394",
                "source_pair": "Local Expensive / Divine Orb",
            }
        ]

        rows, count = self.price_patch.apply_high_value_reference_rows(
            primary=primary,
            fallback=fallback,
            primary_divine_exalted=Decimal("279"),
            fallback_divine_exalted=Decimal("348.46629697"),
            min_divine=Decimal("10"),
            max_ratio=Decimal("5"),
        )

        self.assertEqual(count, 0)
        self.assertEqual(rows[0]["price"], "14.00D")

    def test_parse_poe2db_economy_prices_pair_us_and_cn_rows(self):
        us_html = """
        <table><tbody>
        <tr><td><a href="Economy_divine">Divine Orb</a><a href="Divine_Orb" class="border p-1">Wiki</a></td>
        <td>9.93 <a href="Economy_chaos"></a> 1 <a href="Economy_divine"></a></td><td></td><td>4,913,645</td></tr>
        <tr><td><a href="Economy_exalted">Exalted Orb</a><a href="Exalted_Orb" class="border p-1">Wiki</a></td>
        <td>1 <a href="Economy_divine"></a> 393 <a href="Economy_exalted"></a></td><td></td><td>542,073,655</td></tr>
        <tr><td><a href="Economy_mirror">Mirror of Kalandra</a><a href="Mirror_of_Kalandra" class="border p-1">Wiki</a></td>
        <td>4656 <a href="Economy_divine"></a> 1 <a href="Economy_mirror"></a></td><td></td><td>995</td></tr>
        </tbody></table>
        """
        cn_html = us_html.replace("Divine Orb", "神圣石").replace(
            "Exalted Orb", "崇高石"
        ).replace("Mirror of Kalandra", "卡兰德的魔镜")

        class FakeClient:
            def __init__(self):
                self.calls = 0

            def get(self, _url):
                self.calls += 1
                text = us_html if self.calls == 1 else cn_html
                return type("Response", (), {"text": text})()

        raw, best = self.price_patch.build_poe2db_economy_prices(
            FakeClient(),
            "https://poe2db.tw/us/Economy",
            "https://poe2db.tw/cn/Economy",
        )

        self.assertEqual(raw["matched_rows"], 3)
        self.assertEqual(best["divine"].price_exalted, Decimal("393"))
        self.assertEqual(best["exalted"].price_exalted, Decimal("1"))
        self.assertEqual(best["poe2db:mirror"].en_name, "卡兰德的魔镜")
        self.assertEqual(best["poe2db:mirror"].price_exalted, Decimal("1829808"))

    def test_poe2db_economy_prices_fetch_all_category_pages(self):
        nav = """
        <nav>
        <a href="Economy_Currency">Currency</a>
        <a href="Economy_Fragments">Fragments</a>
        <a href="Economy_mirror">Mirror of Kalandra</a>
        </nav>
        """
        us_currency_html = nav + """
        <table><tbody>
        <tr><td><a href="Economy_divine">Divine Orb</a><a href="Divine_Orb" class="border p-1">Wiki</a></td>
        <td>9.93 <a href="Economy_chaos"></a> 1 <a href="Economy_divine"></a></td><td></td><td>4,913,645</td></tr>
        <tr><td><a href="Economy_exalted">Exalted Orb</a><a href="Exalted_Orb" class="border p-1">Wiki</a></td>
        <td>1 <a href="Economy_divine"></a> 393 <a href="Economy_exalted"></a></td><td></td><td>542,073,655</td></tr>
        </tbody></table>
        """
        us_fragments_html = """
        <table><tbody>
        <tr><td><a href="Economy_ritual-audience">An Audience with the King</a><a href="Ritual_Audience" class="border p-1">Wiki</a></td>
        <td>5 <a href="Economy_divine"></a> 1 <a href="Economy_ritual-audience"></a></td><td></td><td>10</td></tr>
        </tbody></table>
        """
        cn_currency_html = us_currency_html.replace("Divine Orb", "CN Divine").replace(
            "Exalted Orb", "CN Exalted"
        )
        cn_fragments_html = us_fragments_html.replace(
            "An Audience with the King", "CN Audience"
        )

        class FakeClient:
            def __init__(self):
                self.responses = {
                    "https://poe2db.tw/Economy": us_currency_html,
                    "https://poe2db.tw/cn/Economy": cn_currency_html,
                    "https://poe2db.tw/Economy_Fragments": us_fragments_html,
                    "https://poe2db.tw/cn/Economy_Fragments": cn_fragments_html,
                }
                self.urls: list[str] = []

            def get(self, url):
                self.urls.append(url)
                return type("Response", (), {"text": self.responses[url]})()

        client = FakeClient()
        raw, best = self.price_patch.build_poe2db_economy_prices(
            client,
            "https://poe2db.tw/Economy",
            "https://poe2db.tw/cn/Economy",
        )

        self.assertEqual(raw["category_pages"], ["Economy_Currency", "Economy_Fragments"])
        self.assertEqual(raw["us_rows"], 3)
        self.assertEqual(raw["matched_rows"], 3)
        self.assertIn("https://poe2db.tw/Economy_Fragments", client.urls)
        self.assertIn("https://poe2db.tw/cn/Economy_Fragments", client.urls)
        self.assertIn("poe2db:ritual-audience", best)
        self.assertEqual(best["poe2db:ritual-audience"].en_name, "CN Audience")
        self.assertEqual(best["poe2db:ritual-audience"].price_exalted, Decimal("1965"))

    def test_poe2db_economy_prices_fail_when_category_page_is_missing(self):
        nav = """
        <nav>
        <a href="Economy_Currency">Currency</a>
        <a href="Economy_Fragments">Fragments</a>
        </nav>
        """
        currency_html = nav + """
        <table><tbody>
        <tr><td><a href="Economy_divine">Divine Orb</a><a href="Divine_Orb" class="border p-1">Wiki</a></td>
        <td>9.93 <a href="Economy_chaos"></a> 1 <a href="Economy_divine"></a></td><td></td><td>4,913,645</td></tr>
        <tr><td><a href="Economy_exalted">Exalted Orb</a><a href="Exalted_Orb" class="border p-1">Wiki</a></td>
        <td>1 <a href="Economy_divine"></a> 393 <a href="Economy_exalted"></a></td><td></td><td>542,073,655</td></tr>
        </tbody></table>
        """

        class FakeClient:
            def get(self, url):
                if url in {"https://poe2db.tw/Economy", "https://poe2db.tw/cn/Economy"}:
                    return type("Response", (), {"text": currency_html})()
                raise RuntimeError("blocked")

        with self.assertRaisesRegex(ValueError, "Economy_Fragments"):
            self.price_patch.build_poe2db_economy_prices(
                FakeClient(),
                "https://poe2db.tw/Economy",
                "https://poe2db.tw/cn/Economy",
            )

    def test_parse_poe_ninja_currency_prices(self):
        class FakeClient:
            def get_json(self, url):
                self.urls.append(url)
                if "type=Currency" in url:
                    return {
                        "core": {
                            "items": [
                                {"id": "divine", "name": "Divine Orb", "category": "Currency"},
                                {"id": "exalted", "name": "Exalted Orb", "category": "Currency"},
                            ],
                            "rates": {"exalted": 400},
                        },
                        "lines": [
                            {"id": "divine", "primaryValue": 1, "volumePrimaryValue": 100},
                            {"id": "exalted", "primaryValue": 0.0025, "volumePrimaryValue": 100},
                            {"id": "mirror", "primaryValue": 4500, "volumePrimaryValue": 2},
                        ],
                        "items": [
                            {"id": "mirror", "name": "Mirror of Kalandra", "category": "Currency"}
                        ],
                    }
                if "type=Runes" in url:
                    return {
                        "core": {"items": [], "rates": {"exalted": 400}},
                        "lines": [{"id": "adept-rune", "primaryValue": 0.01}],
                        "items": [{"id": "adept-rune", "name": "Adept Rune", "category": "Runes"}],
                    }
                if "type=UniqueWeapons" in url:
                    return {
                        "core": {"rates": {"exalted": 400}},
                        "lines": [
                            {
                                "detailsId": "bluetongue-shortsword",
                                "name": "Bluetongue",
                                "primaryValue": 2,
                                "listingCount": 10,
                            }
                        ],
                    }
                raise AssertionError(f"unexpected URL: {url}")

            def __init__(self):
                self.urls: list[str] = []

        client = FakeClient()
        with patch.object(self.price_patch, "POE_NINJA_EXCHANGE_TYPES", ("Currency", "Runes")), patch.object(
            self.price_patch, "POE_NINJA_ITEM_TYPES", ("UniqueWeapons",)
        ):
            raw, best = self.price_patch.build_poe_ninja_currency_prices(
                client,
                "https://poe.ninja/poe2/economy/runesofaldur/currency",
                "https://poe.ninja/poe2/api/economy/exchange/current/overview",
                "Runes of Aldur",
                "https://poe.ninja/poe2/api/economy/stash/current/item/overview",
            )

        self.assertEqual(raw["source"], "poe-ninja")
        self.assertEqual(raw["category_count"], 3)
        self.assertEqual(raw["lines"], 5)
        self.assertEqual(best["divine"].price_exalted, Decimal("400"))
        self.assertEqual(best["exalted"].price_exalted, Decimal("1"))
        self.assertEqual(best["mirror"].en_name, "Mirror of Kalandra")
        self.assertEqual(best["mirror"].price_exalted, Decimal("1800000"))
        self.assertEqual(best["adept-rune"].price_exalted, Decimal("4.00"))
        self.assertEqual(best["unique:bluetongueshortsword"].price_exalted, Decimal("800"))
        self.assertTrue(any("type=Runes" in url for url in client.urls))
        self.assertTrue(any("type=UniqueWeapons" in url for url in client.urls))

    def test_fetch_unique_category_items_reads_all_pages(self):
        class FakeClient:
            def __init__(self):
                self.urls: list[str] = []

            def get_json(self, url):
                self.urls.append(url)
                if "&Page=1&" in url:
                    return {"Items": [{"Name": "one"}], "Pages": 2, "Total": 2}
                if "&Page=2&" in url:
                    return {"Items": [{"Name": "two"}], "Pages": 2, "Total": 2}
                raise AssertionError(f"unexpected URL: {url}")

        client = FakeClient()
        items = self.price_patch.fetch_unique_category_items(
            client,
            "https://api.poe2scout.com",
            "runes",
            "armour",
            per_page=1,
        )

        self.assertEqual([item["Name"] for item in items], ["one", "two"])
        self.assertTrue(any("Page=1" in url for url in client.urls))
        self.assertTrue(any("Page=2" in url for url in client.urls))

    def test_poecurrency_cn_can_use_localized_baseitems_without_english_pairs(self):
        pairs = [
            self.price_patch.BaseItemPair(
                "Metadata/Items/Currency/CurrencyMirror",
                "",
                "卡兰德的魔镜",
            )
        ]
        prices = {
            "poe2db:mirror": self.price_patch.PriceObservation(
                api_id="poe2db:mirror",
                en_name="卡兰德的魔镜",
                category="poe2db-economy",
                price_exalted=Decimal("1830408"),
                value_traded=Decimal("995"),
                source_pair="Poe2DB Economy/Mirror of Kalandra",
                display_price="4656.00D",
            )
        }

        rows, missing = self.price_patch.match_cn_prices_to_base_items(prices, pairs)

        self.assertEqual(missing, [])
        self.assertEqual(rows[0]["metadata_path"], "Metadata/Items/Currency/CurrencyMirror")
        self.assertEqual(rows[0]["price"], "4656.00D")

    def test_patch_scope_currency_keeps_clean_words_entry(self):
        with TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            (out_dir / "tc_words.datc64").write_bytes(b"clean words")
            calls = {"base": 0, "words": 0}

            def fake_run_patch_builder(**kwargs):
                calls["base"] += 1
                with zipfile.ZipFile(kwargs["output_zip"], "w") as zf:
                    zf.writestr("data/balance/baseitemtypes.datc64", b"base")

            def fake_patch_unique_word_prices(**kwargs):
                calls["words"] += 1
                return 1, [], []

            with patch.object(self.price_patch, "load_base_item_pairs", return_value=[]), patch.object(
                self.price_patch,
                "build_scout_prices",
                return_value=({"exchange_snapshot": {}}, self.minimal_price_map(), [], []),
            ), patch.object(self.price_patch, "divine_price_exalted", return_value=Decimal("100")), patch.object(
                self.price_patch, "apply_display_prices", return_value=None
            ), patch.object(
                self.price_patch, "match_prices_to_base_items", return_value=([], [])
            ), patch.object(
                self.price_patch, "load_unique_names", return_value={"x": object()}
            ), patch.object(
                self.price_patch, "run_patch_builder", side_effect=fake_run_patch_builder
            ), patch.object(
                self.price_patch, "patch_unique_word_prices", side_effect=fake_patch_unique_word_prices
            ):
                rc = self.price_patch.main(
                    [
                        "--patch-scope",
                        "currency",
                        "--fallback-price-sources",
                        "none",
                        "--out-dir",
                        str(out_dir),
                        "--output-zip",
                        str(out_dir / "patch.zip"),
                        "--en-baseitems",
                        str(out_dir / "en.datc64"),
                        "--tc-baseitems",
                        str(out_dir / "tc.datc64"),
                        "--en-words",
                        str(out_dir / "en_words.datc64"),
                        "--tc-words",
                        str(out_dir / "tc_words.datc64"),
                        "--unique-gold-prices",
                        str(out_dir / "unique.datc64"),
                        "--game-path",
                        "data/balance/baseitemtypes.datc64",
                        "--words-game-path",
                        "data/balance/words.datc64",
                    ]
                )

            self.assertEqual(rc, 0)
            self.assertEqual(calls, {"base": 1, "words": 0})
            with zipfile.ZipFile(out_dir / "patch.zip", "r") as zf:
                self.assertEqual(zf.read("data/balance/words.datc64"), b"clean words")

    def test_patch_scope_uniques_cleans_base_item_price_entry(self):
        with TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            for name in ("en_words.datc64", "tc_words.datc64", "unique.datc64"):
                (out_dir / name).write_bytes(b"data")
            (out_dir / "tc.datc64").write_bytes(b"clean baseitems")
            calls = {"base": 0, "words": 0}

            def fake_run_patch_builder(**kwargs):
                calls["base"] += 1
                with zipfile.ZipFile(kwargs["output_zip"], "w") as zf:
                    zf.writestr("data/balance/baseitemtypes.datc64", b"cleaned baseitems")

            def fake_patch_unique_word_prices(**kwargs):
                calls["words"] += 1
                kwargs["patched_words"].write_bytes(b"words")
                return 1, [{"status": "patched"}], []

            with patch.object(self.price_patch, "load_base_item_pairs", return_value=[]), patch.object(
                self.price_patch,
                "build_scout_prices",
                return_value=({"exchange_snapshot": {}}, self.minimal_price_map(), [], []),
            ), patch.object(self.price_patch, "divine_price_exalted", return_value=Decimal("100")), patch.object(
                self.price_patch, "apply_display_prices", return_value=None
            ), patch.object(
                self.price_patch, "match_prices_to_base_items", return_value=([{"api_id": "a", "en_name": "A"}], [])
            ), patch.object(
                self.price_patch, "load_unique_names", return_value={"x": object()}
            ), patch.object(
                self.price_patch, "run_patch_builder", side_effect=fake_run_patch_builder
            ), patch.object(
                self.price_patch, "patch_unique_word_prices", side_effect=fake_patch_unique_word_prices
            ):
                rc = self.price_patch.main(
                    [
                        "--patch-scope",
                        "uniques",
                        "--fallback-price-sources",
                        "none",
                        "--out-dir",
                        str(out_dir),
                        "--output-zip",
                        str(out_dir / "patch.zip"),
                        "--en-baseitems",
                        str(out_dir / "en.datc64"),
                        "--tc-baseitems",
                        str(out_dir / "tc.datc64"),
                        "--en-words",
                        str(out_dir / "en_words.datc64"),
                        "--tc-words",
                        str(out_dir / "tc_words.datc64"),
                        "--unique-gold-prices",
                        str(out_dir / "unique.datc64"),
                        "--game-path",
                        "data/balance/baseitemtypes.datc64",
                        "--words-game-path",
                        "data/balance/words.datc64",
                    ]
                )

            self.assertEqual(rc, 0)
            self.assertEqual(calls, {"base": 1, "words": 1})
            with zipfile.ZipFile(out_dir / "patch.zip", "r") as zf:
                self.assertEqual(
                    zf.read("data/balance/baseitemtypes.datc64"), b"cleaned baseitems"
                )
                self.assertEqual(zf.read("data/balance/words.datc64"), b"words")

    def test_patch_scope_none_cleans_without_fetching_prices(self):
        with TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            (out_dir / "tc.datc64").write_bytes(b"current baseitems")
            (out_dir / "tc_words.datc64").write_bytes(b"current words")
            calls = {"base": 0, "fetch": 0}

            def fake_run_patch_builder(**kwargs):
                calls["base"] += 1
                with zipfile.ZipFile(kwargs["output_zip"], "w") as zf:
                    zf.writestr("data/balance/baseitemtypes.datc64", b"cleaned baseitems")

            def fake_fetch(*_args, **_kwargs):
                calls["fetch"] += 1
                return {}, {}, [], []

            with patch.object(self.price_patch, "build_scout_prices", side_effect=fake_fetch), patch.object(
                self.price_patch, "fetch_poecurrency_summary", side_effect=AssertionError("should not fetch")
            ), patch.object(
                self.price_patch, "run_patch_builder", side_effect=fake_run_patch_builder
            ), patch.object(
                self.price_patch, "clean_word_price_labels_file", return_value=[]
            ):
                rc = self.price_patch.main(
                    [
                        "--patch-scope",
                        "none",
                        "--fallback-price-sources",
                        "none",
                        "--out-dir",
                        str(out_dir),
                        "--output-zip",
                        str(out_dir / "patch.zip"),
                        "--en-baseitems",
                        str(out_dir / "en.datc64"),
                        "--tc-baseitems",
                        str(out_dir / "tc.datc64"),
                        "--tc-words",
                        str(out_dir / "tc_words.datc64"),
                        "--game-path",
                        "data/balance/baseitemtypes.datc64",
                        "--words-game-path",
                        "data/balance/words.datc64",
                    ]
                )

            self.assertEqual(rc, 0)
            self.assertEqual(calls, {"base": 1, "fetch": 0})
            with zipfile.ZipFile(out_dir / "patch.zip", "r") as zf:
                self.assertEqual(
                    zf.read("data/balance/baseitemtypes.datc64"), b"cleaned baseitems"
                )
                self.assertEqual(zf.read("data/balance/words.datc64"), b"current words")

    def test_cn_reference_source_failure_continues_with_primary_prices(self):
        summary = [
            {
                "category_label": "通货仓库",
                "items": [
                    {
                        "item_name": "神圣石",
                        "latest_buy1": 300,
                        "latest_sell1": 300,
                        "currency_unit": "e",
                    },
                    {
                        "item_name": "测试物品",
                        "latest_buy1": 2,
                        "latest_sell1": 2,
                        "currency_unit": "d",
                    },
                ],
            }
        ]

        for source, function_name, error_file in (
            ("poe2scout", "build_scout_prices", "poe2scout_fallback_error.json"),
            (
                "poe2db-economy",
                "build_poe2db_economy_prices",
                "poe2db_economy_fallback_error.json",
            ),
        ):
            with self.subTest(source=source), TemporaryDirectory() as tmp:
                out_dir = Path(tmp)
                tc_baseitems = out_dir / "tc.datc64"
                tc_baseitems.write_bytes(b"baseitems")

                with patch.object(
                    self.price_patch, "load_localized_base_item_pairs", return_value=[]
                ), patch.object(
                    self.price_patch, "fetch_poecurrency_summary", return_value=summary
                ), patch.object(
                    self.price_patch, function_name, side_effect=RuntimeError("blocked")
                ):
                    rc = self.price_patch.main(
                        [
                            "--price-source",
                            "poecurrency-cn",
                            "--cn-reference-source",
                            source,
                            "--patch-scope",
                            "currency",
                            "--fallback-price-sources",
                            "none",
                            "--no-build-patch",
                            "--no-uniques",
                            "--out-dir",
                            str(out_dir),
                            "--en-baseitems",
                            str(out_dir / "missing_en.datc64"),
                            "--tc-baseitems",
                            str(tc_baseitems),
                        ]
                    )

                self.assertEqual(rc, 0)
                summary_json = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
                self.assertEqual(summary_json["cn_reference_status"], "failed")
                self.assertEqual(len(summary_json["cn_reference_warnings"]), 1)
                self.assertIn(source, summary_json["cn_reference_warnings"][0])
                self.assertTrue((out_dir / error_file).exists())

    def test_international_primary_failure_uses_poe_ninja_fallback(self):
        pairs = [
            self.price_patch.BaseItemPair(
                "Metadata/Items/Currency/CurrencyMirror",
                "Mirror of Kalandra",
                "卡兰德的魔镜",
            )
        ]
        fallback_prices = {
            "divine": self.price_patch.PriceObservation(
                api_id="divine",
                en_name="Divine Orb",
                category="currency",
                price_exalted=Decimal("400"),
                value_traded=Decimal("0"),
                source_pair="poe.ninja/core/rates",
            ),
            "exalted": self.price_patch.PriceObservation(
                api_id="exalted",
                en_name="Exalted Orb",
                category="currency",
                price_exalted=Decimal("1"),
                value_traded=Decimal("0"),
                source_pair="poe.ninja/core/rates",
            ),
            "mirror": self.price_patch.PriceObservation(
                api_id="mirror",
                en_name="Mirror of Kalandra",
                category="currency",
                price_exalted=Decimal("1800000"),
                value_traded=Decimal("2"),
                source_pair="poe.ninja/Mirror of Kalandra",
            ),
        }

        with TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            with patch.object(self.price_patch, "load_base_item_pairs", return_value=pairs), patch.object(
                self.price_patch, "build_scout_prices", side_effect=RuntimeError("blocked")
            ), patch.object(
                self.price_patch,
                "build_poe_ninja_currency_prices",
                return_value=({"source": "poe-ninja"}, fallback_prices),
            ):
                rc = self.price_patch.main(
                    [
                        "--patch-scope",
                        "currency",
                        "--fallback-price-sources",
                        "poe-ninja",
                        "--no-build-patch",
                        "--no-uniques",
                        "--out-dir",
                        str(out_dir),
                        "--en-baseitems",
                        str(out_dir / "en.datc64"),
                        "--tc-baseitems",
                        str(out_dir / "tc.datc64"),
                    ]
                )

            self.assertEqual(rc, 0)
            summary_json = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary_json["primary_source_status"], "failed")
            self.assertEqual(summary_json["base_currency"], "poe.ninja")
            self.assertEqual(summary_json["fallback_status"]["poe-ninja"], "ok")
            self.assertEqual(summary_json["matched_items"], 1)
            self.assertEqual(summary_json["fallback_matched_items"], 0)
            rows = list((out_dir / "matched_prices_detail.csv").read_text(encoding="utf-8-sig").splitlines())
            self.assertTrue(any("卡兰德的魔镜" in row and "poe.ninja" in row for row in rows))

    def test_international_primary_and_poe_ninja_prices_are_merged_before_matching(self):
        pairs = [
            self.price_patch.BaseItemPair(
                "Metadata/Items/Currency/CurrencyMirror",
                "Mirror of Kalandra",
                "Mirror CN",
            ),
            self.price_patch.BaseItemPair(
                "Metadata/Items/Currency/AdeptRune",
                "Adept Rune",
                "Adept Rune CN",
            ),
        ]
        scout_prices = {
            "divine": self.price_patch.PriceObservation(
                api_id="divine",
                en_name="Divine Orb",
                category="currency",
                price_exalted=Decimal("400"),
                value_traded=Decimal("0"),
                source_pair="poe2scout/divine",
            ),
            "exalted": self.price_patch.PriceObservation(
                api_id="exalted",
                en_name="Exalted Orb",
                category="currency",
                price_exalted=Decimal("1"),
                value_traded=Decimal("0"),
                source_pair="poe2scout/exalted",
            ),
            "mirror": self.price_patch.PriceObservation(
                api_id="mirror",
                en_name="Mirror of Kalandra",
                category="currency",
                price_exalted=Decimal("1600000"),
                value_traded=Decimal("100"),
                source_pair="poe2scout/Mirror of Kalandra",
            ),
        }
        poe_ninja_prices = {
            "divine": self.price_patch.PriceObservation(
                api_id="divine",
                en_name="Divine Orb",
                category="currency",
                price_exalted=Decimal("400"),
                value_traded=Decimal("0"),
                source_pair="poe.ninja/core/rates",
            ),
            "exalted": self.price_patch.PriceObservation(
                api_id="exalted",
                en_name="Exalted Orb",
                category="currency",
                price_exalted=Decimal("1"),
                value_traded=Decimal("0"),
                source_pair="poe.ninja/core/rates",
            ),
            "mirror-poe-ninja": self.price_patch.PriceObservation(
                api_id="mirror-poe-ninja",
                en_name="Mirror of Kalandra",
                category="currency",
                price_exalted=Decimal("1800000"),
                value_traded=Decimal("2"),
                source_pair="poe.ninja/Mirror of Kalandra",
            ),
            "adept-rune": self.price_patch.PriceObservation(
                api_id="adept-rune",
                en_name="Adept Rune",
                category="Runes",
                price_exalted=Decimal("4"),
                value_traded=Decimal("1"),
                source_pair="poe.ninja/Runes/Adept Rune",
            ),
        }

        with TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            with patch.object(self.price_patch, "load_base_item_pairs", return_value=pairs), patch.object(
                self.price_patch,
                "build_scout_prices",
                return_value=(
                    {"exchange_snapshot": {"Epoch": 123, "BaseCurrencyText": "Exalted Orb"}},
                    scout_prices,
                    [],
                    [],
                ),
            ), patch.object(
                self.price_patch,
                "build_poe_ninja_currency_prices",
                return_value=({"source": "poe-ninja"}, poe_ninja_prices),
            ), patch.object(
                self.price_patch,
                "build_poe2db_economy_prices",
                side_effect=AssertionError("poe2db should not be fetched"),
            ):
                rc = self.price_patch.main(
                    [
                        "--patch-scope",
                        "currency",
                        "--fallback-price-sources",
                        "poe-ninja,poe2db-economy",
                        "--no-build-patch",
                        "--no-uniques",
                        "--out-dir",
                        str(out_dir),
                        "--en-baseitems",
                        str(out_dir / "en.datc64"),
                        "--tc-baseitems",
                        str(out_dir / "tc.datc64"),
                    ]
                )

            self.assertEqual(rc, 0)
            summary_json = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary_json["base_currency"], "poe2scout+poe.ninja")
            self.assertEqual(summary_json["price_items"], 4)
            self.assertEqual(summary_json["fallback_matched_items"], 0)
            rows = (out_dir / "matched_prices_detail.csv").read_text(encoding="utf-8-sig")
            self.assertIn("Adept Rune CN", rows)
            self.assertIn("poe.ninja/Runes/Adept Rune", rows)
            self.assertIn("poe2scout/Mirror of Kalandra", rows)
            self.assertNotIn("poe.ninja/Mirror of Kalandra", rows)

    def test_cn_reference_failure_uses_next_fallback_source(self):
        summary = [
            {
                "category_label": "通货仓库",
                "items": [
                    {"item_name": "神圣石", "latest_buy1": 300, "currency_unit": "e"},
                    {"item_name": "卡兰德的魔镜", "latest_buy1": 1, "currency_unit": "e"},
                ],
            }
        ]
        pairs = [
            self.price_patch.BaseItemPair(
                "Metadata/Items/Currency/CurrencyMirror",
                "Mirror of Kalandra",
                "卡兰德的魔镜",
            )
        ]
        poe_ninja_prices = {
            "divine": self.price_patch.PriceObservation(
                api_id="divine",
                en_name="Divine Orb",
                category="currency",
                price_exalted=Decimal("400"),
                value_traded=Decimal("0"),
                source_pair="poe.ninja/core/rates",
            ),
            "exalted": self.price_patch.PriceObservation(
                api_id="exalted",
                en_name="Exalted Orb",
                category="currency",
                price_exalted=Decimal("1"),
                value_traded=Decimal("0"),
                source_pair="poe.ninja/core/rates",
            ),
            "mirror": self.price_patch.PriceObservation(
                api_id="mirror",
                en_name="Mirror of Kalandra",
                category="currency",
                price_exalted=Decimal("1800000"),
                value_traded=Decimal("2"),
                source_pair="poe.ninja/Mirror of Kalandra",
            ),
        }

        with TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            tc_baseitems = out_dir / "tc.datc64"
            en_baseitems = out_dir / "en.datc64"
            en_baseitems.write_bytes(b"baseitems")
            tc_baseitems.write_bytes(b"baseitems")
            with patch.object(self.price_patch, "load_base_item_pairs", return_value=pairs), patch.object(
                self.price_patch, "fetch_poecurrency_summary", return_value=summary
            ), patch.object(
                self.price_patch, "build_scout_prices", side_effect=RuntimeError("blocked")
            ), patch.object(
                self.price_patch,
                "build_poe_ninja_currency_prices",
                return_value=({"source": "poe-ninja"}, poe_ninja_prices),
            ):
                rc = self.price_patch.main(
                    [
                        "--price-source",
                        "poecurrency-cn",
                        "--cn-reference-source",
                        "poe2scout",
                        "--fallback-price-sources",
                        "poe-ninja",
                        "--patch-scope",
                        "currency",
                        "--no-build-patch",
                        "--no-uniques",
                        "--out-dir",
                        str(out_dir),
                        "--en-baseitems",
                        str(en_baseitems),
                        "--tc-baseitems",
                        str(tc_baseitems),
                    ]
                )

            self.assertEqual(rc, 0)
            summary_json = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary_json["cn_reference_status"], "degraded")
            self.assertEqual(summary_json["fallback_status"]["poe2scout"], "failed")
            self.assertEqual(summary_json["fallback_status"]["poe-ninja"], "ok")
            self.assertEqual(summary_json["high_value_reference_items"], 1)


if __name__ == "__main__":
    unittest.main()
