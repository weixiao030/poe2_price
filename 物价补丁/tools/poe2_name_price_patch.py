#!/usr/bin/env python3
"""
Build a PoE2 GGPK patch zip that appends price text to item display names.

This does not modify Content.ggpk directly. It rewrites a local copy of
BaseItemTypes.datc64 and stores it in a zip with the same path layout used by
the existing VisualGGPK3/PatchBundledGGPK3 patch tools.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import struct
import sys
import zipfile
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
PATCH_ROOT = SCRIPT_DIR.parent
DEFAULT_SOURCE = (
    PATCH_ROOT
    / "output"
    / "dat_files_latest"
    / "data"
    / "data_balance_traditional chinese_baseitemtypes.datc64"
)
DEFAULT_GAME_PATH = "data/balance/traditional chinese/baseitemtypes.datc64"
DISPLAY_NAME_FIELD_INDEX = 8


@dataclass
class BaseItemName:
    row_index: int
    metadata_path: str
    name: str
    name_offset: int
    name_pointer_pos: int
    name_start: int
    name_end: int


@dataclass
class DatLayout:
    row_count: int
    row_size: int
    string_base: int


@dataclass
class NameReplacement:
    row_index: int
    name_start: int
    name_end: int
    name_offset: int
    name_pointer_pos: int
    old_name: str
    requested_name: str
    fitted_name: str
    metadata_path: str
    price: str

    @property
    def slot_chars(self) -> int:
        return (self.name_end - self.name_start) // 2

    @property
    def compacted(self) -> bool:
        return self.requested_name != self.fitted_name


def read_utf16le_z(data: bytes, start: int) -> tuple[str, int]:
    """Read a UTF-16LE zero-terminated string at start."""
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


def looks_like_metadata_path(text: str) -> bool:
    return text.startswith("Metadata/Items/")


def has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


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
    if string_base <= 4 or string_base >= len(data):
        raise ValueError("cannot detect BaseItemTypes string table")

    row_bytes = string_base - 4
    if row_count <= 0 or row_bytes % row_count != 0:
        raise ValueError("cannot detect fixed row size in BaseItemTypes.datc64")

    row_size = row_bytes // row_count
    if row_size <= DISPLAY_NAME_FIELD_INDEX * 4 or row_size % 4 != 0:
        raise ValueError(f"unexpected BaseItemTypes row size: {row_size}")

    return DatLayout(row_count=row_count, row_size=row_size, string_base=string_base)


def is_valid_string_offset(data: bytes, layout: DatLayout, offset: int) -> bool:
    absolute = layout.string_base + offset
    return offset >= 0 and absolute + 1 < len(data) and offset % 2 == 0


def read_string_offset(data: bytes, layout: DatLayout, offset: int) -> tuple[str, int, int]:
    if not is_valid_string_offset(data, layout, offset):
        raise ValueError(f"invalid string offset: 0x{offset:x}")
    start = layout.string_base + offset
    text, end = read_utf16le_z(data, start)
    return text, start, end


def scan_base_item_names(data: bytes) -> list[BaseItemName]:
    """Read BaseItemTypes rows and resolve their display-name string pointer."""
    layout = detect_base_item_layout(data)
    entries: list[BaseItemName] = []

    for row_index in range(layout.row_count):
        row_start = 4 + row_index * layout.row_size
        try:
            metadata_offset = struct.unpack_from("<I", data, row_start)[0]
            name_pointer_pos = row_start + DISPLAY_NAME_FIELD_INDEX * 4
            name_offset = struct.unpack_from("<I", data, name_pointer_pos)[0]
            metadata_path, _metadata_start, _metadata_end = read_string_offset(
                data, layout, metadata_offset
            )
            name, name_start, name_end = read_string_offset(data, layout, name_offset)
        except (struct.error, ValueError):
            continue

        if not looks_like_metadata_path(metadata_path):
            continue

        if name and not name.startswith("Metadata/") and len(name) <= 160:
            entries.append(
                BaseItemName(
                    row_index=row_index,
                    metadata_path=metadata_path,
                    name=name,
                    name_offset=name_offset,
                    name_pointer_pos=name_pointer_pos,
                    name_start=name_start,
                    name_end=name_end,
                )
            )

    return entries


def load_price_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            raise ValueError("prices csv has no header")
        rows = []
        for row in reader:
            clean = {k.strip(): (v or "").strip() for k, v in row.items() if k}
            if any(clean.values()):
                rows.append(clean)
        return rows


_PRICE_RE = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)([A-Za-z]+)\s*$")


def unique_texts(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            output.append(value)
    return output


def compact_price_variants(price: str) -> list[str]:
    """Return price strings from most precise to shortest readable form."""
    clean = price.strip()
    variants = [clean]
    match = _PRICE_RE.match(clean)
    if not match:
        return unique_texts(variants)

    number_text, unit = match.groups()
    stripped = number_text.rstrip("0").rstrip(".") if "." in number_text else number_text
    variants.append(f"{stripped}{unit}")
    if stripped.startswith("0."):
        variants.append(f"{stripped[1:]}{unit}")

    try:
        number = Decimal(number_text)
    except (InvalidOperation, ValueError):
        number = Decimal("0")

    if number >= Decimal("10"):
        rounded = number.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        variants.append(f"{rounded}{unit}")
    elif Decimal("0") < number < Decimal("1"):
        variants.append(f"<1{unit}")

    return unique_texts(variants)


def fit_name_with_price(
    base_name: str,
    requested_name: str,
    price: str,
    separator: str,
    max_chars: int,
) -> str | None:
    """Fit display text into the original UTF-16 string slot without growing datc64."""
    candidates: list[str] = []

    def add(value: str) -> None:
        if value and len(value) <= max_chars:
            candidates.append(value)

    add(requested_name)

    if price:
        for price_text in compact_price_variants(price):
            add(f"{base_name}{separator}{price_text}")
            add(f"{base_name}{price_text}")

        for price_text in compact_price_variants(price):
            room = max_chars - len(separator) - len(price_text)
            if room > 0:
                add(f"{base_name[:room]}{separator}{price_text}")

            room = max_chars - len(price_text)
            if room > 0:
                add(f"{base_name[:room]}{price_text}")

        for price_text in compact_price_variants(price):
            add(price_text)

    add(base_name[:max_chars])
    fitted = unique_texts(candidates)
    return fitted[0] if fitted else None


def build_replacements(
    entries: list[BaseItemName],
    price_rows: list[dict[str, str]],
    separator: str,
    keep_existing_price: bool,
    mode: str,
    patch_same_name_duplicates: bool,
) -> tuple[list[NameReplacement], list[str]]:
    by_path = {entry.metadata_path.lower(): entry for entry in entries}
    by_name: dict[str, list[BaseItemName]] = {}
    for entry in entries:
        by_name.setdefault(entry.name, []).append(entry)

    replacements: list[NameReplacement] = []
    warnings: list[str] = []
    seen_rows: set[int] = set()

    for idx, row in enumerate(price_rows, start=2):
        metadata_path = row.get("metadata_path", "")
        name = row.get("name", "")
        price = row.get("price", "")
        new_name = row.get("new_name", "")
        if not price and not new_name:
            warnings.append(f"line {idx}: skipped, price/new_name is empty")
            continue

        entry: BaseItemName | None = None
        target_entries: list[BaseItemName] = []
        if metadata_path:
            entry = by_path.get(metadata_path.lower())
            if entry is None:
                warnings.append(f"line {idx}: metadata_path not found: {metadata_path}")
                continue
            target_entries = [entry]
        elif name:
            matches = by_name.get(name, [])
            if len(matches) == 1:
                entry = matches[0]
            elif len(matches) > 1:
                if patch_same_name_duplicates:
                    entry = matches[0]
                    target_entries = matches
                else:
                    warnings.append(
                        f"line {idx}: name is ambiguous, use metadata_path: {name}"
                    )
                    continue
            else:
                warnings.append(f"line {idx}: name not found: {name}")
                continue
        else:
            warnings.append(f"line {idx}: need metadata_path or name")
            continue

        if patch_same_name_duplicates:
            target_entries = by_name.get(entry.name, [entry])
        elif not target_entries:
            target_entries = [entry]

        old_name = entry.name
        if keep_existing_price and separator in old_name:
            old_name = old_name.split(separator, 1)[0]
        requested_name = new_name or f"{old_name}{separator}{price}"

        for target_entry in target_entries:
            if target_entry.row_index in seen_rows:
                continue
            seen_rows.add(target_entry.row_index)

            target_old_name = target_entry.name
            if keep_existing_price and separator in target_old_name:
                target_old_name = target_old_name.split(separator, 1)[0]
            target_requested_name = new_name or f"{target_old_name}{separator}{price}"
            slot_chars = (target_entry.name_end - target_entry.name_start) // 2
            if mode == "append":
                fitted_name = target_requested_name
            else:
                fitted_name = fit_name_with_price(
                    base_name=target_old_name,
                    requested_name=target_requested_name,
                    price=price,
                    separator=separator,
                    max_chars=slot_chars,
                )
            if not fitted_name:
                warnings.append(
                    f"line {idx}: skipped, cannot fit text into {slot_chars} chars: {target_entry.name}"
                )
                continue

            if mode != "append" and fitted_name != target_requested_name:
                warnings.append(
                    f"line {idx}: compacted to fixed slot ({slot_chars} chars): "
                    f"{target_requested_name} -> {fitted_name}"
                )
            replacements.append(
                NameReplacement(
                    row_index=target_entry.row_index,
                    name_start=target_entry.name_start,
                    name_end=target_entry.name_end,
                    name_offset=target_entry.name_offset,
                    name_pointer_pos=target_entry.name_pointer_pos,
                    old_name=target_entry.name,
                    requested_name=target_requested_name,
                    fitted_name=fitted_name,
                    metadata_path=target_entry.metadata_path,
                    price=price,
                )
            )

    return replacements, warnings


def append_utf16le_string(output: bytearray, layout: DatLayout, text: str) -> int:
    if len(output) % 2:
        output.append(0)
    offset = len(output) - layout.string_base
    if offset < 0 or offset > 0xFFFFFFFF:
        raise ValueError("appended string offset is out of uint32 range")
    output.extend(text.encode("utf-16-le"))
    output.extend(b"\x00\x00\x00\x00")
    return offset


def apply_replacements_append(data: bytes, replacements: list[NameReplacement]) -> bytes:
    layout = detect_base_item_layout(data)
    output = bytearray(data)
    appended_offsets: dict[str, int] = {}

    for replacement in sorted(replacements, key=lambda item: item.row_index):
        current_offset = struct.unpack_from("<I", output, replacement.name_pointer_pos)[0]
        if current_offset != replacement.name_offset:
            raise ValueError(
                f"display-name pointer changed for row {replacement.row_index}: "
                f"0x{current_offset:x} != 0x{replacement.name_offset:x}"
            )

        if replacement.fitted_name == replacement.old_name:
            new_offset = replacement.name_offset
        else:
            new_offset = appended_offsets.get(replacement.fitted_name)
            if new_offset is None:
                new_offset = append_utf16le_string(
                    output, layout, replacement.fitted_name
                )
                appended_offsets[replacement.fitted_name] = new_offset
        struct.pack_into("<I", output, replacement.name_pointer_pos, new_offset)

    return bytes(output)


def apply_replacements_fixed(data: bytes, replacements: list[NameReplacement]) -> bytes:
    output = bytearray(data)
    for replacement in sorted(
        replacements, key=lambda item: item.name_start, reverse=True
    ):
        start = replacement.name_start
        end = replacement.name_end
        old_name = replacement.old_name
        new_name = replacement.fitted_name
        old_bytes = old_name.encode("utf-16-le")
        current = bytes(output[start:end])
        if current != old_bytes:
            raise ValueError(
                f"name bytes changed at 0x{start:x}; expected {old_name!r}"
            )
        new_bytes = new_name.encode("utf-16-le")
        if len(new_bytes) > len(old_bytes):
            raise ValueError(
                f"fixed-slot replacement overflow at 0x{start:x}: "
                f"{new_name!r} > {old_name!r}"
            )
        output[start:end] = new_bytes + (b"\x00" * (len(old_bytes) - len(new_bytes)))
    return bytes(output)


def export_names(source: Path, output: Path) -> None:
    data = source.read_bytes()
    entries = scan_base_item_names(data)
    with output.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["metadata_path", "name"])
        writer.writeheader()
        for entry in entries:
            if has_cjk(entry.name):
                writer.writerow(
                    {"metadata_path": entry.metadata_path, "name": entry.name}
                )
    print(f"exported {output} ({sum(1 for e in entries if has_cjk(e.name))} names)")


def build_patch(
    source: Path,
    prices: Path,
    output_zip: Path,
    patched_dat: Path | None,
    game_path: str,
    separator: str,
    keep_existing_price: bool,
    mode: str,
    patch_same_name_duplicates: bool,
    report: Path | None,
) -> None:
    data = source.read_bytes()
    entries = scan_base_item_names(data)
    rows = load_price_rows(prices)
    replacements, warnings = build_replacements(
        entries, rows, separator, keep_existing_price, mode, patch_same_name_duplicates
    )
    if not replacements:
        raise SystemExit("no replacements were generated")

    if mode == "append":
        patched = apply_replacements_append(data, replacements)
    else:
        patched = apply_replacements_fixed(data, replacements)
        if len(patched) != len(data):
            raise ValueError(
                f"patched datc64 size changed: {len(data)} -> {len(patched)}"
            )
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(game_path.replace("\\", "/"), patched)

    if patched_dat:
        patched_dat.parent.mkdir(parents=True, exist_ok=True)
        patched_dat.write_bytes(patched)

    info = {
        "source": str(source),
        "output_zip": str(output_zip),
        "game_path": game_path.replace("\\", "/"),
        "mode": mode,
        "fixed_length": mode == "fixed",
        "append_string_table": mode == "append",
        "source_size": len(data),
        "patched_size": len(patched),
        "size_delta": len(patched) - len(data),
        "patched_names": len(replacements),
        "patch_same_name_duplicates": patch_same_name_duplicates,
        "full_text_names": sum(1 for item in replacements if not item.compacted),
        "compacted_names": sum(1 for item in replacements if item.compacted),
        "replacements": [
            {
                "metadata_path": replacement.metadata_path,
                "row_index": replacement.row_index,
                "old_name": replacement.old_name,
                "requested_name": replacement.requested_name,
                "new_name": replacement.fitted_name,
                "price": replacement.price,
                "slot_chars": replacement.slot_chars,
                "compacted": replacement.compacted,
                "offset": f"0x{replacement.name_start:x}",
                "old_string_offset": f"0x{replacement.name_offset:x}",
                "pointer_offset": f"0x{replacement.name_pointer_pos:x}",
            }
            for replacement in replacements
        ],
        "warnings": warnings,
    }
    if report:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"patched names: {len(replacements)}")
    print(f"full text: {info['full_text_names']}")
    print(f"compacted: {info['compacted_names']}")
    print(f"dat size: {len(data)} -> {len(patched)}")
    print(f"mode: {mode}")
    print(f"written: {output_zip}")
    if warnings:
        print("warnings:")
        for warning in warnings:
            print(f"  - {warning}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a PoE2 item-name price patch zip."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    export = sub.add_parser("export", help="export current item names to csv")
    export.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    export.add_argument("--output", type=Path, default=Path("baseitem_names_tc.csv"))

    build = sub.add_parser("build", help="build patch zip from prices csv")
    build.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    build.add_argument("--prices", type=Path, default=Path("prices.csv"))
    build.add_argument("--output-zip", type=Path, default=Path("物价补丁.zip"))
    build.add_argument("--patched-dat", type=Path)
    build.add_argument("--game-path", default=DEFAULT_GAME_PATH)
    build.add_argument("--separator", default="=")
    build.add_argument("--keep-existing-price", action="store_true")
    build.add_argument(
        "--no-patch-same-name-duplicates",
        action="store_true",
        help="only patch the exact metadata_path row, not other rows with the same display name",
    )
    build.add_argument(
        "--mode",
        choices=["append", "fixed"],
        default="append",
        help=(
            "append writes new names at the end of the datc64 string table and "
            "updates row pointers; fixed overwrites the original string slot only"
        ),
    )
    build.add_argument("--report", type=Path, default=Path("price_patch.report.json"))

    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if args.cmd == "export":
        export_names(args.source, args.output)
    elif args.cmd == "build":
        build_patch(
            source=args.source,
            prices=args.prices,
            output_zip=args.output_zip,
            patched_dat=args.patched_dat,
            game_path=args.game_path,
            separator=args.separator,
            keep_existing_price=args.keep_existing_price,
            mode=args.mode,
            patch_same_name_duplicates=not args.no_patch_same_name_duplicates,
            report=args.report,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
