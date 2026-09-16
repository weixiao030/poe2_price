using System.Collections.Frozen;
using System.Reflection;
using System.Text.Json;

namespace POE2Radar.Core.Game;

/// <summary>
/// POE2DB English-to-Traditional-Chinese display-name catalog. The source list is paired by
/// POE2DB's stable value/class identity and is used only at display boundaries.
/// </summary>
public sealed class Poe2DbTranslationCatalog
{
    private readonly FrozenDictionary<string, string> _translations;

    public static Poe2DbTranslationCatalog Shared { get; } = Load();

    private Poe2DbTranslationCatalog(Dictionary<string, string> translations)
        => _translations = translations.ToFrozenDictionary(StringComparer.OrdinalIgnoreCase);

    public int Count => _translations.Count;

    /// <summary>Read-only view used by presentation layers that need exact-name lookup in a
    /// browser or other client. Keys are English POE2DB names and values are Traditional Chinese.
    /// The dictionary is never exposed for mutation.</summary>
    public IReadOnlyDictionary<string, string> Entries => _translations;

    public bool TryTranslate(string? english, out string traditionalChinese)
    {
        if (!string.IsNullOrWhiteSpace(english) && _translations.TryGetValue(english.Trim(), out var found))
        {
            traditionalChinese = found;
            return true;
        }

        traditionalChinese = "";
        return false;
    }

    private static Poe2DbTranslationCatalog Load()
    {
        try
        {
            var assembly = Assembly.GetExecutingAssembly();
            var resourceName = assembly.GetManifestResourceNames()
                .FirstOrDefault(name => name.EndsWith(".Game.poe2db_tw_translations.json", StringComparison.OrdinalIgnoreCase));
            if (resourceName is null) return new Poe2DbTranslationCatalog(new(StringComparer.OrdinalIgnoreCase));

            using var stream = assembly.GetManifestResourceStream(resourceName);
            var raw = stream is null ? null : JsonSerializer.Deserialize<Dictionary<string, string>>(stream);
            var translations = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            if (raw is not null)
            {
                foreach (var (english, chinese) in raw)
                    if (!string.IsNullOrWhiteSpace(english) && !string.IsNullOrWhiteSpace(chinese))
                        translations[english] = chinese;
            }

            return new Poe2DbTranslationCatalog(translations);
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"POE2DB translation catalog load failed: {ex.Message}");
            return new Poe2DbTranslationCatalog(new(StringComparer.OrdinalIgnoreCase));
        }
    }
}
