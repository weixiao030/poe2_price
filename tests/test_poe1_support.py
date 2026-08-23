from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "物价补丁" / "tools"
sys.path.insert(0, str(TOOLS))

import build_poe1_price_patch as poe1  # noqa: E402
from price_sources.models import BaseItemPair  # noqa: E402


COMMON = TOOLS / "poe2_patch_common.ps1"
PROFILES = TOOLS / "poe_patch_profiles.ps1"
POE1_COMMON = TOOLS / "poe1_patch_common.ps1"
POE1_UPDATE = TOOLS / "update_poe1_price_patch.ps1"
GUI = TOOLS / "price_patch_gui.ps1"


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


def powershell_function(script: str, name: str) -> str:
    match = re.search(rf"(?m)^function\s+{re.escape(name)}\b", script)
    assert match is not None, f"missing PowerShell function: {name}"
    next_match = re.search(r"(?m)^function\s+[\w-]+\b", script[match.end() :])
    if next_match is None:
        return script[match.start() :]
    return script[match.start() : match.end() + next_match.start()]


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


def test_poe1_localization_download_prefers_domestic_accelerators_and_validates_tool():
    localize = (TOOLS / "localize_poe1.ps1").read_text(encoding="utf-8-sig")
    download_sources = (
        "ghfast.top",
        "gh-proxy.com",
        "gh.ddlc.top",
        "ghproxy.it",
        "github.boki.moe",
        "ghproxy.net",
        "gh.jasonzeng.dev",
        "gh.monlor.com",
    )
    positions = [localize.index(f'Prefix = "https://{source}/"') for source in download_sources]
    assert positions == sorted(positions)
    assert positions[-1] < localize.index('Name = "GitHub 官方源"')
    assert "bdnb.cn" not in localize
    assert "$script:LatestReleaseApiUrl" in localize
    assert '"Accept" = "application/vnd.github+json"' in localize
    assert "$Asset.digest" in localize
    assert "releases/expanded_assets/" in localize
    assert "Get-Poe1LatestLocalizationRelease" in localize
    assert "Test-Poe1LocalizationExecutable" in localize
    assert "Get-FileHash -LiteralPath $Path -Algorithm SHA256" in localize
    assert "-ExpectedSha256 $Release.Sha256 -ExpectedSize $ExpectedSize" in localize
    assert "$File.Length -ne $ExpectedSize" in localize
    assert "SHA256 与最新版 Release 公布值不一致" in localize
    assert "PoeChinese3|LibGGPK3" in localize


def test_poe1_localization_release_api_uses_digest_and_exact_size():
    localize = (TOOLS / "localize_poe1.ps1").read_text(encoding="utf-8-sig")
    helper = powershell_function(localize, "Get-Poe1LatestLocalizationRelease")
    expected_hash = "a" * 64
    output = run_powershell(
        "$ErrorActionPreference='Stop'; $WarningPreference='SilentlyContinue'; "
        "$script:PatchVersion='test'; $script:LocalizationAssetName='PoeChinese3_win-x64.exe'; "
        "$script:LatestReleaseApiUrl='https://api.example/latest'; "
        "$script:LatestReleasePageUrl='https://github.example/releases/latest'; "
        "function Invoke-RestMethod { [pscustomobject]@{draft=$false;prerelease=$false;tag_name='v9.8.7';assets=@([pscustomobject]@{name='PoeChinese3_win-x64.exe';size=6184600;digest='sha256:"
        + expected_hash
        + "';browser_download_url='https://github.com/aianlinb/LibGGPK3/releases/download/v9.8.7/PoeChinese3_win-x64.exe'})} }; "
        f"{helper}; $result=Get-Poe1LatestLocalizationRelease 3>$null 6>$null; "
        "$result | ConvertTo-Json -Compress"
    )
    result = json.loads(output)
    assert result["Tag"] == "v9.8.7"
    assert result["Size"] == 6184600
    assert result["Sha256"] == expected_hash
    assert result["MetadataSourceName"] == "GitHub API 加速源 gh-proxy.com"


def test_poe1_localization_release_page_fallback_never_needs_bdnb():
    localize = (TOOLS / "localize_poe1.ps1").read_text(encoding="utf-8-sig")
    helper = powershell_function(localize, "Get-Poe1LatestLocalizationRelease")
    expected_hash = "b" * 64
    asset = "/aianlinb/LibGGPK3/releases/download/v9.8.7/PoeChinese3_win-x64.exe"
    output = run_powershell(
        "$ErrorActionPreference='Stop'; $WarningPreference='SilentlyContinue'; "
        "$script:PatchVersion='test'; $script:LocalizationAssetName='PoeChinese3_win-x64.exe'; "
        "$script:LatestReleaseApiUrl='https://api.example/latest'; "
        "$script:LatestReleasePageUrl='https://github.com/aianlinb/LibGGPK3/releases/latest'; "
        "function Invoke-RestMethod { throw 'API offline' }; "
        "function Invoke-WebRequest { param([string]$Uri); "
        "if($Uri -match 'expanded_assets'){return [pscustomobject]@{Content='"
        + f'<a href="{asset}">PoeChinese3_win-x64.exe</a><span>sha256:{expected_hash}</span>'
        + "'}}; "
        "return [pscustomobject]@{BaseResponse=[pscustomobject]@{ResponseUri=[uri]'https://ghfast.top/https://github.com/aianlinb/LibGGPK3/releases/tag/v9.8.7'};Content=''} }; "
        f"{helper}; $result=Get-Poe1LatestLocalizationRelease 3>$null 6>$null; "
        "$result | ConvertTo-Json -Compress"
    )
    result = json.loads(output)
    assert result == {
        "Tag": "v9.8.7",
        "Url": f"https://github.com{asset}",
        "Size": 0,
        "Sha256": expected_hash,
        "MetadataSourceName": "Release 页面加速源 ghfast.top",
    }


def test_poe1_gui_localization_process_reports_progress_without_blocking(tmp_path: Path):
    gui = GUI.read_text(encoding="utf-8-sig")
    working_dir = tmp_path / "游戏目录 with spaces"
    working_dir.mkdir()
    fixture = working_dir / "fake localize with spaces.ps1"
    fixture.write_text(
        "\n".join(
            [
                "param([string]$Poe1Dir)",
                "[Console]::OutputEncoding = [Text.Encoding]::UTF8",
                'Write-Host "阶段一"',
                "Start-Sleep -Milliseconds 350",
                'Write-Output "完成:$Poe1Dir"',
            ]
        ),
        encoding="utf-8-sig",
    )
    helpers = "\n".join(
        powershell_function(gui, name)
        for name in (
            "Read-PoePatchProcessLogText",
            "Get-PoePatchProcessLogTail",
            "Invoke-PoePatchMonitoredLocalization",
        )
    )

    output = run_powershell(
        f"$ErrorActionPreference='Stop'; Add-Type -AssemblyName System.Windows.Forms; {helpers}; "
        "$updates=New-Object System.Collections.Generic.List[string]; "
        f"$result=Invoke-PoePatchMonitoredLocalization -ScriptPath {ps_quote(fixture)} "
        f"-GameDirectory {ps_quote(working_dir)} -PollMilliseconds 50 -TimeoutMilliseconds 5000 "
        "-OnProgress { param([string]$text) $updates.Add($text) | Out-Null }; "
        "[pscustomobject]@{ExitCode=$result.ExitCode;StdOut=$result.StdOut;Updates=@($updates)} | ConvertTo-Json -Compress"
    )
    result = json.loads(output)

    assert result["ExitCode"] == 0
    assert f"完成:{working_dir}" in result["StdOut"]
    assert any("正在汉化 POE1（已运行" in item for item in result["Updates"])
    assert any("阶段一" in item for item in result["Updates"])


def test_poe1_gui_localization_returns_stderr_and_nonzero_exit(tmp_path: Path):
    gui = GUI.read_text(encoding="utf-8-sig")
    fixture = tmp_path / "fake failure.ps1"
    fixture.write_text(
        "param([string]$Poe1Dir)\n[Console]::OutputEncoding=[Text.Encoding]::UTF8\n[Console]::Error.WriteLine('模拟下载失败')\nexit 23\n",
        encoding="utf-8-sig",
    )
    helpers = "\n".join(
        powershell_function(gui, name)
        for name in (
            "Read-PoePatchProcessLogText",
            "Get-PoePatchProcessLogTail",
            "Stop-PoePatchProcessTree",
            "Invoke-PoePatchMonitoredLocalization",
        )
    )
    output = run_powershell(
        f"$ErrorActionPreference='Stop'; Add-Type -AssemblyName System.Windows.Forms; {helpers}; "
        f"$result=Invoke-PoePatchMonitoredLocalization -ScriptPath {ps_quote(fixture)} "
        f"-GameDirectory {ps_quote(tmp_path)} -PollMilliseconds 50 -TimeoutMilliseconds 5000; "
        "$result | Select-Object ExitCode,StdErr | ConvertTo-Json -Compress"
    )
    result = json.loads(output)
    assert result["ExitCode"] == 23
    assert "模拟下载失败" in result["StdErr"]


def test_poe1_gui_localization_timeout_stops_entire_process_tree(tmp_path: Path):
    gui = GUI.read_text(encoding="utf-8-sig")
    fixture = tmp_path / "fake hanging localization.ps1"
    fixture.write_text(
        "\n".join(
            [
                "param([string]$Poe1Dir)",
                "$pidPath=Join-Path $Poe1Dir 'localization-child.pid'",
                "$child=Start-Process powershell.exe -ArgumentList '-NoProfile','-Command','Start-Sleep -Seconds 60' -WindowStyle Hidden -PassThru",
                "[IO.File]::WriteAllText($pidPath,[string]$child.Id)",
                'Write-Output "子进程已启动"',
                "Start-Sleep -Seconds 60",
            ]
        ),
        encoding="utf-8-sig",
    )
    helpers = "\n".join(
        powershell_function(gui, name)
        for name in ("Stop-PoePatchProcessTree", "Invoke-PoePatchMonitoredLocalization")
    )
    output = run_powershell(
        f"$ErrorActionPreference='Stop'; Add-Type -AssemblyName System.Windows.Forms; {helpers}; "
        "$timedOut=$false; try { "
        f"Invoke-PoePatchMonitoredLocalization -ScriptPath {ps_quote(fixture)} "
        f"-GameDirectory {ps_quote(tmp_path)} -PollMilliseconds 50 -TimeoutMilliseconds 2000 | Out-Null "
        "} catch { $timedOut=$_.Exception.Message -match '已停止等待' }; "
        f"$pidPath=Join-Path {ps_quote(tmp_path)} 'localization-child.pid'; "
        "if(-not (Test-Path -LiteralPath $pidPath)){throw 'child pid was not written'}; "
        "$childId=[int][IO.File]::ReadAllText($pidPath); Start-Sleep -Milliseconds 300; "
        "$alive=Get-Process -Id $childId -ErrorAction SilentlyContinue; "
        "if($alive){Stop-Process -Id $childId -Force -ErrorAction SilentlyContinue;throw 'child survived timeout'}; "
        "if(-not $timedOut){throw 'timeout was not reported'}; 'PROCESS_TREE_STOPPED'"
    )
    assert "PROCESS_TREE_STOPPED" in output


def test_poe1_gui_localization_uses_hidden_redirected_child_process():
    gui = GUI.read_text(encoding="utf-8-sig")
    helper = powershell_function(gui, "Invoke-PoePatchMonitoredLocalization")

    assert "$StartInfo.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden" in helper
    assert "$StartInfo.RedirectStandardOutput = $true" in helper
    assert "$StartInfo.RedirectStandardError = $true" in helper
    assert "$Process.WaitForExit($PollMilliseconds)" in helper
    assert "[System.Windows.Forms.Application]::DoEvents()" in helper
    assert "-Wait -PassThru -WindowStyle Normal" not in gui
    assert "taskkill.exe" in gui
    assert "/T /F" in gui
    assert "$Form.Add_FormClosing" in gui
    assert "$EventArgs.Cancel = $true" in gui
    localize = (TOOLS / "localize_poe1.ps1").read_text(encoding="utf-8-sig")
    assert "Get-FileHash -LiteralPath $Target" not in localize


def test_poe1_current_dat_extraction_uses_one_batch_and_requires_english_baseitems():
    common = (TOOLS / "poe1_patch_common.ps1").read_text(encoding="utf-8-sig")
    function = common.split("function Invoke-Poe1ExtractDatFiles", 1)[1].split(
        "function New-Poe1PhysicalRestoreZip", 1
    )[0]
    assert function.count("Invoke-Poe1ExtractBatch") == 1
    assert "$RequiredPaths = @($LocalizedPaths + @($InstallInfo.EnBaseItemsPath))" in function
    assert "$OptionalPaths = @($InstallInfo.EnWordsPath)" in function
    assert "进程无法访问文件|文件正由另一进程使用" in common


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


def test_poe1_china_client_forces_auto_simplified_chinese_language(tmp_path: Path):
    game = tmp_path / "WeGame POE1"
    (game / "Bundles2").mkdir(parents=True)
    (game / "Bundles2" / "_.index.bin").write_bytes(b"index")
    (game / "wegame.ini").write_text("wegame", encoding="utf-8")
    (game / "rail_api64.dll").write_bytes(b"rail")

    output = run_powershell(
        f". {ps_quote(COMMON)}; . {ps_quote(PROFILES)}; "
        "function global:Get-Poe1ConfigLanguage { param([string]$GameDirectory = '', [string]$ConfigDirectory = '') return 'fr' }; "
        "function global:Get-PoeDetectedGameVersion { param([string]$GameDirectory) return 'poe1' }; "
        "$rows = foreach ($requested in @('auto','localization','zh-TW','config')) { "
        f"$info = Get-Poe1InstallInfo -GameDirectory {ps_quote(game)} -LanguageMode $requested; "
        "[pscustomobject]@{ Requested=$requested; Mode=$info.LanguageMode; Code=$info.EffectiveLanguageCode; Path=$info.TcBaseItemsPath; IsChina=$info.IsChina } }; "
        "$rows | ConvertTo-Json -Compress"
    )
    rows = json.loads(output)

    assert all(row["Mode"] == "auto" for row in rows)
    assert all(row["Code"] == "zh-CN" for row in rows)
    assert all(
        row["Path"] == "data/simplified chinese/baseitemtypes.datc64"
        for row in rows
    )
    assert all(row["IsChina"] for row in rows)


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


def test_poe1_official_registry_install_location_is_discovered(tmp_path: Path):
    game = tmp_path / "Path of Exile"
    game.mkdir()
    (game / "Content.ggpk").write_bytes(b"ggpk")
    normalized_game = str(game.resolve()).rstrip("\\")

    output = run_powershell(
        f". {ps_quote(COMMON)}; . {ps_quote(PROFILES)}; "
        "function global:Get-ItemProperty { "
        "param([string]$LiteralPath, [string]$Path, [object]$ErrorAction); "
        "$key = if (-not [string]::IsNullOrWhiteSpace($LiteralPath)) { $LiteralPath } else { $Path }; "
        "if ($key -eq 'HKCU:\\Software\\GrindingGearGames\\Path of Exile') { "
        f"return [pscustomobject]@{{ InstallLocation = {ps_quote(game)} }} "
        "} }; "
        f"$candidate = @(Get-Poe1GameDirectoryCandidates -IgnoreSavedDirectory | Where-Object {{ $_.Path.TrimEnd('\\') -eq {ps_quote(normalized_game)} }}); "
        "if ($candidate.Count -ne 1) { throw 'official registry candidate missing' }; "
        'Write-Output "$($candidate[0].Source)`n$($candidate[0].InstallInfo.Mode)`n$($candidate[0].Priority)"'
    )

    assert output.splitlines() == ["GGG 官服注册表", "GGPK", "15"]


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
    assert "$LanguageCombo.Enabled = $ShowLanguage -and -not $IsChina" in gui
    assert "$LanguageCombo.SelectedIndex = $AutoLanguageIndex" in gui
    assert '$LocalizeButton.Visible = ($Version -eq "poe1" -and $IsInternational)' in gui
    assert "$PathTextBox.Add_TextChanged" in gui
    assert '$SelectedLanguageMode = "auto"' in gui


def test_poe1_restore_baseline_manifest_and_self_heal_are_strictly_scoped():
    common = (TOOLS / "poe1_patch_common.ps1").read_text(encoding="utf-8-sig")
    update = (TOOLS / "update_poe1_price_patch.ps1").read_text(encoding="utf-8-sig")
    restore = (TOOLS / "restore_poe1_price_patch.ps1").read_text(encoding="utf-8-sig")
    logical = powershell_function(common, "New-Poe1LogicalRestoreZip")
    validator = powershell_function(common, "Test-Poe1LogicalRestoreZip")

    assert 'version = 2' in logical
    for field in ("game_version", "install_kind", "mode", "language_code", "restore_files"):
        assert field in logical
    for field in ("install_kind", "mode", "language_code", "baseitems_path", "words_path"):
        assert field in validator
    assert "New-CleanPoe1LogicalRestoreZipFromPatchedState" in update
    assert '"--patch-scope", "none"' in update
    assert '"--strict-feature-cleanup"' in update
    assert "New-Poe1RestoreBaselineFromCurrentDat" in restore
    assert "自动清理迁移" in restore
    builder = (TOOLS / "build_poe1_price_patch.py").read_text(encoding="utf-8")
    main = builder[builder.index("def main(") :]
    assert main.index("if fetch_prices:") < main.index("discover_poe_ninja_league(")
    assert 'league_source = "not-required"' in builder


def test_poe1_bundles2_mutation_fingerprint_detects_count_and_content_changes(
    tmp_path: Path,
):
    game = tmp_path / "game"
    bundles = game / "Bundles2"
    lib = bundles / "LibGGPK3"
    lib.mkdir(parents=True)
    (bundles / "_.index.bin").write_bytes(b"index-v1")
    (lib / "bundle.bin").write_bytes(b"bundle-v1")

    output = run_powershell(
        f"$ErrorActionPreference='Stop'; . {ps_quote(POE1_COMMON)}; "
        f"$game={ps_quote(game)}; $index=Join-Path $game 'Bundles2\\_.index.bin'; "
        "$before=Get-Poe1Bundles2MutationFingerprint -Poe1Dir $game; "
        "Assert-Poe1Bundles2MutationFingerprintCurrent -Expected $before -Poe1Dir $game | Out-Null; "
        "[IO.File]::WriteAllBytes($index,[Text.Encoding]::UTF8.GetBytes('index-v2')); "
        "$contentDetected=$false; try { Assert-Poe1Bundles2MutationFingerprintCurrent -Expected $before -Poe1Dir $game | Out-Null } "
        "catch { $contentDetected=$_.Exception.Message -match '内容与本次写入准备时不同' }; "
        "if(-not $contentDetected){ throw 'same-count content mutation was not detected' }; "
        "$after=Get-Poe1Bundles2MutationFingerprint -Poe1Dir $game; "
        "[IO.File]::WriteAllBytes((Join-Path $game 'Bundles2\\LibGGPK3\\new.bin'),[byte[]](1,2,3)); "
        "$countDetected=$false; try { Assert-Poe1Bundles2MutationFingerprintCurrent -Expected $after -Poe1Dir $game | Out-Null } "
        "catch { $countDetected=$_.Exception.Message -match '文件数量与本次写入准备时不同' }; "
        "if(-not $countDetected){ throw 'file-count mutation was not detected' }; "
        "Write-Output 'POE1_MUTATIONS_DETECTED'"
    )

    assert "POE1_MUTATIONS_DETECTED" in output


def test_poe1_bundles2_repeat_updates_reuse_backup_for_cn_and_international(
    tmp_path: Path,
):
    candidate = tmp_path / "physical-restore.zip"
    candidate.write_bytes(b"verified-clean-restore")
    candidate_hash = hashlib.sha256(candidate.read_bytes()).hexdigest()
    migrated = tmp_path / "migrated-restore.zip"
    migrated.write_bytes(b"migrated-clean-restore")
    state_path = tmp_path / "installed-state.json"
    current_hash = "a" * 64
    stale_hash = "b" * 64
    script = rf"""
$ErrorActionPreference = 'Stop'
function Import-SelectedFunction([string]$Path, [string]$Name) {{
    $Tokens=$null; $Errors=$null
    $Ast=[System.Management.Automation.Language.Parser]::ParseFile($Path,[ref]$Tokens,[ref]$Errors)
    if ($Errors.Count) {{ throw $Errors[0] }}
    $Function=$Ast.Find({{param($Node) $Node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $Node.Name -eq $Name}}, $true)
    if ($null -eq $Function) {{ throw "missing function: $Name" }}
    return $Function.Extent.Text
}}
$Candidate = {ps_quote(candidate)}
$Migrated = {ps_quote(migrated)}
$CurrentHash = '{current_hash}'
$StaleHash = '{stale_hash}'
$script:MigrationCalls = 0
function Assert-Poe1PhysicalRestoreZip {{
    return [pscustomobject]@{{restore_files=@()}}
}}
function Assert-Poe1PhysicalRestoreCurrent {{ throw 'stale pre-install snapshot' }}
function Assert-Poe1Bundles2MutationFingerprintCurrent {{
    param($Expected,[string]$Poe1Dir)
    if ([string]$Expected.inventory_sha256 -ne $CurrentHash) {{ throw 'stale installed state' }}
}}
function Publish-Poe1PhysicalRestoreZip {{ param([string]$Source) return $Source }}
function New-Poe1PhysicalRestoreZip {{ throw 'clean-source backup path must not run' }}
function New-CleanPoe1PhysicalRestoreZipFromPatchedState {{
    param([string]$OutputZip)
    $script:MigrationCalls++
    return $Migrated
}}
$Poe1Dir = 'mock-game'
$PersistentDir = {ps_quote(tmp_path)}
$RestoreDir = {ps_quote(tmp_path / 'missing-output')}
$PersistentPhysicalRestore = {ps_quote(tmp_path / 'published.zip')}
$PhysicalRestoreOut = {ps_quote(tmp_path / 'new-restore.zip')}
$PhysicalRestoreNames = @('{candidate.name}')
$Extracted = [pscustomobject]@{{LocalizedBaseItems='mock-baseitems.datc64'}}
$RepoRoot = 'mock-repo'
Invoke-Expression (Import-SelectedFunction {ps_quote(POE1_UPDATE)} 'Get-Poe1Bundles2InstalledState')
Invoke-Expression (Import-SelectedFunction {ps_quote(POE1_UPDATE)} 'Test-Poe1Bundles2InstalledStateCurrent')
Invoke-Expression (Import-SelectedFunction {ps_quote(POE1_UPDATE)} 'Ensure-Poe1PhysicalRestoreZip')

# Old releases only have the pre-install snapshot, which is stale after their
# own PatchBundle3 write.  A patched source must be migrated offline.
$InstallInfo = [pscustomobject]@{{InstallKind='POE1-CN-WeGame-Bundles2'; TcBaseItemsPath='data/simplified chinese/baseitemtypes.datc64'}}
$Poe1Bundles2InstalledStatePath = {ps_quote(tmp_path / 'missing-state.json')}
$legacy = Ensure-Poe1PhysicalRestoreZip -SourceLooksPatched $true
if ($script:MigrationCalls -ne 1 -or $legacy -ne $Migrated) {{
    throw "STALE_LEGACY_DID_NOT_MIGRATE:$legacy/$($script:MigrationCalls)"
}}

foreach ($Case in @(
    [pscustomobject]@{{Kind='POE1-CN-WeGame-Bundles2'; Target='data/simplified chinese/baseitemtypes.datc64'}},
    [pscustomobject]@{{Kind='POE1-Intl-Bundles2'; Target='data/traditional chinese/baseitemtypes.datc64'}}
)) {{
    $InstallInfo = [pscustomobject]@{{InstallKind=$Case.Kind; TcBaseItemsPath=$Case.Target}}
    $State = [ordered]@{{
        kind='poe1-price-patch-bundles2-installed-state'
        version=1
        install_kind=$Case.Kind
        target_path=$Case.Target
        restore_zip_sha256='{candidate_hash}'
        bundles2_fingerprint=[ordered]@{{
            version=1
            algorithm='path-length-sha256-v1'
            files=@()
            inventory_sha256=$CurrentHash
        }}
    }}
    $State | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath {ps_quote(state_path)} -Encoding UTF8
    $Poe1Bundles2InstalledStatePath = {ps_quote(state_path)}
    $script:MigrationCalls = 0
    $repeat = Ensure-Poe1PhysicalRestoreZip -SourceLooksPatched $true
    if ($script:MigrationCalls -ne 0 -or $repeat -ne $Candidate) {{
        throw "REPEAT_UPDATE_DID_NOT_REUSE:$($Case.Kind):$repeat/$($script:MigrationCalls)"
    }}
}}
Write-Output 'POE1_CN_AND_INTL_REPEAT_UPDATE_STATE_HANDLED'
"""

    assert "POE1_CN_AND_INTL_REPEAT_UPDATE_STATE_HANDLED" in run_powershell(script)


def test_poe1_bundles2_migration_and_write_order_protects_real_game():
    update = POE1_UPDATE.read_text(encoding="utf-8-sig")
    migration = powershell_function(
        update, "New-CleanPoe1PhysicalRestoreZipFromPatchedState"
    )
    ensure = powershell_function(update, "Ensure-Poe1PhysicalRestoreZip")

    assert migration.index("$MigrationPrecondition") < migration.index(
        "New-Item -ItemType Directory -Force -Path $SandboxBundles2"
    )
    sandbox_patch = migration.index(
        "Invoke-Poe1LogicalRestoreWithRetry -Poe1Dir $SandboxRoot"
    )
    package = migration.index("New-Poe1PhysicalRestoreZip -Poe1Dir $SandboxRoot")
    final_real_check = migration.rindex(
        "Assert-Poe1Bundles2MutationFingerprintCurrent"
    )
    assert sandbox_patch < package < final_real_check
    assert "Invoke-Poe1LogicalRestoreWithRetry -Poe1Dir $Poe1Dir" not in migration
    assert ensure.index("Assert-Poe1PhysicalRestoreCurrent") < ensure.index(
        "New-CleanPoe1PhysicalRestoreZipFromPatchedState"
    )

    select_backup = update.index("$PhysicalRestoreZip = Ensure-Poe1PhysicalRestoreZip")
    precondition = update.index("$Poe1Bundles2WritePrecondition =", select_backup)
    final_guard = update.index(
        "Assert-Poe1Bundles2MutationFingerprintCurrent", precondition
    )
    write_and_readback = update.index("Invoke-Poe1PatchWithRetry -Poe1Dir $Poe1Dir", final_guard)
    durable_state = update.index("Write-Poe1Bundles2InstalledState", write_and_readback)
    success = update.index('Write-Host "POE1 物价补丁已安装并通过读回校验。"', durable_state)
    assert select_backup < precondition < final_guard < write_and_readback < durable_state < success


def test_poe1_logical_restore_installs_only_game_dat_entries(tmp_path: Path):
    source = tmp_path / "logical-restore.zip"
    payload = tmp_path / "install-payload.zip"
    base_path = "data/simplified chinese/baseitemtypes.datc64"
    words_path = "data/simplified chinese/words.datc64"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr(base_path, b"baseitems")
        archive.writestr(words_path, b"words")
        archive.writestr("poe1-restore-manifest.json", b'{"kind":"validation-only"}')

    output = run_powershell(
        f"$ErrorActionPreference='Stop'; . {ps_quote(POE1_COMMON)}; "
        f"$info=[pscustomobject]@{{TcBaseItemsPath='{base_path}';TcWordsPath='{words_path}'}}; "
        f"New-Poe1InstallPayloadZip -SourceZip {ps_quote(source)} -InstallInfo $info -OutputZip {ps_quote(payload)} | Out-Null; "
        f"$archive=[IO.Compression.ZipFile]::OpenRead({ps_quote(payload)}); "
        "try { @($archive.Entries | ForEach-Object FullName) | ConvertTo-Json -Compress } finally { $archive.Dispose() }"
    )

    assert json.loads(output) == [base_path, words_path]
    common = POE1_COMMON.read_text(encoding="utf-8-sig")
    assert "FileNotFoundException|Could not found file in Index" in common



def test_python_invocation_avoids_admin_elevation():
    common = COMMON.read_text(encoding="utf-8-sig")
    invoke = powershell_function(common, "Invoke-Poe2Python")
    detector = powershell_function(common, "Test-Poe2PythonElevationFailure")
    assert "__COMPAT_LAYER" in invoke
    assert "RunAsInvoker" in invoke
    assert "Get-Poe2PythonElevationMessage" in invoke
    assert "poe_python.exe" in common
    assert "以管理员身份运行" in common
    assert "requireAdministrator" not in common
    assert "ERROR_ELEVATION_REQUIRED|740" not in detector


def test_python_elevation_detection_ignores_dat_size_false_positive():
    detector = powershell_function(
        COMMON.read_text(encoding="utf-8-sig"),
        "Test-Poe2PythonElevationFailure",
    )
    script = (
        "$ErrorActionPreference='Stop';\n"
        f"{detector}\n"
        "$failed = New-Object System.Collections.Generic.List[string]\n"
        "function Assert-Case([string]$Name, [bool]$Actual, [bool]$Expect) {\n"
        "  if ($Actual -ne $Expect) { [void]$failed.Add(\"${Name}:$Actual\") }\n"
        "}\n"
        "Assert-Case 'dat-size' (Test-Poe2PythonElevationFailure -Text 'dat size: 2724108 -> 2740570' -ExitCode 0) $false\n"
        "Assert-Case 'elapsed' (Test-Poe2PythonElevationFailure -Text '\"elapsed_ms\": 740' -ExitCode 0) $false\n"
        "Assert-Case 'phrase' (Test-Poe2PythonElevationFailure -Text 'The requested operation requires elevation' -ExitCode 1) $true\n"
        "Assert-Case 'error-code' (Test-Poe2PythonElevationFailure -Text '' -Exception 'Win32 error 740') $true\n"
        "Assert-Case 'exit' (Test-Poe2PythonElevationFailure -Text '' -ExitCode 740) $true\n"
        "if ($failed.Count) { throw ($failed -join '; ') }\n"
        "'ok'\n"
    )
    assert run_powershell(script) == "ok"
