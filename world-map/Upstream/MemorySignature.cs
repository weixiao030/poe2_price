namespace Poe2Overlay;

public sealed class MemorySignature
{
    readonly byte?[] bytes;
    public int RelativeOffset { get; }
    public int Length => bytes.Length;

    public MemorySignature(string pattern)
    {
        if (string.IsNullOrWhiteSpace(pattern)) throw new ArgumentException("签名不能为空", nameof(pattern));
        var tokens = pattern.Split(' ', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        var marker = Array.IndexOf(tokens, "^");
        RelativeOffset = marker < 0 ? -1 : marker;
        bytes = tokens.Where(x => x != "^").Select(x => x is "?" or "??" ? (byte?)null : Convert.ToByte(x, 16)).ToArray();
        if (bytes.Length == 0) throw new ArgumentException("签名没有字节", nameof(pattern));
        if (RelativeOffset >= bytes.Length) throw new ArgumentException("相对地址标记位置无效", nameof(pattern));
    }

    public IReadOnlyList<int> Find(byte[] haystack, int maxMatches = 16)
    {
        var result = new List<int>();
        if (haystack.Length < bytes.Length) return result;
        var count = 0;
        for (var i = 0; i <= haystack.Length - bytes.Length && count < maxMatches; i++)
        {
            var matched = true;
            for (var j = 0; j < bytes.Length; j++)
                if (bytes[j].HasValue && bytes[j]!.Value != haystack[i + j]) { matched = false; break; }
            if (!matched) continue;
            count++;
            result.Add(i);
        }
        return result;
    }

    public bool TryResolve(byte[] haystack, IntPtr matchAddress, int matchOffset, out IntPtr target)
    {
        target = IntPtr.Zero;
        if (RelativeOffset < 0 || matchOffset < 0 || matchOffset + RelativeOffset + 4 > haystack.Length) return false;
        var relative = BitConverter.ToInt32(haystack.AsSpan(matchOffset + RelativeOffset, 4));
        target = new IntPtr(matchAddress.ToInt64() + RelativeOffset + 4 + relative);
        return target != IntPtr.Zero;
    }
}
