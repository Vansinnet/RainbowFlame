"""Verify every standalone ZIP entry against its source and resource manifests."""

import hashlib
import json
import sys
from pathlib import Path
from zipfile import ZipFile


mod = Path(__file__).resolve().parents[1]
archive = Path(sys.argv[1]).resolve()
layout = json.loads((mod / "release-layout.json").read_text(encoding="utf-8"))
old = json.loads((mod / "payload/manifest.json").read_text(encoding="utf-8"))
expected = {}
for category in layout["package"].values():
    for entry in category:
        source, destination = mod / entry["source"], entry["destination"]
        if source.is_dir():
            for path in source.rglob("*"):
                if path.is_file():
                    expected[destination + "/" + path.relative_to(source).as_posix()] = path.relative_to(mod).as_posix()
        else:
            expected[destination] = entry["source"]

assert layout["profile"] == "direct" and len(expected) == 181
manifest = (archive.parent / "RainbowFlame.source.sha256").read_text(encoding="ascii").splitlines()
hashes = {path: digest.lower() for digest, path in (line.split("  ", 1) for line in manifest)}
assert len(hashes) == 182
assert set(hashes) == {"RainbowFlame/" + source for source in expected.values()} | {"RainbowFlame/release-layout.json"}
with ZipFile(archive) as zipped:
    names = zipped.namelist()
    assert len(names) == 181 and set(names) == set(expected)
    for name, source in expected.items():
        assert name.startswith("RainbowFlame/") and "\\" not in name and ".." not in Path(name).parts
        digest = hashlib.sha256(zipped.read(name)).hexdigest()
        assert digest == hashes["RainbowFlame/" + source], name
        assert digest == hashlib.sha256((mod / source).read_bytes()).hexdigest(), name
    for item in old["files"]:
        if not item["target"].startswith("bundle/"):
            continue
        resource = "RainbowFlame/payload/direct/" + item["target"].removeprefix("bundle/")
        data = zipped.read(resource)
        assert len(data) == item["outputSize"] and hashlib.sha256(data).hexdigest() == item["outputSha256"]
    assert "RainbowFlame/RainbowFlame.Installer.exe" not in names

digest, filename = (archive.parent / "RainbowFlame.zip.sha256").read_text(encoding="ascii").strip().split("  ", 1)
assert filename == archive.name and digest.lower() == hashlib.sha256(archive.read_bytes()).hexdigest()
assert json.loads((mod / "info.json").read_text(encoding="utf-8"))["version"] == "1.3.0"
print(f"Verified 181 ZIP entries, 168 resource identities and ZIP SHA-256 {digest}")
