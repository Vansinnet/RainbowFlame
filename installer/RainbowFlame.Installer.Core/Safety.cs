using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace RainbowFlame.Installer.Core;

public static class Safety
{
    public static readonly JsonSerializerOptions Json = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        WriteIndented = true,
        Converters = { new System.Text.Json.Serialization.JsonStringEnumConverter(JsonNamingPolicy.CamelCase) }
    };

    public static string Hash(string path)
    {
        using var input = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read, 1024 * 1024,
            FileOptions.SequentialScan);
        using var algorithm = SHA256.Create();
        return Convert.ToHexString(algorithm.ComputeHash(input)).ToLowerInvariant();
    }

    public static void RequireFile(string path, long size, string hash, string label)
    {
        var info = new FileInfo(path);
        if (!info.Exists || info.Attributes.HasFlag(FileAttributes.ReparsePoint))
            throw new InstallerException($"{label} is missing or is not a plain file: {path}");
        if (info.Length != size || !Hash(path).Equals(hash, StringComparison.OrdinalIgnoreCase))
            throw new InstallerException($"{label} has unknown bytes: {path}");
    }

    public static string SafePath(string root, string relative)
    {
        if (string.IsNullOrWhiteSpace(relative) || Path.IsPathRooted(relative))
            throw new InstallerException($"Unsafe manifest path: {relative}");
        var canonicalRoot = Path.TrimEndingDirectorySeparator(Path.GetFullPath(root));
        var result = Path.GetFullPath(Path.Combine(canonicalRoot, relative.Replace('/', Path.DirectorySeparatorChar)));
        if (!result.StartsWith(canonicalRoot + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
            throw new InstallerException($"Manifest path escapes the game root: {relative}");
        return result;
    }

    public static void RejectReparseAncestors(string root, string path, bool includeLeaf)
    {
        var canonicalRoot = Path.TrimEndingDirectorySeparator(Path.GetFullPath(root));
        var current = includeLeaf ? path : Path.GetDirectoryName(path)!;
        while (current.Length >= canonicalRoot.Length)
        {
            if ((Directory.Exists(current) || File.Exists(current)) &&
                File.GetAttributes(current).HasFlag(FileAttributes.ReparsePoint))
                throw new InstallerException($"Reparse points are not allowed in managed paths: {current}");
            if (current.Equals(canonicalRoot, StringComparison.OrdinalIgnoreCase)) break;
            current = Path.GetDirectoryName(current) ?? "";
        }
    }

    public static void WriteJsonDurable<T>(string path, T value)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        var temporary = path + ".tmp-" + Guid.NewGuid().ToString("N");
        var bytes = Encoding.UTF8.GetBytes(JsonSerializer.Serialize(value, Json) + Environment.NewLine);
        using (var output = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None,
                   4096, FileOptions.WriteThrough))
        {
            output.Write(bytes);
            output.Flush(true);
        }
        File.Move(temporary, path, true);
    }

    public static T ReadJson<T>(string path) where T : class =>
        JsonSerializer.Deserialize<T>(File.ReadAllText(path), Json)
        ?? throw new InstallerException($"Invalid JSON: {path}");

    public static void CopyDurable(string source, string destination)
    {
        using var input = new FileStream(source, FileMode.Open, FileAccess.Read, FileShare.Read);
        using var output = new FileStream(destination, FileMode.CreateNew, FileAccess.Write, FileShare.None,
            1024 * 1024, FileOptions.WriteThrough);
        input.CopyTo(output, 1024 * 1024);
        output.Flush(true);
    }

    public static void OverwriteDurable(string source, string destination)
    {
        var attributes = File.GetAttributes(destination);
        try
        {
            if (attributes.HasFlag(FileAttributes.ReadOnly))
                File.SetAttributes(destination, attributes & ~FileAttributes.ReadOnly);
            using var input = new FileStream(source, FileMode.Open, FileAccess.Read, FileShare.Read);
            using var output = new FileStream(destination, FileMode.Open, FileAccess.Write, FileShare.Read,
                1024 * 1024, FileOptions.WriteThrough);
            output.SetLength(0);
            input.CopyTo(output, 1024 * 1024);
            output.Flush(true);
        }
        finally
        {
            if (File.Exists(destination)) File.SetAttributes(destination, attributes);
        }
        File.Delete(source);
    }
}
