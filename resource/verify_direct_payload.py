"""Verify every standalone resource against the published installer manifest."""

import hashlib
import json
import re
from pathlib import Path


mod = Path(__file__).resolve().parents[1]
old = json.loads((mod / "payload/manifest.json").read_text(encoding="utf-8"))
assert old["product"] == "RainbowFlame" and old["version"] == "1.2.0"
resources = [item for item in old["files"] if item["target"].startswith("bundle/")]
assert len(resources) == 168
expected = {}
for item in resources:
    stock = item["target"].removeprefix("bundle/")
    path = mod / "payload/direct" / stock
    data = path.read_bytes()
    assert len(data) == item["outputSize"] and hashlib.sha256(data).hexdigest() == item["outputSha256"], stock
    expected[stock] = ("virtual = true" if item["addition"] else 'sha256 = "' + item["baseSha256"] + '"')
actual = {p.relative_to(mod / "payload/direct").as_posix() for p in (mod / "payload/direct").rglob("*") if p.is_file()}
assert actual == set(expected)
text = (mod / "scripts/mods/RainbowFlame/redirect_files.lua").read_text(encoding="ascii")
entries = re.findall(r'\{ stock = "([^"]+)", file = "([^"]+)", (virtual = true|sha256 = "[a-f0-9]{64}") \}', text)
assert len(entries) == len(expected)
for stock, payload, contract in entries:
    assert stock in expected and contract == expected[stock]
    assert payload == "payload/direct/" + stock
assert len({entry[0] for entry in entries}) == len(expected)
print(f"Verified {len(expected)} authored resources, hashes, stock gates, virtual paths and redirect registrations")
