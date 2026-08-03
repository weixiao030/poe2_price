using System.Diagnostics;
using System.IO.Compression;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

internal static class Program
{
    private static readonly byte[] KeySeed = Encoding.UTF8.GetBytes("poe2-price-patch-launcher-v1");

    public static int Main(string[] args)
    {
        Console.OutputEncoding = Encoding.UTF8;
        try
        {
            var mode = "select";
            var scriptArgs = args;
            if (args.Length > 0 && TryParseMode(args[0], out var explicitMode))
            {
                mode = explicitMode;
                scriptArgs = args.Skip(1).ToArray();
            }

            if (mode is not ("select" or "update" or "restore"))
            {
                throw new InvalidOperationException("无法识别启动模式：" + mode);
            }

            var appDir = Path.TrimEndingDirectorySeparator(Path.GetFullPath(AppContext.BaseDirectory));
            var patchRoot = appDir;
            const string scriptName = "price_patch_gui.ps1";

            // The GUI does not know the final game directory until the user
            // confirms it.  Only take the early launcher lock when an explicit
            // directory or a previously confirmed game directory is available;
            // the PowerShell entrypoint takes the authoritative game-scoped lock
            // after selection.
            var mutexScopeRoot = ResolveMutexScopeRoot(patchRoot, scriptArgs);
            Mutex? instanceMutex = null;
            var instanceMutexHeld = false;
            if (!string.IsNullOrWhiteSpace(mutexScopeRoot))
            {
                instanceMutex = new Mutex(false, CreateInstanceMutexName(mutexScopeRoot));
                if (!TryTakeInstanceMutex(instanceMutex))
                {
                    Console.ForegroundColor = ConsoleColor.Yellow;
                    Console.WriteLine("同一游戏目录的物价补丁正在运行，请等待当前更新或还原完成后再试。");
                    Console.ResetColor();
                    instanceMutex.Dispose();
                    WaitForEnter();
                    return 2;
                }
                instanceMutexHeld = true;
            }

            var tempRoot = Path.Combine(Path.GetTempPath(), "poe_price_patch_" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(tempRoot);
            try
            {
                ExtractPayload(tempRoot);
                var scriptPath = Path.Combine(tempRoot, scriptName);
                if (!File.Exists(scriptPath))
                {
                    throw new FileNotFoundException("内置脚本不存在。", scriptPath);
                }

                var startInfo = new ProcessStartInfo
                {
                    FileName = "powershell.exe",
                    UseShellExecute = false,
                    CreateNoWindow = false,
                    WorkingDirectory = patchRoot
                };
                startInfo.ArgumentList.Add("-NoProfile");
                startInfo.ArgumentList.Add("-STA");
                startInfo.ArgumentList.Add("-ExecutionPolicy");
                startInfo.ArgumentList.Add("Bypass");
                startInfo.ArgumentList.Add("-File");
                startInfo.ArgumentList.Add(scriptPath);
                startInfo.ArgumentList.Add("-Mode");
                startInfo.ArgumentList.Add(mode);
                foreach (var scriptArg in scriptArgs)
                {
                    startInfo.ArgumentList.Add(scriptArg);
                }

                startInfo.Environment["POE2_PATCH_ROOT"] = patchRoot;
                startInfo.Environment["POE2_PATCH_RELEASE"] = "1";

                using var process = Process.Start(startInfo);
                if (process == null)
                {
                    throw new InvalidOperationException("无法启动 powershell.exe。");
                }
                process.WaitForExit();
                PrintCompletion(mode, process.ExitCode);
                if (instanceMutexHeld)
                {
                    instanceMutex!.ReleaseMutex();
                    instanceMutexHeld = false;
                }
                WaitForEnter();
                return process.ExitCode;
            }
            finally
            {
                TryDeleteDirectory(tempRoot);
                if (instanceMutexHeld && instanceMutex is not null)
                {
                    try { instanceMutex.ReleaseMutex(); } catch { }
                    instanceMutexHeld = false;
                }
                instanceMutex?.Dispose();
            }
        }
        catch (Exception ex)
        {
            Console.ForegroundColor = ConsoleColor.Red;
            Console.WriteLine("启动失败: " + ex.Message);
            Console.ResetColor();
            WaitForEnter();
            return 1;
        }
    }

    private static string CreateInstanceMutexName(string gameDirectory)
    {
        var normalized = Path.TrimEndingDirectorySeparator(Path.GetFullPath(gameDirectory))
            .ToUpperInvariant();
        var digest = SHA256.HashData(Encoding.UTF8.GetBytes(normalized));
        // Keep the launcher-instance guard separate from the authoritative
        // game-directory mutex acquired by the PowerShell worker. Otherwise
        // the worker would reject the launcher that started it.
        return "Local\\Poe2PricePatch-Launcher-Game-" + Convert.ToHexString(digest);
    }

    private static string? ResolveMutexScopeRoot(string patchRoot, string[] scriptArgs)
    {
        for (var i = 0; i < scriptArgs.Length; i++)
        {
            foreach (var option in new[] { "-Poe1Dir", "-Poe2Dir" })
            {
                if (string.Equals(scriptArgs[i], option, StringComparison.OrdinalIgnoreCase) &&
                    i + 1 < scriptArgs.Length && !string.IsNullOrWhiteSpace(scriptArgs[i + 1]))
                {
                    return Path.GetFullPath(scriptArgs[i + 1], patchRoot);
                }

                var prefix = option + "=";
                if (scriptArgs[i].StartsWith(prefix, StringComparison.OrdinalIgnoreCase) &&
                    scriptArgs[i].Length > prefix.Length)
                {
                    return Path.GetFullPath(scriptArgs[i][prefix.Length..], patchRoot);
                }
            }
        }

        var patchParent = Directory.GetParent(patchRoot)?.FullName;
        if (!string.IsNullOrWhiteSpace(patchParent) && IsPoe2GameDirectory(patchParent))
        {
            return patchParent;
        }

        return TryReadSavedGameDirectory();
    }

    private static string? TryReadSavedGameDirectory()
    {
        try
        {
            var localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            if (string.IsNullOrWhiteSpace(localAppData))
            {
                return null;
            }

            foreach (var settingsPath in new[]
                     {
                         Path.Combine(localAppData, "PoePricePatch", "settings.json"),
                         Path.Combine(localAppData, "Poe2PricePatch", "settings.json")
                     })
            {
                if (!File.Exists(settingsPath))
                {
                    continue;
                }

                using var settings = JsonDocument.Parse(File.ReadAllText(settingsPath));
                var root = settings.RootElement;
                var candidates = new List<string>();
                if (root.TryGetProperty("last_game_version", out var lastVersion) &&
                    lastVersion.ValueKind == JsonValueKind.String)
                {
                    var property = string.Equals(lastVersion.GetString(), "poe1", StringComparison.OrdinalIgnoreCase)
                        ? "poe1_game_directory"
                        : "poe2_game_directory";
                    candidates.Add(property);
                }
                candidates.Add("poe2_game_directory");
                candidates.Add("poe1_game_directory");
                candidates.Add("game_directory"); // v0.4.x settings compatibility

                foreach (var property in candidates.Distinct(StringComparer.OrdinalIgnoreCase))
                {
                    if (!root.TryGetProperty(property, out var value) || value.ValueKind != JsonValueKind.String)
                    {
                        continue;
                    }
                    var path = value.GetString();
                    if (!string.IsNullOrWhiteSpace(path))
                    {
                        var resolved = Path.TrimEndingDirectorySeparator(Path.GetFullPath(path));
                        if (IsPoe2GameDirectory(resolved))
                        {
                            return resolved;
                        }
                    }
                }
            }
        }
        catch
        {
            // An optional preference file must never block the GUI.
        }
        return null;
    }

    private static bool IsPoe2GameDirectory(string path)
    {
        return Directory.Exists(path) &&
            (File.Exists(Path.Combine(path, "Content.ggpk")) ||
             File.Exists(Path.Combine(path, "Bundles2", "_.index.bin")));
    }

    private static bool TryTakeInstanceMutex(Mutex instanceMutex)
    {
        try
        {
            return instanceMutex.WaitOne(0);
        }
        catch (AbandonedMutexException)
        {
            return true;
        }
    }

    private static void PrintCompletion(string mode, int exitCode)
    {
        Console.WriteLine();
        if (exitCode == 0)
        {
            Console.ForegroundColor = ConsoleColor.Green;
            Console.WriteLine(mode switch
            {
                "restore" => "还原成功。",
                "update" => "更新成功。",
                _ => "操作完成。"
            });
        }
        else
        {
            Console.ForegroundColor = ConsoleColor.Red;
            Console.WriteLine((mode switch
            {
                "restore" => "还原失败",
                "update" => "更新失败",
                _ => "操作失败"
            }) + $"，退出码：{exitCode}");
        }
        Console.ResetColor();
    }

    private static void WaitForEnter()
    {
        Console.WriteLine();
        Console.Write("按回车键关闭窗口 . . .");
        Console.ReadLine();
    }
    private static void ExtractPayload(string targetDir)
    {
        using var resource = Assembly.GetExecutingAssembly().GetManifestResourceStream("payload.enc");
        if (resource == null)
        {
            throw new InvalidOperationException("缺少内置运行文件。");
        }

        using var encrypted = new MemoryStream();
        resource.CopyTo(encrypted);
        var zipBytes = Decrypt(encrypted.ToArray());
        using var zipStream = new MemoryStream(zipBytes);
        using var archive = new ZipArchive(zipStream, ZipArchiveMode.Read);
        archive.ExtractToDirectory(targetDir, overwriteFiles: true);
    }

    private static byte[] Decrypt(byte[] data)
    {
        if (data.Length < 28)
        {
            throw new InvalidOperationException("内置运行文件无效。");
        }

        var salt = data.AsSpan(0, 16).ToArray();
        var nonce = data.AsSpan(16, 12).ToArray();
        var cipherAndTag = data.AsSpan(28).ToArray();
        if (cipherAndTag.Length < 16)
        {
            throw new InvalidOperationException("内置运行文件无效。");
        }

        var cipher = cipherAndTag.AsSpan(0, cipherAndTag.Length - 16).ToArray();
        var tag = cipherAndTag.AsSpan(cipherAndTag.Length - 16, 16).ToArray();
        using var derive = new Rfc2898DeriveBytes(KeySeed, salt, 120_000, HashAlgorithmName.SHA256);
        var key = derive.GetBytes(32);
        var plain = new byte[cipher.Length];
        using var aes = new AesGcm(key, 16);
        aes.Decrypt(nonce, cipher, tag, plain);
        return plain;
    }

    private static bool TryParseMode(string value, out string mode)
    {
        mode = value.Trim().ToLowerInvariant();
        return mode is "select" or "update" or "restore";
    }

    private static void TryDeleteDirectory(string path)
    {
        try
        {
            if (Directory.Exists(path))
            {
                Directory.Delete(path, recursive: true);
            }
        }
        catch
        {
            // Best effort cleanup only.
        }
    }
}

