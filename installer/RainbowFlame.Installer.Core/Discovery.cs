using Microsoft.Win32;
using System.Diagnostics;
using System.Text.RegularExpressions;

namespace RainbowFlame.Installer.Core;

public static class GameDiscovery
{
    public static IEnumerable<string> FindGameRoots()
    {
        var roots = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var view in new[] { RegistryView.Registry64, RegistryView.Registry32 })
        {
            using var hive = RegistryKey.OpenBaseKey(RegistryHive.LocalMachine, view);
            using var key = hive.OpenSubKey(@"SOFTWARE\Valve\Steam");
            var steam = key?.GetValue("InstallPath") as string;
            if (steam is null) continue;
            foreach (var library in SteamLibraries(steam))
            {
                var candidate = Path.Combine(library, "steamapps", "common", "Warhammer 40,000 DARKTIDE");
                if (File.Exists(Path.Combine(candidate, "binaries", "Darktide.exe"))) roots.Add(candidate);
            }
        }
        return roots;
    }

    private static IEnumerable<string> SteamLibraries(string steam)
    {
        yield return steam;
        var file = Path.Combine(steam, "steamapps", "libraryfolders.vdf");
        if (!File.Exists(file)) yield break;
        var text = File.ReadAllText(file);
        foreach (Match match in Regex.Matches(text, "\"path\"\\s+\"([^\"]+)\"", RegexOptions.IgnoreCase))
            yield return match.Groups[1].Value.Replace("\\\\", "\\");
    }

    public static string VerifyGame(string root, PayloadManifest manifest, bool requireSupportedVersion = true)
    {
        root = Path.GetFullPath(root);
        Safety.RejectReparseAncestors(root, root, true);
        var exe = Path.Combine(root, "binaries", "Darktide.exe");
        if (!File.Exists(exe)) throw new InstallerException("The selected folder is not a Darktide game root.");
        var version = FileVersionInfo.GetVersionInfo(exe).FileVersion;
        if (requireSupportedVersion && !string.Equals(version, manifest.ExeVersion, StringComparison.Ordinal))
            throw new InstallerException($"Unsupported Darktide executable version {version}; required {manifest.ExeVersion}.");
        var steamApps = Directory.GetParent(root)?.Parent?.FullName;
        var appManifest = steamApps is null ? null : Path.Combine(steamApps, $"appmanifest_{manifest.SteamAppId}.acf");
        if (appManifest is null || !File.Exists(appManifest))
            throw new InstallerException("Steam app manifest was not found for the selected game folder.");
        var text = File.ReadAllText(appManifest);
        var build = Regex.Match(text, "\"buildid\"\\s+\"([^\"]+)\"").Groups[1].Value;
        if (requireSupportedVersion && build != manifest.SteamBuild)
            throw new InstallerException($"Unsupported Steam build {build}; required {manifest.SteamBuild}.");
        return build;
    }

    public static void VerifyDependencies(string root)
    {
        if (!Directory.Exists(Path.Combine(root, "binaries", "mod_loader")) &&
            !File.Exists(Path.Combine(root, "binaries", "mod_loader")))
            throw new InstallerException("Darktide Mod Loader (DML) is missing. Install DML before RainbowFlame.");
        var dmf = Path.Combine(root, "mods", "dmf", "dmf.mod");
        if (!File.Exists(dmf))
            throw new InstallerException("Darktide Mod Framework (DMF) is missing. Install DMF before RainbowFlame.");
    }
}
