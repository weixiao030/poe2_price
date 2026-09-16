using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using Poe2Overlay;
using POE2Radar.Core.Game;

Console.InputEncoding = new UTF8Encoding(false);
Console.OutputEncoding = new UTF8Encoding(false);
WindowTracker.UsePhysicalPixels();
var json = new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.CamelCase };
if (args.SequenceEqual(["--self-test"])) { SelfTests.Run(); return; }
if (args.Length != 2 || args[0] != "--directory")
{
    Console.Error.WriteLine("Expected --directory <POE2 international directory>");
    Environment.ExitCode = 2;
    return;
}
using var reader = new GameMemoryReader();
var atlas = new NativeAtlasReader();
var session = new AtlasSession();
long connectionGeneration = -1;
var snapshot = NativeAtlasSnapshot.Disabled("等待游戏与世界地图");
string? line;
while ((line = Console.ReadLine()) != null)
{
    string? id = null;
    try
    {
        if (line.Length > 8192) throw new InvalidOperationException("请求过大");
        using var document = JsonDocument.Parse(line);
        var input = document.RootElement;
        id = input.GetProperty("id").GetString();
        if (id is null || id.Length > 80) throw new InvalidOperationException("请求编号无效");
        var action = input.GetProperty("action").GetString();
        if (action == "reset") { atlas.ResetLayout(); session.Reset(); }
        if (action is not ("read" or "reset" or "search" or "route"))
            throw new InvalidOperationException("未知世界地图操作");
        if (!reader.TryConnect(args[1])) snapshot = NativeAtlasSnapshot.Disabled("等待所选目录的 POE2 国际服进程");
        else
        {
            if (connectionGeneration != reader.ConnectionGeneration) { session.Reset(); connectionGeneration = reader.ConnectionGeneration; }
            snapshot = session.Accept(atlas.Read(reader));
        }
        object result;
        if (action == "search")
        {
            var query = input.GetProperty("query").GetString() ?? "";
            if (query.Length > 80) throw new InvalidOperationException("搜索词过长");
            result = RuntimePathFinder.Search(snapshot, query).Select(n => n.Grid.ToString()).ToArray();
        }
        else if (action == "route")
        {
            result = session.Plan(snapshot, input) ?? RuntimeRoute.Missing(snapshot.Reason);
        }
        else result = ToView(snapshot, reader, input.TryGetProperty("planning", out var planning) && planning.ValueKind == JsonValueKind.Object
            ? session.Plan(snapshot, planning) : null);
        Console.WriteLine(JsonSerializer.Serialize(new { id, result }, json));
    }
    catch (Exception error)
    {
        snapshot = NativeAtlasSnapshot.Disabled(error.Message);
        reader.Dispose();
        Console.WriteLine(JsonSerializer.Serialize(new { id, error = error.Message }, json));
    }
}

static object? GameWindow(GameMemoryReader reader)
{
    var handle = reader.Process?.MainWindowHandle ?? IntPtr.Zero;
    if (!WindowTracker.TryGetClient(handle, out var client)) return null;
    return new { client.Left, client.Top, client.Width, client.Height,
        Foreground = WindowTracker.GetForegroundWindow() == handle };
}

static object ToView(NativeAtlasSnapshot value, GameMemoryReader reader, RuntimeRoute? route) => new
{
    value.Available,
    value.Player,
    Route = route,
    GameWindow = GameWindow(reader),
    Reason = Regex.Replace(value.Reason, @"0x[0-9A-Fa-f]+", "[address]"),
    Nodes = value.Nodes.Select(n => new
    {
        Id = n.Grid.ToString(), n.Number, n.Grid, n.Name, n.X, n.Y,
        DisplayName = DisplayTextLocalizer.Localize(n.Name), n.AreaId, n.IsHidden,
        State = (int)n.State, n.StateText, n.CanOpen,
        ContentTags = n.Tags, ContentLabels = n.Tags.Select(DisplayTextLocalizer.Localize).ToArray()
    }).ToArray(),
    value.Edges, value.CurrentNode, value.ReadMilliseconds, value.CapturedAt,
    UnknownNameCount = value.Nodes.Count(n => string.IsNullOrWhiteSpace(n.AreaId))
};
