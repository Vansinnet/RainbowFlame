using System.Text;

namespace RainbowFlame.Installer.Core;

public static class LoadOrder
{
    private static readonly UTF8Encoding StrictUtf8 = new(false, true);

    public static byte[] Add(byte[] original, string modName)
    {
        var text = StrictUtf8.GetString(original);
        var lines = Split(text);
        if (lines.Any(line => line.Equals(modName, StringComparison.OrdinalIgnoreCase))) return original;
        var newline = text.Contains("\r\n", StringComparison.Ordinal) ? "\r\n" : "\n";
        var prefix = text.Length == 0 || text.EndsWith("\n", StringComparison.Ordinal) ? text : text + newline;
        return StrictUtf8.GetBytes(prefix + modName + newline);
    }

    public static byte[] Remove(byte[] current, string modName)
    {
        var text = StrictUtf8.GetString(current);
        var newline = text.Contains("\r\n", StringComparison.Ordinal) ? "\r\n" : "\n";
        var trailing = text.EndsWith("\n", StringComparison.Ordinal);
        var kept = Split(text).Where(line => !line.Equals(modName, StringComparison.OrdinalIgnoreCase)).ToArray();
        var result = string.Join(newline, kept);
        if (trailing && result.Length != 0) result += newline;
        return StrictUtf8.GetBytes(result);
    }

    private static IEnumerable<string> Split(string text) =>
        text.Replace("\r\n", "\n", StringComparison.Ordinal).Split('\n').Where(line => line.Length != 0);
}
