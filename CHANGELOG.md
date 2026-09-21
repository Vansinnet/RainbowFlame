# Changelog

All notable release-facing changes to RainbowFlame are documented here.

## [Unreleased]

## [1.1.0] - 2026-09-21

### Added

- Added an **Opacity** setting for locally rendered Inferno staff streams in
  Original, custom Color, and Rainbow modes.
- Added 0%, 25%, 50%, 75%, and 100% opacity presets for newly created enemy
  Soulblaze effects, independently of the staff opacity setting.

### Changed

- Organized mod options into Soulblaze, Flame, and Rainbow groups.

### Fixed

- Extended teammate Inferno stream controls across all verified flame-ramp
  layers so hue, Rainbow, brightness, opacity, and Original mode affect the
  visible stream rather than only the section nearest the staff.

## [1.0.1] - 2026-09-21

### Fixed

- Applied the selected Inferno staff color to other players' locally rendered
  third-person flame streams in missions.
- Allowed a new installer release to replace files that exactly match its
  ownership receipt while preserving rollback and unknown-file refusal.

## [1.0.0] - 2026-09-20

### Added

- Eight fixed wall-impact color presets selected from the custom hue setting.
- A separate **Repair after update** action that permits game-version drift only
  after every managed file, ownership record, and backup passes a full hash
  preflight.
- Public installation, compatibility, troubleshooting, privacy, and runtime
  coverage documentation.
- Proprietary source-visible license, third-party notice, release metadata, and
  CI checks.

### Changed

- Targeted the installer at the supported .NET 10 Desktop Runtime for Windows
  x64 instead of the end-of-life .NET 6 runtime.
- Limited enemy-color presets to persistent enemy Soulblaze while restoring
  `original_color` as the stock wall-impact control.
- Removed Swedish localization; English remains the supported language.
- Removed obsolete pre-release and prior replacement wording from user-facing
  documentation and localization.
