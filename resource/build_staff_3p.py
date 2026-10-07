"""Name the four verified flame-ramp clouds in the retained Inferno 3P particle."""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import struct
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[4]
RESOURCE = Path(__file__).resolve().parent
ANALYSIS = ROOT / "docs/analysis-rainbow-staff-3p-20260921-a1"
E1 = ROOT / "docs/analysis-flame-bundle-roundtrip-20260917-e1"
sys.path[:0] = [str(RESOURCE), str(E1)]

clouds = importlib.import_module("clouds")
fmt = importlib.import_module("format8")
bundle_roundtrip = importlib.import_module("run")

ORIGINAL_SHA256 = "65fcde9a26dd0eb18c5d1dcab9e910908bb6d32b3802bea5bb7286c47849e153"
PARTICLE_SHA256 = "e38764e74122c85bcdb2a803a5876d82d14424b75c2331866126a93f69a43f8f"
OODLE_SHA256 = "8595a4795f1e0c7f548598f3e2aa528b6be5456c6d934c665182eaecb04156c0"
FLAME_CLOUDS = (
    (0, "RainbowFlame_stream_a", "a8dc696a363ec3d3"),
    (1, "RainbowFlame_stream_3p_b", "20b91c9f8a8cc4aa"),
    (3, "RainbowFlame_stream_3p_c", "20b91c9f8a8cc4aa"),
    (7, "RainbowFlame_stream_3p_d", "2d0708b33f17b5e4"),
)
EXPECTED_IDS = (
    0x6A78A433,
    0xDE38F24D,
    0x338F085C,
    0x0E4CC94E,
    0x2AE5264A,
    0x31E6394A,
    0xC4066BEE,
    0x4EBC3BAD,
    0x2E18CE3F,
    0x3FC912CF,
)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def main(output):
    output = Path(output).resolve()
    if output.parent != ANALYSIS or output.exists():
        raise ValueError("Output must be a new file in the retained 3P analysis directory")

    original = (ANALYSIS / "original.bundle").read_bytes()
    extraction = json.loads((ANALYSIS / "extraction.json").read_text(encoding="utf-8"))
    if sha256(original) != ORIGINAL_SHA256 or extraction["bundle_sha256"] != ORIGINAL_SHA256:
        raise ValueError("Retained 3P bundle identity changed")

    checks, _ = clouds.dependencies()
    oodle = Path(r"D:\Steam\steamapps\common\Warhammer 40,000 DARKTIDE\binaries\oo2core_9_win64.dll")
    if sha256(oodle.read_bytes()) != OODLE_SHA256:
        raise ValueError("Pinned Oodle identity changed")
    container = fmt.read(original, bundle_roundtrip.decoder(oodle))
    records = fmt.records(container)
    start, body, tail = records[0]["bodies"][0]
    if start != 38 or tail or sha256(records[0]["raw"]) != PARTICLE_SHA256:
        raise ValueError("Retained 3P particle identity changed")

    rows = checks.prefixes(body)
    ids = tuple(int(row["cloud_id32"], 16) for row in rows)
    if ids != EXPECTED_IDS or rows[0]["material_candidate"] != "a8dc696a363ec3d3":
        raise ValueError("Unexpected 3P cloud/material profile")

    renamed = bytearray(body)
    mappings = []
    expected = list(EXPECTED_IDS)
    for index, name, material in FLAME_CLOUDS:
        row = rows[index]
        if struct.unpack_from('<I', body, row['visualizer'])[0] != 0 or row['material_candidate'] != material:
            raise ValueError('Flame billboard/material profile changed')
        new_id = checks.r.murmur(name) >> 32
        old_id = EXPECTED_IDS[index]
        offset = start + row['start']
        if clouds.positions(container.logical, struct.pack('<I', old_id)) != [offset]:
            raise ValueError('Unresolved cloud reference')
        if new_id in expected or clouds.positions(container.logical, struct.pack('<I', new_id)):
            raise ValueError('Cloud identity collision')
        struct.pack_into('<I', renamed, row['start'], new_id)
        expected[index] = new_id
        mappings.append(dict(record=index, name=name, material=material,
                             old_id32=f'{old_id:08x}', new_id32=f'{new_id:08x}', offset=offset))
    after_rows = checks.prefixes(renamed)
    if tuple(int(row["cloud_id32"], 16) for row in after_rows) != tuple(expected):
        raise ValueError("3P cloud rename did not preserve the profile")

    logical = container.logical[:start] + renamed + container.logical[start + len(body):]
    candidate = fmt.stored(container, logical)
    rebuilt = fmt.read(candidate)
    rebuilt_records = fmt.records(rebuilt)
    if len(records) != len(rebuilt_records):
        raise ValueError(f"3P bundle resource count changed: {len(records)} to {len(rebuilt_records)}")
    if any(before["raw"] != after["raw"] for before, after in zip(records[1:], rebuilt_records[1:])):
        raise ValueError("A non-particle 3P resource changed")

    reverse = bytearray(rebuilt.logical)
    for mapping in mappings:
        struct.pack_into('<I', reverse, mapping['offset'], int(mapping['old_id32'], 16))
    if bytes(reverse) != container.logical:
        raise ValueError("3P cloud rename is not logically reversible")

    output.write_bytes(candidate)
    report = {
        "status": "AUTHORED 3P CLOUD RENAME; OFFLINE VERIFIED, RUNTIME UNTESTED",
        "source": "original.bundle",
        "source_size": len(original),
        "source_sha256": ORIGINAL_SHA256,
        "output": output.name,
        "output_size": len(candidate),
        "output_sha256": sha256(candidate),
        "particle_sha256": sha256(rebuilt_records[0]["raw"]),
        "clouds": mappings,
        "unchanged_other_resources": len(records) - 1,
        "exact_logical_reverse_roundtrip": True,
    }
    report_path = output.with_suffix(".json")
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    main(parser.parse_args().output)
