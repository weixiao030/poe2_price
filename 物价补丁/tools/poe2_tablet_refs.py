"""Only the eight known tablet rows may redirect to our private templates."""
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path
import struct
import sys
import tempfile
import zipfile

# Embedded Python's isolated search path omits the script directory.
# This file is also invoked directly for ZIP validation and cache cleanup.
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))

ORIGINAL = "Metadata/Items/TowerAugments/TowerAugment"
TYPES = {"Breach": "Breach", "Expedition": "Expedition", "Delirium": "Delirium",
         "Ritual": "Ritual", "Generic": "Irradiated", "MapBoss": "Overseer",
         "Abyss": "Abyss", "Incursion": "Temple"}


def canonical_reference(metadata: str, reference: str) -> str:
    for base, kind in TYPES.items():
        if metadata != f"Metadata/Items/TowerAugment/{base}Augment":
            continue
        allowed = {ORIGINAL, f"Metadata/Items/TowerAugments/Poe2Price/{kind}"}
        if kind in {"Ritual", "Delirium"}:
            allowed.add(f"Metadata/Items/TowerAugments/PriceTest20260920/{kind}")
        if reference in allowed:
            return ORIGINAL
    return reference


def clean_references(data: bytes) -> bytes:
    if not any(marker.encode('utf-16-le') in data for marker in ('Poe2Price/', 'PriceTest20260920/')):
        return data
    # Import lazily so the name builder can share this helper without a cycle.
    from poe2_name_price_patch import detect_base_item_layout, read_string_offset
    layout = detect_base_item_layout(data)
    result = bytearray(data)
    original_pointer = None
    for row in range(layout.row_count):
        at = 4 + row * layout.row_size
        metadata = read_string_offset(data, layout, struct.unpack_from("<I", data, at)[0])[0]
        if metadata not in {f"Metadata/Items/TowerAugment/{base}Augment" for base in TYPES}:
            continue
        if layout.row_size < 48:
            raise ValueError("tablet row has no complete inheritance pointer")
        pointer = struct.unpack_from("<Q", data, at + 40)[0]
        reference = read_string_offset(data, layout, pointer)[0]
        if reference != ORIGINAL and canonical_reference(metadata, reference) == ORIGINAL:
            if original_pointer is None:
                encoded = (ORIGINAL + "\0").encode("utf-16-le")
                position = data.find(encoded, layout.string_base)
                if position >= 0 and (position - layout.string_base) % 2 == 0:
                    original_pointer = position - layout.string_base
                else:
                    original_pointer = len(result) - layout.string_base
                    result.extend(encoded)
            struct.pack_into("<Q", result, at + 40, original_pointer)
    return bytes(result)


def clean_tablet_layer(data: bytes) -> bytes:
    """Remove only the eight tablet name labels and our template redirects."""
    from poe2_name_price_patch import (
        apply_replacements_append, build_replacements, scan_base_item_names,
    )
    from poe2_price_labels import strip_existing_price
    data = clean_references(data)
    if 'Metadata/Items/TowerAugment/'.encode('utf-16-le') not in data:
        return data
    entries = scan_base_item_names(data)
    paths = {f"Metadata/Items/TowerAugment/{base}Augment" for base in TYPES}
    rows = [dict(metadata_path=entry.metadata_path,
                 new_name=strip_existing_price(entry.name))
            for entry in entries if entry.metadata_path in paths
            and strip_existing_price(entry.name) != entry.name]
    if not rows:
        return data
    replacements, warnings = build_replacements(entries, rows, '=', False, 'append', False)
    if warnings:
        raise ValueError('tablet name cleanup failed: ' + '; '.join(warnings))
    return apply_replacements_append(data, replacements)


def same_restore_baseline(saved: bytes, current: bytes) -> bool:
    """Compare structure and every resolved name, ignoring append-only labels."""
    from poe2_name_price_patch import (
        DISPLAY_NAME_FIELD_INDEX, build_structure_signature,
        detect_base_item_layout, read_string_offset,
    )
    if (build_structure_signature(saved)["compatibility_sha256"]
            != build_structure_signature(current)["compatibility_sha256"]):
        return False
    layouts = [detect_base_item_layout(data) for data in (saved, current)]
    for row in range(layouts[0].row_count):
        names = []
        for data, layout in zip((saved, current), layouts):
            at = 4 + row * layout.row_size + DISPLAY_NAME_FIELD_INDEX * 4
            pointer = struct.unpack_from("<I", data, at)[0]
            names.append(read_string_offset(data, layout, pointer)[0])
        if names[0] != names[1]:
            return False
    return True


def clean_zip(path: Path, english: Path | None = None) -> None:
    with zipfile.ZipFile(path) as archive:
        entries = {entry.filename: archive.read(entry) for entry in archive.infolist()
                   if not entry.is_dir() and "/poe2price/" not in entry.filename.lower()}
    for name in entries:
        if name.lower().endswith("/baseitemtypes.datc64"):
            entries[name] = clean_tablet_layer(entries[name])
    if english and english.exists():
        data = clean_tablet_layer(english.read_bytes())
        english_key = next((name for name in entries
                            if name.lower() == "data/balance/baseitemtypes.datc64"), None)
        # Keep the saved clean bytes across repeated updates/restores. Cleaning
        # the live patched table again leaves appended strings and changed
        # pointers. Also compare resolved names: official name-only changes are
        # deliberately invisible to the patch compatibility signature.
        if english_key is None or not same_restore_baseline(entries[english_key], data):
            if english_key is not None:
                del entries[english_key]
            entries["data/balance/baseitemtypes.datc64"] = data
    fd, temporary = tempfile.mkstemp(prefix=".tablet-clean-", suffix=".zip", dir=path.parent)
    os.close(fd)
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, content in entries.items():
                archive.writestr(name, content)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def validate_resources(entries: dict[str, bytes]) -> None:
    from poe2_name_price_patch import detect_base_item_layout, read_string_offset
    from poe2_tablet_prices import decode_resource, validate_csd
    files = {name.lower(): content for name, content in entries.items()}
    for name, data in files.items():
        if not name.endswith('/baseitemtypes.datc64'):
            continue
        layout = detect_base_item_layout(data)
        for row in range(layout.row_count):
            at = 4 + row * layout.row_size
            metadata = read_string_offset(data, layout, struct.unpack_from('<I', data, at)[0])[0]
            if metadata not in {f'Metadata/Items/TowerAugment/{base}Augment' for base in TYPES}:
                continue
            reference = read_string_offset(data, layout, struct.unpack_from('<Q', data, at + 40)[0])[0]
            if '/poe2price/' not in reference.lower():
                continue
            if canonical_reference(metadata, reference) != ORIGINAL:
                raise ValueError('tablet reference does not belong to its base type')
            it_path = reference.lower() + '.it'
            if it_path not in files:
                raise ValueError('tablet ZIP missing referenced template: ' + it_path)
            text = decode_resource(files[it_path])[0]
            descriptions = re.findall(r'(?im)^\s*stat_description_list\s*=\s*"([^"]+)"', text)
            if len(descriptions) > 1:
                raise ValueError('tablet template repeats a single stat_description_list; rarity dispatch is unsupported')
            if not descriptions or any(description.lower() not in files for description in descriptions):
                raise ValueError('tablet ZIP missing referenced stat descriptions')
            for description in descriptions:
                validate_csd(decode_resource(files[description.lower()])[0])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("zip", type=Path)
    parser.add_argument("--english", type=Path)
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()
    if args.validate:
        with zipfile.ZipFile(args.zip) as archive:
            validate_resources({entry.filename:archive.read(entry) for entry in archive.infolist() if not entry.is_dir()})
    else:
        clean_zip(args.zip, args.english)
