using System.Diagnostics;
using System.IO.Compression;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;

internal static class Program
{
    private static readonly byte[] KeySeed = Encoding.UTF8.GetBytes("poe2-price-patch-launcher-v1");

    public static int Main(string[] args)
    {
        Console.OutputEncoding = Encoding.UTF8;
        try
        {
            var exeName = Path.GetFileNameWithoutExtension(Environment.ProcessPath ?? "");
            var mode = GuessModeFromExeName(exeName);
            var scriptArgs = args;
            if (args.Length > 0 && TryParseMode(args[0], out var explicitMode))
            {
                mode = explicitMode;
                scriptArgs = args.Skip(1).ToArray();
            }

            var scriptName = mode switch
            {
                "update" => "update_price_patch.ps1",
                "restore" => "restore_price_patch.ps1",
                _ => throw new InvalidOperationException("无法识别启动模式：" + mode)
            };

            var appDir = AppContext.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            var patchRoot = appDir;
            var tempRoot = Path.Combine(Path.GetTempPath(), "poe2_price_patch_" + Guid.NewGuid().ToString("N"));
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
                startInfo.ArgumentList.Add("-ExecutionPolicy");
                startInfo.ArgumentList.Add("Bypass");
                startInfo.ArgumentList.Add("-File");
                startInfo.ArgumentList.Add(scriptPath);
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
                WaitForEnter();
                return process.ExitCode;
            }
            finally
            {
                TryDeleteDirectory(tempRoot);
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

    private static void PrintCompletion(string mode, int exitCode)
    {
        Console.WriteLine();
        if (exitCode == 0)
        {
            Console.ForegroundColor = ConsoleColor.Green;
            Console.WriteLine(mode == "restore" ? "还原成功。" : "更新成功。");
        }
        else
        {
            Console.ForegroundColor = ConsoleColor.Red;
            Console.WriteLine((mode == "restore" ? "还原失败" : "更新失败") + $"，退出码：{exitCode}");
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

    private static string GuessModeFromExeName(string exeName)
    {
        if (exeName.Contains("restore", StringComparison.OrdinalIgnoreCase) || exeName.Contains("还原", StringComparison.Ordinal))
        {
            return "restore";
        }
        return "update";
    }

    private static bool TryParseMode(string value, out string mode)
    {
        mode = value.Trim().ToLowerInvariant();
        return mode is "update" or "restore";
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

