#!/usr/bin/env python3
"""
Fetch POE2 market prices and build a PoE2 item-name price patch.

Network fetching uses the Python standard library + ThreadPoolExecutor with
retry/backoff. Playwright is only useful for discovering the endpoints; this
script performs the real data collection.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
import os
import re
import struct
import subprocess
import sys
import tempfile
import urllib.parse
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from price_sources.league import resolve_current_leagues
from price_sources.health import (
    evaluate_source_health,
    failed_source_health,
    skipped_source_health,
)
from price_sources.http_client import (
    DEFAULT_REQUEST_TIME_BUDGET,
    HTTP_READ_CHUNK_SIZE,
    MAX_HTTP_RESPONSE_BYTES,
    HttpResponse,
    RequestDeadlineExceeded,
    RetryingRequests,
    compact_text,
)
from price_sources.models import BaseItemPair, PriceObservation, PriceSourceResult

def progress(message: str) -> None:
    print(f"[进度] {message}", flush=True)


DEFAULT_SCOUT_API = "https://api.poe2scout.com"
DEFAULT_POECURRENCY_SUMMARY_API = "https://poecurrency.top/api/summary?version=2"
DEFAULT_POE_NINJA_CURRENCY_URL = "https://poe.ninja/poe2/economy/runesofaldur/currency"
DEFAULT_POE_NINJA_API_URL = "https://poe.ninja/poe2/api/economy/exchange/current/overview"
DEFAULT_POE_NINJA_ITEM_API_URL = "https://poe.ninja/poe2/api/economy/stash/current/item/overview"
DEFAULT_POE_NINJA_LEAGUE = "Runes of Aldur"
DEFAULT_POE2DB_ECONOMY_US_URL = "https://poe2db.tw/Economy"
DEFAULT_POE2DB_ECONOMY_CN_URL = "https://poe2db.tw/cn/Economy"
DEFAULT_LEAGUE = "runes"
PRICE_SOURCES = ("poe2scout", "poecurrency-cn")
FALLBACK_PRICE_SOURCES = ("poe-ninja", "poe2db-economy")
CN_REFERENCE_SOURCES = ("poe2scout", "poe-ninja", "poe2db-economy", "none")
PATCH_SCOPES = ("all", "currency", "uniques", "none")
PATCH_ROOT = SCRIPT_DIR.parent
DEFAULT_EN_BASEITEMS = (
    PATCH_ROOT / "output" / "dat_files_latest" / "data" / "data_balance_baseitemtypes.datc64"
)
DEFAULT_TC_BASEITEMS = (
    PATCH_ROOT
    / "output"
    / "dat_files_latest"
    / "data"
    / "data_balance_simplified chinese_baseitemtypes.datc64"
)
DEFAULT_EN_WORDS = (
    PATCH_ROOT / "output" / "dat_files_latest" / "data" / "data_balance_words.datc64"
)
DEFAULT_TC_WORDS = (
    PATCH_ROOT
    / "output"
    / "dat_files_latest"
    / "data"
    / "data_balance_simplified chinese_words.datc64"
)
DEFAULT_UNIQUE_GOLD_PRICES = (
    PATCH_ROOT
    / "output"
    / "dat_files_latest"
    / "data"
    / "data_balance_uniquegoldprices.datc64"
)
DEFAULT_PATCH_SCRIPT = Path(__file__).with_name("poe2_name_price_patch.py")
PRICE_TEXT_RE = r"(?:<1|[0-9]+(?:\.[0-9]+)?)[CDE]"
UNIQUE_MARKUP_PRICE_RE = rf"\[[^\]\r\n|]*{PRICE_TEXT_RE}[^\]\r\n|]*\|[^\]\r\n]+\]"
UNIQUE_PRICE_LABEL_MODES = ("markup", "overlay", "newline", "off")
DISPLAY_NAME_FIELD_INDEX = 8
DEFAULT_UNIQUE_CATEGORIES = (
    "accessory",
    "armour",
    "flask",
    "jewel",
    "map",
    "weapon",
    "sanctum",
)
POE_NINJA_EXCHANGE_TYPES = (
    "Currency",
    "Fragments",
    "Abyss",
    "UncutGems",
    "LineageSupportGems",
    "Essences",
    "SoulCores",
    "Idols",
    "Runes",
    "Ritual",
    "Expedition",
    "Delirium",
    "Breach",
    "Verisium",
)
POE_NINJA_ITEM_TYPES = (
    "UniqueWeapons",
    "UniqueArmours",
    "UniqueAccessories",
    "UniqueFlasks",
    "UniqueCharms",
    "UniqueJewels",
    "UniqueSanctumRelics",
    "UniqueTablets",
    "PrecursorTablets",
)
WORDS_ROW_SIZE = 64
WORDS_EN_NAME_OFFSET = 4
WORDS_DISPLAY_NAME_OFFSET = 48
UNIQUE_GOLD_PRICES_ROW_SIZE = 20
CN_DIVINE_NAMES = ("神圣石", "神圣宝珠", "Divine Orb")
CN_EXALTED_NAMES = ("崇高石", "崇高宝珠", "Exalted Orb")
CN_TRUSTED_BUY_SELL_RATIO = Decimal("5")
CN_HIGH_VALUE_FALLBACK_THRESHOLD_DIVINE = Decimal("10")
CN_HIGH_VALUE_FALLBACK_MAX_RATIO = Decimal("5")


@dataclass(frozen=True)
class Poe2dbEconomyRow:
    key: str
    name: str
    wiki_slug: str
    left_key: str
    left_qty: Decimal
    right_qty: Decimal
    volume: Decimal


@dataclass(frozen=True)
class DatLayout:
    row_count: int
    row_size: int
    string_base: int


@dataclass(frozen=True)
class WordEntry:
    row_index: int
    en_name: str
    display_name: str
    display_offset: int
    display_pointer_pos: int


@dataclass(frozen=True)
class UniqueName:
    row_index: int
    en_name: str
    display_name: str


def read_utf16le_z(data: bytes, start: int) -> tuple[str, int]:
    pos = start
    chars: list[int] = []
    while pos + 1 < len(data):
        code = data[pos] | (data[pos + 1] << 8)
        if code == 0:
            return "".join(chr(c) for c in chars), pos
        chars.append(code)
        pos += 2
    raise ValueError(f"unterminated UTF-16LE string at 0x{start:x}")


def skip_utf16le_zeroes(data: bytes, start: int) -> int:
    pos = start
    while pos + 1 < len(data) and data[pos] == 0 and data[pos + 1] == 0:
        pos += 2
    return pos


def detect_base_item_layout(data: bytes) -> DatLayout:
    if len(data) < 16:
        raise ValueError("BaseItemTypes.datc64 is too small")

    row_count = struct.unpack_from("<I", data, 0)[0]
    first_name_rel = struct.unpack_from("<I", data, 4)[0]
    marker = "Metadata/Items/".encode("utf-16-le")
    first_metadata = data.find(marker)
    if first_metadata < 0:
        raise ValueError("cannot find Metadata/Items marker in BaseItemTypes.datc64")

    string_base = first_metadata - first_name_rel
    row_bytes = string_base - 4
    if row_count <= 0 or string_base <= 4 or row_bytes % row_count != 0:
        raise ValueError("cannot detect BaseItemTypes row layout")

    row_size = row_bytes // row_count
    if row_size <= DISPLAY_NAME_FIELD_INDEX * 4:
        raise ValueError(f"unexpected BaseItemTypes row size: {row_size}")

    return DatLayout(row_count=row_count, row_size=row_size, string_base=string_base)


def read_string_offset(data: bytes, layout: DatLayout, offset: int) -> str:
    absolute = layout.string_base + offset
    if offset < 0 or offset % 2 != 0 or absolute + 1 >= len(data):
        raise ValueError(f"invalid string offset: 0x{offset:x}")
    text, _end = read_utf16le_z(data, absolute)
    return text


def detect_words_layout(data: bytes) -> DatLayout:
    if len(data) < 4 + WORDS_ROW_SIZE:
        raise ValueError("Words.datc64 is too small")
    row_count = struct.unpack_from("<I", data, 0)[0]
    string_base = 4 + row_count * WORDS_ROW_SIZE
    if row_count <= 0 or string_base >= len(data):
        raise ValueError("cannot detect Words.datc64 row layout")
    return DatLayout(
        row_count=row_count, row_size=WORDS_ROW_SIZE, string_base=string_base
    )


def read_words_row(data: bytes, layout: DatLayout, row_index: int) -> WordEntry | None:
    if row_index < 0 or row_index >= layout.row_count:
        return None
    row_start = 4 + row_index * layout.row_size
    try:
        en_offset = struct.unpack_from("<I", data, row_start + WORDS_EN_NAME_OFFSET)[0]
        display_pointer_pos = row_start + WORDS_DISPLAY_NAME_OFFSET
        display_offset = struct.unpack_from("<I", data, display_pointer_pos)[0]
        en_name = read_string_offset(data, layout, en_offset)
        display_name = read_string_offset(data, layout, display_offset)
    except (struct.error, ValueError):
        return None
    if not en_name or len(en_name) > 160 or len(display_name) > 160:
        return None
    return WordEntry(
        row_index=row_index,
        en_name=en_name,
        display_name=display_name,
        display_offset=display_offset,
        display_pointer_pos=display_pointer_pos,
    )


def inspect_words_price_labels(path: Path) -> dict[str, int | bool]:
    data = path.read_bytes()
    layout = detect_words_layout(data)
    readable_rows = 0
    patched_count = 0
    for row_index in range(layout.row_count):
        entry = read_words_row(data, layout, row_index)
        if not entry:
            continue
        readable_rows += 1
        if strip_existing_price(entry.display_name) != entry.display_name:
            patched_count += 1
    minimum_readable = max(1, math.ceil(layout.row_count * 0.95))
    if readable_rows < minimum_readable:
        raise ValueError(
            "Words.datc64 live-row scan is incomplete: "
            f"readable={readable_rows}, minimum={minimum_readable}, rows={layout.row_count}"
        )
    return {
        "row_count": layout.row_count,
        "readable_rows": readable_rows,
        "patched": patched_count > 0,
        "patched_count": patched_count,
    }


def words_look_price_patched(path: Path) -> bool:
    return bool(inspect_words_price_labels(path)["patched"])


def load_unique_names(
    unique_gold_prices_path: Path, en_words_path: Path, tc_words_path: Path
) -> dict[str, UniqueName]:
    unique_data = unique_gold_prices_path.read_bytes()
    en_words_data = en_words_path.read_bytes()
    tc_words_data = tc_words_path.read_bytes()
    en_layout = detect_words_layout(en_words_data)
    tc_layout = detect_words_layout(tc_words_data)
    row_count = struct.unpack_from("<I", unique_data, 0)[0]

    by_en_name: dict[str, UniqueName] = {}
    for row_index in range(row_count):
        row_start = 4 + row_index * UNIQUE_GOLD_PRICES_ROW_SIZE
        if row_start + 4 > len(unique_data):
            break
        words_row_index = struct.unpack_from("<I", unique_data, row_start)[0]
        en_entry = read_words_row(en_words_data, en_layout, words_row_index)
        tc_entry = read_words_row(tc_words_data, tc_layout, words_row_index)
        if not en_entry or not tc_entry:
            continue
        by_en_name[normalize_name(en_entry.en_name)] = UniqueName(
            row_index=words_row_index,
            en_name=en_entry.en_name,
            display_name=tc_entry.display_name,
        )
    return by_en_name


def append_utf16le_string(output: bytearray, layout: DatLayout, text: str) -> int:
    if len(output) % 2:
        output.append(0)
    offset = len(output) - layout.string_base
    if offset < 0 or offset > 0xFFFFFFFF:
        raise ValueError("appended string offset is out of uint32 range")
    output.extend(text.encode("utf-16-le"))
    output.extend(b"\x00\x00\x00\x00")
    return offset


def strip_existing_price(name: str) -> str:
    markup = re.fullmatch(
        rf"\[[^\]\r\n|]*{PRICE_TEXT_RE}[^\]\r\n|]*\|([^\]\r\n]+)\]",
        name.strip(),
    )
    if markup:
        return markup.group(1).strip()
    if re.search(rf"<<\[{PRICE_TEXT_RE}\]>>$", name):
        return re.sub(rf"<<\[{PRICE_TEXT_RE}\]>>$", "", name).strip()
    if re.search(rf"\s*\[{PRICE_TEXT_RE}\]$", name):
        return re.sub(rf"\s*\[{PRICE_TEXT_RE}\]$", "", name).strip()
    if re.search(rf"={PRICE_TEXT_RE}$", name):
        return re.sub(rf"={PRICE_TEXT_RE}$", "", name).strip()
    return name


def format_unique_price_name(base_name: str, price: str, label_mode: str) -> str:
    if label_mode == "markup":
        return f"[{price}|{base_name}]"
    if label_mode == "newline":
        return f"{base_name}\n[{price}]"
    if label_mode == "overlay":
        return f"{base_name}<<[{price}]>>"
    return base_name


def set_words_display_name(
    output: bytearray, layout: DatLayout, entry: WordEntry, text: str
) -> None:
    new_offset = append_utf16le_string(output, layout, text)
    struct.pack_into("<I", output, entry.display_pointer_pos, new_offset)


def clean_stale_unique_word_prices(
    data: bytes,
    layout: DatLayout,
    output: bytearray,
    unique_names: dict[str, UniqueName],
    skip_rows: set[int] | None = None,
) -> list[dict[str, str]]:
    skip_rows = skip_rows or set()
    cleaned: list[dict[str, str]] = []
    for unique in sorted(unique_names.values(), key=lambda item: item.row_index):
        if unique.row_index in skip_rows:
            continue
        entry = read_words_row(data, layout, unique.row_index)
        if not entry:
            continue
        base_name = strip_existing_price(entry.display_name)
        if base_name == entry.display_name:
            continue
        set_words_display_name(output, layout, entry, base_name)
        cleaned.append(
            {
                "words_row_index": str(unique.row_index),
                "en_name": unique.en_name,
                "old_name": entry.display_name,
                "new_name": base_name,
                "price": "",
                "api_id": "",
                "price_exalted": "",
                "source_pair": "existing-price-cleanup",
                "status": "cleaned",
                "reason": "removed stale unique price label",
            }
        )
    return cleaned


def clean_unique_word_prices_file(
    tc_words_path: Path,
    unique_names: dict[str, UniqueName],
    patched_words: Path,
) -> list[dict[str, str]]:
    data = tc_words_path.read_bytes()
    layout = detect_words_layout(data)
    output = bytearray(data)
    cleaned = clean_stale_unique_word_prices(data, layout, output, unique_names)
    if cleaned:
        atomic_write_bytes(patched_words, bytes(output))
    return cleaned


def clean_word_price_labels_file(
    tc_words_path: Path,
    patched_words: Path,
) -> list[dict[str, str]]:
    data = tc_words_path.read_bytes()
    layout = detect_words_layout(data)
    output = bytearray(data)
    cleaned: list[dict[str, str]] = []
    for row_index in range(layout.row_count):
        entry = read_words_row(data, layout, row_index)
        if not entry:
            continue
        base_name = strip_existing_price(entry.display_name)
        if base_name == entry.display_name:
            continue
        set_words_display_name(output, layout, entry, base_name)
        cleaned.append(
            {
                "words_row_index": str(entry.row_index),
                "en_name": entry.en_name,
                "old_name": entry.display_name,
                "new_name": base_name,
                "price": "",
                "api_id": "",
                "price_exalted": "",
                "source_pair": "existing-price-cleanup",
                "status": "cleaned",
                "reason": "removed disabled unique price label",
            }
        )
    atomic_write_bytes(patched_words, bytes(output))
    return cleaned


def patch_unique_word_prices(
    tc_words_path: Path,
    unique_names: dict[str, UniqueName],
    prices: dict[str, PriceObservation],
    patched_words: Path,
    label_mode: str = "markup",
) -> tuple[int, list[dict[str, str]], list[dict[str, str]]]:
    data = tc_words_path.read_bytes()
    layout = detect_words_layout(data)
    output = bytearray(data)
    patched_rows: set[int] = set()
    patched: list[dict[str, str]] = []
    missing: list[dict[str, str]] = []

    for obs in prices.values():
        if not obs.api_id.startswith("unique:"):
            continue
        if obs.price_exalted < Decimal("1") or not obs.display_price:
            continue
        unique = unique_names.get(normalize_name(obs.en_name))
        if not unique:
            missing.append(
                {
                    "api_id": obs.api_id,
                    "en_name": obs.en_name,
                    "reason": "not found in UniqueGoldPrices/Words",
                }
            )
            continue
        if unique.row_index in patched_rows:
            continue
        entry = read_words_row(data, layout, unique.row_index)
        if not entry:
            missing.append(
                {
                    "api_id": obs.api_id,
                    "en_name": obs.en_name,
                    "reason": "invalid target Words row",
                }
            )
            continue
        base_name = strip_existing_price(entry.display_name)
        new_name = format_unique_price_name(base_name, obs.display_price, label_mode)
        set_words_display_name(output, layout, entry, new_name)
        patched_rows.add(unique.row_index)
        patched.append(
            {
                "words_row_index": str(unique.row_index),
                "en_name": obs.en_name,
                "old_name": entry.display_name,
                "new_name": new_name,
                "price": obs.display_price,
                "api_id": obs.api_id,
                "price_exalted": str(obs.price_exalted),
                "source_pair": obs.source_pair,
                "status": "patched",
                "reason": "",
            }
        )

    cleaned = clean_stale_unique_word_prices(
        data, layout, output, unique_names, skip_rows=patched_rows
    )
    if patched or cleaned:
        atomic_write_bytes(patched_words, bytes(output))
    return len(patched), patched + cleaned, missing


def patch_unique_word_prices_with_cn_fallback(
    tc_words_path: Path,
    unique_names: dict[str, UniqueName],
    primary_prices: dict[str, PriceObservation],
    fallback_prices: dict[str, PriceObservation],
    patched_words: Path,
    label_mode: str = "markup",
) -> tuple[int, list[dict[str, str]], list[dict[str, str]], int]:
    data = tc_words_path.read_bytes()
    layout = detect_words_layout(data)
    output = bytearray(data)
    patched_rows: set[int] = set()
    patched: list[dict[str, str]] = []
    missing: list[dict[str, str]] = []
    fallback_count = 0

    unique_entries = sorted(
        unique_names.values(), key=lambda item: strip_existing_price(item.display_name)
    )
    for unique in unique_entries:
        if unique.row_index in patched_rows:
            continue
        market_name = strip_existing_price(unique.display_name)
        obs = primary_prices.get(poecurrency_api_id(market_name))
        source = "poecurrency-cn"
        if not obs or obs.price_exalted < Decimal("1") or not obs.display_price:
            obs = fallback_prices.get(f"unique:{normalize_name(unique.en_name)}")
            source = "poe2scout-fallback"
        if not obs or obs.price_exalted < Decimal("1") or not obs.display_price:
            missing.append(
                {
                    "api_id": f"cn:{normalize_market_name(market_name)}",
                    "en_name": unique.en_name,
                    "reason": "not found in poecurrency-cn or poe2scout fallback",
                }
            )
            continue

        entry = read_words_row(data, layout, unique.row_index)
        if not entry:
            missing.append(
                {
                    "api_id": obs.api_id,
                    "en_name": unique.en_name,
                    "reason": "invalid target Words row",
                }
            )
            continue
        base_name = strip_existing_price(entry.display_name)
        new_name = format_unique_price_name(base_name, obs.display_price, label_mode)
        set_words_display_name(output, layout, entry, new_name)
        patched_rows.add(unique.row_index)
        if source == "poe2scout-fallback":
            fallback_count += 1
        patched.append(
            {
                "words_row_index": str(unique.row_index),
                "en_name": unique.en_name,
                "old_name": entry.display_name,
                "new_name": new_name,
                "price": obs.display_price,
                "api_id": obs.api_id,
                "price_exalted": str(obs.price_exalted),
                "source_pair": f"{obs.source_pair}; source={source}",
                "status": "patched",
                "reason": "",
            }
        )

    cleaned = clean_stale_unique_word_prices(
        data, layout, output, unique_names, skip_rows=patched_rows
    )
    if patched or cleaned:
        atomic_write_bytes(patched_words, bytes(output))
    return len(patched), patched + cleaned, missing, fallback_count


def list_unique_word_price_candidates(
    unique_names: dict[str, UniqueName],
    prices: dict[str, PriceObservation],
    reason: str,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    rows: list[dict[str, str]] = []
    missing: list[dict[str, str]] = []
    seen_rows: set[int] = set()

    for obs in prices.values():
        if not obs.api_id.startswith("unique:"):
            continue
        if obs.price_exalted < Decimal("1") or not obs.display_price:
            continue
        unique = unique_names.get(normalize_name(obs.en_name))
        if not unique:
            missing.append(
                {
                    "api_id": obs.api_id,
                    "en_name": obs.en_name,
                    "reason": "not found in UniqueGoldPrices/Words",
                }
            )
            continue
        if unique.row_index in seen_rows:
            continue
        seen_rows.add(unique.row_index)
        rows.append(
            {
                "words_row_index": str(unique.row_index),
                "en_name": obs.en_name,
                "old_name": "",
                "new_name": "",
                "price": obs.display_price,
                "api_id": obs.api_id,
                "price_exalted": str(obs.price_exalted),
                "source_pair": obs.source_pair,
                "status": "skipped",
                "reason": reason,
            }
        )

    return rows, missing


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.new-", suffix=".tmp", dir=path.parent
    )
    os.close(handle)
    temp_path = Path(temp_name)
    try:
        temp_path.write_bytes(data)
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def upsert_zip_entry(zip_path: Path, entry_name: str, data: bytes) -> None:
    entry_name = entry_name.replace("\\", "/")
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    existing: list[tuple[zipfile.ZipInfo, bytes]] = []
    if zip_path.exists():
        with zipfile.ZipFile(zip_path, "r") as zf:
            for info in zf.infolist():
                if info.filename != entry_name:
                    existing.append((info, zf.read(info.filename)))
    handle, temp_name = tempfile.mkstemp(
        prefix=f".{zip_path.name}.new-", suffix=".zip", dir=zip_path.parent
    )
    os.close(handle)
    temp_path = Path(temp_name)
    try:
        with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for info, content in existing:
                zf.writestr(info, content)
            zf.writestr(entry_name, data)
        with zipfile.ZipFile(temp_path, "r") as zf:
            if zf.testzip() is not None:
                raise ValueError(f"generated patch zip failed CRC validation: {temp_path}")
        os.replace(temp_path, zip_path)
    finally:
        temp_path.unlink(missing_ok=True)


def scan_base_items(path: Path) -> dict[str, str]:
    data = path.read_bytes()
    layout = detect_base_item_layout(data)
    items: dict[str, str] = {}

    for row_index in range(layout.row_count):
        row_start = 4 + row_index * layout.row_size
        try:
            metadata_offset = struct.unpack_from("<I", data, row_start)[0]
            name_offset = struct.unpack_from(
                "<I", data, row_start + DISPLAY_NAME_FIELD_INDEX * 4
            )[0]
            metadata_path = read_string_offset(data, layout, metadata_offset)
            name = read_string_offset(data, layout, name_offset)
        except (struct.error, ValueError):
            continue
        if (
            metadata_path.startswith("Metadata/Items/")
            and name
            and not name.startswith("Metadata/")
            and len(name) <= 160
        ):
            items[metadata_path] = name
    return items


def load_base_item_pairs(en_path: Path, tc_path: Path) -> list[BaseItemPair]:
    en = scan_base_items(en_path)
    tc = scan_base_items(tc_path)
    pairs = []
    for metadata_path, en_name in en.items():
        tc_name = tc.get(metadata_path)
        if tc_name:
            pairs.append(BaseItemPair(metadata_path, en_name, tc_name))
    return pairs


def load_localized_base_item_pairs(tc_path: Path) -> list[BaseItemPair]:
    tc = scan_base_items(tc_path)
    return [
        BaseItemPair(metadata_path, "", tc_name)
        for metadata_path, tc_name in tc.items()
        if tc_name
    ]


def normalize_name(value: str) -> str:
    value = html.unescape(value).lower()
    value = value.replace("’", "'")
    value = re.sub(r"[^a-z0-9]+", "", value)
    return value


def slug_candidates(en_name: str) -> list[str]:
    cleaned = html.unescape(en_name).replace("’", "'")
    candidates = []
    forms = [
        cleaned,
        cleaned.replace("'", ""),
        cleaned.replace("'", "_"),
        cleaned.replace("-", "_"),
        cleaned.replace("'", "").replace("-", "_"),
    ]
    for form in forms:
        slug = re.sub(r"\s+", "_", form.strip())
        slug = urllib.parse.quote(slug, safe="_")
        if slug and slug not in candidates:
            candidates.append(slug)
    return candidates


def parse_poe2db_title(text: str) -> str | None:
    match = re.search(r"<title>(.*?)</title>", text, flags=re.I | re.S)
    if not match:
        return None
    title = html.unescape(re.sub(r"\s+", " ", match.group(1))).strip()
    for sep in [" - PoE2DB", " - 流亡2編年史"]:
        if sep in title:
            return title.split(sep, 1)[0].strip()
    return title or None


def fetch_poe2db_translation(
    client: RetryingRequests, en_name: str, max_slug_attempts: int = 6
) -> str | None:
    for slug in slug_candidates(en_name)[:max_slug_attempts]:
        try:
            us = client.get(f"https://poe2db.tw/us/{slug}")
            if us.status_code == 404 or not parse_poe2db_title(us.text):
                continue
            tw = client.get(f"https://poe2db.tw/tw/{slug}")
            if tw.status_code == 404:
                continue
            tw_title = parse_poe2db_title(tw.text)
            if tw_title:
                return tw_title
        except Exception:
            continue
    return None


def strip_html_tags(text: str) -> str:
    text = re.sub(r"<script\b.*?</script>", "", text, flags=re.I | re.S)
    text = re.sub(r"<style\b.*?</style>", "", text, flags=re.I | re.S)
    return html.unescape(re.sub(r"<[^>]+>", " ", text)).strip()


def clean_cell_text(text: str) -> str:
    return re.sub(r"\s+", " ", strip_html_tags(text)).strip()


def economy_href_key(href: str) -> str:
    href = html.unescape(href or "").strip()
    name = href.rsplit("/", 1)[-1].split("?", 1)[0].split("#", 1)[0]
    if name.startswith("Economy_"):
        return name[len("Economy_") :].lower()
    return name.lower()


def poe2db_economy_page_name(href: str) -> str:
    href = html.unescape(href or "").strip()
    parsed = urllib.parse.urlparse(href)
    path = parsed.path or href
    return path.rsplit("/", 1)[-1].split("?", 1)[0].split("#", 1)[0]


def discover_poe2db_economy_category_pages(text: str) -> list[str]:
    search_space = re.split(r"<table\b", text, maxsplit=1, flags=re.I)[0]
    pages: list[str] = []
    for href in re.findall(r'<a\b[^>]*href=["\']([^"\']+)["\']', search_space, flags=re.I):
        page = poe2db_economy_page_name(href)
        if not re.fullmatch(r"Economy_[A-Z][A-Za-z0-9_'-]*", page):
            continue
        if page not in pages:
            pages.append(page)
    return pages


def poe2db_economy_category_url(base_url: str, page: str) -> str:
    return urllib.parse.urljoin(base_url, page)


def poe2db_economy_initial_pages(url: str) -> set[str]:
    page = poe2db_economy_page_name(url) or "Economy"
    pages = {page}
    if page == "Economy":
        pages.add("Economy_Currency")
    return pages


def poe_ninja_api_url_from_page(page_url: str, api_url: str, league: str) -> str:
    if "?" in page_url and "/api/" in page_url:
        return page_url
    query = urllib.parse.urlencode({"league": league, "type": "Currency"})
    return f"{api_url}?{query}"


def poe_ninja_api_url(api_url: str, league: str, item_type: str) -> str:
    query = urllib.parse.urlencode({"league": league, "type": item_type})
    return f"{api_url}?{query}"


def decimal_from_text(text: str) -> Decimal:
    cleaned = re.sub(r"[^0-9.]", "", text)
    if not cleaned:
        return Decimal("0")
    return Decimal(cleaned)


POE2DB_SINGLE_LINK_MARKER = "__POE2DB_REFERENCE_LINK__"
POE2DB_SIGNED_NUMBER_RE = r"(?<![\w.])-?[0-9][0-9,]*(?:\.[0-9]+)?"


def parse_poe2db_single_link_value(
    value_cell: str,
    row_key: str,
    value_links: list[str],
) -> tuple[str, Decimal, Decimal] | None:
    """Parse the strict one-link Poe2DB variant without guessing currencies.

    Poe2DB occasionally renders the item side as its plain-text Economy slug
    instead of a second anchor.  The remaining anchor must identify a supported
    reference currency, and the unlinked slug must exactly identify this row.
    Quantities are normalized so the reference currency is always the left side.
    """

    if len(value_links) != 1:
        return None
    reference_key = economy_href_key(value_links[0])
    if reference_key not in {"divine", "exalted"}:
        return None

    anchor_match = re.search(
        r'<a\b[^>]*href="Economy_[^"]+"[^>]*>.*?</a>',
        value_cell,
        flags=re.I | re.S,
    )
    if not anchor_match:
        return None

    marked_cell = (
        value_cell[: anchor_match.start()]
        + f" {POE2DB_SINGLE_LINK_MARKER} "
        + value_cell[anchor_match.end() :]
    )
    visible = clean_cell_text(marked_cell)
    number_matches = list(re.finditer(POE2DB_SIGNED_NUMBER_RE, visible))
    if len(number_matches) != 2:
        return None

    quantities = [Decimal(match.group(0).replace(",", "")) for match in number_matches]
    if any(quantity <= 0 for quantity in quantities):
        return None

    marker_pos = visible.find(POE2DB_SINGLE_LINK_MARKER)
    if marker_pos < 0:
        return None

    residual = visible.replace(POE2DB_SINGLE_LINK_MARKER, " ")
    residual = re.sub(POE2DB_SIGNED_NUMBER_RE, " ", residual)
    residual = re.sub(r"[\s|:;/,=<>↔⇄⇆⇌⟷⟺·•]+", "", residual).lower()
    if residual != row_key.lower():
        return None

    first_number, second_number = number_matches
    if first_number.end() <= marker_pos < second_number.start():
        return reference_key, quantities[0], quantities[1]
    if second_number.end() <= marker_pos:
        return reference_key, quantities[1], quantities[0]
    return None


def parse_poe2db_economy_rows(text: str) -> dict[str, Poe2dbEconomyRow]:
    rows: dict[str, Poe2dbEconomyRow] = {}
    for tr_match in re.finditer(r"<tr\b[^>]*>(.*?)</tr>", text, flags=re.I | re.S):
        cells = re.findall(r"<td\b[^>]*>(.*?)</td>", tr_match.group(1), flags=re.I | re.S)
        if len(cells) < 4:
            continue

        name_cell = cells[0]
        value_cell = cells[1]
        name_match = re.search(
            r'<a\b[^>]*href="(Economy_[^"]+)"[^>]*>(.*?)</a>',
            name_cell,
            flags=re.I | re.S,
        )
        if not name_match:
            continue

        key = economy_href_key(name_match.group(1))
        name = clean_cell_text(name_match.group(2))
        wiki_match = re.search(
            r'<a\b[^>]*href="([^"]+)"[^>]*class="[^"]*\bborder\b[^"]*"',
            name_cell,
            flags=re.I | re.S,
        )
        wiki_slug = html.unescape(wiki_match.group(1)).strip() if wiki_match else ""
        value_links = re.findall(
            r'<a\b[^>]*href="(Economy_[^"]+)"',
            value_cell,
            flags=re.I | re.S,
        )
        numbers = re.findall(r"(?<![\w.])[0-9][0-9,]*(?:\.[0-9]+)?", clean_cell_text(value_cell))
        if len(value_links) >= 2 and len(numbers) >= 2:
            left_key = economy_href_key(value_links[0])
            left_qty = decimal_from_text(numbers[0])
            right_qty = decimal_from_text(numbers[1])
            if left_qty <= 0 or right_qty <= 0:
                continue
        else:
            single_link_value = parse_poe2db_single_link_value(value_cell, key, value_links)
            if single_link_value is None:
                continue
            left_key, left_qty, right_qty = single_link_value

        rows[key] = Poe2dbEconomyRow(
            key=key,
            name=name,
            wiki_slug=wiki_slug,
            left_key=left_key,
            left_qty=left_qty,
            right_qty=right_qty,
            volume=decimal_from_text(clean_cell_text(cells[3])),
        )
    return rows


def poe2db_divine_price_exalted(rows: dict[str, Poe2dbEconomyRow]) -> Decimal:
    exalted = rows.get("exalted")
    if exalted and exalted.left_key == "divine" and exalted.left_qty > 0:
        return exalted.right_qty / exalted.left_qty
    divine = rows.get("divine")
    if divine and divine.left_key == "exalted" and divine.right_qty > 0:
        return divine.left_qty / divine.right_qty
    raise ValueError("cannot determine Poe2DB Economy Divine/Exalted ratio")


def poe2db_row_price_exalted(row: Poe2dbEconomyRow, divine_exalted: Decimal) -> Decimal:
    left_price = row.left_qty / row.right_qty
    if row.left_key == "divine":
        return left_price * divine_exalted
    if row.left_key == "exalted":
        return left_price
    return Decimal("0")


def build_poe2db_economy_prices(
    client: RetryingRequests, us_url: str, cn_url: str
) -> tuple[dict[str, Any], dict[str, PriceObservation]]:
    progress("Poe2DB Economy：读取分类入口页")
    us_html = client.get(us_url).text
    cn_html = client.get(cn_url).text
    us_initial_pages = poe2db_economy_initial_pages(us_url)
    cn_initial_pages = poe2db_economy_initial_pages(cn_url)
    category_pages = discover_poe2db_economy_category_pages(us_html)
    for page in discover_poe2db_economy_category_pages(cn_html):
        if page not in category_pages:
            category_pages.append(page)
    if not category_pages:
        category_pages = [poe2db_economy_page_name(us_url) or "Economy"]
    progress(f"Poe2DB Economy：发现 {len(category_pages)} 个分类页，开始抓取")

    us_rows: dict[str, Poe2dbEconomyRow] = {}
    cn_rows: dict[str, Poe2dbEconomyRow] = {}
    page_results: dict[
        str,
        tuple[dict[str, Poe2dbEconomyRow], dict[str, Poe2dbEconomyRow], dict[str, Any]],
    ] = {}

    def fetch_category(
        page: str,
    ) -> tuple[dict[str, Poe2dbEconomyRow], dict[str, Poe2dbEconomyRow], dict[str, Any]]:
        page_us_url = us_url if page in us_initial_pages else poe2db_economy_category_url(us_url, page)
        page_cn_url = cn_url if page in cn_initial_pages else poe2db_economy_category_url(cn_url, page)
        try:
            page_us_html = us_html if page in us_initial_pages else client.get(page_us_url).text
            page_cn_html = cn_html if page in cn_initial_pages else client.get(page_cn_url).text

            page_us_rows = parse_poe2db_economy_rows(page_us_html)
            page_cn_rows = parse_poe2db_economy_rows(page_cn_html)
            if not page_us_rows:
                raise ValueError("Poe2DB US Economy category table is empty")
            if not page_cn_rows:
                raise ValueError("Poe2DB CN Economy category table is empty")
            return (
                page_us_rows,
                page_cn_rows,
                {
                    "page": page,
                    "us_url": page_us_url,
                    "cn_url": page_cn_url,
                    "us_rows": len(page_us_rows),
                    "cn_rows": len(page_cn_rows),
                    "status": "ok",
                },
            )
        except Exception as exc:
            return (
                {},
                {},
                {
                    "page": page,
                    "us_url": page_us_url,
                    "cn_url": page_cn_url,
                    "us_rows": 0,
                    "cn_rows": 0,
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )

    with ThreadPoolExecutor(max_workers=min(6, max(1, len(category_pages)))) as pool:
        futures = {pool.submit(fetch_category, page): page for page in category_pages}
        completed = 0
        for future in as_completed(futures):
            page = futures[future]
            page_results[page] = future.result()
            completed += 1
            _page_us_rows, _page_cn_rows, stat = page_results[page]
            if stat.get("status") == "ok":
                progress(
                    "Poe2DB Economy："
                    f"{completed}/{len(category_pages)} {page} 完成 "
                    f"(国际 {stat.get('us_rows', 0)}，国服 {stat.get('cn_rows', 0)})"
                )
            else:
                progress(f"Poe2DB Economy：{completed}/{len(category_pages)} {page} 失败")

    page_stats: list[dict[str, Any]] = []
    for page in category_pages:
        page_us_rows, page_cn_rows, stat = page_results[page]
        us_rows.update(page_us_rows)
        cn_rows.update(page_cn_rows)
        page_stats.append(stat)

    failed_pages = [stat for stat in page_stats if stat.get("status") != "ok"]
    core_page = (
        "Economy_Currency"
        if "Economy_Currency" in category_pages
        else (poe2db_economy_page_name(us_url) or "Economy")
    )
    core_failures = [stat for stat in failed_pages if stat.get("page") == core_page]
    if core_failures:
        core_error = str(core_failures[0].get("error") or "unknown error")
        raise ValueError(f"Poe2DB Economy core category {core_page} failed: {core_error}")

    if not us_rows:
        raise ValueError("Poe2DB US Economy table is empty")
    if not cn_rows:
        raise ValueError("Poe2DB CN Economy table is empty")

    divine_exalted = poe2db_divine_price_exalted(us_rows)
    best: dict[str, PriceObservation] = {}
    for key, us_row in us_rows.items():
        cn_row = cn_rows.get(key)
        if not cn_row:
            continue
        if key == "divine":
            price_exalted = divine_exalted
        elif key == "exalted":
            price_exalted = Decimal("1")
        else:
            price_exalted = poe2db_row_price_exalted(us_row, divine_exalted)
        if price_exalted <= 0:
            continue
        api_id = key if key in {"divine", "exalted"} else f"poe2db:{key}"
        best[api_id] = PriceObservation(
            api_id=api_id,
            en_name=cn_row.name,
            category="poe2db-economy",
            price_exalted=price_exalted,
            value_traded=us_row.volume,
            source_pair=(
                f"Poe2DB Economy/{us_row.name}; "
                f"wiki={us_row.wiki_slug}; value={us_row.left_qty}/{us_row.right_qty} {us_row.left_key}"
            ),
        )

    failed_names = [str(stat.get("page")) for stat in failed_pages]
    source_status = "partial" if failed_names else "ok"
    warning = (
        "Poe2DB Economy optional categories failed: " + ", ".join(failed_names)
        if failed_names
        else ""
    )
    if warning:
        progress(f"Poe2DB Economy：部分分类失败，保留其余分类 ({', '.join(failed_names)})")

    raw = {
        "source": "poe2db-economy",
        "status": source_status,
        "health_state": source_status,
        "warning": warning,
        "us_url": us_url,
        "cn_url": cn_url,
        "category_pages": category_pages,
        "category_count": len(category_pages),
        "discovered_categories": list(category_pages),
        "healthy_categories": [
            str(stat.get("page")) for stat in page_stats if stat.get("status") == "ok"
        ],
        "enabled_categories": list(category_pages),
        "failed_categories": failed_names,
        "category_page_stats": page_stats,
        "us_rows": len(us_rows),
        "cn_rows": len(cn_rows),
        "matched_rows": len(best),
        "divine_price_exalted": str(divine_exalted),
    }
    return raw, best


def build_poe_ninja_currency_prices(
    client: RetryingRequests,
    page_url: str,
    api_url: str,
    league: str,
    item_api_url: str | None = None,
) -> tuple[dict[str, Any], dict[str, PriceObservation]]:
    item_api_url = item_api_url or DEFAULT_POE_NINJA_ITEM_API_URL
    source_specs = [
        ("exchange", item_type, poe_ninja_api_url(api_url, league, item_type))
        for item_type in POE_NINJA_EXCHANGE_TYPES
    ] + [
        ("item", item_type, poe_ninja_api_url(item_api_url, league, item_type))
        for item_type in POE_NINJA_ITEM_TYPES
    ]
    if "?" in page_url and "/api/" in page_url:
        source_specs = [("exchange", "Currency", page_url)]

    progress(f"poe.ninja：开始抓取 {len(source_specs)} 个分类")
    payloads: dict[tuple[str, str], dict[str, Any]] = {}
    category_errors: dict[tuple[str, str], str] = {}
    with ThreadPoolExecutor(max_workers=min(8, len(source_specs))) as pool:
        futures = {
            pool.submit(client.get_json, source_url): (source_kind, item_type, source_url)
            for source_kind, item_type, source_url in source_specs
        }
        completed = 0
        for future in as_completed(futures):
            source_kind, item_type, _source_url = futures[future]
            try:
                payload = future.result()
                validate_poe_ninja_category_payload(
                    payload, source_kind, item_type
                )
                payloads[(source_kind, item_type)] = payload
                lines = len(payload.get("lines") or [])
                state = f"完成 ({lines} 条)"
            except Exception as exc:
                category_errors[(source_kind, item_type)] = (
                    f"{type(exc).__name__}: {exc}"
                )
                state = "失败"
            completed += 1
            progress(
                f"poe.ninja：{completed}/{len(source_specs)} {item_type} {state}"
            )

    core_error = category_errors.get(("exchange", "Currency"))
    if core_error:
        raise ValueError(f"poe.ninja core category Currency failed: {core_error}")

    currency_data = payloads.get(("exchange", "Currency")) or {}
    core = currency_data.get("core") or {}
    rates = core.get("rates") or {}
    divine_exalted = to_decimal(rates.get("exalted"))
    if divine_exalted <= 0:
        exalted_line = next(
            (line for line in currency_data.get("lines") or [] if line.get("id") == "exalted"),
            None,
        )
        if exalted_line:
            primary_value = to_decimal(exalted_line.get("primaryValue"))
            if primary_value > 0:
                divine_exalted = Decimal("1") / primary_value
    if divine_exalted <= 0:
        raise ValueError("cannot determine poe.ninja Divine/Exalted ratio")

    best: dict[str, PriceObservation] = {
        "divine": PriceObservation(
            api_id="divine",
            en_name="Divine Orb",
            category="currency",
            price_exalted=divine_exalted,
            value_traded=Decimal("0"),
            source_pair="poe.ninja/core/rates",
        ),
        "exalted": PriceObservation(
            api_id="exalted",
            en_name="Exalted Orb",
            category="currency",
            price_exalted=Decimal("1"),
            value_traded=Decimal("0"),
            source_pair="poe.ninja/core/rates",
        ),
    }

    category_stats: list[dict[str, Any]] = []
    for source_kind, item_type, source_url in source_specs:
        error = category_errors.get((source_kind, item_type), "")
        if error:
            category_stats.append(
                {
                    "kind": source_kind,
                    "type": item_type,
                    "url": source_url,
                    "lines": 0,
                    "items": 0,
                    "status": "failed",
                    "error": error,
                }
            )
            continue
        data = payloads.get((source_kind, item_type)) or {}
        lines = data.get("lines") or []
        category_stats.append(
            {
                "kind": source_kind,
                "type": item_type,
                "url": source_url,
                "lines": len(lines),
                "items": len(data.get("items") or []),
                "status": "ok",
            }
        )
        if source_kind == "exchange":
            items_by_id = {item.get("id"): item for item in data.get("items") or []}
            for item in (data.get("core") or {}).get("items") or []:
                if item.get("id") not in items_by_id:
                    items_by_id[item.get("id")] = item
            for line in lines:
                api_id = str(line.get("id") or "").strip()
                item = items_by_id.get(api_id) or {}
                name = str(item.get("name") or "").strip()
                if not api_id or not name:
                    continue
                primary_value = to_decimal(line.get("primaryValue"))
                if api_id == "divine":
                    price_exalted = divine_exalted
                elif api_id == "exalted":
                    price_exalted = Decimal("1")
                else:
                    price_exalted = primary_value * divine_exalted
                if price_exalted <= 0:
                    continue
                best[api_id] = PriceObservation(
                    api_id=api_id,
                    en_name=name,
                    category=str(item.get("category") or item_type),
                    price_exalted=price_exalted,
                    value_traded=to_decimal(line.get("volumePrimaryValue")),
                    source_pair=f"poe.ninja/{item_type}/{name}; primary_value={primary_value}",
                )
            continue

        for line in lines:
            details_id = str(line.get("detailsId") or line.get("itemId") or line.get("id") or "").strip()
            name = str(line.get("name") or line.get("baseType") or "").strip()
            if not details_id or not name:
                continue
            primary_value = to_decimal(line.get("primaryValue"))
            price_exalted = primary_value * divine_exalted
            if price_exalted <= 0:
                continue
            api_id = f"unique:{normalize_name(details_id)}"
            best[api_id] = PriceObservation(
                api_id=api_id,
                en_name=name,
                category=f"unique:{item_type}",
                price_exalted=price_exalted,
                value_traded=to_decimal(line.get("listingCount")),
                source_pair=f"poe.ninja/{item_type}/{name}; primary_value={primary_value}",
            )

    discovered_categories = [f"{kind}:{item_type}" for kind, item_type, _ in source_specs]
    succeeded_categories = [
        f"{stat['kind']}:{stat['type']}"
        for stat in category_stats
        if stat.get("status") == "ok"
    ]
    failed_categories = [
        f"{stat['kind']}:{stat['type']}"
        for stat in category_stats
        if stat.get("status") == "failed"
    ]
    source_status = "partial" if failed_categories else "ok"
    warning = (
        "poe.ninja optional categories failed: " + ", ".join(failed_categories)
        if failed_categories
        else ""
    )
    raw = {
        "source": "poe-ninja",
        "status": source_status,
        "health_state": source_status,
        "warning": warning,
        "url": poe_ninja_api_url_from_page(page_url, api_url, league),
        "category_count": len(source_specs),
        "discovered_categories": discovered_categories,
        "enabled_categories": discovered_categories,
        "healthy_categories": succeeded_categories,
        "failed_categories": failed_categories,
        "category_stats": category_stats,
        "items": sum(stat["items"] for stat in category_stats),
        "lines": sum(stat["lines"] for stat in category_stats),
        "matched_rows": len(best),
        "divine_price_exalted": str(divine_exalted),
    }
    return raw, best


def validate_poe_ninja_category_payload(
    payload: Any,
    source_kind: str,
    item_type: str,
) -> None:
    """Validate one category before it can affect the whole source parser."""

    if not isinstance(payload, dict):
        raise ValueError(f"poe.ninja {item_type} response root is not an object")
    core = payload.get("core")
    lines = payload.get("lines")
    if not isinstance(core, dict):
        raise ValueError(f"poe.ninja {item_type} core is not an object")
    if not isinstance(lines, list):
        raise ValueError(f"poe.ninja {item_type} lines is not an array")
    if not lines:
        raise ValueError(f"poe.ninja {item_type} lines is empty")
    if any(not isinstance(line, dict) for line in lines):
        raise ValueError(f"poe.ninja {item_type} lines contains a non-object row")
    if source_kind == "exchange":
        items = payload.get("items")
        core_items = core.get("items")
        if items is not None and not isinstance(items, list):
            raise ValueError(f"poe.ninja {item_type} items is not an array")
        if core_items is not None and not isinstance(core_items, list):
            raise ValueError(f"poe.ninja {item_type} core.items is not an array")
        if not isinstance(items, list) and not isinstance(core_items, list):
            raise ValueError(f"poe.ninja {item_type} items is not an array")
        if isinstance(items, list) and any(
            not isinstance(item, dict) for item in items
        ):
            raise ValueError(f"poe.ninja {item_type} items contains a non-object row")
        if isinstance(core_items, list) and any(
            not isinstance(item, dict) for item in core_items
        ):
            raise ValueError(
                f"poe.ninja {item_type} core.items contains a non-object row"
            )


def fetch_scout_data(client: RetryingRequests, api_base: str, league: str) -> dict[str, Any]:
    endpoints = {
        "exchange_snapshot": f"{api_base}/poe2/Leagues/{league}/ExchangeSnapshot",
        "reference_currencies": f"{api_base}/poe2/Leagues/{league}/ReferenceCurrencies",
        "snapshot_pairs": f"{api_base}/poe2/Leagues/{league}/SnapshotPairs",
    }
    labels = {
        "exchange_snapshot": "市场快照",
        "reference_currencies": "参考通货",
        "snapshot_pairs": "全量价格对",
    }
    progress("poe2scout：开始抓取主价格接口")
    progress(
        "poe2scout：全量价格对接口数据较大；"
        f"单个接口最多等待 {client.total_timeout:g} 秒（含重试）"
    )
    results: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        future_to_name = {
            pool.submit(client.get_json, url): name for name, url in endpoints.items()
        }
        completed = 0
        for future in as_completed(future_to_name):
            name = future_to_name[future]
            results[name] = future.result()
            completed += 1
            progress(f"poe2scout：{completed}/{len(endpoints)} {labels.get(name, name)} 完成")
    return results


def build_scout_prices(
    client: RetryingRequests,
    api_base: str,
    league: str,
    include_uniques: bool,
    max_workers: int,
) -> tuple[
    dict[str, Any],
    dict[str, PriceObservation],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    scout = fetch_scout_data(client, api_base, league)
    progress("poe2scout：整理价格对")
    observations = collect_price_observations(scout["snapshot_pairs"])
    best = choose_best_prices(observations, scout["reference_currencies"])
    progress(f"poe2scout：已整理 {len(best)} 条基础价格")
    unique_categories: list[dict[str, Any]] = []
    unique_items: list[dict[str, Any]] = []
    unique_fetch_error = ""
    if include_uniques:
        try:
            unique_categories, unique_items = fetch_unique_items(
                client,
                api_base,
                league,
                max_workers=max(1, max_workers),
            )
        except Exception as exc:
            unique_fetch_error = f"{type(exc).__name__}: {exc}"
            progress("poe2scout：传奇分类入口失败，保留基础价格")
        add_unique_observations(best, unique_items)
    failed_unique_categories = [
        str(category.get("ApiId") or "")
        for category in unique_categories
        if category.get("_fetch_status") == "failed"
    ]
    if unique_fetch_error:
        failed_unique_categories.append("unique-category-index")
    healthy_unique_categories = [
        str(category.get("ApiId") or "")
        for category in unique_categories
        if category.get("_fetch_status") == "ok"
    ]
    enabled_unique_categories = [
        str(category.get("ApiId") or "")
        for category in unique_categories
        if category.get("ApiId")
    ]
    source_status = "partial" if failed_unique_categories else "ok"
    warning = (
        "poe2scout optional unique categories failed: "
        + ", ".join(failed_unique_categories)
        if failed_unique_categories
        else ""
    )
    scout["status"] = source_status
    scout["health_state"] = source_status
    scout["warning"] = warning
    scout["unique_fetch_error"] = unique_fetch_error
    scout["discovered_categories"] = sorted(
        {obs.category for obs in best.values() if obs.category}
    )
    scout["enabled_unique_categories"] = enabled_unique_categories
    scout["healthy_unique_categories"] = healthy_unique_categories
    scout["failed_unique_categories"] = failed_unique_categories
    return scout, best, unique_categories, unique_items


def price_source_label(source: str) -> str:
    if source == "poe2scout":
        return "poe2scout"
    if source == "poe-ninja":
        return "poe.ninja"
    if source == "poe2db-economy":
        return "poe2db-economy"
    if source == "poecurrency-cn":
        return "poecurrency-cn"
    return source


def fallback_raw_filename(source: str, primary: bool = False) -> str:
    prefix = "raw" if primary else "fallback_raw"
    if source == "poe2scout":
        return "poe2scout_raw.json" if primary else "poe2scout_fallback_raw.json"
    if source == "poe-ninja":
        return f"poe_ninja_{prefix}.json"
    if source == "poe2db-economy":
        return f"poe2db_economy_{prefix}.json"
    return f"{source.replace('-', '_')}_{prefix}.json"


def fallback_error_filename(source: str, primary: bool = False) -> str:
    prefix = "error" if primary else "fallback_error"
    if source == "poe2scout":
        return "poe2scout_error.json" if primary else "poe2scout_fallback_error.json"
    if source == "poe-ninja":
        return f"poe_ninja_{prefix}.json"
    if source == "poe2db-economy":
        return f"poe2db_economy_{prefix}.json"
    return f"{source.replace('-', '_')}_{prefix}.json"


def fetch_price_source(
    source: str,
    client: RetryingRequests,
    args: argparse.Namespace,
    include_uniques: bool,
) -> PriceSourceResult:
    if source == "poe2scout":
        raw, prices, unique_categories, unique_items = build_scout_prices(
            client,
            args.api_base.rstrip("/"),
            args.league,
            include_uniques=include_uniques,
            max_workers=max(1, args.max_workers),
        )
        return PriceSourceResult(
            source=source,
            raw=raw,
            prices=prices,
            unique_categories=unique_categories,
            unique_items=unique_items,
            status=str(raw.get("status") or "ok"),
            warning=str(raw.get("warning") or ""),
        )
    if source == "poe-ninja":
        raw, prices = build_poe_ninja_currency_prices(
            client,
            args.poe_ninja_currency_url,
            args.poe_ninja_api_url,
            args.poe_ninja_league,
            args.poe_ninja_item_api_url,
        )
        return PriceSourceResult(
            source=source,
            raw=raw,
            prices=prices,
            status=str(raw.get("status") or "ok"),
            warning=str(raw.get("warning") or ""),
        )
    if source == "poe2db-economy":
        raw, prices = build_poe2db_economy_prices(
            client,
            args.poe2db_economy_us_url,
            args.poe2db_economy_cn_url,
        )
        status = str(raw.get("status") or "ok")
        if status not in {"ok", "partial"}:
            raise ValueError(f"invalid Poe2DB Economy source status: {status}")
        return PriceSourceResult(
            source=source,
            raw=raw,
            prices=prices,
            status=status,
            warning=str(raw.get("warning") or ""),
        )
    raise ValueError(f"unknown price source: {source}")


def price_source_result_is_usable(result: PriceSourceResult) -> bool:
    return (
        result.status in {"ok", "partial"}
        and result.health_state not in {"empty", "incompatible", "failed"}
        and bool(result.prices)
    )


def price_source_health_item_names(
    prices: dict[str, PriceObservation] | None,
) -> list[str]:
    names: list[str] = []
    for api_id, observation in (prices or {}).items():
        if api_id == "divine":
            names.append("Divine Orb")
        elif api_id == "exalted":
            names.append("Exalted Orb")
        else:
            names.append(observation.en_name)
    return names


def attach_price_source_health(result: PriceSourceResult) -> PriceSourceResult:
    """Attach a provider-neutral health contract without changing usable data."""

    raw = result.raw if isinstance(result.raw, dict) else {}
    prices = result.prices or {}
    discovered: list[str] = []
    enabled: list[str] = []
    succeeded: list[str] = []
    failed: list[str] = []
    freshness_timestamp: Any = None
    key_fields: tuple[str, ...] = ()

    if result.source == "poe2scout":
        discovered = [str(value) for value in raw.get("discovered_categories") or []]
        enabled_unique = [
            str(value) for value in raw.get("enabled_unique_categories") or []
        ]
        failed = [str(value) for value in raw.get("failed_unique_categories") or []]
        discovered = sorted(set(discovered).union(enabled_unique).union(failed))
        enabled = list(discovered)
        succeeded = [value for value in discovered if value not in set(failed)]
        snapshot = raw.get("exchange_snapshot") or {}
        if isinstance(snapshot, dict):
            freshness_timestamp = snapshot.get("Epoch", snapshot.get("epoch"))
        key_fields = (
            "CurrencyOne",
            "CurrencyTwo",
            "RelativePrice",
            "ValueTraded",
        )
    elif result.source == "poe-ninja":
        discovered = [str(value) for value in raw.get("discovered_categories") or []]
        enabled = [str(value) for value in raw.get("enabled_categories") or discovered]
        succeeded = [str(value) for value in raw.get("healthy_categories") or []]
        failed = [str(value) for value in raw.get("failed_categories") or []]
        key_fields = ("core", "lines", "items", "primaryValue")
    elif result.source == "poe2db-economy":
        discovered = [str(value) for value in raw.get("discovered_categories") or []]
        enabled = [str(value) for value in raw.get("enabled_categories") or discovered]
        succeeded = [str(value) for value in raw.get("healthy_categories") or []]
        failed = [str(value) for value in raw.get("failed_categories") or []]
        key_fields = ("page", "us_rows", "cn_rows", "matched_rows")

    health = evaluate_source_health(
        result.source,
        raw,
        expected_root="object",
        item_count=len(prices),
        match_count=len(prices),
        item_names=price_source_health_item_names(prices),
        # Divine is the only runtime conversion prerequisite. Exalted is the
        # implicit unit (1E) and the stricter live audit still checks both rows.
        required_references=("Divine Orb",),
        discovered_categories=discovered,
        enabled_categories=enabled,
        succeeded_categories=succeeded,
        failed_categories=failed,
        freshness_timestamp=freshness_timestamp,
        max_age_seconds=48 * 60 * 60 if freshness_timestamp is not None else None,
        key_fields=key_fields,
    )
    result.health_state = health.state
    result.health = health.to_dict()
    if result.raw is not None:
        result.raw["source_health"] = result.health

    if health.is_failure:
        issue_text = "; ".join(
            issue.get("message", "") for issue in result.health.get("issues", [])
        )
        result.status = "failed"
        result.warning = "; ".join(
            value for value in (result.warning, issue_text) if value
        )
    elif health.state == "partial" and result.status == "ok":
        result.status = "partial"
    return result


def try_fetch_price_source(
    source: str,
    client: RetryingRequests,
    args: argparse.Namespace,
    include_uniques: bool,
    out_dir: Path,
    primary: bool = False,
) -> PriceSourceResult:
    progress(f"价格源 {price_source_label(source)}：开始获取")
    try:
        result = attach_price_source_health(
            fetch_price_source(source, client, args, include_uniques)
        )
        price_count = len(result.prices or {})
        if result.status == "failed":
            progress(
                f"价格源 {price_source_label(source)}：健康校验未通过 "
                f"({price_count} 条价格)"
            )
        elif result.status == "partial":
            progress(f"价格源 {price_source_label(source)}：部分成功 ({price_count} 条价格)")
            if result.warning:
                print(f"warning: {result.warning}", file=sys.stderr)
        else:
            progress(f"价格源 {price_source_label(source)}：获取成功 ({price_count} 条价格)")
        if result.raw is not None:
            (out_dir / fallback_raw_filename(source, primary=primary)).write_text(
                json.dumps(result.raw, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        return result
    except Exception as exc:
        warning = (
            f"price source {source} failed; "
            f"{type(exc).__name__}: {exc}"
        )
        progress(f"价格源 {price_source_label(source)}：获取失败，准备尝试下一个可用数据源")
        print(f"warning: {warning}", file=sys.stderr)
        (out_dir / fallback_error_filename(source, primary=primary)).write_text(
            json.dumps(
                {
                    "source": source,
                    "status": "failed",
                    "error": warning,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        health = failed_source_health(source, exc).to_dict()
        return PriceSourceResult(
            source=source,
            status="failed",
            warning=warning,
            health_state="failed",
            health=health,
        )


def fetch_poecurrency_summary(
    client: RetryingRequests, summary_url: str
) -> list[dict[str, Any]]:
    data = client.get_json(summary_url)
    return normalize_poecurrency_summary(data)


def fetch_unique_categories(
    client: RetryingRequests, api_base: str, league: str
) -> list[dict[str, Any]]:
    data = client.get_json(f"{api_base}/poe2/Leagues/{league}/Items/Categories")
    if not isinstance(data, dict):
        raise ValueError("poe2scout unique category response root is not an object")
    categories = data.get("UniqueCategories") or []
    if not isinstance(categories, list) or any(
        not isinstance(category, dict) for category in categories
    ):
        raise ValueError("poe2scout UniqueCategories is not an array of objects")
    return categories


def fetch_unique_category_items(
    client: RetryingRequests,
    api_base: str,
    league: str,
    category: str,
    per_page: int = 100,
) -> list[dict[str, Any]]:
    progress(f"poe2scout：开始抓传奇分类 {category}")
    all_items: list[dict[str, Any]] = []
    page = 1
    while True:
        query = urllib.parse.urlencode(
            {
                "Category": category,
                "ReferenceCurrency": "exalted",
                "Page": page,
                "PerPage": per_page,
                "DataPoints": 7,
                "FrequencyHours": 24,
            }
        )
        data = client.get_json(
            f"{api_base}/poe2/Leagues/{league}/Uniques/ByCategory?{query}"
        )
        if not isinstance(data, dict):
            raise ValueError(
                f"poe2scout unique category {category} response root is not an object"
            )
        items = data.get("Items") or []
        if not isinstance(items, list) or any(
            not isinstance(item, dict) for item in items
        ):
            raise ValueError(
                f"poe2scout unique category {category} Items is not an array of objects"
            )
        all_items.extend(items)

        total_pages = int(data.get("Pages") or 1)
        total_items = int(data.get("Total") or 0)
        progress(
            f"poe2scout：传奇分类 {category} 第 {page}/{total_pages} 页完成 "
            f"(累计 {len(all_items)}/{total_items or '?'})"
        )
        if page >= total_pages:
            break
        if total_items and len(all_items) >= total_items:
            break
        if not items:
            break
        page += 1
    return all_items


def fetch_unique_items(
    client: RetryingRequests,
    api_base: str,
    league: str,
    max_workers: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    categories = [
        dict(category)
        for category in fetch_unique_categories(client, api_base, league)
        if category.get("ApiId") in DEFAULT_UNIQUE_CATEGORIES
    ]
    progress(f"poe2scout：发现 {len(categories)} 个传奇装备分类")
    all_items: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
        future_to_category = {
            pool.submit(
                fetch_unique_category_items,
                client,
                api_base,
                league,
                category["ApiId"],
            ): category
            for category in categories
            if category.get("ApiId")
        }
        completed = 0
        for future in as_completed(future_to_category):
            category = future_to_category[future]
            try:
                items = future.result()
                if not items:
                    raise ValueError("unique category returned no items")
                category["_fetch_status"] = "ok"
                category["_fetch_items"] = len(items)
                all_items.extend(items)
                state = f"完成 ({len(items)} 件)"
            except Exception as exc:
                category["_fetch_status"] = "failed"
                category["_fetch_items"] = 0
                category["_fetch_error"] = f"{type(exc).__name__}: {exc}"
                state = "失败"
            completed += 1
            progress(
                "poe2scout："
                f"{completed}/{len(future_to_category)} 传奇分类 "
                f"{category.get('ApiId')} {state}"
            )
    return categories, all_items


def to_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        parsed = Decimal(str(value))
        return parsed if parsed.is_finite() else default
    except (InvalidOperation, TypeError, ValueError):
        return default


def normalize_market_name(value: str) -> str:
    value = html.unescape(str(value)).strip().lower()
    value = value.replace("（", "(").replace("）", ")")
    return re.sub(r"[\s\u3000]+", "", value)


CN_DIVINE_NORMALIZED = {normalize_market_name(name) for name in CN_DIVINE_NAMES}
CN_EXALTED_NORMALIZED = {normalize_market_name(name) for name in CN_EXALTED_NAMES}

POECURRENCY_CATEGORY_KEYS = ("category_label", "category", "label", "name")
POECURRENCY_ITEMS_KEYS = ("items", "data", "list", "children")
POECURRENCY_NAME_KEYS = ("item_name", "name", "itemName", "item")
POECURRENCY_LATEST_BUY_KEYS = ("latest_buy1", "latest_buy", "buy1", "buy_price")
POECURRENCY_LATEST_SELL_KEYS = ("latest_sell1", "latest_sell", "sell1", "sell_price")
POECURRENCY_AVG_BUY_KEYS = ("buy_avg", "avg_buy", "buyAverage", "buy")
POECURRENCY_AVG_SELL_KEYS = ("sell_avg", "avg_sell", "sellAverage", "sell")
POECURRENCY_PREV_BUY_KEYS = ("prev_buy1", "previous_buy1", "prev_buy")
POECURRENCY_ENGLISH_NAME_KEYS = (
    "engname",
    "english_name",
    "englishName",
    "en_name",
)
POECURRENCY_LATEST_DATETIME_KEYS = (
    "latest_datetime",
    "latestDateTime",
    "latest_time",
    "datetime",
)
POECURRENCY_PREV_BUY_DATETIME_KEYS = (
    "prev_buy1_datetime",
    "prevBuy1Datetime",
    "previous_buy1_datetime",
    "prev_buy_datetime",
)
POECURRENCY_BUY_AVG_YESTERDAY_KEYS = (
    "buy_avg_yesterday",
    "buyAvgYesterday",
    "yesterday_buy_avg",
)
POECURRENCY_SELL_AVG_YESTERDAY_KEYS = (
    "sell_avg_yesterday",
    "sellAvgYesterday",
    "yesterday_sell_avg",
)
POECURRENCY_BUY_AVG_RATIO_KEYS = (
    "buy_avg_ratio",
    "buyAvgRatio",
)
POECURRENCY_SELL_AVG_RATIO_KEYS = (
    "sell_avg_ratio",
    "sellAvgRatio",
)
POECURRENCY_ANOMALY_COUNT_KEYS = (
    "anomaly_count",
    "anomalyCount",
)
POECURRENCY_ERROR_KEYS = ("error", "has_error", "hasError")
POECURRENCY_ERROR_INFO_KEYS = ("error_info", "errorInfo", "error_message")
POECURRENCY_SOURCE_TIMEZONE = timezone(timedelta(hours=8))
POECURRENCY_QUALITY_STALE_HOURS = Decimal("24")


def poecurrency_api_id(name: str) -> str:
    normalized = normalize_market_name(name)
    if normalized in CN_DIVINE_NORMALIZED:
        return "divine"
    if normalized in CN_EXALTED_NORMALIZED:
        return "exalted"
    return f"cn:{normalized}"


def first_present(mapping: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            return value
    return None


def normalize_poecurrency_summary(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        categories = first_present(data, ("value", "data", "items", "list", "result"))
    else:
        categories = data
    if not isinstance(categories, list):
        raise ValueError("poecurrency summary response must contain a category list")

    normalized: list[dict[str, Any]] = []
    for category in categories:
        if not isinstance(category, dict):
            continue
        label = str(first_present(category, POECURRENCY_CATEGORY_KEYS) or "").strip()
        items = first_present(category, POECURRENCY_ITEMS_KEYS) or []
        if not isinstance(items, list):
            continue

        normalized_items: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            normalized_item = dict(item)
            name = str(first_present(item, POECURRENCY_NAME_KEYS) or "").strip()
            if name:
                normalized_item["item_name"] = name
            for target, keys in (
                ("latest_buy1", POECURRENCY_LATEST_BUY_KEYS),
                ("latest_sell1", POECURRENCY_LATEST_SELL_KEYS),
                ("buy_avg", POECURRENCY_AVG_BUY_KEYS),
                ("sell_avg", POECURRENCY_AVG_SELL_KEYS),
                ("prev_buy1", POECURRENCY_PREV_BUY_KEYS),
                ("engname", POECURRENCY_ENGLISH_NAME_KEYS),
                ("latest_datetime", POECURRENCY_LATEST_DATETIME_KEYS),
                ("prev_buy1_datetime", POECURRENCY_PREV_BUY_DATETIME_KEYS),
                ("buy_avg_yesterday", POECURRENCY_BUY_AVG_YESTERDAY_KEYS),
                ("sell_avg_yesterday", POECURRENCY_SELL_AVG_YESTERDAY_KEYS),
                ("buy_avg_ratio", POECURRENCY_BUY_AVG_RATIO_KEYS),
                ("sell_avg_ratio", POECURRENCY_SELL_AVG_RATIO_KEYS),
                ("anomaly_count", POECURRENCY_ANOMALY_COUNT_KEYS),
                ("error", POECURRENCY_ERROR_KEYS),
                ("error_info", POECURRENCY_ERROR_INFO_KEYS),
            ):
                value = first_present(item, keys)
                if value is not None:
                    normalized_item[target] = value
            normalized_items.append(normalized_item)

        normalized.append({"category_label": label, "items": normalized_items})
    return normalized


def poecurrency_raw_unit(item: dict[str, Any]) -> str:
    for key in ("currency_unit", "unit"):
        value = item.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def poecurrency_item_unit(item: dict[str, Any]) -> str:
    raw_unit = poecurrency_raw_unit(item).lower()
    if raw_unit in {"d", "divine", "divine orb", "divine_orb", "神圣石", "神圣宝珠"}:
        return "d"
    if raw_unit in {"e", "exalted", "exalted orb", "exalted_orb", "崇高石", "崇高宝珠"}:
        return "e"
    if raw_unit:
        return ""

    display = str(
        item.get("display")
        or item.get("display_price")
        or item.get("price_display")
        or ""
    ).strip().lower()
    if display.endswith("d"):
        return "d"
    return "e"


def poecurrency_explicit_exalted_price(item: dict[str, Any]) -> tuple[Decimal, str]:
    for field_name in ("e", "price_e", "exalted", "exalted_price"):
        price = to_decimal(item.get(field_name))
        if price > 0:
            return price, field_name
    return Decimal("0"), ""


def choose_poecurrency_pair_price(
    buy_price: Decimal,
    sell_price: Decimal,
    buy_field: str,
    sell_field: str,
) -> tuple[Decimal, str]:
    if buy_price > 0 and sell_price > 0:
        high = max(buy_price, sell_price)
        low = min(buy_price, sell_price)
        ratio = high / low
        if ratio <= CN_TRUSTED_BUY_SELL_RATIO:
            return (buy_price * sell_price).sqrt(), f"geo_{buy_field}_{sell_field}"
        if buy_price <= sell_price:
            return buy_price, f"{buy_field}_conservative_spread_gt_5x"
        return sell_price, f"{sell_field}_conservative_spread_gt_5x"
    if sell_price > 0:
        return sell_price, f"{sell_field}_only"
    if buy_price > 0:
        return buy_price, f"{buy_field}_only"
    return Decimal("0"), ""


def choose_poecurrency_pair_price_with_reference(
    buy_price: Decimal,
    sell_price: Decimal,
    buy_field: str,
    sell_field: str,
    reference_price: Decimal,
    reference_field: str,
) -> tuple[Decimal, str]:
    if buy_price > 0 and sell_price > 0:
        ratio = decimal_spread_ratio(buy_price, sell_price)
        if ratio > CN_TRUSTED_BUY_SELL_RATIO and reference_price > 0:
            price, field = closest_positive_to_reference(
                reference_price,
                [(buy_price, buy_field), (sell_price, sell_field)],
            )
            if decimal_spread_ratio(price, reference_price) <= CN_TRUSTED_BUY_SELL_RATIO:
                return price, f"{field}_closest_to_{reference_field}_spread_gt_5x"
            if reference_field.startswith("geo_"):
                return reference_price, f"{reference_field}_latest_spread_avg_fallback"
    return choose_poecurrency_pair_price(
        buy_price, sell_price, buy_field, sell_field
    )


def decimal_has_fraction(value: Decimal) -> bool:
    return value > 0 and value != value.to_integral_value()


def poecurrency_digit_shifted_divine_pair_price(
    buy_price: Decimal,
    sell_price: Decimal,
    buy_field: str,
    sell_field: str,
) -> tuple[Decimal, str]:
    if buy_price <= 0 or sell_price <= 0:
        return Decimal("0"), ""
    high_price = max(buy_price, sell_price)
    low_price = min(buy_price, sell_price)
    if not decimal_has_fraction(low_price):
        return Decimal("0"), ""
    ratio = decimal_spread_ratio(high_price, low_price)
    if ratio < Decimal("20") or ratio > Decimal("200"):
        return Decimal("0"), ""
    if high_price < Decimal("50") or high_price > Decimal("1000"):
        return Decimal("0"), ""

    scaled_high = high_price / Decimal("100")
    if decimal_spread_ratio(low_price, scaled_high) > CN_TRUSTED_BUY_SELL_RATIO:
        return Decimal("0"), ""

    high_field = buy_field if buy_price >= sell_price else sell_field
    low_field = sell_field if buy_price >= sell_price else buy_field
    return (
        (low_price * scaled_high).sqrt(),
        f"geo_{low_field}_{high_field}_d_digit_shift_100x",
    )


def poecurrency_item_has_error(item: dict[str, Any]) -> bool:
    raw_error = item.get("error")
    if isinstance(raw_error, bool):
        return raw_error
    if str(raw_error).strip().lower() in {"1", "true", "yes"}:
        return True
    return bool(str(item.get("error_info") or "").strip())


def decimal_spread_ratio(left: Decimal, right: Decimal) -> Decimal:
    if left <= 0 or right <= 0:
        return Decimal("0")
    return max(left, right) / min(left, right)


def closest_positive_to_reference(
    reference: Decimal, candidates: list[tuple[Decimal, str]]
) -> tuple[Decimal, str]:
    positive = [(price, field) for price, field in candidates if price > 0]
    if not positive:
        return Decimal("0"), ""
    if reference <= 0:
        return max(positive, key=lambda item: item[0])
    return min(positive, key=lambda item: decimal_spread_ratio(item[0], reference))


def poecurrency_avg_price(item: dict[str, Any]) -> tuple[Decimal, str]:
    buy_avg = to_decimal(item.get("buy_avg"))
    sell_avg = to_decimal(item.get("sell_avg"))
    return choose_poecurrency_pair_price(
        buy_avg, sell_avg, "buy_avg", "sell_avg"
    )


def poecurrency_yesterday_avg_price(item: dict[str, Any]) -> tuple[Decimal, str]:
    buy_avg = to_decimal(item.get("buy_avg_yesterday"))
    sell_avg = to_decimal(item.get("sell_avg_yesterday"))
    return choose_poecurrency_pair_price(
        buy_avg,
        sell_avg,
        "buy_avg_yesterday",
        "sell_avg_yesterday",
    )


def poecurrency_item_price(item: dict[str, Any]) -> tuple[Decimal, str]:
    avg_price, avg_field = poecurrency_avg_price(item)
    unit = poecurrency_item_unit(item)
    latest_buy = to_decimal(item.get("latest_buy1"))
    latest_sell = to_decimal(item.get("latest_sell1"))
    if unit == "d":
        shifted_price, shifted_field = poecurrency_digit_shifted_divine_pair_price(
            latest_buy, latest_sell, "latest_buy1", "latest_sell1"
        )
        if shifted_price > 0:
            return shifted_price, shifted_field
        latest_price, latest_field = choose_poecurrency_pair_price(
            latest_buy, latest_sell, "latest_buy1", "latest_sell1"
        )
        if latest_price > 0 and not latest_field.endswith("spread_gt_5x"):
            return latest_price, latest_field

    if poecurrency_item_has_error(item):
        if avg_price > 0:
            return avg_price, f"{avg_field}_error_fallback"
        prev_buy = to_decimal(item.get("prev_buy1"))
        if prev_buy > 0:
            return prev_buy, "prev_buy1_error_fallback"

    latest_price, latest_field = choose_poecurrency_pair_price_with_reference(
        latest_buy,
        latest_sell,
        "latest_buy1",
        "latest_sell1",
        avg_price,
        avg_field,
    )
    if latest_price > 0:
        return latest_price, latest_field

    if avg_price > 0:
        return avg_price, avg_field
    return poecurrency_yesterday_avg_price(item)


def poecurrency_divine_price(item: dict[str, Any]) -> tuple[Decimal, str]:
    latest_buy = to_decimal(item.get("latest_buy1"))
    latest_sell = to_decimal(item.get("latest_sell1"))
    buy_avg = to_decimal(item.get("buy_avg"))
    sell_avg = to_decimal(item.get("sell_avg"))
    stable_avg, stable_avg_field = (
        (buy_avg, "buy_avg")
        if buy_avg > 0
        else (sell_avg, "sell_avg")
    )

    if poecurrency_item_has_error(item):
        if stable_avg > 0:
            return stable_avg, f"{stable_avg_field}_divine_error_fallback"
        prev_buy = to_decimal(item.get("prev_buy1"))
        if prev_buy > 0:
            return prev_buy, "prev_buy1_divine_error_fallback"

    if (
        latest_buy > 0
        and latest_sell > 0
        and decimal_spread_ratio(latest_buy, latest_sell) > CN_TRUSTED_BUY_SELL_RATIO
    ):
        price, field = closest_positive_to_reference(
            stable_avg,
            [(latest_buy, "latest_buy1"), (latest_sell, "latest_sell1")],
        )
        if price > 0:
            return price, f"{field}_divine_spread_fallback"

    if (
        latest_buy > 0
        and stable_avg > 0
        and decimal_spread_ratio(latest_buy, stable_avg) > CN_TRUSTED_BUY_SELL_RATIO
    ):
        return stable_avg, f"{stable_avg_field}_divine_latest_outlier_fallback"

    if latest_buy > 0:
        return latest_buy, "latest_buy1_divine_ratio"
    if latest_sell > 0:
        return latest_sell, "latest_sell1_divine_ratio"
    if stable_avg > 0:
        return stable_avg, f"{stable_avg_field}_divine_ratio"
    yesterday_price, yesterday_field = poecurrency_yesterday_avg_price(item)
    if yesterday_price > 0:
        return yesterday_price, f"{yesterday_field}_divine_yesterday_fallback"
    return Decimal("0"), ""


def poecurrency_price_to_exalted(
    price: Decimal, unit: str, divine_exalted: Decimal
) -> Decimal:
    if price <= 0:
        return Decimal("0")
    if unit == "d":
        if divine_exalted <= 0:
            return Decimal("0")
        return price * divine_exalted
    return price


def poecurrency_anomaly_count(item: dict[str, Any]) -> int:
    value = to_decimal(item.get("anomaly_count"))
    if not value.is_finite():
        return 0
    try:
        return max(0, int(value))
    except (OverflowError, ValueError):
        return 0


def parse_poecurrency_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=POECURRENCY_SOURCE_TIMEZONE)
    return parsed.astimezone(POECURRENCY_SOURCE_TIMEZONE)


def poecurrency_serializable_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def poecurrency_item_metadata(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: poecurrency_serializable_value(item.get(key))
        for key in (
            "engname",
            "latest_datetime",
            "prev_buy1_datetime",
            "buy_avg_yesterday",
            "sell_avg_yesterday",
            "buy_avg_ratio",
            "sell_avg_ratio",
            "anomaly_count",
            "error",
            "error_info",
        )
        if item.get(key) is not None
    }


def poecurrency_quality_rank(
    quality_flags: tuple[str, ...] | list[str],
    source_timestamp: str,
    price: Decimal,
) -> tuple[int, int, int, int, int, float, Decimal]:
    """Prefer trustworthy/fresh observations before using price as a tiebreaker."""
    flags = set(quality_flags)
    parsed = parse_poecurrency_datetime(source_timestamp)
    timestamp_rank = parsed.timestamp() if parsed is not None else float("-inf")
    return (
        int("error" not in flags),
        int("stale" not in flags),
        int("anomaly" not in flags),
        int("unit_defaulted" not in flags),
        int("yesterday_fallback" not in flags),
        timestamp_rank,
        price,
    )


def collect_poecurrency_observations_with_quality(
    summary: Any,
    *,
    now: datetime | None = None,
    stale_after_hours: Decimal = POECURRENCY_QUALITY_STALE_HOURS,
) -> tuple[dict[str, PriceObservation], dict[str, Any]]:
    categories = normalize_poecurrency_summary(summary)
    current_time = now or datetime.now(POECURRENCY_SOURCE_TIMEZONE)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=POECURRENCY_SOURCE_TIMEZONE)
    else:
        current_time = current_time.astimezone(POECURRENCY_SOURCE_TIMEZONE)
    stale_after = timedelta(seconds=float(stale_after_hours * Decimal("3600")))

    candidates: list[dict[str, Any]] = []
    divine_exalted = Decimal("0")
    schema_fields: set[str] = set()
    latest_times: list[datetime] = []
    previous_times: list[datetime] = []
    source_times: list[datetime] = []
    quality: dict[str, Any] = {
        "category_count": len(categories),
        "categories": [],
        "category_stats": [],
        "empty_categories": [],
        "field_set": [],
        "item_count": 0,
        "named_item_count": 0,
        "candidate_count": 0,
        "observation_count": 0,
        "valid_price_items": 0,
        "error_items": 0,
        "anomaly_items": 0,
        "anomaly_total": 0,
        "unknown_unit_items": 0,
        "unknown_units": [],
        "missing_unit_items": 0,
        "stale_items": 0,
        "invalid_timestamp_items": 0,
        "latest_datetime_items": 0,
        "prev_buy1_datetime_items": 0,
        "english_alias_items": 0,
        "english_alias_matches": 0,
        "localized_name_matches": 0,
        "yesterday_fallback_items": 0,
        "skipped_no_name": 0,
        "skipped_no_price": 0,
        "skipped_unknown_unit": 0,
        "skipped_missing_divine_ratio": 0,
        "latest_datetime_min": "",
        "latest_datetime_max": "",
        "prev_buy1_datetime_min": "",
        "prev_buy1_datetime_max": "",
        "source_timestamp_min": "",
        "source_timestamp_max": "",
        "stale_after_hours": float(stale_after_hours),
    }
    category_labels: list[str] = []
    empty_category_labels: list[str] = []
    category_stats: list[dict[str, Any]] = []
    unknown_units: set[str] = set()

    for category in categories:
        category_label = str(category.get("category_label") or "").strip()
        if category_label and category_label not in category_labels:
            category_labels.append(category_label)
        items = category.get("items") or []
        item_count = len(items) if isinstance(items, list) else 0
        category_state = "ok" if item_count > 0 else "empty"
        category_stats.append(
            {
                "category": category_label,
                "items": item_count,
                "status": category_state,
            }
        )
        if category_label and category_state == "empty":
            empty_category_labels.append(category_label)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            quality["item_count"] += 1
            schema_fields.update(str(key) for key in item)
            name = str(item.get("item_name") or "").strip()
            if not name:
                quality["skipped_no_name"] += 1
                continue
            quality["named_item_count"] += 1

            english_name = str(item.get("engname") or "").strip()
            if english_name:
                quality["english_alias_items"] += 1

            item_has_error = poecurrency_item_has_error(item)
            anomaly_count = poecurrency_anomaly_count(item)
            if item_has_error:
                quality["error_items"] += 1
            if anomaly_count:
                quality["anomaly_items"] += 1
                quality["anomaly_total"] += anomaly_count

            latest_datetime_raw = str(item.get("latest_datetime") or "").strip()
            previous_datetime_raw = str(item.get("prev_buy1_datetime") or "").strip()
            latest_datetime = parse_poecurrency_datetime(latest_datetime_raw)
            previous_datetime = parse_poecurrency_datetime(previous_datetime_raw)
            timestamp_invalid = False
            if latest_datetime_raw:
                quality["latest_datetime_items"] += 1
                if latest_datetime is None:
                    timestamp_invalid = True
                else:
                    latest_times.append(latest_datetime)
                    source_times.append(latest_datetime)
            if previous_datetime_raw:
                quality["prev_buy1_datetime_items"] += 1
                if previous_datetime is None:
                    timestamp_invalid = True
                else:
                    previous_times.append(previous_datetime)
                    source_times.append(previous_datetime)
            if timestamp_invalid:
                quality["invalid_timestamp_items"] += 1

            source_datetime = latest_datetime or previous_datetime
            error_info = str(item.get("error_info") or "").strip().lower()
            stale_from_error = any(
                marker in error_info for marker in ("过时", "stale", "outdated")
            )
            is_stale = stale_from_error or bool(
                source_datetime is not None
                and current_time - source_datetime > stale_after
            )
            if is_stale:
                quality["stale_items"] += 1

            raw_unit = poecurrency_raw_unit(item)
            if not raw_unit:
                quality["missing_unit_items"] += 1

            api_id = poecurrency_api_id(name)
            unit = poecurrency_item_unit(item)
            if not unit:
                quality["unknown_unit_items"] += 1
                quality["skipped_unknown_unit"] += 1
                unknown_units.add(raw_unit)
                continue
            explicit_exalted, explicit_field = poecurrency_explicit_exalted_price(item)
            if explicit_exalted > 0:
                price = explicit_exalted
                price_field = f"{explicit_field}_api_exalted"
                unit = "e"
            elif api_id == "divine":
                price, price_field = poecurrency_divine_price(item)
            else:
                price, price_field = poecurrency_item_price(item)
            if price <= 0:
                quality["skipped_no_price"] += 1
                continue

            quality_flags: list[str] = []
            if item_has_error:
                quality_flags.append("error")
            if anomaly_count:
                quality_flags.append("anomaly")
            if is_stale:
                quality_flags.append("stale")
            if not raw_unit:
                quality_flags.append("unit_defaulted")
            if "yesterday" in price_field:
                quality["yesterday_fallback_items"] += 1
                quality_flags.append("yesterday_fallback")

            candidates.append(
                {
                    "api_id": api_id,
                    "name": name,
                    "category_label": category_label,
                    "price": price,
                    "price_field": price_field,
                    "unit": unit,
                    "english_name": english_name,
                    "source_timestamp": latest_datetime_raw or previous_datetime_raw,
                    "quality_flags": tuple(quality_flags),
                    "source_metadata": poecurrency_item_metadata(item),
                }
            )
            quality["valid_price_items"] += 1

    quality["categories"] = category_labels
    quality["category_stats"] = category_stats
    quality["empty_categories"] = empty_category_labels
    quality["field_set"] = sorted(schema_fields)
    quality["unknown_units"] = sorted(unit for unit in unknown_units if unit)
    for prefix, values in (
        ("latest_datetime", latest_times),
        ("prev_buy1_datetime", previous_times),
        ("source_timestamp", source_times),
    ):
        if values:
            quality[f"{prefix}_min"] = min(values).isoformat(timespec="seconds")
            quality[f"{prefix}_max"] = max(values).isoformat(timespec="seconds")

    divine_candidates = [
        candidate
        for candidate in candidates
        if candidate["api_id"] == "divine" and candidate["unit"] == "e"
    ]
    if divine_candidates:
        selected_divine = max(
            divine_candidates,
            key=lambda candidate: poecurrency_quality_rank(
                candidate["quality_flags"],
                candidate["source_timestamp"],
                candidate["price"],
            ),
        )
        divine_exalted = selected_divine["price"]

    best: dict[str, PriceObservation] = {}
    for candidate in candidates:
        price = candidate["price"]
        unit = candidate["unit"]
        api_id = candidate["api_id"]
        price_exalted = poecurrency_price_to_exalted(price, unit, divine_exalted)
        if api_id == "divine" and unit == "d" and divine_exalted > 0:
            price_exalted = divine_exalted
        if price_exalted <= 0:
            quality["skipped_missing_divine_ratio"] += 1
            continue

        unit_note = unit
        if unit == "d":
            unit_note = f"d_to_e@{divine_exalted}"
        obs = PriceObservation(
            api_id=api_id,
            en_name=candidate["name"],
            category=f"cn:{candidate['category_label']}",
            price_exalted=price_exalted,
            value_traded=Decimal("0"),
            source_pair=(
                f"poecurrency.top/{candidate['category_label']}/"
                f"{candidate['price_field']}/{unit_note}"
            ),
            english_name=candidate["english_name"],
            source_timestamp=candidate["source_timestamp"],
            quality_flags=candidate["quality_flags"],
            source_metadata=candidate["source_metadata"],
        )
        old = best.get(api_id)
        if old is None or poecurrency_quality_rank(
            obs.quality_flags, obs.source_timestamp, obs.price_exalted
        ) > poecurrency_quality_rank(
            old.quality_flags, old.source_timestamp, old.price_exalted
        ):
            best[api_id] = obs

    if "divine" not in best and divine_exalted > 0:
        best["divine"] = PriceObservation(
            api_id="divine",
            en_name="Divine Orb",
            category="cn:currency",
            price_exalted=divine_exalted,
            value_traded=Decimal("0"),
            source_pair="poecurrency.top/divine/e",
        )
    quality["candidate_count"] = len(candidates)
    quality["observation_count"] = len(best)
    return best, quality


def collect_poecurrency_observations(
    summary: Any,
) -> dict[str, PriceObservation]:
    observations, _quality = collect_poecurrency_observations_with_quality(summary)
    return observations


def collect_price_observations(snapshot_pairs: list[dict[str, Any]]) -> dict[str, list[PriceObservation]]:
    by_api_id: dict[str, list[PriceObservation]] = {}
    for pair in snapshot_pairs:
        c1 = pair["CurrencyOne"]
        c2 = pair["CurrencyTwo"]
        pair_name = f"{c1['Text']} / {c2['Text']}"
        for currency_key, data_key in [
            ("CurrencyOne", "CurrencyOneData"),
            ("CurrencyTwo", "CurrencyTwoData"),
        ]:
            currency = pair[currency_key]
            side_data = pair[data_key]
            price = to_decimal(side_data.get("RelativePrice"))
            if price <= 0:
                continue
            value_traded = to_decimal(side_data.get("ValueTraded"))
            api_id = currency["ApiId"]
            by_api_id.setdefault(api_id, []).append(
                PriceObservation(
                    api_id=api_id,
                    en_name=currency["Text"],
                    category=currency.get("CategoryApiId") or "",
                    price_exalted=price,
                    value_traded=value_traded,
                    source_pair=pair_name,
                )
            )
    return by_api_id


def choose_best_prices(
    observations: dict[str, list[PriceObservation]],
    reference_currencies: list[dict[str, Any]],
) -> dict[str, PriceObservation]:
    best: dict[str, PriceObservation] = {}
    for api_id, items in observations.items():
        # Highest traded value tends to match the visible high-confidence market rows.
        best[api_id] = max(items, key=lambda item: (item.value_traded, item.price_exalted))

    for ref in reference_currencies:
        api_id = ref["ApiId"]
        if api_id not in best:
            best[api_id] = PriceObservation(
                api_id=api_id,
                en_name=ref["Text"],
                category="currency",
                price_exalted=to_decimal(ref.get("RelativePrice"), Decimal("1")),
                value_traded=Decimal("0"),
                source_pair="ReferenceCurrencies",
            )
        elif to_decimal(ref.get("RelativePrice")) == Decimal("1"):
            best[api_id] = PriceObservation(
                api_id=api_id,
                en_name=ref["Text"],
                category="currency",
                price_exalted=Decimal("1"),
                value_traded=Decimal("0"),
                source_pair="ReferenceCurrencies",
            )
    return best


def add_unique_observations(
    best: dict[str, PriceObservation], unique_items: list[dict[str, Any]]
) -> None:
    for item in unique_items:
        price = to_decimal(item.get("CurrentPrice"))
        if price <= 0:
            continue
        unique_id = item.get("UniqueItemId") or item.get("ItemId")
        name = (item.get("Name") or item.get("Text") or "").strip()
        if not unique_id or not name:
            continue
        api_id = f"unique:{unique_id}"
        best[api_id] = PriceObservation(
            api_id=api_id,
            en_name=name,
            category=f"unique:{item.get('CategoryApiId') or ''}",
            price_exalted=price,
            value_traded=to_decimal(item.get("CurrentQuantity")),
            source_pair=f"Unique/{item.get('CategoryApiId') or ''}",
        )


def price_observation_merge_key(obs: PriceObservation) -> str:
    if obs.api_id in {"divine", "exalted"}:
        return obs.api_id
    prefix = "unique" if obs.api_id.startswith("unique:") else "item"
    normalized = normalize_name(obs.en_name)
    return f"{prefix}:{normalized or obs.api_id}"


def merge_price_source_results(
    results: list[PriceSourceResult],
) -> dict[str, PriceObservation]:
    merged_by_key: dict[str, PriceObservation] = {}
    for result in results:
        for obs in (result.prices or {}).values():
            key = price_observation_merge_key(obs)
            if key not in merged_by_key:
                merged_by_key[key] = obs

    merged: dict[str, PriceObservation] = {}
    for obs in merged_by_key.values():
        if obs.api_id not in merged:
            merged[obs.api_id] = obs
    return merged


def divine_price_exalted(best: dict[str, PriceObservation]) -> Decimal:
    obs = best.get("divine")
    if obs and obs.price_exalted > 0:
        return obs.price_exalted
    raise ValueError("cannot determine real-time Divine/Exalted ratio from price source")


def divine_exalted_ratio_summary(divine_exalted: Decimal) -> dict[str, str]:
    return {
        "divine_orb": "1",
        "exalted_orb": str(divine_exalted),
        "text": f"1 Divine Orb = {divine_exalted} Exalted Orb",
    }


def format_price(price_exalted: Decimal, divine_exalted: Decimal) -> str:
    if price_exalted <= 0:
        return ""
    price_divine = price_exalted / divine_exalted if divine_exalted else Decimal("0")
    if price_divine >= Decimal("0.1"):
        return f"{price_divine.quantize(Decimal('0.01'))}D"
    if price_exalted >= Decimal("10"):
        return f"{price_exalted.quantize(Decimal('0.1'))}E"
    return f"{price_exalted.quantize(Decimal('0.01'))}E"


def is_reference_currency(obs: PriceObservation) -> bool:
    return obs.api_id in {"divine", "exalted"}


def apply_display_prices(
    prices: dict[str, PriceObservation], divine_exalted: Decimal
) -> None:
    for obs in prices.values():
        obs.display_price = "" if is_reference_currency(obs) else format_price(
            obs.price_exalted, divine_exalted
        )


def match_prices_to_base_items(
    prices: dict[str, PriceObservation],
    base_pairs: list[BaseItemPair],
    client: RetryingRequests,
    use_poe2db: bool,
    max_workers: int,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    # Several game metadata rows intentionally share one visible item name
    # (for example currency and quest aliases for pinnacle fragments). Keep
    # every alias so a price is not tied to whichever row happened to be last
    # in BaseItemTypes.
    by_en: dict[str, list[BaseItemPair]] = {}
    by_en_norm: dict[str, list[BaseItemPair]] = {}
    by_tc: dict[str, list[BaseItemPair]] = {}
    for pair in base_pairs:
        if pair.en_name:
            by_en.setdefault(pair.en_name, []).append(pair)
            normalized_en = normalize_name(pair.en_name)
            if normalized_en:
                by_en_norm.setdefault(normalized_en, []).append(pair)
        if pair.tc_name:
            by_tc.setdefault(pair.tc_name, []).append(pair)

    matched: list[dict[str, str]] = []
    missing: list[dict[str, str]] = []
    pending_poe2db: list[PriceObservation] = []

    for obs in prices.values():
        if obs.api_id.startswith("unique:"):
            continue
        if obs.price_exalted < Decimal("1") or not obs.display_price:
            continue
        pairs = by_en.get(obs.en_name) or by_en_norm.get(normalize_name(obs.en_name), [])
        price = obs.display_price
        if pairs and price:
            for pair in pairs:
                matched.append(
                    {
                        "metadata_path": pair.metadata_path,
                        "name": pair.tc_name,
                        "price": price,
                        "new_name": "",
                        "en_name": obs.en_name,
                        "api_id": obs.api_id,
                        "price_exalted": str(obs.price_exalted),
                        "source_pair": obs.source_pair,
                    }
                )
        elif use_poe2db and price:
            pending_poe2db.append(obs)
        else:
            missing.append(
                {
                    "api_id": obs.api_id,
                    "en_name": obs.en_name,
                    "reason": "not found in local BaseItemTypes",
                }
            )

    if pending_poe2db:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            future_to_obs = {
                pool.submit(fetch_poe2db_translation, client, obs.en_name): obs
                for obs in pending_poe2db
            }
            for future in as_completed(future_to_obs):
                obs = future_to_obs[future]
                price = obs.display_price
                try:
                    tc_name = future.result()
                except Exception:
                    tc_name = None
                pairs = by_tc.get(tc_name or "", [])
                if pairs and price:
                    for pair in pairs:
                        matched.append(
                            {
                                "metadata_path": pair.metadata_path,
                                "name": pair.tc_name,
                                "price": price,
                                "new_name": "",
                                "en_name": obs.en_name,
                                "api_id": obs.api_id,
                                "price_exalted": str(obs.price_exalted),
                                "source_pair": f"{obs.source_pair}; poe2db={tc_name}",
                            }
                        )
                else:
                    missing.append(
                        {
                            "api_id": obs.api_id,
                            "en_name": obs.en_name,
                            "poe2db_tw": tc_name or "",
                            "reason": "not found by poe2db/local TC name",
                        }
                    )

    # Same metadata can appear through several API ids; keep the highest price.
    dedup: dict[str, dict[str, str]] = {}
    for row in matched:
        old = dedup.get(row["metadata_path"])
        if old is None or Decimal(row["price_exalted"]) > Decimal(old["price_exalted"]):
            dedup[row["metadata_path"]] = row
    return sorted(dedup.values(), key=lambda r: r["name"]), missing


def match_cn_prices_to_base_items(
    prices: dict[str, PriceObservation],
    base_pairs: list[BaseItemPair],
    quality: dict[str, Any] | None = None,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    by_tc: dict[str, list[BaseItemPair]] = {}
    by_en: dict[str, list[BaseItemPair]] = {}

    def add_aliases(
        index: dict[str, list[BaseItemPair]],
        names: set[str],
        pair: BaseItemPair,
    ) -> None:
        for name in names:
            normalized = normalize_market_name(name)
            if normalized:
                index.setdefault(normalized, []).append(pair)

    for pair in base_pairs:
        add_aliases(by_tc, {pair.tc_name, strip_existing_price(pair.tc_name)}, pair)
        add_aliases(by_en, {pair.en_name, strip_existing_price(pair.en_name)}, pair)

    def select_localized_aliases(
        candidates: list[BaseItemPair], english_name: str
    ) -> list[BaseItemPair]:
        if len(candidates) <= 1:
            return candidates
        normalized_english = normalize_market_name(english_name)
        if normalized_english:
            english_matches = [
                pair
                for pair in candidates
                if normalize_market_name(pair.en_name) == normalized_english
            ]
            if english_matches:
                return english_matches

        candidate_english_names = {
            normalize_market_name(pair.en_name)
            for pair in candidates
            if pair.en_name
        }
        if len(candidate_english_names) > 1:
            # A localized translation collision is not enough evidence to
            # apply one market price to unrelated English items.
            return candidates[:1]
        return candidates

    matched: list[tuple[dict[str, str], str]] = []
    missing: list[dict[str, str]] = []
    for obs in prices.values():
        if obs.price_exalted < Decimal("1") or not obs.display_price:
            continue
        pairs = select_localized_aliases(
            by_tc.get(normalize_market_name(obs.en_name), []),
            obs.english_name,
        )
        match_method = "localized_name"
        if not pairs and obs.english_name:
            pairs = by_en.get(normalize_market_name(obs.english_name), [])
            match_method = "english_alias"
        if pairs:
            for pair in pairs:
                matched.append(
                    (
                        {
                            "metadata_path": pair.metadata_path,
                            "name": pair.tc_name,
                            "price": obs.display_price,
                            "new_name": "",
                            "en_name": obs.english_name or obs.en_name,
                            "api_id": obs.api_id,
                            "price_exalted": str(obs.price_exalted),
                            "source_pair": obs.source_pair,
                        },
                        match_method,
                    )
                )
        else:
            missing.append(
                {
                    "api_id": obs.api_id,
                    "en_name": obs.en_name,
                    "reason": (
                        "not found by localized name or poecurrency engname in local BaseItemTypes"
                        if obs.english_name
                        else "not found in local Simplified Chinese BaseItemTypes"
                    ),
                }
            )

    dedup: dict[str, dict[str, str]] = {}
    match_methods: dict[str, str] = {}
    for row, match_method in matched:
        old = dedup.get(row["metadata_path"])
        if old is None or Decimal(row["price_exalted"]) > Decimal(old["price_exalted"]):
            dedup[row["metadata_path"]] = row
            match_methods[row["metadata_path"]] = match_method
    if quality is not None:
        quality["localized_name_matches"] = sum(
            method == "localized_name" for method in match_methods.values()
        )
        quality["english_alias_matches"] = sum(
            method == "english_alias" for method in match_methods.values()
        )
        quality["unmatched_observations"] = len(missing)
    return sorted(dedup.values(), key=lambda r: r["name"]), missing


def merge_primary_with_fallback_rows(
    primary: list[dict[str, str]],
    fallback: list[dict[str, str]],
) -> tuple[list[dict[str, str]], int]:
    merged: dict[str, dict[str, str]] = {
        row["metadata_path"]: row for row in primary if row.get("metadata_path")
    }
    added = 0
    for row in fallback:
        metadata_path = row.get("metadata_path", "")
        if not metadata_path or metadata_path in merged:
            continue
        row = dict(row)
        label = "poe2db-economy" if "Poe2DB Economy" in row.get("source_pair", "") else "poe2scout"
        row["source_pair"] = f"{row.get('source_pair', '')}; fallback={label}"
        merged[metadata_path] = row
        added += 1
    return sorted(merged.values(), key=lambda r: r["name"]), added


def decimal_ratio(a: Decimal, b: Decimal) -> Decimal:
    if a <= 0 or b <= 0:
        return Decimal("0")
    high = max(a, b)
    low = min(a, b)
    return high / low


def cn_price_divine_value(row: dict[str, str], divine_exalted: Decimal) -> Decimal:
    price_exalted = to_decimal(row.get("price_exalted"))
    if price_exalted <= 0 or divine_exalted <= 0:
        return Decimal("0")
    return price_exalted / divine_exalted


def apply_high_value_reference_rows(
    primary: list[dict[str, str]],
    fallback: list[dict[str, str]],
    primary_divine_exalted: Decimal,
    fallback_divine_exalted: Decimal,
    min_divine: Decimal,
    max_ratio: Decimal,
) -> tuple[list[dict[str, str]], int]:
    if min_divine <= 0 or max_ratio <= 0:
        return primary, 0

    fallback_by_metadata = {
        row["metadata_path"]: row for row in fallback if row.get("metadata_path")
    }
    replaced = 0
    checked: list[dict[str, str]] = []
    for row in primary:
        metadata_path = row.get("metadata_path", "")
        fallback_row = fallback_by_metadata.get(metadata_path)
        if not fallback_row:
            checked.append(row)
            continue

        primary_divine = cn_price_divine_value(row, primary_divine_exalted)
        fallback_divine = cn_price_divine_value(fallback_row, fallback_divine_exalted)
        if (
            fallback_divine < min_divine
            or decimal_ratio(primary_divine, fallback_divine) <= max_ratio
        ):
            checked.append(row)
            continue

        replacement = dict(fallback_row)
        label = "poe2db-economy" if "Poe2DB Economy" in fallback_row.get("source_pair", "") else "poe2scout"
        replacement["source_pair"] = (
            f"{fallback_row.get('source_pair', '')}; "
            f"high_value_reference={label}; "
            f"cn_price={row.get('price', '')}; "
            f"cn_price_exalted={row.get('price_exalted', '')}; "
            f"cn_source={row.get('source_pair', '')}"
        )
        checked.append(replacement)
        replaced += 1

    return sorted(checked, key=lambda r: r["name"]), replaced


def fallback_rows_from_prices(
    source: str,
    prices: dict[str, PriceObservation],
    base_pairs: list[BaseItemPair],
    client: RetryingRequests,
    use_poe2db: bool,
    max_workers: int,
) -> tuple[list[dict[str, str]], list[dict[str, str]], Decimal]:
    divine_exalted = divine_price_exalted(prices)
    apply_display_prices(prices, divine_exalted)
    if source == "poe2db-economy":
        rows, missing = match_cn_prices_to_base_items(prices, base_pairs)
    else:
        rows, missing = match_prices_to_base_items(
            prices,
            base_pairs,
            client=client,
            use_poe2db=use_poe2db,
            max_workers=max(1, max_workers),
        )
    return rows, missing, divine_exalted


def apply_fallback_rows(
    primary_rows: list[dict[str, str]],
    fallback_rows_by_source: list[tuple[str, list[dict[str, str]]]],
) -> tuple[list[dict[str, str]], dict[str, int]]:
    rows = primary_rows
    counts: dict[str, int] = {}
    for source, fallback_rows in fallback_rows_by_source:
        rows, added = merge_primary_with_fallback_rows(rows, fallback_rows)
        counts[source] = added
    return rows, counts


def evaluate_local_match_gate(
    rows: list[dict[str, str]],
    base_pairs: list[BaseItemPair],
    *,
    enabled: bool,
    low_match_warning_count: int = 25,
) -> dict[str, Any]:
    if not enabled:
        return {"state": "not-applicable", "ratio": 0.0, "warning": ""}
    if not base_pairs:
        return {
            "state": "unavailable",
            "ratio": 0.0,
            "warning": (
                "local BaseItemTypes yielded no matchable rows; "
                "existing labels will be preserved"
            ),
        }
    if not rows:
        raise ValueError(
            "all enabled price sources produced zero matches for the current BaseItemTypes"
        )
    ratio = len(rows) / len(base_pairs) if base_pairs else 0.0
    if len(rows) < low_match_warning_count:
        return {
            "state": "degraded",
            "ratio": ratio,
            "warning": (
                f"local BaseItemTypes match count is unusually low ({len(rows)}); "
                "unmatched existing labels will be preserved"
            ),
        }
    return {"state": "ok", "ratio": ratio, "warning": ""}


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def run_patch_builder(
    patch_script: Path,
    tc_baseitems: Path,
    prices_csv: Path,
    output_zip: Path,
    report: Path,
    mode: str,
    patched_dat: Path | None,
    game_path: str | None,
    preserve_unmatched_existing_price: bool = False,
) -> None:
    progress("生成 BaseItemTypes 价格补丁包")
    cmd = [
        sys.executable,
        str(patch_script),
        "build",
        "--source",
        str(tc_baseitems),
        "--prices",
        str(prices_csv),
        "--output-zip",
        str(output_zip),
        "--report",
        str(report),
        "--mode",
        mode,
        "--keep-existing-price",
    ]
    if preserve_unmatched_existing_price:
        cmd.append("--preserve-unmatched-existing-price")
    if game_path:
        cmd.extend(["--game-path", game_path])
    if patched_dat:
        cmd.extend(["--patched-dat", str(patched_dat)])
    subprocess.run(cmd, check=True)
    progress("BaseItemTypes 价格补丁包生成完成")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch market prices and generate a PoE2 name-price patch."
    )
    parser.add_argument("--price-source", choices=PRICE_SOURCES, default="poe2scout")
    parser.add_argument("--api-base", default=DEFAULT_SCOUT_API)
    parser.add_argument("--poecurrency-summary-url", default=DEFAULT_POECURRENCY_SUMMARY_API)
    parser.add_argument("--poe-ninja-currency-url", default=DEFAULT_POE_NINJA_CURRENCY_URL)
    parser.add_argument("--poe-ninja-api-url", default=DEFAULT_POE_NINJA_API_URL)
    parser.add_argument("--poe-ninja-item-api-url", default=DEFAULT_POE_NINJA_ITEM_API_URL)
    parser.add_argument(
        "--poe-ninja-league",
        default=None,
        help=(
            "poe.ninja league name. By default the current softcore league is "
            "discovered from poe2scout, with a known-good fallback."
        ),
    )
    parser.add_argument("--poe2db-economy-us-url", default=DEFAULT_POE2DB_ECONOMY_US_URL)
    parser.add_argument("--poe2db-economy-cn-url", default=DEFAULT_POE2DB_ECONOMY_CN_URL)
    parser.add_argument(
        "--fallback-price-sources",
        default=",".join(FALLBACK_PRICE_SOURCES),
        help=(
            "Comma-separated fallback price sources used after the primary "
            "source fails or to fill missing international rows. Use none to disable."
        ),
    )
    parser.add_argument(
        "--cn-reference-source",
        choices=CN_REFERENCE_SOURCES,
        default="poe2scout",
        help=(
            "First international reference source used with poecurrency-cn. "
            "The configured fallback-price-sources are tried after it."
        ),
    )
    parser.add_argument(
        "--league",
        default=None,
        help=(
            "poe2scout league short name. By default the current softcore league "
            "is discovered automatically, with a known-good fallback."
        ),
    )
    parser.add_argument("--en-baseitems", type=Path, default=DEFAULT_EN_BASEITEMS)
    parser.add_argument("--tc-baseitems", type=Path, default=DEFAULT_TC_BASEITEMS)
    parser.add_argument("--en-words", type=Path, default=DEFAULT_EN_WORDS)
    parser.add_argument("--tc-words", type=Path, default=DEFAULT_TC_WORDS)
    parser.add_argument("--unique-gold-prices", type=Path, default=DEFAULT_UNIQUE_GOLD_PRICES)
    parser.add_argument("--out-dir", type=Path, default=Path("output/poe2_price_patch_latest"))
    parser.add_argument("--max-workers", type=int, default=12)
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument("--backoff", type=float, default=0.8)
    parser.add_argument(
        "--timeout",
        type=float,
        default=12.0,
        help="Wall-clock timeout in seconds for each HTTP attempt.",
    )
    parser.add_argument(
        "--request-time-budget",
        type=float,
        default=DEFAULT_REQUEST_TIME_BUDGET,
        help="Maximum wall-clock seconds per URL, including retries and backoff.",
    )
    parser.add_argument("--poe2db-fallback", action="store_true")
    parser.add_argument("--no-uniques", action="store_true")
    parser.add_argument("--no-build-patch", action="store_true")
    parser.add_argument(
        "--strict-feature-cleanup",
        action="store_true",
        help=(
            "Fail instead of degrading when an optional Words cleanup cannot be "
            "completed. Used for restore-baseline migration."
        ),
    )
    parser.add_argument(
        "--patch-scope",
        choices=PATCH_SCOPES,
        default="all",
        help="Patch all prices, currency/base items only, unique item names only, or cleanup prices only.",
    )
    parser.add_argument(
        "--cn-high-value-fallback-threshold-divine",
        type=Decimal,
        default=CN_HIGH_VALUE_FALLBACK_THRESHOLD_DIVINE,
        help=(
            "For poecurrency-cn, compare items whose poe2scout reference is "
            "at or above this Divine value and use poe2scout when the "
            "deviation is too large."
        ),
    )
    parser.add_argument(
        "--cn-high-value-fallback-max-ratio",
        type=Decimal,
        default=CN_HIGH_VALUE_FALLBACK_MAX_RATIO,
        help=(
            "For poecurrency-cn high-value comparison, replace with poe2scout "
            "when CN and poe2scout Divine prices differ by more than this ratio."
        ),
    )
    parser.add_argument(
        "--unique-price-label-mode",
        choices=UNIQUE_PRICE_LABEL_MODES,
        default="markup",
        help=(
            "How to label unique item prices in Words.datc64. "
            "Default markup writes [price|name], which PoE Overlay II and "
            "Exile Next TX clean back to the original unique name in copied item text. "
            "overlay is PoE Overlay II only; newline is the legacy three-line title format."
        ),
    )
    parser.add_argument("--patch-script", type=Path, default=DEFAULT_PATCH_SCRIPT)
    parser.add_argument("--output-zip", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--patched-dat", type=Path)
    parser.add_argument("--patched-words", type=Path)
    parser.add_argument(
        "--check-words",
        type=Path,
        help="Only inspect live Words rows for price labels and print JSON.",
    )
    parser.add_argument(
        "--clean-words",
        type=Path,
        help="Only remove active price labels from a Words file and print JSON.",
    )
    parser.add_argument("--clean-words-output", type=Path)
    parser.add_argument("--game-path")
    parser.add_argument("--words-game-path")
    parser.add_argument(
        "--mode",
        choices=["append", "fixed"],
        default="append",
        help="patch build mode passed to poe2_name_price_patch.py",
    )
    return parser.parse_args(argv)


def parse_fallback_sources(value: str) -> list[str]:
    if not value:
        return []
    if value.strip().lower() in {"none", "off", "false", "0"}:
        return []
    sources: list[str] = []
    for raw in value.split(","):
        source = raw.strip()
        if not source:
            continue
        if source not in FALLBACK_PRICE_SOURCES:
            allowed = ", ".join(FALLBACK_PRICE_SOURCES)
            raise SystemExit(f"invalid fallback price source '{source}'. Use {allowed} or none.")
        if source not in sources:
            sources.append(source)
    return sources


def build_cn_reference_chain(first_source: str, fallback_sources: list[str]) -> list[str]:
    if first_source == "none":
        return []
    sources = [first_source]
    for source in fallback_sources:
        if source not in sources:
            sources.append(source)
    return sources


def derive_words_game_path(game_path: str) -> str:
    normalized = str(game_path or "").replace("\\", "/")
    if not re.search(r"baseitemtypes\.datc64$", normalized, flags=re.IGNORECASE):
        return ""
    return re.sub(
        r"baseitemtypes\.datc64$",
        "words.datc64",
        normalized,
        flags=re.IGNORECASE,
    )


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if args.check_words is not None and args.clean_words is not None:
        raise SystemExit("--check-words and --clean-words cannot be used together")
    if args.check_words is not None:
        inspection = inspect_words_price_labels(args.check_words)
        print(
            json.dumps(
                {
                    "path": str(args.check_words),
                    **inspection,
                },
                ensure_ascii=False,
            )
        )
        return 0
    if args.clean_words is not None:
        if args.clean_words_output is None:
            raise SystemExit("--clean-words-output is required with --clean-words")
        cleaned_rows = clean_word_price_labels_file(
            args.clean_words, args.clean_words_output
        )
        inspection = inspect_words_price_labels(args.clean_words_output)
        print(
            json.dumps(
                {
                    "source": str(args.clean_words),
                    "output": str(args.clean_words_output),
                    "cleaned_count": len(cleaned_rows),
                    **inspection,
                },
                ensure_ascii=False,
            )
        )
        return 0

    fallback_price_sources = parse_fallback_sources(args.fallback_price_sources)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    patch_base_items = args.patch_scope in {"all", "currency"}
    patch_unique_words = args.patch_scope in {"all", "uniques"}
    effective_patch_unique_words = patch_unique_words and not args.no_uniques
    if args.patch_scope == "uniques" and args.no_uniques:
        raise SystemExit("--patch-scope=uniques cannot be combined with --no-uniques")
    if args.patch_scope == "none" and args.no_uniques:
        effective_patch_unique_words = False

    fetch_prices = patch_base_items or effective_patch_unique_words
    client = RetryingRequests(
        max_retries=args.retries,
        backoff=args.backoff,
        timeout=max(1.0, args.timeout),
        total_timeout=max(1.0, args.request_time_budget),
    )
    league_selection_source = "not-required"
    league_discovery_url = ""
    league_warnings: list[str] = []
    league_sources = {args.price_source, *fallback_price_sources}
    if args.price_source == "poecurrency-cn":
        league_sources.add(args.cn_reference_source)
    needs_market_league = fetch_prices and bool(
        league_sources.intersection({"poe2scout", "poe-ninja"})
    )
    if needs_market_league:
        selection = resolve_current_leagues(
            client,
            args.api_base,
            explicit_scout=args.league,
            explicit_ninja=args.poe_ninja_league,
            fallback_scout=DEFAULT_LEAGUE,
            fallback_ninja=DEFAULT_POE_NINJA_LEAGUE,
        )
        args.league = selection.scout
        args.poe_ninja_league = selection.poe_ninja
        league_selection_source = selection.source
        league_discovery_url = selection.discovery_url
        league_warnings = list(selection.warnings)
        progress(
            "当前软核赛季："
            f"poe2scout={args.league}, poe.ninja={args.poe_ninja_league} "
            f"({league_selection_source})"
        )
        for warning in league_warnings:
            print(f"[警告] {warning}", file=sys.stderr, flush=True)
    else:
        args.league = args.league or DEFAULT_LEAGUE
        args.poe_ninja_league = args.poe_ninja_league or DEFAULT_POE_NINJA_LEAGUE
    fallback_labels = ", ".join(
        price_source_label(source) for source in fallback_price_sources
    ) or "none"
    progress(
        "启动价格构建："
        f"scope={args.patch_scope}, 主源={price_source_label(args.price_source)}, "
        f"备用源={fallback_labels}"
    )
    if not fetch_prices:
        base_pairs = []
    elif args.price_source == "poecurrency-cn" and not args.en_baseitems.exists():
        progress("加载本地国服 BaseItemTypes")
        base_pairs = load_localized_base_item_pairs(args.tc_baseitems)
    else:
        progress("加载本地中英文 BaseItemTypes")
        base_pairs = load_base_item_pairs(args.en_baseitems, args.tc_baseitems)
    if fetch_prices:
        progress(f"本地可匹配条目：{len(base_pairs)} 条")
    unique_categories: list[dict[str, Any]] = []
    unique_items: list[dict[str, Any]] = []
    source_snapshot_epoch: Any = None
    source_base_currency = "Exalted Orb"
    source_item_count = 0
    fallback_unique_by_name: dict[str, PriceObservation] = {}
    fallback_rows_added = 0
    fallback_rows_added_by_source: dict[str, int] = {}
    high_value_reference_rows = 0
    fallback_unique_words_patched = 0
    cn_reference_status = "disabled"
    cn_reference_warnings: list[str] = []
    fallback_status: dict[str, str] = {}
    fallback_warnings: list[str] = []
    fallback_results: list[PriceSourceResult] = []
    fallback_rows_by_source: list[tuple[str, list[dict[str, str]]]] = []
    fallback_missing_by_source: dict[str, int] = {}
    fallback_divine_by_source: dict[str, Decimal] = {}
    primary_source_status = "ok"
    primary_source_warning = ""
    poecurrency_quality: dict[str, Any] = {}
    source_health_reports: dict[str, dict[str, Any]] = {}
    if not fetch_prices:
        source_health_reports = {
            source: skipped_source_health(
                source, f"price fetching disabled by patch-scope={args.patch_scope}"
            ).to_dict()
            for source in (
                "poe2scout",
                "poe-ninja",
                "poe2db-economy",
                "poecurrency-cn",
            )
        }
    merged_price_sources: set[str] = set()
    best: dict[str, PriceObservation] = {}
    rows: list[dict[str, str]] = []
    missing: list[dict[str, str]] = []
    divine_exalted = Decimal("0")

    if not fetch_prices:
        source_base_currency = "disabled"
    elif args.price_source == "poecurrency-cn":
        try:
            progress("国服主数据源 poecurrency.top：开始获取")
            summary_data = fetch_poecurrency_summary(client, args.poecurrency_summary_url)
            (args.out_dir / "poecurrency_cn_raw.json").write_text(
                json.dumps(summary_data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            best, poecurrency_quality = collect_poecurrency_observations_with_quality(
                summary_data
            )
            source_item_count = sum(
                len(category.get("items") or [])
                for category in summary_data
                if isinstance(category, dict)
            )
            quality_items = max(1, int(poecurrency_quality.get("item_count") or 0))
            timestamp_items = int(
                poecurrency_quality.get("latest_datetime_items") or 0
            )
            missing_unit_ratio = (
                int(poecurrency_quality.get("missing_unit_items") or 0)
                / quality_items
            )
            stale_ratio = (
                int(poecurrency_quality.get("stale_items") or 0)
                / max(1, timestamp_items)
            )
            poecurrency_quality["missing_unit_ratio"] = missing_unit_ratio
            poecurrency_quality["stale_ratio"] = stale_ratio
            if quality_items >= 10 and missing_unit_ratio >= 0.5:
                raise ValueError(
                    "poecurrency-cn unit metadata is missing for at least half of rows"
                )
            if timestamp_items >= 10 and stale_ratio >= 0.5:
                raise ValueError(
                    "poecurrency-cn at least half of timestamped rows are stale"
                )
            poecurrency_health = evaluate_source_health(
                "poecurrency-cn",
                summary_data,
                expected_root="array",
                item_count=source_item_count,
                match_count=len(best),
                item_names=price_source_health_item_names(best),
                required_references=("Divine Orb",),
                discovered_categories=poecurrency_quality.get("categories") or [],
                enabled_categories=poecurrency_quality.get("categories") or [],
                succeeded_categories=[
                    category
                    for category in poecurrency_quality.get("categories") or []
                    if category
                    not in set(poecurrency_quality.get("empty_categories") or [])
                ],
                failed_categories=poecurrency_quality.get("empty_categories") or [],
                freshness_timestamp=(
                    poecurrency_quality.get("latest_datetime_max") or None
                ),
                max_age_seconds=48 * 60 * 60,
                key_fields=(
                    "item_name",
                    "engname",
                    "currency_unit",
                    "latest_datetime",
                    "latest_buy1",
                    "latest_sell1",
                    "buy_avg",
                    "sell_avg",
                    "anomaly_count",
                ),
            )
            source_health_reports["poecurrency-cn"] = poecurrency_health.to_dict()
            poecurrency_quality["health_state"] = poecurrency_health.state
            poecurrency_quality["health"] = poecurrency_health.to_dict()
            if poecurrency_health.is_failure:
                raise ValueError(
                    "poecurrency-cn health validation failed: "
                    + "; ".join(issue.message for issue in poecurrency_health.issues)
                )
            if poecurrency_health.state in {"partial", "stale"}:
                primary_source_status = "partial"
                primary_source_warning = (
                    "poecurrency-cn data is usable but health is "
                    f"{poecurrency_health.state}"
                )
            progress(f"国服主数据源 poecurrency.top：获取成功 ({len(best)} 条价格)")
            source_base_currency = "崇高石"
        except Exception as exc:
            best = {}
            primary_source_status = "failed"
            primary_source_warning = (
                "primary price source poecurrency-cn failed; "
                f"trying fallback sources: {type(exc).__name__}: {exc}"
            )
            progress("国服主数据源 poecurrency.top：获取失败，准备尝试国际参考源")
            print(f"warning: {primary_source_warning}", file=sys.stderr)
            (args.out_dir / "poecurrency_cn_error.json").write_text(
                json.dumps(
                    {
                        "source": "poecurrency-cn",
                        "status": "failed",
                        "error": primary_source_warning,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            source_health_reports.setdefault(
                "poecurrency-cn",
                failed_source_health("poecurrency-cn", exc).to_dict(),
            )

        reference_chain = build_cn_reference_chain(
            args.cn_reference_source, fallback_price_sources
        )
        cn_reference_status = "disabled" if not reference_chain else "failed"
        for source in reference_chain:
            result = try_fetch_price_source(
                source,
                client,
                args,
                include_uniques=effective_patch_unique_words and source == "poe2scout",
                out_dir=args.out_dir,
            )
            source_health_reports[source] = result.health
            fallback_status[source] = result.status
            if result.warning:
                cn_reference_warnings.append(result.warning)
                fallback_warnings.append(result.warning)
            if price_source_result_is_usable(result):
                fallback_results.append(result)
                unique_categories = result.unique_categories or unique_categories
                unique_items = result.unique_items or unique_items
                if result.status == "partial":
                    cn_reference_status = "degraded"
                elif cn_reference_status == "failed":
                    cn_reference_status = "ok"
        if cn_reference_status == "ok" and cn_reference_warnings:
            cn_reference_status = "degraded"
    else:
        primary_result = try_fetch_price_source(
            "poe2scout",
            client,
            args,
            include_uniques=effective_patch_unique_words,
            out_dir=args.out_dir,
            primary=True,
        )
        source_health_reports["poe2scout"] = primary_result.health
        primary_source_status = primary_result.status
        primary_source_warning = primary_result.warning
        preferred_results: list[PriceSourceResult] = []
        if price_source_result_is_usable(primary_result):
            preferred_results.append(primary_result)
            unique_categories = primary_result.unique_categories or []
            unique_items = primary_result.unique_items or []
            scout = primary_result.raw or {}
            source_snapshot_epoch = (scout.get("exchange_snapshot") or {}).get("Epoch")
        elif primary_result.warning:
            fallback_warnings.append(primary_result.warning)

        for source in fallback_price_sources:
            if source == "poe2db-economy" and preferred_results:
                source_health_reports[source] = skipped_source_health(
                    source, "earlier configured international sources were usable"
                ).to_dict()
                continue

            result = try_fetch_price_source(
                source,
                client,
                args,
                include_uniques=False,
                out_dir=args.out_dir,
            )
            source_health_reports[source] = result.health
            fallback_status[source] = result.status
            if result.warning:
                fallback_warnings.append(result.warning)
            if price_source_result_is_usable(result):
                fallback_results.append(result)
                if result.source == "poe-ninja":
                    preferred_results.append(result)

        if preferred_results:
            progress(
                "国际服价格源：开始合并 "
                + ", ".join(price_source_label(result.source) for result in preferred_results)
            )
            best = merge_price_source_results(preferred_results)
            source_base_currency = "+".join(
                price_source_label(result.source) for result in preferred_results
            )
            source_item_count = len(best)
            merged_price_sources = {result.source for result in preferred_results}
            progress(f"国际服价格源：合并后 {len(best)} 条价格")

    if fetch_prices:
        if best:
            progress("整理展示价格并匹配本地物品")
            divine_exalted = divine_price_exalted(best)
            apply_display_prices(best, divine_exalted)
            if args.price_source == "poecurrency-cn":
                rows, missing = match_cn_prices_to_base_items(
                    best,
                    base_pairs,
                    quality=poecurrency_quality,
                )
            else:
                rows, missing = match_prices_to_base_items(
                    best,
                    base_pairs,
                    client=client,
                    use_poe2db=args.poe2db_fallback,
                    max_workers=max(1, args.max_workers),
                )
            progress(f"本地物品匹配完成：命中 {len(rows)}，缺失 {len(missing)}")

        for result in fallback_results:
            if result.source in merged_price_sources:
                continue
            if not result.prices:
                continue
            try:
                progress(f"备用结果 {price_source_label(result.source)}：开始匹配补缺")
                fallback_divine = divine_price_exalted(result.prices)
                apply_display_prices(result.prices, fallback_divine)
                fallback_divine_by_source[result.source] = fallback_divine
                if result.source == "poe2scout":
                    fallback_unique_by_name.update(
                        {
                            f"unique:{normalize_name(obs.en_name)}": obs
                            for obs in result.prices.values()
                            if obs.api_id.startswith("unique:") and obs.display_price
                        }
                    )
                fallback_rows: list[dict[str, str]] = []
                fallback_missing: list[dict[str, str]] = []
                if patch_base_items:
                    if result.source == "poe2db-economy":
                        fallback_rows, fallback_missing = match_cn_prices_to_base_items(
                            result.prices,
                            base_pairs,
                        )
                    else:
                        fallback_rows, fallback_missing = match_prices_to_base_items(
                            result.prices,
                            base_pairs,
                            client=client,
                            use_poe2db=args.poe2db_fallback,
                            max_workers=max(1, args.max_workers),
                        )
                fallback_missing_by_source[result.source] = len(fallback_missing)
                fallback_rows_by_source.append((result.source, fallback_rows))
                progress(
                    f"备用结果 {price_source_label(result.source)}："
                    f"命中 {len(fallback_rows)}，缺失 {len(fallback_missing)}"
                )
                if not best:
                    best = result.prices
                    divine_exalted = fallback_divine
                    source_base_currency = price_source_label(result.source)
                    source_item_count = len(best)
            except Exception as exc:
                fallback_status[result.source] = "failed"
                warning = (
                    f"fallback price source {result.source} could not be matched; "
                    f"{type(exc).__name__}: {exc}"
                )
                fallback_warnings.append(warning)
                print(f"warning: {warning}", file=sys.stderr)

        if not best:
            raise ValueError("all enabled price sources failed")

        if args.price_source == "poecurrency-cn" and rows:
            for source, fallback_rows in fallback_rows_by_source:
                fallback_divine = fallback_divine_by_source.get(source, Decimal("0"))
                if fallback_divine <= 0:
                    continue
                rows, replaced = apply_high_value_reference_rows(
                    primary=rows,
                    fallback=fallback_rows,
                    primary_divine_exalted=divine_exalted,
                    fallback_divine_exalted=fallback_divine,
                    min_divine=args.cn_high_value_fallback_threshold_divine,
                    max_ratio=args.cn_high_value_fallback_max_ratio,
                )
                high_value_reference_rows += replaced

        if patch_base_items and fallback_rows_by_source:
            rows, fallback_rows_added_by_source = apply_fallback_rows(
                rows,
                fallback_rows_by_source,
            )
            fallback_rows_added = sum(fallback_rows_added_by_source.values())
        local_match_gate = evaluate_local_match_gate(
            rows, base_pairs, enabled=patch_base_items
        )
        if local_match_gate["warning"]:
            warning = str(local_match_gate["warning"])
            fallback_warnings.append(warning)
            if primary_source_status == "ok":
                primary_source_status = "partial"
            print(f"warning: {warning}", file=sys.stderr)
    else:
        local_match_gate = evaluate_local_match_gate(
            rows, base_pairs, enabled=False
        )
    if not patch_base_items:
        missing.extend(
            {
                "api_id": row.get("api_id", ""),
                "en_name": row.get("en_name", ""),
                "poe2db_tw": "",
                "reason": f"base item price labels disabled by patch-scope={args.patch_scope}",
            }
            for row in rows
        )
        rows = []
        fallback_rows_added = 0
        high_value_reference_rows = 0

    unique_names: dict[str, UniqueName] = {}
    unique_word_rows: list[dict[str, str]] = []
    unique_word_missing: list[dict[str, str]] = []
    unique_words_patched = 0
    can_patch_unique_words = (
        patch_unique_words
        and effective_patch_unique_words
        and args.en_words.exists()
        and args.tc_words.exists()
        and args.unique_gold_prices.exists()
    )
    if can_patch_unique_words:
        unique_names = load_unique_names(
            args.unique_gold_prices, args.en_words, args.tc_words
        )

    prices_csv = args.out_dir / "prices.csv"
    matched_csv = args.out_dir / "matched_prices_detail.csv"
    missing_csv = args.out_dir / "missing_prices.csv"
    unique_words_csv = args.out_dir / "unique_word_prices_detail.csv"
    unique_words_missing_csv = args.out_dir / "missing_unique_word_prices.csv"
    progress("写出价格明细 CSV")
    write_csv(prices_csv, rows, ["metadata_path", "name", "price", "new_name"])
    write_csv(
        matched_csv,
        rows,
        [
            "metadata_path",
            "name",
            "price",
            "new_name",
            "en_name",
            "api_id",
            "price_exalted",
            "source_pair",
        ],
    )
    write_csv(
        missing_csv,
        missing,
        ["api_id", "en_name", "poe2db_tw", "reason"],
    )

    output_zip = args.output_zip or (args.out_dir / "物价补丁.zip")
    summary = {
        "price_source": args.price_source,
        "patch_scope": args.patch_scope,
        "price_strategy": (
            "poecurrency-cn uses latest buy/sell first with avg fallback; currency_unit=d is converted to exalted by the current Divine ratio and explicit api e fields are preferred when present; high-value outliers are replaced by the configured international reference source when CN and reference prices differ beyond threshold"
            if args.price_source == "poecurrency-cn"
            else "poe2scout relative price"
        ),
        "league": args.league,
        "poe_ninja_league": args.poe_ninja_league,
        "league_selection_source": league_selection_source,
        "league_discovery_url": league_discovery_url,
        "league_warnings": league_warnings,
        "snapshot_epoch": source_snapshot_epoch,
        "base_currency": source_base_currency,
        "price_items": len(best),
        "source_items": source_item_count,
        "unique_categories": len(unique_categories),
        "unique_items": len(unique_items),
        "unique_words_available": len(unique_names),
        "unique_words_patched": unique_words_patched,
        "unique_price_label_mode": args.unique_price_label_mode,
        "unique_words_clean_passthrough": False,
        "matched_items": len(rows),
        "local_match_ratio": local_match_gate["ratio"],
        "local_match_gate": local_match_gate["state"],
        "fallback_matched_items": fallback_rows_added,
        "fallback_matched_items_by_source": fallback_rows_added_by_source,
        "high_value_reference_items": high_value_reference_rows,
        "cn_high_value_fallback_threshold_divine": str(
            args.cn_high_value_fallback_threshold_divine
        ),
        "cn_high_value_fallback_max_ratio": str(
            args.cn_high_value_fallback_max_ratio
        ),
        "missing_items": len(missing),
        "divine_price_exalted": str(divine_exalted),
        "divine_exalted_ratio": divine_exalted_ratio_summary(divine_exalted),
        "primary_source_status": primary_source_status,
        "primary_source_warning": primary_source_warning,
        "fallback_price_sources": fallback_price_sources,
        "fallback_status": fallback_status,
        "fallback_warnings": fallback_warnings,
        "fallback_missing_items_by_source": fallback_missing_by_source,
        "fallback_divine_price_exalted_by_source": {
            source: str(value) for source, value in fallback_divine_by_source.items()
        },
        "poe2scout_fallback": bool(
            "poe2scout" in fallback_divine_by_source
            or "poe2scout" in fallback_rows_added_by_source
        ),
        "cn_reference_source": args.cn_reference_source,
        "cn_reference_status": cn_reference_status,
        "cn_reference_warnings": cn_reference_warnings,
        "poe2db_fallback": bool(args.poe2db_fallback),
        "poecurrency_quality": poecurrency_quality,
        "source_health": source_health_reports,
        "http_request_count": len(client.request_metrics()),
        "http_requests": client.request_metrics(),
        "feature_degradations": [],
    }

    if not args.no_build_patch:
        words_game_path = args.words_game_path or derive_words_game_path(
            args.game_path or ""
        )
        if patch_base_items:
            run_patch_builder(
                patch_script=args.patch_script,
                tc_baseitems=args.tc_baseitems,
                prices_csv=prices_csv,
                output_zip=output_zip,
                report=args.report or (args.out_dir / "price_patch.report.json"),
                mode=args.mode,
                patched_dat=args.patched_dat,
                game_path=args.game_path,
                preserve_unmatched_existing_price=(
                    local_match_gate["state"] in {"degraded", "unavailable"}
                ),
            )
        else:
            if not args.game_path:
                raise SystemExit("--game-path is required when base item price labels are disabled")
            cleanup_report = args.report or (args.out_dir / "price_patch.report.json")
            run_patch_builder(
                patch_script=args.patch_script,
                tc_baseitems=args.tc_baseitems,
                prices_csv=prices_csv,
                output_zip=output_zip,
                report=cleanup_report,
                mode=args.mode,
                patched_dat=args.patched_dat,
                game_path=args.game_path,
            )
        if can_patch_unique_words:
            if words_game_path:
                progress("处理传奇装备 Words 价格标记")
                patched_words = args.patched_words or (args.out_dir / "words.patched.datc64")
                if args.unique_price_label_mode in {"markup", "overlay", "newline"}:
                    if args.price_source == "poecurrency-cn":
                        (
                            unique_words_patched,
                            unique_word_rows,
                            unique_word_missing,
                            fallback_unique_words_patched,
                        ) = patch_unique_word_prices_with_cn_fallback(
                            tc_words_path=args.tc_words,
                            unique_names=unique_names,
                            primary_prices=best,
                            fallback_prices=fallback_unique_by_name,
                            patched_words=patched_words,
                            label_mode=args.unique_price_label_mode,
                        )
                    else:
                        unique_words_patched, unique_word_rows, unique_word_missing = patch_unique_word_prices(
                            tc_words_path=args.tc_words,
                            unique_names=unique_names,
                            prices=best,
                            patched_words=patched_words,
                            label_mode=args.unique_price_label_mode,
                        )
                    unique_words_dat_changed = unique_words_patched > 0 or any(
                        row.get("status") == "cleaned" for row in unique_word_rows
                    )
                    if unique_words_dat_changed:
                        progress(f"写入传奇装备 Words 补丁 ({unique_words_patched} 条)")
                        upsert_zip_entry(
                            output_zip,
                            words_game_path,
                            patched_words.read_bytes(),
                        )
                    else:
                        progress("传奇装备 Words 无需改动，写入原始文件保持补丁完整")
                        upsert_zip_entry(
                            output_zip,
                            words_game_path,
                            args.tc_words.read_bytes(),
                        )
                        summary["unique_words_clean_passthrough"] = True
                else:
                    unique_word_rows, unique_word_missing = list_unique_word_price_candidates(
                        unique_names=unique_names,
                        prices=best,
                        reason="unique Words price labels disabled by unique-price-label-mode=off",
                    )
                    patched_words = args.patched_words or (
                        args.out_dir / "words.patched.datc64"
                    )
                    cleaned_rows = clean_unique_word_prices_file(
                        args.tc_words, unique_names, patched_words
                    )
                    unique_word_rows.extend(cleaned_rows)
                    if cleaned_rows:
                        progress(f"清理旧传奇装备价格标记 ({len(cleaned_rows)} 条)")
                        upsert_zip_entry(
                            output_zip,
                            words_game_path,
                            patched_words.read_bytes(),
                        )
                    else:
                        progress("传奇装备 Words 无需清理，写入原始文件保持补丁完整")
                        upsert_zip_entry(
                            output_zip,
                            words_game_path,
                            args.tc_words.read_bytes(),
                        )
                        summary["unique_words_clean_passthrough"] = True
            else:
                raise SystemExit(
                    "--words-game-path is required when patching unique Words prices"
                )
        elif args.tc_words.exists() and words_game_path:
            progress("清理未启用的传奇装备价格标记")
            patched_words = args.patched_words or (args.out_dir / "words.patched.datc64")
            words_cleanup_failed = False
            try:
                cleaned_rows = clean_word_price_labels_file(args.tc_words, patched_words)
            except Exception as exc:
                if args.strict_feature_cleanup:
                    raise
                print(
                    "warning: failed to clean existing unique price labels; "
                    f"the current Words file will be copied unchanged: {exc}",
                    file=sys.stderr,
                )
                cleaned_rows = []
                words_cleanup_failed = True
                summary["feature_degradations"].append(
                    {
                        "feature": "unique-words",
                        "status": "preserved",
                        "reason": f"cleanup failed: {type(exc).__name__}: {exc}",
                    }
                )
            unique_word_rows.extend(cleaned_rows)
            if cleaned_rows:
                progress(f"写入清理后的 Words 文件 ({len(cleaned_rows)} 条)")
                upsert_zip_entry(
                    output_zip,
                    words_game_path,
                    patched_words.read_bytes(),
                )
            else:
                if words_cleanup_failed:
                    progress("Words 清理不可用，复制当前文件以保持补丁完整")
                else:
                    progress("Words 文件无需清理，写入原始文件保持补丁完整")
                upsert_zip_entry(
                    output_zip,
                    words_game_path,
                    args.tc_words.read_bytes(),
                )
                summary["unique_words_clean_passthrough"] = True
            if patch_unique_words and not args.no_uniques:
                unique_word_missing.append(
                    {
                        "api_id": "",
                        "en_name": "",
                        "reason": "missing Words or UniqueGoldPrices datc64 files",
                    }
                )
        elif patch_unique_words and not args.no_uniques:
            unique_word_missing.append(
                {
                    "api_id": "",
                    "en_name": "",
                    "reason": "missing Words or UniqueGoldPrices datc64 files",
                }
            )

    write_csv(
        unique_words_csv,
        unique_word_rows,
        [
            "words_row_index",
            "en_name",
            "old_name",
            "new_name",
            "price",
            "api_id",
            "price_exalted",
            "source_pair",
            "status",
            "reason",
        ],
    )
    write_csv(
        unique_words_missing_csv,
        unique_word_missing,
        ["api_id", "en_name", "reason"],
    )
    summary["unique_words_available"] = len(unique_names)
    summary["unique_words_patched"] = unique_words_patched
    summary["fallback_unique_words_patched"] = fallback_unique_words_patched
    summary["unique_price_label_mode"] = args.unique_price_label_mode
    summary["missing_unique_word_prices"] = len(unique_word_missing)
    progress("写出构建报告")
    (args.out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"prices: {prices_csv}")
    if not args.no_build_patch:
        print(f"patch: {output_zip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
