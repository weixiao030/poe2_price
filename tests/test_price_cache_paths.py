"""Exercise cache isolation and real atomic writes in Windows PowerShell 5.1."""
import json
from pathlib import Path
import subprocess

import pytest

from tests.test_patched_restore_migration import (
    COMMON, UPDATE, ps_path, read, run_windows_powershell,
)


def cache_setup():
    return rf"""
$ErrorActionPreference = 'Stop'
. '{ps_path(COMMON)}'
$tokens=$null; $errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile('{ps_path(UPDATE)}',[ref]$tokens,[ref]$errors)
if ($errors.Count) {{ throw $errors[0] }}
$assignments=@('PriceCacheKey','PriceCacheFileKey','CachedPatchZip','CachedSummaryJson','LegacyCachedPatchZip')
$nodes=@($assignments | ForEach-Object {{
    $left='$'+$_
    $ast.Find({{param($n) $n -is [System.Management.Automation.Language.AssignmentStatementAst] -and $n.Left.Extent.Text -eq $left}},$true)
}})
function Set-CachePaths {{
    foreach ($node in $nodes) {{ Invoke-Expression $node.Extent.Text }}
    [pscustomobject]@{{key=$PriceCacheFileKey;zip=$CachedPatchZip;summary=$CachedSummaryJson;legacy=$LegacyCachedPatchZip}}
}}
$InstallInfo=@{{InstallKind='CN-WeGame-Bundles2';LanguageFileSlug='zh-CN'}}
$BuildPatchScope='all'; $PatchBuildMode='append'; $CanPatchUniqueWords=$true
$PatchIslandRumourHintsEnabled=$true; $PatchTabletAffixesEnabled=$true; $TabletPrices=$true
$LeagueCacheToken=Get-PoePatchLeagueCacheToken -ScoutLeague same -PoeNinjaLeague Same -PoeCurrencySeason cn-one
"""


def test_cache_filenames_isolate_all_build_dimensions(tmp_path):
    result = run_windows_powershell(cache_setup() + rf"""
$PriceCacheDir='{ps_path(tmp_path)}'
$results=@(Set-CachePaths)
$InstallInfo.InstallKind='INT-Standalone-GGPK'; $results+=Set-CachePaths
$InstallInfo.InstallKind='CN-WeGame-Bundles2'
$InstallInfo.LanguageFileSlug='zh-TW'; $results+=Set-CachePaths
$InstallInfo.LanguageFileSlug='zh-CN'
$BuildPatchScope='currency'; $results+=Set-CachePaths; $BuildPatchScope='all'
$PatchBuildMode='fixed'; $results+=Set-CachePaths; $PatchBuildMode='append'
$CanPatchUniqueWords=$false; $results+=Set-CachePaths; $CanPatchUniqueWords=$true
$PatchIslandRumourHintsEnabled=$false; $results+=Set-CachePaths; $PatchIslandRumourHintsEnabled=$true
$PatchTabletAffixesEnabled=$false; $results+=Set-CachePaths
$TabletPrices=$false; $results+=Set-CachePaths
$PatchTabletAffixesEnabled=$true; $results+=Set-CachePaths; $TabletPrices=$true
$LeagueCacheToken=Get-PoePatchLeagueCacheToken -ScoutLeague same -PoeNinjaLeague Same -PoeCurrencySeason cn-two
$results+=Set-CachePaths
$LeagueCacheToken=Get-PoePatchLeagueCacheToken -ScoutLeague next -PoeNinjaLeague Next -PoeCurrencySeason cn-one
$results+=Set-CachePaths
$LeagueCacheToken=Get-PoePatchLeagueCacheToken -ScoutLeague same -PoeNinjaLeague Same -PoeCurrencySeason cn-one
$repeat=Set-CachePaths
if ($repeat.key -ne $results[0].key) {{ throw 'Non-deterministic cache identity' }}
$results | ConvertTo-Json -Compress
""")
    paths = json.loads(result)
    assert len({item['key'] for item in paths}) == 12
    assert all(len(Path(item['summary']).name) <= 80 for item in paths)
    assert all(item['zip'] != item['legacy'] for item in paths)


def test_atomic_cache_creation_and_replacement_fit_windows_path_limit(tmp_path):
    # Include a realistically long user profile and all runtime subdirectories.
    # Use -File, matching the real desktop worker rather than -Command.
    cache = tmp_path / ('profile-' + 'x' * max(0, 115 - len(str(tmp_path)) - 9))
    assert len(str(cache)) <= 120
    script = tmp_path / 'cache-write.ps1'
    script.write_text("[Console]::OutputEncoding=[Text.UTF8Encoding]::new()\n" + cache_setup() + rf"""
if ($PSVersionTable.PSVersion.Major -ne 5) {{ throw 'Windows PowerShell 5.1 required' }}
$PriceCacheDir='{ps_path(cache)}'
$paths=Set-CachePaths
$source=Join-Path '{ps_path(tmp_path)}' 'payload.dat'
[IO.File]::WriteAllText($source,'first')
if ($paths.legacy.Length -lt 260) {{ throw 'Test must exercise an overlong legacy path' }}
# Reserve the longest suffix used for atomic-copy/replace recovery as well.
if ($paths.summary.Length + 52 -ge 260) {{ throw 'Insufficient Windows path margin' }}
foreach ($content in @('first','replacement')) {{
    [IO.File]::WriteAllText($source,$content)
    foreach ($destination in @($paths.zip,$paths.summary)) {{
        Copy-Poe2FileAtomically -Source $source -Destination $destination | Out-Null
        if ([IO.File]::ReadAllText($destination) -ne $content) {{ throw 'Cache readback mismatch' }}
    }}
}}
if (@(Get-ChildItem -LiteralPath $PriceCacheDir -Force).Count -ne 2) {{ throw 'Atomic operation left temporary files' }}
'CACHE_ATOMIC_WRITE_OK'
""", encoding='utf-8-sig')
    result = subprocess.run(
        ['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy',
         'Bypass', '-File', str(script)],
        capture_output=True, encoding='utf-8', errors='replace', timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'CACHE_ATOMIC_WRITE_OK' in result.stdout


@pytest.mark.parametrize('primary,legacy,enabled,expected', [
    ('valid', 'valid', True, 'primary.zip'),
    ('missing', 'valid', True, 'legacy.zip'),
    ('invalid', 'valid', True, 'legacy.zip'),
    ('invalid', 'invalid', True, ''),
    ('missing', 'valid', False, ''),
])
def test_fallback_checks_legacy_cache_without_bypassing_validation(
    tmp_path, primary, legacy, enabled, expected,
):
    source = read(UPDATE)
    start = source.index('    $CompatibleFallbackPatch = ""\n')
    end = source.index('    if (-not [string]::IsNullOrWhiteSpace($CompatibleFallbackPatch))', start)
    for name, value in [('primary.zip', primary), ('legacy.zip', legacy)]:
        if value != 'missing':
            (tmp_path / name).write_text(value, encoding='utf-8')
    result = run_windows_powershell(rf"""
$ErrorActionPreference='Stop'
$CachedPatchZip='{ps_path(tmp_path / 'primary.zip')}'
$LegacyCachedPatchZip='{ps_path(tmp_path / 'legacy.zip')}'
$BuildStageDir='{ps_path(tmp_path)}'; $TcBaseItems='current-base.dat'
$CanUseSeasonCache=${str(enabled).lower()}; $TabletPrices=$true; $BuildPatchScope='all'
function Test-PricePatchZipCompatible {{
    param($Path,$ReferenceDat)
    if ($ReferenceDat -ne 'current-base.dat') {{ throw 'Lost current baseline check' }}
    return [IO.File]::ReadAllText($Path) -eq 'valid'
}}
function New-CorePricePatchFromCache {{
    param($CacheZip,$OutputZip)
    if ([IO.File]::ReadAllText($CacheZip) -ne 'valid') {{ throw 'Invalid cache accepted' }}
    Copy-Item -LiteralPath $CacheZip -Destination $OutputZip
    return $OutputZip
}}
{source[start:end]}
$selected=if ($FallbackCacheZip) {{ Split-Path -Leaf $FallbackCacheZip }} else {{ '' }}
[pscustomobject]@{{selected=$selected;core=$CompatibleFallbackPatch}} | ConvertTo-Json -Compress
""")
    selected = json.loads(result)
    assert selected['selected'] == expected
    assert bool(selected['core']) == bool(expected)
    assert (tmp_path / 'legacy.zip').read_text(encoding='utf-8') == legacy
