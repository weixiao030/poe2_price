from pathlib import Path

from tests.test_game_directory_selection import COMMON, ps_quote, run_powershell


def run_case(tmp_path: Path, body: str) -> str:
    return run_powershell(
        f"$ErrorActionPreference='Stop'; . {ps_quote(COMMON)}; "
        f"$env:POE2_PATCH_ROOT={ps_quote(tmp_path)}; " + body
    )


def test_cn_directory_does_not_probe_prices_or_replace_latest(tmp_path):
    assert run_case(tmp_path, """
        function Invoke-RestMethod {
            param($Uri, $Headers, $TimeoutSec)
            if ($Uri -ne 'https://poecurrency.top/api/season_list?version=poe2') { throw "Unexpected request $Uri" }
            return ,@('0.5.5', 'RunesofAldur', 'standard')
        }
        $options = @(Get-PoePatchLeagueOptions -GameVersion poe2 -China)
        if ($options.Count -ne 3 -or $options[0].Value -ne '0.5.5' -or -not $options[0].IsCurrent) { throw 'Missing latest' }
        if ($options[0].ScoutLeague -or $options[0].PoeNinjaLeague -or $options[1].IsCurrent) { throw 'Mixed provider IDs' }
        'OK'
    """) == "OK"


def test_cn_current_history_and_rollover_use_correct_endpoints(tmp_path):
    assert run_case(tmp_path, """
        function Invoke-RestMethod {
            param($Uri, $Headers, $TimeoutSec)
            if ($Uri -like '*season_list*') { return @('0.6', '0.5.5', 'RunesofAldur') }
            throw 'Reference unavailable'
        }
        $auto = Resolve-PoePatchLeagueSelection -GameVersion poe2 -China -LeagueMode auto -PoeCurrencySeason '0.5.5'
        $fixed = Resolve-PoePatchLeagueSelection -GameVersion poe2 -China -LeagueMode fixed -PoeCurrencySeason '0.5.5' -LeagueIsCurrent $true
        if ($auto.Value -ne '0.6' -or -not $auto.UseCurrentEndpoint -or $fixed.UseCurrentEndpoint) { throw 'Rollover changed a pinned season' }
        $live = Get-PoePatchChinaSummaryUrl -GameVersion poe2 -Season $auto.PoeCurrencySeason -UseCurrentEndpoint $auto.UseCurrentEndpoint
        $old = Get-PoePatchChinaSummaryUrl -GameVersion poe2 -Season $fixed.PoeCurrencySeason -UseCurrentEndpoint $fixed.UseCurrentEndpoint
        if ($live -ne 'https://poecurrency.top/api/summary?version=2') { throw $live }
        if ($old -ne 'https://poecurrency.top/api/summary?version=2&season=0.5.5') { throw $old }
        if ((Get-PoePatchChinaSummaryUrl -GameVersion poe1 -UseCurrentEndpoint $true) -ne 'https://poecurrency.top/api/summary?version=1') { throw 'POE1 parameter' }
        'OK'
    """) == "OK"


def test_ninja_is_an_independent_directory_without_inventing_scout_slugs(tmp_path):
    assert run_case(tmp_path, """
        function Invoke-RestMethod {
            param($Uri, $Headers, $TimeoutSec)
            if ($Uri -like '*poe2scout*') { throw 'Scout offline' }
            return [pscustomobject]@{
                economyLeagues = @(
                    [pscustomobject]@{ name='HC New'; url='newhc'; hardcore=$true },
                    [pscustomobject]@{ name='New'; url='new'; indexed=$false; hardcore=$false },
                    [pscustomobject]@{ name='Standard'; url='standard'; hardcore=$false })
                oldEconomyLeagues = @([pscustomobject]@{name='Old';url='old';hardcore=$false})
            }
        }
        $options = @(Get-PoePatchLeagueOptions -GameVersion poe2)
        if ($options.Count -ne 3 -or $options[0].PoeNinjaLeague -ne 'New' -or $options[0].ScoutLeague) { throw 'Ninja fallback identity' }
        if (-not $options[0].IsCurrent -or $options[1].IsCurrent) { throw 'Current marker' }
        'OK'
    """) == "OK"


def test_catalog_cache_is_partitioned_and_survives_outage(tmp_path):
    assert run_case(tmp_path, """
        function Invoke-RestMethod {
            param($Uri, $Headers, $TimeoutSec)
            if ($Uri -like '*season_list*') { return @('cn-new','cn-old') }
            return @([pscustomobject]@{Value='New';ShortName='new-id';IsCurrent=$true})
        }
        $null = @(Get-PoePatchLeagueOptions -GameVersion poe2)
        $null = @(Get-PoePatchLeagueOptions -GameVersion poe2 -China)
        function Invoke-RestMethod { throw 'Offline' }
        $intl = @(Get-PoePatchLeagueOptions -GameVersion poe2 -ForceRefresh)
        $cn = @(Get-PoePatchLeagueOptions -GameVersion poe2 -China -ForceRefresh)
        if ($intl[0].Value -ne 'New' -or $cn[0].Value -ne 'cn-new' -or -not $intl[0].DiscoveryFallback) { throw 'Mixed cache' }
        $failed = $false
        try { $null = @(Get-PoePatchLeagueOptions -GameVersion poe1 -China -ForceRefresh) } catch { $failed = $true }
        if (-not $failed) { throw 'POE1 reused POE2 cache' }
        'OK'
    """) == "OK"


def test_pinned_international_selection_needs_no_directory_request(tmp_path):
    assert run_case(tmp_path, """
        function Invoke-RestMethod { throw 'Unexpected request' }
        $fixed = Resolve-PoePatchLeagueSelection -GameVersion poe2 -LeagueMode fixed -League 'old-id' -PoeNinjaLeague 'Old League'
        if ($fixed.ScoutLeague -ne 'old-id' -or $fixed.PoeNinjaLeague -ne 'Old League') { throw 'Pinned selection lost' }
        $ninja = Resolve-PoePatchLeagueSelection -GameVersion poe2 -LeagueMode fixed -PoeNinjaLeague 'Ninja Only'
        if ($ninja.ScoutLeague -or $ninja.PoeNinjaLeague -ne 'Ninja Only') { throw 'Invented Scout ID' }
        'OK'
    """) == "OK"


def test_unidentified_cn_current_does_not_inherit_old_provider_ids(tmp_path):
    assert run_case(tmp_path, """
        function Invoke-RestMethod { throw 'Offline' }
        $auto = Resolve-PoePatchLeagueSelection -GameVersion poe2 -China -LeagueMode auto -PoeCurrencySeason 'old-cn' -League old -PoeNinjaLeague Old
        if (-not $auto.UseCurrentEndpoint -or $auto.PoeCurrencySeason -or $auto.ScoutLeague -or $auto.PoeNinjaLeague) { throw 'Unknown current cached as old season' }
        $fixed = Resolve-PoePatchLeagueSelection -GameVersion poe2 -China -LeagueMode fixed -PoeCurrencySeason 'old-cn' -LeagueIsCurrent $true
        if ($fixed.UseCurrentEndpoint -or $fixed.PoeCurrencySeason -ne 'old-cn') { throw 'Pinned CN silently followed current' }
        'OK'
    """) == "OK"


def test_cn_reference_uses_independent_ids_and_historical_exact_match(tmp_path):
    assert run_case(tmp_path, """
        function Invoke-RestMethod {
            param($Uri, $Headers, $TimeoutSec)
            if ($Uri -like '*season_list*') { return @('0.5.5','RunesofAldur','unknown-history') }
            return @(
                [pscustomobject]@{Value='Forbidden Rites';ShortName='forbiddenrites';IsCurrent=$true},
                [pscustomobject]@{Value='Runes of Aldur';ShortName='runes';IsCurrent=$true})
        }
        $auto = Resolve-PoePatchLeagueSelection -GameVersion poe2 -China -LeagueMode auto
        if ($auto.PoeCurrencySeason -ne '0.5.5' -or $auto.ScoutLeague -ne 'forbiddenrites' -or $auto.PoeNinjaLeague -ne 'Forbidden Rites') { throw 'CN ID sent to international provider' }
        $old = Resolve-PoePatchLeagueSelection -GameVersion poe2 -China -LeagueMode fixed -PoeCurrencySeason RunesofAldur
        if ($old.ScoutLeague -ne 'runes' -or $old.UseCurrentEndpoint) { throw 'History mapping' }
        $unknown = Resolve-PoePatchLeagueSelection -GameVersion poe2 -China -LeagueMode fixed -PoeCurrencySeason unknown-history
        if ($unknown.ScoutLeague -or $unknown.PoeNinjaLeague -or $unknown.UseCurrentEndpoint) { throw 'History mapped to newest' }
        'OK'
    """) == "OK"


def test_cn_patch_cache_identity_includes_the_cn_season(tmp_path):
    assert run_case(tmp_path, """
        $a = Get-PoePatchLeagueCacheToken -ScoutLeague same -PoeNinjaLeague Same -PoeCurrencySeason cn-one
        $b = Get-PoePatchLeagueCacheToken -ScoutLeague same -PoeNinjaLeague Same -PoeCurrencySeason cn-two
        if ($a -eq $b) { throw 'CN seasons share a patch cache' }
        'OK'
    """) == "OK"


def test_corrupt_or_expired_catalog_is_not_a_fabricated_fallback(tmp_path):
    assert run_case(tmp_path, """
        function Invoke-RestMethod { throw 'Offline' }
        $dir = Join-Path $env:POE2_PATCH_ROOT 'output/league_catalog'
        $null = New-Item -ItemType Directory -Path $dir -Force
        $path = Join-Path $dir 'poe2-international.json'
        foreach ($case in @('broken', 'expired')) {
            $option = New-PoePatchLeagueOption -Value Old -Scout old -Ninja Old -Current $true
            $savedAt = [DateTime]::UtcNow
            if ($case -eq 'broken') { $option.PSObject.Properties.Remove('ScoutLeague') }
            else { $savedAt = $savedAt.AddDays(-8) }
            @{ Version=1; Scope='poe2-international'; SavedAt=$savedAt.ToString('o'); Options=@($option) } |
                ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $path -Encoding UTF8
            $failed = $false
            try { $null = @(Get-PoePatchLeagueOptions -GameVersion poe2 -ForceRefresh) } catch { $failed = $true }
            if (-not $failed) { throw "Accepted $case cache" }
        }
        'OK'
    """) == "OK"


def test_transition_with_two_current_leagues_has_one_latest(tmp_path):
    assert run_case(tmp_path, """
        function Invoke-RestMethod {
            return @(
                [pscustomobject]@{Value='New';ShortName='new';IsCurrent=$true},
                [pscustomobject]@{Value='Previous';ShortName='previous';IsCurrent=$true})
        }
        $options = @(Get-PoePatchLeagueOptions -GameVersion poe2)
        if (-not $options[0].IsCurrent -or $options[1].IsCurrent -or $options[1].Value -ne 'Previous') { throw 'Incorrect current marker' }
        'OK'
    """) == "OK"


def test_history_only_primary_directory_tries_independent_current_directory(tmp_path):
    assert run_case(tmp_path, """
        function Invoke-RestMethod {
            param($Uri)
            if ($Uri -like '*poe2scout*') { return @([pscustomobject]@{Value='Old';ShortName='old';IsCurrent=$false}) }
            return [pscustomobject]@{economyLeagues=@([pscustomobject]@{name='New';hardcore=$false});oldEconomyLeagues=@()}
        }
        $current = Resolve-PoePatchLeagueSelection -GameVersion poe2 -LeagueMode auto
        if ($current.PoeNinjaLeague -ne 'New' -or $current.ScoutLeague) { throw 'Did not try independent directory' }
        function Invoke-RestMethod {
            param($Uri)
            if ($Uri -like '*poe2scout*') { return @([pscustomobject]@{Value='Old';ShortName='old';IsCurrent=$false}) }
            throw 'Ninja offline'
        }
        $options = @(Get-PoePatchLeagueOptions -GameVersion poe2 -ForceRefresh)
        if ($options.Count -ne 1 -or $options[0].IsCurrent -or $options[0].Value -ne 'Old') { throw 'History no longer selectable' }
        'OK'
    """) == "OK"


def test_partial_cn_cache_never_assigns_live_prices_to_history(tmp_path):
    assert run_case(tmp_path, """
        function Invoke-RestMethod { throw 'Offline' }
        $dir = Join-Path $env:POE2_PATCH_ROOT 'output/league_catalog'
        $null = New-Item -ItemType Directory -Path $dir -Force
        $path = Join-Path $dir 'poe2-china.json'
        $current = New-PoePatchLeagueOption -Value New -Season New -Current $true
        $current.PSObject.Properties.Remove('ScoutLeague')
        $old = New-PoePatchLeagueOption -Value Old -Season Old
        @{ Version=1; Scope='poe2-china'; SavedAt=[DateTime]::UtcNow.ToString('o'); Options=@($current,$old) } |
            ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $path -Encoding UTF8
        $selected = Resolve-PoePatchLeagueSelection -GameVersion poe2 -China -LeagueMode auto
        if (-not $selected.UseCurrentEndpoint -or $selected.PoeCurrencySeason -or $selected.ScoutLeague -or $selected.PoeNinjaLeague) { throw 'Current prices labeled as history' }
        'OK'
    """) == "OK"
