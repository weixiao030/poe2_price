import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "物价补丁" / "tools"
COMMON = TOOLS / "poe2_patch_common.ps1"
UPDATE = TOOLS / "update_price_patch.ps1"
RESTORE = TOOLS / "restore_price_patch.ps1"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def ps_path(path: Path) -> str:
    return str(path).replace("'", "''")


def run_windows_powershell(script: str, timeout: int = 120) -> str:
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
        timeout=timeout,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def powershell_function(script: str, name: str) -> str:
    """Return one top-level function without depending on the next function's name."""
    match = re.search(rf"(?m)^function\s+{re.escape(name)}\b", script)
    assert match is not None, f"missing PowerShell function: {name}"
    next_match = re.search(r"(?m)^function\s+[\w-]+\b", script[match.end() :])
    if next_match is None:
        return script[match.start() :]
    return script[match.start() : match.end() + next_match.start()]


def test_patch_state_probe_failure_is_not_reported_as_patched(tmp_path: Path):
    """A broken detector is an unknown state, not proof that the file is patched."""
    source = tmp_path / "probe.datc64"
    source.write_bytes(b"probe")
    script = rf"""
$ErrorActionPreference = 'Stop'
function Import-SelectedFunction([string]$Path, [string]$Name) {{
    $Tokens=$null; $Errors=$null
    $Ast=[System.Management.Automation.Language.Parser]::ParseFile($Path,[ref]$Tokens,[ref]$Errors)
    if ($Errors.Count) {{ throw $Errors[0] }}
    $Function=$Ast.Find({{param($Node) $Node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $Node.Name -eq $Name}}, $true)
    if ($null -eq $Function) {{ throw "missing function: $Name" }}
    return $Function.Extent.Text
}}
function Ensure-PythonRequests {{ return 'mock-python.exe' }}
function Invoke-Poe2Python {{
    return [pscustomobject]@{{ExitCode=17; Text='forced detector failure'}}
}}
function Assert-ProbeFailure([string]$ScriptPath, [string]$FunctionName, [string]$SourcePath) {{
    Invoke-Expression (Import-SelectedFunction $ScriptPath $FunctionName)
    try {{
        $Returned = & $FunctionName $SourcePath
        throw "PROBE_RETURNED_NORMALLY:$Returned"
    }}
    catch {{
        $Message = $_.Exception.Message
        if ($Message -like 'PROBE_RETURNED_NORMALLY:*') {{ throw $Message }}
        if ($Message -notmatch '无法判断|检测失败') {{
            throw "检测工具失败时没有抛出明确的无法判断/检测失败错误：$Message"
        }}
    }}
}}
$RepoRoot = '{ps_path(ROOT)}'
$CodeToolsRoot = '{ps_path(TOOLS)}'
$InstallInfo = [pscustomobject]@{{TcEndgameMapsPath='data/test/endgamemaps.datc64'}}
$SourcePath = '{ps_path(source)}'
foreach ($ScriptPath in @('{ps_path(UPDATE)}', '{ps_path(RESTORE)}')) {{
    Assert-ProbeFailure $ScriptPath 'Test-BaseItemsLookPatched' $SourcePath
    Assert-ProbeFailure $ScriptPath 'Test-EndgameMapsLookPatched' $SourcePath
}}
Write-Output 'PROBE_FAILURES_ARE_UNKNOWN'
"""
    output = run_windows_powershell(script)
    assert "PROBE_FAILURES_ARE_UNKNOWN" in output


def test_physical_restore_candidates_include_game_persistent_store(tmp_path: Path):
    """The rollback package must survive replacement or deletion of the patch folder."""
    game = tmp_path / "game"
    repo_copy = game / "replaceable-patch-folder"
    restore_output = repo_copy / "output" / "restore"
    script = rf"""
$ErrorActionPreference = 'Stop'
. '{ps_path(COMMON)}'
function Import-SelectedFunction([string]$Path, [string]$Name) {{
    $Tokens=$null; $Errors=$null
    $Ast=[System.Management.Automation.Language.Parser]::ParseFile($Path,[ref]$Tokens,[ref]$Errors)
    if ($Errors.Count) {{ throw $Errors[0] }}
    $Function=$Ast.Find({{param($Node) $Node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $Node.Name -eq $Name}}, $true)
    if ($null -eq $Function) {{ throw "missing function: $Name" }}
    return $Function.Extent.Text
}}
$Poe2Dir = '{ps_path(game)}'
$RepoRoot = '{ps_path(repo_copy)}'
$RestoreOutDir = '{ps_path(restore_output)}'
$InstallInfo = [pscustomobject]@{{IsChina=$false; InstallKind='INT-Steam'}}
$ExpectedRoot = [IO.Path]::GetFullPath((Join-Path $Poe2Dir '.poe2-price-patch'))
$ExpectedName = Get-Poe2FixedPhysicalRestorePatchZipName -InstallInfo $InstallInfo
foreach ($ScriptPath in @('{ps_path(UPDATE)}', '{ps_path(RESTORE)}')) {{
    Invoke-Expression (Import-SelectedFunction $ScriptPath 'Get-PhysicalRestoreZipCandidates')
    $Candidates = @(Get-PhysicalRestoreZipCandidates)
    $PersistentCandidate = $Candidates | Where-Object {{
        [IO.Path]::GetFullPath((Split-Path -Parent $_)) -eq $ExpectedRoot -and
        (Split-Path -Leaf $_) -eq $ExpectedName
    }} | Select-Object -First 1
        if ([string]::IsNullOrWhiteSpace([string]$PersistentCandidate)) {{
            throw "PERSISTENT_STORE_MISSING:$ExpectedRoot"
        }}
}}
Write-Output 'PERSISTENT_STORE_COVERED_BY_BOTH_SCRIPTS'
"""
    output = run_windows_powershell(script)
    assert "PERSISTENT_STORE_COVERED_BY_BOTH_SCRIPTS" in output


def test_physical_restore_is_published_to_patch_folder_and_persistent_store(
    tmp_path: Path,
):
    patch_copy = tmp_path / "patch" / "真实还原物价补丁.zip"
    persistent_copy = tmp_path / "game" / ".poe2-price-patch" / "真实还原物价补丁.zip"
    script = rf"""
$ErrorActionPreference = 'Stop'
function Import-SelectedFunction([string]$Path, [string]$Name) {{
    $Tokens=$null; $Errors=$null
    $Ast=[System.Management.Automation.Language.Parser]::ParseFile($Path,[ref]$Tokens,[ref]$Errors)
    if ($Errors.Count) {{ throw $Errors[0] }}
    $Function=$Ast.Find({{param($Node) $Node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $Node.Name -eq $Name}}, $true)
    return $Function.Extent.Text
}}
$script:Destinations = New-Object System.Collections.Generic.List[string]
function Copy-PhysicalRestoreZipAtomically([string]$Source, [string]$Destination) {{
    $script:Destinations.Add([IO.Path]::GetFullPath($Destination))
    return [IO.Path]::GetFullPath($Destination)
}}
$PhysicalRestorePatchFolderZip = '{ps_path(patch_copy)}'
$PersistentPhysicalRestoreZip = '{ps_path(persistent_copy)}'
Invoke-Expression (Import-SelectedFunction '{ps_path(UPDATE)}' 'Publish-PhysicalRestoreZip')
$Result = Publish-PhysicalRestoreZip -Source 'source.zip'
$Expected = @(
    [IO.Path]::GetFullPath($PhysicalRestorePatchFolderZip),
    [IO.Path]::GetFullPath($PersistentPhysicalRestoreZip)
)
foreach ($Path in $Expected) {{
    if (-not $script:Destinations.Contains($Path)) {{ throw "MISSING_PUBLISH_DESTINATION:$Path" }}
}}
if ([IO.Path]::GetFullPath($Result) -ne $Expected[0]) {{ throw "UNEXPECTED_PUBLISH_RESULT:$Result" }}
Write-Output 'PHYSICAL_RESTORE_PUBLISHED_DURABLY'
"""
    output = run_windows_powershell(script)
    assert "PHYSICAL_RESTORE_PUBLISHED_DURABLY" in output


def test_patched_source_without_backup_executes_offline_migration(tmp_path: Path):
    migrated_zip = tmp_path / "migrated-physical-restore.zip"
    migrated_zip.write_bytes(b"migration-result")
    script = rf"""
$ErrorActionPreference = 'Stop'
function Import-SelectedFunction([string]$Path, [string]$Name) {{
    $Tokens=$null; $Errors=$null
    $Ast=[System.Management.Automation.Language.Parser]::ParseFile($Path,[ref]$Tokens,[ref]$Errors)
    if ($Errors.Count) {{ throw $Errors[0] }}
    $Function=$Ast.Find({{param($Node) $Node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $Node.Name -eq $Name}}, $true)
    if ($null -eq $Function) {{ throw "missing function: $Name" }}
    return $Function.Extent.Text
}}
$script:MigrationCalls = 0
$MigratedZip = '{ps_path(migrated_zip)}'
function Get-PhysicalRestoreZipCandidates {{ return @() }}
function Test-PhysicalRestoreZipUsable {{ return $true }}
function Copy-PhysicalRestoreZipAtomically {{ return $MigratedZip }}
function Publish-PhysicalRestoreZip {{ return $MigratedZip }}
function New-PhysicalRestoreZip {{ throw 'clean-source backup path must not run' }}
function New-CleanPhysicalRestoreZipFromPatchedSources {{
    $script:MigrationCalls++
    return $MigratedZip
}}
$GameMode = 'Bundles2'
$PhysicalRestoreOutZip = 'unused-output.zip'
$PhysicalRestorePatchFolderZip = 'unused-patch-folder.zip'
$script:LastPhysicalRestoreZipError = ''
Invoke-Expression (Import-SelectedFunction '{ps_path(UPDATE)}' 'Ensure-PhysicalRestoreZip')
$Result = Ensure-PhysicalRestoreZip -SourceLooksPatched $true
if ($script:MigrationCalls -ne 1) {{
    throw "MIGRATION_CALL_COUNT:$($script:MigrationCalls)"
}}
if ([IO.Path]::GetFullPath([string]$Result) -ne [IO.Path]::GetFullPath($MigratedZip)) {{
    throw "MIGRATION_RESULT_NOT_RETURNED:$Result"
}}
Write-Output 'PATCHED_WITHOUT_BACKUP_MIGRATES'
"""
    output = run_windows_powershell(script)
    assert "PATCHED_WITHOUT_BACKUP_MIGRATES" in output


def test_patched_source_has_offline_physical_restore_migration_before_game_write():
    update = read(UPDATE)
    migration_name = "New-CleanPhysicalRestoreZipFromPatchedSources"
    migration = powershell_function(update, migration_name)
    ensure = powershell_function(update, "Ensure-PhysicalRestoreZip")

    # The no-backup branch must migrate instead of stopping at the candidate search.
    candidate_search = ensure.index("Get-PhysicalRestoreZipCandidates")
    migration_call = ensure.index(migration_name)
    assert candidate_search < migration_call

    # Migration is entirely offline: clean a price layer, apply it to a sandbox,
    # then package that sandbox as a version-2 physical restore archive.
    migration_body = migration[migration.index("{") + 1 :]
    assert re.search(r"(?i)clean|清理", migration_body) is not None
    sandbox = re.search(r"(?i)sandbox|沙盒", migration_body)
    patch_bundle = migration.find("PatchBundle3")
    physical_zip = migration.find("New-PhysicalRestoreZip")
    assert sandbox is not None
    assert 0 <= patch_bundle < physical_zip

    physical_zip_builder = powershell_function(update, "New-PhysicalRestoreZip")
    assert re.search(r"(?i)version\s*=\s*2", physical_zip_builder) is not None
    assert "Assert-Poe2PhysicalRestoreZip" in physical_zip_builder

    # The real Bundles2 write remains downstream of a verified rollback archive.
    ensure_call = update.index("$PhysicalRestoreZip = Ensure-PhysicalRestoreZip")
    backup_validation = update.index(
        "Assert-Poe2PhysicalRestoreZip -Path $PhysicalRestoreZip", ensure_call
    )
    game_write = update.index("$BundlePatchResult = Invoke-DotNet8", backup_validation)
    game_write_exe = update.index(
        "& $BundledBundlePatchExe $Bundles2Paths.IndexBin", backup_validation
    )
    assert ensure_call < backup_validation < game_write
    assert backup_validation < game_write_exe


def test_legacy_restore_cleans_missing_endgamemaps_and_validates_words():
    restore = read(RESTORE)
    augment = powershell_function(restore, "Add-CleanCurrentEndgameMapsToRestoreZip")
    assert "$BundledBundleExtractorExe" in augment
    assert '"clean"' in augment
    assert "Test-EndgameMapsLookPatched" in augment
    assert "Test-ZipEntryExists" in augment

    build_install_zip = restore.index("$InstallRestoreZip = New-CurrentTargetRestoreZip")
    augment_call = restore.index(
        "$InstallRestoreZip = Add-CleanCurrentEndgameMapsToRestoreZip",
        build_install_zip,
    )
    patch_bundle_write = restore.index("$BundlePatchResult = Invoke-DotNet8", augment_call)
    assert build_install_zip < augment_call < patch_bundle_write

    assert "Test-WordsLookPatched $TempWords" in restore
    assert "Restore zip Words contains active price markers" in restore
