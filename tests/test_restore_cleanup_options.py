"""Exercise the real restore callers' arguments through the offline builder."""
import json
from pathlib import Path
import shutil
import urllib.request
import zipfile

import pytest

from tests.test_patched_restore_migration import ps_path, run_windows_powershell
from tests.test_tablet_affixes import synthetic_baseitems, names, refs, m as affixes
from tests.test_whole_tablets import words_fixture
import build_poe2scout_price_patch as builder


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "物价补丁" / "tools"
TARGET = "data/balance/simplified chinese/baseitemtypes.datc64"
WORDS_TARGET = "data/balance/simplified chinese/words.datc64"
CALLERS = [
    ("update_price_patch.ps1", "New-CleanPhysicalRestoreZipFromPatchedSources"),
    ("update_price_patch.ps1", "New-CleanLogicalRestoreZipFromPatchedSources"),
    ("restore_price_patch.ps1", "New-Poe2RestoreBaselineFromCurrentGame"),
]


def restore_arguments(script_path, function_name, fixture_dir):
    """Evaluate only production argument-array assignments, never game writes."""
    script = rf"""
$ErrorActionPreference = 'Stop'
$Tokens = $null
$ParseErrors = $null
$Ast = [System.Management.Automation.Language.Parser]::ParseFile(
    '{ps_path(script_path)}', [ref]$Tokens, [ref]$ParseErrors)
if ($ParseErrors.Count) {{ throw ($ParseErrors | Out-String) }}
$Function = $Ast.Find({{
    param($Node)
    $Node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $Node.Name -eq '{function_name}'
}}, $true)
if ($null -eq $Function) {{ throw 'Production cleanup function missing' }}
$Assignments = @($Function.Body.FindAll({{
    param($Node)
    $Node -is [System.Management.Automation.Language.AssignmentStatementAst] -and
        $Node.Left -is [System.Management.Automation.Language.VariableExpressionAst] -and
        $Node.Left.VariablePath.UserPath -in @('Args', 'CleanupArgs')
}}, $true) | Sort-Object {{ $_.Extent.StartOffset }})
if ($Assignments.Count -ne 2) {{ throw 'Expected initial cleanup arguments plus Words arguments' }}
$CodeToolsRoot = '{ps_path(TOOLS)}'
$FixtureDir = '{ps_path(fixture_dir)}'
$EnBaseItems = Join-Path $FixtureDir 'english.datc64'
$TcBaseItems = Join-Path $FixtureDir 'source.datc64'
$SourceDatForLogicalMigration = $TcBaseItems
$CurrentBaseItems = $TcBaseItems
$TcWords = Join-Path $FixtureDir 'words.datc64'
$CurrentWords = $TcWords
$TempRoot = Join-Path $FixtureDir 'output'
$CleanupOutDir = $TempRoot
$CleanPatchZip = Join-Path $TempRoot 'clean.zip'
$CleanZip = $CleanPatchZip
$CleanBaseItems = Join-Path $TempRoot 'baseitems.clean.datc64'
$CleanWords = Join-Path $TempRoot 'words.clean.datc64'
$CleanupReport = Join-Path $TempRoot 'cleanup.report.json'
$InstallInfo = [pscustomobject]@{{ TcBaseItemsPath = '{TARGET}' }}
$TcWordsPath = '{WORDS_TARGET}'
$ArgumentVariable = $Assignments[0].Left.VariablePath.UserPath
$Evaluation = ($Assignments | ForEach-Object {{ $_.Extent.Text }}) -join "`n"
$Evaluation += "`n[string[]]`$$ArgumentVariable"
$Captured = [string[]](& ([scriptblock]::Create($Evaluation)))
ConvertTo-Json -InputObject $Captured -Compress
"""
    captured = json.loads(run_windows_powershell(script))
    assert Path(captured[0]) == TOOLS / "build_poe2scout_price_patch.py"
    return captured[1:]


def make_patched_baseitems(english=False):
    original = synthetic_baseitems(english)
    patched = original
    if not english:
        entries = names.scan_base_item_names(original)
        replacements, warnings = names.build_replacements(
            entries,
            [{"metadata_path": entries[-1].metadata_path, "price": "5E"}],
            "=", True, "append", False,
        )
        assert warnings == []
        patched = names.apply_replacements_append(original, replacements)
    patched, _ = affixes._redirect_tablet_base_items(patched, {"Ritual"})
    if not english:
        patched, _ = affixes.price_tablet_names(
            patched, {"Ritual_Tablet": {"price": "8D"}}
        )
    return original, patched


@pytest.mark.skipif(shutil.which("powershell.exe") is None, reason="Windows PowerShell required")
@pytest.mark.parametrize("script_name,function_name", CALLERS, ids=[item[1] for item in CALLERS])
def test_restore_cleanup_never_fetches_or_reintroduces_prices(
    tmp_path, monkeypatch, script_name, function_name
):
    original, patched = make_patched_baseitems()
    _, english = make_patched_baseitems(english=True)
    source = tmp_path / "source.datc64"
    source.write_bytes(patched)
    (tmp_path / "english.datc64").write_bytes(english)
    words = tmp_path / "words.datc64"
    words_fixture(words, "[9D|字体补丁译名]")
    original_words = words.read_bytes()
    arguments = restore_arguments(TOOLS / script_name, function_name, tmp_path)
    requests = []

    class NetworkDuringCleanup(BaseException):
        # Market fallback handlers must not swallow a forbidden network attempt.
        pass

    class OfflineClient:
        def __init__(self, **kwargs):
            pass

        def get_json(self, url, *args, **kwargs):
            requests.append(url)
            raise NetworkDuringCleanup(url)

        get_text = get_json

        def request_metrics(self):
            return []

    def deny_direct_request(*args, **kwargs):
        requests.append(str(args) + str(kwargs))
        raise NetworkDuringCleanup(requests[-1])

    monkeypatch.setattr(builder, "RetryingRequests", OfflineClient)
    monkeypatch.setattr(urllib.request, "urlopen", deny_direct_request)
    try:
        result = builder.main(arguments)
    finally:
        assert requests == [], f"Restore cleanup attempted network access: {requests}"
    assert result == 0

    out = tmp_path / "output"
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summary["patch_scope"] == "none"
    assert summary["tablet_prices_enabled"] is False
    assert summary["tablet_affix_prices_enabled"] is False
    assert summary["tablet_affixes"]["status"] == "disabled"
    assert summary["whole_tablets"]["status"] == "disabled"
    assert summary["tablet_market"]["status"] == "disabled"
    assert summary["unique_words_patched"] == 0
    assert summary["matched_items"] == 0
    assert summary["http_request_count"] == 0

    clean = (out / "baseitems.clean.datc64").read_bytes()
    expected_names = [(item.metadata_path, item.name) for item in names.scan_base_item_names(original)]
    assert [(item.metadata_path, item.name) for item in names.scan_base_item_names(clean)] == expected_names
    assert refs.clean_tablet_layer(clean) == clean
    assert names.build_structure_signature(clean) == names.build_structure_signature(original)
    clean_words_path = out / "words.clean.datc64"
    clean_words = clean_words_path.read_bytes()
    word_layout = builder.detect_words_layout(clean_words)
    assert builder.read_words_row(clean_words, word_layout, 0).display_name == "字体补丁译名"
    assert not builder.words_look_price_patched(clean_words_path)
    assert builder.detect_words_layout(original_words) == word_layout
    pointer = 4 + builder.WORDS_DISPLAY_NAME_OFFSET
    assert clean_words[:pointer] == original_words[:pointer]
    assert clean_words[pointer + 4:word_layout.string_base] == original_words[pointer + 4:word_layout.string_base]

    with zipfile.ZipFile(out / "clean.zip") as archive:
        assert archive.read(TARGET) == clean
        assert archive.read(WORDS_TARGET) == clean_words
        assert not any("/poe2price/" in path.lower() for path in archive.namelist())
        if refs.ENGLISH_BASEITEMS in archive.namelist():
            assert refs.clean_tablet_layer(archive.read(refs.ENGLISH_BASEITEMS)) == archive.read(refs.ENGLISH_BASEITEMS)
    assert source.read_bytes() == patched
    assert words.read_bytes() == original_words
