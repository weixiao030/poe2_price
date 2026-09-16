using Poe2Overlay;
using POE2Radar.Core.Game;

internal static class SelfTests
{
    public static void Run()
    {
        var checks = 0;
        void Check(bool valid, string name)
        {
            if (!valid) throw new InvalidOperationException(name);
            Console.WriteLine($"PASS {name}");
            checks++;
        }
        RuntimeAtlasNode Node(int number, int x, int y, byte state, bool hidden = false,
            string name = "Steppe", string[]? tags = null) =>
            new(number, 0, new(x, y), x, y, name, "MapSteppe", hidden, state, tags);
        var nodes = new[] { Node(1, 0, 0, 0), Node(2, 1, 0, 1), Node(3, 2, 0, 255),
            Node(4, 3, 0, 255, true, tags: ["Grand Mirror", "魂靈遷徙"]), Node(5, 99, 99, 255) };
        var edges = new[] { new RuntimeAtlasEdge(new(0, 0), new(1, 0)), new(new(1, 0), new(2, 0)),
            new(new(2, 0), new(3, 0)), new(new(2, 0), new(999, 999)) };
        var map = new NativeAtlasSnapshot(true, "fixture", nodes, edges, null, 0, DateTime.UtcNow)
            { CurrentNode = new(0, 0) };
        Check(AtlasMapData.Shared.MapCount > 50, "embedded-map-catalog");
        Check(Poe2DbTranslationCatalog.Shared.Count > 100, "embedded-translations");
        Check(RuntimePathFinder.Find(map, new(0, 0), new(3, 0)).Path.Count == 4, "connected-route");
        Check(!RuntimePathFinder.Find(map, new(0, 0), new(99, 99)).Found, "unreachable-route");
        Check(!RuntimePathFinder.Find(map, new(999, 0), new(3, 0)).Found, "missing-start-is-not-a-route");
        var best = RuntimePathFinder.FindBestFromAccessible(map, new(3, 0));
        Check(best.Found && best.Path[0] == new GridPoint(1, 0) && best.Distance == 2, "accessible-start-only");
        Check(!RuntimePathFinder.FindBestFromAccessible(map with { Nodes = nodes.Where(n => !n.CanOpen).ToArray() }, new(3, 0)).Found, "no-accessible-start");
        Check(RuntimePathFinder.Search(map, "4").Single().IsHidden, "search-hidden-node-number");
        Check(RuntimePathFinder.Search(map, "宏伟之镜").Count == 1, "search-simplified-content");
        Check(RuntimePathFinder.Search(map, "魂灵迁徙").Count == 1, "search-content-alias");
        Check(RuntimePathFinder.Search(map, "2,0").Single().Number == 3, "search-grid");
        Check(NativeAtlasReader.SelectCurrentGrid(new(0, 0), new(1, 0), nodes.Select(n => n.Grid).ToHashSet()) == new GridPoint(0, 0), "marker-authoritative");
        Check(NativeAtlasReader.SelectCurrentGrid(new(9, 9), null, nodes.Select(n => n.Grid).ToHashSet()) is null, "reject-out-of-frame-current");
        var signature = new MemorySignature("48 8B ^ ?? ?? ?? ??");
        var bytes = new byte[] { 0x48, 0x8B, 0xFA, 0xFF, 0xFF, 0xFF };
        Check(signature.TryResolve(bytes, new(0x1000), 0, out var target) && target == new IntPtr(0x1000), "signed-rip-resolution");
        var session = new AtlasSession();
        var frame = map with { TopologyHash = 1 };
        var route = session.Plan(frame, "current", null, new(3, 0));
        Check(route?.Path.Count == 4, "session-initial-route");
        Check(ReferenceEquals(route, session.Plan(frame, "current", null, new(3, 0))), "unchanged-topology-reuses-route");
        Check(session.Plan(frame with { CurrentNode = new(2, 0) }, "current", null, new(3, 0))?.Path.Count == 2, "current-movement-replans");
        Check(session.Plan(frame with { TopologyHash = 2, Edges = [] }, "current", null, new(3, 0))?.Found == false, "topology-change-replans");
        Check(session.Plan(frame, "accessible", null, new(3, 0))?.IncludePlayerGuide == false, "optimal-route-has-no-player-guide");
        Check(session.Plan(frame, "manual", new(2, 0), new(3, 0))?.IncludePlayerGuide == true, "manual-route-has-player-guide");
        var nextAccessible = nodes.Select(n => n.Grid == new GridPoint(2, 0) ? Node(3, 2, 0, 1) : n).ToArray();
        Check(session.Plan(frame with { TopologyHash = 3, Nodes = nextAccessible }, "accessible", null, new(3, 0))?.Path[0] == new GridPoint(2, 0), "accessible-state-change-replans");
        session.Reset();
        Check(!session.Accept(frame).Available, "calibration-hides-first-frame");
        Check(!session.Accept(frame).Available, "cached-frame-does-not-count-twice");
        Check(!session.Accept(NativeAtlasSnapshot.Disabled("transition")).Available, "invalid-frame-breaks-calibration");
        Check(!session.Accept(frame with { CapturedAt = frame.CapturedAt.AddSeconds(1) }).Available, "calibration-requires-consecutive-valid-frames");
        Check(session.Accept(frame with { CapturedAt = frame.CapturedAt.AddSeconds(2) }).Available, "calibration-accepts-second-distinct-valid-frame");
        Check(session.Plan(frame, "current", null, null) is null, "cleared-route-stays-cleared");
        Console.WriteLine($"WORLD_MAP_SELF_TEST checks={checks} failed=0");
    }
}
