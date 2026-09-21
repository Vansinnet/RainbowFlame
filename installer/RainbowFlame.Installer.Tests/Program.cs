using RainbowFlame.Installer.Core;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

var tests = new (string Name, Action Run)[]
{
    ("hash refusal", HashRefusal), ("unknown additions", UnknownAddition),
    ("unowned output refusal", UnownedOutputRefusal),
    ("owned version upgrade", OwnedVersionUpgrade),
    ("interrupted version upgrade rollback", InterruptedVersionUpgradeRollback),
    ("read-only non-deletable replacement", ReadOnlyNonDeletableReplacement),
    ("interrupted operation rollback", InterruptedRollback), ("partial write recovery", PartialWriteRecovery),
    ("repair", Repair),
    ("update repair compatible", UpdateRepairCompatible),
    ("update repair mixed state", UpdateRepairMixedState),
    ("update repair changed replacement preflight", UpdateRepairChangedReplacementPreflight),
    ("update repair changed addition preflight", UpdateRepairChangedAdditionPreflight),
    ("update repair permits environment drift", UpdateRepairPermitsEnvironmentDrift),
    ("update repair requires receipt", UpdateRepairRequiresReceipt),
    ("update repair requires matching release", UpdateRepairRequiresMatchingRelease),
    ("update repair preflights backups", UpdateRepairPreflightsBackups),
    ("uninstall", Uninstall), ("update/build drift", BuildDrift),
    ("path traversal", PathTraversal), ("symlink/reparse refusal", ReparseRefusal),
    ("load order", LoadOrderPreservation), ("load order later changes", LoadOrderLaterChanges)
};
var failures = new List<string>();
foreach (var test in tests)
{
    try { test.Run(); Console.WriteLine("PASS " + test.Name); }
    catch (Exception error) { failures.Add(test.Name + ": " + error); Console.Error.WriteLine("FAIL " + test.Name + ": " + error.Message); }
}
if (failures.Count != 0) { Console.Error.WriteLine(string.Join(Environment.NewLine, failures)); return 1; }
Console.WriteLine($"Passed {tests.Length} installer tests. All filesystem writes used temporary fixtures.");
return 0;

static void HashRefusal()
{
    using var fixture = new Fixture();
    File.WriteAllText(Path.Combine(fixture.Game, "base.bin"), "tampered");
    Throws(() => fixture.Engine().Execute(fixture.Game, InstallerAction.Install, false), "unknown bytes");
}

static void UnknownAddition()
{
    using var fixture = new Fixture();
    var path = Path.Combine(fixture.Game, "mods", "RainbowFlame", "new.bin");
    Directory.CreateDirectory(Path.GetDirectoryName(path)!); File.WriteAllText(path, "unknown");
    Throws(() => fixture.Engine().Execute(fixture.Game, InstallerAction.Install, false), "unknown");
}

static void UnownedOutputRefusal()
{
    using var fixture = new Fixture();
    File.WriteAllText(Path.Combine(fixture.Game, "base.bin"), "output");
    Throws(() => fixture.Engine().Execute(fixture.Game, InstallerAction.Install, false), "ownership receipt");
}

static void OwnedVersionUpgrade()
{
    using var fixture = new Fixture();
    var engine = fixture.Engine();
    engine.Execute(fixture.Game, InstallerAction.Install, false);
    fixture.PrepareUpgrade();

    engine.Execute(fixture.Game, InstallerAction.Install, false);

    Equal("output-v2", File.ReadAllText(Path.Combine(fixture.Game, "base.bin")), "upgraded replacement");
    Equal("new-v2", File.ReadAllText(Path.Combine(fixture.Game, "mods", "RainbowFlame", "new.bin")), "upgraded addition");
    Equal("1.0.1", fixture.Receipt().Version, "upgraded receipt version");
    engine.Execute(fixture.Game, InstallerAction.Uninstall, false);
    Equal("base", File.ReadAllText(Path.Combine(fixture.Game, "base.bin")), "upgrade uninstall restore");
    False(File.Exists(Path.Combine(fixture.Game, "mods", "RainbowFlame", "new.bin")), "upgrade uninstall addition");
}

static void InterruptedVersionUpgradeRollback()
{
    using var fixture = new Fixture();
    fixture.Engine().Execute(fixture.Game, InstallerAction.Install, false);
    fixture.PrepareUpgrade();

    var engine = fixture.Engine(number => { if (number == 2) throw new IOException("injected upgrade interruption"); });
    Throws(() => engine.Execute(fixture.Game, InstallerAction.Install, false), "injected upgrade interruption");

    Equal("output", File.ReadAllText(Path.Combine(fixture.Game, "base.bin")), "upgrade replacement rollback");
    Equal("new", File.ReadAllText(Path.Combine(fixture.Game, "mods", "RainbowFlame", "new.bin")), "upgrade addition rollback");
    Equal("1.0.0", fixture.Receipt().Version, "rollback preserved prior receipt");
}

static void ReadOnlyNonDeletableReplacement()
{
    using var fixture = new Fixture();
    var target = Path.Combine(fixture.Game, "base.bin");
    try
    {
        File.SetAttributes(target, File.GetAttributes(target) | FileAttributes.ReadOnly);
        using (var handle = new FileStream(target, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
            fixture.Engine().Execute(fixture.Game, InstallerAction.Install, false);
        Equal("output", File.ReadAllText(target), "replacement without delete sharing");
        True(File.GetAttributes(target).HasFlag(FileAttributes.ReadOnly), "replacement preserved read-only attribute");
        fixture.Engine().Execute(fixture.Game, InstallerAction.Uninstall, false);
        Equal("base", File.ReadAllText(target), "read-only uninstall restore");
        True(File.GetAttributes(target).HasFlag(FileAttributes.ReadOnly), "uninstall preserved read-only attribute");
    }
    finally
    {
        if (File.Exists(target)) File.SetAttributes(target, FileAttributes.Normal);
    }
}

static void InterruptedRollback()
{
    using var fixture = new Fixture();
    var engine = fixture.Engine(number => { if (number == 2) throw new IOException("injected interruption"); });
    Throws(() => engine.Execute(fixture.Game, InstallerAction.Install, false), "injected interruption");
    Equal("base", File.ReadAllText(Path.Combine(fixture.Game, "base.bin")), "replacement rollback");
    False(File.Exists(Path.Combine(fixture.Game, "mods", "RainbowFlame", "new.bin")), "addition rollback");
}

static void PartialWriteRecovery()
{
    using var fixture = new Fixture();
    var manifest = Safety.ReadJson<PayloadManifest>(Path.Combine(fixture.Payload, "manifest.json"));
    var recipe = manifest.Files[0];
    var target = Path.Combine(fixture.Game, "base.bin");
    var backup = Path.Combine(fixture.State, "partial.backup");
    Directory.CreateDirectory(fixture.State);
    File.WriteAllText(backup, "base");
    File.WriteAllText(target, "partial");
    var journal = new Journal
    {
        Session = "partial", Action = "Install", GameRoot = fixture.Game,
        Entries = new List<JournalEntry>
        {
            new()
            {
                Target = target, Before = recipe.BaseSha256!, BeforeSize = recipe.BaseSize,
                After = recipe.OutputSha256, Backup = backup, Complete = false
            }
        }
    };
    var journalPath = Path.Combine(fixture.State, "journals", "partial.json");
    Safety.WriteJsonDurable(journalPath, journal);

    fixture.Engine().Execute(fixture.Game, InstallerAction.Install, false);

    Equal("output", File.ReadAllText(target), "install after partial recovery");
    Equal("rolledBack", Safety.ReadJson<Journal>(journalPath).State, "partial journal recovery");
}

static void Repair()
{
    using var fixture = new Fixture();
    fixture.Engine().Execute(fixture.Game, InstallerAction.Install, false);
    File.Delete(Path.Combine(fixture.Game, "mods", "RainbowFlame", "new.bin"));
    fixture.Engine().Execute(fixture.Game, InstallerAction.Repair, false);
    Equal("new", File.ReadAllText(Path.Combine(fixture.Game, "mods", "RainbowFlame", "new.bin")), "repair output");
}

static void UpdateRepairCompatible()
{
    using var fixture = new Fixture();
    var engine = fixture.Engine();
    engine.Execute(fixture.Game, InstallerAction.Install, false);
    File.WriteAllText(Path.Combine(fixture.Game, "base.bin"), "base");
    File.Delete(Path.Combine(fixture.Game, "mods", "RainbowFlame", "new.bin"));

    engine.Execute(fixture.Game, InstallerAction.RepairAfterUpdate, false);

    Equal("output", File.ReadAllText(Path.Combine(fixture.Game, "base.bin")), "update replacement");
    Equal("new", File.ReadAllText(Path.Combine(fixture.Game, "mods", "RainbowFlame", "new.bin")), "update addition");
}

static void UpdateRepairMixedState()
{
    using var fixture = new Fixture();
    var engine = fixture.Engine();
    engine.Execute(fixture.Game, InstallerAction.Install, false);
    File.WriteAllText(Path.Combine(fixture.Game, "base.bin"), "base");

    engine.Execute(fixture.Game, InstallerAction.RepairAfterUpdate, false);

    Equal("output", File.ReadAllText(Path.Combine(fixture.Game, "base.bin")), "mixed replacement");
    Equal("new", File.ReadAllText(Path.Combine(fixture.Game, "mods", "RainbowFlame", "new.bin")), "mixed existing addition");
}

static void UpdateRepairChangedReplacementPreflight()
{
    using var fixture = new Fixture();
    var engine = fixture.Engine();
    engine.Execute(fixture.Game, InstallerAction.Install, false);
    var addition = Path.Combine(fixture.Game, "mods", "RainbowFlame", "new.bin");
    File.Delete(addition);
    File.WriteAllText(Path.Combine(fixture.Game, "base.bin"), "changed-by-update");
    fixture.ReverseManifestFiles();

    Throws(() => engine.Execute(fixture.Game, InstallerAction.RepairAfterUpdate, false), "before writing");

    False(File.Exists(addition), "preflight did not restore earlier addition");
    Equal("changed-by-update", File.ReadAllText(Path.Combine(fixture.Game, "base.bin")), "changed replacement preserved");
    True(fixture.JournalCount() == 1, "preflight created a journal");
}

static void UpdateRepairChangedAdditionPreflight()
{
    using var fixture = new Fixture();
    var engine = fixture.Engine();
    engine.Execute(fixture.Game, InstallerAction.Install, false);
    File.WriteAllText(Path.Combine(fixture.Game, "base.bin"), "base");
    File.WriteAllText(Path.Combine(fixture.Game, "mods", "RainbowFlame", "new.bin"), "unknown");

    Throws(() => engine.Execute(fixture.Game, InstallerAction.RepairAfterUpdate, false), "unknown file");

    Equal("base", File.ReadAllText(Path.Combine(fixture.Game, "base.bin")), "preflight did not repair earlier replacement");
    True(fixture.JournalCount() == 1, "directory preflight created a journal");
}

static void UpdateRepairRequiresReceipt()
{
    using var fixture = new Fixture();
    Throws(() => fixture.Engine().Execute(fixture.Game, InstallerAction.RepairAfterUpdate, false), "ownership");
    Equal("base", File.ReadAllText(Path.Combine(fixture.Game, "base.bin")), "receipt refusal preserved replacement");
    True(fixture.JournalCount() == 0, "receipt refusal created a journal");
}

static void UpdateRepairRequiresMatchingRelease()
{
    using var fixture = new Fixture();
    var engine = fixture.Engine();
    engine.Execute(fixture.Game, InstallerAction.Install, false);
    var manifestPath = Path.Combine(fixture.Payload, "manifest.json");
    var manifest = Safety.ReadJson<PayloadManifest>(manifestPath);
    manifest.Version = "different-release";
    Safety.WriteJsonDurable(manifestPath, manifest);

    Throws(() => engine.Execute(fixture.Game, InstallerAction.RepairAfterUpdate, false), "different RainbowFlame release");
    True(fixture.JournalCount() == 1, "release refusal created a journal");
}

static void UpdateRepairPreflightsBackups()
{
    using var fixture = new Fixture();
    var engine = fixture.Engine();
    engine.Execute(fixture.Game, InstallerAction.Install, false);
    var receipt = fixture.Receipt();
    File.Delete(receipt.Files.Single(file => !file.Addition).Backup!);
    File.WriteAllText(Path.Combine(fixture.Game, "base.bin"), "base");

    Throws(() => engine.Execute(fixture.Game, InstallerAction.RepairAfterUpdate, false), "preflight uninstall backup");

    Equal("base", File.ReadAllText(Path.Combine(fixture.Game, "base.bin")), "backup preflight preserved replacement");
    True(fixture.JournalCount() == 1, "backup preflight created a journal");
}

static void UpdateRepairPermitsEnvironmentDrift()
{
    var root = Path.Combine(Path.GetTempPath(), "RainbowFlame-version-test-" + Guid.NewGuid().ToString("N"));
    var game = Path.Combine(root, "steamapps", "common", "Darktide");
    try
    {
        Directory.CreateDirectory(Path.Combine(game, "binaries"));
        File.WriteAllText(Path.Combine(game, "binaries", "Darktide.exe"), "not-the-supported-executable");
        File.WriteAllText(Path.Combine(root, "steamapps", "appmanifest_1361210.acf"), "\"buildid\" \"future-build\"");
        var manifest = new PayloadManifest();

        Throws(() => GameDiscovery.VerifyGame(game, manifest), "Unsupported Darktide executable version");
        Equal("future-build", GameDiscovery.VerifyGame(game, manifest, false), "relaxed update repair build");
    }
    finally
    {
        if (Directory.Exists(root)) Directory.Delete(root, true);
    }
}

static void Uninstall()
{
    using var fixture = new Fixture();
    var engine = fixture.Engine(); engine.Execute(fixture.Game, InstallerAction.Install, false);
    engine.Execute(fixture.Game, InstallerAction.Uninstall, false);
    Equal("base", File.ReadAllText(Path.Combine(fixture.Game, "base.bin")), "uninstall restore");
    False(File.Exists(Path.Combine(fixture.Game, "mods", "RainbowFlame", "new.bin")), "uninstall addition");
    Equal("dmf\nOther", File.ReadAllText(Path.Combine(fixture.Game, "mods", "mod_load_order.txt")).Replace("\r\n", "\n"), "exact load order uninstall");
}

static void BuildDrift()
{
    using var fixture = new Fixture();
    var engine = fixture.Engine(); engine.Execute(fixture.Game, InstallerAction.Install, false);
    var manifest = Safety.ReadJson<PayloadManifest>(Path.Combine(fixture.Payload, "manifest.json"));
    manifest.SteamBuild = "new-build"; Safety.WriteJsonDurable(Path.Combine(fixture.Payload, "manifest.json"), manifest);
    Throws(() => engine.Execute(fixture.Game, InstallerAction.Uninstall, false), "build differs");
}

static void PathTraversal()
{
    using var fixture = new Fixture();
    var manifest = Safety.ReadJson<PayloadManifest>(Path.Combine(fixture.Payload, "manifest.json"));
    manifest.Files[0].Target = "../escape"; Safety.WriteJsonDurable(Path.Combine(fixture.Payload, "manifest.json"), manifest);
    Throws(() => fixture.Engine().LoadManifest(), "escapes");
}

static void ReparseRefusal()
{
    var junction = @"C:\Documents and Settings";
    True(Directory.Exists(junction) && File.GetAttributes(junction).HasFlag(FileAttributes.ReparsePoint),
        "Windows reparse fixture is unavailable");
    Throws(() => Safety.RejectReparseAncestors(junction, junction, true), "Reparse");
}

static void LoadOrderPreservation()
{
    var original = Encoding.UTF8.GetBytes("dmf\r\nOther\r\n");
    var added = LoadOrder.Add(original, "RainbowFlame");
    Equal("dmf\r\nOther\r\nRainbowFlame\r\n", Encoding.UTF8.GetString(added), "append preserving CRLF");
    var duplicate = LoadOrder.Add(added, "RainbowFlame");
    True(added.AsSpan().SequenceEqual(duplicate), "idempotent load order");
    Equal("dmf\r\nOther\r\n", Encoding.UTF8.GetString(LoadOrder.Remove(added, "RainbowFlame")), "remove preserving content");
}

static void LoadOrderLaterChanges()
{
    using var fixture = new Fixture();
    var engine = fixture.Engine();
    engine.Execute(fixture.Game, InstallerAction.Install, false);
    var path = Path.Combine(fixture.Game, "mods", "mod_load_order.txt");
    File.AppendAllText(path, "LaterMod\n");
    engine.Execute(fixture.Game, InstallerAction.Repair, false);
    engine.Execute(fixture.Game, InstallerAction.Uninstall, false);
    Equal("dmf\nOther\nLaterMod\n", File.ReadAllText(path).Replace("\r\n", "\n"), "uninstall preserved later load-order change");
}

static void Throws(Action action, string contains)
{
    try { action(); }
    catch (Exception error) when (error.Message.Contains(contains, StringComparison.OrdinalIgnoreCase)) { return; }
    throw new Exception("Expected failure containing: " + contains);
}
static void Equal(string expected, string actual, string label) { if (expected != actual) throw new Exception($"{label}: expected {expected}, got {actual}"); }
static void True(bool value, string label) { if (!value) throw new Exception(label); }
static void False(bool value, string label) => True(!value, label);

sealed class Fixture : IDisposable
{
    public string Root { get; } = Path.Combine(Path.GetTempPath(), "RainbowFlame-tests-" + Guid.NewGuid().ToString("N"));
    public string Game => Path.Combine(Root, "game");
    public string Payload => Path.Combine(Root, "payload");
    public string State => Path.Combine(Root, "state");

    public Fixture()
    {
        Directory.CreateDirectory(Game); Directory.CreateDirectory(Path.Combine(Payload, "inserts"));
        Directory.CreateDirectory(Path.Combine(Game, "mods"));
        File.WriteAllText(Path.Combine(Game, "base.bin"), "base");
        File.WriteAllText(Path.Combine(Game, "mods", "mod_load_order.txt"), "dmf\nOther");
        File.WriteAllText(Path.Combine(Payload, "inserts", "replacement.bin"), "output");
        File.WriteAllText(Path.Combine(Payload, "inserts", "addition.bin"), "new");
        var manifest = new PayloadManifest
        {
            Version = "1.0.0",
            Files = new List<FileRecipe>
            {
                Recipe("replacement", "base.bin", "base.bin", "base", "output", false, "inserts/replacement.bin"),
                Recipe("addition", "mods/RainbowFlame/new.bin", null, null, "new", true, "inserts/addition.bin")
            }
        };
        Safety.WriteJsonDurable(Path.Combine(Payload, "manifest.json"), manifest);
    }

    public InstallerEngine Engine(Action<int>? failure = null) => new(Payload, State, new Stopped(), failure);
    public InstallReceipt Receipt()
    {
        var path = Directory.EnumerateFiles(Path.Combine(State, "installations"), "*.json").Single();
        return Safety.ReadJson<InstallReceipt>(path);
    }
    public int JournalCount()
    {
        var path = Path.Combine(State, "journals");
        return Directory.Exists(path) ? Directory.EnumerateFiles(path, "*.json").Count() : 0;
    }
    public void ReverseManifestFiles()
    {
        var path = Path.Combine(Payload, "manifest.json");
        var manifest = Safety.ReadJson<PayloadManifest>(path);
        manifest.Files.Reverse();
        Safety.WriteJsonDurable(path, manifest);
    }
    public void PrepareUpgrade()
    {
        var path = Path.Combine(Payload, "manifest.json");
        var manifest = Safety.ReadJson<PayloadManifest>(path);
        manifest.Version = "1.0.1";
        SetOutput(manifest.Files.Single(file => file.Id == "replacement"), "output-v2");
        SetOutput(manifest.Files.Single(file => file.Id == "addition"), "new-v2");
        Safety.WriteJsonDurable(path, manifest);
    }
    public void Dispose() { if (Directory.Exists(Root)) Directory.Delete(Root, true); }

    private void SetOutput(FileRecipe recipe, string output)
    {
        var bytes = Encoding.UTF8.GetBytes(output);
        File.WriteAllBytes(Path.Combine(Payload, recipe.Payload.Replace('/', Path.DirectorySeparatorChar)), bytes);
        recipe.OutputSize = bytes.Length;
        recipe.OutputSha256 = Hash(output);
        recipe.PayloadSize = bytes.Length;
        recipe.PayloadSha256 = recipe.OutputSha256;
        recipe.Operations = new List<DeltaOperation>
        {
            new() { Kind = DeltaKind.Insert, Offset = 0, Count = bytes.Length }
        };
    }

    private static FileRecipe Recipe(string id, string target, string? basis, string? baseText, string output,
        bool addition, string payload)
    {
        var payloadBytes = Encoding.UTF8.GetBytes(output);
        return new FileRecipe
        {
            Id = id, Target = target, Base = basis, BaseSize = baseText?.Length ?? 0,
            BaseSha256 = baseText is null ? null : Hash(baseText), OutputSize = output.Length, OutputSha256 = Hash(output),
            Payload = payload, PayloadSize = payloadBytes.Length, PayloadSha256 = Hash(output), Addition = addition,
            Operations = new List<DeltaOperation> { new() { Kind = DeltaKind.Insert, Offset = 0, Count = output.Length } }
        };
    }
    private static string Hash(string text) => Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(text))).ToLowerInvariant();
}

sealed class Stopped : IProcessGuard { public void EnsureGameStopped() { } }
