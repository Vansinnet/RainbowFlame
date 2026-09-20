# Changelog

All notable release-facing changes to RainbowFlame are documented here.

## [Unreleased]

## [1.0.0-rc7] - 2026-09-20

### Added

- Eight fixed wall-impact color presets selected from the custom hue setting.
- A separate **Repair after update** action that permits game-version drift only
  after every managed file, ownership record, and backup passes a full hash
  preflight.
- Public installation, compatibility, troubleshooting, privacy, and runtime
  coverage documentation.
- Proprietary source-visible license, third-party notice, security policy, and
  contribution policy.
- Repository hygiene, issue forms, release metadata template, and CI checks.

### Changed

- Targeted the installer at the supported .NET 10 Desktop Runtime for Windows
  x64 instead of the end-of-life .NET 6 runtime.
- Limited enemy-color presets to persistent enemy Soulblaze while restoring
  `original_color` as the stock wall-impact control.
- Removed Swedish localization; English remains the supported language.
- Removed obsolete pre-release and prior replacement wording from user-facing
  documentation and localization.
