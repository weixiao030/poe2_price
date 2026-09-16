using POE2Radar.Core.Game;

namespace Poe2Overlay;

public sealed class NativeAtlasReader
{
    public const string SupportedHash = "E62036DAEEF618C2F24BB133D5DCA6A821F6E8F105ECFB986E46838BF355B02A";
    // The game updated its executable between the last live audit and the current run. Keep the
    // previously verified build and the new hash in the candidate set; the signature, vtable and
    // torn-snapshot checks below still have to pass before any nodes are exposed.
    public const string CurrentSupportedHash = "E0CDE00D395DBB339F2C2E0812C3D872FE5425C04A88AF544AB06E19B07A7504";
    static readonly HashSet<string> SupportedHashes = new(StringComparer.OrdinalIgnoreCase)
    {
        SupportedHash,
        CurrentSupportedHash,
    };
    // The old build-specific signature is retained as the first candidate, but the reader no
    // longer gates on a hard-coded executable hash.  A structurally validated chain is safer and
    // more portable than rejecting a perfectly readable client merely because it was rebuilt on
    // another machine or received a small game patch.
    static readonly string[] GameStateSignatures =
    [
        "83 ?? ?? ?? 8B ?? 33 ?? ?? 39 ?? ^ ?? ?? ?? ?? 0F 85 ?? ?? ?? ?? ?? ?? ?? ?? ?? E8 ?? ?? ?? ??",
        "48 39 2D ^ ?? ?? ?? ?? 0F 85 ?? ?? ?? ??",
        "8B C7 48 83 C4 40 5F C3 48 8B 05 ^ ?? ?? ?? ?? 48 89 07"
    ];
    const int UiSelf = 0x08;
    const int UiChildren = 0x10;
    const int UiChildrenEnd = 0x18;
    const int UiParent = 0xB8;
    const int UiRelativePos = 0x100;
    const int UiPositionModifier = 0x108;
    // The reference build's position getter uses the transform scale at +0xF8.  The live
    // 2026 client also exposes a widget/local scale at +0x118 (0.85 for atlas nodes), but
    // that value is not part of the screen projection.  Using it here stretches every point
    // by ~1.53x and is the reason the overlay can report valid nodes while drawing them away
    // from the game's markers.
    const int UiTransformScale = 0xF8;
    const int UiFlags = 0x168;
    const int UiSizeW = 0x270;
    const int UiSizeH = 0x274;
    // These UI fields moved as a group between recent PoE2 clients.  The live node class is
    // sampled before the first snapshot and selects the layout with the most finite/diverse data;
    // the current client resolves to 0x100/0x118/0x168/0x270, while the upstream layout resolves
    // to 0x118/0x130/0x180/0x288.  No user-specific address is involved.
    static readonly int[] UiRelativePosCandidates = [0x100, 0x118];
    static readonly int[] UiPositionModifierCandidates = [0x108, 0xF0];
    // Keep the proven reference offset first.  A future field insertion can be added here only
    // after a structural projection check; never choose the node's widget scale just because it
    // is finite.
    static readonly int[] UiTransformScaleCandidates = [UiTransformScale];
    static readonly int[] UiFlagsCandidates = [0x168, 0x180];
    static readonly (int W, int H)[] UiSizeCandidates = [(0x270, 0x274), (0x288, 0x28C)];
    const int AtlasGridPos = 0x310; // current client: old +0x320 moved to +0x310
    // Atlas node layouts have used both offsets across live client builds.  The upstream
    // reference treats the grid field as a build-validated structural field rather than
    // assuming one maintainer's executable.  Keep both candidates and select the one that
    // yields a real, diverse grid for the detected node class.
    static readonly int[] AtlasGridPosCandidates = [0x310, 0x320];
    // The node UI element's +0x32C byte is not the gameplay state.  The three-state
    // value used by the Atlas is owned by node +0x10 (storage) -> +0x20 (model) ->
    // model +0x2CF.  Keep the UI offsets separate so a layout change cannot silently
    // turn an unrelated byte into an "openable" node.
    const int AtlasModelState = 0x2CF;
    const int AtlasDataStorage = 0x10;
    const int AtlasDataModel = 0x20;
    // Current node-data map-id field. The former 0x290 value belonged to the
    // pre-0.5.4 layout and silently skipped names after the model insertion.
    const int AtlasDataMapId = 0x2A0; // Upstream Poe2.AtlasNode.DataMapId at 7dde80b.
    const int AtlasMapRow = 0x300;
    const int AtlasConnections = 0x590; // current client: old +0x5A8 moved to +0x590
    static readonly int[] AtlasConnectionCandidates = [0x590, 0x5A8];
    // The current-location marker is a non-node UiElement whose +0x300 pointer refers to
    // the active Atlas node.  +0x2E8 is an adjacent UI field and must not be allowed to
    // overwrite the independently read current-grid value.
    const int AtlasCurrentMarkerNode = 0x300;
    const int WorldVtable = 0x30E18F0, AtlasVtable = 0x30E39A8, NodeVtable = 0x30DCA90;
    // Vtables move when Grinding Gear Games rebuilds the executable.  The old constants are
    // retained as documentation/fast-path hints, but the reader discovers the current class
    // vtables from the already validated UI object graph below.
    long detectedWorldVtable, detectedAtlasVtable, detectedNodeVtable;
    long detectedNodeCanvas;
    long detectedCurrentMarker;
    int detectedGridOffset = AtlasGridPos;
    int detectedConnectionsOffset = AtlasConnections;
    int detectedRelativePosOffset = UiRelativePos;
    int detectedPositionModifierOffset = UiPositionModifier;
    int detectedTransformScaleOffset = UiTransformScale;
    int detectedFlagsOffset = UiFlags;
    int detectedSizeWOffset = UiSizeW;
    int detectedSizeHOffset = UiSizeH;
    DateTime nextCanvasProbe;
    // Atlas child elements are virtualized and recycled while the player drags the map.  A
    // child address therefore is not a stable identity: keeping its old name makes a freshly
    // positioned node inherit the label of the previous node.  Keep only a map-code cache and
    // resolve the current node payload before consulting it.
    readonly Dictionary<string, (string Id, string Name)> names = new(StringComparer.Ordinal);
    // Name objects are stable for the lifetime of a live Atlas payload. Cache the resolved
    // code by the +0x2F0 payload pointer so subsequent snapshots avoid three remote pointer
    // reads and a UTF-16 probe per node; the grid/address is deliberately not used as a key
    // because UI children are recycled while panning.
    readonly Dictionary<long, (string Id, string Name)> namePayloadCache = new();
    // Atlas 子元素按视口动态重排，不能把数组下标当作节点编号。
    readonly Dictionary<string, int> stableNumbers = new(StringComparer.Ordinal);
    int nextStableNumber = 1;
    // Full node walks are deliberately bounded. Between full samples we only return a
    // translated immutable snapshot after checking the child vector, edge header, layout and
    // a sparse live-position fingerprint. This removes the per-tick 1 MB node walk while
    // still invalidating quickly when the map pans, zooms or its children are rebuilt.
    const int FullRefreshIntervalMs = 250;
    NativeAtlasSnapshot? cachedSnapshot;
    byte[] cachedChildrenBytes = Array.Empty<byte>();
    byte[] cachedEdgeHeader = Array.Empty<byte>();
    byte[] cachedLayout = Array.Empty<byte>();
    ulong cachedNodeFingerprint;
    long cachedCanvasAddress;
    long cachedWorldAddress;
    PixelPoint cachedCanvasOrigin;
    double cachedCanvasScale;
    DateTime lastFullRefreshAt;
    // The game's Atlas canvas may virtualize children while it is being panned. Keep the
    // validated node payloads seen during this open-canvas session so the overlay does not
    // require the user to trigger refreshes manually. Cached positions are always transformed
    // from the previous canvas origin/scale; raw coordinates are never reused unchanged.
    readonly Dictionary<GridPoint, RuntimeAtlasNode> retainedNodes = new();
    readonly HashSet<(GridPoint A, GridPoint B)> retainedEdges = new();
    long retainedCanvasAddress;
    long retainedWorldAddress;
    PixelPoint retainedCanvasOrigin;
    double retainedCanvasScale;
    bool retainedTransformValid;
    DateTime atlasClosedAt;
    long session = -1;
    IntPtr global;
    DateTime nextProbe;
    // UI buttons and the map-rebuild watchdog request invalidation from the WPF thread while
    // Read runs on the sampling thread.  Apply the request at the start of the next read so
    // the mutable name/number dictionaries are never cleared while a snapshot is enumerating.
    int layoutResetRequested;

    /// <summary>
    /// Requests a fresh, read-only discovery of the Atlas UI layout on the next sample.
    /// This does not write to the game process; it only discards local pointer/layout caches.
    /// </summary>
    public void ResetLayout() => InvalidateCalibration();

    /// <summary>
    /// Alias used by the calibration control and anomaly detector.
    /// </summary>
    public void InvalidateCalibration() => System.Threading.Interlocked.Exchange(ref layoutResetRequested, 1);

    void ApplyLayoutReset()
    {
        global = IntPtr.Zero;
        nextProbe = DateTime.MinValue;
        ClearAtlasSessionCache();
        atlasClosedAt = DateTime.MinValue;
    }

    void ClearAtlasSessionCache()
    {
        names.Clear();
        namePayloadCache.Clear();
        stableNumbers.Clear();
        nextStableNumber = 1;
        cachedSnapshot = null;
        cachedChildrenBytes = Array.Empty<byte>();
        cachedEdgeHeader = Array.Empty<byte>();
        cachedLayout = Array.Empty<byte>();
        cachedNodeFingerprint = 0;
        cachedCanvasAddress = cachedWorldAddress = 0;
        cachedCanvasOrigin = new PixelPoint(0, 0);
        cachedCanvasScale = 0;
        lastFullRefreshAt = DateTime.MinValue;
        retainedNodes.Clear();
        retainedEdges.Clear();
        retainedCanvasAddress = retainedWorldAddress = 0;
        retainedCanvasOrigin = new PixelPoint(0, 0);
        retainedCanvasScale = 0;
        retainedTransformValid = false;
        detectedWorldVtable = detectedAtlasVtable = detectedNodeVtable = 0;
        detectedNodeCanvas = detectedCurrentMarker = 0;
        detectedGridOffset = AtlasGridPos;
        detectedConnectionsOffset = AtlasConnections;
        detectedRelativePosOffset = UiRelativePos;
        detectedPositionModifierOffset = UiPositionModifier;
        detectedTransformScaleOffset = UiTransformScale;
        detectedFlagsOffset = UiFlags;
        detectedSizeWOffset = UiSizeW;
        detectedSizeHOffset = UiSizeH;
        nextCanvasProbe = DateTime.MinValue;
    }

    public NativeAtlasSnapshot Read(GameMemoryReader reader)
    {
        var watch = System.Diagnostics.Stopwatch.StartNew();
        if (!reader.IsConnected || !reader.CanReadMemory) return NativeAtlasSnapshot.Disabled("只读内存句柄不可用");
        if (System.Threading.Interlocked.Exchange(ref layoutResetRequested, 0) != 0)
            ApplyLayoutReset();
        // Do not reject a client solely because its SHA-256 is not in our catalog. The live
        // pointer chain, module-resident vtables, node-grid distribution and torn-frame checks
        // below are the actual compatibility gates and let another PC/user run the same build
        // without editing a local hash allow-list. A future layout still fails closed.
        if (session != reader.ConnectionGeneration)
        {
            session = reader.ConnectionGeneration;
            ApplyLayoutReset();
        }
        if (!reader.TryGetMainModule(out var module)) return NativeAtlasSnapshot.Disabled("游戏主模块不可用");
        if (global == IntPtr.Zero)
        {
            if (DateTime.UtcNow < nextProbe) return NativeAtlasSnapshot.Disabled("等待重新定位 GameState");
            nextProbe = DateTime.UtcNow.AddSeconds(5);
            foreach (var text in GameStateSignatures)
            {
                var signature = new MemorySignature(text);
                var hits = reader.ScanMainModule(signature, 16);
                foreach (var hit in hits)
                {
                    if (!reader.TryReadBytes(hit, signature.Length, out var bytes) ||
                        !signature.TryResolve(bytes, hit, 0, out var candidate) ||
                        !reader.TryReadPointer(candidate, out var candidateState) ||
                        candidateState.ToInt64() <= 0x10000 ||
                        !HasUiRoot(reader, candidateState))
                        continue;
                    global = candidate;
                    break;
                }
                if (global != IntPtr.Zero) break;
            }
            if (global == IntPtr.Zero)
                return NativeAtlasSnapshot.Disabled("GameState 特征码未解析到有效根对象");
        }
        // Keep every hop separate.  A generic transition message used to hide whether the
        // game was between scenes or the patch had moved one of the UI roots, which made live
        // diagnosis unnecessarily difficult.  Each failed hop is still a safe read-only stop.
        // The byte cache is created before resolving the UI root so the structural checks below
        // can validate candidates without trusting a maintainer-specific offset.
        var cache = new Dictionary<long, byte[]>();
        if (!reader.TryReadPointer(global, out var state) || state == IntPtr.Zero)
        {
            return NativeAtlasSnapshot.Disabled("GameState 指针为空，等待场景加载");
        }
        // The reference reader probes the active InGameState and then validates the UI root
        // structurally.  Support both the current direct chain (GameState+0x90 → holder →
        // UI+0x2F0) and the upstream chain (GameState+0x90 → InGameState → UI+0x300), plus the
        // historical state-vector slots.  This is per-process discovery; no user/account map
        // data or absolute heap address is persisted.
        var stateCandidates = new List<IntPtr>();
        void AddStateCandidate(IntPtr value)
        {
            if (value != IntPtr.Zero && value.ToInt64() > 0x10000 && !stateCandidates.Contains(value))
                stateCandidates.Add(value);
        }
        if (reader.TryReadPointer(state + 0x90, out var directState)) AddStateCandidate(directState);
        if (reader.TryReadPointer(state + 0x08, out var currentState)) AddStateCandidate(currentState);
        for (var i = 0; i < 12; i++)
            if (reader.TryReadPointer(state + 0x48 + i * 0x10, out var slotState)) AddStateCandidate(slotState);

        IntPtr holder = IntPtr.Zero, ui = IntPtr.Zero;
        foreach (var candidate in stateCandidates)
        {
            foreach (var uiOffset in new[] { 0x2F0, 0x300 })
            {
                if (!reader.TryReadPointer(candidate + uiOffset, out var candidateUi) || !LooksLikeUiElement(reader, candidateUi)) continue;
                holder = candidate; ui = candidateUi;
                break;
            }
            if (ui != IntPtr.Zero) break;
        }
        if (ui == IntPtr.Zero)
        {
            return NativeAtlasSnapshot.Disabled(stateCandidates.Count == 0
                ? "GameState.UIHolder 指针为空，等待 UI 初始化"
                : "UI 根对象指针为空，等待界面初始化");
        }
        byte[]? Element(IntPtr address)
        {
            if (cache.TryGetValue(address.ToInt64(), out var saved)) return saved;
            // Node data now reaches +0x339/+0x350; keep one cached header large enough for
            // the current atlas class while still using the same self-pointer guard.
            if (!reader.TryReadBytes(address, 0x380, out var value) || Pointer(value, UiSelf) != address) return null;
            cache[address.ToInt64()] = value;
            return value;
        }
        bool VisibleWithFlags(IntPtr address, int flagsOffset)
        {
            var seen = new HashSet<long>();
            for (var depth = 0; address != IntPtr.Zero && depth < 16; depth++)
            {
                if (!seen.Add(address.ToInt64()) || Element(address) is not { } d || (U32(d, flagsOffset) & 0x800) == 0) return false;
                address = Pointer(d, UiParent);
            }
            return address == IntPtr.Zero;
        }
        bool Visible(IntPtr address)
        {
            // Probe both known flag locations until the node layout has been discovered.  This
            // keeps the UI gate usable after a client field insertion instead of silently treating
            // a valid atlas as closed because the old flag word is zero.
            if (VisibleWithFlags(address, detectedFlagsOffset)) return true;
            foreach (var candidate in UiFlagsCandidates.Distinct())
            {
                if (candidate == detectedFlagsOffset || !VisibleWithFlags(address, candidate)) continue;
                detectedFlagsOffset = candidate;
                return true;
            }
            return false;
        }
        PixelPoint? Origin(IntPtr address, int depth = 0)
        {
            if (address == IntPtr.Zero) return new PixelPoint(0, 0);
            if (depth > 16 || Element(address) is not { } d) return null;
            var scale = F32(d, detectedTransformScaleOffset);
            if (!double.IsFinite(scale) || scale is < .05 or > 8)
            {
                foreach (var candidate in UiTransformScaleCandidates.Distinct())
                {
                    var probe = F32(d, candidate);
                    if (!double.IsFinite(probe) || probe is < .05 or > 8) continue;
                    detectedTransformScaleOffset = candidate;
                    scale = probe;
                    break;
                }
            }
            if (!double.IsFinite(scale) || scale is < .05 or > 8) return null;
            var parent = Pointer(d, 0xB8);
            if (Origin(parent, depth + 1) is not { } p) return null;
            var x = p.X + F32(d, detectedRelativePosOffset) * scale;
            var y = p.Y + F32(d, detectedRelativePosOffset + 4) * scale;
            // The game's position getter adds parent content offsets when bit 10 is set.
            if (parent != IntPtr.Zero && (U32(d, detectedFlagsOffset) & 0x400) != 0 && Element(parent) is { } pd)
            {
                x += F32(pd, detectedPositionModifierOffset) * F32(pd, detectedTransformScaleOffset);
                y += F32(pd, detectedPositionModifierOffset + 4) * F32(pd, detectedTransformScaleOffset);
            }
            return double.IsFinite(x) && double.IsFinite(y) ? new PixelPoint(x, y) : null;
        }

        // WorldScreen/AtlasPanel offsets also drift. Prefer the legacy chain when it passes a
        // self-pointer check, but fall back to the UI root; node-canvas discovery below then
        // follows the actual visible Atlas subtree exactly as the reference project does.
        var world = IntPtr.Zero;
        if (reader.TryReadPointer(ui + 0x770, out var fixedWorld) && Element(fixedWorld) is not null)
            world = fixedWorld;
        world = world == IntPtr.Zero ? ui : world;

        (string Id, string Name) ResolveNodeName(byte[] data)
        {
            // The current client stores the map identifier behind an unaligned payload pointer:
            // node +0x2F0 -> object +0x00 -> object +0x00 -> UTF-16 identifier.  Do not require
            // pointer alignment; ReadProcessMemory accepts the exact byte address and older builds
            // use the same representation.  Cache the result by the payload object, not the UI
            // element address, because virtualized children are recycled while the atlas pans.
            var payload = Pointer(data, 0x2F0);
            if (payload != IntPtr.Zero && namePayloadCache.TryGetValue(payload.ToInt64(), out var payloadName))
                return payloadName;

            string code = "";
            var storage = Pointer(data, AtlasDataStorage);
            var model = storage == IntPtr.Zero ? IntPtr.Zero : PointerAt(storage + AtlasDataModel);
            var cursor = model == IntPtr.Zero ? IntPtr.Zero : PointerAt(model + AtlasDataMapId);
            for (var hop = 0; hop < 6 && cursor != IntPtr.Zero; hop++)
            {
                var text = ReadUtf16(cursor);
                if (IsAtlasIdentifier(text)) { code = text; break; }
                cursor = PointerAt(cursor);
            }

            // The live +0x2F0 chain is the primary path. Keep the compact legacy +0x300 path for
            // older clients, but accept every valid Atlas identifier rather than only Map*; the
            // ExpeditionLogBook_* identifiers are real map nodes and have localized static metadata.
            if (code.Length == 0)
            {
                var row = Pointer(data, AtlasMapRow);
                if (row != IntPtr.Zero)
                {
                    var worldRow = PointerAt(row);
                    var direct = worldRow == IntPtr.Zero ? "" : ReadUtf16(worldRow);
                    if (IsAtlasIdentifier(direct)) code = direct;
                    else if (worldRow != IntPtr.Zero)
                    {
                        var idPointer = PointerAt(worldRow);
                        var id = idPointer == IntPtr.Zero ? "" : ReadUtf16(idPointer);
                        if (IsAtlasIdentifier(id)) code = id;
                    }
                }
            }

            // Build-drift fallback: a bounded set of payload fields may hold the same object graph.
            // This is intentionally not a heap scan and is used only when the primary paths fail.
            if (code.Length == 0)
            {
                foreach (var offset in new[] { 0x2F0, 0x2F8, 0x300, 0x308, 0x318, 0x320, 0x338, 0x340, 0x348, 0x350 })
                {
                    var probeCursor = Pointer(data, offset);
                    var seen = new HashSet<long>();
                    for (var hop = 0; hop < 6 && probeCursor != IntPtr.Zero && seen.Add(probeCursor.ToInt64()); hop++)
                    {
                        var text = ReadUtf16(probeCursor);
                        if (IsAtlasIdentifier(text)) { code = text; break; }
                        probeCursor = PointerAt(probeCursor);
                    }
                    if (code.Length != 0) break;
                }
            }

            (string Id, string Name) result;
            if (code.Length == 0)
            {
                result = ("", "名称未读取");
            }
            else
            {
                // atlas_maps.json includes both Map* and ExpeditionLogBook_* entries. Prefer the
                // shipped Traditional-Chinese name; fall back to a deterministic readable code.
                var display = DisplayTextLocalizer.Localize(code);
                if (POE2Radar.Core.Game.AtlasMapData.Shared.Get(code) is { } meta)
                    display = meta.LocalizedName("traditional chinese");
                else if (POE2Radar.Core.Game.ZoneGuide.Shared.Area(code) is { Name.Length: > 0 })
                    display = POE2Radar.Core.Game.ZoneGuide.Shared.FriendlyName(code);
                result = (code, string.IsNullOrWhiteSpace(display) ? code : display);
            }
            if (payload != IntPtr.Zero && result.Id.Length != 0)
                namePayloadCache[payload.ToInt64()] = result;
            return result;

            IntPtr PointerAt(IntPtr address) => reader.TryReadPointer(address, out var value) && value.ToInt64() > 0x10000 ? value : IntPtr.Zero;
            string ReadUtf16(IntPtr address) => reader.TryReadUtf16(address, 128, out var text) ? text : "";
            static bool IsAtlasIdentifier(string text)
            {
                if (text.Length is < 4 or > 96 || !char.IsAsciiLetter(text[0])) return false;
                for (var i = 1; i < text.Length; i++)
                    if (!(char.IsAsciiLetterOrDigit(text[i]) || text[i] == '_')) return false;
                // Map* is the common case. The known ExpeditionLogBook_* family is a real Atlas
                // map namespace; metadata lookup below also admits future shipped identifiers.
                return text.StartsWith("Map", StringComparison.Ordinal)
                    || text.StartsWith("ExpeditionLogBook_", StringComparison.Ordinal)
                    || POE2Radar.Core.Game.AtlasMapData.Shared.Get(text).HasValue
                    || POE2Radar.Core.Game.ZoneGuide.Shared.Area(text).HasValue;
            }
        }
        byte? ReadNodeRawState(byte[] data)
        {
            var storage = Pointer(data, AtlasDataStorage);
            if (storage == IntPtr.Zero || !reader.TryReadPointer(storage + AtlasDataModel, out var model) ||
                model.ToInt64() <= 0x10000)
                return null;
            return reader.TryReadBytes(model + AtlasModelState, 1, out var state) ? state[0] : null;
        }
        if (!Visible(world))
        {
            // A close/reopen recreates the Atlas payload. Invalidate immediately on the first
            // invisible sample so a quickly reopened map can never inherit the previous map's
            // retained nodes, names or projection. MainWindow keeps only a 140 ms visual grace
            // for transient rebuild frames, so delaying this reset only risks stale coordinates.
            if (atlasClosedAt == DateTime.MinValue)
            {
                atlasClosedAt = DateTime.UtcNow;
                ClearAtlasSessionCache();
            }
            return NativeAtlasSnapshot.Disabled(world == ui ? "世界地图已关闭或尚未初始化" : "世界地图已关闭");
        }
        atlasClosedAt = DateTime.MinValue;
        // If the legacy WorldScreen → MapControl → AtlasPanel chain is valid, use it as the
        // preferred BFS root.  Otherwise the UI root itself is the safe structural root; this
        // is what lets another user's client survive a field insertion or child-index drift.
        var atlas = world;
        if (world != ui && reader.TryReadPointer(world + 0x470, out var mapControl) &&
            reader.TryReadPointer(mapControl + 0x3C8, out var fixedAtlas) &&
            Element(fixedAtlas) is { } fixedAtlasData && Visible(fixedAtlas))
        {
            atlas = fixedAtlas;
            detectedAtlasVtable = Pointer(fixedAtlasData, 0).ToInt64();
        }

        // The atlas panel is not guaranteed to be the node canvas.  On the current client the
        // panel owns one or more intermediate containers and the actual canvas is the parent that
        // holds the largest group of elements with distinct grid coordinates.  The old direct-child
        // assumption is why a valid session could report exactly one node and zero edges.
        bool TryResolveNodeCanvas(IntPtr panel, IntPtr uiRoot, out IntPtr canvas, out long nodeVtable)
        {
            canvas = IntPtr.Zero; nodeVtable = 0;
            if (detectedNodeCanvas != 0 && detectedNodeVtable != 0 &&
                Element(new IntPtr(detectedNodeCanvas)) is { } cachedCanvas &&
                Visible(new IntPtr(detectedNodeCanvas)))
            {
                canvas = new IntPtr(detectedNodeCanvas);
                nodeVtable = detectedNodeVtable;
                return true;
            }
            if (DateTime.UtcNow < nextCanvasProbe) return false;
            nextCanvasProbe = DateTime.UtcNow.AddMilliseconds(750);

            // Do not bake the maintainer's current atlas bounds into detection.  Atlas grids are
            // account/session independent but their origin and extents legitimately move (for
            // example, live sessions can contain coordinates such as X=108,Y=-136).  The
            // reference implementation validates node classes via size/biome diversity; here we
            // only reject clearly corrupt integer payloads and let the class/topology score pick
            // the actual grid field.
            static bool InGrid(int x, int y) => Math.Abs((long)x) <= 10000 && Math.Abs((long)y) <= 10000;
            void DetectUiLayout(IReadOnlyList<IntPtr> elements)
            {
                var samples = elements.Select(Element).OfType<byte[]>().ToArray();
                if (samples.Length < 8) return;

                (int Valid, int Distinct) VectorScore(int offset)
                {
                    var coords = new HashSet<(int X, int Y)>();
                    var valid = 0;
                    foreach (var d in samples)
                    {
                        var x = F32(d, offset); var y = F32(d, offset + 4);
                        if (!double.IsFinite(x) || !double.IsFinite(y) || Math.Abs(x) > 200000 || Math.Abs(y) > 200000) continue;
                        valid++; coords.Add(((int)Math.Round(x * 10), (int)Math.Round(y * 10)));
                    }
                    return (valid, coords.Count);
                }
                var vector = UiRelativePosCandidates
                    .Select(offset => (Offset: offset, Score: VectorScore(offset)))
                    .OrderByDescending(x => x.Score.Valid * 1000 + x.Score.Distinct)
                    .First();
                if (vector.Score.Valid >= Math.Max(8, samples.Length / 2) && vector.Score.Distinct >= 6)
                    detectedRelativePosOffset = vector.Offset;

                int ScaleScore(int offset)
                {
                    var valid = 0;
                    var distinct = new HashSet<int>();
                    foreach (var d in samples)
                    {
                        var value = F32(d, offset);
                        if (!double.IsFinite(value) || value is < .05 or > 8) continue;
                        valid++; distinct.Add(BitConverter.SingleToInt32Bits((float)value));
                    }
                    return valid * 1000 + distinct.Count;
                }
                var scale = UiTransformScaleCandidates
                    .Select(offset => (Offset: offset, Score: ScaleScore(offset)))
                    .OrderByDescending(x => x.Score).First();
                if (scale.Score >= samples.Length / 2 * 1000)
                    detectedTransformScaleOffset = scale.Offset;

                int FlagScore(int offset)
                {
                    var nonZero = 0; var visible = 0;
                    foreach (var d in samples)
                    {
                        var value = U32(d, offset);
                        if (value != 0) nonZero++;
                        if ((value & 0x800) != 0) visible++;
                    }
                    return nonZero * 10 + visible;
                }
                var flags = UiFlagsCandidates
                    .Select(offset => (Offset: offset, Score: FlagScore(offset)))
                    .OrderByDescending(x => x.Score).First();
                if (flags.Score > 0) detectedFlagsOffset = flags.Offset;

                int SizeScore((int W, int H) offsets)
                {
                    var valid = 0;
                    foreach (var d in samples)
                    {
                        var w = F32(d, offsets.W); var h = F32(d, offsets.H);
                        if (double.IsFinite(w) && double.IsFinite(h) && w is >= 1 and <= 1024 && h is >= 1 and <= 1024)
                            valid++;
                    }
                    return valid;
                }
                var size = UiSizeCandidates
                    .Select(offsets => (Offsets: offsets, Score: SizeScore(offsets)))
                    .OrderByDescending(x => x.Score).First();
                if (size.Score >= Math.Max(8, samples.Length / 2))
                {
                    detectedSizeWOffset = size.Offsets.W;
                    detectedSizeHOffset = size.Offsets.H;
                }

                // The position-modifier field moved with the relative-position layout in the
                // same client revisions. Prefer a measured finite pair on elements carrying the
                // modifier bit; otherwise use the paired layout's known companion offset.
                var preferredModifier = detectedRelativePosOffset == 0x118 ? 0xF0 : 0x108;
                var modified = samples.Where(d => (U32(d, detectedFlagsOffset) & 0x400) != 0).ToArray();
                var modifier = UiPositionModifierCandidates
                    .Select(offset => (Offset: offset, Valid: modified.Count(d =>
                    double.IsFinite(F32(d, offset)) && double.IsFinite(F32(d, offset + 4)) &&
                    Math.Abs(F32(d, offset)) < 200000 && Math.Abs(F32(d, offset + 4)) < 200000)))
                    .OrderByDescending(x => x.Valid).First();
                detectedPositionModifierOffset = modified.Length > 0 && modifier.Valid >= Math.Max(4, modified.Length / 2)
                    ? modifier.Offset : preferredModifier;
            }
            var roots = new[] { panel, uiRoot };
            foreach (var root in roots.Distinct())
            {
                var queue = new Queue<IntPtr>();
                var visited = new HashSet<long>();
                var byVtable = new Dictionary<long, List<IntPtr>>();
                queue.Enqueue(root);
                while (queue.Count > 0 && visited.Count < 120000)
                {
                    var el = queue.Dequeue();
                    if (el == IntPtr.Zero || !visited.Add(el.ToInt64()) || Element(el) is not { } d) continue;
                    var vt = Pointer(d, 0);
                    if (IsModuleVtable(reader, module, vt))
                        (byVtable.TryGetValue(vt.ToInt64(), out var list) ? list : byVtable[vt.ToInt64()] = new()).Add(el);

                    if (!TryVector(reader, el + UiChildren, 8, 16384, out var childBytes, out _)) continue;
                    for (var i = 0; i < childBytes.Length / 8; i++)
                    {
                        var child = Pointer(childBytes, i * 8);
                        if (child != IntPtr.Zero) queue.Enqueue(child);
                    }
                }

                long bestVt = 0; var bestDistinct = 0; var bestGridOffset = AtlasGridPos;
                foreach (var (vt, list) in byVtable)
                {
                    if (list.Count < 8) continue;
                    foreach (var gridOffset in AtlasGridPosCandidates)
                    {
                        var coords = new HashSet<(int X, int Y)>();
                        var inRange = 0;
                        foreach (var el in list)
                        {
                            if (Element(el) is not { } d) continue;
                            var gx = I32(d, gridOffset);
                            var gy = I32(d, gridOffset + 4);
                            if (!InGrid(gx, gy)) continue;
                            inRange++; coords.Add((gx, gy));
                        }
                        if (inRange < Math.Max(8, list.Count / 2) || coords.Count < Math.Min(20, list.Count)) continue;
                        if (coords.Count > bestDistinct)
                        {
                            bestDistinct = coords.Count;
                            bestVt = vt;
                            bestGridOffset = gridOffset;
                        }
                    }
                }
                if (bestVt == 0 || !byVtable.TryGetValue(bestVt, out var nodes)) continue;
                var parentCount = new Dictionary<long, (IntPtr Parent, int Count)>();
                foreach (var el in nodes)
                {
                    if (Element(el) is not { } d) continue;
                    var parent = Pointer(d, UiParent);
                    if (parent == IntPtr.Zero) continue;
                    var prior = parentCount.GetValueOrDefault(parent.ToInt64());
                    parentCount[parent.ToInt64()] = (parent, prior.Count + 1);
                }
                var chosen = parentCount.Values.OrderByDescending(x => x.Count).FirstOrDefault();
                if (chosen.Parent == IntPtr.Zero || chosen.Count < 8) continue;
                detectedNodeCanvas = chosen.Parent.ToInt64();
                detectedNodeVtable = bestVt;
                detectedGridOffset = bestGridOffset;
                DetectUiLayout(nodes);
                nextCanvasProbe = DateTime.MinValue;
                canvas = chosen.Parent;
                nodeVtable = bestVt;
                // Locate the current-map marker structurally. It is the non-node UI element whose
                // +0x300 points to one of the discovered node elements; this survives class-vtable drift.
                var nodeSet = nodes.Select(n => n.ToInt64()).ToHashSet();
                foreach (var el in visited.Select(p => new IntPtr(p)))
                {
                    if (nodeSet.Contains(el.ToInt64()) || Element(el) is not { } d) continue;
                    var targetNode = Pointer(d, AtlasCurrentMarkerNode);
                    if (targetNode != IntPtr.Zero && nodeSet.Contains(targetNode.ToInt64()))
                    { detectedCurrentMarker = el.ToInt64(); break; }
                }
                return true;
            }
            detectedNodeCanvas = detectedNodeVtable = detectedCurrentMarker = 0;
            return false;
        }

        if (!TryResolveNodeCanvas(atlas, ui, out var canvas, out var nodeVtable) ||
            Element(canvas) is not { } canvasData ||
            Origin(canvas) is not { } atlasOrigin ||
            !TryVector(reader, canvas + UiChildren, 8, 20000, out var children, out var childHeader))
            return NativeAtlasSnapshot.Disabled("Atlas 布局正在变化");
        // Connection-vector placement moved between client layouts (+0x590 / +0x5A8).
        // Probe the candidate headers and remember the one that has a sane std::vector shape;
        // this keeps edge topology tied to the current process instead of the maintainer build.
        byte[] edgeHeaderProbe = Array.Empty<byte>();
        foreach (var offset in AtlasConnectionCandidates.Distinct())
        {
            if (!reader.TryReadBytes(canvas + offset, 24, out var header) || !LooksLikeVectorHeader(header, 20, 50000)) continue;
            edgeHeaderProbe = header;
            detectedConnectionsOffset = offset;
            break;
        }
        if (edgeHeaderProbe.Length == 0 || !reader.TryReadBytes(canvas + detectedTransformScaleOffset, 0x24, out var layoutProbe))
            return NativeAtlasSnapshot.Disabled("地图布局正在更新");
        var atlasScale = F32(canvasData, detectedTransformScaleOffset);
        if (!double.IsFinite(atlasScale) || atlasScale is < .05 or > 8)
        {
            return NativeAtlasSnapshot.Disabled("地图缩放数据无效");
        }

        var nodeFingerprint = ComputeNodeFingerprint(reader, children, detectedGridOffset,
            detectedRelativePosOffset, detectedFlagsOffset);
        // A map pan/rebuild can recycle the same UI child address for a new payload.  Invalidate
        // payload-name entries whenever the live canvas/fingerprint changes; this keeps the fast
        // name cache from attaching a previous node's label to a recycled child while preserving
        // the no-rebuild fast path for stable frames.
        if (cachedCanvasAddress != canvas.ToInt64() || cachedWorldAddress != world.ToInt64() ||
            cachedNodeFingerprint != nodeFingerprint)
            namePayloadCache.Clear();
        GridPoint? ReadDirectGrid()
        {
            if (!reader.TryReadBytes(canvas + 0x660, 8, out var currentBytes)) return null;
            var canvasGrid = new GridPoint(I32(currentBytes, 0), I32(currentBytes, 4));
            // The controller and canvas expose the same live grid through independent chains.
            // During an Atlas rebuild, a half-updated chain can briefly contain another valid
            // map grid. Treat disagreement as transient instead of replacing a known location.
            if (reader.TryReadPointer(canvas + 0x308, out var controller) &&
                reader.TryReadPointer(controller + 0x1B0, out var stateData) &&
                reader.TryReadBytes(stateData + 0x3E68, 8, out var liveGrid) &&
                BitConverter.ToInt64(liveGrid) != 0)
            {
                var controllerGrid = new GridPoint(I32(liveGrid, 0), I32(liveGrid, 4));
                return controllerGrid == canvasGrid ? controllerGrid : null;
            }
            return canvasGrid;
        }

        GridPoint? ReadMarkerGrid(IReadOnlyList<RuntimeAtlasNode> knownNodes)
        {
            var markerAddress = detectedCurrentMarker != 0 ? new IntPtr(detectedCurrentMarker) : IntPtr.Zero;
            if (markerAddress == IntPtr.Zero || Element(markerAddress) is not { } markerData)
                return null;

            // The marker is the game's own "you are here" element. Re-read its target on every
            // sample and require that target to be one of this frame's node elements; a recycled
            // UI child must never carry a previous map's location into the new snapshot.
            var markerNode = Pointer(markerData, AtlasCurrentMarkerNode);
            var match = knownNodes.FirstOrDefault(n => n.Address == markerNode.ToInt64());
            return match is null ? null : match.Grid;
        }

        // The map can be sampled much faster than it can be rebuilt. If the child vector, edge
        // header, layout bytes and sparse live positions are unchanged, translate the last
        // validated full snapshot by the canvas-origin delta instead of rereading every node.
        // A hard 250 ms deadline still refreshes hidden flags and names when the topology is idle.
        var sampleNow = DateTime.UtcNow;
        if (retainedCanvasAddress != 0 &&
            (retainedCanvasAddress != canvas.ToInt64() || retainedWorldAddress != world.ToInt64()))
        {
            retainedNodes.Clear();
            retainedEdges.Clear();
            retainedTransformValid = false;
        }
        if (!retainedTransformValid)
        {
            retainedCanvasAddress = canvas.ToInt64();
            retainedWorldAddress = world.ToInt64();
            retainedCanvasOrigin = atlasOrigin;
            retainedCanvasScale = atlasScale;
            retainedTransformValid = true;
        }
        var sameStructure = cachedSnapshot is { Available: true } &&
            sampleNow - lastFullRefreshAt < TimeSpan.FromMilliseconds(FullRefreshIntervalMs) &&
            cachedCanvasAddress == canvas.ToInt64() && cachedWorldAddress == world.ToInt64() &&
            cachedChildrenBytes.AsSpan().SequenceEqual(children) &&
            cachedEdgeHeader.AsSpan().SequenceEqual(edgeHeaderProbe) &&
            cachedLayout.AsSpan().SequenceEqual(layoutProbe) &&
            cachedNodeFingerprint == nodeFingerprint;
        if (sameStructure && cachedSnapshot is { } previous)
        {
            var shifted = TransformNodes(previous.Nodes, cachedCanvasOrigin, atlasOrigin,
                cachedCanvasScale, atlasScale);
            if (shifted != null)
            {
                var fastKnownGrids = shifted.Select(n => n.Grid).ToHashSet();
                var fastCurrentGrid = SelectCurrentGrid(ReadMarkerGrid(previous.Nodes), ReadDirectGrid(), fastKnownGrids);
                var fastPlayer = previous.Player is { } cachedPlayer
                    ? TransformPoint(cachedPlayer, cachedCanvasOrigin, atlasOrigin, cachedCanvasScale, atlasScale)
                    : (PixelPoint?)null;
                GridPoint? fastCurrentNode = fastCurrentGrid is { } currentGrid && shifted.Any(n => n.Grid == currentGrid)
                    ? currentGrid
                    : null;
                var fast = previous with
                {
                    Nodes = shifted,
                    Player = fastPlayer,
                    CurrentNode = fastCurrentNode,
                    ReadMilliseconds = watch.Elapsed.TotalMilliseconds,
                    CapturedAt = sampleNow,
                };
                cachedSnapshot = fast;
                cachedCanvasOrigin = atlasOrigin;
                cachedCanvasScale = atlasScale;
                return fast;
            }
        }
        var nodes = new List<RuntimeAtlasNode>();
        var grids = new HashSet<GridPoint>();
        for (var i = 0; i < children.Length / 8; i++)
        {
            var address = Pointer(children, i * 8);
            if (Element(address) is not { } d || Pointer(d, 0).ToInt64() != nodeVtable) continue;
            if (Pointer(d, UiParent) != canvas) continue;
            var grid = new GridPoint(I32(d, detectedGridOffset), I32(d, detectedGridOffset + 4));
            if (Math.Abs((long)grid.X) > 100000 || Math.Abs((long)grid.Y) > 100000 || !grids.Add(grid)) continue;
            var scale = F32(d, detectedTransformScaleOffset);
            if (!double.IsFinite(scale) || scale is < .05 or > 8) { grids.Remove(grid); continue; }
            cache[address.ToInt64()] = d;
            if (Origin(address) is not { } origin) { grids.Remove(grid); continue; }
            var x = origin.X + F32(d, detectedSizeWOffset) * scale / 2;
            var y = origin.Y + F32(d, detectedSizeHOffset) * scale / 2;
            if (!double.IsFinite(x) || !double.IsFinite(y) || Math.Abs(x) > 1000000 || Math.Abs(y) > 1000000) { grids.Remove(grid); continue; }
            // Resolve from the current payload first.  Virtualized children are recycled while
            // panning; an address-keyed cache would attach the previous map name to this grid.
            var name = ResolveNodeName(d);
            if (!string.IsNullOrEmpty(name.Id) && names.TryGetValue(name.Id, out var cachedName))
                name = cachedName;
            else if (!string.IsNullOrEmpty(name.Id))
                names[name.Id] = name;
            // Fog/virtualized nodes can legitimately have no map row until the player reveals
            // them. Keep them routable and uniquely addressable using the live grid identity.
            if (string.IsNullOrEmpty(name.Id))
                name = ($"MapUnknown_{grid.X}_{grid.Y}", $"未探索节点 ({grid.X},{grid.Y})");
            // Grid coordinates are the stable identity.  A fogged node can gain its map code after
            // a reveal; including AreaId here would renumber the same point during a pan/reveal.
            var identity = $"{grid.X}|{grid.Y}";
            if (!stableNumbers.TryGetValue(identity, out var number))
                stableNumbers[identity] = number = nextStableNumber++;
            var hidden = (U32(d, detectedFlagsOffset) & 0x800) == 0;
            nodes.Add(new(number, address.ToInt64(), grid, x, y, name.Name, name.Id, hidden, ReadNodeRawState(d), ResolveContentTags(reader, d)));
        }
        if (nodes.Count == 0) return NativeAtlasSnapshot.Disabled("终局节点尚未加载");
        // 节点会因视口平移被回收。不要把未出现在本帧的子节点重新塞回结果：
        // 它们的 RelativePos 已经被游戏重写或失效，沿用旧像素会把点位留在旧视口。
        // 只发布本帧通过一致性校验的 live 节点，宁可短暂少显示也不显示错位点。
        byte[] edgeBytes = Array.Empty<byte>(), edgeHeader = Array.Empty<byte>();
        foreach (var offset in AtlasConnectionCandidates.Distinct())
        {
            if (!TryVector(reader, canvas + offset, 20, 50000, out var candidateBytes, out var candidateHeader)) continue;
            // Prefer the vector whose endpoints overlap the nodes just read.  A stale field can
            // still look like a valid empty vector; only accept it as a last resort.
            var endpointHits = 0;
            for (var probeOffset = 0; probeOffset + 20 <= candidateBytes.Length; probeOffset += 20)
            {
                var a = new GridPoint(I32(candidateBytes, probeOffset + 4), I32(candidateBytes, probeOffset + 8));
                var b = new GridPoint(I32(candidateBytes, probeOffset + 12), I32(candidateBytes, probeOffset + 16));
                if (grids.Contains(a) && grids.Contains(b)) endpointHits++;
            }
            if (edgeHeader.Length == 0 || endpointHits > 0 || candidateBytes.Length == 0)
            {
                edgeBytes = candidateBytes; edgeHeader = candidateHeader; detectedConnectionsOffset = offset;
                if (endpointHits > 0 || candidateBytes.Length == 0) break;
            }
        }
        if (edgeHeader.Length == 0)
            return NativeAtlasSnapshot.Disabled("连接表正在变化");
        var edges = new List<RuntimeAtlasEdge>();
        var seenEdges = new HashSet<(GridPoint A, GridPoint B)>();
        for (var offset = 0; offset < edgeBytes.Length; offset += 20)
        {
            var a = new GridPoint(I32(edgeBytes, offset + 4), I32(edgeBytes, offset + 8));
            var b = new GridPoint(I32(edgeBytes, offset + 12), I32(edgeBytes, offset + 16));
            if (!grids.Contains(a) || !grids.Contains(b) || a == b) continue;
            var key = NormalizeEdge(a, b);
            if (!seenEdges.Add(key)) continue;
            // 合法地图边的网格跨度很小。拒绝跨视口/损坏数据产生的长线。
            var gridDistance = Math.Abs((long)a.X - b.X) + Math.Abs((long)a.Y - b.Y);
            if (gridDistance > 16) continue;
            edges.Add(new(a, b));
        }
        // Keep topology observed in earlier virtualized frames. The edge vector is read-only and
        // belongs to this canvas; retaining only validated short-span pairs lets newly materialized
        // nodes connect to nodes that were temporarily outside the UI child list.
        foreach (var edge in edges)
            retainedEdges.Add(NormalizeEdge(edge.A, edge.B));
        PixelPoint? player = null;
        var markerAddress = detectedCurrentMarker != 0 ? new IntPtr(detectedCurrentMarker) : IntPtr.Zero;
        // Prefer the structurally identified marker. The direct fields are retained only as a
        // compatibility fallback for clients where the marker is not present yet.
        GridPoint? currentNode = SelectCurrentGrid(ReadMarkerGrid(nodes), ReadDirectGrid(), grids);
        if (markerAddress != IntPtr.Zero && Element(markerAddress) is { } markerData)
        {
            var markerNode = Pointer(markerData, AtlasCurrentMarkerNode);
            if (Visible(markerAddress) && Origin(markerAddress) is { } mp)
                player = new(mp.X + F32(markerData, detectedSizeWOffset) * F32(markerData, detectedTransformScaleOffset) / 2,
                    mp.Y + F32(markerData, detectedSizeHOffset) * F32(markerData, detectedTransformScaleOffset) / 2);
        }
        if (player is null && reader.TryReadPointer(canvas + 0x418, out var marker) && Element(marker) is { } md &&
            Pointer(md, UiParent) == canvas && Visible(marker) && Origin(marker) is { } fallbackMarker)
            player = new(fallbackMarker.X + F32(md, detectedSizeWOffset) * F32(md, detectedTransformScaleOffset) / 2,
                fallbackMarker.Y + F32(md, detectedSizeHOffset) * F32(md, detectedTransformScaleOffset) / 2);

        // Reject torn snapshots instead of retaining an old overlay during transitions.
        if (!reader.TryReadBytes(canvas + UiChildren, 24, out var lastChildren) || !lastChildren.SequenceEqual(childHeader) ||
            !reader.TryReadBytes(canvas + detectedConnectionsOffset, 24, out var lastEdges) || !lastEdges.SequenceEqual(edgeHeader) ||
            !reader.TryReadInt32(world + detectedFlagsOffset, out var lastFlags) || (lastFlags & 0x800) == 0 ||
            !reader.TryReadBytes(canvas + detectedTransformScaleOffset, 0x24, out var lastLayout) || !lastLayout.SequenceEqual(canvasData.AsSpan(detectedTransformScaleOffset, 0x24).ToArray()))
            return NativeAtlasSnapshot.Disabled("地图正在更新，等待一致快照");
        var liveNodeCount = nodes.Count;
        var liveEdgeCount = edges.Count;
        // Move retained positions into the current canvas frame before replacing entries observed
        // in this sample. This is a translation + uniform zoom transform, matching the game's
        // canvas projection and keeping off-screen nodes aligned without stale raw coordinates.
        TransformRetainedNodes(atlasOrigin, atlasScale);
        foreach (var node in nodes) retainedNodes[node.Grid] = node;
        var allNodes = retainedNodes.Values.OrderBy(n => n.Number).ToArray();
        var allEdges = retainedEdges.Select(e => new RuntimeAtlasEdge(e.A, e.B)).ToArray();
        var result = new NativeAtlasSnapshot(true,
            $"内存：{allNodes.Length} 个节点，{allEdges.Length} 条连接（本帧 {liveNodeCount} / {liveEdgeCount}）",
            allNodes, allEdges, player,
            watch.Elapsed.TotalMilliseconds, DateTime.UtcNow)
        {
            CurrentNode = currentNode,
            TopologyHash = ComputeTopologyHash(allNodes, allEdges),
        };
        cachedSnapshot = result;
        cachedChildrenBytes = children.ToArray();
        cachedEdgeHeader = edgeHeader.ToArray();
        cachedLayout = layoutProbe.ToArray();
        cachedNodeFingerprint = nodeFingerprint;
        cachedCanvasAddress = canvas.ToInt64();
        cachedWorldAddress = world.ToInt64();
        cachedCanvasOrigin = atlasOrigin;
        cachedCanvasScale = atlasScale;
        lastFullRefreshAt = DateTime.UtcNow;
        return result;
    }

    // Structural UI-root validation shared by the bootstrap probe and the per-tick resolver.
    // It intentionally checks only self/children vector shape; no absolute address, account
    // state, map name, or maintainer snapshot is involved.
    static bool LooksLikeUiElement(GameMemoryReader reader, IntPtr address)
    {
        if (address == IntPtr.Zero || !reader.TryReadPointer(address + UiSelf, out var self) || self != address)
            return false;
        if (!reader.TryReadPointer(address + UiChildren, out var first) || first == IntPtr.Zero)
            return false;
        if (!reader.TryReadPointer(address + UiChildrenEnd, out var last) || last < first)
            return false;
        var count = (last.ToInt64() - first.ToInt64()) / IntPtr.Size;
        return count is >= 0 and <= 20000;
    }

    static bool HasUiRoot(GameMemoryReader reader, IntPtr gameState)
    {
        // Active InGameState candidates: current direct pointer, current-state vector first
        // element, and the historical fixed slot table used by older clients.
        var candidates = new List<IntPtr>();
        void Add(IntPtr p)
        {
            if (p != IntPtr.Zero && p.ToInt64() > 0x10000 && !candidates.Contains(p)) candidates.Add(p);
        }
        if (reader.TryReadPointer(gameState + 0x90, out var direct)) Add(direct);
        if (reader.TryReadPointer(gameState + 0x08, out var current)) Add(current);
        for (var i = 0; i < 12; i++)
            if (reader.TryReadPointer(gameState + 0x48 + i * 0x10, out var slot)) Add(slot);

        foreach (var candidate in candidates)
            foreach (var uiOffset in new[] { 0x2F0, 0x300 })
                if (reader.TryReadPointer(candidate + uiOffset, out var ui) && LooksLikeUiElement(reader, ui))
                    return true;
        return false;
    }

    static bool LooksLikeVectorHeader(byte[] header, int stride, int limit)
    {
        if (header.Length < 24 || stride <= 0 || limit <= 0) return false;
        var first = Pointer(header, 0).ToInt64();
        var last = Pointer(header, 8).ToInt64();
        var cap = Pointer(header, 16).ToInt64();
        if (first == 0 && last == 0 && cap == 0) return true;
        return first >= 0x10000 && last >= first && cap >= last
            && last - first <= (long)stride * limit
            && (last - first) % stride == 0;
    }

    static bool IsModuleVtable(GameMemoryReader reader, MemoryModule module, IntPtr value)
    {
        var v = value.ToInt64();
        var start = module.BaseAddress.ToInt64();
        var end = start + module.Size;
        return v >= start && v < end && (v & (IntPtr.Size - 1)) == 0 && reader.IsReadable(value, IntPtr.Size);
    }

    static (GridPoint A, GridPoint B) NormalizeEdge(GridPoint a, GridPoint b) =>
        a.X < b.X || (a.X == b.X && a.Y <= b.Y) ? (a, b) : (b, a);

    static IReadOnlyList<RuntimeAtlasNode>? TransformNodes(IReadOnlyList<RuntimeAtlasNode> source,
        PixelPoint fromOrigin, PixelPoint toOrigin, double fromScale, double toScale)
    {
        if (!double.IsFinite(fromScale) || !double.IsFinite(toScale) || fromScale < .05 || toScale < .05)
            return null;
        var ratio = toScale / fromScale;
        var dx = toOrigin.X - fromOrigin.X;
        var dy = toOrigin.Y - fromOrigin.Y;
        if (!double.IsFinite(ratio) || ratio < .1 || ratio > 10 ||
            !double.IsFinite(dx) || !double.IsFinite(dy) || Math.Abs(dx) > 10000 || Math.Abs(dy) > 10000)
            return null;
        if (Math.Abs(ratio - 1) < 0.000001 && Math.Abs(dx) < 0.001 && Math.Abs(dy) < 0.001)
            return source;
        var shifted = new RuntimeAtlasNode[source.Count];
        for (var i = 0; i < source.Count; i++)
        {
            var point = TransformPoint(new PixelPoint(source[i].X, source[i].Y),
                fromOrigin, toOrigin, fromScale, toScale);
            shifted[i] = source[i] with { X = point.X, Y = point.Y };
        }
        return shifted;
    }

    static PixelPoint TransformPoint(PixelPoint point, PixelPoint fromOrigin, PixelPoint toOrigin,
        double fromScale, double toScale)
    {
        var ratio = toScale / fromScale;
        return new(toOrigin.X + (point.X - fromOrigin.X) * ratio,
            toOrigin.Y + (point.Y - fromOrigin.Y) * ratio);
    }

    void TransformRetainedNodes(PixelPoint atlasOrigin, double atlasScale)
    {
        if (!retainedTransformValid)
        {
            retainedCanvasOrigin = atlasOrigin;
            retainedCanvasScale = atlasScale;
            retainedTransformValid = true;
            return;
        }
        var transformed = TransformNodes(retainedNodes.Values.ToArray(), retainedCanvasOrigin,
            atlasOrigin, retainedCanvasScale, atlasScale);
        if (transformed == null)
        {
            retainedNodes.Clear();
            retainedEdges.Clear();
            retainedTransformValid = false;
            retainedCanvasOrigin = atlasOrigin;
            retainedCanvasScale = atlasScale;
            retainedTransformValid = true;
            return;
        }
        foreach (var node in transformed) retainedNodes[node.Grid] = node;
        retainedCanvasOrigin = atlasOrigin;
        retainedCanvasScale = atlasScale;
    }

    static ulong ComputeNodeFingerprint(GameMemoryReader reader, byte[] children, int gridOffset,
        int relativeOffset, int flagsOffset)
    {
        // Sample at most twelve live elements. The periodic full refresh catches unsampled flag
        // changes; this cheap guard exists to detect a pan/recycle before serving translated data.
        ulong hash = 1469598103934665603UL;
        var count = children.Length / IntPtr.Size;
        if (count == 0) return hash;
        var samples = Math.Min(12, count);
        for (var i = 0; i < samples; i++)
        {
            var index = samples == 1 ? 0 : (int)((long)i * (count - 1) / (samples - 1));
            var address = Pointer(children, index * IntPtr.Size);
            if (address == IntPtr.Zero) continue;
            hash = Mix(hash, unchecked((ulong)address.ToInt64()));
            if (reader.TryReadBytes(address + relativeOffset, 8, out var rel))
                foreach (var b in rel) hash = Mix(hash, b);
            if (reader.TryReadBytes(address + gridOffset, 8, out var grid))
                foreach (var b in grid) hash = Mix(hash, b);
            if (reader.TryReadBytes(address + flagsOffset, 4, out var flags))
                foreach (var b in flags) hash = Mix(hash, b);
        }
        return hash;

        static ulong Mix(ulong state, ulong value)
        {
            state ^= value;
            return state * 1099511628211UL;
        }
    }
    static long ComputeTopologyHash(IReadOnlyList<RuntimeAtlasNode> nodes, IReadOnlyList<RuntimeAtlasEdge> edges)
    {
        // Sort grid keys so viewport reordering does not invalidate the route cache.  This hash is local
        // process state only; it is not persisted or used as a security identifier.
        static long Pack(GridPoint p) => ((long)p.X << 32) ^ (uint)p.Y;
        var nodeKeys = new long[nodes.Count];
        for (var i = 0; i < nodes.Count; i++) nodeKeys[i] = Pack(nodes[i].Grid);
        Array.Sort(nodeKeys);
        var edgeKeys = new long[edges.Count];
        for (var i = 0; i < edges.Count; i++)
        {
            var a = Pack(edges[i].A); var b = Pack(edges[i].B);
            if (a > b) (a, b) = (b, a);
            edgeKeys[i] = HashCode.Combine(a, b);
        }
        Array.Sort(edgeKeys);
        var hash = new HashCode();
        hash.Add(nodes.Count); hash.Add(edges.Count);
        foreach (var key in nodeKeys) hash.Add(key);
        // State changes must invalidate the route cache even when the graph geometry is
        // unchanged: a newly accessible node can be a shorter optimal starting point.
        foreach (var node in nodes.OrderBy(n => Pack(n.Grid)))
        {
            hash.Add((int)node.State);
            hash.Add(node.IsHidden);
        }
        foreach (var key in edgeKeys) hash.Add(key);
        return hash.ToHashCode();
    }

    public static bool TryVector(GameMemoryReader reader, IntPtr address, int stride, int limit, out byte[] data, out byte[] header)
    {
        data = header = Array.Empty<byte>();
        if (!reader.TryReadBytes(address, 24, out header)) return false;
        var first = Pointer(header, 0).ToInt64();
        var last = Pointer(header, 8).ToInt64();
        var cap = Pointer(header, 16).ToInt64();
        if (first == 0 && last == 0 && cap == 0) return true;
        if (first < 0x10000 || last < first || cap < last || last - first > (long)stride * limit || (last - first) % stride != 0) return false;
        if (last == first) return true;
        return reader.TryReadBytes(new(first), (int)(last - first), out data) && reader.TryReadBytes(address, 24, out var after) && after.SequenceEqual(header);
    }

    static IntPtr Pointer(byte[] d, int o) => new(BitConverter.ToInt64(d, o));
    static int I32(byte[] d, int o) => BitConverter.ToInt32(d, o);
    static uint U32(byte[] d, int o) => BitConverter.ToUInt32(d, o);
    static double F32(byte[] d, int o) => BitConverter.ToSingle(d, o);

    /// <summary>
    /// Reads the localized payload rendered by the current Atlas node.  On the live 0.5.x client
    /// the node's +0x2D0 pointer is a UTF-16 block containing the map name, biome, headline content
    /// and its description (for example "宏偉之鏡" followed by "含有一個[MapBoss|地圖頭目]的映像").
    /// This is deliberately a read-only, bounded fallback: older layouts may not have the field and
    /// simply return an empty tag list.  Bracket display names and known English aliases are retained
    /// so search works with Traditional Chinese, Simplified Chinese, or the English content key.
    static IReadOnlyList<string> ResolveContentTags(GameMemoryReader reader, byte[] data)
    {
        var payload = Pointer(data, 0x2D0);
        if (payload == IntPtr.Zero || !reader.TryReadBytes(payload, 512, out var payloadBytes))
            return Array.Empty<string>();
        // This UI payload is a fixed-capacity text buffer: the first string is NUL-terminated,
        // but the following bytes may already belong to the next recycled node.  Do not require
        // a terminator at the end of the remote read (TryReadUtf16 would reject a valid prefix).
        var chars = System.Text.Encoding.Unicode.GetChars(payloadBytes);
        var end = Array.FindIndex(chars, c => c == '\0');
        var raw = new string(chars, 0, end >= 0 ? end : chars.Length);
        if (raw.Length == 0) return Array.Empty<string>();
        var tags = new List<string>(8);
        foreach (var line0 in raw.Replace("\r", "", StringComparison.Ordinal).Split('\n'))
        {
            var line = line0.Trim();
            if (line.Length < 2 || line.Length > 96 || line.StartsWith("區域", StringComparison.Ordinal)
                || line.StartsWith("玩家", StringComparison.Ordinal) || line.StartsWith("怪物", StringComparison.Ordinal)
                || line.StartsWith("增加", StringComparison.Ordinal) || line.StartsWith("含有", StringComparison.Ordinal))
                continue;
            // The first two lines are map name and biome, not node content.
            if (tags.Count == 0 || tags.Count == 1) { /* still inspect bracket labels below */ }
            if (!tags.Contains(line, StringComparer.Ordinal)) tags.Add(line);
            foreach (var alias in ContentAliases(line))
                if (!tags.Contains(alias, StringComparer.OrdinalIgnoreCase)) tags.Add(alias);
        }
        // Descriptions often carry the useful [Code|localized display] labels even when their whole
        // line is intentionally omitted above.
        foreach (System.Text.RegularExpressions.Match m in System.Text.RegularExpressions.Regex.Matches(raw, @"\[([^\]|]+)(?:\|([^\]]+))?\]"))
        {
            var display = m.Groups[2].Success ? m.Groups[2].Value.Trim() : m.Groups[1].Value.Trim();
            if (display.Length is < 2 or > 64) continue;
            if (!tags.Contains(display, StringComparer.Ordinal)) tags.Add(display);
            foreach (var alias in ContentAliases(display))
                if (!tags.Contains(alias, StringComparer.OrdinalIgnoreCase)) tags.Add(alias);
            var code = m.Groups[1].Value.Trim();
            foreach (var alias in ContentAliases(code))
                if (!tags.Contains(alias, StringComparer.OrdinalIgnoreCase)) tags.Add(alias);
        }
        // Remove the map name and biome lines that were accepted as ordinary text above.
        if (raw.Contains('\n'))
        {
            var first = raw.Replace("\r", "", StringComparison.Ordinal).Split('\n', StringSplitOptions.RemoveEmptyEntries)
                .Take(2).Select(s => s.Trim()).ToHashSet(StringComparer.Ordinal);
            tags.RemoveAll(t => first.Contains(t));
        }
        return tags;

        static IEnumerable<string> ContentAliases(string text)
        {
            if (text.Contains("宏偉之鏡", StringComparison.Ordinal) || text.Contains("宏伟之镜", StringComparison.Ordinal) ||
                text.Contains("Grand Mirror", StringComparison.OrdinalIgnoreCase)) yield return "Grand Mirror";
            if (text.Contains("強大地圖頭目", StringComparison.Ordinal) || text.Contains("强大地图头目", StringComparison.Ordinal) ||
                text.Contains("Powerful Map Boss", StringComparison.OrdinalIgnoreCase)) yield return "Powerful Map Boss";
            if (text.Contains("致命地圖頭目", StringComparison.Ordinal) || text.Contains("致命地图头目", StringComparison.Ordinal) ||
                text.Contains("Deadly Map Boss", StringComparison.OrdinalIgnoreCase)) yield return "Deadly Map Boss";
            if (text.Contains("譫妄", StringComparison.Ordinal) || text.Contains("谵妄", StringComparison.Ordinal) ||
                text.Contains("Delirium", StringComparison.OrdinalIgnoreCase)) yield return "Delirium";
            if (text.Contains("破碎幻鏡", StringComparison.Ordinal) || text.Contains("破碎幻镜", StringComparison.Ordinal) ||
                text.Contains("Fragmented Mirror", StringComparison.OrdinalIgnoreCase)) yield return "Fragmented Mirror";
            if (text.Contains("魂靈遷徙", StringComparison.Ordinal) || text.Contains("魂灵迁徙", StringComparison.Ordinal) ||
                text.Contains("Spirit Migration", StringComparison.OrdinalIgnoreCase)) yield return "Spirit Migration";
            if (text.Contains("魂靈蜂擁", StringComparison.Ordinal) || text.Contains("魂灵蜂拥", StringComparison.Ordinal) ||
                text.Contains("Swarming Spirits", StringComparison.OrdinalIgnoreCase)) yield return "Swarming Spirits";
            if (text.Contains("魂靈指引", StringComparison.Ordinal) || text.Contains("魂灵指引", StringComparison.Ordinal) ||
                text.Contains("Spirit Guide", StringComparison.OrdinalIgnoreCase)) yield return "Spirit Guide";
        }
    }

    /// <summary>
    /// Selects the current atlas node without allowing a stale or out-of-frame value through.
    /// The marker is authoritative; the two direct fields are only a compatibility fallback.
    /// </summary>
    public static GridPoint? SelectCurrentGrid(GridPoint? markerGrid, GridPoint? directGrid,
        IReadOnlySet<GridPoint> frameGrids)
    {
        if (markerGrid is { } marker && frameGrids.Contains(marker)) return marker;
        if (directGrid is { } direct && frameGrids.Contains(direct)) return direct;
        return null;
    }
}

public readonly record struct GridPoint(int X, int Y)
{
    public override string ToString() => $"{X},{Y}";
}
public readonly record struct PixelPoint(double X, double Y);
public enum RuntimeAtlasNodeState
{
    Unknown = -1,
    Completed = 0,
    Accessible = 1,
    VisibleLocked = 255,
    Hidden = -2,
}

public sealed record RuntimeAtlasNode(int Number, long Address, GridPoint Grid, double X, double Y, string Name, string AreaId, bool IsHidden, byte? RawState, IReadOnlyList<string>? ContentTags = null)
{
    public IReadOnlyList<string> Tags => ContentTags ?? Array.Empty<string>();
    public RuntimeAtlasNodeState State => IsHidden
        ? RuntimeAtlasNodeState.Hidden
        : RawState switch
        {
            0 => RuntimeAtlasNodeState.Completed,
            1 => RuntimeAtlasNodeState.Accessible,
            255 => RuntimeAtlasNodeState.VisibleLocked,
            _ => RuntimeAtlasNodeState.Unknown,
        };

    public bool CanOpen => State == RuntimeAtlasNodeState.Accessible;

    public string StateText => State switch
    {
        RuntimeAtlasNodeState.Completed => "已完成",
        RuntimeAtlasNodeState.Accessible => "可见已开启",
        RuntimeAtlasNodeState.VisibleLocked => "可见未开启",
        RuntimeAtlasNodeState.Hidden => "隐藏",
        _ => "状态未知",
    };
}
public sealed record RuntimeAtlasEdge(GridPoint A, GridPoint B);
public sealed record NativeAtlasSnapshot(bool Available, string Reason, IReadOnlyList<RuntimeAtlasNode> Nodes,
    IReadOnlyList<RuntimeAtlasEdge> Edges, PixelPoint? Player, double ReadMilliseconds, DateTime CapturedAt)
{
    public GridPoint? CurrentNode { get; init; }
    /// <summary>Stable-in-process hash of node grids + edge endpoints.  Viewport panning and node order do
    /// not change it, so route planners can reuse a path while the map is being translated.</summary>
    public long TopologyHash { get; init; }
    public static NativeAtlasSnapshot Disabled(string reason) => new(false, reason, Array.Empty<RuntimeAtlasNode>(), Array.Empty<RuntimeAtlasEdge>(), null, 0, DateTime.UtcNow);
}
