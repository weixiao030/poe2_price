"""A successful recovery must not turn a failed game update into success."""
from pathlib import Path
import subprocess

import pytest


SOURCE = (Path(__file__).resolve().parents[1] / '物价补丁/tools/update_price_patch.ps1').read_text(encoding='utf-8-sig')


@pytest.mark.parametrize('mode', ['ggpk', 'bundles'])
def test_install_failure_remains_failure_after_successful_rollback(tmp_path, mode):
    restore = tmp_path / 'restore_price_patch.ps1'
    restore.write_text('exit 0', encoding='utf-8-sig')
    archive = tmp_path / 'restore.zip'
    archive.write_bytes(b'fake archive; rollback is stubbed')
    def literal(value):
        return "'" + str(value).replace("'", "''") + "'"
    start_marker = '$InstallError = $_.Exception.Message' if mode == 'ggpk' else '$PatchError = $_.Exception.Message'
    end_marker = '\n        }\n        Write-Host "补丁已写入 Content.ggpk。"' if mode == 'ggpk' else '\n        }\n    }\n}\nelse {'
    start = SOURCE.index(start_marker)
    end = SOURCE.index(end_marker, start)
    catch_body = SOURCE[start:end]
    script = tmp_path / 'worker.ps1'
    script.write_text(f'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$global:LASTEXITCODE = 0
$LogicalRestoreReady = $true
$RestoreZip = {literal(archive)}
$PhysicalRestoreZip = {literal(archive)}
$Poe2Dir = {literal(tmp_path)}
$CodeToolsRoot = {literal(tmp_path)}
$BundledInstallerDir = {literal(tmp_path)}
$ContentGgpk = 'unused.ggpk'
function Assert-File {{ param($Path,$Label) if (!(Test-Path -LiteralPath $Path)) {{ throw 'missing fixture' }} }}
function Invoke-TabletResourceTool {{ $global:LASTEXITCODE = 0; Write-Output 'ROLLBACK_OK' }}
function Assert-GgpkPatchApplied {{ $global:LASTEXITCODE = 0; Write-Output 'READBACK_OK' }}
try {{
    try {{ throw 'injected-original-install-failure' }}
    catch {{ {catch_body} }}
    exit $LASTEXITCODE
}} catch {{
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}}
''', encoding='utf-8-sig')
    completed = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script)], capture_output=True, timeout=30)
    assert completed.returncode == 1, completed.stdout + completed.stderr
    assert b'injected-original-install-failure' in completed.stderr
    assert '已自动恢复' in completed.stderr.decode('utf-8')
