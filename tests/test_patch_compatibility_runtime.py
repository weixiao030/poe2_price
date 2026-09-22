"""Exercise the update gate with the same isolated Python used by releases."""
import subprocess
from pathlib import Path
import zipfile

import pytest

from tests.test_tablet_affixes import synthetic_baseitems

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / '物价补丁/tools'
SCRIPT = (TOOLS / 'update_price_patch.ps1').read_text(encoding='utf-8-sig')
PYTHON = ROOT / 'desktop/.runtime/tools/python/poe_python.exe'


def function(name, next_name):
    start = SCRIPT.index(f'function {name}')
    return SCRIPT[start:SCRIPT.index(f'function {next_name}', start)]


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def run_powershell(tmp_path, script):
    path = tmp_path / '验证.ps1'
    path.write_text('$ErrorActionPreference = "Stop"\n' + script, encoding='utf-8-sig')
    result = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                             '-File', str(path)], cwd=tmp_path, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr


def test_update_gate_accepts_valid_patch_and_reports_actual_validator_failure(tmp_path):
    if not PYTHON.exists():
        pytest.skip('prepare the bundled Python runtime first')
    source = tmp_path / 'source.datc64'
    data = synthetic_baseitems() + b'\0' * 1048576
    source.write_bytes(data)
    archive = tmp_path / '补丁.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('data/balance/baseitemtypes.datc64', data)
    broken_tools = tmp_path / 'broken-tools'
    broken_tools.mkdir()
    (broken_tools / 'poe2_tablet_refs.py').write_text(
        "raise RuntimeError('validator-startup-regression')\n", encoding='utf-8')
    script = f"""
        . {literal(TOOLS / 'poe2_patch_common.ps1')}
        $RepoRoot = {literal(tmp_path)}
        $CodeToolsRoot = {literal(TOOLS)}
        $InstallInfo = [pscustomobject]@{{ TcBaseItemsPath = 'data/balance/baseitemtypes.datc64' }}
        function Ensure-PythonRequests {{ param([string]$RepoRoot) return {literal(PYTHON)} }}
        function Assert-File {{ param([string]$Path, [string]$Label)
            if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {{ throw "missing $Label" }}
        }}
        {function('Get-BaseItemsMetadataSignature', 'Test-RestoreZipUsable')}
        {function('Test-PricePatchZipCompatible', 'New-CorePricePatchFromCache')}
        if (-not (Test-PricePatchZipCompatible {literal(archive)} {literal(source)} -ThrowOnFailure)) {{
            throw 'compatible core was rejected'
        }}
        $Bytes = [System.IO.File]::ReadAllBytes({literal(source)})
        $Bytes[12] = $Bytes[12] -bxor 1
        [System.IO.File]::WriteAllBytes({literal(source)}, $Bytes)
        if (Test-PricePatchZipCompatible {literal(archive)} {literal(source)}) {{
            throw 'changed fixed field was accepted'
        }}
        $CodeToolsRoot = {literal(broken_tools)}
        $Rejected = $false
        try {{ Test-PricePatchZipCompatible {literal(archive)} {literal(source)} -ThrowOnFailure | Out-Null }}
        catch {{
            if ($_.Exception.Message -notlike '*validator-startup-regression*') {{ throw }}
            $Rejected = $true
        }}
        if (-not $Rejected) {{ throw 'validator failure was accepted' }}
        if (Test-PricePatchZipCompatible {literal(archive)} {literal(source)} -WarningVariable Details) {{
            throw 'broken validator accepted cache'
        }}
        if (($Details -join '') -notlike '*validator-startup-regression*') {{ throw 'missing cache diagnostic' }}
    """
    run_powershell(tmp_path, script)


def test_extraction_compaction_preserves_tablet_mapping_inputs(tmp_path):
    # Run the production call as well as the production cleanup function.
    call = next(line for line in SCRIPT.splitlines() if line.startswith('Compact-LatestBaseItems $LatestDir '))
    variables = ('EnBaseItems TcBaseItems EnWords TcWords TcEndgameMaps UniqueGoldPrices '
                 'TabletTemplateIt TabletTemplateCsd TabletMapCsd TabletGlobalCsd '
                 'TabletMods TabletStats TabletTags').split()
    latest = tmp_path / 'latest'
    latest.mkdir()
    for name in [*variables, 'unused']:
        (latest / name).write_bytes(name.encode())
    assignments = '\n'.join(f'${name} = {literal(latest / name)}' for name in variables)
    run_powershell(tmp_path, f"""
        . {literal(TOOLS / 'poe2_patch_common.ps1')}
        $RepoRoot = {literal(tmp_path)}
        $LatestDir = {literal(latest)}
        {assignments}
        {function('Compact-LatestBaseItems', 'Test-BaseItemsLookPatched')}
        {call}
    """)
    assert {path.name for path in latest.iterdir()} == set(variables)
    for name in variables:
        assert (latest / name).read_bytes() == name.encode()
