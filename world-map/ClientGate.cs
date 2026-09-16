using System.Text;

namespace Poe2Overlay;

public static class ClientGate
{
    public static readonly string[] ExecutableNames =
        ["PathOfExile.exe", "PathOfExile_x64.exe", "PathOfExileSteam.exe", "PathOfExile_x64Steam.exe"];
    static readonly string[] ForbiddenMarkers =
        ["wegame.ini", "rail_api64.dll", "rail_files", "WeGameLauncher", "TCLS", "AntiCheatExpert", "QQOpenSDK.dll"];

    public static string ValidateDirectory(string directory)
    {
        if (!Path.IsPathFullyQualified(directory) || directory.StartsWith(@"\\"))
            throw new InvalidOperationException("请选择本机 POE2 国际服目录");
        var root = Path.TrimEndingDirectorySeparator(Path.GetFullPath(directory));
        if (!Directory.Exists(root)) throw new InvalidOperationException("游戏目录不存在");
        for (var info = new DirectoryInfo(root); info != null; info = info.Parent)
            if ((info.Attributes & FileAttributes.ReparsePoint) != 0)
                throw new InvalidOperationException("世界地图不接受链接或重定向目录");
        if (ForbiddenMarkers.Any(name => Path.Exists(Path.Combine(root, name))) ||
            Directory.EnumerateFiles(root, "MSDK*.dll").Any())
            throw new InvalidOperationException("世界地图规划仅限 POE2 国际服，禁止在国服或其他服使用");
        if (!File.Exists(Path.Combine(root, "Content.ggpk")) &&
            !File.Exists(Path.Combine(root, "Bundles2", "_.index.bin")))
            throw new InvalidOperationException("未找到 POE2 客户端数据");
        return root;
    }

    public static bool IsInternationalExecutable(string file)
    {
        if (!ExecutableNames.Contains(Path.GetFileName(file), StringComparer.OrdinalIgnoreCase)) return false;
        var info = new FileInfo(file);
        if (!info.Exists || (info.Attributes & FileAttributes.ReparsePoint) != 0 ||
            info.Length < 4096 || info.Length > 512L * 1024 * 1024) return false;
        // Require a positive POE2 international build marker, not merely absence of WeGame.
        var marker = Encoding.ASCII.GetBytes("us.patch.pathofexile2.com");
        using var stream = File.OpenRead(file);
        if (stream.ReadByte() != 'M' || stream.ReadByte() != 'Z') return false;
        var buffer = new byte[1024 * 1024 + marker.Length];
        var carry = 0;
        int read;
        while ((read = stream.Read(buffer, carry, buffer.Length - carry)) > 0)
        {
            var count = carry + read;
            if (buffer.AsSpan(0, count).IndexOf(marker) >= 0) return true;
            carry = Math.Min(marker.Length - 1, count);
            buffer.AsSpan(count - carry, carry).CopyTo(buffer);
        }
        return false;
    }
}
