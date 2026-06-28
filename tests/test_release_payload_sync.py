import subprocess
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "物价补丁" / "tools"
PAYLOAD = ROOT / "build" / "payload"
PAYLOAD_ZIP = ROOT / "build" / "payload.zip"
PAYLOAD_ENC = ROOT / "build" / "Poe2PatchLauncher" / "payload.enc"
PACKER_PROJECT = ROOT / "build" / "PayloadPacker" / "PayloadPacker.csproj"

PAYLOAD_FILES = [
    "poe2_patch_common.ps1",
    "update_price_patch.ps1",
    "restore_price_patch.ps1",
    "poe2_name_price_patch.py",
    "poe2_island_rumour_patch.py",
    "build_poe2scout_price_patch.py",
    "BundleExtractor/BundleExtractor.exe",
    "BundleExtractor/oo2core.dll",
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
