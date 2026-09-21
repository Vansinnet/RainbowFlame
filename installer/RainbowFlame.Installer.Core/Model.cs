using System.Text.Json.Serialization;

namespace RainbowFlame.Installer.Core;

public sealed class PayloadManifest
{
    public int Format { get; set; } = 1;
    public string Product { get; set; } = "RainbowFlame";
    public string Version { get; set; } = "1.0.1";
    public string SteamAppId { get; set; } = "1361210";
    public string SteamBuild { get; set; } = "24735202";
    public string ExeVersion { get; set; } = "1.3.770.210";
    public List<FileRecipe> Files { get; set; } = new();
}

public sealed class FileRecipe
{
    public string Id { get; set; } = "";
    public string Target { get; set; } = "";
    public string? Base { get; set; }
    public long BaseSize { get; set; }
    public string? BaseSha256 { get; set; }
    public long OutputSize { get; set; }
    public string OutputSha256 { get; set; } = "";
    public string Payload { get; set; } = "";
    public long PayloadSize { get; set; }
    public string PayloadSha256 { get; set; } = "";
    public bool Addition { get; set; }
    public List<DeltaOperation> Operations { get; set; } = new();
}

public sealed class DeltaOperation
{
    [JsonConverter(typeof(JsonStringEnumConverter))]
    public DeltaKind Kind { get; set; }
    public long Offset { get; set; }
    public int Count { get; set; }
}

public enum DeltaKind { Copy, Insert }

public sealed class InstallReceipt
{
    public string Product { get; set; } = "RainbowFlame";
    public string Version { get; set; } = "";
    public string GameRoot { get; set; } = "";
    public string SteamBuild { get; set; } = "";
    public string ExeVersion { get; set; } = "";
    public string Session { get; set; } = "";
    public List<ReceiptFile> Files { get; set; } = new();
    public ReceiptFile? LoadOrder { get; set; }
}

public sealed class ReceiptFile
{
    public string Id { get; set; } = "";
    public string Target { get; set; } = "";
    public string OutputSha256 { get; set; } = "";
    public long OutputSize { get; set; }
    public bool Addition { get; set; }
    public string? Backup { get; set; }
    public string? BackupSha256 { get; set; }
    public long BackupSize { get; set; }
}

public sealed class Journal
{
    public string Session { get; set; } = "";
    public string Action { get; set; } = "";
    public string State { get; set; } = "prepared";
    public string GameRoot { get; set; } = "";
    public List<JournalEntry> Entries { get; set; } = new();
}

public sealed class JournalEntry
{
    public string Target { get; set; } = "";
    public string Before { get; set; } = "absent";
    public string After { get; set; } = "";
    public string? Backup { get; set; }
    public long BeforeSize { get; set; }
    public bool Complete { get; set; }
}

public enum InstallerAction { Install, Repair, RepairAfterUpdate, Uninstall }

public sealed record OperationResult(bool Success, string Message);

public interface IProcessGuard
{
    void EnsureGameStopped();
}

public sealed class DarktideProcessGuard : IProcessGuard
{
    public void EnsureGameStopped()
    {
        var processes = System.Diagnostics.Process.GetProcessesByName("Darktide");
        try
        {
            if (processes.Length != 0)
                throw new InstallerException("Darktide is running. Close the game before continuing.");
        }
        finally
        {
            foreach (var process in processes) process.Dispose();
        }
    }
}

public sealed class InstallerException : Exception
{
    public InstallerException(string message) : base(message) { }
    public InstallerException(string message, Exception inner) : base(message, inner) { }
}
