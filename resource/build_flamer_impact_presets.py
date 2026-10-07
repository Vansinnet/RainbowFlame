"""Author fixed-color Zealot flamer impact presets from retained offline inputs."""
import copy
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
import tempfile

sys.dont_write_bytecode = True
if not __debug__:
    raise RuntimeError("Run without -O: exact-profile checks are required")

import build
import build_enemy_presets as bundles
import build_flamer_streams as streams
import build_impact_presets as staff
import enemy_cloud_bundle
import export_resources as resources
import flamer_stream_materials as materials
import shader_tables
import surface_tables

ROOT = Path(__file__).resolve().parents[4]
ANALYSIS = ROOT / "mods/active/RainbowFlame/analysis/flamer-streams-20260922-a1"
OUTPUT = ANALYSIS / "authored-impact"
PACKAGE = "3d487cca8bd5c544"
EFFECT = "content/fx/particles/weapons/rifles/zealot_flamer/zealot_flamer_impact_delay"
EFFECT_PREFIX = "content/fx/particles/rainbow_flame/zealot_flamer_impact_delay_"
PACKAGE_SHA256 = "c04e6a56e333d5bd3e437e36b45bf39cb1588db5504776319f9f53d936195afa"
PARTICLE_PROFILE_SHA256 = "8ab02e61ebe7d03f60a66712a4af39ff846db8571a3c95bac62353def4218423"
MATERIAL_PROFILE_SHA256 = "1dce4188b64c62b323522e6b2f5b64cd9d3919106cc935d7d0cbce63f8097d34"
PARTICLE_SHA256 = "1b4c6aba2a0c5fdc6a8a140e16e5be067e139114f5e512f158a7270465858974"
PARENT_1CC = 0x1CC58F33452CA960
PARENT_BE93 = 0xBE9333164C3DDF4A
COLOR_PROGRAMS_1CC = tuple(range(1, 32, 4))
COLOR_PROGRAMS_BE93 = tuple(range(1, 48, 4))
CHILDREN = (
    (0xC16522C1AAE825FA, PARENT_BE93, "data/a3/a32a282ef1b4e77b",
     "da12c502b3737aa210f10bcbceafcf17096379479349ab7a86155b0ded41dc6b"),
    (0xAED1F9F8AB43A5D3, PARENT_1CC, "data/de/de4a56acd3482018",
     "f85babd35c5e15ea0cebf1377040c12a0ab6f74be6c9932ed905299d35e2d415"),
    (0xD048CF6EBB1FA2BC, PARENT_1CC, "data/5a/5a4670ce8ebfe921",
     "f7d31d7f15cd85182a99a59971d62f4d9ea08936eb5241279ddf76eca5f8f41e"),
    (0x0E506B3AA5D52550, PARENT_1CC, "data/c4/c4581b0eb9ea8afe",
     "f4db128ca1df5f6d9bee08ddf68df3718f0c41433cea54e0e901a6431b791c60"),
)
PRESETS = staff.PRESETS
HASHES = {
    "red": ("b6ec3e126391a698", "eb3466d3e9254483", "ab0a2048460bda30", "9780461578926a65", "a63943a548360c80", "1bac7784b2d6a42d", "47e037d0e9d29c97"),
    "orange": ("a3c44b67e472ba16", "ecda941b65e3b127", "f7d2e2511f7830d4", "e9b08abc87732ced", "ebd4df0905e83eb7", "e66a749a4b152b64", "bd23bb5243c879a5"),
    "yellow": ("b86927de9538e5b8", "f11528855550f7d7", "e98a6defd14592fe", "455eebea11aade09", "161f13b53a58998c", "44ab39c869e4b926", "aa5dcd0dcfc465d5"),
    "green": ("a65ecd179bec6bdf", "2d4cbaf1c071c2ca", "8b16081af97bc9de", "24a473e7cef8c0b7", "33352077231102e8", "8cc9e24685aef722", "93162410127e7673"),
    "cyan": ("7300eb431d0163c6", "40ddf93b12a52345", "9f422c69ec74260a", "52f0039939325c15", "3884eec1f37ec4e0", "1166532e4b4ebd61", "fee30113f616baca"),
    "blue": ("947bf8e489542692", "df78bc0ef210d0a3", "6338736211354a0f", "75fb81db042f7816", "b17dfcd3b05cc3c6", "f40c2f2ed3900851", "93c141b5c4f0fb98"),
    "violet": ("6dcce67ba4a1aeff", "a6677a03706bbee6", "4d454784c44de1b9", "bb1a173c59fd2541", "aa49f5250061708c", "047b6a47693c072f", "df510820732c27d1"),
    "pink": ("89a2d50be45546d6", "343f889c0539706b", "10a4378f7af61950", "fbd8a35468b7a35e", "b502ad2b4b531916", "70fe96951c489f7a", "725ae6ea4e13f523"),
}


def require(value, message):
    if not value:
        raise ValueError(message)


def identity(data):
    return {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def material_layout(data):
    require(len(data) >= 32, "Short parent material")
    version, material_offset, material_size, shader_offset, shader_size, other, other_size = struct.unpack_from(
        "<7I", data
    )
    require((version, material_offset, shader_offset, other, other + other_size) ==
            (61, 28, material_offset + material_size, shader_offset + shader_size, len(data)),
            "Parent material61 layout")
    shader = data[shader_offset:other]
    header = struct.unpack_from("<12I", shader)
    device_start, device_size = header[10:12]
    require(header[0] == 43 and device_start < device_start + device_size <= header[5] <= len(shader),
            "Parent shader43 layout")
    resources.default_table(shader[header[5]:])
    return shader, device_start, device_start + device_size, header[5], shader_offset, other


def scan_programs(data, old, parser, expected):
    shader, start, end, _, _, _ = material_layout(data)
    rows, position = [], start
    while True:
        begin = shader.find(b"\x8c\x06", position, end)
        if begin < 0:
            break
        position = begin + 2
        if begin < start + 8 or begin + 5 > end:
            continue
        envelope, encoded_length = struct.unpack_from("<II", shader, begin - 8)
        finish = begin + encoded_length
        if envelope != 1 or not begin + 8 <= finish <= end - 16:
            continue
        frame = shader[begin:finish]
        if int.from_bytes(frame[2:5], "big") + 1 != len(frame) - 5:
            continue
        kind, decoded_length, key = struct.unpack_from("<IIQ", shader, finish)
        if kind != 5 or old.murmur64(frame) != key:
            continue
        require(32 <= decoded_length <= 2_000_000, "Parent decoded program bound")
        metadata = surface_tables.metadata(shader, finish)
        rows.append({"index": len(rows), "begin": begin, "end": finish,
                     "stop": metadata["span"][1], "data": parser.decompress(frame, decoded_length),
                     "frame": frame, "metadata": shader[finish:metadata["span"][1]]})
        position = finish
    require(len(rows) == expected and rows[-1]["stop"] <= end, "Exact parent program count")
    return rows


def repack_parent(data, rows, replacements, old, repack, encoded=False):
    shader, start, end, default, shader_offset, tail = material_layout(data)
    device, cursor = bytearray(), start
    for row in rows:
        device += shader[cursor:row["begin"] - 8]
        frame, metadata = row["frame"], row["metadata"]
        if row["index"] in replacements:
            if encoded:
                frame, metadata = replacements[row["index"]]
            else:
                decoded = replacements[row["index"]]
                frame, metadata = repack.stored_frame(decoded), bytearray(metadata)
                struct.pack_into("<IQ", metadata, 4, len(decoded), old.murmur64(frame))
                metadata = bytes(metadata)
        device += struct.pack("<II", 1, len(frame)) + frame + metadata
        cursor = row["stop"]
    device += shader[cursor:end]
    prefix = bytearray(shader[:start])
    new_default = (start + len(device) + 3) & ~3
    struct.pack_into("<I", prefix, 20, new_default)
    struct.pack_into("<I", prefix, 44, len(device))
    new_shader = bytes(prefix) + device + bytes(new_default - start - len(device))
    new_shader += resources.serialize_defaults(resources.default_table(shader[default:]))
    new_shader += bytes((-len(new_shader)) % 16)
    header = bytearray(data[:28])
    struct.pack_into("<II", header, 16, len(new_shader), shader_offset + len(new_shader))
    return bytes(header) + data[28:shader_offset] + new_shader + data[tail:]


def fixed_be93_module(text, rgb, float_ir):
    spec = materials.SPECS[f"{PARENT_BE93:016x}"]
    path = materials.color_path(f"{PARENT_BE93:016x}", text)
    require(tuple(path["rgb"]) == spec["rgb"] and tuple(spec["targets"]) == COLOR_PROGRAMS_BE93,
            "Exact be93 reflected color path")
    body = text.replace("\r\n", "\n")
    insertions, changed = [], body
    replacement_lines = []
    for channel, factor, source, consumer in zip("rgb", rgb, spec["rgb"], spec["consumers"], strict=True):
        if factor == 0:
            value = "0.000000e+00"
        elif factor == 1:
            value = spec["rgb"][1]
        else:
            value = "%impact." + channel
            insertions.append(f"  {value} = fmul float {spec['rgb'][1]}, {float_ir(factor)}\n")
        replacement, substitutions = re.subn(re.escape(source) + r"(?![\w.])", value, consumer)
        require(substitutions == 1 and changed.count("  " + consumer) == 1, "Exact be93 RGB consumer")
        changed = changed.replace("  " + consumer, "  " + replacement)
        replacement_lines.append((consumer, replacement))
    anchor = "  " + spec["consumers"][0]
    require(changed.count("  " + replacement_lines[0][1]) == 1, "be93 insertion anchor")
    changed = changed.replace("  " + replacement_lines[0][1], "".join(insertions) + "  " + replacement_lines[0][1])
    reverse = changed.replace("".join(insertions), "")
    for original, replacement in replacement_lines:
        reverse = reverse.replace("  " + replacement, "  " + original)
    require(reverse == body, "Exact be93 executable reverse")
    return changed


def dxbc_chunks(data, parser):
    return {row["tag"]: data[row["offset"] + 8:row["offset"] + 8 + row["size"]]
            for row in parser.dxbc(data)}


def build_be93(rgb, temp, dependencies):
    old, shaders, repack, reflection, checks, parser, dxc = dependencies
    name = f"{PARENT_BE93:016x}"
    original = materials.source(name)
    shader = materials.inspect_parent(name, original)
    manifest = {row["material"]: row for row in json.loads((materials.REFLECTION / "manifest.json").read_text())}
    program_profile = manifest[name]["programs"]
    before = scan_programs(original, old, parser, 48)
    require([list((row["begin"], row["end"])) for row in before] ==
            [row["frame"] for row in program_profile], "Pinned be93 program layout")
    replacements, program_reports = {}, []
    for index, (profile, row) in enumerate(zip(program_profile, before, strict=True)):
        base = materials.REFLECTION / name / f"program-{index:02d}"
        dxbc = base.with_suffix(".dxbc").read_bytes()
        text = base.with_suffix(".ll.txt").read_text().replace("\r\n", "\n")
        require(identity(dxbc)["sha256"] == profile["sha256"] and dxbc == row["data"],
                "Pinned be93 reflected program")
        validated, message = dxc.operation(dxbc, assemble=False)
        require(not message and validated == dxbc and dxbc[4:20] != bytes(16), "Stock be93 DXIL validation")
        require(reflection.dump(base.with_suffix(".dxbc")).decode().replace("\r\n", "\n") == text,
                "Stock be93 reflection readback")
        report = {"index": index, "stock": identity(dxbc), "stock_dxil_valid": True,
                  "stock_reflection_readback": True, "changed": index in COLOR_PROGRAMS_BE93}
        if index in COLOR_PROGRAMS_BE93:
            parts = dxbc_chunks(dxbc, parser)
            stat_path = temp / f"be93-{index:02d}-STAT.program"
            stat_path.write_bytes(parts["STAT"])
            stat = reflection.dump(stat_path).decode()
            module = staff.merged_module(fixed_be93_module(text, rgb, shaders.float_ir), stat)
            assembled, message = dxc.operation(module.encode(), assemble=True)
            require(not message, "be93 DXIL assembly: " + str(message))
            signed, message = dxc.operation(assembled, assemble=False)
            require(not message and signed[4:20] != bytes(16), "be93 signed DXIL validation: " + str(message))
            signed_path = temp / f"be93-{index:02d}.dxbc"
            signed_path.write_bytes(signed)
            reflected = reflection.dump(signed_path).decode().replace("\r\n", "\n")
            require(build.canonical(module, shaders) == build.canonical(reflected, shaders),
                    "be93 executable readback")
            new_parts = dxbc_chunks(signed, parser)
            require(all(parts[tag] == new_parts[tag] for tag in ("SFI0", "ISG1", "OSG1", "PSV0")),
                    "be93 signature/binding preservation")
            stat_path.write_bytes(new_parts["STAT"])
            new_stat = reflection.dump(stat_path).decode()
            require(checks.count_instructions(reflected) == checks.counters(new_stat), "be93 STAT counters")
            replacements[index] = signed
            report.update({"authored": identity(signed), "authored_dxil_valid": True,
                           "canonical_executable": True, "stat_counters": True,
                           "exact_executable_reverse": True})
        program_reports.append(report)
    require(tuple(replacements) == COLOR_PROGRAMS_BE93, "Exact be93 replacement range")
    require(repack_parent(original, before, {}, old, repack) == original, "be93 no-op parent roundtrip")
    candidate = repack_parent(original, before, replacements, old, repack)
    after = scan_programs(candidate, old, parser, 48)
    for previous, current in zip(before, after, strict=True):
        require(current["data"] == replacements.get(previous["index"], previous["data"]),
                "be93 program readback")
        if previous["index"] not in replacements:
            require((current["frame"], current["metadata"]) == (previous["frame"], previous["metadata"]),
                    "be93 non-color program changed")
        require(current["metadata"][16:] == previous["metadata"][16:], "be93 metadata changed")
    reverse_frames = {index: (before[index]["frame"], before[index]["metadata"])
                      for index in COLOR_PROGRAMS_BE93}
    restored = repack_parent(candidate, after, reverse_frames, old, repack, encoded=True)
    require(restored == original, "Byte-exact be93 parent reverse")
    old_shader, _, _, old_default, old_offset, old_tail = material_layout(original)
    new_shader, _, _, new_default, new_offset, new_tail = material_layout(candidate)
    require(original[28:old_offset] == candidate[28:new_offset] and
            resources.default_table(old_shader[old_default:]) == resources.default_table(new_shader[new_default:]) and
            original[old_tail:] == candidate[new_tail:], "be93 non-program parent sections changed")
    return candidate, {"source": identity(original), "material": identity(candidate),
                       "targets": list(COLOR_PROGRAMS_BE93), "programs": program_reports,
                       "all_stock_dxil_valid": True, "all_authored_dxil_valid": True,
                       "unchanged_programs": 36, "byte_exact_parent_reverse": True,
                       "non_program_sections_unchanged": True}


def build_1cc(rgb, dependencies):
    old, _, repack, _, _, parser, dxc = dependencies
    original_path = staff.ANALYSIS / f"parents-stream/hash-only/{PARENT_1CC:016x}.material"
    original = original_path.read_bytes()
    require(identity(original)["sha256"] == staff.PARENT_SHA, "Pinned 1cc parent identity")
    before = scan_programs(original, old, parser, 32)
    for row in before:
        validated, message = dxc.operation(row["data"], assemble=False)
        require(not message and validated == row["data"] and row["data"][4:20] != bytes(16),
                "Stock 1cc DXIL validation")
    candidate, report = staff.build_parent(rgb)
    after = scan_programs(candidate, old, parser, 32)
    require(report["changed_programs"] == list(COLOR_PROGRAMS_1CC) and report["dxc_valid"],
            "Existing fixed-color 1cc result")
    reverse_frames = {index: (before[index]["frame"], before[index]["metadata"])
                      for index in COLOR_PROGRAMS_1CC}
    restored = repack_parent(candidate, after, reverse_frames, old, repack, encoded=True)
    require(restored == original, "Byte-exact 1cc parent reverse")
    report = copy.deepcopy(report)
    report.update({"source": identity(original), "material": identity(candidate),
                   "byte_exact_parent_reverse": True, "reused_staff_fixed_color_authoring": True,
                   "all_authored_dxil_valid": True})
    return candidate, report


def retained_profiles():
    particle_raw = (ANALYSIS / "particle-profiles.json").read_bytes()
    material_raw = (ANALYSIS / "material-profiles.json").read_bytes()
    require(identity(particle_raw)["sha256"] == PARTICLE_PROFILE_SHA256, "Pinned particle profiles")
    require(identity(material_raw)["sha256"] == MATERIAL_PROFILE_SHA256, "Pinned material profiles")
    particle_rows = {row["path"]: row for row in json.loads(particle_raw)["profiles"]}
    material_rows = {int(row["material"], 16): row for row in json.loads(material_raw)["materials"]}
    profile = particle_rows[EFFECT]
    require(profile["bundle"] == PACKAGE and profile["bundle_sha256"] == PACKAGE_SHA256 and
            profile["particle_sha256"] == PARTICLE_SHA256 and profile["cloud_count"] == 8,
            "Pinned Zealot impact profile")
    require(tuple(int(row["material_candidate"], 16) for row in profile["clouds"][:4]) ==
            tuple(row[0] for row in CHILDREN), "Pinned impact color-bearing records")
    require([row["index"] for row in profile["clouds"]] == list(range(8)), "Pinned impact record layout")
    for child, parent, stream, digest in CHILDREN:
        row = material_rows[child]
        require(row["stream"] == stream and row["stream_sha256"] == digest and
                int(row["parsed"]["parent_hashes"][0], 16) == parent,
                "Pinned impact child graph")
    return profile


def build_artifacts():
    profile = retained_profiles()
    source = (ANALYSIS / "stock/bundle" / PACKAGE).read_bytes()
    require(identity(source)["sha256"] == PACKAGE_SHA256, "Pinned impact bundle")
    checks, fmt = streams.load_dependencies()
    container = fmt.read(source, streams.decoder())
    stock_records = fmt.records(container)
    require(len(stock_records) == 43, "Pinned stock resource count")
    murmur = enemy_cloud_bundle.baseline.assets.index.murmur
    particle_type, material_type = murmur("particles"), murmur("material")
    particle_record, = [row for row in stock_records if row["identity"] == (particle_type, murmur(EFFECT), 0)]
    require(identity(particle_record["raw"])["sha256"] == PARTICLE_SHA256 and
            len(particle_record["bodies"]) == 1, "Pinned stock particle")
    body_start, particle, tail = particle_record["bodies"][0]
    require(body_start == 38 and not tail, "Pinned particle wrapper")
    clouds = checks.prefixes(particle)
    require(clouds == profile["clouds"], "Retained whole impact cloud profile")
    child_sources = {}
    for child, parent, stream, digest in CHILDREN:
        data = (ANALYSIS / "stock/bundle" / stream).read_bytes()
        require(identity(data)["sha256"] == digest and data.count(struct.pack("<Q", parent)) == 1,
                "Pinned child stream and parent reference")
        child_sources[child] = data

    old, shaders, repack, reflection, validation = build.dependencies()
    _, parser = old.prior()
    prepare, parser = old.prior()
    dependencies = (old, shaders, repack, reflection, validation, parser, prepare.Dxc())
    artifacts, index, appended = {}, list(container.index), bytearray()
    generated, preset_reports = set(), {}
    with tempfile.TemporaryDirectory() as temporary:
        temp = Path(temporary)
        for preset, hsv in PRESETS.items():
            effect = EFFECT_PREFIX + preset
            names = (effect, effect + "_parent_be93", effect + "_parent_1cc",
                     *(effect + f"_material_{number}" for number in range(1, 5)))
            actual_hashes = tuple(murmur(name) for name in names)
            expected_hashes = tuple(int(value, 16) for value in HASHES[preset])
            require(actual_hashes == expected_hashes, "Pinned custom Murmur identities: " + preset)
            require(len(set(actual_hashes)) == 7 and not set(actual_hashes).intersection(generated) and
                    not set(actual_hashes).intersection(name for _, name, _ in container.index),
                    "Custom resource identity collision")
            generated.update(actual_hashes)
            particle_hash, be93_hash, onecc_hash, *child_hashes = actual_hashes
            rgb = staff.hsv_rgb(*hsv)
            be93, be93_report = build_be93(rgb, temp, dependencies)
            onecc, onecc_report = build_1cc(rgb, dependencies)
            material_values = [(be93_hash, be93), (onecc_hash, onecc)]
            changed_particle = particle
            child_reports = []
            for (stock_child, stock_parent, _, _), custom_child in zip(CHILDREN, child_hashes, strict=True):
                custom_parent = be93_hash if stock_parent == PARENT_BE93 else onecc_hash
                source_child = child_sources[stock_child]
                child = source_child.replace(struct.pack("<Q", stock_parent), struct.pack("<Q", custom_parent))
                require(child.count(struct.pack("<Q", custom_parent)) == 1, "Custom child parent rewrite")
                restored = child.replace(struct.pack("<Q", custom_parent), struct.pack("<Q", stock_parent))
                require(restored == source_child, "Exact child graph reverse")
                material_values.append((custom_child, child))
                old_reference = struct.pack("<Q", stock_child)
                require(changed_particle.count(old_reference) == 1, "Unique particle child reference")
                changed_particle = changed_particle.replace(old_reference, struct.pack("<Q", custom_child))
                child_reports.append({"stock_child": f"{stock_child:016x}",
                                      "stock_parent": f"{stock_parent:016x}",
                                      "custom_child": f"{custom_child:016x}",
                                      "custom_parent": f"{custom_parent:016x}",
                                      "stream": identity(child), "exact_reverse": True})
            changed_clouds = checks.prefixes(changed_particle)
            require(changed_clouds[4:] == clouds[4:], "Stock impact records 4-7 changed")
            require([row["material_candidate"] for row in changed_clouds[:4]] ==
                    [f"{value:016x}" for value in child_hashes], "Impact records 0-3 graph rewrite")
            reverse_particle = changed_particle
            for (stock_child, _, _, _), custom_child in zip(CHILDREN, child_hashes, strict=True):
                reverse_particle = reverse_particle.replace(struct.pack("<Q", custom_child), struct.pack("<Q", stock_child))
            require(reverse_particle == particle, "Exact particle graph reverse")
            for material_hash, value in material_values:
                path = f"bundle/data/rf/{material_hash:016x}"
                artifacts[path] = value
                resource_identity = (material_type, material_hash, 4)
                index.append(resource_identity)
                appended += bundles.resource_record(resource_identity,
                                                      bundles.stream_pointer(f"data/rf/{material_hash:016x}"), True)
            particle_identity = (particle_type, particle_hash, 0)
            index.append(particle_identity)
            appended += bundles.resource_record(particle_identity, changed_particle, False)
            preset_reports[preset] = {"effect": effect, "rgb": rgb,
                                      "hashes": dict(zip(("particle", "parent_be93", "parent_1cc",
                                                          "child_1", "child_2", "child_3", "child_4"),
                                                         HASHES[preset], strict=True)),
                                      "particle": identity(changed_particle), "children": child_reports,
                                      "parent_be93": be93_report, "parent_1cc": onecc_report}
    require(len(generated) == 56 and len(index) == 99, "Exact authored identity and resource counts")
    candidate = bundles.serialize_expanded(container, index, container.logical + appended)
    reread = bundles.read_expanded(candidate, 99)
    after = fmt.records(reread)
    require(len(after) == 99 and len({row["identity"] for row in after}) == 99, "Candidate resource index")
    require(all(left["raw"] == right["raw"] for left, right in zip(stock_records, after[:43], strict=True)),
            "Stock bundle records changed")
    require([row["identity"] for row in after[43:]] == index[43:], "Authored record order")
    artifacts[f"bundle/{PACKAGE}"] = candidate
    report = {
        "status": "OFFLINE AUTHORED; NOT DEPLOYED; RUNTIME UNTESTED",
        "effect_prefix": EFFECT_PREFIX,
        "source_bundle": identity(source),
        "candidate_bundle": identity(candidate),
        "stock_records": 43,
        "added_records": 56,
        "candidate_records": 99,
        "particle_identities": [EFFECT_PREFIX + preset for preset in PRESETS],
        "presets": preset_reports,
        "checks": {"profile_hashes_pinned": True, "layouts_pinned": True,
                   "unique_murmur_identities": True, "records_0_3_rewritten": True,
                   "records_4_7_stock": True, "all_stock_records_unchanged": True,
                   "all_dxil_valid": True, "parent_transformations_exactly_reversible": True,
                   "children_and_particles_exactly_reversible": True},
        "limitations": ["No Lua, payload, installed files, deployment, native loading, or in-game behavior was changed or tested."],
    }
    artifacts["report.json"] = (json.dumps(report, indent=2) + "\n").encode("ascii")
    manifest = {name: identity(data) for name, data in sorted(artifacts.items())}
    artifacts["manifest.json"] = (json.dumps({"artifacts": manifest, "record_count": 99,
                                               "stream_count": 48, "preset_count": 8}, indent=2) + "\n").encode("ascii")
    return artifacts, report


def run(check_only=False):
    artifacts, report = build_artifacts()
    if check_only:
        require(OUTPUT.is_dir(), "Authored impact output is missing")
        actual = {str(path.relative_to(OUTPUT)).replace("\\", "/")
                  for path in OUTPUT.rglob("*") if path.is_file()}
        require(actual == set(artifacts), "Authored impact artifact set changed")
        for name, data in artifacts.items():
            require((OUTPUT / name).read_bytes() == data, "Deterministic artifact differs: " + name)
    else:
        require(not OUTPUT.exists(), "Fresh authored-impact directory required")
        for name, data in artifacts.items():
            path = OUTPUT / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            require(path.read_bytes() == data, "Authored artifact readback: " + name)
    print(json.dumps({"output": str(OUTPUT), "bundle": report["candidate_bundle"],
                      "records": report["candidate_records"], "check_only": check_only}, indent=2))
    return artifacts, report


if __name__ == "__main__":
    import argparse
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--check", action="store_true", help="rebuild and compare all authored artifacts")
    run(cli.parse_args().check)
