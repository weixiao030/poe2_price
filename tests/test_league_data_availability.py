import pytest

from tests.test_league_selection import run_case


@pytest.mark.parametrize("version,number", [("poe1", "1"), ("poe2", "2")])
def test_cn_checks_exact_current_and_history_and_preserves_network_errors(tmp_path, version, number):
    assert run_case(tmp_path, r"""
        $script:urls = @()
        function Invoke-RestMethod {
            param($Uri, $Headers, $TimeoutSec)
            $script:urls += $Uri
            if ($Uri -like '*season_list*') { return ,@('Current', 'RunesofAldur', 'standard', 'Offline') }
            if ($Uri -like '*season=standard') { return ,@() }
            if ($Uri -like '*season=Offline') { throw 'HTTP 503 / network timeout' }
            return ,@([pscustomobject]@{category_label='Currency';items=@([pscustomobject]@{item_name='Orb';latest_buy1=0})})
        }
        $options = @(Get-PoePatchLeagueOptions -GameVersion VERSION -China)
        if (($options.PriceDataStatus -join ',') -ne 'available,available,empty,unknown') { throw 'Wrong statuses' }
        if ($script:urls -notcontains 'https://poecurrency.top/api/summary?version=NUMBER') { throw 'Missing current endpoint' }
        if ($script:urls -notcontains 'https://poecurrency.top/api/summary?version=NUMBER&season=RunesofAldur') { throw 'Missing history endpoint' }
        if (-not $options[0].IsCurrent -or $options[1].IsCurrent) { throw 'Promoted history' }
        'OK'
    """.replace('VERSION', version).replace('NUMBER', number)) == 'OK'


@pytest.mark.parametrize('response,expected', [
    ('return ,@()', 'empty'),
    ("return ,@([pscustomobject]@{category_label='Currency';items=@()})", 'empty'),
    ('return $null', 'unknown'),
    ("return '<html>proxy error</html>'", 'unknown'),
    ("return [pscustomobject]@{error='rate limited';items=@()}", 'unknown'),
    ("return ,@([pscustomobject]@{category_label='Currency';items=$null})", 'unknown'),
    ("return ,@([pscustomobject]@{category_label='Currency';items=@()},[pscustomobject]@{error='bad category'})", 'unknown'),
    ("return ,@([pscustomobject]@{category_label='Currency';items=@([pscustomobject]@{item_name='Old orb';latest_datetime='2020-01-01'})})", 'available'),
    ("throw 'HTTP 404'", 'unknown'),
    ("throw 'HTTP 429'", 'unknown'),
])
def test_only_valid_empty_summary_is_hidden(tmp_path, response, expected):
    assert run_case(tmp_path, r"""
        function Invoke-RestMethod { param($Uri,$Headers,$TimeoutSec) RESPONSE }
        $option=New-PoePatchLeagueOption -Value 'standard' -Season 'standard'
        $state=Get-PoePatchChinaPriceDataStatus -GameVersion poe2 -Option $option
        if ($state -ne 'EXPECTED') { throw "Wrong state: $state" }
        'OK'
    """.replace('RESPONSE', response).replace('EXPECTED', expected)) == 'OK'


def test_cache_rechecks_empty_seasons_and_all_empty_never_revives_old_cache(tmp_path):
    assert run_case(tmp_path, r"""
        $script:phase='empty'
        function Invoke-RestMethod {
            param($Uri,$Headers,$TimeoutSec)
            if ($script:phase -eq 'offline') { throw 'offline' }
            if ($Uri -like '*season_list*') { return ,@('Current','standard') }
            if ($script:phase -eq 'empty') { return ,@() }
            return ,@([pscustomobject]@{category_label='Currency';items=@([pscustomobject]@{item_name='Orb'})})
        }
        $empty=@(Get-PoePatchLeagueOptions -GameVersion poe2 -China -ForceRefresh)
        $cached=@(Get-PoePatchLeagueOptions -GameVersion poe2 -China)
        if (@($empty | Where-Object { $_.PriceDataStatus -ne 'empty' }).Count -or @($cached | Where-Object { $_.PriceDataStatus -ne 'empty' }).Count) { throw 'Empty list lost in cache' }
        if (-not $cached[0].IsCurrent -or $cached[1].IsCurrent) { throw 'Current identity changed' }
        $script:phase='online'
        $fresh=@(Get-PoePatchLeagueOptions -GameVersion poe2 -China -ForceRefresh)
        if (@($fresh | Where-Object { $_.PriceDataStatus -ne 'available' }).Count) { throw 'Empty status stuck' }
        $script:phase='offline'
        $fallback=@(Get-PoePatchLeagueOptions -GameVersion poe2 -China -ForceRefresh)
        if (@($fallback | Where-Object { $_.PriceDataStatus -ne 'unknown' -or -not $_.DiscoveryFallback }).Count) { throw 'Network error treated as empty' }
        'OK'
    """) == 'OK'
