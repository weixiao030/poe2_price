import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMMON = ROOT / "物价补丁" / "tools" / "poe2_patch_common.ps1"
PAYLOAD_COMMON = ROOT / "build" / "payload" / "poe2_patch_common.ps1"
UPDATE = ROOT / "物价补丁" / "tools" / "update_price_patch.ps1"
PAYLOAD_UPDATE = ROOT / "build" / "payload" / "update_price_patch.ps1"


def ps_quote(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def run_powershell(script: str) -> str:
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
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip()


def test_manual_selection_accepts_game_root_and_bundles2_child(tmp_path: Path):
    game = tmp_path / "manual game"
    bundles = game / "Bundles2"
    bundles.mkdir(parents=True)
    (bundles / "_.index.bin").write_bytes(b"index")

    output = run_powershell(
        f". {ps_quote(COMMON)}; "
        f"$root = Resolve-Poe2GameDirectorySelection -Mode manual -ManualPath {ps_quote(game)}; "
        f"$child = Resolve-Poe2GameDirectorySelection -Mode manual -ManualPath {ps_quote(bundles)}; "
        'Write-Output "$root`n$child"'
    )

    expected = str(game.resolve())
    assert output.splitlines() == [expected, expected]


def test_auto_selection_prefers_patch_parent(tmp_path: Path):
    preferred = tmp_path / "preferred"
    fallback = tmp_path / "fallback"
    (preferred / "Bundles2").mkdir(parents=True)
    fallback.mkdir()
    (preferred / "Bundles2" / "_.index.bin").write_bytes(b"index")
    (fallback / "Content.ggpk").write_bytes(b"ggpk")

    output = run_powershell(
        f". {ps_quote(COMMON)}; "
        "$selected = Resolve-Poe2GameDirectorySelection "
        f"-Mode auto -PreferredRoot {ps_quote(preferred)} "
        f"-AdditionalPaths @({ps_quote(fallback)}); "
        "Write-Output $selected"
    )

    assert output == str(preferred.resolve())


def test_gui_exposes_auto_and_manual_directory_modes():
    update = UPDATE.read_text(encoding="utf-8-sig")
    for expected in (
        "System.Windows.Forms.FolderBrowserDialog",
        "自动识别游戏文件夹",
        "手动选择游戏文件夹",
        'Resolve-Poe2GameDirectorySelection -Mode "auto"',
        'Resolve-Poe2GameDirectorySelection -Mode "manual"',
    ):
        assert expected in update


def test_gui_controls_construct_without_opening_window(tmp_path: Path):
    game = tmp_path / "gui game"
    (game / "Bundles2").mkdir(parents=True)
    (game / "Bundles2" / "_.index.bin").write_bytes(b"index")

    output = run_powershell(
        f". {ps_quote(COMMON)}; "
        "$tokens = $null; $errors = $null; "
        f"$ast = [System.Management.Automation.Language.Parser]::ParseFile({ps_quote(UPDATE)}, [ref]$tokens, [ref]$errors); "
        'foreach ($name in @("New-Utf16Text", "Show-PatchScopeDialog")) { '
        "$definition = $ast.FindAll({ param($node) "
        "$node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name }, $true) | "
        "Select-Object -First 1; "
        "$text = $definition.Extent.Text; "
        'if ($name -eq "Show-PatchScopeDialog") { '
        "$text = $text.Replace('$Result = $Form.ShowDialog()', "
        "'$Result = [System.Windows.Forms.DialogResult]::Cancel') }; "
        ". ([scriptblock]::Create($text)) }; "
        '$script:PatchWindowTitle = "GUI smoke test"; $Poe2DirWasExplicit = $false; '
        f"try {{ Show-PatchScopeDialog -PreferredPoe2Dir {ps_quote(game)}; throw 'dialog did not cancel' }} "
        'catch { if ($_.Exception.Message -ne "Patch scope selection was cancelled.") { throw } }; '
        'Write-Output "GUI_OK"'
    )

    assert output == "GUI_OK"


def test_release_payload_copies_stay_in_sync():
    assert COMMON.read_bytes() == PAYLOAD_COMMON.read_bytes()
    assert UPDATE.read_bytes() == PAYLOAD_UPDATE.read_bytes()
