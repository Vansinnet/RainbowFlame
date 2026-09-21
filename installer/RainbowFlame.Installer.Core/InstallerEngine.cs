using System.Security.Cryptography;

namespace RainbowFlame.Installer.Core;

public sealed class InstallerEngine
{
    private readonly string payloadRoot;
    private readonly string stateRoot;
    private readonly IProcessGuard processes;
    private readonly Action<int>? beforeWrite;

    public InstallerEngine(string payloadRoot, string? stateRoot = null, IProcessGuard? processes = null,
        Action<int>? beforeWrite = null)
    {
        this.payloadRoot = Path.GetFullPath(payloadRoot);
        this.stateRoot = Path.GetFullPath(stateRoot ?? Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "RainbowFlame"));
        this.processes = processes ?? new DarktideProcessGuard();
        this.beforeWrite = beforeWrite;
    }

    public PayloadManifest LoadManifest()
    {
        var manifestPath = Path.Combine(payloadRoot, "manifest.json");
        var manifest = Safety.ReadJson<PayloadManifest>(manifestPath);
        if (manifest.Format != 1 || manifest.Product != "RainbowFlame" || manifest.Files.Count == 0)
            throw new InstallerException("Unsupported or empty RainbowFlame payload manifest.");
        var targets = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var recipe in manifest.Files)
        {
            _ = Safety.SafePath("C:\\payload-root", recipe.Payload);
            _ = Safety.SafePath("C:\\game-root", recipe.Target);
            if (recipe.Base is not null) _ = Safety.SafePath("C:\\game-root", recipe.Base);
            if (!targets.Add(recipe.Target)) throw new InstallerException($"Duplicate target: {recipe.Target}");
            if (recipe.OutputSize < 0 || recipe.PayloadSize < 0 || recipe.Operations.Count == 0)
                throw new InstallerException($"Invalid recipe: {recipe.Id}");
        }
        return manifest;
    }

    public OperationResult Execute(string gameRoot, InstallerAction action, bool verifyEnvironment = true)
    {
        var manifest = LoadManifest();
        gameRoot = Path.TrimEndingDirectorySeparator(Path.GetFullPath(gameRoot));
        try
        {
            processes.EnsureGameStopped();
            var observedBuild = manifest.SteamBuild;
            if (verifyEnvironment)
            {
                var requireSupportedVersion = action != InstallerAction.RepairAfterUpdate;
                observedBuild = GameDiscovery.VerifyGame(gameRoot, manifest, requireSupportedVersion);
                GameDiscovery.VerifyDependencies(gameRoot);
            }
            RecoverPending(gameRoot);
            return action == InstallerAction.Uninstall
                ? Uninstall(gameRoot, manifest, verifyEnvironment)
                : InstallOrRepair(gameRoot, manifest, action, observedBuild);
        }
        catch (Exception exception) when (exception is not InstallerException)
        {
            throw new InstallerException(exception.Message, exception);
        }
    }

    private OperationResult InstallOrRepair(string gameRoot, PayloadManifest manifest, InstallerAction action,
        string observedBuild)
    {
        var receiptPath = ReceiptPath(gameRoot);
        var oldReceipt = File.Exists(receiptPath) ? Safety.ReadJson<InstallReceipt>(receiptPath) : null;
        if ((action is InstallerAction.Repair or InstallerAction.RepairAfterUpdate) && oldReceipt is null)
            throw new InstallerException("RainbowFlame is not installed by this installer; repair cannot establish ownership.");
        if (oldReceipt is not null && !Path.GetFullPath(oldReceipt.GameRoot).Equals(gameRoot, StringComparison.OrdinalIgnoreCase))
            throw new InstallerException("The ownership receipt belongs to a different game folder.");
        if ((action is InstallerAction.Repair or InstallerAction.RepairAfterUpdate) &&
            (oldReceipt!.Product != manifest.Product || oldReceipt.Version != manifest.Version ||
             oldReceipt.SteamBuild != manifest.SteamBuild ||
             oldReceipt.ExeVersion != manifest.ExeVersion))
            throw new InstallerException("The ownership receipt belongs to a different RainbowFlame release.");

        ValidateManagedModDirectory(gameRoot, manifest, oldReceipt);
        if (action == InstallerAction.RepairAfterUpdate)
            PreflightUpdateRepair(gameRoot, manifest, oldReceipt!);
        var session = DateTime.UtcNow.ToString("yyyyMMddTHHmmssfffZ") + "-" + Guid.NewGuid().ToString("N");
        var backupRoot = Path.Combine(stateRoot, "backups", manifest.SteamBuild, session);
        var journalPath = Path.Combine(stateRoot, "journals", session + ".json");
        Directory.CreateDirectory(backupRoot);
        var stageRoot = Path.Combine(gameRoot, ".rainbowflame-stage", session);
        Directory.CreateDirectory(stageRoot);
        Safety.RejectReparseAncestors(gameRoot, stageRoot, true);

        var journal = new Journal { Session = session, Action = action.ToString(), GameRoot = gameRoot };
        Safety.WriteJsonDurable(journalPath, journal);
        var receipt = new InstallReceipt
        {
            Product = manifest.Product, Version = manifest.Version, GameRoot = gameRoot, SteamBuild = manifest.SteamBuild,
            ExeVersion = manifest.ExeVersion, Session = session
        };
        var writeNumber = 0;
        try
        {
            foreach (var recipe in manifest.Files)
            {
                processes.EnsureGameStopped();
                var target = Safety.SafePath(gameRoot, recipe.Target);
                Safety.RejectReparseAncestors(gameRoot, target, true);
                Directory.CreateDirectory(Path.GetDirectoryName(target)!);
                Safety.RejectReparseAncestors(gameRoot, target, false);

                var existingKnownOutput = File.Exists(target) && IsExact(target, recipe.OutputSize, recipe.OutputSha256);
                var prior = oldReceipt?.Files.SingleOrDefault(file => file.Target.Equals(recipe.Target,
                    StringComparison.OrdinalIgnoreCase));
                var existingPriorOutput = prior is not null && File.Exists(target) &&
                    IsExact(target, prior.OutputSize, prior.OutputSha256);
                if (existingKnownOutput && prior is null)
                    throw new InstallerException($"Refusing to adopt an existing RainbowFlame output without an ownership receipt: {recipe.Target}");
                if (recipe.Addition && File.Exists(target) && !existingKnownOutput && !existingPriorOutput)
                    throw new InstallerException($"Refusing to overwrite unknown addition: {recipe.Target}");
                if (!recipe.Addition && !existingKnownOutput && !existingPriorOutput)
                    Safety.RequireFile(target, recipe.BaseSize, recipe.BaseSha256!, $"input for {recipe.Id}");

                var staged = Path.Combine(stageRoot, recipe.Id + ".stage");
                var row = new ReceiptFile
                {
                    Id = recipe.Id, Target = recipe.Target, Addition = recipe.Addition,
                    OutputSha256 = recipe.OutputSha256, OutputSize = recipe.OutputSize
                };

                if (!recipe.Addition)
                {
                    if (prior?.Backup is not null)
                    {
                        Safety.RequireFile(prior.Backup, prior.BackupSize, prior.BackupSha256!, "preserved uninstall backup");
                        row.Backup = prior.Backup;
                        row.BackupSha256 = prior.BackupSha256;
                        row.BackupSize = prior.BackupSize;
                    }
                    else
                    {
                        var backup = Path.Combine(backupRoot, recipe.Id + ".backup");
                        Safety.CopyDurable(target, backup);
                        row.Backup = backup;
                        row.BackupSize = new FileInfo(backup).Length;
                        row.BackupSha256 = Safety.Hash(backup);
                    }
                }

                if (!existingKnownOutput)
                {
                    var reconstructionBase = !recipe.Addition && existingPriorOutput ? row.Backup : null;
                    Delta.Reconstruct(recipe, payloadRoot, gameRoot, staged, reconstructionBase);
                }

                if (!existingKnownOutput)
                {
                    var targetExists = File.Exists(target);
                    var beforeSize = targetExists ? new FileInfo(target).Length : 0;
                    var beforeHash = targetExists ? Safety.Hash(target) : "absent";
                    var rollbackBackup = row.Backup;
                    if (targetExists && existingPriorOutput)
                    {
                        rollbackBackup = Path.Combine(backupRoot, recipe.Id + ".upgrade.rollback");
                        Safety.CopyDurable(target, rollbackBackup);
                    }
                    var entry = new JournalEntry
                    {
                        Target = target, Before = beforeHash, BeforeSize = beforeSize,
                        After = recipe.OutputSha256, Backup = rollbackBackup
                    };
                    journal.Entries.Add(entry);
                    Safety.WriteJsonDurable(journalPath, journal);
                    beforeWrite?.Invoke(++writeNumber);
                    processes.EnsureGameStopped();
                    if (!targetExists && File.Exists(target))
                        throw new InstallerException($"Addition appeared during installation: {recipe.Target}");
                    if (targetExists)
                    {
                        Safety.RequireFile(target, beforeSize, beforeHash, $"owned input for {recipe.Id}");
                        Safety.OverwriteDurable(staged, target);
                    }
                    else if (recipe.Addition) File.Move(staged, target);
                    else Safety.OverwriteDurable(staged, target);
                    Safety.RequireFile(target, recipe.OutputSize, recipe.OutputSha256, $"installed output for {recipe.Id}");
                    entry.Complete = true;
                    Safety.WriteJsonDurable(journalPath, journal);
                }
                receipt.Files.Add(row);
            }

            receipt.LoadOrder = InstallLoadOrder(gameRoot, backupRoot, journal, journalPath, ref writeNumber,
                oldReceipt?.LoadOrder);
            Safety.WriteJsonDurable(receiptPath, receipt);
            journal.State = "committed";
            Safety.WriteJsonDurable(journalPath, journal);
            var message = action switch
            {
                InstallerAction.Repair => "RainbowFlame repair completed and all files were verified.",
                InstallerAction.RepairAfterUpdate =>
                    $"RainbowFlame was restored after Steam build {observedBuild}. All managed file hashes were compatible and verified.",
                _ => "RainbowFlame installation completed. Backups were preserved."
            };
            return new OperationResult(true, message);
        }
        catch
        {
            Rollback(journal, journalPath);
            RemoveEmptyOwnedDirectories(gameRoot);
            throw;
        }
        finally
        {
            if (Directory.Exists(stageRoot)) Directory.Delete(stageRoot, true);
            var stageParent = Path.GetDirectoryName(stageRoot)!;
            if (Directory.Exists(stageParent) && !Directory.EnumerateFileSystemEntries(stageParent).Any())
                Directory.Delete(stageParent);
        }
    }

    private static void PreflightUpdateRepair(string gameRoot, PayloadManifest manifest, InstallReceipt receipt)
    {
        if (receipt.Files.Count != manifest.Files.Count)
            throw new InstallerException("Update repair stopped before writing: the ownership receipt has a different managed-file set.");
        foreach (var recipe in manifest.Files)
        {
            var target = Safety.SafePath(gameRoot, recipe.Target);
            Safety.RejectReparseAncestors(gameRoot, target, true);
            var exists = File.Exists(target);
            var output = exists && IsExact(target, recipe.OutputSize, recipe.OutputSha256);
            var owned = receipt.Files.SingleOrDefault(file =>
                file.Target.Equals(recipe.Target, StringComparison.OrdinalIgnoreCase));
            if (owned is null || owned.Id != recipe.Id || owned.Addition != recipe.Addition ||
                owned.OutputSize != recipe.OutputSize ||
                !owned.OutputSha256.Equals(recipe.OutputSha256, StringComparison.OrdinalIgnoreCase))
                throw new InstallerException($"Update repair stopped before writing: the ownership receipt does not match {recipe.Target}.");
            if (!recipe.Addition)
            {
                if (owned.Backup is null || owned.BackupSha256 is null)
                    throw new InstallerException($"Update repair stopped before writing: the uninstall backup is missing for {recipe.Target}.");
                Safety.RequireFile(owned.Backup, owned.BackupSize, owned.BackupSha256,
                    $"preflight uninstall backup for {recipe.Id}");
            }
            if (recipe.Addition)
            {
                if (exists && !output)
                    throw new InstallerException($"Update repair stopped before writing: unknown addition bytes at {recipe.Target}");
            }
            else if (!output)
            {
                if (!exists || new FileInfo(target).Length != recipe.BaseSize ||
                    !Safety.Hash(target).Equals(recipe.BaseSha256, StringComparison.OrdinalIgnoreCase))
                    throw new InstallerException($"Update repair stopped before writing: {recipe.Target} changed in this Darktide update. A new RainbowFlame release is required.");
            }
        }

        var loadOrder = Path.Combine(gameRoot, "mods", "mod_load_order.txt");
        Safety.RejectReparseAncestors(gameRoot, loadOrder, true);
        if (!File.Exists(loadOrder))
            throw new InstallerException("Update repair stopped before writing: DMF load-order file is missing.");
        _ = LoadOrder.Add(File.ReadAllBytes(loadOrder), "RainbowFlame");
        if (receipt.LoadOrder?.Backup is null || receipt.LoadOrder.BackupSha256 is null)
            throw new InstallerException("Update repair stopped before writing: the load-order backup is missing.");
        Safety.RequireFile(receipt.LoadOrder.Backup, receipt.LoadOrder.BackupSize,
            receipt.LoadOrder.BackupSha256, "preflight load-order backup");
    }

    private ReceiptFile InstallLoadOrder(string gameRoot, string backupRoot, Journal journal, string journalPath,
        ref int writeNumber, ReceiptFile? old)
    {
        var target = Path.Combine(gameRoot, "mods", "mod_load_order.txt");
        Safety.RejectReparseAncestors(gameRoot, target, true);
        if (!File.Exists(target)) throw new InstallerException("DMF load-order file is missing: mods/mod_load_order.txt");
        var original = File.ReadAllBytes(target);
        var updated = LoadOrder.Add(original, "RainbowFlame");
        var outputHash = Hash(updated);
        var row = new ReceiptFile { Id = "load-order", Target = "mods/mod_load_order.txt", OutputSha256 = outputHash, OutputSize = updated.Length };
        if (old?.Backup is not null)
        {
            Safety.RequireFile(old.Backup, old.BackupSize, old.BackupSha256!, "preserved load-order backup");
            row.Backup = old.Backup; row.BackupSha256 = old.BackupSha256; row.BackupSize = old.BackupSize;
        }
        else
        {
            var backup = Path.Combine(backupRoot, "mod_load_order.txt.backup");
            Safety.CopyDurable(target, backup);
            row.Backup = backup; row.BackupSize = original.Length; row.BackupSha256 = Safety.Hash(backup);
        }
        if (!original.AsSpan().SequenceEqual(updated))
        {
            var undo = Path.Combine(backupRoot, "mod_load_order.txt.rollback");
            Safety.CopyDurable(target, undo);
            var entry = new JournalEntry { Target = target, Before = Hash(original), BeforeSize = original.Length, After = outputHash, Backup = undo };
            journal.Entries.Add(entry); Safety.WriteJsonDurable(journalPath, journal);
            beforeWrite?.Invoke(++writeNumber);
            ReplaceBytesSameVolume(target, updated);
            entry.Complete = true; Safety.WriteJsonDurable(journalPath, journal);
        }
        return row;
    }

    private OperationResult Uninstall(string gameRoot, PayloadManifest manifest, bool verifyEnvironment)
    {
        var receiptPath = ReceiptPath(gameRoot);
        if (!File.Exists(receiptPath)) throw new InstallerException("No RainbowFlame ownership receipt was found.");
        var receipt = Safety.ReadJson<InstallReceipt>(receiptPath);
        if (receipt.SteamBuild != manifest.SteamBuild || receipt.ExeVersion != manifest.ExeVersion)
            throw new InstallerException("Installed receipt build differs from this installer.");
        if (verifyEnvironment) GameDiscovery.VerifyGame(gameRoot, manifest);
        var session = "uninstall-" + DateTime.UtcNow.ToString("yyyyMMddTHHmmssfffZ") + "-" + Guid.NewGuid().ToString("N");
        var journalPath = Path.Combine(stateRoot, "journals", session + ".json");
        var undoRoot = Path.Combine(stateRoot, "backups", manifest.SteamBuild, session);
        Directory.CreateDirectory(undoRoot);
        var journal = new Journal { Session = session, Action = "Uninstall", GameRoot = gameRoot };
        Safety.WriteJsonDurable(journalPath, journal);
        try
        {
            foreach (var row in receipt.Files.AsEnumerable().Reverse())
            {
                processes.EnsureGameStopped();
                var target = Safety.SafePath(gameRoot, row.Target);
                Safety.RejectReparseAncestors(gameRoot, target, true);
                Safety.RequireFile(target, row.OutputSize, row.OutputSha256, $"installed output {row.Id}");
                var undo = Path.Combine(undoRoot, row.Id + ".installed");
                Safety.CopyDurable(target, undo);
                var entry = new JournalEntry { Target = target, Before = row.OutputSha256, BeforeSize = row.OutputSize,
                    After = row.Addition ? "absent" : row.BackupSha256!, Backup = undo };
                journal.Entries.Add(entry); Safety.WriteJsonDurable(journalPath, journal);
                if (row.Addition) File.Delete(target);
                else RestoreBackup(target, row.Backup!, row.BackupSize, row.BackupSha256!);
                entry.Complete = true; Safety.WriteJsonDurable(journalPath, journal);
            }
            RemoveLoadOrderEntry(gameRoot, undoRoot, journal, journalPath, receipt.LoadOrder);
            File.Delete(receiptPath);
            journal.State = "committed"; Safety.WriteJsonDurable(journalPath, journal);
            RemoveEmptyOwnedDirectories(gameRoot);
            return new OperationResult(true, "RainbowFlame was uninstalled. Original backups remain preserved.");
        }
        catch
        {
            Rollback(journal, journalPath);
            throw;
        }
    }

    private static void ValidateManagedModDirectory(string gameRoot, PayloadManifest manifest, InstallReceipt? receipt)
    {
        var modRoot = Path.Combine(gameRoot, "mods", "RainbowFlame");
        if (!Directory.Exists(modRoot)) return;
        Safety.RejectReparseAncestors(gameRoot, modRoot, true);
        var allowed = manifest.Files.Where(file => file.Target.StartsWith("mods/RainbowFlame/", StringComparison.OrdinalIgnoreCase))
            .ToDictionary(file => Path.GetFullPath(Path.Combine(gameRoot, file.Target.Replace('/', Path.DirectorySeparatorChar))),
                StringComparer.OrdinalIgnoreCase);
        var previouslyOwned = receipt?.Files
            .Where(file => file.Target.StartsWith("mods/RainbowFlame/", StringComparison.OrdinalIgnoreCase))
            .ToDictionary(file => Path.GetFullPath(Path.Combine(gameRoot, file.Target.Replace('/', Path.DirectorySeparatorChar))),
                StringComparer.OrdinalIgnoreCase);
        foreach (var path in Directory.EnumerateFiles(modRoot, "*", SearchOption.AllDirectories))
        {
            Safety.RejectReparseAncestors(gameRoot, path, true);
            var fullPath = Path.GetFullPath(path);
            var isAllowed = allowed.TryGetValue(fullPath, out var recipe);
            var currentOutput = isAllowed && IsExact(path, recipe!.OutputSize, recipe.OutputSha256);
            var priorOutput = isAllowed && previouslyOwned is not null &&
                previouslyOwned.TryGetValue(fullPath, out var prior) &&
                IsExact(path, prior.OutputSize, prior.OutputSha256);
            if (!isAllowed || !currentOutput && !priorOutput)
                throw new InstallerException($"Refusing unknown file in the RainbowFlame mod directory: {path}");
        }
        foreach (var directory in Directory.EnumerateDirectories(modRoot, "*", SearchOption.AllDirectories))
            Safety.RejectReparseAncestors(gameRoot, directory, true);
    }

    private void RecoverPending(string gameRoot)
    {
        var directory = Path.Combine(stateRoot, "journals");
        if (!Directory.Exists(directory)) return;
        foreach (var path in Directory.EnumerateFiles(directory, "*.json"))
        {
            var journal = Safety.ReadJson<Journal>(path);
            if (journal.State != "prepared" || !Path.GetFullPath(journal.GameRoot).Equals(gameRoot, StringComparison.OrdinalIgnoreCase)) continue;
            var receiptPath = ReceiptPath(gameRoot);
            if (journal.Action == "Uninstall" && !File.Exists(receiptPath))
            {
                journal.State = "committed"; Safety.WriteJsonDurable(path, journal); continue;
            }
            if (journal.Action != "Uninstall" && File.Exists(receiptPath) &&
                Safety.ReadJson<InstallReceipt>(receiptPath).Session == journal.Session)
            {
                journal.State = "committed"; Safety.WriteJsonDurable(path, journal); continue;
            }
            Rollback(journal, path);
        }
    }

    private static void Rollback(Journal journal, string journalPath)
    {
        var errors = new List<string>();
        foreach (var entry in journal.Entries.AsEnumerable().Reverse())
        {
            try
            {
                if (!File.Exists(entry.Target))
                {
                    if (entry.Before == "absent") continue;
                    RestoreBackup(entry.Target, entry.Backup!, entry.BeforeSize, entry.Before);
                }
                else
                {
                    var current = Safety.Hash(entry.Target);
                    if (current.Equals(entry.Before, StringComparison.OrdinalIgnoreCase)) continue;
                    if (!entry.Complete && entry.Before != "absent")
                    {
                        RestoreBackup(entry.Target, entry.Backup!, entry.BeforeSize, entry.Before);
                        continue;
                    }
                    if (!current.Equals(entry.After, StringComparison.OrdinalIgnoreCase))
                        throw new InstallerException($"Unknown bytes prevent rollback: {entry.Target}");
                    if (entry.Before == "absent") File.Delete(entry.Target);
                    else RestoreBackup(entry.Target, entry.Backup!, entry.BeforeSize, entry.Before);
                }
            }
            catch (Exception error) { errors.Add(error.Message); }
        }
        journal.State = errors.Count == 0 ? "rolledBack" : "rollbackFailed";
        Safety.WriteJsonDurable(journalPath, journal);
        if (errors.Count != 0) throw new InstallerException("Rollback failed: " + string.Join(" | ", errors));
    }

    private static void RemoveLoadOrderEntry(string gameRoot, string undoRoot, Journal journal, string journalPath,
        ReceiptFile? installed)
    {
        var target = Path.Combine(gameRoot, "mods", "mod_load_order.txt");
        var current = File.ReadAllBytes(target);
        byte[]? original = null;
        if (installed?.Backup is not null && installed.BackupSha256 is not null)
        {
            Safety.RequireFile(installed.Backup, installed.BackupSize, installed.BackupSha256,
                "preserved load-order backup");
            var backup = File.ReadAllBytes(installed.Backup);
            var installedFromBackup = LoadOrder.Add(backup, "RainbowFlame");
            if (current.AsSpan().SequenceEqual(installedFromBackup)) original = backup;
        }
        var updated = original ?? LoadOrder.Remove(current, "RainbowFlame");
        if (current.AsSpan().SequenceEqual(updated)) return;
        var undo = Path.Combine(undoRoot, "mod_load_order.txt.installed");
        Safety.CopyDurable(target, undo);
        var entry = new JournalEntry
        {
            Target = target, Before = Hash(current), BeforeSize = current.Length,
            After = Hash(updated), Backup = undo
        };
        journal.Entries.Add(entry); Safety.WriteJsonDurable(journalPath, journal);
        ReplaceBytesSameVolume(target, updated);
        entry.Complete = true; Safety.WriteJsonDurable(journalPath, journal);
    }

    private static void RestoreBackup(string target, string backup, long size, string hash)
    {
        Safety.RequireFile(backup, size, hash, "rollback backup");
        var stage = Path.Combine(Path.GetDirectoryName(target)!, ".rf-restore-" + Guid.NewGuid().ToString("N"));
        Safety.CopyDurable(backup, stage);
        Safety.RequireFile(stage, size, hash, "staged rollback backup");
        Safety.OverwriteDurable(stage, target);
        Safety.RequireFile(target, size, hash, "restored rollback target");
    }

    private static void ReplaceBytesSameVolume(string target, byte[] bytes)
    {
        var stage = Path.Combine(Path.GetDirectoryName(target)!, ".rf-stage-" + Guid.NewGuid().ToString("N"));
        using (var output = new FileStream(stage, FileMode.CreateNew, FileAccess.Write, FileShare.None, 4096, FileOptions.WriteThrough))
        { output.Write(bytes); output.Flush(true); }
        Safety.OverwriteDurable(stage, target);
    }

    private static string Hash(byte[] bytes) => Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
    private static bool IsExact(string path, long size, string hash) => File.Exists(path) &&
        new FileInfo(path).Length == size && Safety.Hash(path).Equals(hash, StringComparison.OrdinalIgnoreCase);
    private string ReceiptPath(string gameRoot) => Path.Combine(stateRoot, "installations", Hash(System.Text.Encoding.UTF8.GetBytes(gameRoot.ToUpperInvariant())) + ".json");

    private static void RemoveEmptyOwnedDirectories(string root)
    {
        foreach (var relative in new[] { "mods/RainbowFlame/scripts/mods/RainbowFlame", "mods/RainbowFlame/scripts/mods", "mods/RainbowFlame/scripts", "mods/RainbowFlame", "bundle/data/rf" })
        {
            var path = Safety.SafePath(root, relative);
            if (Directory.Exists(path) && !Directory.EnumerateFileSystemEntries(path).Any()) Directory.Delete(path);
        }
    }
}
