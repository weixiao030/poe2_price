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
import re
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_SCOUT_API = "https://api.poe2scout.com"
DEFAULT_POECURRENCY_SUMMARY_API = "https://poecurrency.top/api/summary?version=2"
DEFAULT_POE2DB_ECONOMY_US_URL = "https://poe2db.tw/us/Economy"
DEFAULT_POE2DB_ECONOMY_CN_URL = "https://poe2db.tw/cn/Economy"
DEFAULT_LEAGUE = "runes"
PRICE_SOURCES = ("poe2scout", "poecurrency-cn")
CN_REFERENCE_SOURCES = ("poe2scout", "poe2db-economy", "none")
PATCH_SCOPES = ("all", "currency", "uniques", "none")
SCRIPT_DIR = Path(__file__).resolve().parent
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
PRICE_TEXT_RE = r"(?:<1|[0-9]+(?:\.[0-9]+)?)[DE]"
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
class BaseItemPair:
    metadata_path: str
    en_name: str
    tc_name: str


@dataclass(frozen=True)
class Poe2dbEconomyRow:
    key: str
    name: str
    wiki_slug: str
    left_key: str
    left_qty: Decimal
    right_qty: Decimal
    volume: Decimal


@dataclass
class PriceObservation:
    api_id: str
    en_name: str
    category: str
    price_exalted: Decimal
    value_traded: Decimal
    source_pair: str
    display_price: str = ""


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


@dataclass(frozen=True)
class HttpResponse:
    url: str
    status_code: int
    reason: str
    content: bytes
    encoding: str = "utf-8"

    @property
    def text(self) -> str:
        return self.content.decode(self.encoding or "utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.text)


class RetryingRequests:
    def __init__(
        self,
        max_retries: int = 4,
        backoff: float = 0.8,
        timeout: float = 25.0,
        user_agent: str = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36 poe2-price-patch/1.0"
        ),
    ) -> None:
        self.max_retries = max_retries
        self.backoff = backoff
        self.timeout = timeout
        self.user_agent = user_agent
        self.retry_statuses = {429, 500, 502, 503, 504}

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.user_agent,
            "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
        }

    def _decode_response(
        self,
        url: str,
        status_code: int,
        reason: str,
        headers: Any,
        content: bytes,
    ) -> HttpResponse:
        encoding = "utf-8"
        get_content_charset = getattr(headers, "get_content_charset", None)
        if callable(get_content_charset):
            encoding = get_content_charset() or encoding
        return HttpResponse(
            url=url,
            status_code=status_code,
            reason=reason,
            content=content,
            encoding=encoding,
        )

    def _get_once(self, url: str) -> HttpResponse:
        request = urllib.request.Request(url, headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return self._decode_response(
                    url=response.geturl(),
                    status_code=response.status,
                    reason=response.reason,
                    headers=response.headers,
                    content=response.read(),
                )
        except urllib.error.HTTPError as exc:
            return self._decode_response(
                url=exc.url,
                status_code=exc.code,
                reason=exc.reason,
                headers=exc.headers,
                content=exc.read(),
            )

    def get(self, url: str, **kwargs: Any) -> HttpResponse:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self._get_once(url)
                if response.status_code < 400:
                    return response
                if response.status_code not in self.retry_statuses:
                    return response
                last_error = RuntimeError(f"{response.status_code} {response.reason}: {url}")
            except Exception as exc:
                last_error = exc
            if attempt < self.max_retries:
                time.sleep(self.backoff * (2**attempt))
        assert last_error is not None
        raise last_error

    def get_json(self, url: str) -> Any:
        response = self.get(url)
        return response.json()


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
    if row_size <= DISPLAY_NAME_FIELD_INDEX * 4 or row_size % 4 != 0:
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


def words_look_price_patched(path: Path) -> bool:
    try:
        data = path.read_bytes()
        layout = detect_words_layout(data)
        for row_index in range(layout.row_count):
            entry = read_words_row(data, layout, row_index)
            if entry and re.search(
                rf"(?:\r?\n\[{PRICE_TEXT_RE}\]|<<\[{PRICE_TEXT_RE}\]>>|{UNIQUE_MARKUP_PRICE_RE})",
                entry.display_name,
            ):
                return True
    except Exception:
        return True
    return False


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
    name = re.sub(rf"<<\[{PRICE_TEXT_RE}\]>>$", "", name)
    name = re.sub(rf"\s*\[{PRICE_TEXT_RE}\]$", "", name)
    return re.sub(rf"={PRICE_TEXT_RE}$", "", name).strip()


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
        patched_words.parent.mkdir(parents=True, exist_ok=True)
        patched_words.write_bytes(bytes(output))
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
    if cleaned:
        patched_words.parent.mkdir(parents=True, exist_ok=True)
        patched_words.write_bytes(bytes(output))
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
        patched_words.parent.mkdir(parents=True, exist_ok=True)
        patched_words.write_bytes(bytes(output))
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
        patched_words.parent.mkdir(parents=True, exist_ok=True)
        patched_words.write_bytes(bytes(output))
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


def upsert_zip_entry(zip_path: Path, entry_name: str, data: bytes) -> None:
    entry_name = entry_name.replace("\\", "/")
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    existing: list[tuple[zipfile.ZipInfo, bytes]] = []
    if zip_path.exists():
        with zipfile.ZipFile(zip_path, "r") as zf:
            for info in zf.infolist():
                if info.filename != entry_name:
                    existing.append((info, zf.read(info.filename)))
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for info, content in existing:
            zf.writestr(info, content)
        zf.writestr(entry_name, data)


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


def decimal_from_text(text: str) -> Decimal:
    cleaned = re.sub(r"[^0-9.]", "", text)
    if not cleaned:
        return Decimal("0")
    return Decimal(cleaned)


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
        if len(value_links) < 2 or len(numbers) < 2:
            continue

        left_qty = decimal_from_text(numbers[0])
        right_qty = decimal_from_text(numbers[1])
        if left_qty <= 0 or right_qty <= 0:
            continue

        rows[key] = Poe2dbEconomyRow(
            key=key,
            name=name,
            wiki_slug=wiki_slug,
            left_key=economy_href_key(value_links[0]),
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
    us_html = client.get(us_url).text
    cn_html = client.get(cn_url).text
    us_rows = parse_poe2db_economy_rows(us_html)
    cn_rows = parse_poe2db_economy_rows(cn_html)
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

    raw = {
        "source": "poe2db-economy",
        "us_url": us_url,
        "cn_url": cn_url,
        "us_rows": len(us_rows),
        "cn_rows": len(cn_rows),
        "matched_rows": len(best),
        "divine_price_exalted": str(divine_exalted),
    }
    return raw, best


def fetch_scout_data(client: RetryingRequests, api_base: str, league: str) -> dict[str, Any]:
    endpoints = {
        "exchange_snapshot": f"{api_base}/poe2/Leagues/{league}/ExchangeSnapshot",
        "reference_currencies": f"{api_base}/poe2/Leagues/{league}/ReferenceCurrencies",
        "snapshot_pairs": f"{api_base}/poe2/Leagues/{league}/SnapshotPairs",
    }
    results: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        future_to_name = {
            pool.submit(client.get_json, url): name for name, url in endpoints.items()
        }
        for future in as_completed(future_to_name):
            name = future_to_name[future]
            results[name] = future.result()
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
    observations = collect_price_observations(scout["snapshot_pairs"])
    best = choose_best_prices(observations, scout["reference_currencies"])
    unique_categories: list[dict[str, Any]] = []
    unique_items: list[dict[str, Any]] = []
    if include_uniques:
        unique_categories, unique_items = fetch_unique_items(
            client,
            api_base,
            league,
            max_workers=max(1, max_workers),
        )
        add_unique_observations(best, unique_items)
    return scout, best, unique_categories, unique_items


def fetch_poecurrency_summary(
    client: RetryingRequests, summary_url: str
) -> list[dict[str, Any]]:
    data = client.get_json(summary_url)
    if not isinstance(data, list):
        raise ValueError("poecurrency summary response must be a list")
    return data


def fetch_unique_categories(
    client: RetryingRequests, api_base: str, league: str
) -> list[dict[str, Any]]:
    data = client.get_json(f"{api_base}/poe2/Leagues/{league}/Items/Categories")
    return data.get("UniqueCategories") or []


def fetch_unique_category_items(
    client: RetryingRequests,
    api_base: str,
    league: str,
    category: str,
    per_page: int = 100,
) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode(
        {
            "Category": category,
            "ReferenceCurrency": "exalted",
            "Page": 1,
            "PerPage": per_page,
            "DataPoints": 7,
            "FrequencyHours": 24,
        }
    )
    data = client.get_json(
        f"{api_base}/poe2/Leagues/{league}/Uniques/ByCategory?{query}"
    )
    return data.get("Items") or []


def fetch_unique_items(
    client: RetryingRequests,
    api_base: str,
    league: str,
    max_workers: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    categories = [
        category
        for category in fetch_unique_categories(client, api_base, league)
        if category.get("ApiId") in DEFAULT_UNIQUE_CATEGORIES
    ]
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
        for future in as_completed(future_to_category):
            all_items.extend(future.result())
    return categories, all_items


def to_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default


def normalize_market_name(value: str) -> str:
    value = html.unescape(str(value)).strip().lower()
    value = value.replace("（", "(").replace("）", ")")
    return re.sub(r"[\s\u3000]+", "", value)


CN_DIVINE_NORMALIZED = {normalize_market_name(name) for name in CN_DIVINE_NAMES}
CN_EXALTED_NORMALIZED = {normalize_market_name(name) for name in CN_EXALTED_NAMES}


def poecurrency_api_id(name: str) -> str:
    normalized = normalize_market_name(name)
    if normalized in CN_DIVINE_NORMALIZED:
        return "divine"
    if normalized in CN_EXALTED_NORMALIZED:
        return "exalted"
    return f"cn:{normalized}"


def poecurrency_item_unit(item: dict[str, Any]) -> str:
    raw_unit = str(item.get("currency_unit") or item.get("unit") or "").strip().lower()
    if raw_unit in {"d", "divine", "divine orb", "divine_orb", "神圣石", "神圣宝珠"}:
        return "d"
    if raw_unit in {"e", "exalted", "exalted orb", "exalted_orb", "崇高石", "崇高宝珠"}:
        return "e"

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


def poecurrency_item_price(item: dict[str, Any]) -> tuple[Decimal, str]:
    latest_buy = to_decimal(item.get("latest_buy1"))
    latest_sell = to_decimal(item.get("latest_sell1"))
    latest_price, latest_field = choose_poecurrency_pair_price(
        latest_buy, latest_sell, "latest_buy1", "latest_sell1"
    )
    if latest_price > 0:
        return latest_price, latest_field

    buy_avg = to_decimal(item.get("buy_avg"))
    sell_avg = to_decimal(item.get("sell_avg"))
    return choose_poecurrency_pair_price(
        buy_avg, sell_avg, "buy_avg", "sell_avg"
    )


def poecurrency_divine_price(item: dict[str, Any]) -> tuple[Decimal, str]:
    for field_name in ("latest_buy1", "buy_avg", "latest_sell1", "sell_avg"):
        price = to_decimal(item.get(field_name))
        if price > 0:
            return price, f"{field_name}_divine_ratio"
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


def collect_poecurrency_observations(
    summary: list[dict[str, Any]],
) -> dict[str, PriceObservation]:
    candidates: list[dict[str, Any]] = []
    divine_exalted = Decimal("0")

    for category in summary:
        if not isinstance(category, dict):
            continue
        category_label = str(category.get("category_label") or "").strip()
        items = category.get("items") or []
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("item_name") or "").strip()
            if not name:
                continue

            api_id = poecurrency_api_id(name)
            unit = poecurrency_item_unit(item)
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
                continue

            if api_id == "divine" and unit == "e":
                divine_exalted = max(divine_exalted, price)

            candidates.append(
                {
                    "api_id": api_id,
                    "name": name,
                    "category_label": category_label,
                    "price": price,
                    "price_field": price_field,
                    "unit": unit,
                }
            )

    best: dict[str, PriceObservation] = {}
    for candidate in candidates:
        price = candidate["price"]
        unit = candidate["unit"]
        api_id = candidate["api_id"]
        price_exalted = poecurrency_price_to_exalted(price, unit, divine_exalted)
        if api_id == "divine" and unit == "d" and divine_exalted > 0:
            price_exalted = divine_exalted
        if price_exalted <= 0:
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
        )
        old = best.get(api_id)
        if old is None or obs.price_exalted > old.price_exalted:
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
    return best


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
    by_en = {pair.en_name: pair for pair in base_pairs}
    by_en_norm = {normalize_name(pair.en_name): pair for pair in base_pairs}
    by_tc = {pair.tc_name: pair for pair in base_pairs}

    matched: list[dict[str, str]] = []
    missing: list[dict[str, str]] = []
    pending_poe2db: list[PriceObservation] = []

    for obs in prices.values():
        if obs.api_id.startswith("unique:"):
            continue
        if obs.price_exalted < Decimal("1") or not obs.display_price:
            continue
        pair = by_en.get(obs.en_name) or by_en_norm.get(normalize_name(obs.en_name))
        price = obs.display_price
        if pair and price:
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
                pair = by_tc.get(tc_name or "")
                if pair and price:
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
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    by_tc: dict[str, BaseItemPair] = {}
    for pair in base_pairs:
        for name in {pair.tc_name, strip_existing_price(pair.tc_name)}:
            normalized = normalize_market_name(name)
            if normalized and normalized not in by_tc:
                by_tc[normalized] = pair

    matched: list[dict[str, str]] = []
    missing: list[dict[str, str]] = []
    for obs in prices.values():
        if obs.price_exalted < Decimal("1") or not obs.display_price:
            continue
        pair = by_tc.get(normalize_market_name(obs.en_name))
        if pair:
            matched.append(
                {
                    "metadata_path": pair.metadata_path,
                    "name": pair.tc_name,
                    "price": obs.display_price,
                    "new_name": "",
                    "en_name": "",
                    "api_id": obs.api_id,
                    "price_exalted": str(obs.price_exalted),
                    "source_pair": obs.source_pair,
                }
            )
        else:
            missing.append(
                {
                    "api_id": obs.api_id,
                    "en_name": obs.en_name,
                    "reason": "not found in local Simplified Chinese BaseItemTypes",
                }
            )

    dedup: dict[str, dict[str, str]] = {}
    for row in matched:
        old = dedup.get(row["metadata_path"])
        if old is None or Decimal(row["price_exalted"]) > Decimal(old["price_exalted"]):
            dedup[row["metadata_path"]] = row
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
) -> None:
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
    if game_path:
        cmd.extend(["--game-path", game_path])
    if patched_dat:
        cmd.extend(["--patched-dat", str(patched_dat)])
    subprocess.run(cmd, check=True)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch market prices and generate a PoE2 name-price patch."
    )
    parser.add_argument("--price-source", choices=PRICE_SOURCES, default="poe2scout")
    parser.add_argument("--api-base", default=DEFAULT_SCOUT_API)
    parser.add_argument("--poecurrency-summary-url", default=DEFAULT_POECURRENCY_SUMMARY_API)
    parser.add_argument("--poe2db-economy-us-url", default=DEFAULT_POE2DB_ECONOMY_US_URL)
    parser.add_argument("--poe2db-economy-cn-url", default=DEFAULT_POE2DB_ECONOMY_CN_URL)
    parser.add_argument(
        "--cn-reference-source",
        choices=CN_REFERENCE_SOURCES,
        default="poe2scout",
        help="International reference source used with poecurrency-cn.",
    )
    parser.add_argument("--league", default=DEFAULT_LEAGUE)
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
        help="HTTP request timeout in seconds for price sources.",
    )
    parser.add_argument("--poe2db-fallback", action="store_true")
    parser.add_argument("--no-uniques", action="store_true")
    parser.add_argument("--no-build-patch", action="store_true")
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
    parser.add_argument("--game-path")
    parser.add_argument("--words-game-path")
    parser.add_argument(
        "--mode",
        choices=["append", "fixed"],
        default="append",
        help="patch build mode passed to poe2_name_price_patch.py",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
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
    )
    if not fetch_prices:
        base_pairs = []
    elif args.price_source == "poecurrency-cn" and not args.en_baseitems.exists():
        base_pairs = load_localized_base_item_pairs(args.tc_baseitems)
    else:
        base_pairs = load_base_item_pairs(args.en_baseitems, args.tc_baseitems)
    unique_categories: list[dict[str, Any]] = []
    unique_items: list[dict[str, Any]] = []
    source_snapshot_epoch: Any = None
    source_base_currency = "Exalted Orb"
    source_item_count = 0
    scout_fallback: dict[str, Any] | None = None
    scout_fallback_prices: dict[str, PriceObservation] = {}
    fallback_unique_by_name: dict[str, PriceObservation] = {}
    fallback_rows_added = 0
    high_value_reference_rows = 0
    fallback_unique_words_patched = 0
    best: dict[str, PriceObservation] = {}
    rows: list[dict[str, str]] = []
    missing: list[dict[str, str]] = []
    divine_exalted = Decimal("0")

    if not fetch_prices:
        source_base_currency = "disabled"
    elif args.price_source == "poecurrency-cn":
        summary_data = fetch_poecurrency_summary(client, args.poecurrency_summary_url)
        (args.out_dir / "poecurrency_cn_raw.json").write_text(
            json.dumps(summary_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        best = collect_poecurrency_observations(summary_data)
        source_base_currency = "崇高石"
        source_item_count = sum(
            len(category.get("items") or [])
            for category in summary_data
            if isinstance(category, dict)
        )
        if args.cn_reference_source == "poe2scout":
            scout_fallback, scout_fallback_prices, unique_categories, unique_items = build_scout_prices(
                client,
                args.api_base.rstrip("/"),
                args.league,
                include_uniques=effective_patch_unique_words,
                max_workers=max(1, args.max_workers),
            )
            (args.out_dir / "poe2scout_fallback_raw.json").write_text(
                json.dumps(scout_fallback, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        elif args.cn_reference_source == "poe2db-economy":
            scout_fallback, scout_fallback_prices = build_poe2db_economy_prices(
                client,
                args.poe2db_economy_us_url,
                args.poe2db_economy_cn_url,
            )
            (args.out_dir / "poe2db_economy_fallback_raw.json").write_text(
                json.dumps(scout_fallback, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    else:
        scout, best, unique_categories, unique_items = build_scout_prices(
            client,
            args.api_base.rstrip("/"),
            args.league,
            include_uniques=effective_patch_unique_words,
            max_workers=max(1, args.max_workers),
        )
        (args.out_dir / "poe2scout_raw.json").write_text(
            json.dumps(scout, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        source_snapshot_epoch = scout["exchange_snapshot"].get("Epoch")
        source_base_currency = scout["exchange_snapshot"].get("BaseCurrencyText")
        source_item_count = len(best)

    if fetch_prices:
        divine_exalted = divine_price_exalted(best)
        apply_display_prices(best, divine_exalted)
        if args.price_source == "poecurrency-cn":
            rows, missing = match_cn_prices_to_base_items(best, base_pairs)
            if scout_fallback_prices:
                fallback_divine_exalted = divine_price_exalted(scout_fallback_prices)
                apply_display_prices(scout_fallback_prices, fallback_divine_exalted)
                if args.cn_reference_source == "poe2db-economy":
                    fallback_rows, _fallback_missing = match_cn_prices_to_base_items(
                        scout_fallback_prices,
                        base_pairs,
                    )
                else:
                    fallback_rows, _fallback_missing = match_prices_to_base_items(
                        scout_fallback_prices,
                        base_pairs,
                        client=client,
                        use_poe2db=args.poe2db_fallback,
                        max_workers=max(1, args.max_workers),
                    )
                rows, high_value_reference_rows = apply_high_value_reference_rows(
                    primary=rows,
                    fallback=fallback_rows,
                    primary_divine_exalted=divine_exalted,
                    fallback_divine_exalted=fallback_divine_exalted,
                    min_divine=args.cn_high_value_fallback_threshold_divine,
                    max_ratio=args.cn_high_value_fallback_max_ratio,
                )
                rows, fallback_rows_added = merge_primary_with_fallback_rows(
                    rows, fallback_rows
                )
                if args.cn_reference_source == "poe2scout":
                    fallback_unique_by_name = {
                        f"unique:{normalize_name(obs.en_name)}": obs
                        for obs in scout_fallback_prices.values()
                        if obs.api_id.startswith("unique:") and obs.display_price
                    }
        else:
            rows, missing = match_prices_to_base_items(
                best,
                base_pairs,
                client=client,
                use_poe2db=args.poe2db_fallback,
                max_workers=max(1, args.max_workers),
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
        "fallback_matched_items": fallback_rows_added,
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
        "poe2scout_fallback": bool(
            args.price_source == "poecurrency-cn" and args.cn_reference_source == "poe2scout"
        ),
        "cn_reference_source": args.cn_reference_source,
        "poe2db_fallback": bool(args.poe2db_fallback),
    }

    if not args.no_build_patch:
        words_game_path = args.words_game_path or (
            (args.game_path or "").replace("baseitemtypes.datc64", "words.datc64")
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
                        upsert_zip_entry(
                            output_zip,
                            words_game_path,
                            patched_words.read_bytes(),
                        )
                    else:
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
                        upsert_zip_entry(
                            output_zip,
                            words_game_path,
                            patched_words.read_bytes(),
                        )
                    else:
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
            patched_words = args.patched_words or (args.out_dir / "words.patched.datc64")
            try:
                cleaned_rows = clean_word_price_labels_file(args.tc_words, patched_words)
            except Exception as exc:
                print(
                    f"warning: failed to clean existing unique price labels; keeping current Words.datc64: {exc}",
                    file=sys.stderr,
                )
                cleaned_rows = []
            unique_word_rows.extend(cleaned_rows)
            if cleaned_rows:
                upsert_zip_entry(
                    output_zip,
                    words_game_path,
                    patched_words.read_bytes(),
                )
            else:
                upsert_zip_entry(output_zip, words_game_path, args.tc_words.read_bytes())
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
