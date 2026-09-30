"""Run the real PowerShell guards against isolated process and game fixtures."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
COMMON = ROOT / "物价补丁/tools/poe2_patch_common.ps1"
WORKER = ROOT / "desktop/resources/worker.ps1"
pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell process guards")

# Keep state on each object so a second HasExited read can observe termination.
# Zero activity counters intentionally do not establish whether it has exited.
PROCESS_MOCK = r"""
function Get-Process {
    param([string[]]$Name, $ErrorAction)
    foreach ($Spec in @($Request.testProcesses)) {
        if ($Name.Count -gt 0 -and $Spec.name -notin $Name) { continue }
        $Item = [pscustomobject]@{
            ProcessName = $Spec.name; Id = 1756
            ExitStates = @($Spec.exitStates); ExitReadIndex = 0
            ImagePath = $Spec.path; PathThrows = [bool]$Spec.pathThrows
            CPU = 0; HandleCount = 0; Threads = @()
        }
        $Item | Add-Member ScriptProperty HasExited {
            $Index = [Math]::Min($this.ExitReadIndex, $this.ExitStates.Count - 1)
            $this.ExitReadIndex += 1
            $State = $this.ExitStates[$Index]
            if ($State -is [string] -and $State -eq 'error') { throw 'simulated process status access denied' }
            return $State
        }
        $Item | Add-Member ScriptProperty Path {
            if ($this.PathThrows) { throw 'simulated process path access denied' }
            return $this.ImagePath
        }
        $Item
    }
}
"""


def ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def run_powershell(script, *arguments):
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
         str(script), *map(str, arguments)],
        capture_output=True, text=True, encoding="utf-8", timeout=30, cwd=ROOT,
    )


@pytest.fixture
def worker_root(tmp_path):
    tools = tmp_path / "worker/tools"
    tools.mkdir(parents=True)
    shutil.copyfile(COMMON, tools / COMMON.name)
    shutil.copyfile(COMMON.with_name("poe_patch_leagues.ps1"), tools / "poe_patch_leagues.ps1")
    # Windows PowerShell needs the BOM to decode the worker's Chinese messages.
    (tools.parent / WORKER.name).write_text(WORKER.read_text(encoding="utf-8-sig"), encoding="utf-8-sig")
    (tools / "poe_patch_profiles.ps1").write_text(
        PROCESS_MOCK + """
function Resolve-PoePatchManualSelection {
    param($RequestedGameVersion, $Path, $Poe1LanguageMode)
    return [pscustomobject]@{
        Path = $Path; GameVersion = $RequestedGameVersion
        InstallInfo = [pscustomobject]@{ IsChina = $false; InstallKind = 'fixture' }
    }
}
""", encoding="utf-8-sig",
    )
    (tools / "update_price_patch.ps1").write_text(
        "param([switch]$SkipGameDirectoryMutex)\n"
        "Write-Output '__UPDATE_REACHED__'\n$global:LASTEXITCODE = 0\n",
        encoding="utf-8-sig",
    )
    return tools.parent


def process_spec(game, state, location="same", name="PathOfExile_x64"):
    paths = {
        "same": game / "PathOfExile_x64.exe",
        "child": game / "bin/PathOfExile2.exe",
        "other": game.parent / "other-game/PathOfExile_x64.exe",
        "prefix": game.parent / (game.name + "-copy/PathOfExile_x64.exe"),
        "empty": "",
        "unreadable": "",
    }
    return {
        "name": name,
        "exitStates": state,
        "path": str(paths[location]),
        "pathThrows": location == "unreadable",
    }


def invoke_worker(worker_root, game, processes, automatic):
    index = game / "Bundles2/_.index.bin"
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_bytes(b"synthetic index")
    request = worker_root / "request.json"
    request.write_text(json.dumps({
        "action": "run", "automatic": automatic,
        "request": {
            "gameVersion": "poe2", "gameDirectory": str(game),
            "languageMode": "en", "operation": "update",
        },
        "arguments": {}, "script": "update_price_patch.ps1",
        "testProcesses": processes,
    }, ensure_ascii=False), encoding="utf-8")
    result = run_powershell(worker_root / WORKER.name, "-RequestPath", request)
    assert index.read_bytes() == b"synthetic index"
    return result


@pytest.mark.parametrize("automatic", [False, True], ids=["manual", "automatic"])
@pytest.mark.parametrize("state,location,blocked", [
    pytest.param([True], "same", False, id="exited"),
    pytest.param([True], "empty", False, id="exited-empty-path"),
    pytest.param([True], "unreadable", False, id="exited-unreadable-path"),
    pytest.param([False], "same", True, id="live-zero-activity"),
    pytest.param([False], "child", True, id="live-child-directory"),
    pytest.param([False], "empty", True, id="live-empty-path"),
    pytest.param([False], "unreadable", True, id="live-unreadable-path"),
    pytest.param(["error"], "same", True, id="status-access-denied"),
    pytest.param(["error"], "empty", True, id="status-and-path-unavailable"),
    pytest.param([None], "same", True, id="status-unknown"),
    pytest.param([False, True], "same", False, id="exit-during-path-read"),
    pytest.param([False, True], "empty", False, id="exit-with-empty-path"),
    pytest.param([False, True], "unreadable", False, id="exit-with-unreadable-path"),
    pytest.param([False], "other", False, id="other-directory"),
    pytest.param([False], "prefix", False, id="same-directory-prefix"),
])
def test_worker_process_lifetime_and_directory_guard(
    worker_root, tmp_path, state, location, blocked, automatic,
):
    game = tmp_path / "游戏目录"
    game.mkdir()
    result = invoke_worker(worker_root, game, [process_spec(game, state, location)], automatic)
    expected_code = (2 if automatic else 1) if blocked else 0
    assert result.returncode == expected_code, result.stdout + result.stderr
    assert ("__UPDATE_REACHED__" in result.stdout) is not blocked
    if blocked:
        expected_message = "已跳过本轮自动更新" if automatic else "请关闭游戏后再执行"
        assert expected_message in result.stdout + result.stderr


def test_exited_entry_cannot_hide_a_live_game(worker_root, tmp_path):
    game = tmp_path / "游戏目录"
    game.mkdir()
    processes = [process_spec(game, [True]), process_spec(game, [False])]
    result = invoke_worker(worker_root, game, processes, automatic=False)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "请关闭游戏后再执行" in result.stderr
    assert "__UPDATE_REACHED__" not in result.stdout


@pytest.mark.parametrize("state,locked,expected_message", [
    pytest.param([True], False, None, id="exited-and-unlocked"),
    pytest.param([False], False, "游戏仍在运行", id="live"),
    pytest.param(["error"], False, "游戏仍在运行", id="status-access-denied"),
    pytest.param([None], False, "游戏仍在运行", id="status-unknown"),
    pytest.param([True], True, "索引文件被占用或不可写", id="exited-but-file-still-locked"),
])
def test_common_preflight_keeps_real_file_lock_guard(tmp_path, state, locked, expected_message):
    game = tmp_path / "游戏目录"
    index = game / "Bundles2/_.index.bin"
    index.parent.mkdir(parents=True)
    original = b"synthetic game index; must not be changed"
    index.write_bytes(original)
    request = tmp_path / "processes.json"
    request.write_text(json.dumps({"testProcesses": [process_spec(game, state)]}), encoding="utf-8")
    script = tmp_path / "preflight.ps1"
    script.write_text(
        "$ErrorActionPreference = 'Stop'\n"
        "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()\n"
        f". {ps_quote(COMMON)}\n"
        f"$Request = Get-Content -LiteralPath {ps_quote(request)} -Raw -Encoding UTF8 | ConvertFrom-Json\n"
        + PROCESS_MOCK
        + (f"$Held = [IO.File]::Open({ps_quote(index)}, 'Open', 'ReadWrite', 'None')\n"
           if locked else "$Held = $null\n")
        + "try {\n"
        f"    Assert-Poe2GameFilesAvailable -Poe2Dir {ps_quote(game)} -IndexPath {ps_quote(index)} -RetryCount 1\n"
        "    Write-Output '__PREFLIGHT_ALLOWED__'\n"
        "    exit 0\n"
        "} catch {\n"
        "    [Console]::Error.WriteLine($_.Exception.Message)\n"
        "    exit 1\n"
        "} finally { if ($null -ne $Held) { $Held.Dispose() } }\n",
        encoding="utf-8-sig",
    )
    result = run_powershell(script)
    assert result.returncode == (1 if expected_message else 0), result.stdout + result.stderr
    if expected_message:
        assert expected_message in result.stderr
        assert "__PREFLIGHT_ALLOWED__" not in result.stdout
    else:
        assert "__PREFLIGHT_ALLOWED__" in result.stdout
    assert index.read_bytes() == original
