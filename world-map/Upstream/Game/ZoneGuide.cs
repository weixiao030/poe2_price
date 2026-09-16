using System.Reflection;
using System.Text.Json;

namespace POE2Radar.Core.Game;

/// <summary>
/// Static zone reference data: resolves a PoE2 area code (e.g. <c>G1_1</c>, <c>P1_Town</c>) to a
/// friendly name + act + monster level, and surfaces optional per-zone / per-act leveling notes.
/// This closes the long-standing "friendly area Name string" gap (we only had the raw code from
/// memory) using a static table rather than another memory read.
///
/// <para>Two embedded tables: <c>world_areas.json</c> (code → name/act/level/waypoint/town) and
/// <c>zone_notes.json</c> (community leveling notes — per-zone by code, per-act fallback). Read-only;
/// loaded once (cf. <see cref="EntityNameResolver"/>, <see cref="CustomLandmarkData"/>).</para>
/// </summary>
public sealed class ZoneGuide
{
    /// <summary>A zone's static metadata. <see cref="Act"/>/<see cref="Level"/> are 0 when unknown.</summary>
    public readonly record struct ZoneArea(string Name, int Act, int Level, bool Waypoint, bool Town);

    private readonly Dictionary<string, ZoneArea> _areas = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<string, string> _zoneNotes = new(StringComparer.OrdinalIgnoreCase); // code → notes
    private readonly Dictionary<string, string> _actNotes = new(StringComparer.OrdinalIgnoreCase);  // "Act N" → notes

    /// <summary>The shared guide, loaded once from the embedded tables.</summary>
    public static ZoneGuide Shared { get; } = LoadEmbedded();

    /// <summary>Number of zones with known metadata (0 means the table failed to load).</summary>
    public int Count => _areas.Count;

    private static ZoneGuide LoadEmbedded()
    {
        var guide = new ZoneGuide();
        try
        {
            var asm = Assembly.GetExecutingAssembly();
            using (var s = OpenResource(asm, "world_areas"))
                if (s != null)
                {
                    var doc = JsonDocument.Parse(s);
                    foreach (var prop in doc.RootElement.EnumerateObject())
                    {
                        var v = prop.Value;
                        guide._areas[prop.Name] = new ZoneArea(
                            Name: v.TryGetProperty("name", out var n) ? n.GetString() ?? "" : "",
                            Act: v.TryGetProperty("act", out var a) && a.TryGetInt32(out var ai) ? ai : 0,
                            Level: v.TryGetProperty("level", out var l) && l.TryGetInt32(out var li) ? li : 0,
                            Waypoint: v.TryGetProperty("waypoint", out var w) && w.ValueKind == JsonValueKind.True,
                            Town: v.TryGetProperty("town", out var t) && t.ValueKind == JsonValueKind.True);
                    }
                }

            using (var s = OpenResource(asm, "zone_notes"))
                if (s != null)
                {
                    var doc = JsonDocument.Parse(s);
                    if (doc.RootElement.TryGetProperty("actNotes", out var actArr) && actArr.ValueKind == JsonValueKind.Array)
                        foreach (var e in actArr.EnumerateArray())
                        {
                            var act = Str(e, "actName");
                            if (act.Length > 0) guide._actNotes[act] = Str(e, "notes");
                        }
                    if (doc.RootElement.TryGetProperty("zoneNotes", out var zoneArr) && zoneArr.ValueKind == JsonValueKind.Array)
                        foreach (var e in zoneArr.EnumerateArray())
                        {
                            var code = Str(e, "zoneCode");
                            var notes = Str(e, "notes");
                            if (code.Length > 0 && notes.Length > 0) guide._zoneNotes[code] = notes;
                        }
                }
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"ZoneGuide load failed: {ex.Message}");
        }
        return guide;
    }

    private static Stream? OpenResource(Assembly asm, string contains)
    {
        var name = asm.GetManifestResourceNames().FirstOrDefault(n => n.Contains(contains));
        return name == null ? null : asm.GetManifestResourceStream(name);
    }

    private static string Str(JsonElement e, string prop)
        => e.TryGetProperty(prop, out var v) && v.ValueKind == JsonValueKind.String ? v.GetString() ?? "" : "";

    /// <summary>Zone metadata for an area code, or null if unknown.</summary>
    public ZoneArea? Area(string areaCode)
        => !string.IsNullOrEmpty(areaCode) && _areas.TryGetValue(areaCode, out var a) ? a : null;

    /// <summary>Friendly area name (e.g. "The Riverbank"), falling back to the raw code when unknown.</summary>
    public string FriendlyName(string areaCode)
        => DisplayTextLocalizer.Localize(Area(areaCode) is { Name.Length: > 0 } a ? a.Name : areaCode);

    /// <summary>"Act N" string for an area, or "" when the act is unknown.</summary>
    public string ActLabel(string areaCode)
        => Area(areaCode) is { Act: > 0 } a ? $"第 {a.Act} 章" : "";

    /// <summary>
    /// Leveling notes for an area: the zone-specific note if present, else the act-level note.
    /// Returns a title ("Act N — Name") + the note text, or null if nothing is known for the area.
    /// </summary>
    public (string Title, string Notes)? Notes(string areaCode)
    {
        if (Area(areaCode) is not { } a) return null;
        var actKey = a.Act > 0 ? $"Act {a.Act}" : "";
        var actLabel = a.Act > 0 ? $"第 {a.Act} 章" : "";
        var title = actLabel.Length > 0 ? $"{actLabel} — {DisplayTextLocalizer.Localize(a.Name)}" : DisplayTextLocalizer.Localize(a.Name);

        var notes = _zoneNotes.GetValueOrDefault(areaCode, "");
        if (notes.Length == 0 && actKey.Length > 0) notes = _actNotes.GetValueOrDefault(actKey, "");
        return (title, notes);
    }
}
