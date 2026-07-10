import base64
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "物价补丁" / "tools"
COMMON = TOOLS / "poe2_patch_common.ps1"
UPDATE = TOOLS / "update_price_patch.ps1"
RESTORE = TOOLS / "restore_price_patch.ps1"


def run_windows_powershell(script: str, timeout: int = 120) -> str:
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-EncodedCommand",
            encoded,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def ps_path(path: Path) -> str:
    return str(path).replace("'", "''")


def test_v2_fingerprint_inventory_and_legacy_v1_age_rules(tmp_path: Path):
    game = tmp_path / "game"
    script = rf"""
$ErrorActionPreference = 'Stop'
. '{ps_path(COMMON)}'
$Game = '{ps_path(game)}'
New-Item -ItemType Directory -Force -Path (Join-Path $Game 'Bundles2') | Out-Null
[IO.File]::WriteAllBytes((Join-Path $Game 'PathOfExile.exe'), [byte[]](1,2,3))
[IO.File]::WriteAllBytes((Join-Path $Game 'Bundles2/Tiny.V0.1.bundle.bin'), [byte[]](4,5,6))
$Fingerprint = Get-Poe2PhysicalBaseFingerprint -Poe2Dir $Game
$Manifest = [pscustomobject]@{{kind='poe2-price-patch-physical-restore';version=2;base_fingerprint=$Fingerprint}}
Assert-Poe2PhysicalRestoreManifestCurrent -Manifest $Manifest -Poe2Dir $Game | Out-Null
Write-Output 'V2_MATCH'

[IO.File]::WriteAllBytes((Join-Path $Game 'Bundles2/Added.bundle.bin'), [byte[]](7))
try {{ Assert-Poe2PhysicalRestoreManifestCurrent -Manifest $Manifest -Poe2Dir $Game | Out-Null; throw 'expected add rejection' }} catch {{ if ($_.Exception.Message -eq 'expected add rejection') {{ throw }} }}
Remove-Item (Join-Path $Game 'Bundles2/Added.bundle.bin') -Force
[IO.File]::AppendAllText((Join-Path $Game 'Bundles2/Tiny.V0.1.bundle.bin'), 'changed')
try {{ Assert-Poe2PhysicalRestoreManifestCurrent -Manifest $Manifest -Poe2Dir $Game | Out-Null; throw 'expected change rejection' }} catch {{ if ($_.Exception.Message -eq 'expected change rejection') {{ throw }} }}
Remove-Item (Join-Path $Game 'Bundles2/Tiny.V0.1.bundle.bin') -Force
try {{ Assert-Poe2PhysicalRestoreManifestCurrent -Manifest $Manifest -Poe2Dir $Game | Out-Null; throw 'expected delete rejection' }} catch {{ if ($_.Exception.Message -eq 'expected delete rejection') {{ throw }} }}
[IO.File]::WriteAllBytes((Join-Path $Game 'Bundles2/Tiny.V0.1.bundle.bin'), [byte[]](4,5,6))
Write-Output 'V2_INVENTORY_CHANGES_REJECTED'

$OldTime = (Get-Date).ToUniversalTime().AddHours(-1)
[IO.File]::SetLastWriteTimeUtc((Join-Path $Game 'PathOfExile.exe'), $OldTime)
[IO.File]::SetLastWriteTimeUtc((Join-Path $Game 'Bundles2/Tiny.V0.1.bundle.bin'), $OldTime)
$V1 = [pscustomobject]@{{kind='poe2-price-patch-physical-restore';version=1;created_at=(Get-Date).ToUniversalTime().ToString('o')}}
Assert-Poe2PhysicalRestoreManifestCurrent -Manifest $V1 -Poe2Dir $Game | Out-Null
$V1.created_at = (Get-Date).ToUniversalTime().AddDays(-1).ToString('o')
try {{ Assert-Poe2PhysicalRestoreManifestCurrent -Manifest $V1 -Poe2Dir $Game | Out-Null; throw 'expected legacy rejection' }} catch {{ if ($_.Exception.Message -eq 'expected legacy rejection') {{ throw }} }}
$V1.created_at = (Get-Date).ToUniversalTime().AddDays(1).ToString('o')
try {{ Assert-Poe2PhysicalRestoreManifestCurrent -Manifest $V1 -Poe2Dir $Game | Out-Null; throw 'expected future timestamp rejection' }} catch {{ if ($_.Exception.Message -eq 'expected future timestamp rejection') {{ throw }} }}
Write-Output 'V1_AGE_AND_FUTURE_RULES_OK'
"""
    output = run_windows_powershell(script)
    assert "V2_MATCH" in output
    assert "V2_INVENTORY_CHANGES_REJECTED" in output
    assert "V1_AGE_AND_FUTURE_RULES_OK" in output


def test_atomic_generation_and_restore_transaction_rollback(tmp_path: Path):
    game = tmp_path / "game"
    script = rf"""
$ErrorActionPreference = 'Stop'
. '{ps_path(COMMON)}'
function Assert-Poe2GameFilesAvailable {{ param([string]$Poe2Dir,[string]$IndexPath) }}
function Import-SelectedFunction([string]$Path, [string]$Name) {{
    $Tokens=$null; $Errors=$null
    $Ast=[System.Management.Automation.Language.Parser]::ParseFile($Path,[ref]$Tokens,[ref]$Errors)
    if ($Errors.Count) {{ throw $Errors[0] }}
    return $Ast.Find({{param($Node) $Node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $Node.Name -eq $Name}}, $true).Extent.Text
}}
Invoke-Expression (Import-SelectedFunction '{ps_path(UPDATE)}' 'New-PhysicalRestoreZip')
Invoke-Expression (Import-SelectedFunction '{ps_path(RESTORE)}' 'Restore-PhysicalBundles2')

$Game = '{ps_path(game)}'
New-Item -ItemType Directory -Force -Path (Join-Path $Game 'Bundles2/LibGGPK3') | Out-Null
[IO.File]::WriteAllBytes((Join-Path $Game 'PathOfExile.exe'), [byte[]](1,2,3))
[IO.File]::WriteAllBytes((Join-Path $Game 'Bundles2/Tiny.V0.1.bundle.bin'), [byte[]](4,5,6))
$OriginalIndex = New-Object byte[] 1048577; $OriginalIndex[0]=11; $OriginalIndex[-1]=22
[IO.File]::WriteAllBytes((Join-Path $Game 'Bundles2/_.index.bin'), $OriginalIndex)
[IO.File]::WriteAllText((Join-Path $Game 'Bundles2/LibGGPK3/0.bundle.bin'), 'ORIGINAL-LIB')
$global:Poe2Dir=$Game; $global:GameMode='Bundles2'; $global:Bundles2Paths=Get-Bundles2Paths $Game
$global:InstallInfo=[pscustomobject]@{{InstallKind='INT-Steam';TcBaseItemsPath='data/balance/baseitemtypes.datc64'}}
$Zip = Join-Path $Game 'restore.zip'
New-PhysicalRestoreZip -OutputZip $Zip | Out-Null
$OldZipHash = (Get-FileHash $Zip).Hash
$env:POE2_PATCH_TEST_FAIL_PHYSICAL_ZIP='before-replace'
try {{ New-PhysicalRestoreZip -OutputZip $Zip | Out-Null; throw 'expected generation failure' }} catch {{ if ($_.Exception.Message -eq 'expected generation failure') {{ throw }} }}
Remove-Item Env:POE2_PATCH_TEST_FAIL_PHYSICAL_ZIP
if ((Get-FileHash $Zip).Hash -ne $OldZipHash) {{ throw 'old ZIP was replaced after failed generation' }}
Write-Output 'ATOMIC_GENERATION_OK'

$PatchedIndex = New-Object byte[] 1048577; $PatchedIndex[0]=99; $PatchedIndex[-1]=88
[IO.File]::WriteAllBytes((Join-Path $Game 'Bundles2/_.index.bin'), $PatchedIndex)
[IO.File]::WriteAllText((Join-Path $Game 'Bundles2/LibGGPK3/0.bundle.bin'), 'PATCHED-LIB')
$IndexHash = (Get-FileHash (Join-Path $Game 'Bundles2/_.index.bin')).Hash
$LibHash = (Get-FileHash (Join-Path $Game 'Bundles2/LibGGPK3/0.bundle.bin')).Hash
$env:POE2_PATCH_TEST_RESTORE_FAILURE='after-first-file'
try {{ Restore-PhysicalBundles2 -Path $Zip; throw 'expected restore failure' }} catch {{ if ($_.Exception.Message -eq 'expected restore failure') {{ throw }} }}
Remove-Item Env:POE2_PATCH_TEST_RESTORE_FAILURE
if ((Get-FileHash (Join-Path $Game 'Bundles2/_.index.bin')).Hash -ne $IndexHash) {{ throw 'index rollback mismatch' }}
if ((Get-FileHash (Join-Path $Game 'Bundles2/LibGGPK3/0.bundle.bin')).Hash -ne $LibHash) {{ throw 'LibGGPK3 rollback mismatch' }}
Write-Output 'RESTORE_ROLLBACK_OK'

# If another process creates LibGGPK3 after the final preflight but before this
# transaction installs its staged directory, the external directory must survive.
Remove-Item -LiteralPath (Join-Path $Game 'Bundles2/LibGGPK3') -Recurse -Force
$env:POE2_PATCH_TEST_CREATE_CONCURRENT_LIB='1'
try {{ Restore-PhysicalBundles2 -Path $Zip; throw 'expected concurrent Lib failure' }} catch {{ if ($_.Exception.Message -eq 'expected concurrent Lib failure') {{ throw }} }}
Remove-Item Env:POE2_PATCH_TEST_CREATE_CONCURRENT_LIB
$ExternalLib = Join-Path $Game 'Bundles2/LibGGPK3/external.bundle.bin'
if (-not (Test-Path -LiteralPath $ExternalLib -PathType Leaf)) {{ throw 'concurrent LibGGPK3 was deleted' }}
if ((Get-Content -LiteralPath $ExternalLib -Raw) -ne 'EXTERNAL-LIB') {{ throw 'concurrent LibGGPK3 content changed' }}
Write-Output 'CONCURRENT_LIB_PRESERVED'

# A top-level target changed after the rollback snapshot must be detected before
# this transaction overwrites it.  The external content must remain untouched.
$env:POE2_PATCH_TEST_MUTATE_TOP_LEVEL_BEFORE_WRITE='1'
try {{ Restore-PhysicalBundles2 -Path $Zip; throw 'expected concurrent top-level failure' }} catch {{ if ($_.Exception.Message -eq 'expected concurrent top-level failure') {{ throw }} }}
Remove-Item Env:POE2_PATCH_TEST_MUTATE_TOP_LEVEL_BEFORE_WRITE
$ExternalIndex = Join-Path $Game 'Bundles2/_.index.bin'
if ((Get-Content -LiteralPath $ExternalIndex -Raw) -ne 'EXTERNAL-TOP-LEVEL') {{ throw 'concurrent top-level change was overwritten' }}
Write-Output 'CONCURRENT_TOP_LEVEL_PRESERVED'
"""
    output = run_windows_powershell(script)
    assert "ATOMIC_GENERATION_OK" in output
    assert "RESTORE_ROLLBACK_OK" in output
    assert "CONCURRENT_LIB_PRESERVED" in output
    assert "CONCURRENT_TOP_LEVEL_PRESERVED" in output


def test_update_only_refreshes_physical_backup_when_it_will_install():
    update = UPDATE.read_text(encoding="utf-8-sig")
    assert 'if ($GameMode -eq "Bundles2" -and -not $NoInstall -and -not $NoOpenTool)' in update
    physical_block = update[update.index("$PhysicalRestoreZip = Ensure-PhysicalRestoreZip") - 200 :]
    assert "刷新真实还原包失败，将继续更新补丁" not in physical_block[:1000]
    restore = RESTORE.read_text(encoding="utf-8-sig")
    assert "skipping compatibility check against patched game data" not in restore
    assert "Test-BaseItemsCompatible $RestoreEntryTemp $CleanDatForCheck" in restore
    merge_pos = update.index("Merge-ExistingBundlePatchEntries -ZipPath $TempPatchZip")
    revalidate_pos = update.index(
        "Assert-Poe2PhysicalRestoreZip -Path $PhysicalRestoreZip", merge_pos
    )
    patch_pos = update.index("$BundlePatchResult = Invoke-DotNet8", revalidate_pos)
    assert merge_pos < revalidate_pos < patch_pos
