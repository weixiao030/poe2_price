import importlib.util
import sys
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "物价补丁" / "tools" / "build_poe2scout_price_patch.py"
FIXTURE = ROOT / "verification/tablet-rarity-test-20260920/run/staged/resources/data/statdescriptions/pricetest20260920/ritual_tablet_stat_descriptions.csd"


def module():
    spec = importlib.util.spec_from_file_location("tablet_price_patch", SCRIPT)
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = loaded
    assert spec.loader is not None
    spec.loader.exec_module(loaded)
    return loaded


def test_tablet_api_paginates_and_keeps_best_quote_per_modifier():
    m = module()

    class FakeClient:
        def __init__(self):
            self.urls = []

        def get_json(self, url):
            self.urls.append(url)
            if "/currencies?" in url:
                return {"values": {"exalted": 0.002, "chaos": 0.1}}
            if "offset=0" in url:
                return {
                    "total": 2,
                    "data": [
                        {
                            "tablet": "Ritual_Tablet",
                            "text_en": "Map has (15-20)% increased Monster Rarity",
                            "prices": {"exalted": {"low_sample_median": 2}},
                        }
                    ],
                }
            return {
                "total": 2,
                "data": [
                    {
                        "tablet": "Ritual_Tablet",
                        "text_en": "Map has (15-20)% increased Monster Rarity",
                        "prices": {"exalted": {"low_sample_median": 3}},
                    }
                ],
            }

    client = FakeClient()
    prices, report = m.fetch_tablet_affix_prices(client, "https://example.invalid", "Forbidden Rites")
    key = m._tablet_text_key("Map has {0}% increased Monster Rarity")
    assert prices["Ritual_Tablet"][key] == Decimal("3")
    assert report["pages"] == 2
    assert len(client.urls) == 3


def test_tablet_raw_chaos_quote_converts_to_exalted_units():
    m = module()
    value = m._tablet_price_from_row(
        {"prices": {"chaos": {"low_sample_median": 5}}},
        {"exalted": Decimal("0.002197802197802198"), "chaos": Decimal("0.11933174224343675")},
    )
    assert value.quantize(Decimal("0.01")) == Decimal("271.48")


def test_tablet_stat_description_appends_price_without_touching_other_languages():
    m = module()
    key = m._tablet_text_key("Map has {0}% increased Monster Rarity")
    transformed, matched, changed = m._append_tablet_price_to_csd(
        str(FIXTURE), {key: Decimal("2")}
    )
    assert matched >= 1
    assert changed == 1
    assert transformed.count("=2.00E".encode("utf-16-le")) == 1
    assert "Map has {0}% increased [MonsterRarity|Monster Rarity]=2.00E".encode("utf-16-le") not in transformed


def test_poe_ninja_precursor_tablets_parser_isolated_from_affix_failure():
    m = module()

    class FakeClient:
        def get_json(self, url):
            assert "type=PrecursorTablets" in url
            return {
                "core": {"rates": {"exalted": 477}},
                "lines": [
                    {"name": "Abyss Tablet", "baseType": "Abyss Tablet", "primaryValue": 1.2, "listingCount": 8},
                    {"name": "Broken", "baseType": "Abyss Tablet", "primaryValue": 0, "listingCount": 0},
                ],
            }

    report = m.fetch_poe_ninja_precursor_tablets(FakeClient(), "Forbidden Rites")
    assert report["status"] == "ok"
    assert report["usable_lines"] == 1
    assert report["divine_exalted"] == "477"


def test_tablet_base_aliases_redirect_special_precursor_types():
    m = module()
    source = ROOT / "verification/tablet-rarity-test-20260920/run/backup/resources/data/balance/traditional chinese/baseitemtypes.datc64"
    patched, redirected = m._redirect_tablet_base_items(source.read_bytes(), {"Irradiated", "Overseer", "Temple"})
    assert redirected == 3
    layout = m.detect_base_item_layout(patched)
    names = []
    for row in range(layout.row_count):
        start = 4 + row * layout.row_size
        try:
            metadata = m.read_string_offset(patched, layout, int.from_bytes(patched[start:start + 4], "little"))
            if "TowerAugment" in metadata:
                name = m.read_string_offset(patched, layout, int.from_bytes(patched[start + 40:start + 44], "little"))
                names.append((metadata, name))
        except (ValueError, IndexError):
            continue
    assert ("Metadata/Items/TowerAugment/GenericAugment", "Metadata/Items/TowerAugments/Poe2Price/Irradiated") in names
    assert ("Metadata/Items/TowerAugment/MapBossAugment", "Metadata/Items/TowerAugments/Poe2Price/Overseer") in names
    assert ("Metadata/Items/TowerAugment/IncursionAugment", "Metadata/Items/TowerAugments/Poe2Price/Temple") in names
