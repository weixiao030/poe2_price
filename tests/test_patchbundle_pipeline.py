import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "物价补丁" / "tools"
UPDATE = TOOLS / "update_price_patch.ps1"
RESTORE = TOOLS / "restore_price_patch.ps1"
COMMON = TOOLS / "poe2_patch_common.ps1"
BUNDLE_EXTRACTOR_SOURCE = ROOT / "build" / "BundleExtractor" / "Program.cs"
BUNDLE_EXTRACTOR_EXE = TOOLS / "BundleExtractor" / "BundleExtractor.exe"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def powershell_function(script: str, name: str, next_name: str) -> str:
    start = script.index(f"function {name}")
    end = script.index(f"function {next_name}", start)
    return script[start:end]


def test_bundle_extractor_has_single_load_batch_mode():
    source = read(BUNDLE_EXTRACTOR_SOURCE)
    assert 'args[0].Equals("--extract-list"' in source
    batch = source[source.index("static int ExtractFiles"):]
    assert "LoadIndex(indexPath, parsePaths: false)" in batch
    assert "TryGetFile(filePath" in batch


def test_published_bundle_extractor_exposes_batch_mode():
    result = subprocess.run(
        [str(BUNDLE_EXTRACTOR_EXE)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=15,
    )
    assert result.returncode == 1
    assert "--extract-list" in result.stdout


def test_update_preserves_existing_entries_with_one_batch_extract():
    script = read(UPDATE)
    merge = powershell_function(
        script,
        "Merge-ExistingBundlePatchEntries",
        "Assert-Bundles2PatchApplied",
    )
    assert merge.count("--extract-list") == 1
    assert "--extract-list $Bundles2Paths.IndexBin $RequestListPath $ExtractDir" in merge
    assert "$BundledBundleExtractorExe $Bundles2Paths.IndexBin $EntryName" not in merge
    assert "Test-ZipEntryExists" not in merge
    assert "Update-ZipEntryFromFile" not in merge
    assert "$ExistingZipEntries" in merge
    assert "CreateEntryFromFile" in merge
    assert "为避免覆盖并丢失其它补丁，本次已中止" in merge
    assert "MissingExtractedEntries" in merge


def test_patchbundle_calls_close_stdin_and_update_verifies_hashes():
    update = read(UPDATE)
    restore = read(RESTORE)
    expected_input = '-InputText "" -Quiet'
    assert expected_input in update
    assert expected_input in restore
    assert "Assert-Bundles2PatchApplied -ZipPath $TempPatchZip" in update
    verify = powershell_function(
        update,
        "Assert-Bundles2PatchApplied",
        "Update-RestoreZipEntry",
    )
    assert "--extract-list" in verify
    assert "SHA256" in verify
    assert "Content mismatch" in verify


def test_bundles2_write_preflight_checks_game_and_exclusive_index_access():
    common = read(COMMON)
    update = read(UPDATE)
    preflight = powershell_function(
        common,
        "Assert-Poe2GameFilesAvailable",
        "Test-Poe2ReleaseMode",
    )
    assert 'ProcessName -like "PathOfExile*"' in preflight
    assert "[System.IO.FileAccess]::ReadWrite" in preflight
    assert "[System.IO.FileShare]::None" in preflight
    assert update.count("Assert-Poe2GameFilesAvailable -Poe2Dir $Poe2Dir") >= 4
    assert '$GameMode -eq "Bundles2" -and -not $NoInstall -and -not $NoOpenTool' in update
