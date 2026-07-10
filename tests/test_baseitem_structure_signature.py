import hashlib
import importlib.util
import json
import struct
import subprocess
import sys
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "物价补丁" / "tools"
PAYLOAD = ROOT / "build" / "payload"
SCRIPT = TOOLS / "poe2_name_price_patch.py"
UPDATE_SCRIPT = TOOLS / "update_price_patch.ps1"
RESTORE_SCRIPT = TOOLS / "restore_price_patch.ps1"
PAYLOAD_UPDATE_SCRIPT = PAYLOAD / "update_price_patch.ps1"
PAYLOAD_RESTORE_SCRIPT = PAYLOAD / "restore_price_patch.ps1"


SIGNATURE_FIELDS = (
    "signature_version",
    "row_count",
    "row_size",
    "metadata_paths_sha256",
    "fixed_rows_sha256",
    "compatibility_sha256",
)


def load_module():
    spec = importlib.util.spec_from_file_location("baseitem_signature", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def powershell_functions(path: Path, next_function: str) -> str:
    script = path.read_text(encoding="utf-8-sig")
    start = script.index("function Get-BaseItemsMetadataSignature")
    end = script.index(f"function {next_function}", start)
    return script[start:end]


def run_powershell(script: str) -> None:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def encode_string(text: str) -> bytes:
    return text.encode("utf-16-le") + b"\x00\x00"


def make_baseitem_dat() -> bytes:
    row_size = 48
    paths = ["Metadata/Items/A", "Metadata/Items/B"]
    names = ["Item A", "Item B"]
    rows = bytearray(row_size * len(paths))
    strings = bytearray()

    for row_index, (path, name) in enumerate(zip(paths, names, strict=True)):
        row_start = row_index * row_size
        for field_index in range(row_size // 4):
            struct.pack_into(
                "<I", rows, row_start + field_index * 4, 1000 + row_index * 100 + field_index
            )

        metadata_offset = len(strings)
        strings.extend(encode_string(path))
        name_offset = len(strings)
        strings.extend(encode_string(name))
        struct.pack_into("<I", rows, row_start, metadata_offset)
        struct.pack_into("<I", rows, row_start + 8 * 4, name_offset)

    return struct.pack("<I", len(paths)) + bytes(rows) + bytes(strings)


def append_display_name(module, data: bytes, row_index: int, name: str) -> bytes:
    layout = module.detect_base_item_layout(data)
    output = bytearray(data)
    name_offset = len(output) - layout.string_base
    output.extend(encode_string(name))
    pointer_pos = 4 + row_index * layout.row_size + module.DISPLAY_NAME_FIELD_INDEX * 4
    struct.pack_into("<I", output, pointer_pos, name_offset)
    return bytes(output)


def test_signature_ignores_display_name_pointer_and_appended_strings():
    module = load_module()
    source = make_baseitem_dat()
    patched = append_display_name(module, source, 1, "Item B=12D")

    assert module.build_structure_signature(patched) == module.build_structure_signature(source)


def test_signature_changes_when_any_other_fixed_row_field_changes():
    module = load_module()
    source = make_baseitem_dat()
    changed = bytearray(source)
    changed[4 + 4] ^= 0x01

    before = module.build_structure_signature(source)
    after = module.build_structure_signature(bytes(changed))

    assert after["metadata_paths_sha256"] == before["metadata_paths_sha256"]
    assert after["fixed_rows_sha256"] != before["fixed_rows_sha256"]
    assert after["compatibility_sha256"] != before["compatibility_sha256"]


def test_signature_changes_when_metadata_path_text_changes():
    module = load_module()
    source = make_baseitem_dat()
    changed = source.replace(
        "Metadata/Items/A".encode("utf-16-le"),
        "Metadata/Items/C".encode("utf-16-le"),
        1,
    )

    before = module.build_structure_signature(source)
    after = module.build_structure_signature(changed)

    assert after["metadata_paths_sha256"] != before["metadata_paths_sha256"]
    assert after["fixed_rows_sha256"] == before["fixed_rows_sha256"]
    assert after["compatibility_sha256"] != before["compatibility_sha256"]


def test_signature_cli_prints_complete_json(tmp_path: Path):
    source = tmp_path / "baseitemtypes.datc64"
    source.write_bytes(make_baseitem_dat())

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "signature", "--source", str(source)],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["signature_version"] == 1
    assert payload["row_count"] == 2
    assert payload["row_size"] == 48
    assert len(payload["metadata_paths_sha256"]) == 64
    assert len(payload["fixed_rows_sha256"]) == 64

    compatibility_source = "\n".join(
        (
            str(payload["signature_version"]),
            str(payload["row_count"]),
            str(payload["row_size"]),
            payload["metadata_paths_sha256"],
            payload["fixed_rows_sha256"],
        )
    ).encode("ascii")
    assert payload["compatibility_sha256"] == hashlib.sha256(
        compatibility_source
    ).hexdigest()


def test_powershell_signature_bridge_parses_and_compares_every_field():
    script_pairs = (
        (UPDATE_SCRIPT, "Test-RestoreZipUsable"),
        (RESTORE_SCRIPT, "Get-ZipBaseItemsEntryAsTempFile"),
    )
    valid_json = json.dumps(
        {
            "signature_version": 1,
            "row_count": 2,
            "row_size": 48,
            "metadata_paths_sha256": "a" * 64,
            "fixed_rows_sha256": "b" * 64,
            "compatibility_sha256": "c" * 64,
        },
        separators=(",", ":"),
    )
    missing_json = json.dumps(
        {
            "signature_version": 1,
            "row_count": 2,
            "row_size": 48,
            "metadata_paths_sha256": "a" * 64,
            "fixed_rows_sha256": "b" * 64,
        },
        separators=(",", ":"),
    )

    harness = textwrap.dedent(
        r"""
        $ErrorActionPreference = "Stop"
        $RepoRoot = $env:TEMP
        $CodeToolsRoot = $env:TEMP
        $script:SignatureText = '__VALID_JSON__'

        function Assert-File { param([string]$Path, [string]$Label) }
        function Ensure-PythonRequests { param([string]$RepoRoot) return "python" }
        function Invoke-Poe2Python {
            param(
                [string]$Python,
                [string[]]$ArgumentList = @(),
                [switch]$Quiet
            )
            if ($ArgumentList.Count -ne 4) { throw "unexpected argument count" }
            if ($ArgumentList[1] -cne "signature") { throw "signature command was not used" }
            if ($ArgumentList[2] -cne "--source") { throw "--source was not used" }
            if ($ArgumentList[3] -cne "source.datc64") { throw "source path was not forwarded" }
            return [pscustomobject]@{
                ExitCode = 0
                Lines = @($script:SignatureText)
                Text = $script:SignatureText
            }
        }

        __FUNCTIONS__

        $Actual = Get-BaseItemsMetadataSignature "source.datc64"
        foreach ($Field in @(__QUOTED_FIELDS__)) {
            if ($null -eq $Actual.PSObject.Properties[$Field]) {
                throw "parsed signature is missing $Field"
            }
        }

        $script:SignatureText = '__MISSING_JSON__'
        $MissingWasRejected = $false
        try {
            Get-BaseItemsMetadataSignature "source.datc64" | Out-Null
        }
        catch {
            $MissingWasRejected = $true
        }
        if (-not $MissingWasRejected) { throw "missing signature field was accepted" }

        function Get-BaseItemsMetadataSignature {
            param([string]$SourceDat)
            return $script:Signatures[$SourceDat]
        }

        $script:Signatures = @{
            left = ('__VALID_JSON__' | ConvertFrom-Json)
            right = ('__VALID_JSON__' | ConvertFrom-Json)
        }
        if (-not (Test-BaseItemsCompatible "left" "right")) {
            throw "identical signatures were rejected"
        }

        $Alternatives = @{
            signature_version = 2
            row_count = 3
            row_size = 49
            metadata_paths_sha256 = ("A" * 64)
            fixed_rows_sha256 = ("B" * 64)
            compatibility_sha256 = ("C" * 64)
        }
        foreach ($Field in @(__QUOTED_FIELDS__)) {
            $Changed = '__VALID_JSON__' | ConvertFrom-Json
            $Changed.$Field = $Alternatives[$Field]
            $script:Signatures["right"] = $Changed
            if (Test-BaseItemsCompatible "left" "right") {
                throw "signature mismatch was accepted for $Field"
            }
        }
        """
    )
    quoted_fields = ", ".join(f'"{field}"' for field in SIGNATURE_FIELDS)

    for script_path, next_function in script_pairs:
        functions = powershell_functions(script_path, next_function)
        command = (
            harness.replace("__FUNCTIONS__", functions)
            .replace("__VALID_JSON__", valid_json)
            .replace("__MISSING_JSON__", missing_json)
            .replace("__QUOTED_FIELDS__", quoted_fields)
        )
        run_powershell(command)


def test_powershell_signature_bridge_matches_payload_copy():
    assert powershell_functions(
        UPDATE_SCRIPT, "Test-RestoreZipUsable"
    ) == powershell_functions(PAYLOAD_UPDATE_SCRIPT, "Test-RestoreZipUsable")
    assert powershell_functions(
        RESTORE_SCRIPT, "Get-ZipBaseItemsEntryAsTempFile"
    ) == powershell_functions(
        PAYLOAD_RESTORE_SCRIPT, "Get-ZipBaseItemsEntryAsTempFile"
    )
