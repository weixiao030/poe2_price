import subprocess
import zipfile
import re
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "物价补丁" / "tools"
PAYLOAD = ROOT / "build" / "payload"
PAYLOAD_ZIP = ROOT / "build" / "payload.zip"
PAYLOAD_ENC = ROOT / "build" / "Poe2PatchLauncher" / "payload.enc"
PACKER_PROJECT = ROOT / "build" / "PayloadPacker" / "PayloadPacker.csproj"
PUBLISHED_LAUNCHER = ROOT / "build" / "publish-self" / "Poe2PatchLauncher.exe"
SOURCE_LAUNCHER = ROOT / "物价补丁" / "物价补丁.exe"
LAUNCHER_PROJECT = ROOT / "build" / "Poe2PatchLauncher" / "Poe2PatchLauncher.csproj"
SOURCE_DOC = ROOT / "物价补丁" / "使用文档.docx"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "build-release.yml"

PAYLOAD_FILES = [
    "poe2_patch_common.ps1",
    "poe_patch_profiles.ps1",
    "price_patch_gui.ps1",
    "update_price_patch.ps1",
    "restore_price_patch.ps1",
    "poe1_patch_common.ps1",
    "localize_poe1.ps1",
    "update_poe1_price_patch.ps1",
    "restore_poe1_price_patch.ps1",
    "build_poe1_price_patch.py",
    "poe2_name_price_patch.py",
    "poe2_island_rumour_patch.py",
    "build_poe2scout_price_patch.py",
    "BundleExtractor/BundleExtractor.exe",
    "BundleExtractor/oo2core.dll",
    "BundleExtractor/vcruntime140.dll",
] + [
    path.relative_to(TOOLS).as_posix()
    for path in sorted((TOOLS / "price_sources").rglob("*.py"))
]


def source_for_payload(relative: str) -> Path:
    return TOOLS.joinpath(*relative.split("/"))


def test_payload_folder_matches_tool_sources():
    for relative in PAYLOAD_FILES:
        source = source_for_payload(relative)
        payload = PAYLOAD / relative
        assert payload.exists(), f"missing payload file: {relative}"
        assert payload.read_bytes() == source.read_bytes(), f"stale payload file: {relative}"


def test_payload_zip_matches_payload_folder():
    assert PAYLOAD_ZIP.exists(), "missing build/payload.zip"
    with zipfile.ZipFile(PAYLOAD_ZIP, "r") as archive:
        names = {name.replace("\\", "/") for name in archive.namelist()}
        for relative in PAYLOAD_FILES:
            assert relative in names, f"missing payload zip entry: {relative}"
            assert archive.read(relative) == (PAYLOAD / relative).read_bytes(), (
                f"stale payload zip entry: {relative}"
            )


def test_encrypted_payload_matches_payload_zip():
    assert PAYLOAD_ENC.exists(), "missing build/Poe2PatchLauncher/payload.enc"
    result = subprocess.run(
        [
            "dotnet",
            "run",
            "-c",
            "Release",
            "--project",
            str(PACKER_PROJECT),
            "--",
            "--verify",
            str(PAYLOAD_ZIP),
            str(PAYLOAD_ENC),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_source_launchers_match_published_launcher():
    assert PUBLISHED_LAUNCHER.exists(), "missing published launcher"
    expected = PUBLISHED_LAUNCHER.read_bytes()
    assert SOURCE_LAUNCHER.read_bytes() == expected, "stale unified launcher"
    assert not (ROOT / "物价补丁" / "一键更新物价补丁.exe").exists()
    assert not (ROOT / "物价补丁" / "一键还原物价补丁.exe").exists()


def test_declared_version_is_consistent():
    update_script = (TOOLS / "update_price_patch.ps1").read_text(encoding="utf-8-sig")
    match = re.search(r'\$script:PatchVersion\s*=\s*"v([0-9.]+)"', update_script)
    assert match, "missing PatchVersion"
    version = match.group(1)
    assert version == "0.5.6"

    restore_script = (TOOLS / "restore_price_patch.ps1").read_text(encoding="utf-8-sig")
    restore_match = re.search(
        r'\$script:PatchVersion\s*=\s*"v([0-9.]+)"', restore_script
    )
    assert restore_match, "missing restore PatchVersion"
    assert restore_match.group(1) == version

    for script_name in (
        "price_patch_gui.ps1",
        "update_poe1_price_patch.ps1",
        "restore_poe1_price_patch.ps1",
    ):
        script = (TOOLS / script_name).read_text(encoding="utf-8-sig")
        assert f'PatchVersion = "v{version}"' in script, script_name

    release_doc_script = (ROOT / "build" / "create_release_doc.py").read_text(
        encoding="utf-8-sig"
    )
    assert f'PATCH_VERSION = "v{version}"' in release_doc_script

    project = ET.parse(LAUNCHER_PROJECT).getroot()
    properties = {node.tag: (node.text or "").strip() for node in project.iter()}
    assert properties["Version"] == version
    assert properties["AssemblyVersion"] == version
    assert properties["FileVersion"] == version
    assert properties["InformationalVersion"] == version
    assert properties["IncludeSourceRevisionInInformationalVersion"].lower() == "false"

    readme = (ROOT / "README.md").read_text(encoding="utf-8-sig")
    changelog = (ROOT / "更新日志.md").read_text(encoding="utf-8-sig")
    assert f"POE1/2 物价补丁 v{version}" in readme
    assert f"（v{version}）" in changelog

    with zipfile.ZipFile(SOURCE_DOC, "r") as archive:
        document = ET.fromstring(archive.read("word/document.xml"))
        core_properties = ET.fromstring(archive.read("docProps/core.xml"))
    assert f"POE1 / POE2 物价补丁使用文档 v{version}" in "".join(document.itertext())
    title = core_properties.find("{http://purl.org/dc/elements/1.1/}title")
    assert title is not None
    assert title.text == f"POE1 / POE2 物价补丁使用文档 v{version}"


def test_release_document_describes_fail_safe_behavior():
    assert SOURCE_DOC.exists(), "missing generated release document"
    with zipfile.ZipFile(SOURCE_DOC, "r") as archive:
        document = ET.fromstring(archive.read("word/document.xml"))
    text = "".join(document.itertext())
    for expected in (
        "实时数据失败时仅使用当前范围和模式的兼容核心缓存",
        "没有安全候选时只停止本次更新，不覆盖当前游戏",
        "写入或校验失败会自动重试一次",
        "低匹配会保留未命中的旧价格",
        "发布包另含校验过的离线修复包",
        "华为云、阿里云、南京大学镜像和 Python 官方备用源",
        "更新和还原都会自动识别",
        "流放之路：降临",
        "如果发现多个客户端",
        "确认自动识别的路径和客户端类型",
        "点击底部“还原物价补丁”执行还原",
        "自动识别、汉化补丁、简体中文、繁体中文或跟随游戏配置",
        "更新与还原必须使用同一目标语言",
        "POE1 国际服一键汉化",
        "每次都会从 PoEDB 推荐的 LibGGPK3 GitHub 最新 Release 下载",
        "第二个（法文）国旗",
        "ghfast.top",
        "gh-proxy.com",
        "正常使用不需要联网",
    ):
        assert expected in text


def test_release_workflow_uses_stable_windows_runner_and_waits_for_inflight_runs():
    workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8-sig")
    assert "runs-on: windows-2022" in workflow
    assert "timeout-minutes: 45" in workflow
    assert "cancel-in-progress: false" in workflow


def test_runtime_downloads_prefer_domestic_mirrors_with_official_fallback():
    common = (TOOLS / "poe2_patch_common.ps1").read_text(encoding="utf-8-sig")
    release = (ROOT / "build" / "make_release.ps1").read_text(encoding="utf-8-sig")

    dotnet_sources = (
        "https://dotnetcli.azureedge.net/dotnet/",
        "https://builds.dotnet.microsoft.com/dotnet/",
    )
    python_sources = (
        "https://mirrors.huaweicloud.com/python/",
        "https://mirrors.aliyun.com/python-release/windows/",
        "https://mirrors.nju.edu.cn/python/",
        "https://www.python.org/ftp/python/",
    )
    assert [common.index(source) for source in dotnet_sources] == sorted(
        common.index(source) for source in dotnet_sources
    )
    assert [common.index(source) for source in python_sources] == sorted(
        common.index(source) for source in python_sources
    )
    assert [release.index(source) for source in python_sources] == sorted(
        release.index(source) for source in python_sources
    )
    assert "ExpectedSha512" in common and "ExpectedSha256" in common
    assert "Install-Poe2DotNetRuntimeArchive" in common
    assert "使用随发布包提供的 .NET" in common
    assert "Invoke-DownloadFromSources" in release
    assert "tools\\downloads\\dotnet-runtime-8.0.28-win-x64.zip" in release


def test_localization_payload_matches_domestic_first_download_policy():
    source = (TOOLS / "localize_poe1.ps1").read_text(encoding="utf-8-sig")
    payload = (PAYLOAD / "localize_poe1.ps1").read_text(encoding="utf-8-sig")
    assert source == payload
    for expected in ("ghfast.top", "gh-proxy.com", "GitHub 官方源", "Test-Poe1LocalizationExecutable", "SHA256"):
        assert expected in source
    assert source.index('Name = "国内加速源 ghfast.top"') < source.index(
        'Name = "国内加速源 gh-proxy.com"'
    )
    assert source.index('Name = "国内加速源 gh-proxy.com"') < source.index(
        'Name = "GitHub 官方源"'
    )


def test_release_quick_start_keeps_directory_selection_instructions():
    release = (ROOT / "build" / "make_release.ps1").read_text(encoding="utf-8-sig")
    quick_start = (ROOT / "物价补丁" / "请先看使用文档.txt").read_text(
        encoding="utf-8-sig"
    )

    for expected in ("可以放在任意位置", "手动选择", "流放之路：降临", "多个客户端", "汉化补丁", "一键汉化POE1国际服"):
        assert expected in release
        assert expected in quick_start
    assert "把整个物价补丁文件夹放到 POE2 游戏根目录" not in release
    assert "把整个物价补丁文件夹放到 POE2 游戏根目录" not in quick_start
