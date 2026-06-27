import importlib.util
import struct
import sys
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "物价补丁" / "tools" / "poe2_island_rumour_patch.py"


def load_module():
    spec = importlib.util.spec_from_file_location("island_rumour_patch", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


EN_RUMOURS = [
    "All that glitters...",
    "Almost paradise.",
    "Reflective waters...",
    "A good fellow...",
    "Crazed Chieftain...",
    "Somethin' fishy...",
    "End of the circle...",
    "The last to fall...",
    "Stardrinker...",
    "Origin of the fall...",
    "Nothin' to drink...",
    "Unknown ruins...",
    "It's dry at least...",
    "Fallen stars...",
    "Endless cliffs...",
    "Warm but risky...",
    "Bleak and awful...",
    "Wild roaming free...",
    "Cold as ice...",
    "Sulphite!",
]


TC_RUMOURS = [
    "閃光的未必是金……",
    "近乎天堂。",
    "映照水域……",
    "好人一個……",
    "瘋狂酋長……",
    "有點可疑……",
    "圓環的終點……",
    "最後倒下者……",
    "飲星者……",
    "墮落的起源……",
    "沒東西可喝……",
    "未知的遺跡……",
    "至少很乾燥……",
    "殞落群星……",
    "無盡懸崖……",
    "溫暖但危險……",
    "荒涼又糟糕……",
    "野性自由遊蕩……",
    "冷如寒冰……",
    "硫酸！",
]


SC_RUMOURS = [
    "闪光的未必是金……",
    "近乎天堂。",
    "映照水域……",
    "好人一个……",
    "疯狂酋长……",
    "有点可疑……",
    "循环的尽头……",
    "最后倒下者……",
    "饮星者……",
    "堕落的起源……",
    "没东西可喝……",
    "未知的遗迹……",
    "至少很干燥……",
    "陨落群星……",
    "无尽悬崖……",
    "温暖但危险……",
    "荒凉又糟糕……",
    "野性自由游荡……",
    "冷如寒冰……",
    "硫酸！",
]


def make_endgame_maps_dat(module, rumours):
    row_count = 173
    row_size = 239
    string_base = 4 + row_count * row_size
    rows = bytearray(b"\x00" * (row_count * row_size))
    strings = bytearray()

    for map_index, text in enumerate(rumours):
        if len(strings) % 2:
            strings.append(0)
        offset = len(strings)
        row_index = module.RUMOUR_ROWS[map_index]
        pointer_pos = row_index * row_size + module.RUMOUR_TEXT_OFFSET
        struct.pack_into("<I", rows, pointer_pos, offset)
        strings.extend(text.encode("utf-16-le"))
        strings.extend(b"\x00\x00\x00\x00")

    assert len(rows) + 4 == string_base
    return struct.pack("<I", row_count) + bytes(rows) + bytes(strings)


def read_rumour(module, data, map_index):
    layout, entries = module.scan_rumours(data)
    by_index = {entry.map_index: entry for entry in entries}
    return by_index[map_index].text


class IslandRumourPatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_build_patch_adds_english_island_hint(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "endgamemaps.datc64"
            output_zip = root / "patch.zip"
            source.write_bytes(make_endgame_maps_dat(self.module, EN_RUMOURS))

            self.module.build_patch(
                source=source,
                output_zip=output_zip,
                patched_dat=None,
                game_path="data/balance/endgamemaps.datc64",
                report=None,
            )

            with zipfile.ZipFile(output_zip, "r") as zf:
                patched = zf.read("data/balance/endgamemaps.datc64")
            self.assertEqual(
                read_rumour(self.module, patched, 5),
                "Somethin' fishy...(Barren Atoll)",
            )
            self.assertEqual(
                read_rumour(self.module, patched, 0),
                "All that glitters...(Castaway/Gold)",
            )

    def test_build_patch_is_idempotent(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "endgamemaps.datc64"
            output_zip = root / "patch.zip"
            patched_dat = root / "patched.datc64"
            source.write_bytes(make_endgame_maps_dat(self.module, EN_RUMOURS))

            self.module.build_patch(
                source=source,
                output_zip=output_zip,
                patched_dat=patched_dat,
                game_path="data/balance/endgamemaps.datc64",
                report=None,
            )
            source.write_bytes(patched_dat.read_bytes())
            self.module.build_patch(
                source=source,
                output_zip=output_zip,
                patched_dat=patched_dat,
                game_path="data/balance/endgamemaps.datc64",
                report=None,
            )

            self.assertEqual(
                read_rumour(self.module, patched_dat.read_bytes(), 5),
                "Somethin' fishy...(Barren Atoll)",
            )

    def test_unknown_parenthetical_text_is_preserved(self):
        entries = [
            self.module.RumourEntry(
                map_index=0,
                row_index=self.module.RUMOUR_ROWS[0],
                text="A clue (uncertain)",
                text_offset=0,
                pointer_pos=0,
            )
        ]

        replacements, unchanged = self.module.build_replacements(entries, "en")

        self.assertEqual(len(unchanged), len(self.module.RUMOUR_ROWS) - 1)
        self.assertEqual(replacements[0].base_text, "A clue (uncertain)")
        self.assertEqual(replacements[0].new_text, "A clue (uncertain)(Castaway/Gold)")

    def test_traditional_chinese_special_hints_override_map_name(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "endgamemaps.datc64"
            output_zip = root / "patch.zip"
            source.write_bytes(make_endgame_maps_dat(self.module, TC_RUMOURS))

            self.module.build_patch(
                source=source,
                output_zip=output_zip,
                patched_dat=None,
                game_path="data/balance/traditional chinese/endgamemaps.datc64",
                report=None,
            )

            with zipfile.ZipFile(output_zip, "r") as zf:
                patched = zf.read("data/balance/traditional chinese/endgamemaps.datc64")
            self.assertEqual(
                read_rumour(self.module, patched, 8),
                "飲星者……(隱密神廟/烏特雷)",
            )
            self.assertEqual(
                read_rumour(self.module, patched, 0),
                "閃光的未必是金……(漂流者之所/金幣圖)",
            )
            self.assertEqual(
                read_rumour(self.module, patched, 1),
                "近乎天堂。(純淨樂園/經驗圖)",
            )
            self.assertEqual(
                read_rumour(self.module, patched, 2),
                "映照水域……(破裂迷湖/獨特基底裝備)",
            )
            self.assertEqual(
                read_rumour(self.module, patched, 3),
                "好人一個……(禪意時刻/傳奇裝備)",
            )
            self.assertEqual(
                read_rumour(self.module, patched, 4),
                "瘋狂酋長……(翠玉群島/首領戰)",
            )
            self.assertEqual(
                read_rumour(self.module, patched, 7),
                "最後倒下者……(哀泣崖壁/沃拉娜)",
            )
            self.assertEqual(
                read_rumour(self.module, patched, 6),
                "圓環的終點……(蔓延叢林/梅德偉)",
            )
            self.assertEqual(
                read_rumour(self.module, patched, 13),
                "殞落群星……(殞空荒原/八孔遺物)",
            )
            self.assertEqual(
                read_rumour(self.module, patched, 9),
                "墮落的起源……(幽隱島嶼/奥尔罗斯)",
            )

    def test_simplified_chinese_special_hints_include_boss(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "endgamemaps.datc64"
            output_zip = root / "patch.zip"
            source.write_bytes(make_endgame_maps_dat(self.module, SC_RUMOURS))

            self.module.build_patch(
                source=source,
                output_zip=output_zip,
                patched_dat=None,
                game_path="data/balance/simplified chinese/endgamemaps.datc64",
                report=None,
            )

            with zipfile.ZipFile(output_zip, "r") as zf:
                patched = zf.read("data/balance/simplified chinese/endgamemaps.datc64")
            self.assertEqual(
                read_rumour(self.module, patched, 6),
                "循环的尽头……(蔓生丛林/梅德维德)",
            )
            self.assertEqual(
                read_rumour(self.module, patched, 0),
                "闪光的未必是金……(颠沛领域/金币图)",
            )
            self.assertEqual(
                read_rumour(self.module, patched, 1),
                "近乎天堂。(纯净乐园/经验图)",
            )
            self.assertEqual(
                read_rumour(self.module, patched, 2),
                "映照水域……(千裂泽/独特基底装备)",
            )
            self.assertEqual(
                read_rumour(self.module, patched, 3),
                "好人一个……(顿悟时刻/传奇装备)",
            )
            self.assertEqual(
                read_rumour(self.module, patched, 4),
                "疯狂酋长……(青玉群岛/首领战)",
            )
            self.assertEqual(
                read_rumour(self.module, patched, 8),
                "饮星者……(静谧神庙/乌特雷)",
            )
            self.assertEqual(
                read_rumour(self.module, patched, 9),
                "堕落的起源……(无名之岛/奥尔罗斯)",
            )

    def test_simplified_chinese_official_rumour_aliases_include_boss(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "endgamemaps.datc64"
            output_zip = root / "patch.zip"
            rumours = list(SC_RUMOURS)
            rumours[7] = "最后一个倒下……"
            rumours[8] = "吞星者……"
            rumours[9] = "陨落的源头……"
            source.write_bytes(make_endgame_maps_dat(self.module, rumours))

            self.module.build_patch(
                source=source,
                output_zip=output_zip,
                patched_dat=None,
                game_path="data/balance/simplified chinese/endgamemaps.datc64",
                report=None,
            )

            with zipfile.ZipFile(output_zip, "r") as zf:
                patched = zf.read("data/balance/simplified chinese/endgamemaps.datc64")
            self.assertEqual(
                read_rumour(self.module, patched, 7),
                "最后一个倒下……(恸哭悬崖/沃拉娜)",
            )
            self.assertEqual(
                read_rumour(self.module, patched, 8),
                "吞星者……(静谧神庙/乌特雷)",
            )
            self.assertEqual(
                read_rumour(self.module, patched, 9),
                "陨落的源头……(无名之岛/奥尔罗斯)",
            )


if __name__ == "__main__":
    unittest.main()
