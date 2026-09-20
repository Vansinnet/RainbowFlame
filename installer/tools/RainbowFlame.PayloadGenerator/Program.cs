using RainbowFlame.Installer.Core;
using System.Security.Cryptography;
using System.Text.Json;

var workspace = args.Length == 2 && args[0] == "--workspace"
    ? Path.GetFullPath(args[1]) : FindWorkspace(AppContext.BaseDirectory);
var mod = Path.Combine(workspace, "mods", "active", "RainbowFlame");
var output = Path.Combine(mod, "payload");
var specs = Sources(workspace, mod).OrderBy(spec => spec.Id, StringComparer.Ordinal).ToArray();
var blockers = new List<object>();
foreach (var spec in specs)
{
    Check(spec.OutputSource, spec.OutputSize, spec.OutputHash, spec.Id + " output", blockers);
    if (spec.BaseSource is not null) Check(spec.BaseSource, spec.BaseSize, spec.BaseHash!, spec.Id + " base", blockers);
}
if (blockers.Count != 0)
{
    Directory.CreateDirectory(output);
    File.WriteAllText(Path.Combine(output, "blockers.json"),
        JsonSerializer.Serialize(new { status = "blocked", blockers }, Safety.Json) + "\n");
    Console.Error.WriteLine($"Payload generation blocked by {blockers.Count} unauthenticated or missing source(s).");
    return 2;
}

if (Directory.Exists(output)) Directory.Delete(output, true);
Directory.CreateDirectory(Path.Combine(output, "inserts"));
var manifest = new PayloadManifest();
foreach (var spec in specs)
{
    var basis = spec.BaseSource is null ? null : File.ReadAllBytes(spec.BaseSource);
    var desired = File.ReadAllBytes(spec.OutputSource);
    var (operations, inserts) = BuildDelta(basis, desired);
    VerifyDelta(spec.Id, basis, inserts, operations, desired);
    var payloadRelative = "inserts/" + spec.Id + ".bin";
    var payloadPath = Path.Combine(output, payloadRelative.Replace('/', Path.DirectorySeparatorChar));
    File.WriteAllBytes(payloadPath, inserts);
    manifest.Files.Add(new FileRecipe
    {
        Id = spec.Id, Target = spec.Target, Base = spec.BaseTarget, BaseSize = spec.BaseSize,
        BaseSha256 = spec.BaseHash, OutputSize = desired.LongLength, OutputSha256 = Hash(desired),
        Payload = payloadRelative, PayloadSize = inserts.LongLength, PayloadSha256 = Hash(inserts),
        Addition = spec.Addition, Operations = operations
    });
}
File.WriteAllText(Path.Combine(output, "manifest.json"),
    JsonSerializer.Serialize(manifest, Safety.Json).Replace("\r\n", "\n", StringComparison.Ordinal) + "\n");
Console.WriteLine($"Generated {manifest.Files.Count} authenticated recipes in {output}");
return 0;

static (List<DeltaOperation>, byte[]) BuildDelta(byte[]? basis, byte[] desired)
{
    if (basis is null)
        return (new List<DeltaOperation> { new() { Kind = DeltaKind.Insert, Offset = 0, Count = desired.Length } }, desired);
    const int block = 256;
    var index = new Dictionary<ulong, List<int>>();
    for (var offset = 0; offset + block <= basis.Length; offset += 16)
    {
        var key = Fingerprint(basis.AsSpan(offset, block));
        if (!index.TryGetValue(key, out var offsets)) index[key] = offsets = new List<int>();
        if (offsets.Count < 128) offsets.Add(offset);
    }
    var operations = new List<DeltaOperation>();
    using var inserts = new MemoryStream();
    var pendingStart = 0;
    var pendingCount = 0;
    void FlushInsert()
    {
        if (pendingCount == 0) return;
        operations.Add(new DeltaOperation { Kind = DeltaKind.Insert, Offset = pendingStart, Count = pendingCount });
        pendingCount = 0;
    }
    for (var position = 0; position < desired.Length;)
    {
        var bestOffset = -1;
        var bestLength = 0;
        if (position + block <= desired.Length && index.TryGetValue(Fingerprint(desired.AsSpan(position, block)), out var candidates))
        {
            foreach (var candidate in candidates)
            {
                var length = 0;
                while (candidate + length < basis.Length && position + length < desired.Length &&
                       basis[candidate + length] == desired[position + length]) length++;
                if (length > bestLength) { bestOffset = candidate; bestLength = length; }
            }
        }
        if (bestLength >= block)
        {
            FlushInsert();
            operations.Add(new DeltaOperation { Kind = DeltaKind.Copy, Offset = bestOffset, Count = bestLength });
            position += bestLength;
        }
        else
        {
            if (pendingCount == 0) pendingStart = checked((int)inserts.Position);
            inserts.WriteByte(desired[position++]);
            pendingCount++;
        }
    }
    FlushInsert();
    return (operations, inserts.ToArray());
}

static ulong Fingerprint(ReadOnlySpan<byte> bytes)
{
    const ulong basis = 14695981039346656037;
    const ulong prime = 1099511628211;
    var value = basis;
    foreach (var item in bytes) { value ^= item; value *= prime; }
    return value;
}

static void VerifyDelta(string id, byte[]? basis, byte[] inserts, IEnumerable<DeltaOperation> operations, byte[] expected)
{
    using var actual = new MemoryStream();
    foreach (var operation in operations)
    {
        var source = operation.Kind == DeltaKind.Copy ? basis : inserts;
        if (source is null || operation.Offset < 0 || operation.Count < 0 || operation.Offset + operation.Count > source.Length)
            throw new InvalidDataException("Invalid generated operation for " + id);
        actual.Write(source, checked((int)operation.Offset), operation.Count);
    }
    if (!actual.ToArray().AsSpan().SequenceEqual(expected))
        throw new InvalidDataException("Generated delta replay differs for " + id);
}

static void Check(string path, long size, string hash, string label, List<object> blockers)
{
    if (!File.Exists(path)) { blockers.Add(new { component = label, path, reason = "missing" }); return; }
    var actualSize = new FileInfo(path).Length;
    var actualHash = Safety.Hash(path);
    if (actualSize != size || !actualHash.Equals(hash, StringComparison.OrdinalIgnoreCase))
        blockers.Add(new { component = label, path, reason = "identity-mismatch", expectedSize = size,
            actualSize, expectedSha256 = hash, actualSha256 = actualHash });
}

static string Hash(byte[] bytes) => Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();

static string FindWorkspace(string start)
{
    for (var directory = new DirectoryInfo(start); directory is not null; directory = directory.Parent)
        if (Directory.Exists(Path.Combine(directory.FullName, "mods", "active", "RainbowFlame"))) return directory.FullName;
    throw new InvalidOperationException("Workspace root was not found. Use --workspace <path>.");
}

static IEnumerable<SourceSpec> Sources(string root, string mod)
{
    string P(string relative) => Path.Combine(root, relative.Replace('/', Path.DirectorySeparatorChar));
    yield return new("staff-a8", "bundle/data/85/85d24accc98ef272", P("docs/analysis-flame-huecycle-deployment-20260918-q1/a8dc696a363ec3d3.original.rollback.material"), 41732, "1cf95fd9e9ac6afa6370849696d67a4cc602f369e0c6c8310409f18479c46ece", P("docs/analysis-rainbow-live-controls-20260919-e1/a8dc696a363ec3d3.material"), 71604, "f14191c3fa372d10089fac9d8e042d9363e33929aa551b57e02b79ffe51585fb", false, "bundle/data/85/85d24accc98ef272");
    yield return new("staff-49", "bundle/data/80/809f0435f2b74af3", P("docs/analysis-flame-huecycle-deployment-20260918-q1/49697971309d8a04.original.rollback.material"), 42128, "6c281be550d37d8ba3cb765199619bbaf81eb0d0365251a21dd9835e1621dfaf", P("docs/analysis-rainbow-live-controls-20260919-e1/49697971309d8a04.material"), 71952, "5634cbbc75b5953260b03727c0ad09b045ce32e1ba553d9e14256c8b4275f9a8", false, "bundle/data/80/809f0435f2b74af3");
    yield return new("staff-cloud", "bundle/4e6163c275b96d00", P("docs/analysis-flame-noop-deployment-20260917-f1/original.rollback.bundle"), 83256, "1bdf1a5b90e324da137b98a9d971902ad206cd7d55b59b5d218ba6edd67b6d51", P("docs/analysis-rainbow-live-controls-20260919-e1/cloud-rename-NOOP-OFFLINE-UNTESTED.bundle"), 524960, "a5d76ad745cb65bc29f628a11f90c4891d60ee88e4938a0bb3b8f62b0fcd0911", false, "bundle/4e6163c275b96d00");
    yield return new("enemy-global", "bundle/30ebeee18093c079", P("docs/analysis-rainbow-enemy-material-routing-20260919-l1/30ebeee18093c079.stock.rollback"), 11598878, "53fd3e19870d70e18377151233f3aa3a141ead0339c55ad4dd83b4625fa5e531", P("docs/analysis-rainbow-enemy-presets-20260920-u2/30ebeee18093c079"), 14171296, "572f42ec0c7639a6616f0fffd9b44f12d153004acbd53e05e8191f8596763799", false, "bundle/30ebeee18093c079");
    foreach (var spec in ImpactSources(root)) yield return spec;
    var parent = P("docs/analysis-rainbow-enemy-deployment-20260919-h1/enemy-parent.previous.rollback");
    var child = P("docs/analysis-rainbow-enemy-deployment-20260919-h1/enemy-child.previous.rollback");
    var streamRoot = P("docs/analysis-rainbow-enemy-presets-20260920-u2/bundle/data/rf");
    var parents = new Dictionary<string, (long Size, string Hash)>
    {
        ["0fb83861b4678991"] = (427181, "b41264fd22101500af879b30fecd8c2128969e48e2a35c55d7207a5c508585a4"),
        ["5c2550b09227a9e4"] = (427181, "7e23f890fa3da3f4408ca9b8cb6d0108699b39b9c2a7e3867a1d8c197e2609a0"),
        ["5d0509aa059fa83b"] = (427229, "2f67a15410d286457ed79a24d50c50ddd528b84b0dec000d888d2c12b9dbfe9b"),
        ["5e046cad1e9570d7"] = (427181, "16e9373192add0c856398ae2afb27c66f2f2344b71e01b73780a8296ec6791ee"),
        ["625c6576926fd717"] = (427181, "430026d2ba232aa1ba06d951176686444bbb2abea25114a12567076cb11a7c11"),
        ["635c81c8bc9bb9ec"] = (427261, "cb5de42a387de4f4787dc1ae202376eba04ac3927dfd474b85c399f25738d8a9"),
        ["f493e7d98ae95981"] = (427181, "60351439b055486d355b04c0e0e6b30c598e834c03202a0ea029ebd0d5db5d06"),
        ["fb32077a4c21f759"] = (427229, "3e6355c5a8d6335f2eb6e292d974b193009783884267019bd7ac51cd50111114")
    };
    foreach (var (name, identity) in parents)
    {
        var path = Path.Combine(streamRoot, name);
        yield return new("stream-" + name, "bundle/data/rf/" + name, parent, 393229, "a5c007c5b0af581b834d62b5053237a56888da2d575666461fefc77ab9665e32", path, identity.Size, identity.Hash, true, "bundle/data/a4/a40299ecf616514c");
    }
    var children = new Dictionary<string, string>
    {
        ["16f192bd60914c73"] = "8564d685e7962c96b4cc45bcea634399ddf1d6ac7b9560092c293d18bc849e04",
        ["466a37a1b48d4aef"] = "da98a786c51de8df6b9745b8645983abe6ba9d7bf85ed484892922fac7c574f1",
        ["4b81288c5455597c"] = "37a53bf8734895dd96406d19ef8f2e508706893d020de9ab772608a6e715ae21",
        ["4e1b335ebbd4f33f"] = "5b83240f0d51a1d72303a3efd67524314f66ef949539a89199a707854c6feab8",
        ["550feb5374742368"] = "97ba93058f53861789967abc05a93fc63a215866846e55a05d3eae1c9a2035f2",
        ["e9db71adf077d8e3"] = "b89634cc682e07e6e39413c707263cc2a5f991ba3eedbd6323213b2c281dfad6",
        ["eb22e9e523c6bd4b"] = "e5a186be8bbf04f0e9cc255334e8dc7e7db5f3ce224fbc74c180d78f38d2c1dd",
        ["eb8b192632de716f"] = "7073cc3950fd3a594545b6867e98ca22fb41f2335aa1c62251d4481e57f5b49d"
    };
    foreach (var (name, hash) in children)
    {
        var path = Path.Combine(streamRoot, name);
        yield return new("stream-" + name, "bundle/data/rf/" + name, child, 244, "b55f7d9c5d7577bf46c625ae4a776872a6592944f8db93057736ef8fd217019b", path, 308, hash, true, "bundle/data/e7/e75d420a2056a602");
    }
    foreach (var relative in new[] { "RainbowFlame.mod", "scripts/mods/RainbowFlame/RainbowFlame.lua", "scripts/mods/RainbowFlame/RainbowFlame_data.lua", "scripts/mods/RainbowFlame/RainbowFlame_localization.lua" })
    {
        var path = Path.Combine(mod, relative.Replace('/', Path.DirectorySeparatorChar));
        yield return new("mod-" + Path.GetFileName(relative).Replace('.', '-'), "mods/RainbowFlame/" + relative,
            null, 0, null, path, new FileInfo(path).Length, Safety.Hash(path), true, null);
    }
}

static IEnumerable<SourceSpec> ImpactSources(string root)
{
    string P(string relative) => Path.Combine(root, relative.Replace('/', Path.DirectorySeparatorChar));
    var impactRoot = P("mods/active/RainbowFlame/analysis/impact-presets-20260920-b4");
    var manifestPath = Path.Combine(impactRoot, "candidate.json");
    Safety.RequireFile(manifestPath, 15482, "4b6050aa56cc86fa2afde5a07111f4047ccdfffbfb3ca858f74ff1be841ddfa4", "sealed impact preset manifest");
    using var document = JsonDocument.Parse(File.ReadAllText(manifestPath));
    var candidate = document.RootElement;
    if (candidate.GetProperty("preserved_stock_records").GetInt32() != 30 ||
        candidate.GetProperty("added_records").GetInt32() != 40)
        throw new InvalidDataException("Unexpected impact preset record counts.");
    yield return new("impact-global", "bundle/97498862fb42b0d6",
        Path.Combine(impactRoot, "stock/bundle/97498862fb42b0d6"), 230018,
        "7d48b146e33c023586c37e427c3e941063f86801ce8b0047f962f193bd746dad",
        Path.Combine(impactRoot, "bundle/97498862fb42b0d6"), 525984,
        "6554b503d9965c33bf8c711c880e8d1c5c399d555948a17f28a4e7efefa8cdef",
        false, "bundle/97498862fb42b0d6");

    var bases = new[]
    {
        ("parents-stream/hash-only/1cc58f33452ca960.material", "data/bb/bb79ba7a5b92d132", 337248L, "7e072a559e0c2d77f762c12bde0214521e925d235e2ae17c75ff7605f9a6b35c"),
        ("materials-stream/hash-only/43eccf3418d41d30.material", "data/3b/3b36696951142a11", 324L, "844a8628c340c4cfc0c8263bab9a97af230832ca20043f5be4d6d40e822c62f0"),
        ("materials-stream/hash-only/c69e5a80e9b93deb.material", "data/4c/4c2838a126b34a02", 328L, "45cecdf4f460ce4a3d9f8ed909fe50fd19fb0f1e984f0b9825af857b1a3c35a9"),
        ("materials-stream/hash-only/9f9f92ebd789847e.material", "data/d5/d54eeb584a215210", 324L, "66100d4107564ba2f97c75998488480994ef2ffecc76869e8cbec74c07be0561")
    };
    var presets = candidate.GetProperty("presets");
    var streams = candidate.GetProperty("streams");
    var names = new[] { "red", "orange", "yellow", "green", "cyan", "blue", "violet", "pink" };
    var emitted = new HashSet<string>(StringComparer.Ordinal);
    foreach (var presetName in names)
    {
        var preset = presets.GetProperty(presetName);
        var identities = new List<string> { preset.GetProperty("parent_hash").GetString()! };
        identities.AddRange(preset.GetProperty("child_hashes").EnumerateArray().Select(value => value.GetString()!));
        for (var index = 0; index < identities.Count; index++)
        {
            var name = identities[index];
            if (!emitted.Add(name)) throw new InvalidDataException("Duplicate impact stream identity: " + name);
            var stream = streams.GetProperty("bundle/data/rf/" + name);
            var basis = bases[index];
            yield return new("stream-" + name, "bundle/data/rf/" + name,
                P("mods/active/RainbowFlame/analysis/impact-color-20260920-a1/" + basis.Item1),
                basis.Item3, basis.Item4, Path.Combine(impactRoot, "bundle/data/rf", name),
                stream.GetProperty("size").GetInt64(), stream.GetProperty("sha256").GetString()!,
                true, "bundle/" + basis.Item2);
        }
    }
    if (emitted.Count != 32 || streams.EnumerateObject().Count() != 32)
        throw new InvalidDataException("Unexpected impact stream count.");
}

internal sealed record SourceSpec(string Id, string Target, string? BaseSource, long BaseSize, string? BaseHash,
    string OutputSource, long OutputSize, string OutputHash, bool Addition, string? BaseTarget);
