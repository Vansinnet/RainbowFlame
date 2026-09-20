namespace RainbowFlame.Installer.Core;

public static class Delta
{
    public static void Reconstruct(FileRecipe recipe, string payloadRoot, string gameRoot, string destination)
    {
        var payload = Safety.SafePath(payloadRoot, recipe.Payload);
        Safety.RequireFile(payload, recipe.PayloadSize, recipe.PayloadSha256, $"payload for {recipe.Id}");
        var basePath = recipe.Base is null ? null : Safety.SafePath(gameRoot, recipe.Base);
        if (basePath is not null)
            Safety.RequireFile(basePath, recipe.BaseSize, recipe.BaseSha256!, $"authenticated base for {recipe.Id}");

        using (var source = basePath is null ? null : new FileStream(basePath, FileMode.Open, FileAccess.Read, FileShare.Read))
        using (var inserts = new FileStream(payload, FileMode.Open, FileAccess.Read, FileShare.Read))
        using (var output = new FileStream(destination, FileMode.CreateNew, FileAccess.Write, FileShare.None,
                   1024 * 1024, FileOptions.WriteThrough))
        {
            var buffer = new byte[1024 * 1024];
            foreach (var operation in recipe.Operations)
            {
                var input = operation.Kind == DeltaKind.Copy ? source : inserts;
                if (input is null) throw new InstallerException($"COPY without a base in {recipe.Id}");
                if (operation.Offset < 0 || operation.Count < 0 || operation.Offset + operation.Count > input.Length)
                    throw new InstallerException($"Out-of-range delta operation in {recipe.Id}");
                input.Position = operation.Offset;
                var remaining = operation.Count;
                while (remaining > 0)
                {
                    var read = input.Read(buffer, 0, Math.Min(buffer.Length, remaining));
                    if (read == 0) throw new EndOfStreamException();
                    output.Write(buffer, 0, read);
                    remaining -= read;
                }
            }
            output.Flush(true);
        }
        Safety.RequireFile(destination, recipe.OutputSize, recipe.OutputSha256, $"reconstructed output for {recipe.Id}");
    }
}
