import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMMON = ROOT / "物价补丁" / "tools" / "poe2_patch_common.ps1"
PAYLOAD_COMMON = ROOT / "build" / "payload" / "poe2_patch_common.ps1"
UPDATE = ROOT / "物价补丁" / "tools" / "update_price_patch.ps1"
PAYLOAD_UPDATE = ROOT / "build" / "payload" / "update_price_patch.ps1"
RESTORE = ROOT / "物价补丁" / "tools" / "restore_price_patch.ps1"
PAYLOAD_RESTORE = ROOT / "build" / "payload" / "restore_price_patch.ps1"
GUI = ROOT / "物价补丁" / "tools" / "price_patch_gui.ps1"
PAYLOAD_GUI = ROOT / "build" / "payload" / "price_patch_gui.ps1"
LAUNCHER = ROOT / "build" / "Poe2PatchLauncher" / "Program.cs"


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
        encoding="utf-8",
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


def test_wegame_library_discovers_china_release_name(tmp_path: Path):
    library = tmp_path / "WeGameApps" / "rail_apps"
    game = library / "流放之路：降临"
    (game / "Bundles2").mkdir(parents=True)
    (game / "Bundles2" / "_.index.bin").write_bytes(b"index")
    (game / "wegame.ini").write_text("wegame", encoding="utf-8")
    (game / "rail_api64.dll").write_bytes(b"rail")

    output = run_powershell(
        f". {ps_quote(COMMON)}; "
        "$selected = Resolve-Poe2GameDirectorySelection "
        f"-Mode auto -AdditionalWeGameRoots @({ps_quote(library)}) "
        "-IgnoreSavedDirectory -SkipSystemGameDiscovery; "
        "$info = Get-Poe2InstallInfo -Poe2Dir $selected; "
        'Write-Output "$selected`n$($info.InstallKind)`n$($info.DisplayName)"'
    )

    assert output.splitlines() == [
        str(game.resolve()),
        "CN-WeGame-Bundles2",
        "国服 WeGame Bundles2",
    ]


def test_auto_selection_rejects_ambiguous_discovered_clients(tmp_path: Path):
    library = tmp_path / "WeGameApps" / "rail_apps"
    for name in ("流放之路：降临", "Path of Exile 2"):
        game = library / name
        (game / "Bundles2").mkdir(parents=True)
        (game / "Bundles2" / "_.index.bin").write_bytes(b"index")

    output = run_powershell(
        f". {ps_quote(COMMON)}; "
        "try { Resolve-Poe2GameDirectorySelection "
        f"-Mode auto -AdditionalWeGameRoots @({ps_quote(library)}) "
        "-IgnoreSavedDirectory -SkipSystemGameDiscovery; "
        "throw 'expected ambiguity' } "
        "catch { if ($_.Exception.Message -eq 'expected ambiguity') { throw }; "
        'Write-Output $_.Exception.Message }'
    )

    assert "自动识别到多个 POE2 客户端" in output
    assert "手动选择" in output


def test_saved_directory_round_trip_and_stale_path_is_ignored(tmp_path: Path):
    game = tmp_path / "saved game"
    settings = tmp_path / "state" / "settings.json"
    (game / "Bundles2").mkdir(parents=True)
    (game / "Bundles2" / "_.index.bin").write_bytes(b"index")

    output = run_powershell(
        f". {ps_quote(COMMON)}; "
        f"Save-Poe2GameDirectory -Poe2Dir {ps_quote(game)} -SettingsPath {ps_quote(settings)} | Out-Null; "
        f"$saved = Get-Poe2SavedGameDirectory -SettingsPath {ps_quote(settings)}; "
        f"Remove-Item -LiteralPath {ps_quote(game / 'Bundles2' / '_.index.bin')} -Force; "
        f"$stale = Get-Poe2SavedGameDirectory -SettingsPath {ps_quote(settings)}; "
        'Write-Output "$saved`n$([string]::IsNullOrWhiteSpace($stale))"'
    )

    assert output.splitlines() == [str(game.resolve()), "True"]


def test_environment_directory_overrides_saved_auto_choice(tmp_path: Path):
    saved_game = tmp_path / "saved game"
    env_game = tmp_path / "environment game"
    settings = tmp_path / "state" / "settings.json"
    for game in (saved_game, env_game):
        (game / "Bundles2").mkdir(parents=True)
        (game / "Bundles2" / "_.index.bin").write_bytes(b"index")

    output = run_powershell(
        f". {ps_quote(COMMON)}; "
        f"Save-Poe2GameDirectory -Poe2Dir {ps_quote(saved_game)} -SettingsPath {ps_quote(settings)} | Out-Null; "
        "$previous = $env:POE2_GAME_DIR; "
        f"try {{ $env:POE2_GAME_DIR = {ps_quote(env_game)}; "
        "$selected = Resolve-Poe2GameDirectorySelection -Mode auto "
        f"-SettingsPath {ps_quote(settings)} -SkipSystemGameDiscovery; Write-Output $selected }} "
        "finally { if ([string]::IsNullOrWhiteSpace($previous)) { Remove-Item Env:POE2_GAME_DIR -ErrorAction SilentlyContinue } "
        "else { $env:POE2_GAME_DIR = $previous } }"
    )

    assert output == str(env_game.resolve())


def test_poe2_official_registry_install_location_is_discovered(tmp_path: Path):
    game = tmp_path / "Path of Exile 2"
    game.mkdir()
    (game / "Content.ggpk").write_bytes(b"ggpk")
    normalized_game = str(game.resolve()).rstrip("\\")

    output = run_powershell(
        f". {ps_quote(COMMON)}; "
        "function global:Get-ItemProperty { "
        "param([string]$LiteralPath, [string]$Path, [object]$ErrorAction); "
        "$key = if (-not [string]::IsNullOrWhiteSpace($LiteralPath)) { $LiteralPath } else { $Path }; "
        "if ($key -eq 'HKCU:\\Software\\GrindingGearGames\\Path of Exile 2') { "
        f"return [pscustomobject]@{{ InstallLocation = {ps_quote(game)} }} "
        "} }; "
        f"$candidate = @(Get-Poe2GameDirectoryCandidates -IgnoreSavedDirectory | Where-Object {{ $_.Path.TrimEnd('\\') -eq {ps_quote(normalized_game)} }}); "
        "if ($candidate.Count -ne 1) { throw 'official registry candidate missing' }; "
        'Write-Output "$($candidate[0].Source)`n$($candidate[0].Mode)`n$($candidate[0].Priority)"'
    )

    assert output.splitlines() == ["GGG 官服注册表", "GGPK", "15"]


def test_saved_and_registry_paths_with_trailing_separator_are_deduplicated(
    tmp_path: Path,
):
    game = tmp_path / "Path of Exile 2"
    settings = tmp_path / "state" / "settings.json"
    game.mkdir()
    (game / "Content.ggpk").write_bytes(b"ggpk")
    normalized_game = str(game.resolve()).rstrip("\\")
    registry_game = normalized_game + "\\"

    output = run_powershell(
        f". {ps_quote(COMMON)}; "
        f"Save-Poe2GameDirectory -Poe2Dir {ps_quote(game)} -SettingsPath {ps_quote(settings)} | Out-Null; "
        "function global:Get-ItemProperty { "
        "param([string]$LiteralPath, [string]$Path, [object]$ErrorAction); "
        "$key = if (-not [string]::IsNullOrWhiteSpace($LiteralPath)) { $LiteralPath } else { $Path }; "
        "if ($key -eq 'HKCU:\\Software\\GrindingGearGames\\Path of Exile 2') { "
        f"return [pscustomobject]@{{ InstallLocation = {ps_quote(registry_game)} }} "
        "} }; "
        f"$candidate = @(Get-Poe2GameDirectoryCandidates -SettingsPath {ps_quote(settings)} | Where-Object {{ $_.Path.TrimEnd('\\') -eq {ps_quote(normalized_game)} }}); "
        "if ($candidate.Count -ne 1) { throw 'duplicate official registry candidate' }; "
        'Write-Output "$($candidate[0].Source)`n$($candidate[0].Priority)"'
    )

    assert output.splitlines() == ["最近使用的游戏目录", "8"]


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


def test_restore_uses_the_shared_directory_selector_and_game_mutex():
    restore = RESTORE.read_text(encoding="utf-8-sig")
    assert "Show-Poe2GameDirectorySelectionDialog" in restore
    assert "Save-Poe2GameDirectory -Poe2Dir $Poe2Dir" in restore
    assert "Enter-Poe2GameDirectoryMutex -Poe2Dir $Poe2Dir" in restore
    assert "[switch]$SkipGameDirectoryMutex" in restore
    assert "$Poe2Dir = (Split-Path -Parent $RepoRoot)" not in restore


def test_launcher_and_scripts_use_game_scoped_concurrency_guards():
    common = COMMON.read_text(encoding="utf-8-sig")
    update = UPDATE.read_text(encoding="utf-8-sig")
    launcher = LAUNCHER.read_text(encoding="utf-8-sig")

    assert '"Local\\Poe2PricePatch-Game-"' in common
    assert "Poe2PricePatch-Launcher-Game-" in launcher
    assert "Poe2PricePatch-Game-" not in launcher
    assert "TryReadSavedGameDirectory" in launcher
    assert '"Poe2PricePatch", "settings.json"' in launcher
    assert "IsPoe2GameDirectory(patchParent)" in launcher
    assert "-SkipGameDirectoryMutex" in update


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


def test_gui_optional_directory_check_accepts_empty_and_invalid_paths(tmp_path: Path):
    existing = tmp_path / "existing"
    existing.mkdir()
    missing = tmp_path / "missing"

    output = run_powershell(
        "$tokens = $null; $errors = $null; "
        f"$ast = [System.Management.Automation.Language.Parser]::ParseFile({ps_quote(GUI)}, [ref]$tokens, [ref]$errors); "
        "$definition = $ast.FindAll({ param($node) "
        "$node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and "
        "$node.Name -eq 'Test-PoePatchExistingDirectory' }, $true) | Select-Object -First 1; "
        "if ($null -eq $definition) { throw 'missing optional directory guard' }; "
        ". ([scriptblock]::Create($definition.Extent.Text)); "
        "$results = @("
        "(Test-PoePatchExistingDirectory -Path $null), "
        "(Test-PoePatchExistingDirectory -Path ''), "
        "(Test-PoePatchExistingDirectory -Path '   '), "
        f"(Test-PoePatchExistingDirectory -Path {ps_quote(missing)}), "
        f"(Test-PoePatchExistingDirectory -Path {ps_quote(existing)})"
        "); Write-Output ($results -join ',')"
    )

    assert output == "False,False,False,False,True"


def test_poe1_browse_and_language_handlers_ignore_empty_optional_paths():
    output = run_powershell(
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$tokens = $null; $errors = $null; "
        f"$ast = [System.Management.Automation.Language.Parser]::ParseFile({ps_quote(GUI)}, [ref]$tokens, [ref]$errors); "
        "$definition = $ast.FindAll({ param($node) "
        "$node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and "
        "$node.Name -eq 'Test-PoePatchExistingDirectory' }, $true) | Select-Object -First 1; "
        "if ($null -ne $definition) { . ([scriptblock]::Create($definition.Extent.Text)) }; "
        "function Get-GuiHandler([string]$Control, [string]$Member) { "
        "$node = $ast.FindAll({ param($candidate) "
        "$candidate -is [System.Management.Automation.Language.ScriptBlockExpressionAst] -and "
        "$candidate.Parent -is [System.Management.Automation.Language.InvokeMemberExpressionAst] -and "
        "$candidate.Parent.Expression.Extent.Text -eq $Control -and "
        "$candidate.Parent.Member.Value -eq $Member }, $true) | Select-Object -First 1; "
        "if ($null -eq $node) { throw \"missing handler: $Control.$Member\" }; "
        "return $node.ScriptBlock.EndBlock.Extent.Text }; "
        "$browseText = (Get-GuiHandler '$BrowseButton' 'Add_Click').Replace("
        "'$Dialog.ShowDialog($Form)', '[System.Windows.Forms.DialogResult]::Cancel'); "
        "$browseHandler = [scriptblock]::Create($browseText); "
        "$languageHandler = [scriptblock]::Create("
        "(Get-GuiHandler '$LanguageCombo' 'Add_SelectedIndexChanged')); "
        "$PathTextBox = New-Object System.Windows.Forms.TextBox; $PathTextBox.Text = ''; "
        "$PreferredGameRoot = ''; "
        "$Form = New-Object System.Windows.Forms.Form; "
        "$ClientCombo = New-Object System.Windows.Forms.ComboBox; "
        "$ManualPathRadio = New-Object System.Windows.Forms.RadioButton; "
        "$ManualPathRadio.Checked = $true; "
        "$status = [pscustomobject]@{ Text = ''; IsError = $false }; "
        "$SetStatus = { param([string]$Text, [bool]$IsError) "
        "$status.Text = $Text; $status.IsError = $IsError }; "
        "$GetRequestedGameVersion = { 'poe1' }; "
        "$GetSelectedLanguageMode = { 'auto' }; "
        "try { "
        "& $browseHandler; "
        "if ($status.IsError) { throw $status.Text }; "
        "& $languageHandler; "
        "if ($status.IsError) { throw $status.Text }; "
        "Write-Output 'EMPTY_PATH_OK' "
        "} finally { $Form.Dispose(); $PathTextBox.Dispose(); "
        "$ClientCombo.Dispose(); $ManualPathRadio.Dispose() }"
    )

    assert output == "EMPTY_PATH_OK"


def test_restore_directory_dialog_constructs_without_opening_window(tmp_path: Path):
    game = tmp_path / "restore gui game"
    (game / "Bundles2").mkdir(parents=True)
    (game / "Bundles2" / "_.index.bin").write_bytes(b"index")

    output = run_powershell(
        f". {ps_quote(COMMON)}; "
        "$tokens = $null; $errors = $null; "
        f"$ast = [System.Management.Automation.Language.Parser]::ParseFile({ps_quote(COMMON)}, [ref]$tokens, [ref]$errors); "
        "$definition = $ast.FindAll({ param($node) "
        "$node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and "
        "$node.Name -eq 'Show-Poe2GameDirectorySelectionDialog' }, $true) | Select-Object -First 1; "
        "$text = $definition.Extent.Text.Replace('$Result = $Form.ShowDialog()', "
        "'$Result = [System.Windows.Forms.DialogResult]::Cancel'); "
        ". ([scriptblock]::Create($text)); "
        f"try {{ Show-Poe2GameDirectorySelectionDialog -PreferredRoot {ps_quote(game)}; throw 'dialog did not cancel' }} "
        "catch { if ($_.Exception.Message -ne '已取消游戏目录选择。') { throw } }; "
        'Write-Output "RESTORE_GUI_OK"'
    )

    assert output == "RESTORE_GUI_OK"


def test_release_payload_copies_stay_in_sync():
    assert COMMON.read_bytes() == PAYLOAD_COMMON.read_bytes()
    assert UPDATE.read_bytes() == PAYLOAD_UPDATE.read_bytes()
    assert RESTORE.read_bytes() == PAYLOAD_RESTORE.read_bytes()
    assert GUI.read_bytes() == PAYLOAD_GUI.read_bytes()
