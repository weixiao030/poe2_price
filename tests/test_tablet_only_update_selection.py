"""The updater must resolve ordinary seasons only for ordinary price layers."""
import json

import pytest

from tests.test_patched_restore_migration import TOOLS, read, run_windows_powershell


def run_production_selection(scope, china, mode, tablet_names, tablet_affixes, fail_directory):
    update = read(TOOLS / "update_price_patch.ps1")
    flags_start = update.index("$PatchUniqueWordsEnabled =")
    flags_end = update.index("$PatchIslandRumourHintsEnabled =", flags_start)
    selection_start = update.index("$IsChinaClient =", flags_end)
    selection_end = update.index("$CanUseSeasonCache =", selection_start)
    resolved_argument = update.index('"--resolved-leagues"', selection_end)
    arguments_start = update.rfind("\nif (", selection_end, resolved_argument)
    arguments_end = update.index("\nif (", resolved_argument)
    script = rf"""
$ErrorActionPreference = 'Stop'
$PatchScope = '{scope}'
$TabletPrices = ${str(tablet_names).lower()}
$TabletAffixPrices = ${str(tablet_affixes).lower()}
$League = 'selected-scout'
$PoeNinjaLeague = 'Selected Ninja'
$PoeCurrencySeason = 'selected-cn'
$LeagueMode = '{mode}'
$LeagueIsCurrent = $false
$InstallInfo = [pscustomobject]@{{
    IsChina = ${str(china).lower()}
    InstallKind = '{'CN-WeGame-Bundles2' if china else 'INT-Steam-Bundles2'}'
}}
$script:DirectoryCalls = 0
function Resolve-PoePatchLeagueSelection {{
    param($GameVersion, $League, $PoeNinjaLeague, $PoeCurrencySeason,
          $LeagueMode, $LeagueIsCurrent, [switch]$China, $TimeoutSeconds)
    $script:DirectoryCalls += 1
    if (${str(fail_directory).lower()}) {{ throw 'ORDINARY_DIRECTORY_UNAVAILABLE' }}
    return [pscustomobject]@{{
        ScoutLeague='resolved-scout'; PoeNinjaLeague='Resolved Ninja';
        PoeCurrencySeason='resolved-cn'; UseCurrentEndpoint=$true; IsCurrent=$true;
        Value='Resolved Season'; DiscoveryFallback=$false
    }}
}}
{update[flags_start:flags_end]}
$Failure = ''
try {{
    {update[selection_start:selection_end]}
}} catch {{ $Failure = $_.Exception.Message }}
$BuildArgs = @()
{update[arguments_start:arguments_end]}
$Result = [ordered]@{{
    failure=$Failure; calls=$script:DirectoryCalls;
    fetch_prices=$PatchPriceFetchEnabled;
    tablet_prices=$TabletPrices; tablet_affixes=$PatchTabletAffixesEnabled;
    league=$League; ninja=$PoeNinjaLeague; cn=$PoeCurrencySeason;
    current=$LeagueIsCurrent; arguments=@($BuildArgs)
}}
'__RESULT__' + (ConvertTo-Json -InputObject $Result -Compress)
"""
    output = run_windows_powershell(script)
    return json.loads(output.split("__RESULT__", 1)[1].strip())


@pytest.mark.parametrize("china", [False, True], ids=["international", "china"])
@pytest.mark.parametrize("mode", ["auto", "fixed"])
@pytest.mark.parametrize("names,affixes", [(True, True), (True, False), (False, True), (False, False)])
def test_tablet_only_update_skips_unavailable_ordinary_season_directory(china, mode, names, affixes):
    result = run_production_selection("none", china, mode, names, affixes, fail_directory=True)
    assert result["failure"] == "", "Only-tablet update must survive an ordinary season-directory outage"
    assert result["calls"] == 0
    assert result["fetch_prices"] == (names or affixes)
    assert result["tablet_prices"] == names
    assert result["tablet_affixes"] == affixes
    assert result["arguments"] == []
    assert (result["league"], result["ninja"], result["cn"]) == (
        "selected-scout", "Selected Ninja", "selected-cn"
    )


@pytest.mark.parametrize("china", [False, True], ids=["international", "china"])
@pytest.mark.parametrize("scope", ["all", "currency", "uniques"])
def test_ordinary_price_layers_still_resolve_and_forward_the_selected_season(china, scope):
    result = run_production_selection(scope, china, "auto", True, True, fail_directory=False)
    assert result["failure"] == ""
    assert result["calls"] == 1
    assert result["current"] is True
    assert result["fetch_prices"] is True
    assert (result["league"], result["ninja"], result["cn"]) == (
        "resolved-scout", "Resolved Ninja", "resolved-cn"
    )
    assert result["arguments"] == [
        "--resolved-leagues", "--league-is-current", "true",
        "--fallback-price-sources", "poe-ninja",
    ]
