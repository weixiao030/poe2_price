import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_official_bundle_change_rejects_physical_restore_even_with_unchanged_dat(tmp_path):
    game = tmp_path / 'game'
    bundles = game / 'Bundles2'
    bundles.mkdir(parents=True)
    (game / 'PathOfExile.exe').write_bytes(b'fixture')
    (bundles / 'a.bundle.bin').write_bytes(b'official-before')
    (bundles / '_.index.bin').write_bytes(b'index')
    literal = lambda value: "'" + str(value).replace("'", "''") + "'"
    script = tmp_path / 'verify.ps1'
    script.write_text(f'''
$ErrorActionPreference='Stop'
. {literal(ROOT / '物价补丁/tools/poe1_patch_common.ps1')}
function Get-Poe1BaseItemsSignature {{ return @{{compatibility_sha256=('a'*64)}} }}
$Info=@{{InstallKind='Intl-Steam-Bundles2';TcBaseItemsPath='Data/BaseItemTypes.datc64'}}
$Zip=New-Poe1PhysicalRestoreZip -Poe1Dir {literal(game)} -InstallInfo $Info -CurrentBaseItems 'unchanged' -OutputZip {literal(tmp_path / 'restore.zip')} -RepoRoot {literal(tmp_path)}
$Manifest=Assert-Poe1PhysicalRestoreZip -ZipPath $Zip -InstallInfo $Info -CurrentBaseItems 'unchanged' -RepoRoot {literal(tmp_path)} -Poe1Dir {literal(game)}
if($Manifest.version -ne 2){{throw 'expected bound manifest'}}
[IO.File]::WriteAllText({literal(bundles / 'a.bundle.bin')},'official-after-different-size')
$Rejected=$false
try {{ Assert-Poe1PhysicalRestoreZip -ZipPath $Zip -InstallInfo $Info -CurrentBaseItems 'unchanged' -RepoRoot {literal(tmp_path)} -Poe1Dir {literal(game)} | Out-Null }}
catch {{ if($_.Exception.Message -notlike '*已过期*'){{throw}}; $Rejected=$true }}
if(!$Rejected){{throw 'stale physical archive accepted'}}
if([IO.File]::ReadAllText({literal(bundles / '_.index.bin')}) -ne 'index'){{throw 'index changed'}}
'STALE_BASE_REJECTED'
''', encoding='utf-8-sig')
    result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script)], capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert b'STALE_BASE_REJECTED' in result.stdout
