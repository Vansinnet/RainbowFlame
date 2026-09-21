# RainbowFlame

RainbowFlame customizes the Inferno staff's flame and persistent enemy Soulblaze
effects in Warhammer 40,000: Darktide.

## Features

- Staff modes: Original, a custom hue and brightness, or an animated Rainbow,
  applied to locally rendered Inferno streams from you and your teammates.
- Adjustable Rainbow speed.
- Adjustable staff-flame opacity in Original, custom Color, and Rainbow modes.
- Enemy Soulblaze presets: Original, Red, Orange, Yellow, Green, Cyan, Blue,
  Violet, and Pink.
- Enemy Soulblaze opacity presets: 0%, 25%, 50%, 75%, and 100%.
- Enemy presets affect newly created, locally rendered persistent Soulblaze only.
  Existing effects keep their current appearance, and gameplay damage, buffs,
  impacts, and network state are unchanged.

The staff flame uses additive rendering, so Opacity scales its final visible
intensity rather than conventional alpha blending. `0` hides the stream and `1`
keeps its full visibility. Wall impacts and enemy Soulblaze are unaffected.

## Requirements

- Darktide Mod Loader (DML)
- Darktide Mod Framework (DMF)
- Microsoft [.NET 10 Desktop Runtime](https://dotnet.microsoft.com/en-us/download/dotnet/10.0),
  Windows x64
- Supported Darktide build: build ID `24735202`, executable
  `1.3.770.210`

Later Darktide builds are unsupported until a RainbowFlame release explicitly
lists them. Game updates can change the assets this mod depends on even when the
Lua mod still loads.

## Installation

1. Install DML and DMF and confirm that DMF loads successfully in Darktide.
2. Install the Microsoft .NET 10 Desktop Runtime for Windows x64 if it is not
   already present.
3. Download the official, unmodified `RainbowFlame.zip` release and extract the
   entire archive to one folder. Keep the installer DLLs and `payload/` directory
   beside `RainbowFlame.Installer.exe`.
4. Close Darktide completely. The installer refuses to continue while the game
   is running.
5. Run `RainbowFlame.Installer.exe`. Select the
   `Warhammer 40,000 DARKTIDE` game folder if it is not detected automatically,
   then choose **Install**.
6. Wait for the installer to verify the game build, original resource hashes,
   generated files and backups. An unknown game build or conflicting resource
   replacement is rejected rather than overwritten.
7. Start Darktide and open **Mod Options > RainbowFlame**. A changed enemy
   Soulblaze preset applies to newly created burns; existing burns retain their
   previous color.

The installer is the primary installation method. Copying the `RainbowFlame`
folder into Darktide's `/mods` directory alone is insufficient because the mod
also requires game-resource files installed outside that folder. Do not combine
files from different RainbowFlame releases. The installer is framework-dependent
and does not access the network or download the required .NET runtime.

The installer is currently unsigned. Windows SmartScreen may
therefore identify it as coming from an unknown publisher. Download RainbowFlame
only from this repository's official Releases page and verify the included
`RainbowFlame.zip.sha256` value before running it. Do not disable antivirus
protection to install the mod.

The repository versions the installer payload together with the Lua mod. The
`payload/` directory contains a manifest and compact authenticated delta data,
not complete extracted Darktide bundles. Every release must update and validate
the mod files and payload as one matching set.

### Update Or Repair

Close Darktide and run the installer from the new release. Choose **Install** to
install a supported update, or **Repair** to reconstruct missing files from the
same installed release. Repair requires an ownership receipt created by the
installer. Never combine the installer, DLLs or payload from different releases.

If a Darktide update overwrites RainbowFlame, run the same installed release and
choose **Repair after update**. This action permits a changed Steam build and
executable version only after every managed file passes a complete hash preflight.
It restores files when all replacements still match their known stock inputs and
all additions are absent or exact. If Fatshark changed a required resource, it
stops before writing anything; wait for a RainbowFlame release that supports the
new build. Passing this repair verifies file compatibility, not general game or
mod-framework compatibility on the new build.

### Uninstall

Close Darktide, run the same release's installer and choose **Uninstall**. The
installer verifies the installed files, restores its same-build backups, removes
only files it owns and removes RainbowFlame from `mod_load_order.txt`. Do not
delete replaced files manually. If Darktide has updated since installation, use a
RainbowFlame release that explicitly supports the new build; the installer will
not restore obsolete game files over a newer build.

### Vortex And Manual Installation

Vortex installation is not currently supported. Copying only the included
`RainbowFlame/` folder into `/mods` installs the Lua files but not the required
compiled resources, so the complete feature set will not work. Use the bundled
installer for installation, repair and removal.

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
