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
  build `24735202` / Darktide executable `1.3.770.210`. Later builds may need
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

There is no separate installer or .NET runtime requirement. The complete mod
folder includes Asset Redirect v2 from Polychromatic 1.0.1; **Polychromatic
itself is not required**. At startup, RainbowFlame registers 168 custom
resource files from its own folder. Original resources are SHA-256 checked;
the game files under `bundle/` are not modified. All redirects must be active
or shared before custom effects are enabled. If a resource is missing, was
changed by a game update, or is displaced by another mod, RainbowFlame leaves
its effects stock and reports the incomplete status in the log/chat. Restart
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

Asset Redirect resolves overlapping registrations by priority and load
order. Polychromatic also replaces several flame and Soulblaze resources;
the two mods' different resource edits are **not automatically combined**.
When another mod owns a required redirect, RainbowFlame reports incomplete
resources and leaves its custom effects stock instead of mixing incompatible
files. Other resource-replacement mods may likewise conflict.

The prior resource effects were user-tested on the supported build in the
Psykanium: staff Original, Color and Rainbow, enemy presets, Zealot flamer
bursts and streams, impacts and Opacity. Regular dedicated-server missions,
the new direct-install path and interaction with Polychromatic have **not**
been independently verified in game for this release. The packaged resource
bytes, Lua syntax and archive contents are validated offline.

## Privacy and license

RainbowFlame adds no telemetry or network communication. The mod is
source-visible but proprietary; see [LICENSE](LICENSE), [NOTICE](NOTICE)
and [CHANGELOG.md](CHANGELOG.md). The
[reverse-engineering diary](https://github.com/Vansinnet/RainbowFlame/blob/main/REVERSE_ENGINEERING.md)
documents the resource research and earlier installer releases.
