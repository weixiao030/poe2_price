using POE2Radar.Core.Game;

namespace Poe2Overlay;

public sealed record RuntimeRoute(bool Found, IReadOnlyList<GridPoint> Path, double Distance, string Message)
{
    // Ordinary routes guide the player from the live position to the first node.  An
    // accessible-node optimal route starts at an Atlas node by design and must not draw
    // that extra player-to-start segment.
    public bool IncludePlayerGuide { get; init; } = true;
    public static RuntimeRoute Missing(string reason) => new(false, Array.Empty<GridPoint>(), 0, reason);
}

public static class RuntimePathFinder
{
    public static IReadOnlyList<RuntimeAtlasNode> Search(NativeAtlasSnapshot snapshot, string query)
    {
        query = query.Trim();
        if (query.Length == 0) return Array.Empty<RuntimeAtlasNode>();
        var exact = snapshot.Nodes.Where(n => n.Number.ToString() == query || n.Grid.ToString() == query).ToArray();
        if (exact.Length > 0) return exact;
        // Use the shared deterministic character map first.  LCMapStringEx is only a best-effort
        // Windows fallback and can be unavailable in trimmed/Wine test hosts.
        var chinese = DisplayTextLocalizer.ToSimplifiedUiText(query);
        return snapshot.Nodes.Where(n =>
        {
            var displayName = DisplayTextLocalizer.Localize(n.Name);
            var simplifiedDisplay = DisplayTextLocalizer.ToSimplifiedUiText(displayName);
            var content = n.Tags.SelectMany(tag => new[]
            {
                tag,
                DisplayTextLocalizer.Localize(tag),
                DisplayTextLocalizer.ToSimplifiedUiText(DisplayTextLocalizer.Localize(tag)),
                tag.Equals("Grand Mirror", StringComparison.OrdinalIgnoreCase) ? "宏偉之鏡" : "",
                tag.Equals("Grand Mirror", StringComparison.OrdinalIgnoreCase) ? "宏伟之镜" : "",
            });
            return n.Name.Contains(query, StringComparison.OrdinalIgnoreCase) ||
                displayName.Contains(query, StringComparison.OrdinalIgnoreCase) ||
                n.AreaId.Contains(query, StringComparison.OrdinalIgnoreCase) ||
                simplifiedDisplay.Contains(chinese, StringComparison.OrdinalIgnoreCase) ||
                Simplified(displayName).Contains(chinese, StringComparison.OrdinalIgnoreCase) ||
                content.Any(value => value.Contains(query, StringComparison.OrdinalIgnoreCase) ||
                    value.Contains(chinese, StringComparison.OrdinalIgnoreCase));
        }).ToArray();
    }

    static string Simplified(string value)
    {
        var result = new System.Text.StringBuilder(value.Length * 2 + 2);
        return LCMapStringEx("zh-CN", 0x02000000, value, value.Length, result, result.Capacity, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero) > 0
            ? result.ToString() : value;
    }
    [System.Runtime.InteropServices.DllImport("kernel32.dll", CharSet = System.Runtime.InteropServices.CharSet.Unicode)]
    static extern int LCMapStringEx(string locale, uint flags, string source, int length, System.Text.StringBuilder destination, int capacity, IntPtr version, IntPtr reserved, IntPtr sort);

    public static RuntimeRoute Find(NativeAtlasSnapshot snapshot, GridPoint start, GridPoint target)
    {
        if (!snapshot.Available) return RuntimeRoute.Missing("实时地图数据不可用");
        var adjacency = snapshot.Nodes.ToDictionary(n => n.Grid, _ => new List<GridPoint>());
        if (!adjacency.ContainsKey(target)) return RuntimeRoute.Missing("终点尚未加载到客户端");
        if (!adjacency.ContainsKey(start))
            return RuntimeRoute.Missing("起点不在当前内存地图中，等待有效节点");
        // The game recycles atlas children while panning. A torn-but-valid frame can therefore
        // contain an edge whose far endpoint is not in this frame yet. Dropping that edge keeps the
        // connected portion usable; treating the entire graph as invalid made every route fail and
        // also hid otherwise valid connection lines.
        foreach (var e in snapshot.Edges)
        {
            if (!adjacency.ContainsKey(e.A) || !adjacency.ContainsKey(e.B)) continue;
            adjacency[e.A].Add(e.B); adjacency[e.B].Add(e.A);
        }
        var previous = new Dictionary<GridPoint, GridPoint?> { [start] = null };
        var queue = new Queue<GridPoint>();
        queue.Enqueue(start);
        while (queue.TryDequeue(out var current))
        {
            if (current == target)
            {
                var path = new List<GridPoint>();
                for (GridPoint? at = current; at.HasValue; at = previous[at.Value]) path.Add(at.Value);
                path.Reverse();
                var distance = path.Zip(path.Skip(1), CoordinateDistance).Sum();
                return new(true, path, distance, $"已规划 {path.Count - 1} 段 · {distance:F1} 格");
            }
            foreach (var next in adjacency[current])
                if (previous.TryAdd(next, current)) queue.Enqueue(next);
        }
        return RuntimeRoute.Missing("当前客户端连接图中不可达");
    }

    public static RuntimeRoute FindBestFromAccessible(NativeAtlasSnapshot snapshot, GridPoint target)
    {
        if (!snapshot.Available) return RuntimeRoute.Missing("实时地图数据不可用");
        var adjacency = snapshot.Nodes.ToDictionary(n => n.Grid, _ => new List<GridPoint>());
        if (!adjacency.ContainsKey(target)) return RuntimeRoute.Missing("终点尚未加载到客户端");
        foreach (var e in snapshot.Edges)
        {
            if (!adjacency.ContainsKey(e.A) || !adjacency.ContainsKey(e.B)) continue;
            adjacency[e.A].Add(e.B); adjacency[e.B].Add(e.A);
        }

        var starts = snapshot.Nodes.Where(n => n.CanOpen && adjacency.ContainsKey(n.Grid))
            .Select(n => n.Grid)
            .Distinct()
            .ToArray();
        if (starts.Length == 0) return RuntimeRoute.Missing("当前内存地图没有可开启起点");

        var distance = new Dictionary<GridPoint, double>();
        var previous = new Dictionary<GridPoint, GridPoint?>();
        var queue = new PriorityQueue<GridPoint, double>();
        foreach (var start in starts)
        {
            if (distance.TryAdd(start, 0))
            {
                previous[start] = null;
                queue.Enqueue(start, 0);
            }
        }

        while (queue.TryDequeue(out var current, out var currentDistance))
        {
            if (!distance.TryGetValue(current, out var knownDistance) || currentDistance > knownDistance + 0.000001)
                continue;
            if (current == target)
            {
                var path = new List<GridPoint>();
                for (GridPoint? at = current; at.HasValue; at = previous[at.Value]) path.Add(at.Value);
                path.Reverse();
                var start = path[0];
                return new RuntimeRoute(true, path, knownDistance,
                    $"最优路径：从可开启节点 [{start}] 出发 · {path.Count - 1} 段 · {knownDistance:F1} 格")
                {
                    IncludePlayerGuide = false,
                };
            }
            foreach (var next in adjacency[current])
            {
                var nextDistance = knownDistance + CoordinateDistance(current, next);
                if (distance.TryGetValue(next, out var oldDistance) && nextDistance >= oldDistance - 0.000001)
                    continue;
                distance[next] = nextDistance;
                previous[next] = current;
                queue.Enqueue(next, nextDistance);
            }
        }
        return RuntimeRoute.Missing("所有可开启节点到目标均不可达");
    }

    // Compatibility name for callers from older builds.  It intentionally keeps the new
    // accessible-node semantics; the UI must never silently fall back to every visible node.
    public static RuntimeRoute FindBestFromVisible(NativeAtlasSnapshot snapshot, GridPoint target) =>
        FindBestFromAccessible(snapshot, target);

    static RuntimeRoute DirectGuide(NativeAtlasSnapshot snapshot, GridPoint start, GridPoint target, string message)
    {
        var distance = CoordinateDistance(start, target);
        var path = snapshot.Nodes.Any(n => n.Grid == start)
            ? new[] { start, target }
            : new[] { target };
        return new RuntimeRoute(true, path, distance, $"直达引导 · {distance:F1} 格");
    }

    public static double CoordinateDistance(GridPoint a, GridPoint b)
    {
        var x = (double)a.X - b.X;
        var y = (double)a.Y - b.Y;
        return Math.Sqrt(x * x + y * y);
    }
}
