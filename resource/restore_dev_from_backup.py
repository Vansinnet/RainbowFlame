"""Restore only missing, ignored development inputs after Git history reconciliation."""

import argparse
import hashlib
from pathlib import Path


mod = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--backup", type=Path, required=True)
backup = parser.parse_args().backup.resolve()
prefix = "files/mods/active/RainbowFlame/"
restored = 0
for line in (backup / "SHA256SUMS").read_text(encoding="ascii").splitlines():
    digest, relative = line.split("  ", 1)
    if not relative.startswith(prefix):
        continue
    child = relative.removeprefix(prefix)
    if not (child.startswith("installer/") or child.startswith("payload/inserts/") or
            child in {"payload/manifest.json", "release-manifest.template.json"}):
        continue
    source = backup / relative
    data = source.read_bytes()
    if hashlib.sha256(data).hexdigest() != digest.lower():
        raise ValueError(f"Backup hash mismatch: {relative}")
    destination = mod / child
    if destination.exists():
        if destination.read_bytes() != data:
            raise ValueError(f"Existing development input differs; refusing overwrite: {destination}")
        continue
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    restored += 1
print(f"Restored {restored} missing, hash-verified development files; existing files left untouched")
