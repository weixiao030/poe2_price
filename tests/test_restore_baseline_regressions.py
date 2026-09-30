"""Regression coverage for price detection and clean localization baselines."""
import sys

import pytest

from tests.test_patched_restore_migration import (
    TOOLS, powershell_function, ps_path, read, run_windows_powershell,
)
from tests.test_tablet_affixes import names, synthetic_baseitems


@pytest.mark.parametrize("script_name", ["update_price_patch.ps1", "restore_price_patch.ps1"])
@pytest.mark.parametrize("price", ["2C", "<1C", "2D", "2E", ""])
def test_poe2_baseitems_probe_recognizes_every_generated_currency(tmp_path, script_name, price):
    source = tmp_path / "baseitems.datc64"
    data = synthetic_baseitems()
    if price:
        entries = names.scan_base_item_names(data)
        replacements, warnings = names.build_replacements(
            entries, [{"metadata_path": entries[-1].metadata_path, "price": price}],
            "=", True, "append", False,
        )
        assert warnings == []
        data = names.apply_replacements_append(data, replacements)
    source.write_bytes(data)
    function = powershell_function(read(TOOLS / script_name), "Test-BaseItemsLookPatched")
    script = function + rf"""
$ErrorActionPreference = 'Stop'
$RepoRoot = '{ps_path(tmp_path)}'
$CodeToolsRoot = '{ps_path(TOOLS)}'
function Ensure-PythonRequests {{ return '{ps_path(sys.executable)}' }}
function Invoke-Poe2Python {{
    param($Python, $ArgumentList, [switch]$Quiet)
    $Text = & $Python @ArgumentList 2>&1 | Out-String
    return [pscustomobject]@{{ExitCode=$LASTEXITCODE; Text=$Text}}
}}
$Detected = Test-BaseItemsLookPatched '{ps_path(source)}'
if ($Detected -ne ${str(bool(price)).lower()}) {{ throw 'Price marker detection disagrees with generated DAT' }}
'PRICE_MARKERS_DETECTED'
"""
    assert "PRICE_MARKERS_DETECTED" in run_windows_powershell(script)


@pytest.mark.parametrize("active_layer", ["", "base", "words"])
def test_poe1_refreshes_clean_localization_but_keeps_repeat_update_baseline(tmp_path, active_layer):
    current = tmp_path / "current.dat"
    current.write_text("new localized names", encoding="utf-8")
    old = tmp_path / "old.zip"
    old.write_text("previous localized names", encoding="utf-8")
    update = read(TOOLS / "update_poe1_price_patch.ps1")
    start = update.index('    Write-Poe1Step "准备独立 POE1 还原底板"')
    end = update.index('    if (-not $NoInstall) {', start)
    production_selection = update[start:end]
    script = rf"""
$ErrorActionPreference = 'Stop'
$CurrentBasePatched = ${str(active_layer == 'base').lower()}
$CurrentWordsPatched = ${str(active_layer == 'words').lower()}
$Extracted = [pscustomobject]@{{LocalizedBaseItems='{ps_path(current)}'; LocalizedWords='{ps_path(current)}'}}
$PersistentLogicalRestore = '{ps_path(old)}'
$LogicalRestoreOut = '{ps_path(tmp_path / 'new.zip')}'
$InstallInfo = [pscustomobject]@{{}}
$RepoRoot = '{ps_path(tmp_path)}'
function Write-Poe1Step {{}}
function Test-Poe1LogicalRestoreZip {{ return $true }}
function New-Poe1LogicalRestoreZip {{
    param($BaseItems, $Words, $OutputZip, $InstallInfo, $RepoRoot)
    Copy-Item -LiteralPath $BaseItems -Destination $OutputZip -Force
    return $OutputZip
}}
function New-CleanPoe1LogicalRestoreZipFromPatchedState {{ throw 'Repeat update must keep its original baseline' }}
{production_selection}
$Actual = [IO.File]::ReadAllText($LogicalRestoreZip)
if ($Actual -ne '{'previous localized names' if active_layer else 'new localized names'}') {{
    throw "Selected wrong localization baseline: $Actual"
}}
'LOCALIZATION_BASELINE_OK'
"""
    assert "LOCALIZATION_BASELINE_OK" in run_windows_powershell(script)
