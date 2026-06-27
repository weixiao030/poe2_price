#!/usr/bin/env python3
"""Build a PoE2 EndgameMaps.datc64 patch for island rumour hints."""

from __future__ import annotations

import argparse
import json
import os
import re
import struct
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


SCRIPT_DIR = Path(__file__).resolve().parent
PATCH_ROOT = SCRIPT_DIR.parent
DEFAULT_SOURCE = (
    PATCH_ROOT
    / "output"
    / "dat_files_latest"
    / "data"
    / "data_balance_simplified chinese_endgamemaps.datc64"
)
DEFAULT_GAME_PATH = "data/balance/simplified chinese/endgamemaps.datc64"

RUMOUR_TEXT_OFFSET = 227
RUMOUR_ROWS = (
    47,
    48,
    78,
    57,
    83,
    127,
    141,
    142,
    143,
    144,
    151,
    152,
    153,
    154,
    155,
    156,
    157,
    158,
    159,
    160,
)

ISLAND_HINTS = {
    "en": (
        "Castaway",
        "Untainted Paradise",
        "The Fractured Lake",
        "Moment of Zen",
        "The Jade Isles",
        "Barren Atoll",
        "Sprawling Jungle",
        "Mournful Cliffside",
        "Secluded Temple",
        "Obscure Island",
        "Stagnant Basin",
        "Exhumed Ruins",
        "Sloughed Gully",
        "Moor of Fallen Skies",
        "Craggy Peninsula",
        "Grazed Prairie",
        "Bleached Shoals",
        "Lush Isle",
        "Frigid Bluffs",
        "Scorched Cay",
    ),
    "zh-cn": (
        "颠沛领域",
        "纯净乐园",
        "千裂泽",
        "顿悟时刻",
        "青玉群岛",
        "贫瘠环礁",
        "蔓生丛林",
        "恸哭悬崖",
        "静谧神庙",
        "无名之岛",
        "死水盆地",
        "掘尸遗迹",
        "脱落沟壑",
        "天陨荒原",
        "乱石半岛",
        "牧野荒原",
        "褪色浅滩",
        "笼葱海岛",
        "凛风悬崖",
        "焦灼小岛",
    ),
    "zh-tw": (
        "漂流者之所",
        "純淨樂園",
        "破裂迷湖",
        "禪意時刻",
        "翠玉群島",
        "貧瘠環礁",
        "蔓延叢林",
        "哀泣崖壁",
        "隱密神廟",
        "幽隱島嶼",
        "靜滯盆地",
        "廢棄挖掘場",
        "滑塌溪谷",
        "殞空荒原",
        "崎嶇半島",
        "闊牧遼原",
        "白化淺灘",
        "蓊鬱群島",
        "寒風峭壁",
        "焦灼孤島",
    ),
    "ja": (
        "難破",
        "汚れなき楽園",
        "ひび割れた湖",
        "禅の刹那",
        "ヒスイの島",
        "荒れ果てた環礁",
        "広がるジャングル",
        "嘆きの崖",
        "孤立した寺院",
        "隠れた島",
        "淀んだ盆地",
        "掘り起こされた遺跡",
        "ぬかるんだ峡谷",
        "落ちたる空の原野",
        "岩だらけの半島",
        "放牧の大草原",
        "白化した浅瀬",
        "生い茂った島",
        "凍てついた断崖",
        "焼け焦げた小島",
    ),
    "ko": (
        "조난자",
        "때묻지 않은 낙원",
        "분열된 호수",
        "한 순간의 선",
        "비취 군도",
        "불모의 산호섬",
        "뻗어 가는 밀림",
        "음울한 낭떠러지",
        "외딴 사원",
        "후미진 섬",
        "고인 분지",
        "파헤쳐진 폐허",
        "진창이 된 고랑",
        "무너진 하늘의 황야",
        "바위투성이 반도",
        "풀이 뜯긴 프레리",
        "표백된 모래톱",
        "우거진 섬",
        "차디찬 절벽",
        "그을린 암초",
    ),
    "ru": (
        "Изгой",
        "Нетронутый рай",
        "Расколотое озеро",
        "Безмятежность",
        "Нефритовые острова",
        "Бесплодный риф",
        "Разросшиеся джунгли",
        "Скорбный утёс",
        "Уединённый храм",
        "Неясный остров",
        "Застойный водоём",
        "Разрытые руины",
        "Осыпавшийся овраг",
        "Причал Падших небес",
        "Скалистый мыс",
        "Травянистые прерии",
        "Выбеленная отмель",
        "Зелёный островок",
        "Холодные скалы",
        "Выжженный островок",
    ),
    "fr": (
        "Naufrage",
        "Paradis immaculé",
        "Le Lac fracturé",
        "Moment de quiétude",
        "Les Îles de Jade",
        "Atoll stérile",
        "Sprawling Jungle",
        "Mournful Cliffside",
        "Temple retiré",
        "Île obscure",
        "Bassin stagnant",
        "Excavation abandonnée",
        "Ravin érodé",
        "Lande des Cieux tombés",
        "Péninsule escarpée",
        "Prairie pâturée",
        "Bancs de sable blanchis",
        "Île luxuriante",
        "Falaises glaciales",
        "Îlot calciné",
    ),
    "de": (
        "Schiffbruch",
        "Unberührtes Paradies",
        "Der zerbrochene See",
        "Augenblick des Zen",
        "Die Jadeinseln",
        "Ödes Atoll",
        "Weitläufiger Dschungel",
        "Trostlose Steilküste",
        "Abgelegener Tempel",
        "Geheimnisvolle Insel",
        "Stagnierendes Becken",
        "Exhumierte Ruinen",
        "Abgetragene Schlucht",
        "Heide der Untergegangenen Himmel",
        "Zerklüftete Halbinsel",
        "Abgegraste Prärie",
        "Gebleichte Untiefen",
        "Üppige Insel",
        "Kalte Klippen",
        "Verbrannte Sandbank",
    ),
    "es": (
        "Naufragio",
        "Paraíso prístino",
        "El lago fracturado",
        "Momento zen",
        "Las islas de jade",
        "Atolón desierto",
        "Jungla expansiva",
        "Acantilado apenado",
        "Templo oculto",
        "Isla oscura",
        "Cuenca estancada",
        "Ruinas exhumadas",
        "Hondonada pantanosa",
        "Páramo del cielo caído",
        "Península escarpada",
        "Pradera erosionada",
        "Bajíos blanquecinos",
        "Isla frondosa",
        "Peñascos helados",
        "Cayo calcinado",
    ),
    "pt": (
        "Náufrago",
        "Paraíso Imaculado",
        "O Lago Rachado",
        "Momento Zen",
        "As Ilhas Jade",
        "Atoleiro Estéril",
        "Selva Extensa",
        "Encosta Melancólica",
        "Templo Isolado",
        "Ilha Obscura",
        "Bacia Estagnada",
        "Ruínas Exumadas",
        "Ravina Erodida",
        "Charneca dos Céus Caídos",
        "Península Escarpada",
        "Pradaria Pastoreada",
        "Bancos de Areia Descorados",
        "Ilha Viçosa",
        "Penhascos Frígidos",
        "Recife Queimado",
    ),
    "th": (
        "ซากเรืออับปาง",
        "เกาะสวรรค์ไร้มลทิน",
        "ทะเลสาบแตกร้าว",
        "ช่วงเวลาสงบเงียบ",
        "หมู่เกาะหยก",
        "เกาะวงแหวนแห้งแล้ง",
        "ป่าดงดิบกว้างไกล",
        "เชิงผาอาลัย",
        "วิหารสันโดษ",
        "เกาะลับแล",
        "ลุ่มน้ำขัง",
        "ซากที่ถูกขุดค้น",
        "ร่องธารโคลน",
        "ทุ่งโล่งนภาร่วง",
        "แหลมชะง่อน",
        "ทุ่งหญ้าเตียนโล่ง",
        "ดอนทรายซีดใต้น้ำ",
        "เกาะเขียวขจี",
        "ผาชันเยือกเย็น",
        "เกาะปริ่มน้ำร้อนระอุ",
    ),
}

SPECIAL_HINTS_BY_RUMOUR = {
    "吞星者……": "静谧神庙/乌特雷",
    "饮星者……": "静谧神庙/乌特雷",
    "最后一个倒下……": "恸哭悬崖/沃拉娜",
    "最后倒下者……": "恸哭悬崖/沃拉娜",
    "圆环的终点……": "蔓生丛林/梅德维德",
    "循环的尽头……": "蔓生丛林/梅德维德",
    "殒落群星……": "天陨荒原/八孔遗物",
    "陨落群星……": "天陨荒原/八孔遗物",
    "陨落的源头……": "无名之岛/奥尔罗斯",
    "堕落的起源……": "无名之岛/奥尔罗斯",
    "飲星者……": "隱密神廟/烏特雷",
    "最後倒下者……": "哀泣崖壁/沃拉娜",
    "圓環的終點……": "蔓延叢林/梅德偉",
    "殞落群星……": "殞空荒原/八孔遺物",
    "墮落的起源……": "幽隱島嶼/奥尔罗斯",
}

REWARD_HINT_LABELS = {
    "en": ("Gold", "Experience", "Unique Base Items", "Unique Items", "Boss Fight"),
    "zh-cn": ("金币图", "经验图", "独特基底装备", "传奇装备", "首领战"),
    "zh-tw": ("金幣圖", "經驗圖", "獨特基底裝備", "傳奇裝備", "首領戰"),
    "ja": ("ゴールド", "経験値", "ユニークベース装備", "ユニーク装備", "ボス戦"),
    "ko": ("골드", "경험치", "고유 베이스 장비", "고유 장비", "보스전"),
    "ru": ("золото", "опыт", "уникальные базы", "уникальные предметы", "босс"),
    "fr": ("or", "expérience", "bases uniques", "objets uniques", "boss"),
    "de": ("Gold", "Erfahrung", "einzigartige Basistypen", "einzigartige Gegenstände", "Bosskampf"),
    "es": ("oro", "experiencia", "bases únicas", "objetos únicos", "jefe"),
    "pt": ("ouro", "experiência", "bases únicas", "itens únicos", "chefe"),
    "th": ("ทอง", "ค่าประสบการณ์", "เบสยูนิค", "ไอเทมยูนิค", "บอส"),
}

SPECIAL_HINTS_BY_INDEX = {
    language_key: {
        map_index: f"{ISLAND_HINTS[language_key][map_index]}/{label}"
        for map_index, label in enumerate(labels)
    }
    for language_key, labels in REWARD_HINT_LABELS.items()
}

TRAILING_HINT_RE = re.compile(r"^(?P<base>.+?)\((?P<hint>[^()\r\n]+)\)$")
ALL_KNOWN_HINTS = {
    hint for hints in ISLAND_HINTS.values() for hint in hints
} | set(SPECIAL_HINTS_BY_RUMOUR.values()) | {
    hint for hints in SPECIAL_HINTS_BY_INDEX.values() for hint in hints.values()
}


@dataclass(frozen=True)
class DatLayout:
    row_count: int
    row_size: int
    string_base: int


@dataclass(frozen=True)
class RumourEntry:
    map_index: int
    row_index: int
    text: str
    text_offset: int
    pointer_pos: int


@dataclass(frozen=True)
class RumourReplacement:
    map_index: int
    row_index: int
    old_text: str
    base_text: str
    new_text: str
    hint: str
    old_string_offset: int
    pointer_pos: int


def read_utf16le_z(data: bytes, start: int, max_chars: int = 256) -> tuple[str, int]:
    chars: list[int] = []
    pos = start
    while pos + 1 < len(data) and len(chars) <= max_chars:
        code = data[pos] | (data[pos + 1] << 8)
        if code == 0:
            return "".join(chr(item) for item in chars), pos
        chars.append(code)
        pos += 2
    raise ValueError(f"unterminated UTF-16LE string at 0x{start:x}")


def is_sane_text(text: str) -> bool:
    if not text or len(text) > 80:
        return False
    if "\x00" in text or "\ufffd" in text:
        return False
    return not any(0xD800 <= ord(ch) <= 0xDFFF for ch in text)


def read_string_at_offset(data: bytes, layout: DatLayout, offset: int) -> str:
    if offset < 0 or offset % 2 != 0:
        raise ValueError(f"invalid string offset: 0x{offset:x}")
    absolute = layout.string_base + offset
    if absolute < layout.string_base or absolute + 1 >= len(data):
        raise ValueError(f"string offset out of range: 0x{offset:x}")
    text, _end = read_utf16le_z(data, absolute)
    if not is_sane_text(text):
        raise ValueError(f"invalid rumour text at 0x{absolute:x}")
    return text


def read_rumour_entry(
    data: bytes, layout: DatLayout, map_index: int
) -> RumourEntry | None:
    row_index = RUMOUR_ROWS[map_index]
    if row_index >= layout.row_count:
        return None
    pointer_pos = 4 + row_index * layout.row_size + RUMOUR_TEXT_OFFSET
    if pointer_pos + 4 > layout.string_base:
        return None
    text_offset = struct.unpack_from("<I", data, pointer_pos)[0]
    try:
        text = read_string_at_offset(data, layout, text_offset)
    except ValueError:
        return None
    return RumourEntry(
        map_index=map_index,
        row_index=row_index,
        text=text,
        text_offset=text_offset,
        pointer_pos=pointer_pos,
    )


def detect_endgame_maps_layout(data: bytes) -> DatLayout:
    if len(data) < 4096:
        raise ValueError("EndgameMaps.datc64 is too small")

    row_count = struct.unpack_from("<I", data, 0)[0]
    if row_count <= max(RUMOUR_ROWS):
        raise ValueError(f"unexpected EndgameMaps row count: {row_count}")

    best_layout: DatLayout | None = None
    best_score = -1
    for row_size in range(RUMOUR_TEXT_OFFSET + 4, 360):
        string_base = 4 + row_count * row_size
        if string_base >= len(data):
            continue
        layout = DatLayout(
            row_count=row_count, row_size=row_size, string_base=string_base
        )
        score = 0
        for map_index in range(len(RUMOUR_ROWS)):
            if read_rumour_entry(data, layout, map_index) is not None:
                score += 1
        if score > best_score:
            best_score = score
            best_layout = layout

    if best_layout is None or best_score < 10:
        raise ValueError("cannot detect EndgameMaps.datc64 row layout")
    return best_layout


def language_key_from_game_path(game_path: str) -> str:
    normalized = game_path.replace("\\", "/").lower()
    if "/traditional chinese/" in normalized:
        return "zh-tw"
    if "/simplified chinese/" in normalized:
        return "zh-cn"
    if "/japanese/" in normalized:
        return "ja"
    if "/korean/" in normalized:
        return "ko"
    if "/russian/" in normalized:
        return "ru"
    if "/french/" in normalized:
        return "fr"
    if "/german/" in normalized:
        return "de"
    if "/spanish/" in normalized:
        return "es"
    if "/portuguese/" in normalized:
        return "pt"
    if "/thai/" in normalized:
        return "th"
    return "en"


def strip_existing_hint(text: str) -> str:
    match = TRAILING_HINT_RE.match(text)
    if not match:
        return text
    hint = match.group("hint")
    if hint not in ALL_KNOWN_HINTS and "/" not in hint:
        return text
    return match.group("base")


def expected_hint(language_key: str, map_index: int, base_text: str) -> str:
    special = SPECIAL_HINTS_BY_RUMOUR.get(base_text)
    if special:
        return special
    special_by_index = SPECIAL_HINTS_BY_INDEX.get(language_key, {})
    if map_index in special_by_index:
        return special_by_index[map_index]
    hints = ISLAND_HINTS.get(language_key, ISLAND_HINTS["en"])
    return hints[map_index]


def scan_rumours(data: bytes) -> tuple[DatLayout, list[RumourEntry]]:
    layout = detect_endgame_maps_layout(data)
    entries: list[RumourEntry] = []
    for map_index in range(len(RUMOUR_ROWS)):
        entry = read_rumour_entry(data, layout, map_index)
        if entry is not None:
            entries.append(entry)
    return layout, entries


def build_replacements(
    entries: list[RumourEntry], language_key: str
) -> tuple[list[RumourReplacement], list[dict[str, object]]]:
    replacements: list[RumourReplacement] = []
    unchanged: list[dict[str, object]] = []
    seen_rows = {entry.row_index for entry in entries}

    for entry in entries:
        base_text = strip_existing_hint(entry.text)
        hint = expected_hint(language_key, entry.map_index, base_text)
        new_text = f"{base_text}({hint})"
        item = {
            "map_index": entry.map_index,
            "row_index": entry.row_index,
            "old_text": entry.text,
            "base_text": base_text,
            "new_text": new_text,
            "hint": hint,
        }
        if entry.text == new_text:
            unchanged.append(item)
            continue
        replacements.append(
            RumourReplacement(
                map_index=entry.map_index,
                row_index=entry.row_index,
                old_text=entry.text,
                base_text=base_text,
                new_text=new_text,
                hint=hint,
                old_string_offset=entry.text_offset,
                pointer_pos=entry.pointer_pos,
            )
        )

    for map_index, row_index in enumerate(RUMOUR_ROWS):
        if row_index not in seen_rows:
            unchanged.append(
                {
                    "map_index": map_index,
                    "row_index": row_index,
                    "old_text": "",
                    "base_text": "",
                    "new_text": "",
                    "hint": "",
                    "warning": "target rumour row was not readable",
                }
            )

    return replacements, unchanged


def append_utf16le_string(output: bytearray, layout: DatLayout, text: str) -> int:
    if (len(output) - layout.string_base) % 2:
        output.append(0)
    offset = len(output) - layout.string_base
    if offset <= 0 or offset > 0xFFFFFFFF:
        raise ValueError("appended string offset is out of uint32 range")
    output.extend(text.encode("utf-16-le"))
    output.extend(b"\x00\x00\x00\x00")
    return offset


def apply_replacements(
    data: bytes, layout: DatLayout, replacements: list[RumourReplacement]
) -> bytes:
    output = bytearray(data)
    appended_offsets: dict[str, int] = {}

    for replacement in sorted(replacements, key=lambda item: item.row_index):
        current_offset = struct.unpack_from("<I", output, replacement.pointer_pos)[0]
        if current_offset != replacement.old_string_offset:
            raise ValueError(
                f"rumour pointer changed for row {replacement.row_index}: "
                f"0x{current_offset:x} != 0x{replacement.old_string_offset:x}"
            )
        new_offset = appended_offsets.get(replacement.new_text)
        if new_offset is None:
            new_offset = append_utf16le_string(output, layout, replacement.new_text)
            appended_offsets[replacement.new_text] = new_offset
        struct.pack_into("<I", output, replacement.pointer_pos, new_offset)

    return bytes(output)


def has_known_hint(text: str) -> bool:
    match = TRAILING_HINT_RE.match(text)
    if not match:
        return False
    hint = match.group("hint")
    return hint in ALL_KNOWN_HINTS or "/" in hint


def get_patch_status(source: Path, game_path: str) -> dict[str, object]:
    data = source.read_bytes()
    layout, entries = scan_rumours(data)
    language_key = language_key_from_game_path(game_path)
    patched_count = 0
    expected_count = 0
    rows = []

    for entry in entries:
        base_text = strip_existing_hint(entry.text)
        hint = expected_hint(language_key, entry.map_index, base_text)
        expected_text = f"{base_text}({hint})"
        is_expected = entry.text == expected_text
        is_hinted = is_expected or has_known_hint(entry.text)
        if is_hinted:
            patched_count += 1
        if is_expected:
            expected_count += 1
        rows.append(
            {
                "map_index": entry.map_index,
                "row_index": entry.row_index,
                "text": entry.text,
                "base_text": base_text,
                "expected_text": expected_text,
                "patched": is_hinted,
                "expected": is_expected,
            }
        )

    return {
        "source": str(source),
        "game_path": game_path.replace("\\", "/"),
        "language": language_key,
        "layout": {
            "row_count": layout.row_count,
            "row_size": layout.row_size,
            "string_base": layout.string_base,
        },
        "readable_rumours": len(entries),
        "patched_count": patched_count,
        "expected_count": expected_count,
        "rows": rows,
    }


def upsert_zip_entry(zip_path: Path, entry_name: str, payload: bytes) -> None:
    entry_name = entry_name.replace("\\", "/")
    zip_path.parent.mkdir(parents=True, exist_ok=True)

    if not zip_path.exists():
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(entry_name, payload)
        return

    fd, temp_name = tempfile.mkstemp(
        prefix=f"{zip_path.stem}.", suffix=".zip", dir=str(zip_path.parent)
    )
    os.close(fd)
    Path(temp_name).unlink(missing_ok=True)
    try:
        with zipfile.ZipFile(zip_path, "r") as source, zipfile.ZipFile(
            temp_name, "w", compression=zipfile.ZIP_DEFLATED
        ) as target:
            for info in source.infolist():
                if info.filename.replace("\\", "/") == entry_name:
                    continue
                target.writestr(info, source.read(info.filename))
            target.writestr(entry_name, payload)
        Path(temp_name).replace(zip_path)
    finally:
        try:
            Path(temp_name).unlink()
        except FileNotFoundError:
            pass


def build_patch(
    source: Path,
    output_zip: Path,
    patched_dat: Path | None,
    game_path: str,
    report: Path | None,
) -> None:
    data = source.read_bytes()
    layout, entries = scan_rumours(data)
    language_key = language_key_from_game_path(game_path)
    replacements, unchanged = build_replacements(entries, language_key)

    patched = apply_replacements(data, layout, replacements)
    upsert_zip_entry(output_zip, game_path, patched)

    if patched_dat:
        patched_dat.parent.mkdir(parents=True, exist_ok=True)
        patched_dat.write_bytes(patched)

    info = {
        "source": str(source),
        "output_zip": str(output_zip),
        "game_path": game_path.replace("\\", "/"),
        "language": language_key,
        "layout": {
            "row_count": layout.row_count,
            "row_size": layout.row_size,
            "string_base": layout.string_base,
        },
        "source_size": len(data),
        "patched_size": len(patched),
        "size_delta": len(patched) - len(data),
        "readable_rumours": len(entries),
        "patched_rumours": len(replacements),
        "unchanged_rumours": len(unchanged),
        "replacements": [
            {
                "map_index": item.map_index,
                "row_index": item.row_index,
                "old_text": item.old_text,
                "base_text": item.base_text,
                "new_text": item.new_text,
                "hint": item.hint,
                "old_string_offset": f"0x{item.old_string_offset:x}",
                "pointer_offset": f"0x{item.pointer_pos:x}",
            }
            for item in replacements
        ],
        "unchanged": unchanged,
    }
    if report:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"island rumour hints: {len(replacements)} changed, {len(unchanged)} unchanged")
    print(f"language: {language_key}")
    print(f"dat size: {len(data)} -> {len(patched)}")
    print(f"written: {output_zip}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a PoE2 island rumour hint patch zip."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    build = sub.add_parser("build", help="add EndgameMaps.datc64 to a patch zip")
    build.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    build.add_argument("--output-zip", type=Path, default=Path("物价补丁.zip"))
    build.add_argument("--patched-dat", type=Path)
    build.add_argument("--game-path", default=DEFAULT_GAME_PATH)
    build.add_argument("--report", type=Path, default=Path("island_rumour_patch.report.json"))

    check = sub.add_parser("check", help="report whether a datc64 already has hints")
    check.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    check.add_argument("--game-path", default=DEFAULT_GAME_PATH)

    export = sub.add_parser("export", help="print the detected rumour rows as json")
    export.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    export.add_argument("--game-path", default=DEFAULT_GAME_PATH)

    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if args.cmd == "build":
        build_patch(
            source=args.source,
            output_zip=args.output_zip,
            patched_dat=args.patched_dat,
            game_path=args.game_path,
            report=args.report,
        )
    elif args.cmd == "check":
        print(json.dumps(get_patch_status(args.source, args.game_path), ensure_ascii=False))
    elif args.cmd == "export":
        status = get_patch_status(args.source, args.game_path)
        print(json.dumps(status["rows"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
