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
    static byte[] Pack(byte[] raw, Oodle.Compressor compressor = Oodle.Compressor.Invalid)
    {
        using var stream = new MemoryStream();
        using var bundle = new FreshBundle(stream);
        bundle.Save(raw, compressor);
        byte[] result = stream.ToArray();
        Check(Unpack(result).AsSpan().SequenceEqual(raw), "Bundle compression check failed");
        return result;
    }
    static byte[] Unpack(byte[] bytes) { using var b = new Bundle(new MemoryStream(bytes)); return b.ReadWithoutCache(); }
    // Some third-party indexes deliberately leave most path chunks unreadable.
    // File lookup uses hashes and does not need those chunks. Preserve them and
    // read only our own directories when adding another tablet resource.
    sealed class PackedPaths
    {
        readonly byte[] bytes;
        readonly int dataStart;
        readonly int dataEnd;
        readonly int[] sizes;
        public int Length { get; }
        public int ChunkSize { get; }
        public int AlignedLength => checked(sizes.Length * ChunkSize);
        public PackedPaths(byte[] bytes)
        {
            this.bytes = bytes;
            Check(bytes.Length >= 60, "Truncated path bundle header");
            Length = BitConverter.ToInt32(bytes, 0);
            int compressed = BitConverter.ToInt32(bytes, 4);
            int count = BitConverter.ToInt32(bytes, 36);
            ChunkSize = BitConverter.ToInt32(bytes, 40);
            Check(Length >= 0 && compressed >= 0 && count >= 0 && ChunkSize > 0, "Invalid path bundle header");
            Check(BitConverter.ToInt64(bytes, 20) == Length && BitConverter.ToInt64(bytes, 28) == compressed,
                "Inconsistent path bundle sizes");
            dataStart = checked(60 + count * 4);
            Check(BitConverter.ToInt32(bytes, 8) == dataStart - 12 && dataStart <= bytes.Length,
                "Unsupported path bundle header");
            Check(count == (Length + (long)ChunkSize - 1) / ChunkSize, "Invalid path chunk count");
            sizes = new int[count];
            long total = 0;
            for (int i = 0; i < count; i++)
            {
                sizes[i] = BitConverter.ToInt32(bytes, 60 + i * 4);
                Check(sizes[i] > 0, "Invalid compressed path chunk size");
                total += sizes[i];
            }
            Check(total == compressed && dataStart + total <= bytes.Length, "Truncated path bundle");
            dataEnd = checked(dataStart + compressed);
        }
        public byte[] Read(int offset, int length)
        {
            Check(offset >= 0 && length >= 0 && offset + (long)length <= Length, "Path directory out of bounds");
            if (length == 0) return [];
            using var bundle = new Bundle(new MemoryStream(bytes));
            return bundle.ReadWithoutCache(offset, length).ToArray();
        }
        public byte[] Append(byte[] addition)
        {
            Check(addition.Length > 0, "Empty path addition");
            var compressor = (Oodle.Compressor)BitConverter.ToInt32(bytes, 12);
            var appended = new PackedPaths(Pack(addition, compressor));
            Check(appended.ChunkSize == ChunkSize, "Unsupported path chunk size for append");
            Check(bytes.AsSpan(12, 8).SequenceEqual(appended.bytes.AsSpan(12, 8)), "Unsupported path bundle compressor for append");
            byte[]? paddedTail = null;
            if (sizes.Length > 0 && Length % ChunkSize != 0)
            {
                byte[]? tail;
                try { tail = Read((sizes.Length - 1) * ChunkSize, Length % ChunkSize); }
                catch (Exception ex) when (ex.Message.StartsWith("Failed to decompress chunk with index:", StringComparison.Ordinal) ||
                    ex.Message.StartsWith("Failed to decompress last chunk with index:", StringComparison.Ordinal))
                {
                    // The original last chunk was already unreadable. Its bytes
                    // and every original directory range remain unchanged. Only
                    // the unused logical tail is extended to the next boundary.
                    tail = null;
                }
                if (tail != null)
                {
                    Array.Resize(ref tail, ChunkSize);
                    var padded = new PackedPaths(Pack(tail, compressor));
                    Check(padded.ChunkSize == ChunkSize && padded.sizes.Length == 1, "Unexpected padded path chunk");
                    paddedTail = padded.bytes[padded.dataStart..padded.dataEnd];
                }
            }
            int keptLength = dataEnd - dataStart - (paddedTail == null ? 0 : sizes[^1]);
            int compressedLength = checked(keptLength + (paddedTail?.Length ?? 0) + appended.dataEnd - appended.dataStart);
            int count = checked(sizes.Length + appended.sizes.Length);
            int length = checked(AlignedLength + addition.Length);
            using var result = new MemoryStream();
            using var writer = new BinaryWriter(result, Encoding.UTF8, true);
            byte[] header = bytes[..60];
            BitConverter.GetBytes(length).CopyTo(header, 0);
            BitConverter.GetBytes(compressedLength).CopyTo(header, 4);
            BitConverter.GetBytes(checked(48 + count * 4)).CopyTo(header, 8);
            BitConverter.GetBytes((long)length).CopyTo(header, 20);
            BitConverter.GetBytes((long)compressedLength).CopyTo(header, 28);
            BitConverter.GetBytes(count).CopyTo(header, 36);
            writer.Write(header);
            for (int i = 0; i < sizes.Length; i++) writer.Write(i == sizes.Length - 1 && paddedTail != null ? paddedTail.Length : sizes[i]);
            foreach (int size in appended.sizes) writer.Write(size);
            writer.Write(bytes.AsSpan(dataStart, keptLength));
            if (paddedTail != null) writer.Write(paddedTail);
            writer.Write(appended.bytes.AsSpan(appended.dataStart, appended.dataEnd - appended.dataStart));
            writer.Write(bytes.AsSpan(dataEnd)); // Preserve third-party trailing data too.
            byte[] output = result.ToArray();
            Check(new PackedPaths(output).Read(AlignedLength, addition.Length).AsSpan().SequenceEqual(addition),
                "Appended paths failed read-back");
            return output;
        }
    }
    static void VerifyOwnDirectory(byte[] bytes, string directory, BIndex index)
    {
        using var stream = new MemoryStream(bytes);
        using var reader = new BinaryReader(stream, Encoding.UTF8);
        var seen = new HashSet<ulong>();
        while (stream.Position < stream.Length)
        {
            Check(stream.Length - stream.Position >= 5 && reader.ReadInt32() == 1, "Unsupported tablet directory encoding");
            int start = checked((int)stream.Position);
            int end = Array.IndexOf(bytes, (byte)0, start);
            Check(end >= start, "Unterminated tablet path");
            string path = new UTF8Encoding(false, true).GetString(bytes, start, end - start);
            Check(path.StartsWith(directory + "/", StringComparison.Ordinal) && NewPathAllowed(path), "Unexpected existing tablet path");
            Check(seen.Add(index.NameHash(path)) && index.TryGetFile(path, out _), "Invalid existing tablet directory entry");
            stream.Position = end + 1;
        }
    }
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
        byte[] originalPaths = raw[dirsEnd..];
        PackedPaths? originalPathBundle = files.Any(f => !f.Exists) ? new PackedPaths(originalPaths) : null;
        using var paths = new MemoryStream();
        using var pw = new BinaryWriter(paths, Encoding.UTF8, true);
        var directories = new List<(ulong Hash, int Offset, int Size)>();
        var replacedDirectories = new Dictionary<int, (int Offset, int Size)>();
        foreach (var group in files.Where(f => !f.Exists).GroupBy(f => f.Path[..f.Path.LastIndexOf('/')]))
        {
            int begin = checked(originalPathBundle!.AlignedLength + (int)paths.Position);
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
                byte[] previous = originalPathBundle.Read(offset, size);
                VerifyOwnDirectory(previous, group.Key, index);
                paths.Write(previous);
            }
            foreach (var file in group) { pw.Write(1); pw.Write(Encoding.UTF8.GetBytes(file.Path)); pw.Write((byte)0); }
            int combinedSize = checked(originalPathBundle.AlignedLength + (int)paths.Position - begin);
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
        byte[] pathBundle = originalPathBundle == null ? originalPaths : originalPathBundle.Append(paths.ToArray());
        if (originalPathBundle != null)
        {
            var updatedPaths = new PackedPaths(pathBundle);
            foreach (var d in directories)
                Check(updatedPaths.Read(d.Offset, d.Size).AsSpan().SequenceEqual(paths.GetBuffer().AsSpan(d.Offset - originalPathBundle.AlignedLength, d.Size)), "New directory changed");
            foreach (var d in replacedDirectories.Values)
                Check(updatedPaths.Read(d.Offset, d.Size).AsSpan().SequenceEqual(paths.GetBuffer().AsSpan(d.Offset - originalPathBundle.AlignedLength, d.Size)), "Updated directory changed");
        }
        w.Write(pathBundle);
        return Pack(output.ToArray());
    }
    static bool IsProcessRunning(Process process)
    {
        // Windows can retain an exited process in an enumeration while another
        // application still holds its handle. Only a confirmed exit is ignored.
        try { return !process.HasExited; }
        catch (System.ComponentModel.Win32Exception) { return true; }
        catch (InvalidOperationException) { return true; }
    }
    static bool IsGameLauncher(Process process, string gameRoot)
    {
        try
        {
            var executable = process.MainModule?.FileName;
            return !string.IsNullOrWhiteSpace(executable) &&
                Path.GetFullPath(executable).StartsWith(gameRoot, StringComparison.OrdinalIgnoreCase) &&
                IsProcessRunning(process); // It may exit while its path is read.
        }
        catch (System.ComponentModel.Win32Exception) { return false; }
        catch (InvalidOperationException) { return false; } // Process exited during inspection.
        // Client is a generic name: an unreadable path is not proof of a POE
        // launcher. Exclusive game-file access below still rejects locked files.
    }
    static void EnsureStopped(string gameRoot)
    {
        foreach (var name in new[] { "PathOfExile", "PathOfExile_x64", "PathOfExileSteam", "PathOfExile_x64Steam", "Client" })
        {
            var processes = Process.GetProcessesByName(name);
            bool running;
            try { running = processes.Any(process => IsProcessRunning(process) &&
                (name != "Client" || IsGameLauncher(process, gameRoot))); }
            finally { foreach (var process in processes) process.Dispose(); }
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
            // GGPK lives in the game root; the loose index lives in Bundles2.
            var gameDirectory = Path.GetDirectoryName(target)!;
            if (!ggpkMode) gameDirectory = Path.GetDirectoryName(gameDirectory) ?? gameDirectory;
            var gameRoot = gameDirectory.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar) + Path.DirectorySeparatorChar;
            var files = ReadZip(args[2]);
            if (!verifyOnly) EnsureStopped(gameRoot);
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
                var changes = payloads.Select(f => index.NameHash(f.Path)).ToHashSet();
                foreach (var (hash, old) in index.Files)
                {
                    Check(staged.Files.TryGetValue(hash, out var current), "Original record lost");
                    if (!changes.Contains(hash))
                        Check(current!.BundleRecord.Path == old.BundleRecord.Path && current.Offset == old.Offset && current.Size == old.Size, "Unrelated record changed");
                }
                Verify(staged, payloads.ToDictionary(f => f.Path, f => f.Bytes));
                File.WriteAllText(Path.Combine(transaction, "manifest.json"), JsonSerializer.Serialize(new {
                    target, before_sha256 = Hash(before), after_sha256 = Hash(after), bundle = bundleRelative,
                    original_records = index.Files.Count, unchanged_records = index.Files.Count - payloads.Count(f => f.Exists),
                    new_records = payloads.Count(f => !f.Exists), path_validation = "preserved-original-chunks-and-verified-additions",
                    files = payloads.Select(f => new { path = f.Path, sha256 = Hash(f.Bytes) })
                }, new JsonSerializerOptions { WriteIndented = true }), new UTF8Encoding(false));
                Console.WriteLine($"STAGED: {payloads.Count} resources; {index.Files.Count} original records checked; {payloads.Count(f => !f.Exists)} new paths");
            }
            EnsureStopped(gameRoot);
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
