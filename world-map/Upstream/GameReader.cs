using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Security.Cryptography;

namespace Poe2Overlay;

public sealed class GameMemoryReader : IDisposable
{
    const uint VmRead = 0x10;
    const uint QueryInformation = 0x400;

    [DllImport("kernel32.dll", SetLastError = true)] static extern IntPtr OpenProcess(uint access, bool inherit, int processId);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
    [DllImport("kernel32.dll", SetLastError = true)] static extern bool ReadProcessMemory(IntPtr process, IntPtr address, byte[] buffer, int size, out IntPtr read);
    [DllImport("kernel32.dll", SetLastError = true)] static extern IntPtr VirtualQueryEx(IntPtr process, IntPtr address, out MEMORY_BASIC_INFORMATION buffer, IntPtr length);

    IntPtr handle;
    readonly Dictionary<long, MemoryRange> readableRegions = new();
    public Process? Process { get; private set; }
    public long ConnectionGeneration { get; private set; }
    public bool IsConnected => handle != IntPtr.Zero;
    public bool CanReadMemory { get; private set; }
    public string MemoryStatus { get; private set; } = "未连接";
    public string? ExecutableHash { get; private set; }

    public bool TryConnect(string directory)
    {
        var root = ClientGate.ValidateDirectory(directory);
        try
        {
            if (Process != null && !Process.HasExited && IsConnected)
            {
                Process.Refresh();
                if (string.Equals(Path.GetDirectoryName(Process.MainModule?.FileName), root, StringComparison.OrdinalIgnoreCase))
                    return true;
            }
        }
        catch { }
        Dispose();
        foreach (var candidate in ClientGate.ExecutableNames
            .SelectMany(name => System.Diagnostics.Process.GetProcessesByName(Path.GetFileNameWithoutExtension(name))))
        {
            try
            {
                var file = candidate.MainModule?.FileName;
                if (Process != null || file is null ||
                    !string.Equals(Path.GetDirectoryName(file), root, StringComparison.OrdinalIgnoreCase) ||
                    !ClientGate.IsInternationalExecutable(file))
                { candidate.Dispose(); continue; }
                Process = candidate;
            }
            catch { candidate.Dispose(); }
        }
        if (Process == null) return false;
        handle = OpenProcess(VmRead | QueryInformation, false, Process.Id);
        if (handle == IntPtr.Zero) { Dispose(); return false; }
        ConnectionGeneration++;
        try { ExecutableHash = Process.MainModule?.FileName is { } path ? Sha256(path) : null; } catch { }
        ValidateReadAccess();
        return IsConnected;
    }

    public bool TryReadUtf16(IntPtr address, int maxChars, out string value)
    {
        value = "";
        if (maxChars is < 1 or > 1024) return false;
        var bytes = new List<byte>();
        for (var offset = 0; offset < maxChars * 2;)
        {
            var current = address.ToInt64() + offset;
            var count = Math.Min(32, Math.Min(maxChars * 2 - offset, 4096 - (int)(current & 4095)));
            count -= count % 2;
            if (count == 0 || !TryReadBytes(new(current), count, out var part)) return false;
            for (var i = 0; i < part.Length; i += 2)
            {
                if (part[i] == 0 && part[i + 1] == 0)
                {
                    try
                    {
                        value = new System.Text.UnicodeEncoding(false, false, true).GetString(bytes.ToArray());
                        return value.Length > 0 && value.All(c => !char.IsControl(c));
                    }
                    catch { return false; }
                }
                bytes.Add(part[i]); bytes.Add(part[i + 1]);
            }
            offset += count;
        }
        return false;
    }

    void ValidateReadAccess()
    {
        CanReadMemory = false;
        MemoryStatus = "只读句柄打开失败";
        if (handle == IntPtr.Zero || Process == null) return;
        try
        {
            var address = Process.MainModule?.BaseAddress ?? IntPtr.Zero;
            var bytes = new byte[2];
            CanReadMemory = address != IntPtr.Zero && IsReadable(address, bytes.Length) && ReadProcessMemory(handle, address, bytes, bytes.Length, out var read) && read.ToInt64() == 2 && bytes[0] == (byte)'M' && bytes[1] == (byte)'Z';
            MemoryStatus = CanReadMemory ? "只读句柄正常（PE 头读取成功）" : "只读句柄可用，但模块读取失败";
        }
        catch { MemoryStatus = "只读读取异常，已停用内存适配器"; }
    }

    public bool TryReadBytes(IntPtr address, int size, out byte[] bytes)
    {
        bytes = Array.Empty<byte>();
        if (!CanReadMemory || size <= 0 || size > 1024 * 1024 || !IsReadable(address, size)) return false;
        var buffer = new byte[size];
        if (!ReadProcessMemory(handle, address, buffer, size, out var read) || read.ToInt64() != size)
        {
            readableRegions.Clear();
            return false;
        }
        bytes = buffer;
        return true;
    }

    public bool TryReadInt32(IntPtr address, out int value)
    {
        value = 0;
        if (!TryReadBytes(address, sizeof(int), out var bytes)) return false;
        value = BitConverter.ToInt32(bytes);
        return true;
    }

    public bool TryReadPointer(IntPtr address, out IntPtr value)
    {
        value = IntPtr.Zero;
        if (!TryReadBytes(address, IntPtr.Size, out var bytes)) return false;
        value = IntPtr.Size == 8
            ? new IntPtr(BitConverter.ToInt64(bytes))
            : new IntPtr(BitConverter.ToInt32(bytes));
        return value != IntPtr.Zero;
    }

    public bool TryGetMainModule(out MemoryModule module)
    {
        module = default;
        try
        {
            var processModule = Process?.MainModule;
            if (processModule == null || processModule.BaseAddress == IntPtr.Zero || processModule.ModuleMemorySize <= 0) return false;
            module = new MemoryModule(processModule.ModuleName ?? "PathOfExile.exe", processModule.BaseAddress, processModule.ModuleMemorySize);
            return true;
        }
        catch { return false; }
    }

    public IReadOnlyList<IntPtr> ScanMainModule(MemorySignature signature, int maxMatches = 16)
    {
        var matches = new List<IntPtr>();
        if (!TryGetMainModule(out var module) || module.Size <= 0 || signature.Length <= 0) return matches;
        const int chunkSize = 1024 * 1024;
        var overlap = Math.Max(0, signature.Length - 1);
        var seen = new HashSet<long>();
        for (var offset = 0; offset < module.Size && matches.Count < maxMatches; offset += chunkSize - overlap)
        {
            var size = Math.Min(chunkSize, module.Size - offset);
            if (!TryReadBytes(module.BaseAddress + offset, size, out var bytes)) continue;
            foreach (var match in signature.Find(bytes, maxMatches))
            {
                var address = module.BaseAddress + offset + match;
                if (seen.Add(address.ToInt64())) matches.Add(address);
                if (matches.Count >= maxMatches) break;
            }
        }
        return matches;
    }

    public bool IsReadable(IntPtr address, int size = 1)
    {
        if (handle == IntPtr.Zero || address == IntPtr.Zero || size <= 0) return false;
        var value = address.ToInt64();
        var key = value >> 16;
        if (readableRegions.TryGetValue(key, out var cached) && cached.Contains(value, size)) return true;
        var mbi = new MEMORY_BASIC_INFORMATION();
        if (VirtualQueryEx(handle, address, out mbi, (IntPtr)Marshal.SizeOf<MEMORY_BASIC_INFORMATION>()) == IntPtr.Zero) return false;
        if (mbi.State != MemCommit || !IsReadableProtection(mbi.Protect)) return false;
        var a = value;
        var start = mbi.BaseAddress.ToInt64();
        var end = start + mbi.RegionSize.ToInt64();
        if (a < start || a > end || size > end - a) return false;
        var range = new MemoryRange(start, end);
        var firstKey = start >> 16;
        var lastKey = (end - 1) >> 16;
        if (lastKey - firstKey <= 8192)
            for (var regionKey = firstKey; regionKey <= lastKey; regionKey++) readableRegions[regionKey] = range;
        else readableRegions[key] = range;
        return true;
    }

    static bool IsReadableProtection(uint protect)
    {
        if ((protect & 0x100) != 0) return false;
        var p = protect & 0xff;
        return p is PageReadOnly or PageReadWrite or PageWriteCopy or PageExecuteRead or PageExecuteReadWrite or PageExecuteWriteCopy;
    }


    public static string? Sha256(string path)
    {
        try { using var s = File.OpenRead(path); return Convert.ToHexString(SHA256.HashData(s)); }
        catch { return null; }
    }

    void DisposeHandle()
    {
        if (handle != IntPtr.Zero) CloseHandle(handle);
        handle = IntPtr.Zero;
        CanReadMemory = false;
        MemoryStatus = "未连接";
        ExecutableHash = null;
        readableRegions.Clear();
    }

    public void Dispose()
    {
        DisposeHandle();
        Process?.Dispose();
        Process = null;
    }

    const uint MemCommit = 0x1000;
    const uint PageReadOnly = 0x02;
    const uint PageReadWrite = 0x04;
    const uint PageWriteCopy = 0x08;
    const uint PageExecuteRead = 0x20;
    const uint PageExecuteReadWrite = 0x40;
    const uint PageExecuteWriteCopy = 0x80;

    [StructLayout(LayoutKind.Sequential)] struct MEMORY_BASIC_INFORMATION
    {
        public IntPtr BaseAddress;
        public IntPtr AllocationBase;
        public uint AllocationProtect;
        public IntPtr RegionSize;
        public uint State;
        public uint Protect;
        public uint Type;
    }

    readonly record struct MemoryRange(long Start, long End)
    {
        public bool Contains(long address, int size) => address >= Start && address <= End && size <= End - address;
    }
}

public readonly record struct MemoryModule(string Name, IntPtr BaseAddress, int Size);


public readonly record struct ScreenRect(int Left, int Top, int Width, int Height);

public static class WindowTracker
{
    [DllImport("user32.dll")] static extern bool SetProcessDpiAwarenessContext(IntPtr context);
    public static void UsePhysicalPixels() => SetProcessDpiAwarenessContext(new IntPtr(-4));
    [StructLayout(LayoutKind.Sequential)] struct RECT { public int Left, Top, Right, Bottom; }
    [StructLayout(LayoutKind.Sequential)] struct POINT { public int X, Y; }
    [DllImport("user32.dll")] static extern bool GetClientRect(IntPtr hwnd, out RECT rect);
    [DllImport("user32.dll")] static extern bool ClientToScreen(IntPtr hwnd, ref POINT point);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr hwnd);
    [DllImport("user32.dll")] public static extern uint GetDpiForWindow(IntPtr hwnd);
    public static bool TryGetClient(IntPtr hwnd, out ScreenRect bounds)
    {
        bounds = default;
        if (hwnd == IntPtr.Zero || IsIconic(hwnd) || !GetClientRect(hwnd, out var rect)) return false;
        var origin = new POINT();
        if (!ClientToScreen(hwnd, ref origin)) return false;
        bounds = new(origin.X, origin.Y, rect.Right - rect.Left, rect.Bottom - rect.Top);
        return bounds.Width > 0 && bounds.Height > 0;
    }
}
