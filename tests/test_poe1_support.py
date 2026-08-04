from decimal import Decimal
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "物价补丁" / "tools"
sys.path.insert(0, str(TOOLS))

import build_poe1_price_patch as poe1  # noqa: E402
from price_sources.models import BaseItemPair  # noqa: E402


COMMON = TOOLS / "poe2_patch_common.ps1"
PROFILES = TOOLS / "poe_patch_profiles.ps1"


def ps_quote(value: Path | str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def run_powershell(script: str) -> str:
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip()


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


def test_poe1_matching_prefers_exact_metadata_path_over_market_name():
    prices = {
        "scout:test": poe1.Poe1Price(
            api_id="scout:test",
            en_name="A renamed market item",
            localized_name="",
            category="currency",
            price_chaos=Decimal("7"),
            volume=Decimal("10"),
            source_pair="poe2scout/test",
            display_price="7C",
            metadata_path="Metadata/Exact",
        )
    }
    pairs = [BaseItemPair("Metadata/Exact", "Old Internal Name", "本地名称")]

    matched, missing = poe1.match_base_items(prices, pairs, prefer_localized=False)

    assert missing == []
    assert matched[0]["metadata_path"] == "Metadata/Exact"
    assert matched[0]["name"] == "本地名称"


def test_poe1_poe2scout_pc_prices_keep_direct_base_item_paths():
    class FakeClient:
        def get_json(self, url: str):
            if url.endswith("/pc/Leagues"):
                return [
                    {
                        "Value": "Allflame",
                        "ShortName": "allflame",
                        "IsCurrent": True,
                    }
                ]
            if url.endswith("/ReferenceCurrencies"):
                return [
                    {"ApiId": "chaos", "Text": "Chaos Orb", "RelativePrice": 1},
                    {"ApiId": "divine", "Text": "Divine Orb", "RelativePrice": 160},
                ]
            if url.endswith("/SnapshotPairs"):
                pairs = [
                    {
                        "CurrencyOne": {
                            "ApiId": "binding",
                            "Text": "Orb of Binding",
                            "CategoryApiId": "currency",
                            "BaseItemTypeId": "Metadata/Items/Currency/CurrencyUpgradeRandomly",
                        },
                        "CurrencyTwo": {
                            "ApiId": "chaos",
                            "Text": "Chaos Orb",
                            "CategoryApiId": "currency",
                            "BaseItemTypeId": "Metadata/Items/Currency/CurrencyRerollRare",
                        },
                        "CurrencyOneData": {"RelativePrice": 5, "ValueTraded": 100},
                        "CurrencyTwoData": {"RelativePrice": 1, "ValueTraded": 100},
                    },
                    {
                        "CurrencyOne": {
                            "ApiId": "divine",
                            "Text": "Divine Orb",
                            "CategoryApiId": "currency",
                            "BaseItemTypeId": "Metadata/Items/Currency/CurrencyModValues",
                        },
                        "CurrencyTwo": {
                            "ApiId": "chaos",
                            "Text": "Chaos Orb",
                            "CategoryApiId": "currency",
                            "BaseItemTypeId": "Metadata/Items/Currency/CurrencyRerollRare",
                        },
                        "CurrencyOneData": {"RelativePrice": 160, "ValueTraded": 200},
                        "CurrencyTwoData": {"RelativePrice": 1, "ValueTraded": 200},
                    },
                ]
                for index in range(20):
                    pairs.append(
                        {
                            "CurrencyOne": {
                                "ApiId": f"example-{index}",
                                "Text": f"Example Currency {index}",
                                "CategoryApiId": "currency",
                                "BaseItemTypeId": f"Metadata/Example/{index}",
                            },
                            "CurrencyTwo": pairs[0]["CurrencyTwo"],
                            "CurrencyOneData": {
                                "RelativePrice": index + 1,
                                "ValueTraded": index + 1,
                            },
                            "CurrencyTwoData": {"RelativePrice": 1, "ValueTraded": 1},
                        }
                    )
                return pairs
            raise AssertionError(url)

    raw, prices, divine_chaos = poe1.fetch_poe2scout_poe1_prices(
        FakeClient(), "https://api.example", "Allflame"
    )

    assert raw["realm"] == "pc"
    assert raw["snapshot_pair_count"] == 22
    assert divine_chaos == Decimal("160")
    assert prices["binding"].price_chaos == Decimal("5")
    assert prices["binding"].metadata_path.endswith("CurrencyUpgradeRandomly")


def test_poe1_poedb_uses_chaos_as_base_currency():
    divine = poe1.shared.Poe2dbEconomyRow(
        key="divine",
        name="Divine Orb",
        wiki_slug="Divine_Orb",
        left_key="chaos",
        left_qty=Decimal("160"),
        right_qty=Decimal("1"),
        volume=Decimal("100"),
    )
    mirror = poe1.shared.Poe2dbEconomyRow(
        key="mirror",
        name="Mirror of Kalandra",
        wiki_slug="Mirror_of_Kalandra",
        left_key="divine",
        left_qty=Decimal("2"),
        right_qty=Decimal("1"),
        volume=Decimal("10"),
    )

    divine_chaos = poe1.poe1_poedb_divine_price_chaos({"divine": divine})

    assert divine_chaos == Decimal("160")
    assert poe1.poe1_poedb_row_price_chaos(mirror, divine_chaos) == Decimal("320")


def test_poe1_safe_categories_expand_without_variant_dependent_market_rows():
    assert {
        "Runegraft",
        "Ducat",
        "EnshroudingCrystal",
        "Astrolabe",
    }.issubset(poe1.POE_NINJA_EXCHANGE_TYPES)
    assert {"Invitation", "Vial"}.issubset(poe1.POE_NINJA_BASE_ITEM_TYPES)
    unsafe = {
        "Wombgift",
        "SkillGem",
        "ClusterJewel",
        "BaseType",
        "ValdoMap",
        "ForbiddenJewel",
        "Beast",
    }
    assert unsafe.isdisjoint(poe1.POE_NINJA_BASE_ITEM_TYPES)
    assert unsafe.isdisjoint(poe1.POE_NINJA_UNIQUE_TYPES)


def test_poe1_fallback_source_parser_is_ordered_and_deduplicated():
    assert poe1.parse_fallback_sources("poe2scout,poedb-economy,poe2scout") == [
        "poe2scout",
        "poedb-economy",
    ]
    assert poe1.parse_fallback_sources("none") == []


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


def test_poe1_auto_language_detects_localization_from_latest_client_log(tmp_path: Path):
    game = tmp_path / "Path of Exile"
    (game / "Bundles2").mkdir(parents=True)
    (game / "Bundles2" / "_.index.bin").write_bytes(b"index")
    (game / "logs").mkdir()
    (game / "logs" / "LatestClient.txt").write_text(
        "\n".join(
            [
                "[SCENE] Set Source [The Coast]",
                "[SCENE] Set Source [(null)]",
                "[SCENE] Set Source [獅眼守望]",
                "[LOADING SCREEN] (獅眼守望) Duration = 1.0 seconds",
            ]
        ),
        encoding="utf-8",
    )

    output = run_powershell(
        f". {ps_quote(COMMON)}; . {ps_quote(PROFILES)}; "
        "function global:Get-Poe1ConfigLanguage { param([string]$GameDirectory = '', [string]$ConfigDirectory = '') return 'fr' }; "
        f"$info = Get-Poe1InstallInfo -GameDirectory {ps_quote(game)} -LanguageMode auto; "
        "$info | Select-Object ConfiguredLanguage,EffectiveLanguageCode,LanguageName,TcBaseItemsPath,LocalizationDetected,LocalizationAreaName | ConvertTo-Json -Compress"
    )
    info = json.loads(output)

    assert info == {
        "ConfiguredLanguage": "fr",
        "EffectiveLanguageCode": "zh-TW",
        "LanguageName": "Traditional Chinese",
        "TcBaseItemsPath": "data/traditional chinese/baseitemtypes.datc64",
        "LocalizationDetected": True,
        "LocalizationAreaName": "獅眼守望",
    }


def test_poe1_explicit_language_modes_override_auto_detection(tmp_path: Path):
    game = tmp_path / "Path of Exile"
    (game / "Bundles2").mkdir(parents=True)
    (game / "Bundles2" / "_.index.bin").write_bytes(b"index")
    (game / "logs").mkdir()
    (game / "logs" / "LatestClient.txt").write_text(
        "[SCENE] Set Source [獅眼守望]\n", encoding="utf-8"
    )

    output = run_powershell(
        f". {ps_quote(COMMON)}; . {ps_quote(PROFILES)}; "
        "function global:Get-Poe1ConfigLanguage { param([string]$GameDirectory = '', [string]$ConfigDirectory = '') return 'fr' }; "
        "$result = foreach ($mode in @('localization','zh-CN','zh-TW','config')) { "
        f"$info = Get-Poe1InstallInfo -GameDirectory {ps_quote(game)} -LanguageMode $mode; "
        "[pscustomobject]@{ Mode=$mode; Code=$info.EffectiveLanguageCode; Path=$info.TcBaseItemsPath; Detected=$info.LocalizationDetected } }; "
        "$result | ConvertTo-Json -Compress"
    )
    rows = {row["Mode"]: row for row in json.loads(output)}

    assert rows["localization"]["Code"] == "zh-TW"
    assert rows["zh-CN"]["Path"] == "data/simplified chinese/baseitemtypes.datc64"
    assert rows["zh-TW"]["Path"] == "data/traditional chinese/baseitemtypes.datc64"
    assert rows["config"]["Code"] == "fr"
    assert rows["config"]["Path"] == "data/french/baseitemtypes.datc64"
    assert all(not row["Detected"] for row in rows.values())


def test_latest_non_chinese_area_prevents_stale_localization_detection(tmp_path: Path):
    game = tmp_path / "game"
    (game / "logs").mkdir(parents=True)
    (game / "logs" / "LatestClient.txt").write_text(
        "[SCENE] Set Source [獅眼守望]\n[SCENE] Set Source [The Coast]\n",
        encoding="utf-8",
    )

    output = run_powershell(
        f". {ps_quote(PROFILES)}; "
        f"Get-Poe1LocalizationLogEvidence -GameDirectory {ps_quote(game)} | "
        "Select-Object Detected,AreaName | ConvertTo-Json -Compress"
    )
    evidence = json.loads(output)

    assert evidence == {"Detected": False, "AreaName": "The Coast"}


def test_poe1_language_setting_survives_game_directory_save(tmp_path: Path):
    game = tmp_path / "Path of Exile"
    settings = tmp_path / "state" / "settings.json"
    (game / "Bundles2").mkdir(parents=True)
    (game / "Bundles2" / "_.index.bin").write_bytes(b"index")

    run_powershell(
        f". {ps_quote(COMMON)}; . {ps_quote(PROFILES)}; "
        f"Save-Poe1LanguageMode -LanguageMode localization -SettingsPath {ps_quote(settings)} | Out-Null; "
        f"Save-PoePatchGameDirectory -GameVersion poe1 -GameDirectory {ps_quote(game)} -SettingsPath {ps_quote(settings)} | Out-Null"
    )
    state = json.loads(settings.read_text(encoding="utf-8"))

    assert state["poe1_language_mode"] == "localization"
    assert Path(state["poe1_game_directory"]) == game.resolve()


def test_poe1_gui_and_scripts_forward_language_mode_and_isolate_restore_names():
    gui = (TOOLS / "price_patch_gui.ps1").read_text(encoding="utf-8-sig")
    update = (TOOLS / "update_poe1_price_patch.ps1").read_text(encoding="utf-8-sig")
    restore = (TOOLS / "restore_poe1_price_patch.ps1").read_text(encoding="utf-8-sig")
    common = (TOOLS / "poe1_patch_common.ps1").read_text(encoding="utf-8-sig")

    for expected in ("自动识别", "汉化补丁", "简体中文", "繁体中文", "跟随游戏配置"):
        assert expected in gui
    assert 'Poe1LanguageMode = [string]$Selection.Poe1LanguageMode' in gui
    assert '[string]$Poe1LanguageMode = "auto"' in update
    assert '[string]$Poe1LanguageMode = "auto"' in restore
    assert "-LanguageMode $Poe1LanguageMode" in update
    assert "-LanguageMode $Poe1LanguageMode" in restore
    assert "EffectiveLanguageCode" in common
    assert '"POE1真实还原补丁_${Kind}.zip"' in common
