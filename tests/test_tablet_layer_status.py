import base64
import json
from pathlib import Path
import shutil
import subprocess

import pytest


def test_tablet_options_have_four_distinct_cache_keys():
    shell = shutil.which('powershell.exe') or shutil.which('pwsh')
    if not shell:
        pytest.skip('PowerShell required')
    source = Path(__file__).resolve().parents[1] / '物价补丁/tools/update_price_patch.ps1'
    script = r'''
$tokens=$null; $errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile('__SOURCE__',[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw $errors[0] }
$node=$ast.Find({param($n) $n -is [System.Management.Automation.Language.AssignmentStatementAst] -and $n.Left.Extent.Text -eq '$PriceCacheKey'},$true)
$InstallInfo=@{InstallKind='CN-Bundles2'; LanguageFileSlug='zh-CN'}
$BuildPatchScope='all'; $PatchBuildMode='append'; $CanPatchUniqueWords=$true
$PatchIslandRumourHintsEnabled=$true; $LeagueCacheToken='same-season'
$results=@()
foreach ($enabled in @($false,$true)) {
    $PatchTabletAffixesEnabled=$enabled
    foreach ($prices in @($false,$true)) {
        $TabletPrices=$prices
        Invoke-Expression $node.Extent.Text
        $results+=$PriceCacheKey
    }
}
$results | ConvertTo-Json -Compress
'''.replace('__SOURCE__', str(source).replace("'", "''"))
    result = subprocess.run([shell, '-NoProfile', '-EncodedCommand',
                             base64.b64encode(script.encode('utf-16-le')).decode()],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    keys = json.loads(result.stdout)
    assert len(set(keys)) == 4
    assert all(key.endswith('_league-same-season') for key in keys)
    assert '_tablet-prices-off_' in keys[0] and '_tablet-prices-on_' in keys[1]
    assert keys[2].replace('_tablet-markup-v1', '') == keys[0]
    assert keys[3].replace('_tablet-markup-v1', '') == keys[1]


def test_current_summary_distinguishes_missing_layer_from_missing_single_quote():
    shell = shutil.which('powershell.exe') or shutil.which('pwsh')
    if not shell:
        pytest.skip('PowerShell required')
    source = Path(__file__).resolve().parents[1] / '物价补丁/tools/update_price_patch.ps1'
    script = r'''
$tokens=$null; $errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile('__SOURCE__',[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw $errors[0] }
$node=$ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Get-TabletLayerStatus'},$true)
Invoke-Expression $node.Extent.Text
$cases=@(
    [pscustomobject]@{status='skipped';reason='offline'},
    [pscustomobject]@{status='partial';resources=@()},
    [pscustomobject]@{status='partial';resources=@(@{tablet='Ritual_Tablet'});game_coverage=@{missing_quotes=@('one')}},
    [pscustomobject]@{status='ok';resources=@(@{tablet='Ritual_Tablet'})},
    [pscustomobject]@{status='partial'},
    $null
)
$results=@($cases | ForEach-Object { Get-TabletLayerStatus -Enabled $true -Summary @{tablet_affixes=$_} })
$results+=Get-TabletLayerStatus -Enabled $false -Summary $null
$node=$ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Get-WholeTabletLayerStatus'},$true)
Invoke-Expression $node.Extent.Text
$results+=Get-WholeTabletLayerStatus -Enabled $true -Summary @{whole_tablets=@{status='partial';installation_status='applied'}}
$results+=Get-WholeTabletLayerStatus -Enabled $true -Summary @{whole_tablets=@{status='unavailable';installation_status='unavailable'}}
$results+=Get-WholeTabletLayerStatus -Enabled $true -Summary $null
$results+=Get-WholeTabletLayerStatus -Enabled $false -Summary $null
$results | ConvertTo-Json -Compress
'''.replace('__SOURCE__', str(source).replace("'", "''"))
    encoded = base64.b64encode(script.encode('utf-16-le')).decode()
    result = subprocess.run([shell, '-NoProfile', '-EncodedCommand', encoded], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == ['unavailable', 'unavailable', 'applied', 'applied', 'unavailable', 'unknown', 'disabled',
                                        'applied', 'unavailable', 'unknown', 'disabled']
