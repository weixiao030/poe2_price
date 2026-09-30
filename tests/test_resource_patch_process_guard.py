"""Exercise the shipped writer with real, harmless Client.exe processes."""

import json
import os
import shutil
import subprocess
import time
import zipfile
from contextlib import contextmanager
from pathlib import Path
from xml.sax.saxutils import escape

import pytest


ROOT = Path(__file__).resolve().parents[1]
EXTRACTOR = ROOT / "物价补丁/tools/BundleExtractor/BundleExtractor.exe"
pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows process guard")


@pytest.fixture(scope="module")
def client_exe(tmp_path_factory):
    directory = tmp_path_factory.mktemp("client-process-fixture")
    executable = directory / "Client.exe"
    script = directory / "compile.ps1"
    script.write_text(
        "param([string]$OutputPath)\n"
        "$ErrorActionPreference = 'Stop'\n"
        "Add-Type -OutputAssembly $OutputPath -OutputType ConsoleApplication -TypeDefinition @'\n"
        "using System; using System.IO;\n"
        "public class Client { public static void Main(string[] args) {\n"
        "  using (var held = args.Length > 1 ? File.Open(args[1], FileMode.Open, FileAccess.ReadWrite, FileShare.None) : null) {\n"
        "    File.WriteAllText(args[0], \"ready\");\n"
        "    Console.ReadLine();\n"
        "  }\n"
        "} }\n'@\n",
        encoding="utf-8-sig",
    )
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), str(executable)],
        check=True, capture_output=True, timeout=30,
    )
    return executable


@contextmanager
def running_client(client_exe, directory, locked_file=None, executable_name="Client.exe"):
    directory.mkdir(parents=True, exist_ok=True)
    executable = directory / executable_name
    shutil.copyfile(client_exe, executable)
    ready = directory / "ready.txt"
    args = [str(executable), str(ready)]
    if locked_file is not None:
        args.append(str(locked_file))
    process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        deadline = time.monotonic() + 10
        while not ready.exists():
            assert process.poll() is None, "Client fixture exited before readiness"
            assert time.monotonic() < deadline, "Client fixture did not become ready"
            time.sleep(0.05)
        assert process.poll() is None
        yield process
    finally:
        process.communicate(input=b"\n", timeout=10)


def invoke_writer(tmp_path, mode):
    game = tmp_path / "游戏目录"
    target = game / ("Content.ggpk" if mode == "ggpk" else "Bundles2/_.index.bin")
    target.parent.mkdir(parents=True, exist_ok=True)
    patch = tmp_path / "patch.zip"
    with zipfile.ZipFile(patch, "w") as archive:
        archive.writestr("metadata/items/toweraugments/poe2price/ritual.it", b"fixture")
    # Missing target is a sentinel: reaching file-open proves the process guard
    # allowed the operation, without ever risking a real game installation.
    result = subprocess.run([str(EXTRACTOR), f"--patch-{mode}", str(target), str(patch)],
                            capture_output=True, text=True, encoding="utf-8", timeout=20)
    assert result.returncode == 1
    return result, target


@pytest.mark.parametrize("mode", ["ggpk", "bundles"])
@pytest.mark.parametrize("location", ["其他软件", "游戏目录-copy", "另一游戏"])
def test_unrelated_client_does_not_block_writer(client_exe, tmp_path, mode, location):
    with running_client(client_exe, tmp_path / location):
        result, target = invoke_writer(tmp_path, mode)
    assert "Close game and launcher before writing" not in result.stderr
    assert "System.IO.FileNotFoundException" in result.stderr
    assert not target.exists()


@pytest.mark.parametrize("mode", ["ggpk", "bundles"])
@pytest.mark.parametrize("location", ["游戏目录", "游戏目录/启动器"])
def test_game_client_still_blocks_writer(client_exe, tmp_path, mode, location):
    # Two same-name processes ensure an unrelated process cannot hide the launcher.
    with running_client(client_exe, tmp_path / "其他软件"), running_client(client_exe, tmp_path / location):
        result, target = invoke_writer(tmp_path, mode)
    assert "Close game and launcher before writing: Client" in result.stderr
    assert "System.IO.FileNotFoundException" not in result.stderr
    assert not target.exists()


@pytest.mark.parametrize("name", ["PathOfExile", "PathOfExile_x64", "PathOfExileSteam", "PathOfExile_x64Steam"])
def test_live_dedicated_game_process_still_blocks_writer(client_exe, tmp_path, name):
    with running_client(client_exe, tmp_path / "游戏目录", executable_name=name + ".exe"):
        result, target = invoke_writer(tmp_path, "bundles")
    assert "Close game and launcher before writing: " + name in result.stderr
    assert "System.IO.FileNotFoundException" not in result.stderr
    assert not target.exists()


def test_retained_exited_process_is_ignored_and_unknown_state_stays_protected(client_exe, tmp_path):
    dotnet = shutil.which("dotnet")
    if dotnet is None:
        pytest.skip(".NET SDK required for the real Process lifetime probe")
    project = tmp_path / "LifetimeProbe.csproj"
    project.write_text(
        '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
        '<OutputType>Exe</OutputType><TargetFramework>net8.0</TargetFramework>'
        '<ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable>'
        '</PropertyGroup><ItemGroup><ProjectReference Include="'
        + escape(str(ROOT / "build/BundleExtractor/BundleExtractor.csproj"), {'"': '&quot;'})
        + '" /></ItemGroup></Project>', encoding="utf-8",
    )
    (tmp_path / "Program.cs").write_text(r'''
using System.Diagnostics;
using System.Reflection;
using System.Text.Json;

var guard = Assembly.Load("BundleExtractor").GetType("ResourcePatch")!
    .GetMethod("IsProcessRunning", BindingFlags.Static | BindingFlags.NonPublic)!;
bool Running(Process process) => (bool)guard.Invoke(null, new object[] { process })!;
var start = new ProcessStartInfo(args[0]) {
    UseShellExecute = false, RedirectStandardInput = true, CreateNoWindow = true
};
start.ArgumentList.Add(args[1]);
using var child = Process.Start(start)!;
try {
    using var enumerated = Process.GetProcessesByName("Client")
        .Single(process => process.Id == child.Id);
    _ = enumerated.Handle; // Keep the same OS process object alive after exit.
    bool live = Running(enumerated);
    child.StandardInput.WriteLine();
    child.StandardInput.Flush();
    if (!child.WaitForExit(10000)) throw new Exception("Fixture did not exit");
    bool exited = Running(enumerated);
    using var unknown = new Process(); // No associated process: HasExited throws.
    Console.WriteLine(JsonSerializer.Serialize(new { live, exited, unknown = Running(unknown) }));
} finally {
    if (!child.HasExited) { child.Kill(); child.WaitForExit(); }
}
''', encoding="utf-8")
    output = tmp_path / "compiled"
    built = subprocess.run(
        [dotnet, "build", str(project), "--configuration", "Release", "--output", str(output), "--verbosity", "quiet"],
        capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    assert built.returncode == 0, built.stdout + built.stderr
    result = subprocess.run(
        [dotnet, str(output / "LifetimeProbe.dll"), str(client_exe), str(tmp_path / "ready.txt")],
        capture_output=True, text=True, encoding="utf-8", timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"live": True, "exited": False, "unknown": True}


@pytest.mark.parametrize("mode", ["ggpk", "bundles"])
def test_unrelated_client_holding_target_file_still_prevents_access(client_exe, tmp_path, mode):
    target = tmp_path / "游戏目录" / ("Content.ggpk" if mode == "ggpk" else "Bundles2/_.index.bin")
    target.parent.mkdir(parents=True)
    before = b"locked game file sentinel"
    target.write_bytes(before)
    with running_client(client_exe, tmp_path / "其他软件", locked_file=target):
        result, _ = invoke_writer(tmp_path, mode)
    assert "Close game and launcher before writing" not in result.stderr
    assert "System.IO.IOException" in result.stderr
    assert target.read_bytes() == before


def test_write_readback_and_repeat_with_unrelated_client(client_exe, tmp_path):
    # Synthetic index: zero bundles/files, one empty root directory with the
    # POE2 name-hash marker 17594038612473627390; contains no game resources.
    target = tmp_path / "游戏目录/Bundles2/_.index.bin"
    target.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "tests/fixtures/empty-bundles.index.bin", target)
    patch = tmp_path / "patch.zip"
    resource = "metadata/items/toweraugments/poe2price/ritual.it"
    payload = b"synthetic tablet resource\n"
    with zipfile.ZipFile(patch, "w") as archive:
        archive.writestr(resource, payload)
    command = [str(EXTRACTOR), "--patch-bundles", str(target), str(patch)]
    with running_client(client_exe, tmp_path / "其他软件"):
        applied = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=20)
        assert applied.returncode == 0, applied.stderr
        assert "INSTALLED: 1 resources verified" in applied.stdout
        index_after = target.read_bytes()
        bundles_after = list(target.parent.rglob("*.bundle.bin"))
        repeated = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=20)
        assert repeated.returncode == 0, repeated.stderr
        assert "resources already current; no write" in repeated.stdout
        assert target.read_bytes() == index_after
        assert list(target.parent.rglob("*.bundle.bin")) == bundles_after
        extracted = tmp_path / "readback.it"
        result = subprocess.run([str(EXTRACTOR), str(target), resource, str(extracted)],
                                capture_output=True, timeout=20)
        assert result.returncode == 0, result.stderr
        assert extracted.read_bytes() == payload

    with running_client(client_exe, target.parent.parent):
        blocked = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", timeout=20)
        assert blocked.returncode == 1
        assert "Close game and launcher before writing: Client" in blocked.stderr
        assert target.read_bytes() == index_after
