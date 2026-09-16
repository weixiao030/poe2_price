using System.Text.Json;
using Poe2Overlay;

// Owns read-only planning and calibration across renderer navigation and tray operation.
internal sealed class AtlasSession
{
    int calibrationFrames;
    bool calibrating;
    DateTime lastCalibrationAt;
    string? routeKey;
    RuntimeRoute? cachedRoute;
    public void Reset()
    {
        calibrating = true;
        calibrationFrames = 0;
        lastCalibrationAt = default;
        routeKey = null;
        cachedRoute = null;
    }
    public NativeAtlasSnapshot Accept(NativeAtlasSnapshot snapshot)
    {
        if (!calibrating) return snapshot;
        if (!snapshot.Available) { calibrationFrames = 0; lastCalibrationAt = default; return snapshot; }
        if (lastCalibrationAt != snapshot.CapturedAt) { calibrationFrames++; lastCalibrationAt = snapshot.CapturedAt; }
        if (calibrationFrames < 2) return NativeAtlasSnapshot.Disabled("正在重新定位地图节点，等待连续有效帧");
        calibrating = false;
        return snapshot;
    }
    public RuntimeRoute? Plan(NativeAtlasSnapshot snapshot, string? mode, GridPoint? start, GridPoint? target)
    {
        if (target is not { } goal || !snapshot.Available) { routeKey = null; cachedRoute = null; return null; }
        var origin = mode == "current" ? snapshot.CurrentNode : start;
        var key = $"{snapshot.TopologyHash}|{mode}|{(mode == "accessible" ? null : origin)}|{goal}";
        if (snapshot.TopologyHash != 0 && key == routeKey) return cachedRoute;
        cachedRoute = mode switch
        {
            "accessible" => RuntimePathFinder.FindBestFromAccessible(snapshot, goal),
            "current" or "manual" => origin is { } point ? RuntimePathFinder.Find(snapshot, point, goal) : RuntimeRoute.Missing("起点尚未确认"),
            _ => throw new InvalidOperationException("无效路线模式")
        };
        routeKey = key;
        return cachedRoute;
    }
    public RuntimeRoute? Plan(NativeAtlasSnapshot snapshot, JsonElement request)
    {
        var mode = request.GetProperty("mode").GetString();
        return Plan(snapshot, mode, mode == "manual" ? ReadGrid(request.GetProperty("start")) : null, ReadGrid(request.GetProperty("target")));
    }
    public static GridPoint ReadGrid(JsonElement value)
    {
        var x = value.GetProperty("x").GetInt32();
        var y = value.GetProperty("y").GetInt32();
        if (Math.Abs((long)x) > 1000000 || Math.Abs((long)y) > 1000000) throw new InvalidOperationException("节点坐标超限");
        return new(x, y);
    }
}
