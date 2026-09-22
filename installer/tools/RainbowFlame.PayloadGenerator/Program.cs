using RainbowFlame.Installer.Core;
using System.Security.Cryptography;
using System.Text.Json;

var workspace = args.Length == 2 && args[0] == "--workspace"
    ? Path.GetFullPath(args[1]) : FindWorkspace(AppContext.BaseDirectory);
var mod = Path.Combine(workspace, "mods", "active", "RainbowFlame");
var output = Path.Combine(mod, "payload");
var specs = Sources(workspace, mod).OrderBy(spec => spec.Id, StringComparer.Ordinal).ToArray();
var duplicateIds = specs.GroupBy(spec => spec.Id, StringComparer.Ordinal).Where(group => group.Count() != 1).Select(group => group.Key).ToArray();
var duplicateTargets = specs.GroupBy(spec => spec.Target, StringComparer.OrdinalIgnoreCase).Where(group => group.Count() != 1).Select(group => group.Key).ToArray();
if (duplicateIds.Length != 0 || duplicateTargets.Length != 0)
    throw new InvalidDataException($"Duplicate payload identities. IDs: {string.Join(", ", duplicateIds)}; targets: {string.Join(", ", duplicateTargets)}");
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
    yield return new("staff-a8", "bundle/data/85/85d24accc98ef272", P("docs/analysis-flame-huecycle-deployment-20260918-q1/a8dc696a363ec3d3.original.rollback.material"), 41732, "1cf95fd9e9ac6afa6370849696d67a4cc602f369e0c6c8310409f18479c46ece", P("docs/analysis-rainbow-live-controls-20260921-opacity1/a8dc696a363ec3d3.material"), 71700, "57f513ec81c1b98bc562ff5fcdb4688ac321c4b12103e220375536199f9f3bcb", false, "bundle/data/85/85d24accc98ef272");
    yield return new("staff-49", "bundle/data/80/809f0435f2b74af3", P("docs/analysis-flame-huecycle-deployment-20260918-q1/49697971309d8a04.original.rollback.material"), 42128, "6c281be550d37d8ba3cb765199619bbaf81eb0d0365251a21dd9835e1621dfaf", P("docs/analysis-rainbow-live-controls-20260921-opacity1/49697971309d8a04.material"), 72048, "460f671ed1ba7107e98827e922908a06b2a02012d0df4322d6186ee30dc9b032", false, "bundle/data/80/809f0435f2b74af3");
    yield return new("staff-cloud", "bundle/4e6163c275b96d00", P("docs/analysis-flame-noop-deployment-20260917-f1/original.rollback.bundle"), 83256, "1bdf1a5b90e324da137b98a9d971902ad206cd7d55b59b5d218ba6edd67b6d51", P("docs/analysis-rainbow-live-controls-20260919-e1/cloud-rename-NOOP-OFFLINE-UNTESTED.bundle"), 524960, "a5d76ad745cb65bc29f628a11f90c4891d60ee88e4938a0bb3b8f62b0fcd0911", false, "bundle/4e6163c275b96d00");
    yield return new("staff-cloud-3p", "bundle/bf83ff6f40d45fc8", P("docs/analysis-rainbow-staff-3p-20260921-a1/original.bundle"), 65413, "65fcde9a26dd0eb18c5d1dcab9e910908bb6d32b3802bea5bb7286c47849e153", P("docs/analysis-rainbow-staff-3p-20260921-a1/staff-cloud-3p-full.bundle"), 524944, "e0430cc09cb8dab3b2dce9160c037e4744ba943cc5549a4ac2eba3c8cc6b1e50", false, "bundle/bf83ff6f40d45fc8");
    yield return new("staff-3p-20", "bundle/data/03/03f68803faf03b51", P("docs/analysis-rainbow-staff-3p-20260921-a1/layers/20b91c9f8a8cc4aa.material"), 167796, "73943bfb02628b95f6e822cddfea241e87feaa7849080f157952a012cb7efce3", P("docs/analysis-rainbow-staff-3p-20260921-a1/live20-offline-20260921-b1/20b91c9f8a8cc4aa.material"), 199556, "2c1d9f9d98817dee9cd9fea444213f5ad537eaf207ebe1b444bfd4073798d2a9", false, "bundle/data/03/03f68803faf03b51");
    yield return new("staff-3p-84", "bundle/data/a1/a124af34da8f38d4", P("docs/analysis-flame-ramp-20260918-k1/materials/84dce57f22a9d409.material"), 316004, "c4d900493a29f564ebb8d844cc0dac4f759288d254612c4aba84ace6ef37d08f", P("docs/analysis-rainbow-staff-3p-20260921-a1/live84-offline/84dce57f22a9d409.material"), 380036, "25915d4277c864aac462c1b2f13e45dc91534f8129039a64668fad34f364e73a", false, "bundle/data/a1/a124af34da8f38d4");
    yield return new("staff-3p-2d", "bundle/data/b3/b30657a1a41cf556", P("docs/analysis-flame-target-20260917-a1/materials-4e6163c275b96d00-v8-stream/hash-only/2d0708b33f17b5e4.material"), 300, "e1b7c9e8a483009c090f31641261471d3a60d2c25cc7879e201e079ecb18139c", P("docs/analysis-rainbow-staff-3p-20260921-a1/live84-offline/2d0708b33f17b5e4.material"), 364, "527d3bfb8a20ab1d327477d584172df8fe386e5ba0a5017abbf6440bed98d5af", false, "bundle/data/b3/b30657a1a41cf556");
    foreach (var spec in FlamerSources(root)) yield return spec;
    foreach (var spec in EnemySources(root)) yield return spec;
    foreach (var spec in StaffImpactSources(root)) yield return spec;
    foreach (var spec in FlamerImpactSources(root)) yield return spec;
    foreach (var relative in new[] { "RainbowFlame.mod", "scripts/mods/RainbowFlame/RainbowFlame.lua", "scripts/mods/RainbowFlame/RainbowFlame_data.lua", "scripts/mods/RainbowFlame/RainbowFlame_localization.lua" })
    {
        var path = Path.Combine(mod, relative.Replace('/', Path.DirectorySeparatorChar));
        yield return new("mod-" + Path.GetFileName(relative).Replace('.', '-'), "mods/RainbowFlame/" + relative,
            null, 0, null, path, new FileInfo(path).Length, Safety.Hash(path), true, null);
    }
}

static IEnumerable<SourceSpec> FlamerSources(string root)
{
    string P(string relative) => Path.Combine(root, relative.Replace('/', Path.DirectorySeparatorChar));
    var analysis = P("mods/active/RainbowFlame/analysis/flamer-streams-20260922-a1");
    var authored = Path.Combine(analysis, "authored");
    var authoredManifestPath = Path.Combine(authored, "manifest.json");
    Safety.RequireFile(authoredManifestPath, 1689, "1ac12a3328521da4ac829e16319b4543c7bd0f6276184fd73973275fdb043e33", "sealed flamer bundle manifest");
    using var authoredManifestDocument = JsonDocument.Parse(File.ReadAllText(authoredManifestPath));
    var authoredOutputs = authoredManifestDocument.RootElement.GetProperty("outputs").EnumerateArray()
        .ToDictionary(value => value.GetProperty("file").GetString()!, StringComparer.Ordinal);
    var bundles = new[]
    {
        ("continuous", "e605c5550cf3088b", "RainbowFlame_flamer_continuous.json", 2792L, "7231769e61fd7d2948e3a2601986c472d92cd777788881d648532bd36c799756"),
        ("burst", "f3952b5fba574342", "RainbowFlame_flamer_burst.json", 3184L, "d887b3b813daf56d73da0767a8b2420f28acc8cdeb98321015bb86dbaa4b21e8"),
        ("3p", "299f23117d653583", "RainbowFlame_flamer_3p.json", 2333L, "066f6acd9ceccbe3f1854353a4fdfaafafb01d2fe94364095432eec480a39444")
    };
    foreach (var (kind, targetHash, reportName, reportSize, reportHash) in bundles)
    {
        var reportPath = Path.Combine(authored, reportName);
        Safety.RequireFile(reportPath, reportSize, reportHash, "sealed flamer " + kind + " report");
        using var reportDocument = JsonDocument.Parse(File.ReadAllText(reportPath));
        var report = reportDocument.RootElement;
        var outputName = report.GetProperty("output").GetString()!;
        var manifestOutput = authoredOutputs[outputName];
        if (report.GetProperty("kind").GetString() != kind ||
            report.GetProperty("source").GetString() != "stock/bundle/" + targetHash ||
            manifestOutput.GetProperty("size").GetInt64() != report.GetProperty("output_size").GetInt64() ||
            manifestOutput.GetProperty("sha256").GetString() != report.GetProperty("output_sha256").GetString())
            throw new InvalidDataException("Unexpected flamer bundle report: " + reportName);
        yield return new("flamer-" + kind, "bundle/" + targetHash,
            Path.Combine(analysis, "stock", "bundle", targetHash), report.GetProperty("source_size").GetInt64(),
            report.GetProperty("source_sha256").GetString()!, Path.Combine(authored, outputName),
            report.GetProperty("output_size").GetInt64(), report.GetProperty("output_sha256").GetString()!, false,
            "bundle/" + targetHash);
    }
    if (authoredOutputs.Count != 3) throw new InvalidDataException("Unexpected flamer bundle output count.");

    var profilesPath = Path.Combine(analysis, "material-profiles.json");
    Safety.RequireFile(profilesPath, 49486, "1dce4188b64c62b323522e6b2f5b64cd9d3919106cc935d7d0cbce63f8097d34", "sealed flamer material profiles");
    using var profilesDocument = JsonDocument.Parse(File.ReadAllText(profilesPath));
    var profiles = profilesDocument.RootElement.GetProperty("materials").EnumerateArray()
        .ToDictionary(value => value.GetProperty("material").GetString()!, StringComparer.Ordinal);
    var materialsRoot = Path.Combine(analysis, "authored-materials");
    var materialsReportPath = Path.Combine(materialsRoot, "report.json");
    Safety.RequireFile(materialsReportPath, 33390, "422e0202aad1c7cc92e7f22f2a091b7ac5395d29e638980ac8653d41de8f0bff", "sealed authored material report");
    using var materialsDocument = JsonDocument.Parse(File.ReadAllText(materialsReportPath));
    var materialsReport = materialsDocument.RootElement;
    foreach (var materialHash in new[] { "da27aa083a052838", "3bbd4f5f32613f4b", "be9333164c3ddf4a" })
    {
        var profile = profiles[materialHash];
        var result = materialHash == "3bbd4f5f32613f4b"
            ? materialsReport.GetProperty("child")
            : materialsReport.GetProperty("parents").GetProperty(materialHash);
        var source = result.GetProperty("source");
        var material = result.GetProperty("material");
        if (source.GetProperty("size").GetInt64() != profile.GetProperty("stream_size").GetInt64() ||
            source.GetProperty("sha256").GetString() != profile.GetProperty("stream_sha256").GetString())
            throw new InvalidDataException("Authored material source differs from sealed profile: " + materialHash);
        var target = "bundle/" + profile.GetProperty("stream").GetString();
        yield return new("zz-flamer-material-" + materialHash[..4], target,
            Path.Combine(analysis, "stock", "bundle", profile.GetProperty("stream").GetString()!.Replace('/', Path.DirectorySeparatorChar)),
            source.GetProperty("size").GetInt64(), source.GetProperty("sha256").GetString()!,
            Path.Combine(materialsRoot, materialHash + ".material"), material.GetProperty("size").GetInt64(),
            material.GetProperty("sha256").GetString()!, false, target);
    }
}

static IEnumerable<SourceSpec> EnemySources(string root)
{
    string P(string relative) => Path.Combine(root, relative.Replace('/', Path.DirectorySeparatorChar));
    var presetRoot = P("docs/analysis-rainbow-enemy-presets-20260921-opacity1");
    var manifestPath = Path.Combine(presetRoot, "candidate.json");
    Safety.RequireFile(manifestPath, 25206, "8a52825a4492069d153032beae6d2e941bb0bbf6e4d376bf92068d27fbef20de", "sealed enemy preset manifest");
    using var document = JsonDocument.Parse(File.ReadAllText(manifestPath));
    var candidate = document.RootElement;
    var levels = candidate.GetProperty("opacity_levels").EnumerateArray().Select(value => value.GetInt32()).ToArray();
    if (candidate.GetProperty("preserved_stock_records").GetInt32() != 711 ||
        candidate.GetProperty("added_records").GetInt32() != 108 ||
        !levels.SequenceEqual(new[] { 0, 25, 50, 75, 100 }))
        throw new InvalidDataException("Unexpected enemy preset candidate shape.");
    var bundle = candidate.GetProperty("bundle");
    yield return new("enemy-global", "bundle/30ebeee18093c079",
        P("docs/analysis-rainbow-enemy-material-routing-20260919-l1/30ebeee18093c079.stock.rollback"),
        11598878, "53fd3e19870d70e18377151233f3aa3a141ead0339c55ad4dd83b4625fa5e531",
        Path.Combine(presetRoot, bundle.GetProperty("path").GetString()!), bundle.GetProperty("size").GetInt64(),
        bundle.GetProperty("sha256").GetString()!, false, "bundle/30ebeee18093c079");

    var parent = P("docs/analysis-rainbow-enemy-deployment-20260919-h1/enemy-parent.previous.rollback");
    var child = P("docs/analysis-rainbow-enemy-deployment-20260919-h1/enemy-child.previous.rollback");
    var streamRoot = Path.Combine(presetRoot, "bundle", "data", "rf");
    var emitted = new HashSet<string>(StringComparer.Ordinal);
    foreach (var property in candidate.GetProperty("variants").EnumerateObject().OrderBy(property => property.Name, StringComparer.Ordinal))
    {
        var variant = property.Value;
        var parentHash = variant.GetProperty("parent_hash").GetString()!;
        var childHash = variant.GetProperty("child_hash").GetString()!;
        if (parentHash.Length != 16 || childHash.Length != 16 || !emitted.Add(parentHash) || !emitted.Add(childHash))
            throw new InvalidDataException("Invalid or duplicate enemy stream identity.");
        yield return new("stream-" + parentHash, "bundle/data/rf/" + parentHash,
            parent, 393229, "a5c007c5b0af581b834d62b5053237a56888da2d575666461fefc77ab9665e32",
            Path.Combine(streamRoot, parentHash), variant.GetProperty("parent_size").GetInt64(),
            variant.GetProperty("parent_sha256").GetString()!, true, "bundle/data/a4/a40299ecf616514c");
        yield return new("stream-" + childHash, "bundle/data/rf/" + childHash,
            child, 244, "b55f7d9c5d7577bf46c625ae4a776872a6592944f8db93057736ef8fd217019b",
            Path.Combine(streamRoot, childHash), variant.GetProperty("child_size").GetInt64(),
            variant.GetProperty("child_sha256").GetString()!, true, "bundle/data/e7/e75d420a2056a602");
    }
    if (emitted.Count != 72) throw new InvalidDataException("Unexpected enemy stream count.");
}

static IEnumerable<SourceSpec> StaffImpactSources(string root)
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

static IEnumerable<SourceSpec> FlamerImpactSources(string root)
{
    string P(string relative) => Path.Combine(root, relative.Replace('/', Path.DirectorySeparatorChar));
    var analysis = P("mods/active/RainbowFlame/analysis/flamer-streams-20260922-a1");
    var impactRoot = Path.Combine(analysis, "authored-impact");
    var manifestPath = Path.Combine(impactRoot, "manifest.json");
    Safety.RequireFile(manifestPath, 7615, "4928ba3c9c2f29a6b6c6f6ed1082889964f9252c9ef1cd408771c238a14caa1c", "sealed Zealot impact manifest");
    using var manifestDocument = JsonDocument.Parse(File.ReadAllText(manifestPath));
    var manifest = manifestDocument.RootElement;
    var artifacts = manifest.GetProperty("artifacts");
    if (manifest.GetProperty("record_count").GetInt32() != 99 || manifest.GetProperty("stream_count").GetInt32() != 48 ||
        manifest.GetProperty("preset_count").GetInt32() != 8)
        throw new InvalidDataException("Unexpected Zealot impact manifest counts.");
    var reportPath = Path.Combine(impactRoot, "report.json");
    Safety.RequireFile(reportPath, 189331, "6303b90db522292996e41e81e397da5679e7b5052723e603122d397f3eb80f95", "sealed Zealot impact report");
    using var reportDocument = JsonDocument.Parse(File.ReadAllText(reportPath));
    var report = reportDocument.RootElement;
    var bundleArtifact = artifacts.GetProperty("bundle/3d487cca8bd5c544");
    var sourceBundle = report.GetProperty("source_bundle");
    var candidateBundle = report.GetProperty("candidate_bundle");
    if (report.GetProperty("stock_records").GetInt32() != 43 || report.GetProperty("added_records").GetInt32() != 56 ||
        report.GetProperty("candidate_records").GetInt32() != 99 ||
        candidateBundle.GetProperty("size").GetInt64() != bundleArtifact.GetProperty("size").GetInt64() ||
        candidateBundle.GetProperty("sha256").GetString() != bundleArtifact.GetProperty("sha256").GetString())
        throw new InvalidDataException("Unexpected Zealot impact report shape.");
    yield return new("impact-zealot", "bundle/3d487cca8bd5c544", Path.Combine(analysis, "stock", "bundle", "3d487cca8bd5c544"),
        sourceBundle.GetProperty("size").GetInt64(), sourceBundle.GetProperty("sha256").GetString()!,
        Path.Combine(impactRoot, "bundle", "3d487cca8bd5c544"), candidateBundle.GetProperty("size").GetInt64(),
        candidateBundle.GetProperty("sha256").GetString()!, false, "bundle/3d487cca8bd5c544");

    var profilesPath = Path.Combine(analysis, "material-profiles.json");
    Safety.RequireFile(profilesPath, 49486, "1dce4188b64c62b323522e6b2f5b64cd9d3919106cc935d7d0cbce63f8097d34", "sealed flamer material profiles");
    using var profilesDocument = JsonDocument.Parse(File.ReadAllText(profilesPath));
    var profiles = profilesDocument.RootElement.GetProperty("materials").EnumerateArray()
        .ToDictionary(value => value.GetProperty("material").GetString()!, StringComparer.Ordinal);
    var oneCcSource = P("mods/active/RainbowFlame/analysis/impact-color-20260920-a1/parents-stream/hash-only/1cc58f33452ca960.material");
    var emitted = new HashSet<string>(StringComparer.Ordinal);
    foreach (var presetProperty in report.GetProperty("presets").EnumerateObject())
    {
        var preset = presetProperty.Value;
        var hashes = preset.GetProperty("hashes");
        foreach (var parentRole in new[] { (Name: "parent_be93", Stock: "be9333164c3ddf4a"), (Name: "parent_1cc", Stock: "1cc58f33452ca960") })
        {
            var name = hashes.GetProperty(parentRole.Name).GetString()!;
            var result = preset.GetProperty(parentRole.Name);
            var material = result.GetProperty("material");
            var source = result.GetProperty("source");
            var baseTarget = parentRole.Stock == "be9333164c3ddf4a" ? "data/c5/c54a5bfcf52f138d" : "data/bb/bb79ba7a5b92d132";
            var baseSource = parentRole.Stock == "be9333164c3ddf4a"
                ? Path.Combine(analysis, "stock", "bundle", baseTarget.Replace('/', Path.DirectorySeparatorChar)) : oneCcSource;
            yield return ImpactStream(name, baseTarget, baseSource, source, material);
        }
        foreach (var child in preset.GetProperty("children").EnumerateArray())
        {
            var stockChild = child.GetProperty("stock_child").GetString()!;
            if (!profiles.TryGetValue(stockChild, out var profile))
                throw new InvalidDataException("Missing sealed material profile for impact child " + stockChild);
            var name = child.GetProperty("custom_child").GetString()!;
            var stream = child.GetProperty("stream");
            var baseTarget = profile.GetProperty("stream").GetString()!;
            yield return ImpactStream(name, baseTarget,
                Path.Combine(analysis, "stock", "bundle", baseTarget.Replace('/', Path.DirectorySeparatorChar)), profile, stream);
        }
    }

    SourceSpec ImpactStream(string name, string baseTarget, string baseSource, JsonElement source, JsonElement desired)
    {
        if (!emitted.Add(name)) throw new InvalidDataException("Duplicate Zealot impact stream identity: " + name);
        var target = "bundle/data/rf/" + name;
        if (!artifacts.TryGetProperty(target, out var artifact) ||
            artifact.GetProperty("size").GetInt64() != desired.GetProperty("size").GetInt64() ||
            artifact.GetProperty("sha256").GetString() != desired.GetProperty("sha256").GetString())
            throw new InvalidDataException("Zealot impact stream differs from sealed manifest: " + name);
        var sourceSizeName = source.TryGetProperty("stream_size", out _) ? "stream_size" : "size";
        var sourceHashName = source.TryGetProperty("stream_sha256", out _) ? "stream_sha256" : "sha256";
        return new("stream-" + name, target, baseSource, source.GetProperty(sourceSizeName).GetInt64(),
            source.GetProperty(sourceHashName).GetString()!, Path.Combine(impactRoot, "bundle", "data", "rf", name),
            desired.GetProperty("size").GetInt64(), desired.GetProperty("sha256").GetString()!, true, "bundle/" + baseTarget);
    }
    var manifestStreams = artifacts.EnumerateObject().Count(property => property.Name.StartsWith("bundle/data/rf/", StringComparison.Ordinal));
    if (emitted.Count != 48 || manifestStreams != 48)
        throw new InvalidDataException("Unexpected Zealot impact stream count.");
}

internal sealed record SourceSpec(string Id, string Target, string? BaseSource, long BaseSize, string? BaseHash,
    string OutputSource, long OutputSize, string OutputHash, bool Addition, string? BaseTarget);
