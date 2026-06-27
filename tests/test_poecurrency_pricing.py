import importlib.util
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
                return_value=({"exchange_snapshot": {}}, {}, [], []),
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
                return_value=({"exchange_snapshot": {}}, {}, [], []),
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


if __name__ == "__main__":
    unittest.main()
