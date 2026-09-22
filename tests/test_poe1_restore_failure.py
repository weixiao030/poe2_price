from pathlib import Path
import subprocess
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def test_locked_restore_target_preserves_the_only_preoperation_backup(tmp_path):
    game = tmp_path / 'game'
    bundles = game / 'Bundles2'
    bundles.mkdir(parents=True)
    (bundles / '_.index.bin').write_bytes(b'original-index-that-must-survive')
    archive = tmp_path / 'restore.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('Bundles2/_.index.bin', b'replacement-index')
    def literal(value):
        return "'" + str(value).replace("'", "''") + "'"
    script = tmp_path / 'test.ps1'
    script.write_text(f'''
$ErrorActionPreference='Stop'
. {literal(ROOT / '物价补丁/tools/poe2_patch_common.ps1')}
. {literal(ROOT / '物价补丁/tools/poe1_patch_common.ps1')}
function Assert-Poe1PhysicalRestoreZip {{ return [pscustomobject]@{{restore_files=@([pscustomobject]@{{path='Bundles2/_.index.bin';sha256='unused'}})}} }}
function Assert-Poe2GameFilesAvailable {{}}
function Assert-Poe1File {{ param($Path,$Name)
  $script:Locked=[IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::None)
  throw 'injected-readback-failure'
}}
$Failed=$false
try {{ Restore-Poe1PhysicalBundles2 -Poe1Dir {literal(game)} -ZipPath {literal(archive)} -InstallInfo @{{}} -CurrentBaseItems 'unused' -RepoRoot {literal(tmp_path)} }}
catch {{ $Failed=$true; if($_.Exception.Message -notlike '*injected-readback-failure*') {{throw}} }}
finally {{ if($script:Locked){{$script:Locked.Dispose()}} }}
if(!$Failed){{throw 'expected restore failure'}}
$Backups=@(Get-ChildItem -LiteralPath {literal(bundles)} -Directory -Filter '.poe1-restore-rollback-*')
if($Backups.Count -ne 1){{throw 'rollback backup was removed'}}
if([IO.File]::ReadAllText((Join-Path $Backups[0].FullName '_.index.bin')) -ne 'original-index-that-must-survive'){{throw 'original data lost'}}
'BACKUP_PRESERVED'
''', encoding='utf-8-sig')
    result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script)], capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert b'BACKUP_PRESERVED' in result.stdout
