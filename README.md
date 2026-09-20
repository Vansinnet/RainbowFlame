# RainbowFlame

RainbowFlame customizes the Inferno staff's flame and persistent enemy Soulblaze
effects in Warhammer 40,000: Darktide.

## Features

- Staff modes: Original, a custom hue and brightness, or an animated Rainbow.
- Adjustable Rainbow speed.
- Enemy Soulblaze presets: Original, Red, Orange, Yellow, Green, Cyan, Blue,
  Violet, and Pink.
- Enemy presets affect newly created, locally rendered persistent Soulblaze only.
  Existing effects keep their current appearance, and gameplay damage, buffs,
  impacts, and network state are unchanged.

## Requirements

- Darktide Mod Loader (DML)
- Darktide Mod Framework (DMF)
- Microsoft [.NET 6 Desktop Runtime](https://dotnet.microsoft.com/en-us/download/dotnet/6.0/runtime),
  Windows x64
- Supported Darktide build: build ID `24735202`, executable
  `1.3.770.210`

Later Darktide builds are unsupported until a RainbowFlame release explicitly
lists them. Game updates can change the assets this mod depends on even when the
Lua mod still loads.

## Installation

1. Close Darktide completely.
2. Install DML and DMF if they are not already installed.
3. Download the official, unmodified RainbowFlame release.
4. Run `RainbowFlame.Installer.exe` and follow its prompts.
5. Start Darktide and configure RainbowFlame under DMF's Mod Options.

The installer is the primary installation method. Copying the `RainbowFlame`
folder into Darktide's `/mods` directory alone is insufficient because the mod
also requires game-resource files installed outside that folder. Do not combine
files from different RainbowFlame releases. The installer is framework-dependent
and does not access the network or download the required .NET runtime.

The repository versions the installer payload together with the Lua mod. The
`payload/` directory contains a manifest and compact authenticated delta data,
not complete extracted Darktide bundles. Every release must update and validate
the mod files and payload as one matching set.

## Compatibility

RainbowFlame can conflict with mods or manual asset replacements that alter the
same Inferno staff or enemy Soulblaze resources. Remove those changes before
installing RainbowFlame. Recheck compatibility after every Darktide update and
wait for a release that names the new build.

## Troubleshooting

- Confirm Darktide was closed during installation.
- Confirm the game build is exactly `24735202` / `1.3.770.210`.
- Confirm DML and DMF load correctly before troubleshooting RainbowFlame.
- Remove other flame, Soulblaze, particle, shader, or asset replacement mods.
- Reinstall the same official release with its installer; do not repair it by
  copying only the `/mods` folder.
- Include the Darktide build, RainbowFlame release, selected settings, conflicting
  mods, and relevant console-log excerpt in a bug report.

## Runtime Coverage

User testing on the supported build covered the Psykanium with the staff's
Original, Custom, and Rainbow modes and the enemy preset feature. The installed
local build was reported working ("perfekt"). Enemy presets were confirmed
collectively; no individual per-color test matrix has been recorded. Regular
missions and dedicated-server behavior are not claimed as user-tested here.

## Privacy

RainbowFlame does not add telemetry, analytics, account access, or network
communication. Darktide, its platform services, DML, and DMF have their own
behavior and policies.

## License

The source is visible for inspection, but RainbowFlame is not open source. It is
proprietary and may be used only under the restrictive terms in [LICENSE](LICENSE).
Personal use is limited to an official, unmodified release. See [NOTICE](NOTICE)
for third-party ownership and affiliation information.
