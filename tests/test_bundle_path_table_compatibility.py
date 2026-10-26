"""Exercise third-party path-table compatibility with synthetic game-free data."""

import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import pytest


ROOT = Path(__file__).resolve().parents[1]
LIBRARIES = ROOT / "物价补丁/一键安装特殊补丁工具"
EXTRACTOR = ROOT / "物价补丁/tools/BundleExtractor/BundleExtractor.exe"
EMPTY_INDEX = ROOT / "tests/fixtures/empty-bundles.index.bin"
CHUNK_SIZE = 262144
ROOT_HASH = 17594038612473627390
TARGET = "data/balance/simplified chinese/baseitemtypes.datc64"
THIRD_PARTY = "data/balance/simplified chinese/words.datc64"
NEW_FIRST = "metadata/items/toweraugments/poe2price/ritual.it"
NEW_SECOND = "metadata/items/toweraugments/poe2price/breach.it"
TRAILER = b"synthetic third-party bytes after directory bundle\x00\xff"
pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows bundle runtime")


HELPER_SOURCE = r'''
using System.Text.Json;
using LibBundle3;
using BIndex = LibBundle3.Index;

static class Program
{
    sealed class FreshBundle(Stream stream) : Bundle(stream, (LibBundle3.Records.BundleRecord?)null);
    static BIndex Open(string path) => new BIndex(
        File.OpenRead(path), false, false, new DriveBundleFactory(Path.GetDirectoryName(path)!));
    static int Main(string[] args)
    {
        try
        {
            switch (args[0])
            {
                case "pack":
                    using (var stream = new MemoryStream())
                    {
                        using var bundle = new FreshBundle(stream);
                        var compressor = args.Length > 3
                            ? (Oodle.Compressor)int.Parse(args[2]) : Oodle.Compressor.Invalid;
                        bundle.Save(File.ReadAllBytes(args[1]), compressor);
                        File.WriteAllBytes(args[^1], stream.ToArray());
                    }
                    break;
                case "unpack":
                    using (var bundle = new Bundle(File.OpenRead(args[1])))
                        File.WriteAllBytes(args[2], bundle.ReadWithoutCache());
                    break;
                case "range":
                    using (var bundle = new Bundle(File.OpenRead(args[1])))
                        File.WriteAllBytes(args[4], bundle.ReadWithoutCache(
                            int.Parse(args[2]), int.Parse(args[3])).AsSpan().ToArray());
                    break;
                case "hash":
                    using (var index = Open(args[1]))
                        Console.WriteLine(JsonSerializer.Serialize(args.Skip(2)
                            .ToDictionary(path => path, path => index.NameHash(path))));
                    break;
                case "records":
                    using (var index = Open(args[1]))
                        Console.WriteLine(JsonSerializer.Serialize(index.Files.ToDictionary(
                            item => item.Key.ToString(), item => new {
                                bundle = item.Value.BundleRecord.Path,
                                offset = item.Value.Offset, size = item.Value.Size
                            })));
                    break;
                case "read":
                    using (var index = Open(args[1]))
                    {
                        if (!index.TryGetFile(args[2], out var record))
                            throw new Exception("Missing synthetic resource: " + args[2]);
                        using var bundle = new DriveBundleFactory(Path.GetDirectoryName(args[1])!)
                            .GetBundle(record.BundleRecord);
                        File.WriteAllBytes(args[3], record.Read(bundle).ToArray());
                    }
                    break;
                case "parse":
                    using (var index = Open(args[1]))
                        Console.WriteLine(index.ParsePaths());
                    break;
                default: throw new Exception("Unknown fixture operation");
            }
            return 0;
        }
        catch (Exception error) { Console.Error.WriteLine(error); return 1; }
    }
}
'''


class BundleTools:
    def __init__(self, dotnet, dll):
        self.dotnet = dotnet
        self.dll = dll
        self.counter = 0

    def run(self, *args, succeeds=True):
        result = subprocess.run(
            [self.dotnet, str(self.dll), *map(str, args)],
            capture_output=True, text=True, encoding="utf-8", timeout=90,
        )
        if succeeds:
            assert result.returncode == 0, result.stdout + result.stderr
        return result

    def convert(self, operation, data, folder, *args):
        self.counter += 1
        source = folder / f"fixture-{self.counter}-input.bin"
        output = folder / f"fixture-{self.counter}-output.bin"
        source.write_bytes(data)
        self.run(operation, source, *args, output)
        return output.read_bytes()

    def pack(self, data, folder, compressor=None):
        options = () if compressor is None else (compressor,)
        return self.convert("pack", data, folder, *options)

    def unpack(self, data, folder):
        return self.convert("unpack", data, folder)

    def read_range(self, data, folder, offset, size):
        return self.convert("range", data, folder, offset, size)

    def records(self, index):
        return json.loads(self.run("records", index).stdout)

    def read(self, index, resource, folder):
        self.counter += 1
        output = folder / f"resource-{self.counter}.bin"
        self.run("read", index, resource, output)
        return output.read_bytes()


@pytest.fixture(scope="module")
def bundle_tools(tmp_path_factory):
    dotnet = shutil.which("dotnet")
    if dotnet is None:
        pytest.skip(".NET SDK required for synthetic bundle fixtures")
    folder = tmp_path_factory.mktemp("bundle-path-fixture-helper")
    references = "".join(
        f'<Reference Include="{name}"><HintPath>'
        + escape(str(LIBRARIES / f"{name}.dll"))
        + "</HintPath><Private>true</Private></Reference>"
        for name in ("LibBundle3", "LibBundledGGPK3", "LibGGPK3", "SystemExtensions")
    )
    project = folder / "BundleFixture.csproj"
    project.write_text(
        '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
        '<OutputType>Exe</OutputType><TargetFramework>net8.0</TargetFramework>'
        '<ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable>'
        '</PropertyGroup><ItemGroup>' + references + "</ItemGroup></Project>",
        encoding="utf-8",
    )
    (folder / "Program.cs").write_text(HELPER_SOURCE, encoding="utf-8")
    output = folder / "compiled"
    built = subprocess.run(
        [dotnet, "build", str(project), "--configuration", "Release", "--output", str(output),
         "--verbosity", "quiet"],
        capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    assert built.returncode == 0, built.stdout + built.stderr
    for name in ("oo2core.dll", "vcruntime140.dll"):
        shutil.copyfile(LIBRARIES / name, output / name)
    return BundleTools(dotnet, output / "BundleFixture.dll")


def split_bundle(data):
    """Inspect documented bundle framing without decoding any compressed chunk."""
    raw_size, = struct.unpack_from("<i", data, 0)
    count, chunk_size = struct.unpack_from("<ii", data, 36)
    assert count > 0 and chunk_size == CHUNK_SIZE
    sizes = struct.unpack_from(f"<{count}i", data, 60)
    position = 60 + 4 * count
    chunks = []
    for size in sizes:
        assert size > 0 and position + size <= len(data)
        chunks.append(data[position:position + size])
        position += size
    compressor, = struct.unpack_from("<i", data, 12)
    return {"raw_size": raw_size, "chunk_size": chunk_size, "chunks": chunks,
            "compressor": compressor,
            "trailer": data[position:], "data_offset": 60 + 4 * count}


def split_index(raw):
    position = 0
    bundle_count, = struct.unpack_from("<i", raw, position)
    position += 4
    bundles = []
    for _ in range(bundle_count):
        size, = struct.unpack_from("<i", raw, position)
        position += 4
        bundles.append(raw[position:position + size].decode("utf-8"))
        position += size + 4
    file_count, = struct.unpack_from("<i", raw, position)
    position += 4
    files = {}
    for _ in range(file_count):
        record = struct.unpack_from("<Qiii", raw, position)
        files[record[0]] = record[1:]
        position += 20
    directory_count, = struct.unpack_from("<i", raw, position)
    position += 4
    directories = {}
    for _ in range(directory_count):
        record = struct.unpack_from("<Qiii", raw, position)
        directories[record[0]] = record[1:]
        position += 20
    return {"bundles": bundles, "files": files, "directories": directories,
            "path_blob": raw[position:]}


def encoded_name(path):
    return struct.pack("<i", 1) + path.encode("utf-8") + b"\0"


def make_game(folder, tools, *, bad_tail, path_compressor=9,
              broken_own_directory=False, corrupt_payload=False):
    game = folder / "合成游戏/Bundles2"
    game.mkdir(parents=True)
    paths = (TARGET, THIRD_PARTY, NEW_FIRST, NEW_SECOND,
             "data/balance/simplified chinese", "metadata/items/toweraugments/poe2price")
    hashes = json.loads(tools.run("hash", EMPTY_INDEX, *paths).stdout)
    old_content = {TARGET: b"synthetic base-item table\n",
                   THIRD_PARTY: b"third-party lookup data to preserve\n"}
    contents = b"".join(old_content.values())
    bundle_file = game / "LibGGPK3/third-party.bundle.bin"
    bundle_file.parent.mkdir()
    payload_bundle = bytearray(tools.pack(contents, folder))
    if corrupt_payload:
        payload_framing = split_bundle(payload_bundle)
        start = payload_framing["data_offset"]
        payload_bundle[start:start + len(payload_framing["chunks"][0])] = \
            b"\0" * len(payload_framing["chunks"][0])
    bundle_file.write_bytes(payload_bundle)
    names = encoded_name(TARGET) + encoded_name(THIRD_PARTY)
    # Valid names occupy the first chunk. Unreferenced synthetic padding spans
    # enough chunks to reproduce index 51; it contains no shipped game bytes.
    pool = bytearray(CHUNK_SIZE * 52 + 173)
    pool[:len(names)] = names
    pool[-173:] = bytes(range(173))
    path_blob = bytearray(tools.pack(pool, folder, compressor=path_compressor))
    framing = split_bundle(path_blob)
    assert len(framing["chunks"]) == 53
    assert framing["compressor"] == path_compressor
    damaged = (51, 52) if bad_tail else (51,)
    offset = framing["data_offset"]
    for number, chunk in enumerate(framing["chunks"]):
        if number in damaged:
            path_blob[offset:offset + len(chunk)] = b"\0" * len(chunk)
        offset += len(chunk)
    path_blob += TRAILER
    bundle_name = b"LibGGPK3/third-party"
    raw = bytearray(struct.pack("<ii", 1, len(bundle_name)) + bundle_name
                    + struct.pack("<ii", len(contents), 2))
    position = 0
    for path, data in old_content.items():
        raw += struct.pack("<Qiii", hashes[path], 0, position, len(data))
        position += len(data)
    raw += struct.pack("<i", 3 if broken_own_directory else 2)
    raw += struct.pack("<Qiii", ROOT_HASH, 0, 0, 0)
    raw += struct.pack("<Qiii", hashes["data/balance/simplified chinese"],
                       0, len(names), len(names))
    if broken_own_directory:
        raw += struct.pack("<Qiii", hashes["metadata/items/toweraugments/poe2price"],
                           CHUNK_SIZE * 51, 64, 64)
    raw += path_blob
    index = game / "_.index.bin"
    index.write_bytes(tools.pack(raw, folder))
    return {"index": index, "hashes": hashes, "contents": old_content,
            "raw": bytes(raw), "pool": bytes(pool), "path_blob": bytes(path_blob),
            "bad_chunks": damaged, "bundle": bundle_file,
            "bundle_sha256": hashlib.sha256(bundle_file.read_bytes()).hexdigest()}


def write_patch(folder, entries):
    patch = folder / "patch.zip"
    with zipfile.ZipFile(patch, "w") as archive:
        for path, data in entries.items():
            archive.writestr(path, data)
    return patch


def invoke_writer(game, patch):
    return subprocess.run(
        [str(EXTRACTOR), "--patch-bundles", str(game["index"]), str(patch)],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
    )


def assert_third_party_preserved(game, tools, folder, before_records):
    after = tools.records(game["index"])
    key = str(game["hashes"][THIRD_PARTY])
    assert after[key] == before_records[key]
    assert tools.read(game["index"], THIRD_PARTY, folder) == game["contents"][THIRD_PARTY]
    assert hashlib.sha256(game["bundle"].read_bytes()).hexdigest() == game["bundle_sha256"]


def assert_original_path_chunks_preserved(game, current_blob, *, allow_padded_tail):
    original = split_bundle(game["path_blob"])
    current = split_bundle(current_blob)
    assert current_blob[12:20] == game["path_blob"][12:20]
    assert current["trailer"] == original["trailer"] == TRAILER
    for number, chunk in enumerate(original["chunks"]):
        if allow_padded_tail and number == len(original["chunks"]) - 1:
            continue
        assert current["chunks"][number] == chunk, f"Original path chunk {number} changed"
    for number in game["bad_chunks"]:
        assert current["chunks"][number] == original["chunks"][number]


def assert_new_directory_readable(game, tools, folder, layout, paths):
    directory_hash = game["hashes"]["metadata/items/toweraugments/poe2price"]
    offset, size, recursive_size = layout["directories"][directory_hash]
    assert size == recursive_size
    old_end = ((len(game["pool"]) + CHUNK_SIZE - 1) // CHUNK_SIZE) * CHUNK_SIZE
    assert offset >= old_end
    actual = tools.read_range(layout["path_blob"], folder, offset, size)
    assert actual == b"".join(encoded_name(path) for path in paths)


def test_fixture_reproduces_bad_directory_chunk_without_corrupting_resources(bundle_tools, tmp_path):
    game = make_game(tmp_path, bundle_tools, bad_tail=True)
    assert tools_parse_failure(bundle_tools, game["index"], 51)
    for path, contents in game["contents"].items():
        assert bundle_tools.read(game["index"], path, tmp_path) == contents
    assert split_index(bundle_tools.unpack(game["index"].read_bytes(), tmp_path))["path_blob"] \
        == game["path_blob"]


def tools_parse_failure(tools, index, chunk):
    result = tools.run("parse", index, succeeds=False)
    assert result.returncode != 0
    assert f"Failed to decompress chunk with index: {chunk}" in result.stderr
    return True


def test_replace_existing_resource_preserves_opaque_directory_blob(bundle_tools, tmp_path):
    game = make_game(tmp_path, bundle_tools, bad_tail=True)
    before_records = bundle_tools.records(game["index"])
    expected = b"updated synthetic price table\n"
    patch = write_patch(tmp_path, {TARGET: expected})
    result = invoke_writer(game, patch)
    assert result.returncode == 0, result.stdout + result.stderr
    layout = split_index(bundle_tools.unpack(game["index"].read_bytes(), tmp_path))
    original = split_index(game["raw"])
    assert layout["path_blob"] == game["path_blob"]
    assert layout["directories"] == original["directories"]
    assert bundle_tools.read(game["index"], TARGET, tmp_path) == expected
    assert_third_party_preserved(game, bundle_tools, tmp_path, before_records)


@pytest.mark.parametrize("bad_tail,path_compressor", [
    (False, 9), (True, 9), (False, 12), (True, 12),
], ids=["mermaid-valid-partial-tail", "mermaid-opaque-tail",
        "hydra-valid-partial-tail", "hydra-opaque-tail"])
def test_append_paths_preserves_old_chunks_and_repeated_updates(
        bundle_tools, tmp_path, bad_tail, path_compressor):
    game = make_game(tmp_path, bundle_tools, bad_tail=bad_tail,
                     path_compressor=path_compressor)
    before_records = bundle_tools.records(game["index"])
    before_layout = split_index(game["raw"])
    first = b"synthetic ritual item\n"
    second = b"synthetic breach item\n"
    patch = write_patch(tmp_path, {NEW_FIRST: first})
    applied = invoke_writer(game, patch)
    assert applied.returncode == 0, applied.stdout + applied.stderr
    first_layout = split_index(bundle_tools.unpack(game["index"].read_bytes(), tmp_path))
    first_records = bundle_tools.records(game["index"])
    for key, record in before_records.items():
        assert first_records[key] == record
    for key, record in before_layout["directories"].items():
        assert first_layout["directories"][key] == record
    assert_original_path_chunks_preserved(game, first_layout["path_blob"], allow_padded_tail=not bad_tail)
    assert_new_directory_readable(game, bundle_tools, tmp_path, first_layout, [NEW_FIRST])
    assert bundle_tools.read(game["index"], NEW_FIRST, tmp_path) == first
    if not bad_tail:
        last_start = CHUNK_SIZE * 52
        assert bundle_tools.read_range(first_layout["path_blob"], tmp_path, last_start, 173) \
            == game["pool"][last_start:]
    assert_third_party_preserved(game, bundle_tools, tmp_path, before_records)

    patch = write_patch(tmp_path, {NEW_SECOND: second})
    applied = invoke_writer(game, patch)
    assert applied.returncode == 0, applied.stdout + applied.stderr
    second_layout = split_index(bundle_tools.unpack(game["index"].read_bytes(), tmp_path))
    assert_new_directory_readable(game, bundle_tools, tmp_path, second_layout, [NEW_FIRST, NEW_SECOND])
    assert_original_path_chunks_preserved(game, second_layout["path_blob"], allow_padded_tail=not bad_tail)
    assert bundle_tools.read(game["index"], NEW_FIRST, tmp_path) == first
    assert bundle_tools.read(game["index"], NEW_SECOND, tmp_path) == second
    assert_third_party_preserved(game, bundle_tools, tmp_path, before_records)

    before_index = game["index"].read_bytes()
    before_bundles = sorted(game["index"].parent.rglob("*.bundle.bin"))
    repeated = invoke_writer(game, patch)
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert "resources already current; no write" in repeated.stdout
    assert game["index"].read_bytes() == before_index
    assert sorted(game["index"].parent.rglob("*.bundle.bin")) == before_bundles


@pytest.mark.parametrize("damage", ["own-directory", "target-payload"])
def test_required_corrupt_data_fails_before_index_or_bundle_commit(bundle_tools, tmp_path, damage):
    game = make_game(tmp_path, bundle_tools, bad_tail=True,
                     broken_own_directory=damage == "own-directory",
                     corrupt_payload=damage == "target-payload")
    before_index = game["index"].read_bytes()
    bundle_dir = game["index"].parent / "LibGGPK3"
    before_bundles = {path.name: path.read_bytes() for path in bundle_dir.glob("*.bundle.bin")}
    path = NEW_SECOND if damage == "own-directory" else TARGET
    patch = write_patch(tmp_path, {path: b"must not be committed\n"})
    result = invoke_writer(game, patch)
    assert result.returncode != 0
    expected_chunk = 51 if damage == "own-directory" else 0
    assert re.search(rf"Failed to decompress (?:last )?chunk with index: {expected_chunk}\b",
                     result.stderr)
    assert game["index"].read_bytes() == before_index
    assert {path.name: path.read_bytes() for path in bundle_dir.glob("*.bundle.bin")} \
        == before_bundles
