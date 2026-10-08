# RainbowFlame

RainbowFlame customizes Inferno staff and Zealot flamer streams, wall impacts,
and locally rendered persistent enemy Soulblaze in Warhammer 40,000: Darktide.

## Features

- Separate Original, custom Color/Brightness and animated Rainbow settings for
  Inferno staves and Zealot flamers, including locally rendered teammate flames.
- Independent Rainbow speed and flame Opacity controls for each weapon. The
  flames render additively, so Opacity changes their visible intensity;
  impacts and Soulblaze are unaffected by the weapon Opacity controls.
- Eight fixed impact color presets per weapon in custom Color mode.
- Enemy Soulblaze: Original, Red, Orange, Yellow, Green, Cyan, Blue, Violet
  or Pink; independent 0%, 25%, 50%, 75% or 100% opacity presets.

Changes affect new effects; existing burns keep their appearance. Gameplay
damage, buffs, audio and networking remain unchanged.

## Requirements

- Darktide Mod Loader (DML) and Darktide Mod Framework (DMF), Windows x64.
- The original game resources must match the stock SHA-256 hashes for Steam
  build `25606770` (October 2026 update). Later builds may need
  a RainbowFlame update before all custom effects work again.

## Installation

1. Download **RainbowFlame.zip** from the latest
   [GitHub release](https://github.com/Vansinnet/RainbowFlame/releases).
   Remove an earlier `RainbowFlame` mod folder so no old files remain, then
   extract the ZIP into the game's `mods` directory. The entry file should be
   `mods/RainbowFlame/RainbowFlame.mod`. Keep `bin/`, `payload/` and `scripts/`
   inside that folder. You can instead install the ZIP with a mod manager.
2. Add `RainbowFlame` to `mods/mod_load_order.txt`, or enable it through your
   mod manager. Start Darktide and open **Mod Options > RainbowFlame**.

There is no separate installer or .NET runtime requirement. The mod folder
includes [Reforge](https://github.com/Vansinnet/Reforge) (`reforge.lua` and
`bin/reforge.dll`), an open-source library that serves the mod's files in
place of the game's while Darktide runs. At startup, RainbowFlame registers
166 custom resource files from its own folder. Original resources are
SHA-256 checked; the game files under `bundle/` are not modified.

The replaced weapon effect bundles keep the exact size and layout of the
originals, because Darktide reads them before mods start. The colour presets
RainbowFlame adds (impact and enemy Soulblaze variants) live in an unused
debug package, which RainbowFlame loads itself once Reforge is running. All
resources must be served before custom effects are enabled. If a resource is
missing, was changed by a game update, or is displaced by another mod,
RainbowFlame leaves its effects stock and reports why in the log/chat. Type
`/reforge` in chat to list every replaced file and its state. Restart
Darktide if it reports `restart_required`.

### Upgrading from the installer-based 1.2.0 or earlier

With Darktide **closed**, run **Uninstall** using your old RainbowFlame
installer before using this ZIP. This restores the stock resources and
removes that installer's material additions. The redirect cannot adopt
previously modified game files: its original-file hash checks would fail.
If you deployed a separate local development trial, use its own rollback
receipts to restore only its owned files first.

For future direct-install updates, replace the entire `mods/RainbowFlame`
folder. To uninstall a direct-install release, remove that folder and its
load-order entry; there are no game-resource files to restore.

## Compatibility and testing

Polychromatic also replaces 9 of the same flame resources, and
the two mods' edits cannot be combined. When Polychromatic is installed,
Reforge leaves those files to it: RainbowFlame reports that Polychromatic
replaces the same resources, withdraws all of its own files and keeps its
custom effects off instead of mixing incompatible files. Use one of the two mods for flame effects. Other
resource-replacement mods may conflict in the same way; RainbowBarrels and
BurningTertium do not.

Version 1.4.2 fixes custom-colour wall impacts that could render as flat
colour squares, depending on load order. This fix has not been tested in
game.

Version 1.4.1 rebuilds the material streams for the October 2026 update.
All 166 resource registrations match Steam build `25606770` in offline
Reforge verification. The rebuilt shader programs were validated offline;
this version has not been tested in game.

Version 1.4.0 was tested in game on Steam build `24735202` together with
RainbowBarrels and BurningTertium. `/reforge` reported all files active, and
staff and flamer colours, impact presets and enemy Soulblaze colours worked
with no errors. Regular dedicated-server missions and running alongside
Polychromatic have not been tested in game. The packaged resource bytes, Lua
syntax and archive contents are validated offline.

## Privacy and license

RainbowFlame adds no telemetry or network communication. The mod is
source-visible but proprietary; see [LICENSE](LICENSE), [NOTICE](NOTICE)
and [the release notes](https://github.com/Vansinnet/RainbowFlame/releases). The
[reverse-engineering diary](https://github.com/Vansinnet/RainbowFlame/blob/main/REVERSE_ENGINEERING.md)
documents the resource research and earlier installer releases.
