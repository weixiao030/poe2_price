import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMMON = ROOT / "物价补丁" / "tools" / "poe2_patch_common.ps1"
PAYLOAD_COMMON = ROOT / "desktop" / ".runtime" / "tools" / "poe2_patch_common.ps1"
UPDATE = ROOT / "物价补丁" / "tools" / "update_price_patch.ps1"
PAYLOAD_UPDATE = ROOT / "desktop" / ".runtime" / "tools" / "update_price_patch.ps1"
RESTORE = ROOT / "物价补丁" / "tools" / "restore_price_patch.ps1"
PAYLOAD_RESTORE = ROOT / "desktop" / ".runtime" / "tools" / "restore_price_patch.ps1"


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
            "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(); " + script,
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
    launcher = (ROOT / "desktop/src/main/index.ts").read_text(encoding="utf-8")

    assert '"Local\\Poe2PricePatch-Game-"' in common
    assert "requestSingleInstanceLock" in launcher
    assert "-SkipGameDirectoryMutex" in update








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


def test_gui_and_update_scripts_forward_explicit_league_without_cross_season_fallback():
    gui = (ROOT / "desktop/src/renderer/stores/app.ts").read_text(encoding="utf-8")
    update = UPDATE.read_text(encoding="utf-8-sig")
    common = COMMON.read_text(encoding="utf-8-sig")

    for expected in (
        "getLeagues",
        "selectedLeague",
        "ScoutLeague",
        "PoeNinjaLeague",
        "leagueIsCurrent",
    ):
        assert expected in gui
    assert '"--fallback-price-sources", "poe-ninja"' in update
    assert '"--league-is-current"' in update
    assert "PoeCurrencySeason" in update
    assert "season=" in update
    assert "$UseChinaPriceSource = $IsChinaClient" in update
    assert "Resolve-PoePatchLeagueSelection" in update
    assert "--poe2db-fallback" in update
    assert "-not $IsChinaClient" in update
    assert "ConvertTo-PoePatchBoolean" in common
    assert "Get-PoePatchLeagueCacheToken" in common




def test_powershell_league_parser_handles_string_booleans_without_mixing_seasons():
    output = run_powershell(
        f". {ps_quote(COMMON)}; "
        "function global:Invoke-RestMethod { "
        "param([string]$Uri,[hashtable]$Headers,[int]$TimeoutSec); "
        "return @("
        "[pscustomobject]@{Value='Old';ShortName='old';IsCurrent='false';IsHardcore='false'},"
        "[pscustomobject]@{Value='Current';ShortName='current';IsCurrent='true';IsHardcore='false'},"
        "[pscustomobject]@{Value='HC Current';ShortName='currenthc';IsCurrent='true';IsHardcore='true'}) "
        "}; "
        "$items=@(Get-PoePatchLeagueOptions -GameVersion poe2); "
        "if($items.Count -ne 2 -or $items[0].PoeNinjaLeague -ne 'Current' -or $items[1].IsCurrent){throw 'season parser mismatch'}; "
        "Write-Output 'STRING_BOOLEAN_SEASON_PARSE_OK'"
    )
    assert output == "STRING_BOOLEAN_SEASON_PARSE_OK"


def test_powershell_league_parser_keeps_newest_current_first_during_transition():
    output = run_powershell(
        f". {ps_quote(COMMON)}; "
        "function global:Invoke-RestMethod { "
        "param([string]$Uri,[hashtable]$Headers,[int]$TimeoutSec); "
        "return @("
        "[pscustomobject]@{Value='Forbidden Rites';ShortName='forbiddenrites';IsCurrent=$true;IsHardcore=$false},"
        "[pscustomobject]@{Value='HC Forbidden Rites';ShortName='forbiddenriteshc';IsCurrent=$true;IsHardcore=$true},"
        "[pscustomobject]@{Value='Runes of Aldur';ShortName='runes';IsCurrent=$true;IsHardcore=$false}) "
        "}; "
        "$items=@(Get-PoePatchLeagueOptions -GameVersion poe2); "
        "if($items.Count -ne 2 -or $items[0].PoeNinjaLeague -ne 'Forbidden Rites' -or $items[1].PoeNinjaLeague -ne 'Runes of Aldur' -or $items[0].Label -ne 'Forbidden Rites（最新）' -or $items[1].Label -ne 'Runes of Aldur'){throw 'newest season or label was not kept first'}; "
        "Write-Output 'NEWEST_CURRENT_SEASON_FIRST_OK'"
    )
    assert output == "NEWEST_CURRENT_SEASON_FIRST_OK"


def test_powershell_league_parser_uses_builtin_current_season_when_discovery_fails():
    output = run_powershell(
        f". {ps_quote(COMMON)}; "
        "function global:Invoke-RestMethod { throw 'simulated timeout' }; "
        "$items=@(Get-PoePatchLeagueOptions -GameVersion poe2); "
        "if($items.Count -ne 1 -or $items[0].ScoutLeague -ne 'runes' -or "
        "$items[0].PoeNinjaLeague -ne 'Runes of Aldur' -or -not $items[0].IsCurrent -or "
        "-not $items[0].DiscoveryFallback) { throw 'builtin season fallback mismatch' }; "
        "Write-Output 'BUILTIN_SEASON_FALLBACK_OK'"
    )
    assert output == "BUILTIN_SEASON_FALLBACK_OK"


def test_powershell_ggpk_installer_dependencies_are_repaired_from_extractor(tmp_path: Path):
    installer = tmp_path / "一键安装特殊补丁工具"
    fallback = tmp_path / "tools" / "GGPKExtractor"
    installer.mkdir(parents=True)
    fallback.mkdir(parents=True)
    required = (
        "LibBundle3.dll",
        "LibBundledGGPK3.dll",
        "LibGGPK3.dll",
        "SystemExtensions.dll",
        "oo2core.dll",
        "vcruntime140.dll",
    )
    for name in required:
        (fallback / name).write_bytes(name.encode("ascii"))
    (installer / "LibGGPK3.dll").unlink(missing_ok=True)

    output = run_powershell(
        f". {ps_quote(COMMON)}; "
        f"$copied=@(Ensure-Poe2GgpkInstallerDependencies -BundledInstallerDir {ps_quote(installer)} -FallbackDirectories @({ps_quote(fallback)})); "
        f"$required=@({','.join(repr(name) for name in required)}); "
        "if($copied -notcontains 'LibGGPK3.dll' -or @($required | Where-Object { -not (Test-Path (Join-Path "
        f"{ps_quote(installer)} $_) -PathType Leaf) }}).Count -ne 0) {{ throw 'GGPK dependency repair mismatch' }}; "
        "Write-Output 'GGPK_DEPENDENCY_REPAIR_OK'"
    )
    assert output == "GGPK_DEPENDENCY_REPAIR_OK"




def test_explicit_poe1_league_uses_seasoned_fallback_chain():
    update = (ROOT / "物价补丁" / "tools" / "update_poe1_price_patch.ps1").read_text(
        encoding="utf-8-sig"
    )
    gui = (ROOT / "desktop/src/renderer/stores/app.ts").read_text(encoding="utf-8")
    assert "PoeNinjaLeague" in gui
    assert '"--fallback-price-sources", "poe2scout"' in update
    assert '"--league-is-current"' in update
    assert "league_is_current" in update
    assert "Resolve-PoePatchLeagueSelection" in update
