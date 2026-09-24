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
                "Somethin' fishy...(B Barren Atoll)",
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
                "Somethin' fishy...(B Barren Atoll)",
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

    def test_unknown_slash_parenthetical_text_is_preserved(self):
        entries = [
            self.module.RumourEntry(
                map_index=0,
                row_index=self.module.RUMOUR_ROWS[0],
                text="A clue (other/mod)",
                text_offset=0,
                pointer_pos=0,
            )
        ]

        replacements, unchanged = self.module.build_replacements(entries, "en")

        self.assertEqual(len(unchanged), len(self.module.RUMOUR_ROWS) - 1)
        self.assertEqual(replacements[0].base_text, "A clue (other/mod)")
        self.assertEqual(replacements[0].new_text, "A clue (other/mod)(Castaway/Gold)")

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
                "飲星者……(C級隱密神廟/烏特雷)",
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
                "瘋狂酋長……(C級翠玉群島/首領戰)",
            )
            self.assertEqual(
                read_rumour(self.module, patched, 7),
                "最後倒下者……(C級哀泣崖壁/沃拉娜)",
            )
            self.assertEqual(
                read_rumour(self.module, patched, 6),
                "圓環的終點……(C級蔓延叢林/梅德偉)",
            )
            self.assertEqual(
                read_rumour(self.module, patched, 13),
                "殞落群星……(S級殞空荒原/八孔遺物)",
            )
            self.assertEqual(
                read_rumour(self.module, patched, 9),
                "墮落的起源……(C級幽隱島嶼/奧爾羅斯)",
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
                "循环的尽头……(C级蔓生丛林/梅德维德)",
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
                "疯狂酋长……(C级青玉群岛/首领战)",
            )
            self.assertEqual(
                read_rumour(self.module, patched, 8),
                "饮星者……(C级静谧神庙/乌特雷)",
            )
            self.assertEqual(
                read_rumour(self.module, patched, 9),
                "堕落的起源……(C级无名之岛/奥尔罗斯)",
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
            rumours[13] = "坠落的星辰……"
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
                "最后一个倒下……(C级恸哭悬崖/沃拉娜)",
            )
            self.assertEqual(
                read_rumour(self.module, patched, 8),
                "吞星者……(C级静谧神庙/乌特雷)",
            )
            self.assertEqual(
                read_rumour(self.module, patched, 9),
                "陨落的源头……(C级无名之岛/奥尔罗斯)",
            )
            self.assertEqual(
                read_rumour(self.module, patched, 13),
                "坠落的星辰……(S级天陨荒原/八孔遗物)",
            )

    def test_clean_patch_removes_existing_island_hints(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "endgamemaps.datc64"
            patched_dat = root / "patched.datc64"
            output_zip = root / "patch.zip"
            rumours = list(SC_RUMOURS)
            rumours[0] = "闪光的未必是金……(颠沛领域/金币图)"
            rumours[6] = "循环的尽头……(蔓生丛林/梅德维德)"
            source.write_bytes(make_endgame_maps_dat(self.module, rumours))

            self.module.clean_patch(
                source=source,
                output_zip=output_zip,
                patched_dat=patched_dat,
                game_path="data/balance/simplified chinese/endgamemaps.datc64",
                report=None,
            )

            with zipfile.ZipFile(output_zip, "r") as zf:
                patched = zf.read("data/balance/simplified chinese/endgamemaps.datc64")
            self.assertEqual(read_rumour(self.module, patched, 0), "闪光的未必是金……")
            self.assertEqual(read_rumour(self.module, patched, 6), "循环的尽头……")

    def test_chinese_ratings_upgrade_repeat_and_restore_all_twenty_rumours(self):
        expected_hints = [
            ("颠沛领域/金币图", "漂流者之所/金幣圖"),
            ("纯净乐园/经验图", "純淨樂園/經驗圖"),
            ("千裂泽/独特基底装备", "破裂迷湖/獨特基底裝備"),
            ("顿悟时刻/传奇装备", "禪意時刻/傳奇裝備"),
            ("C级青玉群岛/首领战", "C級翠玉群島/首領戰"),
            ("B级贫瘠环礁", "B級貧瘠環礁"),
            ("C级蔓生丛林/梅德维德", "C級蔓延叢林/梅德偉"),
            ("C级恸哭悬崖/沃拉娜", "C級哀泣崖壁/沃拉娜"),
            ("C级静谧神庙/乌特雷", "C級隱密神廟/烏特雷"),
            ("C级无名之岛/奥尔罗斯", "C級幽隱島嶼/奧爾羅斯"),
            ("A级死水盆地", "A級靜滯盆地"),
            ("B级掘尸遗迹", "B級廢棄挖掘場"),
            ("B级脱落沟壑", "B級滑塌溪谷"),
            ("S级天陨荒原/八孔遗物", "S級殞空荒原/八孔遺物"),
            ("A级乱石半岛", "A級崎嶇半島"),
            ("B级牧野荒原", "B級闊牧遼原"),
            ("B级褪色浅滩", "B級白化淺灘"),
            ("A级笼葱海岛", "A級蓊鬱群島"),
            ("A级凛风悬崖", "A級寒風峭壁"),
            ("B级焦灼小岛", "B級焦灼孤島"),
        ]
        for column, (locale, originals) in enumerate([
            ("simplified chinese", SC_RUMOURS),
            ("traditional chinese", TC_RUMOURS),
        ]):
            with self.subTest(locale=locale), TemporaryDirectory() as tmp:
                root = Path(tmp)
                source = root / "endgamemaps.datc64"
                output_zip = root / "patch.zip"
                game_path = f"data/balance/{locale}/endgamemaps.datc64"
                rumours = list(originals)
                if column == 0:
                    rumours[13] = "坠落的星辰……"
                hints = [pair[column] for pair in expected_hints]
                legacy_hints = [
                    hint[2:] if hint[0] in "SABC" else hint for hint in hints
                ]
                if column == 0:
                    legacy_hints[13] = "天陨荒原"  # Old official-CN alias bug.
                else:
                    legacy_hints[9] = "幽隱島嶼/奥尔罗斯"
                source.write_bytes(make_endgame_maps_dat(self.module, [
                    f"{text}({hint})" for text, hint in zip(rumours, legacy_hints)
                ]))
                with zipfile.ZipFile(output_zip, "w") as archive:
                    archive.writestr("other-layer.txt", b"preserve this layer")

                self.module.build_patch(source, output_zip, source, game_path, None)
                first_patch = source.read_bytes()
                _, entries = self.module.scan_rumours(first_patch)
                self.assertEqual([entry.text for entry in entries], [
                    f"{text}({hint})" for text, hint in zip(rumours, hints)
                ])
                status = self.module.get_patch_status(source, game_path)
                self.assertEqual(status["patched_count"], 20)
                self.assertEqual(status["expected_count"], 20)
                self.module.build_patch(source, output_zip, source, game_path, None)
                self.assertEqual(source.read_bytes(), first_patch)

                self.module.clean_patch(source, output_zip, source, game_path, None)
                _, entries = self.module.scan_rumours(source.read_bytes())
                self.assertEqual([entry.text for entry in entries], rumours)
                self.assertEqual(
                    self.module.get_patch_status(source, game_path)["patched_count"], 0
                )
                with zipfile.ZipFile(output_zip) as archive:
                    self.assertEqual(archive.read(game_path), source.read_bytes())
                    self.assertEqual(archive.read("other-layer.txt"), b"preserve this layer")

    def test_fallen_stars_reward_survives_unrecognized_chinese_translation(self):
        for language, expected in [
            ("zh-cn", "S级天陨荒原/八孔遗物"),
            ("zh-tw", "S級殞空荒原/八孔遺物"),
        ]:
            with self.subTest(language=language):
                self.assertEqual(
                    self.module.expected_hint(language, 13, "A revised translation..."),
                    expected,
                )


if __name__ == "__main__":
    unittest.main()
