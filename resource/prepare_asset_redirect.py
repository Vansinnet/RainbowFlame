"""Copy exactly the published Asset Redirect v2 components from Polychromatic 1.0.1."""

import argparse
import hashlib
from pathlib import Path


MOD = Path(__file__).resolve().parents[1]
COMPONENTS = (
    ("scripts/mods/Polychromatic/asset_redirect.lua", "scripts/mods/RainbowFlame/asset_redirect.lua",
     "0e0e788c7ae9f523a1a163e711b2e1a86a016cfc"),
    ("bin/asset-redirect.dll", "bin/asset-redirect.dll",
     "0267e09bc60ad50218aafd0680eb1839e49b4c44"),
)


def git_blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--polychromatic", required=True, type=Path)
    other = parser.parse_args().polychromatic
    verified = []
    for source, target, expected in COMPONENTS:
        data = (other / source).read_bytes()
        if git_blob(data) != expected:
            raise ValueError(f"Unexpected Polychromatic component: {source}")
        destination = MOD / target
        if destination.exists() and destination.read_bytes() != data:
            raise ValueError(f"Refusing to overwrite changed component: {destination}")
        verified.append((destination, data))
    for destination, data in verified:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            destination.write_bytes(data)
        print(f"Verified {destination.relative_to(MOD)}: {len(data)} bytes, SHA-256 {hashlib.sha256(data).hexdigest()}")


if __name__ == "__main__":
    main()
