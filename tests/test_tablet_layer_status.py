import base64
import json
from pathlib import Path
import shutil
import subprocess

import pytest


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
$results | ConvertTo-Json -Compress
'''.replace('__SOURCE__', str(source).replace("'", "''"))
    encoded = base64.b64encode(script.encode('utf-16-le')).decode()
    result = subprocess.run([shell, '-NoProfile', '-EncodedCommand', encoded], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == ['unavailable', 'unavailable', 'applied', 'applied', 'unavailable', 'unknown', 'disabled']
