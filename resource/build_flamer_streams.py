"""Author verified Zealot flamer stream cloud renames from retained stock bundles."""
import argparse
import ctypes as C
import hashlib
import json
from pathlib import Path
import struct
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[4]
RESOURCE = Path(__file__).resolve().parent
ANALYSIS = ROOT / "mods/active/RainbowFlame/analysis/flamer-streams-20260922-a1"
AUTHORED = ANALYSIS / "authored"
E1 = ROOT / "docs/analysis-flame-bundle-roundtrip-20260917-e1"
T1 = ROOT / "docs/analysis-rainbow-live-controls-20260918-t1"
OODLE = Path(r"D:\Steam\steamapps\common\Warhammer 40,000 DARKTIDE\binaries\oo2core_9_win64.dll")

PROFILE_SHA256 = "8ab02e61ebe7d03f60a66712a4af39ff846db8571a3c95bac62353def4218423"
OODLE_SHA256 = "8595a4795f1e0c7f548598f3e2aa528b6be5456c6d934c665182eaecb04156c0"
PARTICLE_EXTENSION = 0xA8193123526FAD64
SPECS = (
    {
        "kind": "continuous",
        "path": "content/fx/particles/weapons/rifles/player_flamer/flamer_code_control",
        "bundle": "e605c5550cf3088b",
        "source_sha256": "eb74db948d7983eeb7ba6c27fbeaa3562d2f9c7dada83b8176f09a6145fa9743",
        "particle_sha256": "8d80ea58b96a49d74a6782728c4f7f26bfb9bf6728215e5a5c583b1a2ad51931",
        "records": (2, 3, 5, 6),
    },
    {
        "kind": "burst",
        "path": "content/fx/particles/weapons/rifles/player_flamer/flamer_code_control_burst",
        "bundle": "f3952b5fba574342",
        "source_sha256": "d9e012a29d3f9193690fd187b01eb1bad35899dac7a8a252a5a57f2ed78cf0bd",
        "particle_sha256": "4b76aacf6c7d1ebf5de7b2db56b14d60ee0812f939c37315ce720f1058390a02",
        "records": (1, 2, 3, 5, 6),
    },
    {
        "kind": "3p",
        "path": "content/fx/particles/weapons/rifles/player_flamer/flamer_code_control_3p",
        "bundle": "299f23117d653583",
        "source_sha256": "debb237ed0d16f6fed4adb2640bbf8ac398e9f8ec93f11f7a1cb432c01a114b8",
        "particle_sha256": "092b195f97da26b0fd25876a169cb8265dc4cd5350c3d4ce4db0fbe587e47ccc",
        "records": (0, 1, 3),
    },
)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def positions(data, needle):
    found, offset = [], 0
    while (offset := data.find(needle, offset)) >= 0:
        found.append(offset)
        offset += 1
    return found


def load_dependencies():
    import importlib

    sys.path[:0] = [str(RESOURCE), str(E1), str(T1)]
    clouds = importlib.import_module("clouds")
    checks, fmt = clouds.dependencies()
    return checks, fmt


def decoder(path=OODLE):
    data = path.read_bytes()
    if len(data) != 645120 or sha256(data) != OODLE_SHA256:
        raise ValueError("Pinned Oodle decoder identity changed")
    lib = C.CDLL(str(path))
    memory_size = lib.OodleLZDecoder_MemorySizeNeeded
    memory_size.argtypes, memory_size.restype = [C.c_int32, C.c_int64], C.c_uint64
    scratch_size = memory_size(-1, -1)
    if not 0 < scratch_size <= 16 * 1024 * 1024:
        raise ValueError("Oodle scratch bound")
    scratch = C.create_string_buffer(scratch_size)
    decompress = lib.OodleLZ_Decompress
    decompress.argtypes = [C.c_void_p, C.c_uint64, C.c_void_p, C.c_uint64,
                           C.c_int, C.c_int, C.c_int, C.c_void_p, C.c_uint64,
                           C.c_void_p, C.c_void_p, C.c_void_p, C.c_uint64, C.c_int]
    decompress.restype = C.c_uint64

    def unpack(block):
        source, output = C.create_string_buffer(block), C.create_string_buffer(0x80000)
        actual = decompress(source, len(block), output, 0x80000, 1, 0, 3, None, 0,
                            None, None, scratch, scratch_size, 3)
        if actual != 0x80000:
            raise ValueError("Oodle output length")
        return output.raw

    return unpack


def names_for(spec):
    return tuple(f"RainbowFlame_flamer_{spec['kind']}_{chr(97 + i)}"
                 for i in range(len(spec["records"])))


def profile_map():
    raw = (ANALYSIS / "particle-profiles.json").read_bytes()
    if sha256(raw) != PROFILE_SHA256:
        raise ValueError("Retained particle profiles changed")
    profiles = json.loads(raw)["profiles"]
    result = {row["path"]: row for row in profiles}
    if len(result) != len(profiles):
        raise ValueError("Duplicate retained particle profile")
    return result


def author_one(spec, profile, checks, fmt, unpack, all_new_ids):
    source_path = ANALYSIS / "stock/bundle" / spec["bundle"]
    original = source_path.read_bytes()
    if len(original) != profile["bundle_size"] or sha256(original) != spec["source_sha256"]:
        raise ValueError(f"Retained source identity changed: {spec['kind']}")
    if profile["bundle"] != spec["bundle"] or profile["bundle_sha256"] != spec["source_sha256"]:
        raise ValueError(f"Profile source identity changed: {spec['kind']}")

    container = fmt.read(original, unpack)
    records = fmt.records(container)
    matches = [record for record in records
               if record["identity"][:2] == (PARTICLE_EXTENSION, int(profile["name_hash"], 16))]
    if len(matches) != 1 or matches[0] is not records[0]:
        raise ValueError(f"Expected one first particle record: {spec['kind']}")
    particle = matches[0]
    if sha256(particle["raw"]) != spec["particle_sha256"] or len(particle["bodies"]) != 1:
        raise ValueError(f"Particle identity changed: {spec['kind']}")
    body_start, body, tail = particle["bodies"][0]
    if body_start != 38 or tail or len(particle["raw"]) != profile["particle_size"]:
        raise ValueError(f"Particle wrapper changed: {spec['kind']}")

    before_rows = checks.prefixes(body)
    if before_rows != profile["clouds"] or len(before_rows) != profile["cloud_count"]:
        raise ValueError(f"Whole cloud profile changed: {spec['kind']}")
    if struct.unpack_from("<I", body, 36)[0] != profile["variables"]:
        raise ValueError(f"Particle variable profile changed: {spec['kind']}")

    renamed = bytearray(body)
    mappings = []
    names = names_for(spec)
    for index, name in zip(spec["records"], names):
        row = before_rows[index]
        if row["index"] != index or row["material_candidate"] is None:
            raise ValueError(f"Selected material candidate changed: {spec['kind']} record {index}")
        visualizer = struct.unpack_from("<I", body, row["visualizer"])[0]
        if visualizer != 0:
            raise ValueError(f"Selected record is not a billboard: {spec['kind']} record {index}")
        old_id = int(row["cloud_id32"], 16)
        new_id = checks.r.murmur(name) >> 32
        logical_offset = body_start + row["start"]
        old_hits = positions(container.logical, struct.pack("<I", old_id))
        if old_hits != [logical_offset]:
            raise ValueError(f"Old cloud reference is not unique: {spec['kind']} record {index}")
        if new_id not in all_new_ids or positions(container.logical, struct.pack("<I", new_id)):
            raise ValueError(f"Authored cloud identity collision: {name}")
        struct.pack_into("<I", renamed, row["start"], new_id)
        mappings.append({
            "record": index,
            "name": name,
            "old_id32": f"{old_id:08x}",
            "new_id32": f"{new_id:08x}",
            "material_candidate": row["material_candidate"],
            "visualizer": visualizer,
            "body_offset": row["start"],
            "logical_offset": logical_offset,
            "old_reference_hits": old_hits,
        })

    after_rows = checks.prefixes(renamed)
    selected = set(spec["records"])
    expected_ids = {row["record"]: row["new_id32"] for row in mappings}
    for before, after in zip(before_rows, after_rows):
        expected = dict(before)
        if before["index"] in selected:
            expected["cloud_id32"] = expected_ids[before["index"]]
        if after != expected:
            raise ValueError(f"Cloud profile field changed: {spec['kind']} record {before['index']}")

    logical = container.logical[:body_start] + bytes(renamed) + container.logical[body_start + len(body):]
    candidate = fmt.stored(container, logical)
    rebuilt = fmt.read(candidate)
    rebuilt_records = fmt.records(rebuilt)
    if rebuilt.prefix != container.prefix or rebuilt.final_padding != container.final_padding:
        raise ValueError(f"Format-8 envelope changed: {spec['kind']}")
    if len(rebuilt_records) != len(records):
        raise ValueError(f"Resource count changed: {spec['kind']}")
    if any(before["raw"] != after["raw"]
           for before, after in zip(records[1:], rebuilt_records[1:])):
        raise ValueError(f"Non-particle resource changed: {spec['kind']}")
    for mapping in mappings:
        hits = positions(rebuilt.logical, struct.pack("<I", int(mapping["new_id32"], 16)))
        if hits != [mapping["logical_offset"]]:
            raise ValueError(f"New cloud reference is not unique: {mapping['name']}")
        mapping["new_reference_hits"] = hits

    reverse = bytearray(rebuilt.logical)
    for mapping in mappings:
        struct.pack_into("<I", reverse, mapping["logical_offset"], int(mapping["old_id32"], 16))
    if bytes(reverse) != container.logical:
        raise ValueError(f"Exact logical reverse failed: {spec['kind']}")
    changed = [i for i, (before, after) in enumerate(zip(container.logical, rebuilt.logical))
               if before != after]
    allowed = {mapping["logical_offset"] + byte for mapping in mappings for byte in range(4)}
    if not set(changed) <= allowed:
        raise ValueError(f"Logical edit escaped cloud words: {spec['kind']}")

    output_name = f"RainbowFlame_flamer_{spec['kind']}.bundle"
    report = {
        "status": "AUTHORED CLOUD RENAMES; OFFLINE VERIFIED, RUNTIME UNTESTED",
        "kind": spec["kind"],
        "particle_path": spec["path"],
        "source": str(source_path.relative_to(ANALYSIS)).replace("\\", "/"),
        "source_size": len(original),
        "source_sha256": sha256(original),
        "source_particle_sha256": sha256(particle["raw"]),
        "output": output_name,
        "output_size": len(candidate),
        "output_sha256": sha256(candidate),
        "output_particle_sha256": sha256(rebuilt_records[0]["raw"]),
        "cloud_profile_count": len(before_rows),
        "whole_cloud_profile_verified": True,
        "material_candidates_verified": True,
        "selected_billboard_visualizers_are_zero": True,
        "clouds": mappings,
        "unique_old_references_in_logical_bundle": True,
        "unique_new_references_in_logical_bundle": True,
        "authored_id_collisions_absent": True,
        "unchanged_non_particle_records": len(records) - 1,
        "logical_changed_byte_offsets": changed,
        "exact_logical_reverse": True,
    }
    return output_name, candidate, report


def build(check_only=False):
    checks, fmt = load_dependencies()
    profiles = profile_map()
    names = tuple(name for spec in SPECS for name in names_for(spec))
    new_ids = tuple(checks.r.murmur(name) >> 32 for name in names)
    if len(names) != 12 or len(set(names)) != 12 or len(set(new_ids)) != 12:
        raise ValueError("Authored cloud names or IDs are not globally unique")
    retained_cloud_ids = {
        int(cloud["cloud_id32"], 16)
        for profile in profiles.values()
        for cloud in profile["clouds"]
    }
    if retained_cloud_ids.intersection(new_ids):
        raise ValueError("Authored cloud ID collides with a retained cloud profile")
    unpack = decoder()
    artifacts = {}
    reports = []
    for spec in SPECS:
        if spec["path"] not in profiles:
            raise ValueError(f"Missing retained profile: {spec['path']}")
        output_name, candidate, report = author_one(
            spec, profiles[spec["path"]], checks, fmt, unpack, set(new_ids)
        )
        artifacts[output_name] = candidate
        artifacts[output_name.replace(".bundle", ".json")] = (
            json.dumps(report, indent=2) + "\n"
        ).encode()
        reports.append(report)
    manifest = {
        "status": "OFFLINE AUTHORED; NOT DEPLOYED; RUNTIME UNTESTED",
        "source_profile_sha256": PROFILE_SHA256,
        "global_unique_cloud_names": list(names),
        "global_unique_cloud_ids32": [f"{value:08x}" for value in new_ids],
        "outputs": [{"file": row["output"], "sha256": row["output_sha256"],
                     "size": row["output_size"]} for row in reports],
        "checks": {
            "exact_source_hashes": True,
            "whole_cloud_profiles_and_material_candidates": True,
            "selected_visualizers_are_billboards": True,
            "unique_old_reference_occurrence": True,
            "collision_absence": True,
            "unchanged_non_particle_records": True,
            "exact_reverse": True,
        },
    }
    artifacts["manifest.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    sums = {name: {"size": len(data), "sha256": sha256(data)}
            for name, data in sorted(artifacts.items())}
    artifacts["SHA256SUMS.json"] = (json.dumps(sums, indent=2) + "\n").encode()

    if check_only:
        if not AUTHORED.is_dir():
            raise ValueError("Authored output directory is missing")
        for name, data in artifacts.items():
            if (AUTHORED / name).read_bytes() != data:
                raise ValueError(f"Authored artifact differs: {name}")
    else:
        AUTHORED.mkdir(exist_ok=True)
        expected = set(artifacts)
        unexpected = {path.name for path in AUTHORED.iterdir() if path.is_file()} - expected
        if unexpected:
            raise ValueError(f"Unexpected authored artifacts: {sorted(unexpected)}")
        for name, data in artifacts.items():
            path = AUTHORED / name
            if path.exists() and path.read_bytes() != data:
                raise ValueError(f"Refusing different-content overwrite: {name}")
            if not path.exists():
                path.write_bytes(data)
    print(json.dumps(manifest, indent=2))
    return artifacts, manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify existing authored outputs")
    build(parser.parse_args().check)
