# RainbowFlame Installer

The .NET 10 x64 WinForms application is a transparent, framework-dependent
installer. It uses only managed .NET APIs and does not use networking, scripts,
shell execution, WMI, elevation, unsafe code, native FFI, packing, or obfuscation.

The UI delegates Install, Repair, and Uninstall to the tested core. The core gates
Steam build `24735202` and executable version `1.3.770.210`, checks that Darktide is
stopped with `Process.GetProcessesByName`, explains missing DML/DMF dependencies,
rejects reparse points and unknown files, reconstructs authenticated COPY/INSERT
deltas, stages on the game volume, writes durable journals, rolls back failures,
and preserves versioned backups under `%LOCALAPPDATA%/RainbowFlame/backups`.

`Repair after update` permits Steam build and executable-version drift only for an
existing owned installation. Before creating a journal or writing anything, it
requires every managed replacement to match either the known stock input or the
RainbowFlame output, and every managed addition to be absent or exact. If an update
changed a required bundle, it stops and requires a new RainbowFlame release.

Build and test from this directory:

```text
dotnet build RainbowFlame.Installer.sln -c Release
dotnet run --project RainbowFlame.Installer.Tests -c Release
dotnet run --project tools/RainbowFlame.PayloadGenerator -c Release -- --workspace <workspace-root>
```

Tests create disposable fixtures under the system temporary directory. They never
write to an installed game.
