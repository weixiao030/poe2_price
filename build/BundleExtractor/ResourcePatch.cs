using System.Diagnostics;
using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using LibBundle3;
using LibBundledGGPK3;
using LibGGPK3;
using BIndex = LibBundle3.Index;
using GFile = LibGGPK3.Records.FileRecord;

// New paths require file records AND directory paths. Index.Replace only replaces
// existing records. Stage a separate bundle and index; leave old bundles intact.
static class ResourcePatch
{
    sealed class FreshBundle(Stream stream) : Bundle(stream, (LibBundle3.Records.BundleRecord?)null);
    sealed record Payload(string Path, byte[] Bytes, bool Exists, int Offset);
    const string IndexPath = "Bundles2/_.index.bin";
    static string Hash(byte[] bytes) => Convert.ToHexString(SHA256.HashData(bytes));
    static void Check(bool condition, string message) { if (!condition) throw new InvalidDataException(message); }
    static GFile FileIn(GGPK ggpk, string path)
    {
        Check(ggpk.Root.TryFindNode(path, out var node) && node is GFile, "Missing GGPK file: " + path);
        return (GFile)node!;
    }
    static byte[] Pack(byte[] raw)
    {
        using var stream = new MemoryStream();
        using var bundle = new FreshBundle(stream);
        bundle.Save(raw);
        byte[] result = stream.ToArray();
        Check(Unpack(result).AsSpan().SequenceEqual(raw), "Bundle compression check failed");
        return result;
    }
    static byte[] Unpack(byte[] bytes) { using var b = new Bundle(new MemoryStream(bytes)); return b.ReadWithoutCache(); }
    static void Write(string path, byte[] bytes)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        using var stream = new FileStream(path, FileMode.Create, FileAccess.Write, FileShare.None);
        stream.Write(bytes); stream.Flush(true);
    }
    static bool NewPathAllowed(string path)
    {
        string[] types = ["breach", "expedition", "delirium", "ritual", "irradiated", "overseer", "abyss", "temple"];
        return types.Any(t => path == $"metadata/items/toweraugments/poe2price/{t}.it" ||
            path == $"data/statdescriptions/poe2price/{t}_tablet_stat_descriptions.csd");
    }
    static Dictionary<string, byte[]> ReadZip(string path)
    {
        var files = new Dictionary<string, byte[]>(StringComparer.Ordinal);
        using var zip = ZipFile.OpenRead(path);
        foreach (var entry in zip.Entries)
        {
            var name = entry.FullName.Replace('\\', '/').ToLowerInvariant();
            if (entry.FullName.EndsWith('/') || name is "poe2-restore-manifest.json" or "manifest.json") continue;
            Check(!name.StartsWith('/') && !name.Split('/').Any(s => s is ".." or "." or ""), "Invalid resource path");
            Check(name.StartsWith("data/balance/") && name.EndsWith(".datc64") || NewPathAllowed(name), "Unexpected patch resource: " + name);
            Check(entry.Length > 0 && entry.Length < 64 * 1024 * 1024, "Invalid resource size: " + name);
            using var source = entry.Open(); using var data = new MemoryStream(); source.CopyTo(data);
            Check(files.TryAdd(name, data.ToArray()), "Duplicate patch entry: " + name);
        }
        Check(files.Count > 0, "No patch resources");
        return files;
    }
    static void Verify(BIndex index, Dictionary<string, byte[]> files)
    {
        foreach (var (path, bytes) in files)
        {
            Check(index.TryGetFile(path, out var record), "Missing indexed resource: " + path);
            Check(record!.Read().Span.SequenceEqual(bytes), "Read-back mismatch: " + path);
        }
    }
    static byte[] MakeIndex(byte[] original, BIndex index, List<Payload> files, string stem, int length)
    {
        byte[] raw = Unpack(original);
        using var source = new MemoryStream(raw); using var reader = new BinaryReader(source);
        int bundleCount = reader.ReadInt32();
        for (int i = 0; i < bundleCount; i++) { int len = reader.ReadInt32(); source.Position += len + 4; }
        int endBundles = checked((int)source.Position);
        int fileCount = reader.ReadInt32(); int fileStart = checked((int)source.Position);
        source.Position += checked(fileCount * 20L);
        int dirCount = reader.ReadInt32(); int dirStart = checked((int)source.Position);
        source.Position += checked(dirCount * 20L); int dirsEnd = checked((int)source.Position);
        byte[] directoryRaw = Unpack(raw[dirsEnd..]);
        using var paths = new MemoryStream(); paths.Write(directoryRaw);
        using var pw = new BinaryWriter(paths, Encoding.UTF8, true);
        var directories = new List<(ulong Hash, int Offset, int Size)>();
        var replacedDirectories = new Dictionary<int, (int Offset, int Size)>();
        foreach (var group in files.Where(f => !f.Exists).GroupBy(f => f.Path[..f.Path.LastIndexOf('/')]))
        {
            int begin = checked((int)paths.Position);
            ulong directoryHash = index.NameHash(group.Key);
            int existing = -1;
            for (int i = 0; i < dirCount; i++)
            {
                int at = dirStart + i * 20;
                if (BitConverter.ToUInt64(raw, at) != directoryHash) continue;
                Check(existing == -1, "Ambiguous existing tablet directory");
                existing = i;
                int offset = BitConverter.ToInt32(raw, at + 8);
                int size = BitConverter.ToInt32(raw, at + 12);
                Check(size == BitConverter.ToInt32(raw, at + 16), "Tablet directory has unexpected nested paths");
                paths.Write(directoryRaw.AsSpan(offset, size));
            }
            foreach (var file in group) { pw.Write(1); pw.Write(Encoding.UTF8.GetBytes(file.Path)); pw.Write((byte)0); }
            int combinedSize = checked((int)paths.Position) - begin;
            if (existing >= 0) replacedDirectories.Add(existing, (begin, combinedSize));
            else directories.Add((directoryHash, begin, combinedSize));
        }
        using var output = new MemoryStream(); using var w = new BinaryWriter(output, Encoding.UTF8, true);
        w.Write(bundleCount + 1); w.Write(raw.AsSpan(4, endBundles - 4));
        byte[] bundleName = Encoding.UTF8.GetBytes(stem); w.Write(bundleName.Length); w.Write(bundleName); w.Write(length);
        var byHash = files.ToDictionary(f => index.NameHash(f.Path));
        w.Write(fileCount + files.Count(f => !f.Exists));
        for (int i = 0; i < fileCount; i++)
        {
            int at = fileStart + i * 20; ulong hash = BitConverter.ToUInt64(raw, at);
            if (byHash.TryGetValue(hash, out var file))
            {
                Check(file.Exists, "New path hash collision");
                w.Write(hash); w.Write(bundleCount); w.Write(file.Offset); w.Write(file.Bytes.Length);
            }
            else w.Write(raw.AsSpan(at, 20));
        }
        foreach (var file in files.Where(f => !f.Exists))
        { w.Write(index.NameHash(file.Path)); w.Write(bundleCount); w.Write(file.Offset); w.Write(file.Bytes.Length); }
        w.Write(dirCount + directories.Count);
        for (int i = 0; i < dirCount; i++)
        {
            int at = dirStart + i * 20;
            if (replacedDirectories.TryGetValue(i, out var replacement))
            {
                w.Write(BitConverter.ToUInt64(raw, at));
                w.Write(replacement.Offset); w.Write(replacement.Size); w.Write(replacement.Size);
            }
            else w.Write(raw.AsSpan(at, 20));
        }
        foreach (var d in directories) { w.Write(d.Hash); w.Write(d.Offset); w.Write(d.Size); w.Write(d.Size); }
        w.Write(Pack(paths.ToArray()));
        return Pack(output.ToArray());
    }
    static void EnsureStopped()
    {
        foreach (var name in new[] { "PathOfExile", "PathOfExile_x64", "PathOfExileSteam", "PathOfExile_x64Steam", "Client" })
        {
            var processes = Process.GetProcessesByName(name);
            bool running = processes.Length > 0;
            foreach (var process in processes) process.Dispose();
            Check(!running, "Close game and launcher before writing: " + name);
        }
    }
    public static int Run(string[] args)
    {
        Console.OutputEncoding = Encoding.UTF8;
        try
        {
            Check(args.Length is 3 or 4, "Usage: --patch-ggpk/--patch-bundles <game> <zip> [transaction-directory]; --verify-ggpk-zip/--verify-bundles-zip <game> <zip>");
            bool ggpkMode = args[0].Contains("ggpk");
            bool verifyOnly = args[0].StartsWith("--verify");
            var target = Path.GetFullPath(args[1]);
            var files = ReadZip(args[2]);
            if (!verifyOnly) EnsureStopped();
            var transaction = args.Length == 4 ? Path.GetFullPath(args[3]) : Path.Combine(Path.GetDirectoryName(target)!, ".poe2-price-patch", "resource-transaction");
            byte[] before, after, packed;
            var stem = "LibGGPK3/poe2price-" + Guid.NewGuid().ToString("N");
            string bundleRelative = stem + ".bundle.bin";
            using (var input = File.Open(target, FileMode.Open, FileAccess.Read, FileShare.Read))
            using (var ggpk = ggpkMode ? new BundledGGPK(input, true, false) : null)
            using (var plain = ggpkMode ? null : new BIndex(input, true, false, new DriveBundleFactory(Path.GetDirectoryName(target)!)))
            {
                var index = ggpk?.Index ?? plain!;
                if (verifyOnly) { Verify(index, files); Console.WriteLine($"VERIFIED: {files.Count} resources"); return 0; }
                before = ggpkMode ? FileIn(ggpk!, IndexPath).Read() : File.ReadAllBytes(target);
                var payloads = new List<Payload>(); using var payload = new MemoryStream();
                foreach (var (path, bytes) in files)
                {
                    bool exists = index.TryGetFile(path, out var record);
                    Check(exists || NewPathAllowed(path), "Cannot add arbitrary resource: " + path);
                    if (exists && record!.Read().Span.SequenceEqual(bytes)) continue;
                    payloads.Add(new(path, bytes, exists, checked((int)payload.Length))); payload.Write(bytes);
                }
                if (payloads.Count == 0) { Verify(index, files); Console.WriteLine("VERIFIED: resources already current; no write"); return 0; }
                packed = Pack(payload.ToArray());
                after = MakeIndex(before, index, payloads, stem, checked((int)payload.Length));
                Directory.CreateDirectory(transaction);
                Write(Path.Combine(transaction, "before.index.bin"), before);
                Write(Path.Combine(transaction, "after.index.bin"), after);
                var stage = Path.Combine(transaction, "staged");
                Write(Path.Combine(stage, bundleRelative), packed);
                using var staged = new BIndex(new MemoryStream(after), false, false, new DriveBundleFactory(stage));
                Check(staged.Files.Count == index.Files.Count + payloads.Count(f => !f.Exists), "Unexpected file count");
                int oldPathErrors = index.ParsePaths();
                Check(staged.ParsePaths() == oldPathErrors, "New path decoding errors");
                var changes = payloads.Select(f => index.NameHash(f.Path)).ToHashSet();
                foreach (var (hash, old) in index.Files)
                {
                    Check(staged.Files.TryGetValue(hash, out var current), "Original record lost");
                    if (!changes.Contains(hash))
                        Check(current!.BundleRecord.Path == old.BundleRecord.Path && current.Offset == old.Offset && current.Size == old.Size && current.Path == old.Path, "Unrelated record changed");
                }
                Verify(staged, payloads.ToDictionary(f => f.Path, f => f.Bytes));
                File.WriteAllText(Path.Combine(transaction, "manifest.json"), JsonSerializer.Serialize(new {
                    target, before_sha256 = Hash(before), after_sha256 = Hash(after), bundle = bundleRelative,
                    original_records = index.Files.Count, unchanged_records = index.Files.Count - payloads.Count(f => f.Exists),
                    new_records = payloads.Count(f => !f.Exists), path_errors = oldPathErrors,
                    files = payloads.Select(f => new { path = f.Path, sha256 = Hash(f.Bytes) })
                }, new JsonSerializerOptions { WriteIndented = true }), new UTF8Encoding(false));
                Console.WriteLine($"STAGED: {payloads.Count} resources; {index.Files.Count} original records checked; {payloads.Count(f => !f.Exists)} new paths");
            }
            EnsureStopped();
            if (ggpkMode)
            {
                using var stream = File.Open(target, FileMode.Open, FileAccess.ReadWrite, FileShare.None);
                using var ggpk = new GGPK(stream, true);
                var indexFile = FileIn(ggpk, IndexPath);
                Check(Hash(indexFile.Read()) == Hash(before), "Game changed after staging; refusing stale index");
                Check(!ggpk.Root.TryFindNode("Bundles2/" + bundleRelative, out _), "Bundle already exists");
                try
                {
                    ggpk.Root.FindOrAddFile("Bundles2/" + bundleRelative, out var file);
                    file.Write(packed); Check(Hash(file.Read()) == Hash(packed), "Bundle write failed");
                    indexFile.Write(after); Check(Hash(indexFile.Read()) == Hash(after), "Index write failed");
                    ggpk.Flush(); stream.Flush(true);
                }
                catch { indexFile.Write(before); ggpk.Flush(); stream.Flush(true); throw; }
            }
            else
            {
                string bundlePath = Path.Combine(Path.GetDirectoryName(target)!, bundleRelative);
                Check(!File.Exists(bundlePath), "Bundle already exists");
                // Keep an exclusive lock from precondition through the index commit.
                using var stream = File.Open(target, FileMode.Open, FileAccess.ReadWrite, FileShare.None);
                using var old = new MemoryStream(); stream.CopyTo(old);
                Check(Hash(old.ToArray()) == Hash(before), "Index changed after staging");
                Write(bundlePath, packed);
                Check(Hash(File.ReadAllBytes(bundlePath)) == Hash(packed), "Bundle write failed");
                try { stream.Position = 0; stream.Write(after); stream.SetLength(after.Length); stream.Flush(true); }
                catch { stream.Position = 0; stream.Write(before); stream.SetLength(before.Length); stream.Flush(true); throw; }
            }
            // Full logical read-back is performed again by the caller. A failure
            // returns nonzero and invokes its validated restore flow.
            int verified = Run([ggpkMode ? "--verify-ggpk-zip" : "--verify-bundles-zip", target, args[2]]);
            Check(verified == 0, "Installed resources failed read-back; transaction backup retained");
            Console.WriteLine($"INSTALLED: {files.Count} resources verified");
            return 0;
        }
        catch (Exception ex) { Console.Error.WriteLine(ex); return 1; }
    }
}
