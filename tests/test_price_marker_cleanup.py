import importlib.util
import re
import struct
import sys
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "物价补丁" / "tools"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def clean_exile_next_title_line(text: str) -> str:
    """Mirror the active Exile Next TX trailing-bracket cleanup."""
    return re.sub(r"\[[^\]]*\]$", "", text).strip()


def clean_overlay_ii_title_line(text: str) -> str:
    """Mirror PoE Overlay II's shared raw and item-name cleanup stages."""
    unwrapped = re.sub(r"\[(?:[^|\]]*\|)?([^|\]]+)\]", r"\1", text)
    return re.sub(r"<<[^>]*>>", "", unwrapped).strip()


class PriceMarkerCleanupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.name_patch = load_module(
            "name_patch_cleanup", TOOLS / "poe2_name_price_patch.py"
        )
        cls.price_patch = load_module(
            "price_patch_cleanup", TOOLS / "build_poe2scout_price_patch.py"
        )
        cls.poe1_price_patch = load_module(
            "poe1_price_patch_cleanup", TOOLS / "build_poe1_price_patch.py"
        )

    def test_base_item_cleanup_only_removes_price_suffix(self):
        strip = self.name_patch.strip_existing_price_suffix
        self.assertEqual(strip("卡兰德的魔镜=12D", "="), "卡兰德的魔镜")
        self.assertEqual(strip("低价物品=<1E", "="), "低价物品")
        self.assertEqual(strip("A=大功能名", "="), "A=大功能名")

    def test_build_replacements_refreshes_and_cleans_stale_prices(self):
        BaseItemName = self.name_patch.BaseItemName
        entries = [
            BaseItemName(0, "Metadata/Items/A", "卡兰德的魔镜=12D", 0, 100, 0, 20),
            BaseItemName(1, "Metadata/Items/B", "过期物品=3E", 20, 104, 20, 40),
            BaseItemName(2, "Metadata/Items/C", "A=大功能名", 40, 108, 40, 60),
        ]
        rows = [{"metadata_path": "Metadata/Items/A", "price": "15D"}]

        replacements, warnings = self.name_patch.build_replacements(
            entries=entries,
            price_rows=rows,
            separator="=",
            keep_existing_price=True,
            mode="append",
            patch_same_name_duplicates=True,
        )

        by_row = {item.row_index: item.fitted_name for item in replacements}
        self.assertEqual(warnings, [])
        self.assertEqual(by_row[0], "卡兰德的魔镜=15D")
        self.assertEqual(by_row[1], "过期物品")
        self.assertNotIn(2, by_row)

    def test_degraded_partial_match_preserves_unmatched_existing_prices(self):
        BaseItemName = self.name_patch.BaseItemName
        entries = [
            BaseItemName(0, "Metadata/Items/A", "已命中=12D", 0, 100, 0, 20),
            BaseItemName(1, "Metadata/Items/B", "未命中=3E", 20, 104, 20, 40),
        ]
        replacements, warnings = self.name_patch.build_replacements(
            entries=entries,
            price_rows=[{"metadata_path": "Metadata/Items/A", "price": "15D"}],
            separator="=",
            keep_existing_price=True,
            mode="append",
            patch_same_name_duplicates=True,
            preserve_unmatched_existing_price=True,
        )

        self.assertEqual(warnings, [])
        self.assertEqual(
            {item.row_index: item.fitted_name for item in replacements},
            {0: "已命中=15D"},
        )

    def test_metadata_paths_do_not_collapse_distinct_same_name_items(self):
        BaseItemName = self.name_patch.BaseItemName
        entries = [
            BaseItemName(0, "Metadata/Items/A", "同名物品", 0, 100, 0, 20),
            BaseItemName(1, "Metadata/Items/B", "同名物品", 20, 104, 20, 40),
        ]
        rows = [
            {"metadata_path": "Metadata/Items/A", "price": "1D"},
            {"metadata_path": "Metadata/Items/B", "price": "2D"},
        ]

        replacements, warnings = self.name_patch.build_replacements(
            entries=entries,
            price_rows=rows,
            separator="=",
            keep_existing_price=True,
            mode="append",
            patch_same_name_duplicates=True,
        )

        self.assertEqual(warnings, [])
        self.assertEqual(
            {item.metadata_path: item.fitted_name for item in replacements},
            {
                "Metadata/Items/A": "同名物品=1D",
                "Metadata/Items/B": "同名物品=2D",
            },
        )

    def test_zero_replacements_replace_stale_zip_with_clean_current_data(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "baseitemtypes.datc64"
            prices = root / "prices.csv"
            output_zip = root / "物价补丁.zip"
            patched_dat = root / "baseitemtypes.patched.datc64"
            report = root / "report.json"
            source.write_bytes(b"current clean dat")
            prices.write_text("metadata_path,name,price\n", encoding="utf-8")
            with zipfile.ZipFile(output_zip, "w") as archive:
                archive.writestr(
                    "data/balance/baseitemtypes.datc64",
                    b"stale priced dat from the previous run",
                )

            with patch.object(self.name_patch, "scan_base_item_names", return_value=[]):
                self.name_patch.build_patch(
                    source=source,
                    prices=prices,
                    output_zip=output_zip,
                    patched_dat=patched_dat,
                    game_path="data/balance/baseitemtypes.datc64",
                    separator="=",
                    keep_existing_price=True,
                    mode="append",
                    patch_same_name_duplicates=True,
                    report=report,
                )

            self.assertTrue(output_zip.exists())
            with zipfile.ZipFile(output_zip) as archive:
                self.assertEqual(
                    archive.read("data/balance/baseitemtypes.datc64"),
                    source.read_bytes(),
                )
            self.assertEqual(patched_dat.read_bytes(), source.read_bytes())

    def test_unique_price_cleanup_accepts_all_generated_forms(self):
        strip = self.price_patch.strip_existing_price
        self.assertEqual(strip("[12D|卡兰德的魔镜]"), "卡兰德的魔镜")
        self.assertEqual(strip("[<1E|低价传奇]"), "低价传奇")
        self.assertEqual(strip("冈姆的壮志[<<0.25D>>]"), "冈姆的壮志")
        self.assertEqual(strip("低价传奇[<<<1D>>]"), "低价传奇")
        self.assertEqual(strip("传奇名\n[12.5D]"), "传奇名")
        self.assertEqual(strip("传奇名<<[<1D]>>"), "传奇名")
        self.assertEqual(strip("普通名=不是价格"), "普通名=不是价格")
        self.assertEqual(strip(" 前导空格"), " 前导空格")

    def test_poe1_and_poe2_default_to_compat_unique_price_labels(self):
        self.assertEqual(
            self.price_patch.DEFAULT_UNIQUE_PRICE_LABEL_MODE,
            "compat",
        )
        self.assertEqual(
            self.price_patch.UNIQUE_PRICE_LABEL_MODES,
            ("compat", "markup", "overlay", "newline", "off"),
        )
        self.assertEqual(
            self.price_patch.parse_args([]).unique_price_label_mode,
            "compat",
        )
        self.assertEqual(
            self.poe1_price_patch.parse_args([]).unique_price_label_mode,
            "compat",
        )

    def test_compat_unique_price_labels_survive_supported_query_cleaners(self):
        cases = (
            ("冈姆的壮志", "0.25D"),
            ("三龙战纪", "1.00E"),
            ("低价传奇", "<1D"),
        )
        for base_name, price in cases:
            with self.subTest(base_name=base_name, price=price):
                label = self.price_patch.format_unique_price_name(
                    base_name,
                    price,
                    "compat",
                )
                self.assertEqual(label, f"{base_name}[<<{price}>>]")
                self.assertEqual(clean_exile_next_title_line(label), base_name)
                self.assertEqual(clean_overlay_ii_title_line(label), base_name)

        # The old whole-line markup explains the base-type fallback regression:
        # Exile Next TX removes the entire line and leaves an empty unique name.
        self.assertEqual(clean_exile_next_title_line("[0.25D|冈姆的壮志]"), "")

    def test_full_word_cleanup_does_not_need_unique_gold_prices(self):
        WordEntry = self.price_patch.WordEntry
        layout = self.price_patch.DatLayout(row_count=4, row_size=64, string_base=260)
        entries = {
            0: WordEntry(0, "Unique A", "[12D|传奇甲]", 0, 48),
            1: WordEntry(1, "Unique B", "传奇乙<<[<1D]>>", 20, 112),
            2: WordEntry(2, "Unique C", "传奇丙[<<2.5D>>]", 40, 176),
            3: WordEntry(3, "普通名", "普通名", 60, 240),
        }
        captured: list[tuple[int, str]] = []

        with patch.object(self.price_patch, "detect_words_layout", return_value=layout), patch.object(
            self.price_patch, "read_words_row", side_effect=lambda _data, _layout, row: entries.get(row)
        ), patch.object(
            self.price_patch, "set_words_display_name", side_effect=lambda _output, _layout, entry, text: captured.append((entry.row_index, text))
        ):
            with TemporaryDirectory() as tmp:
                source = Path(tmp) / "words.datc64"
                patched = Path(tmp) / "patched.datc64"
                source.write_bytes(b"placeholder")

                rows = self.price_patch.clean_word_price_labels_file(source, patched)

        self.assertEqual(
            captured,
            [(0, "传奇甲"), (1, "传奇乙"), (2, "传奇丙")],
        )
        self.assertEqual(
            [row["status"] for row in rows],
            ["cleaned", "cleaned", "cleaned"],
        )

    def test_clean_word_noop_still_writes_a_complete_output(self):
        module = self.price_patch
        layout_base = 4 + module.WORDS_ROW_SIZE
        data = bytearray(layout_base)
        struct.pack_into("<I", data, 0, 1)

        def append_string(text: str) -> int:
            offset = len(data) - layout_base
            data.extend(text.encode("utf-16-le"))
            data.extend(b"\x00\x00\x00\x00")
            return offset

        en_offset = append_string("Unique A")
        display_offset = append_string("传奇甲")
        struct.pack_into("<I", data, 4 + module.WORDS_EN_NAME_OFFSET, en_offset)
        struct.pack_into(
            "<I", data, 4 + module.WORDS_DISPLAY_NAME_OFFSET, display_offset
        )
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "words.datc64"
            output = Path(tmp) / "words.clean.datc64"
            source.write_bytes(data)

            rows = module.clean_word_price_labels_file(source, output)

            self.assertEqual(rows, [])
            self.assertTrue(output.exists())
            self.assertEqual(output.read_bytes(), source.read_bytes())

    def test_words_game_path_derivation_is_case_insensitive(self):
        self.assertEqual(
            self.price_patch.derive_words_game_path(
                "Data/Balance/Traditional Chinese/BaseItemTypes.datc64"
            ),
            "Data/Balance/Traditional Chinese/words.datc64",
        )
        self.assertEqual(
            self.price_patch.derive_words_game_path("data/balance/not-base-items.datc64"),
            "",
        )

    def test_zero_local_matches_are_rejected_but_small_partial_sets_degrade(self):
        pair = self.price_patch.BaseItemPair("Metadata/Items/A", "A", "甲")
        with self.assertRaisesRegex(ValueError, "zero matches"):
            self.price_patch.evaluate_local_match_gate([], [pair], enabled=True)
        result = self.price_patch.evaluate_local_match_gate(
            [{"metadata_path": "Metadata/Items/A"}], [pair], enabled=True
        )
        self.assertEqual(result["state"], "degraded")
        self.assertGreater(result["ratio"], 0)

    def test_words_probe_ignores_orphaned_marker_bytes_after_cleanup(self):
        module = self.price_patch
        layout_base = 4 + module.WORDS_ROW_SIZE
        data = bytearray(layout_base)
        struct.pack_into("<I", data, 0, 1)

        def append_string(text: str) -> int:
            offset = len(data) - layout_base
            data.extend(text.encode("utf-16-le"))
            data.extend(b"\x00\x00\x00\x00")
            return offset

        en_offset = append_string("Unique A")
        display_offset = append_string("[12D|传奇甲]")
        struct.pack_into("<I", data, 4 + module.WORDS_EN_NAME_OFFSET, en_offset)
        struct.pack_into(
            "<I", data, 4 + module.WORDS_DISPLAY_NAME_OFFSET, display_offset
        )
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "words.datc64"
            cleaned = Path(tmp) / "words.clean.datc64"
            source.write_bytes(data)

            rows = module.clean_word_price_labels_file(source, cleaned)

            self.assertEqual(len(rows), 1)
            self.assertFalse(module.words_look_price_patched(cleaned))
            self.assertIn(
                "[12D|传奇甲]",
                cleaned.read_bytes().decode("utf-16-le", errors="ignore"),
            )

    def test_words_probe_detects_legacy_equals_price_label(self):
        module = self.price_patch
        layout_base = 4 + module.WORDS_ROW_SIZE
        data = bytearray(layout_base)
        struct.pack_into("<I", data, 0, 1)

        def append_string(text: str) -> int:
            offset = len(data) - layout_base
            data.extend(text.encode("utf-16-le"))
            data.extend(b"\x00\x00\x00\x00")
            return offset

        en_offset = append_string("Unique A")
        display_offset = append_string("传奇甲=12D")
        struct.pack_into("<I", data, 4 + module.WORDS_EN_NAME_OFFSET, en_offset)
        struct.pack_into(
            "<I", data, 4 + module.WORDS_DISPLAY_NAME_OFFSET, display_offset
        )

        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "legacy-words.datc64"
            source.write_bytes(data)
            self.assertTrue(module.words_look_price_patched(source))

    def test_words_probe_rejects_layout_with_no_readable_rows(self):
        with TemporaryDirectory() as tmp:
            broken = Path(tmp) / "broken-words.datc64"
            data = bytearray(2048)
            struct.pack_into("<I", data, 0, 1)
            broken.write_bytes(data)

            with self.assertRaisesRegex(ValueError, "live-row scan is incomplete"):
                self.price_patch.words_look_price_patched(broken)

    def test_words_probe_rejects_partially_readable_layout(self):
        module = self.price_patch
        layout_base = 4 + 2 * module.WORDS_ROW_SIZE
        data = bytearray(layout_base)
        struct.pack_into("<I", data, 0, 2)

        def append_string(text: str) -> int:
            offset = len(data) - layout_base
            data.extend(text.encode("utf-16-le"))
            data.extend(b"\x00\x00\x00\x00")
            return offset

        en_offset = append_string("Unique A")
        display_offset = append_string("传奇甲")
        struct.pack_into("<I", data, 4 + module.WORDS_EN_NAME_OFFSET, en_offset)
        struct.pack_into(
            "<I", data, 4 + module.WORDS_DISPLAY_NAME_OFFSET, display_offset
        )
        struct.pack_into(
            "<I",
            data,
            4 + module.WORDS_ROW_SIZE + module.WORDS_EN_NAME_OFFSET,
            0xFFFFFFF0,
        )

        with TemporaryDirectory() as tmp:
            broken = Path(tmp) / "partially-readable-words.datc64"
            broken.write_bytes(data)
            with self.assertRaisesRegex(ValueError, "readable=1, minimum=2"):
                module.words_look_price_patched(broken)


if __name__ == "__main__":
    unittest.main()
