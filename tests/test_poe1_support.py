from decimal import Decimal
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "物价补丁" / "tools"
sys.path.insert(0, str(TOOLS))

import build_poe1_price_patch as poe1  # noqa: E402
from price_sources.models import BaseItemPair  # noqa: E402


def test_poe1_display_units_use_chaos_and_divine_with_small_price_guard():
    assert poe1.format_price(Decimal("0.2"), Decimal("159.5")) == "<1C"
    assert poe1.format_price(Decimal("1"), Decimal("159.5")) == "1C"
    assert poe1.format_price(Decimal("15.95"), Decimal("159.5")) == "0.1D"
    assert poe1.format_price(Decimal("159.5"), Decimal("159.5")) == "1D"


def test_poecurrency_v1_summary_normalizes_units_and_reference_orbs():
    items = [
        {
            "engname": "Chaos Orb",
            "item_name": "混沌石",
            "latest_buy1": 1,
            "latest_sell1": 1,
            "currency_unit": "C",
        },
        {
            "engname": "Divine Orb",
            "item_name": "神圣石",
            "latest_buy1": 159.5,
            "latest_sell1": 159.5,
            "currency_unit": "C",
        },
    ]
    for index in range(8):
        items.append(
            {
                "engname": f"Example Currency {index}",
                "item_name": f"示例通货{index}",
                "latest_buy1": 2 + index,
                "latest_sell1": 2 + index,
                "currency_unit": "C",
            }
        )

    prices, divine_chaos, quality = poe1.collect_poecurrency_prices(
        [{"category": "通货", "items": items}], Decimal("0")
    )
    poe1.apply_display_prices(prices, divine_chaos)

    assert divine_chaos == Decimal("159.5")
    assert prices["chaos"].price_chaos == Decimal("1")
    assert prices["divine"].price_chaos == Decimal("159.5")
    assert prices["cn:examplecurrency0"].display_price == "2C"
    assert quality["source_items"] == 10


def test_poe1_matching_keeps_duplicate_metadata_aliases():
    prices = {
        "ninja:currency:1": poe1.Poe1Price(
            api_id="ninja:currency:1",
            en_name="Orb of Binding",
            localized_name="绑定石",
            category="Currency",
            price_chaos=Decimal("5"),
            volume=Decimal("1"),
            source_pair="test",
            display_price="5C",
        )
    }
    pairs = [
        BaseItemPair("Metadata/One", "Orb of Binding", "绑定石"),
        BaseItemPair("Metadata/Two", "Orb of Binding", "绑定石"),
    ]

    matched, missing = poe1.match_base_items(prices, pairs, prefer_localized=True)

    assert missing == []
    assert [row["metadata_path"] for row in matched] == ["Metadata/One", "Metadata/Two"]


def test_poe1_scripts_keep_isolated_paths_and_c_d_contract():
    common = (TOOLS / "poe1_patch_common.ps1").read_text(encoding="utf-8-sig")
    update = (TOOLS / "update_poe1_price_patch.ps1").read_text(encoding="utf-8-sig")
    restore = (TOOLS / "restore_poe1_price_patch.ps1").read_text(encoding="utf-8-sig")
    gui = (TOOLS / "price_patch_gui.ps1").read_text(encoding="utf-8-sig")
    profiles = (TOOLS / "poe_patch_profiles.ps1").read_text(encoding="utf-8-sig")

    assert ".poe1-price-patch" in update and ".poe1-price-patch" in restore
    assert "output\\poe1" in update
    assert "POE1-CN-WeGame-Bundles2" in profiles
    assert 'if ($DetectedVersion -eq "poe1") {' in profiles
    assert "one physical directory" in profiles
    assert "POE1" in restore
    assert "RequestedGameVersion" in gui
    assert '"poe1"' in gui and '"poe2"' in gui and '"auto"' in gui


def test_unified_gui_uses_cached_compact_client_switching_and_both_links():
    gui = (TOOLS / "price_patch_gui.ps1").read_text(encoding="utf-8-sig")

    assert "$CandidateCache" in gui
    assert '$CandidateCache.ContainsKey("auto")' in gui
    assert 'Label = "[$VersionText]$ClientText | $($Candidate.Path)"' in gui
    assert "https://github.com/weixiao030/poe2_price" in gui
    assert "https://www.caimogu.cc/post/2403703.html" in gui
    assert "POE1 使用混沌石 / 神圣石计价；" in gui
    assert "开始/更新物价补丁" in gui
    assert "更新物价补丁" in gui
    assert "还原物价补丁" in gui
    assert "Operation" in gui
    assert "restore_poe1_price_patch.ps1" in gui
    assert "ScriptParameters[\"PatchScope\"]" in gui
    assert "Poe1Dir = [string]$Selection.GameDirectory" in gui
    assert "岛屿提示仅适用于 POE2" not in gui
    assert "选择游戏、客户端和本次更新范围" not in gui
