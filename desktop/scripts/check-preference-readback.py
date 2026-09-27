"""Check active names/references in resources re-extracted from the real client."""
import json
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / '物价补丁/tools'))
from poe2_name_price_patch import scan_base_item_names, detect_base_item_layout, read_string_offset
from poe2_tablet_refs import TYPES, ORIGINAL, ENGLISH_BASEITEMS
from poe2_price_labels import strip_existing_price
from poe2_whole_tablets import UNIQUE_TABLET_NAMES
from build_poe2scout_price_patch import detect_words_layout, read_words_row

directory = Path(sys.argv[1])
prices, affixes = [value == 'true' for value in sys.argv[2:4]]
scope = sys.argv[4] if len(sys.argv) > 4 else 'all'
records = json.loads((directory / 'resources.json').read_text(encoding='utf-8-sig'))
evidence = []
for i, record in enumerate(records):
    name = record['path'].lower()
    data = (directory / f'{i:06}.bin').read_bytes()
    if name.endswith('/baseitemtypes.datc64'):
        layout = detect_base_item_layout(data)
        entries = scan_base_item_names(data)
        tablets = [entry for entry in entries if entry.metadata_path in {
            f'Metadata/Items/TowerAugment/{kind}Augment' for kind in TYPES}]
        labels = sum(entry.name != strip_existing_price(entry.name) for entry in tablets)
        references = []
        for index, entry in enumerate(entries):
            if entry not in tablets:
                continue
            pointer = struct.unpack_from('<Q', data, 4 + entry.row_index * layout.row_size + 40)[0]
            references.append(read_string_offset(data, layout, pointer)[0])
        redirects = sum('/Poe2Price/' in value for value in references)
        if name == ENGLISH_BASEITEMS:
            assert labels == 0, 'English filter identities must remain clean'
        else:
            assert bool(labels) == prices, (name, labels, prices)
            if scope not in ('all', 'currency'):
                other_prices = [entry.name for entry in entries if entry not in tablets and entry.name != strip_existing_price(entry.name)]
                assert not other_prices, (name, 'Unselected currency prices remain', other_prices[:5])
        assert bool(redirects) == affixes, (name, redirects, affixes)
        if not affixes:
            assert all(value == ORIGINAL for value in references), references
        evidence.append(dict(path=name, tablets=len(tablets), names=labels, redirects=redirects))
    elif name.endswith('/words.datc64'):
        layout = detect_words_layout(data)
        ordinary_labels, tablet_labels = [], []
        for row in range(layout.row_count):
            entry = read_words_row(data, layout, row)
            if entry and entry.display_name != strip_existing_price(entry.display_name):
                (tablet_labels if entry.en_name in UNIQUE_TABLET_NAMES else ordinary_labels).append(entry.display_name)
        if not prices:
            assert not tablet_labels, tablet_labels
        if scope not in ('all', 'uniques'):
            assert not ordinary_labels, ('Unselected unique prices remain', ordinary_labels[:5])
        evidence.append(dict(path=name, ordinary_prices=len(ordinary_labels), tablet_prices=len(tablet_labels)))
assert evidence, 'No BaseItemTypes read back'
print(json.dumps({'verified': True, 'prices': prices, 'affixes': affixes, 'tables': evidence}, ensure_ascii=False))
