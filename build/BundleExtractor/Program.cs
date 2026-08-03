using LibBundle3;
using LibBundle3.Records;
using LibBundledGGPK3;
using System.Text;

class Program
{
    static int Main(string[] args)
    {
        if (args.Length > 0 && args[0].Equals("--detect-ggpk-game", StringComparison.OrdinalIgnoreCase))
        {
            if (args.Length != 2)
            {
                PrintUsage();
                return 1;
            }

            return DetectGgpkGame(args[1]);
        }

        if (args.Length > 0 && args[0].Equals("--extract-ggpk-list", StringComparison.OrdinalIgnoreCase))
        {
            if (args.Length != 4)
            {
                PrintUsage();
                return 1;
            }

            return ExtractGgpkFiles(args[1], args[2], args[3]);
        }

        if (args.Length > 0 && args[0].Equals("--extract-ggpk", StringComparison.OrdinalIgnoreCase))
        {
            if (args.Length != 4)
            {
                PrintUsage();
                return 1;
            }

            return ExtractGgpkFile(args[1], args[2], args[3]);
        }

        if (args.Length > 0 && args[0].Equals("--detect-game", StringComparison.OrdinalIgnoreCase))
        {
            if (args.Length != 2)
            {
                PrintUsage();
                return 1;
            }

            return DetectGame(args[1]);
        }

        if (args.Length > 0 && args[0].Equals("--extract-list", StringComparison.OrdinalIgnoreCase))
        {
            if (args.Length != 4)
            {
                PrintUsage();
                return 1;
            }

            return ExtractFiles(args[1], args[2], args[3]);
        }

        if (args.Length > 0 && args[0].Equals("--list", StringComparison.OrdinalIgnoreCase))
        {
            if (args.Length < 3)
            {
                PrintUsage();
                return 1;
            }

            string bundlePrefix = args.Length >= 4 ? args[3] : "";
            return ListFiles(args[1], args[2], bundlePrefix);
        }

        if (args.Length < 3)
        {
            PrintUsage();
            return 1;
        }

        return ExtractFile(args[0], args[1], args[2]);
    }

    static void PrintUsage()
    {
        Console.WriteLine("Usage:");
        Console.WriteLine("  BundleExtractor <index.bin> <file_path> <output_path>");
        Console.WriteLine("  BundleExtractor --detect-game <index.bin>");
        Console.WriteLine("  BundleExtractor --detect-ggpk-game <Content.ggpk>");
        Console.WriteLine("  BundleExtractor --list <index.bin> <output_tsv> [bundle_prefix]");
        Console.WriteLine("  BundleExtractor --extract-list <index.bin> <input_list> <output_dir>");
        Console.WriteLine("  BundleExtractor --extract-ggpk <Content.ggpk> <file_path> <output_path>");
        Console.WriteLine("  BundleExtractor --extract-ggpk-list <Content.ggpk> <input_list> <output_dir>");
        Console.WriteLine("  index.bin    : Path to _.index.bin");
        Console.WriteLine("  file_path    : File path in bundle (e.g. data/balance/baseitemtypes.datc64)");
        Console.WriteLine("  output_path  : Output file path");
        Console.WriteLine("  output_tsv   : TSV list containing path, bundle, size, and offset");
        Console.WriteLine("  bundle_prefix: Optional bundle path prefix filter, e.g. LibGGPK3/");
        Console.WriteLine("  input_list   : UTF-8 text file with one exact bundle path per line");
        Console.WriteLine("  output_dir   : Files are written as 000000.bin, 000001.bin, ...");
    }

    static int DetectGame(string indexPath)
    {
        try
        {
            using var loaded = LoadIndex(indexPath, parsePaths: false);
            bool hasPoe1 = loaded.Index.TryGetFile("data/baseitemtypes.datc64", out _);
            bool hasPoe2 = loaded.Index.TryGetFile("data/balance/baseitemtypes.datc64", out _);

            if (hasPoe1 == hasPoe2)
            {
                Console.WriteLine(hasPoe1 ? "ambiguous" : "unknown");
                return 2;
            }

            Console.WriteLine(hasPoe1 ? "poe1" : "poe2");
            return 0;
        }
        catch (Exception ex)
        {
            PrintError(ex);
            return 1;
        }
    }

    static int DetectGgpkGame(string ggpkPath)
    {
        try
        {
            using var loaded = LoadGgpkIndex(ggpkPath);
            return PrintDetectedGame(loaded.Index);
        }
        catch (Exception ex)
        {
            PrintError(ex);
            return 1;
        }
    }

    static int PrintDetectedGame(LibBundle3.Index index)
    {
        bool hasPoe1 = index.TryGetFile("data/baseitemtypes.datc64", out _);
        bool hasPoe2 = index.TryGetFile("data/balance/baseitemtypes.datc64", out _);

        if (hasPoe1 == hasPoe2)
        {
            Console.WriteLine(hasPoe1 ? "ambiguous" : "unknown");
            return 2;
        }

        Console.WriteLine(hasPoe1 ? "poe1" : "poe2");
        return 0;
    }

    static int ExtractGgpkFile(string ggpkPath, string filePath, string outputPath)
    {
        try
        {
            using var loaded = LoadGgpkIndex(ggpkPath);
            if (!loaded.Index.TryGetFile(filePath, out FileRecord? targetFile) || targetFile == null)
            {
                Console.WriteLine($"Error: File not found in Content.ggpk: {filePath}");
                return 1;
            }

            byte[] data = ReadFile(targetFile);
            string outputDir = Path.GetDirectoryName(outputPath) ?? "";
            if (!string.IsNullOrWhiteSpace(outputDir))
            {
                Directory.CreateDirectory(outputDir);
            }
            File.WriteAllBytes(outputPath, data);
            Console.WriteLine($"Successfully extracted to: {outputPath} ({data.Length} bytes)");
            return 0;
        }
        catch (Exception ex)
        {
            PrintError(ex);
            return 1;
        }
    }

    static int ExtractGgpkFiles(string ggpkPath, string inputListPath, string outputDirectory)
    {
        try
        {
            if (!File.Exists(inputListPath))
            {
                throw new FileNotFoundException($"Input list not found: {inputListPath}", inputListPath);
            }

            string[] requestedPaths = File.ReadAllLines(inputListPath, Encoding.UTF8)
                .Select(path => path.Trim())
                .Where(path => !string.IsNullOrWhiteSpace(path))
                .ToArray();
            if (requestedPaths.Length == 0)
            {
                Console.WriteLine("No files requested.");
                return 0;
            }

            string outputRoot = Path.GetFullPath(outputDirectory);
            Directory.CreateDirectory(outputRoot);
            using var loaded = LoadGgpkIndex(ggpkPath);
            int extracted = 0;
            int failed = 0;
            Console.WriteLine($"Extracting {requestedPaths.Length} requested files from Content.ggpk . . .");

            for (int i = 0; i < requestedPaths.Length; i++)
            {
                string filePath = requestedPaths[i];
                string outputPath = Path.Combine(outputRoot, $"{i:D6}.bin");
                if (!loaded.Index.TryGetFile(filePath, out FileRecord? targetFile) || targetFile == null)
                {
                    Console.WriteLine($"Error: File not found in Content.ggpk: {filePath}");
                    failed++;
                    continue;
                }

                try
                {
                    File.WriteAllBytes(outputPath, ReadFile(targetFile));
                    extracted++;
                    Console.WriteLine($"Extracted [{i + 1}/{requestedPaths.Length}]: {filePath}");
                }
                catch (Exception ex)
                {
                    Console.WriteLine($"Error: Failed to extract {filePath}: {ex.GetType().Name}: {ex.Message}");
                    failed++;
                }
            }

            Console.WriteLine($"GGPK batch extraction complete. Extracted: {extracted}, failed: {failed}");
            return failed == 0 ? 0 : 2;
        }
        catch (Exception ex)
        {
            PrintError(ex);
            return 1;
        }
    }

    static byte[] ReadFile(FileRecord targetFile)
    {
        if (!targetFile.BundleRecord.TryGetBundle(out Bundle? bundle) || bundle == null)
        {
            throw new InvalidOperationException($"Unable to open bundle: {targetFile.BundleRecord.Path}");
        }
        using (bundle)
        {
            return targetFile.Read(bundle).ToArray();
        }
    }

    static BundledGGPK LoadGgpkIndex(string ggpkPath)
    {
        if (!File.Exists(ggpkPath))
        {
            throw new FileNotFoundException($"Content.ggpk not found: {ggpkPath}", ggpkPath);
        }

        Console.WriteLine($"Loading Content.ggpk: {ggpkPath}");
        var loaded = new BundledGGPK(ggpkPath, false);
        Console.WriteLine($"Index loaded. Files count: {loaded.Index.Files.Count}");
        return loaded;
    }

    static int ListFiles(string indexPath, string outputPath, string bundlePrefix)
    {
        try
        {
            using var loaded = LoadIndex(indexPath);
            Directory.CreateDirectory(Path.GetDirectoryName(outputPath) ?? ".");

            using var writer = new StreamWriter(outputPath, false, new UTF8Encoding(false));
            writer.WriteLine("path\tbundle\tsize\toffset");
            int written = 0;
            foreach (var file in loaded.Index.Files.Values.OrderBy(file => file.Path ?? ""))
            {
                if (string.IsNullOrWhiteSpace(file.Path))
                {
                    continue;
                }
                if (!string.IsNullOrWhiteSpace(bundlePrefix) &&
                    !file.BundleRecord.Path.StartsWith(bundlePrefix, StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }

                writer.WriteLine(
                    $"{CleanTsv(file.Path)}\t{CleanTsv(file.BundleRecord.Path)}\t{file.Size}\t{file.Offset}"
                );
                written++;
            }

            Console.WriteLine($"Listed {written} files to: {outputPath}");
            return 0;
        }
        catch (Exception ex)
        {
            PrintError(ex);
            return 1;
        }
    }

    static int ExtractFile(string indexPath, string filePath, string outputPath)
    {
        try
        {
            using var loaded = LoadIndex(indexPath, parsePaths: false);

            loaded.Index.TryGetFile(filePath, out FileRecord? targetFile);

            if (targetFile == null)
            {
                // Keep the old fuzzy fallback for diagnostics, but only pay the full
                // multi-million-path parsing cost when the exact hash lookup failed.
                loaded.Index.ParsePaths();
                var similarFiles = loaded.Index.Files.Values
                    .Where(file => IsSafeFuzzyPathMatch(file.Path, filePath))
                    .Take(6)
                    .ToArray();
                if (similarFiles.Length == 1)
                {
                    Console.WriteLine($"Found unique similar file: {similarFiles[0].Path}");
                    targetFile = similarFiles[0];
                }
                else if (similarFiles.Length > 1)
                {
                    Console.WriteLine($"Error: File path is ambiguous: {filePath}");
                    foreach (var file in similarFiles.Take(5))
                        Console.WriteLine($"  Candidate: {file.Path}");
                    return 1;
                }
            }

            if (targetFile == null)
            {
                Console.WriteLine($"Error: File not found in bundle: {filePath}");
                return 1;
            }

            Console.WriteLine($"Found file: {targetFile.Path ?? filePath}");
            Console.WriteLine($"  Size: {targetFile.Size} bytes");
            Console.WriteLine($"  Offset: {targetFile.Offset}");
            Console.WriteLine($"  Bundle: {targetFile.BundleRecord.Path}");

            Console.WriteLine("Reading file content...");
            byte[] data;
            using (var bundle = loaded.Factory.GetBundle(targetFile.BundleRecord))
            {
                data = targetFile.Read(bundle).ToArray();
            }

            string outputDir = Path.GetDirectoryName(outputPath) ?? "";
            if (!string.IsNullOrEmpty(outputDir))
            {
                Directory.CreateDirectory(outputDir);
            }

            File.WriteAllBytes(outputPath, data);
            Console.WriteLine($"Successfully extracted to: {outputPath} ({data.Length} bytes)");

            return 0;
        }
        catch (Exception ex)
        {
            PrintError(ex);
            return 1;
        }
    }

    static bool IsSafeFuzzyPathMatch(string? candidate, string requested)
    {
        if (string.IsNullOrWhiteSpace(candidate) || string.IsNullOrWhiteSpace(requested))
            return false;

        static string Normalize(string path) => path.Replace('\\', '/').Trim('/');
        string normalizedCandidate = Normalize(candidate);
        string normalizedRequested = Normalize(requested);
        return normalizedCandidate.Equals(normalizedRequested, StringComparison.OrdinalIgnoreCase)
            || normalizedCandidate.EndsWith('/' + normalizedRequested, StringComparison.OrdinalIgnoreCase)
            || normalizedRequested.EndsWith('/' + normalizedCandidate, StringComparison.OrdinalIgnoreCase);
    }

    static int ExtractFiles(string indexPath, string inputListPath, string outputDirectory)
    {
        try
        {
            if (!File.Exists(inputListPath))
            {
                throw new FileNotFoundException($"Input list not found: {inputListPath}", inputListPath);
            }

            string[] requestedPaths = File.ReadAllLines(inputListPath, Encoding.UTF8)
                .Select(path => path.Trim())
                .Where(path => !string.IsNullOrWhiteSpace(path))
                .ToArray();
            if (requestedPaths.Length == 0)
            {
                Console.WriteLine("No files requested.");
                return 0;
            }

            string outputRoot = Path.GetFullPath(outputDirectory);
            Directory.CreateDirectory(outputRoot);

            // Exact path lookup uses the index hash table and does not need the expensive
            // ParsePaths pass. This is intentionally one process/index load for the whole
            // request list; launching once per file takes minutes on multi-million-file indexes.
            using var loaded = LoadIndex(indexPath, parsePaths: false);
            int extracted = 0;
            int failed = 0;
            Console.WriteLine($"Extracting {requestedPaths.Length} requested files . . .");

            for (int i = 0; i < requestedPaths.Length; i++)
            {
                string filePath = requestedPaths[i];
                string outputPath = Path.Combine(outputRoot, $"{i:D6}.bin");
                if (!loaded.Index.TryGetFile(filePath, out FileRecord? targetFile))
                {
                    Console.WriteLine($"Error: File not found in bundle: {filePath}");
                    failed++;
                    continue;
                }

                try
                {
                    byte[] data;
                    using (var bundle = loaded.Factory.GetBundle(targetFile.BundleRecord))
                    {
                        data = targetFile.Read(bundle).ToArray();
                    }

                    File.WriteAllBytes(outputPath, data);
                    extracted++;
                    Console.WriteLine($"Extracted [{i + 1}/{requestedPaths.Length}]: {filePath}");
                }
                catch (Exception ex)
                {
                    Console.WriteLine($"Error: Failed to extract {filePath}: {ex.GetType().Name}: {ex.Message}");
                    failed++;
                }
            }

            Console.WriteLine($"Batch extraction complete. Extracted: {extracted}, failed: {failed}");
            return failed == 0 ? 0 : 2;
        }
        catch (Exception ex)
        {
            PrintError(ex);
            return 1;
        }
    }

    static LoadedIndex LoadIndex(string indexPath, bool parsePaths = true)
    {
        if (!File.Exists(indexPath))
        {
            throw new FileNotFoundException($"Index file not found: {indexPath}", indexPath);
        }

        string bundles2Dir = Path.GetDirectoryName(indexPath) ?? "";
        if (string.IsNullOrEmpty(bundles2Dir))
        {
            bundles2Dir = Environment.CurrentDirectory;
        }

        Console.WriteLine($"Loading index: {indexPath}");
        Console.WriteLine($"Bundles2 dir: {bundles2Dir}");

        var factory = new DriveBundleFactory(bundles2Dir);
        var index = new LibBundle3.Index(indexPath, false, factory);

        if (parsePaths)
        {
            int failedPaths = index.ParsePaths();
            if (failedPaths > 0)
            {
                Console.WriteLine($"Warning: {failedPaths} files failed to parse paths (ignored)");
            }
        }

        Console.WriteLine($"Index loaded. Files count: {index.Files.Count}");
        return new LoadedIndex(factory, index);
    }

    static string CleanTsv(string value)
    {
        return value.Replace('\t', ' ').Replace('\r', ' ').Replace('\n', ' ');
    }

    static void PrintError(Exception ex)
    {
        Console.WriteLine($"Error: {ex.GetType().Name}: {ex.Message}");
        Console.WriteLine(ex.StackTrace);
    }

    sealed class LoadedIndex : IDisposable
    {
        public LoadedIndex(DriveBundleFactory factory, LibBundle3.Index index)
        {
            Factory = factory;
            Index = index;
        }

        public DriveBundleFactory Factory { get; }

        public LibBundle3.Index Index { get; }

        public void Dispose()
        {
            Index.Dispose();
        }
    }
}
