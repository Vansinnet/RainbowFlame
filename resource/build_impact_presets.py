"""Build isolated fixed-color flame-staff impact presets offline."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import sys

sys.dont_write_bytecode = True
if not __debug__:
    raise RuntimeError("Run without -O: exact-profile checks are required")

import build
import build_enemy_presets as presets
import enemy_cloud_bundle as enemy_bundle
import export_resources as resources
import shader_tables
import surface_tables

ROOT = build.WORKSPACE
MOD = ROOT / "mods/active/RainbowFlame"
ANALYSIS = MOD / "analysis/impact-color-20260920-a1"
PACKAGE = "97498862fb42b0d6"
PACKAGE_SHA = "7d48b146e33c023586c37e427c3e941063f86801ce8b0047f962f193bd746dad"
SOURCE_PACKAGE = MOD / "analysis/impact-green-candidate-20260920-b2/stock/bundle" / PACKAGE
EFFECT = "content/fx/particles/weapons/flame_staff/psyker_flame_staff_impact_delay"
EFFECT_PREFIX = "content/fx/particles/rainbow_flame/psyker_flame_staff_impact_delay_"
PARTICLE_SHA = "b0a3d2142fe64fc57b0e031d5fab25a6532ab13f789555ebab52419260c6005a"
PARTICLE_BODY_SHA = "0841e940ea0aa3a65dcf2a057efa564928d70a65e3d39616ed78920c2d7b1cba"
PARENT = 0x1CC58F33452CA960
PARENT_SHA = "7e072a559e0c2d77f762c12bde0214521e925d235e2ae17c75ff7605f9a6b35c"
CHILDREN = (0x43ECCF3418D41D30, 0xC69E5A80E9B93DEB, 0x9F9F92EBD789847E)
CHILD_SHA = {
    0x43ECCF3418D41D30: "844a8628c340c4cfc0c8263bab9a97af230832ca20043f5be4d6d40e822c62f0",
    0xC69E5A80E9B93DEB: "45cecdf4f460ce4a3d9f8ed909fe50fd19fb0f1e984f0b9825af857b1a3c35a9",
    0x9F9F92EBD789847E: "66100d4107564ba2f97c75998488480994ef2ffecc76869e8cbec74c07be0561",
}
COLOR_PROGRAMS = (1, 5, 9, 13, 17, 21, 25, 29)
COLOR_PROGRAM_SHA = "f3d69894688705fee1f450d3c5c3c2aba5c54cfbe8b706155f8eb73119827c91"
FEEDBACK_PROGRAMS = (3, 7, 11, 15, 19, 23, 27, 31)
FEEDBACK_PROGRAM_SHA = "466a94037b0cc3a1797b1b62e61570d95aa6f50e7412836d3d28d4c0792bae78"
PRESETS = {
    "red": (0, 1, 1),
    "orange": (30, 1, 1),
    "yellow": (55, 1, 1),
    "green": (120, 1, 1),
    "cyan": (180, 1, 1),
    "blue": (240, 1, 1),
    "violet": (275, 1, 1),
    "pink": (325, 0.72, 1),
}


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def hsv_rgb(hue, saturation, value):
    chroma = value * saturation
    sector = (hue % 360) / 60
    x = chroma * (1 - abs(sector % 2 - 1))
    colors = ((chroma, x, 0), (x, chroma, 0), (0, chroma, x),
              (0, x, chroma), (x, 0, chroma), (chroma, 0, x))
    base = colors[int(sector) % 6]
    match = value - chroma
    return tuple(channel + match for channel in base)


def material_layout(data):
    require(len(data) >= 32, "Short material")
    version, material_offset, material_size, shader_offset, shader_size, tail, tail_size = struct.unpack_from(
        "<7I", data
    )
    require(
        (version, material_offset, shader_offset, tail, tail + tail_size)
        == (61, 28, material_offset + material_size, shader_offset + shader_size, len(data)),
        "Impact parent material layout",
    )
    shader = data[shader_offset:tail]
    header = struct.unpack_from("<12I", shader)
    group_start, group_size, device_start, device_size = header[8:12]
    require(
        header[0] == 43
        and 48 <= group_start < group_start + group_size <= device_start
        and device_start < device_start + device_size <= header[5] <= len(shader),
        "Impact shader layout",
    )
    groups = shader[group_start:group_start + group_size]
    parsed_groups = parse_groups(groups)
    require(serialize_groups(parsed_groups) == groups, "Impact group-table roundtrip")
    resources.default_table(shader[header[5]:])
    return shader, (device_start, device_start + device_size), header[5], shader_offset, tail


def parse_groups(data):
    cursor = shader_tables.Cursor(data)
    count = cursor.words()[0]
    require(count == 8, "Impact shader group count")
    groups = []
    for _ in range(count):
        key, allocation = cursor.words(2)
        group_resources = cursor.table(4)
        buffer_count = cursor.words()[0]
        require(1 <= buffer_count <= 64, "Impact buffer count")
        buffers = []
        for _ in range(buffer_count):
            descriptors = cursor.table(5)
            size, offset = cursor.words(2)
            require(0 < size <= 65536, "Impact buffer size")
            require(all(row[3] + max(1, row[1]) * row[4] <= size for row in descriptors),
                    "Impact descriptor extent")
            buffers.append((descriptors, size, offset))
        associations = cursor.table(7)
        technique_count = cursor.words()[0]
        require(1 <= technique_count <= 64, "Impact technique count")
        techniques = cursor.read(21 * technique_count)
        groups.append((key, allocation, group_resources, buffers, associations, techniques))
    require(cursor.p == len(data), "Impact group-table exhaustion")
    return groups


def serialize_groups(groups):
    data = shader_tables.words([len(groups)])
    for key, allocation, group_resources, buffers, associations, techniques in groups:
        require(len(techniques) % 21 == 0, "Impact technique width")
        data += shader_tables.words([key, allocation]) + shader_tables.table(group_resources)
        data += shader_tables.words([len(buffers)])
        for descriptors, size, offset in buffers:
            data += shader_tables.table(descriptors) + shader_tables.words([size, offset])
        data += shader_tables.table(associations)
        data += shader_tables.words([len(techniques) // 21]) + techniques
    return data


def programs(data, old, parser):
    shader, (start, end), _, _, _ = material_layout(data)
    rows = []
    position = start
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
        require(32 <= decoded_length <= 2_000_000 and len(rows) < 64, "Impact program bound")
        decoded = parser.decompress(frame, decoded_length)
        metadata = surface_tables.metadata(shader, finish)
        rows.append({
            "index": len(rows),
            "begin": begin,
            "end": finish,
            "stop": metadata["span"][1],
            "data": decoded,
            "frame": frame,
            "metadata": shader[finish:metadata["span"][1]],
        })
        position = finish
    require(len(rows) == 32 and rows[-1]["stop"] <= end, "Impact program count")
    return rows


def fixed_module(text, factors, float_ir):
    text = text.replace("\r\n", "\n")
    require("define void @ps_main()" in text, "Impact color stage")
    for field, offset in (
        ("__BINDLESS_SAMPLER_texture_map_6b479ae8", 4),
        ("__BINDLESS_TEX2D_texture_map_6b479ae8", 40),
        ("__BINDLESS_MINLOD_texture_map_6b479ae8", 48),
    ):
        require(re.search(r";\s+uint2? " + field + r";\s*; Offset:\s*" + str(offset) + r"\s*$", text, re.M),
                "Impact ramp reflection field: " + field)
    definitions = {
        key: value.split(";", 1)[0].rstrip()
        for key, value in re.findall(r"^  (%[\w.]+) = (.+)$", text, re.M)
    }

    def ancestors(value):
        pending, seen = [value], set()
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.add(current)
            pending.extend(v for v in re.findall(r"%[\w.]+", definitions.get(current, "")) if v in definitions)
        return seen

    material_handles = [key for key, value in definitions.items() if re.fullmatch(
        r"call %dx.types.Handle @dx.op.createHandle\(i32 57, i8 2, i32 \d+, i32 1, i1 false\)", value
    )]
    require(len(material_handles) == 1, "Impact material cbuffer handle")
    material = material_handles[0]

    def loads(register, component):
        rows = [key for key, value in definitions.items() if value ==
                f"call %dx.types.CBufRet.i32 @dx.op.cbufferLoadLegacy.i32(i32 59, %dx.types.Handle {material}, i32 {register})"]
        return [key for key, value in definitions.items() if any(
            value == f"extractvalue %dx.types.CBufRet.i32 {row}, {component}" for row in rows
        )]

    texture_indices, sampler_indices = loads(2, 2), loads(0, 1)
    require(len(texture_indices) == len(sampler_indices) == 1, "Impact ramp descriptor loads")
    samples = []
    for key, value in definitions.items():
        if "@dx.op.sample" not in value:
            continue
        handles = re.findall(r"%dx.types.Handle (%[\w.]+)", value)
        require(len(handles) == 2, "Impact sample handle count")
        if ancestors(handles[0]).intersection(texture_indices) and ancestors(handles[1]).intersection(sampler_indices):
            samples.append(key)
    require(len(samples) == 1, "Impact ramp sample count")
    rgb = []
    for channel in range(3):
        extracted = [key for key, value in definitions.items()
                     if value == f"extractvalue %dx.types.ResRet.f32 {samples[0]}, {channel}"]
        require(len(extracted) == 1, "Impact ramp RGB extraction")
        rgb.append(extracted[0])
    body = re.search(r"^define void @ps_main\(\) \{\n.*?^\}", text, re.M | re.S)
    if body is None:
        raise ValueError("Impact pixel body")
    lines = body[0].splitlines(keepends=True)
    positions = [i for i, line in enumerate(lines) if any(line.startswith("  " + value + " =") for value in rgb)]
    require(len(positions) == 3, "Impact RGB boundary")
    boundary = max(positions) + 1
    suffix = "".join(lines[boundary:])
    inserted = []
    replacements = []
    for channel, factor in zip("rgb", factors, strict=True):
        if factor == 0:
            replacements.append("0.000000e+00")
        elif factor == 1:
            replacements.append(rgb[1])
        else:
            name = "%impact." + channel
            inserted.append(f"  {name} = fmul float {rgb[1]}, {float_ir(factor)}\n")
            replacements.append(name)
    replacement_by_source = dict(zip(rgb, replacements, strict=True))
    for source in rgb:
        require(len(re.findall(re.escape(source) + r"(?![\w.])", suffix)) == 1,
                "Impact RGB consumer count")
    pattern = "(?:" + "|".join(re.escape(source) for source in rgb) + r")(?![\w.])"
    suffix, count = re.subn(pattern, lambda match: replacement_by_source[match.group()], suffix)
    require(count == 3, "Impact RGB replacement count")
    changed_body = "".join(lines[:boundary]) + "".join(inserted) + suffix
    changed = text[:body.start()] + changed_body + text[body.end():]
    return changed


def merged_module(executable_source, stat_source):
    executable_source = executable_source.replace("\r\n", "\n")
    stat_source = stat_source.replace("\r\n", "\n")
    body = re.search(r"^define void @ps_main\(\) \{\n.*?^\}", executable_source, re.M | re.S)
    if body is None:
        raise ValueError("Impact executable body")
    module = stat_source[stat_source.index("target datalayout"):]
    require(module.count("declare void @ps_main()") == 1, "Impact STAT entry")
    require(module.count("!2 = !{i32 0, i32 0}") == 1, "Impact STAT shader metadata")
    module = module.replace("!2 = !{i32 0, i32 0}", "!2 = !{i32 1, i32 7}")
    counters = re.search(r"^!dx.counters = !\{(!\d+)\}$", module, re.M)
    if counters is None:
        raise ValueError("Impact STAT counters metadata")
    module = re.sub(r"^!dx.counters = .*\n", "", module, flags=re.M)
    module = re.sub(r"^" + re.escape(counters[1]) + r" = .*\n", "", module, flags=re.M)
    refs = sorted(set(re.findall(r"!(\d+)", body[0])), key=int)
    next_id = 1 + max(map(int, re.findall(r"^!(\d+) =", module, re.M)))
    hints = {key: str(next_id + index) for index, key in enumerate(refs)}
    for key, new in hints.items():
        hint = re.search(
            r"^!" + key + r" = distinct !\{!" + key + r', !"dx.controlflow.hints", i32 ([12])\}$',
            executable_source,
            re.M,
        )
        if hint is None:
            raise ValueError("Impact executable metadata")
        module += f'\n!{new} = distinct !{{!{new}, !"dx.controlflow.hints", i32 {hint[1]}}}\n'
    executable = re.sub(r"!(\d+)", lambda match: "!" + hints[match[1]], body[0])
    return module.replace("declare void @ps_main()", executable)


def repack_parent(data, rows, replacements, old, repack):
    shader, (start, end), default, shader_offset, tail = material_layout(data)
    device = bytearray()
    cursor = start
    for row in rows:
        device += shader[cursor:row["begin"] - 8]
        frame, metadata = row["frame"], bytearray(row["metadata"])
        if row["index"] in replacements:
            replacement = replacements[row["index"]]
            frame = repack.stored_frame(replacement)
            struct.pack_into("<IQ", metadata, 4, len(replacement), old.murmur64(frame))
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


def build_parent(rgb):
    path = ANALYSIS / f"parents-stream/hash-only/{PARENT:016x}.material"
    parent = path.read_bytes()
    require(sha(parent) == PARENT_SHA, "Impact parent baseline drift")
    old, shaders, repack, reflection, checks = build.dependencies()
    prepare, parser = old.prior()
    dxc = prepare.Dxc()
    before = programs(parent, old, parser)
    require(all(sha(before[i]["data"]) == COLOR_PROGRAM_SHA for i in COLOR_PROGRAMS),
            "Impact color program identity")
    require(all(sha(before[i]["data"]) == FEEDBACK_PROGRAM_SHA for i in FEEDBACK_PROGRAMS),
            "Impact feedback program identity")
    original = before[COLOR_PROGRAMS[0]]["data"]
    temp = ANALYSIS / "shaders/1cc58f33452ca960/program-01.dxbc"
    require(temp.read_bytes() == original, "Retained impact program identity")
    original_text = reflection.dump(temp).decode()
    parts = lambda value: {row["tag"]: value[row["offset"] + 8:row["offset"] + 8 + row["size"]]
                           for row in parser.dxbc(value)}
    original_parts = parts(original)
    stat_path = ANALYSIS / "shaders/1cc58f33452ca960/program-01.green-STAT.tmp"
    try:
        stat_path.write_bytes(original_parts["STAT"])
        stat_source = reflection.dump(stat_path).decode()
    finally:
        if stat_path.exists():
            stat_path.unlink()
    module = merged_module(fixed_module(original_text, rgb, shaders.float_ir), stat_source)
    assembled, message = dxc.operation(module.encode(), assemble=True)
    require(not message, str(message))
    signed, message = dxc.operation(assembled, assemble=False)
    require(not message and signed[4:20] != bytes(16), "Impact DXC validation: " + str(message))
    validated, message = dxc.operation(signed, assemble=False)
    require(not message and validated == signed, "Impact signed readback")
    replacement = {index: signed for index in COLOR_PROGRAMS}
    require(repack_parent(parent, before, {}, old, repack) == parent, "Impact no-op parent roundtrip")
    candidate = repack_parent(parent, before, replacement, old, repack)
    after = programs(candidate, old, parser)
    for previous, current in zip(before, after, strict=True):
        expected = signed if previous["index"] in COLOR_PROGRAMS else previous["data"]
        require(current["data"] == expected, "Impact program readback")
        require(previous["metadata"][16:] == current["metadata"][16:], "Impact metadata preservation")
        if previous["index"] not in COLOR_PROGRAMS:
            require((previous["frame"], previous["metadata"]) == (current["frame"], current["metadata"]),
                    "Unrelated impact program changed")
    restored = repack_parent(candidate, after, {index: before[index]["data"] for index in COLOR_PROGRAMS}, old, repack)
    restored_programs = programs(restored, old, parser)
    require([row["data"] for row in restored_programs] == [row["data"] for row in before],
            "Impact decoded reverse parent roundtrip")
    parent_shader, _, parent_default, parent_shader_offset, parent_tail = material_layout(parent)
    candidate_shader, _, candidate_default, candidate_shader_offset, candidate_tail = material_layout(candidate)
    require(parent[28:parent_shader_offset] == candidate[28:candidate_shader_offset],
            "Impact material template changed")
    require(resources.default_table(parent_shader[parent_default:])
            == resources.default_table(candidate_shader[candidate_default:]),
            "Impact shader defaults changed")
    require(parent[parent_tail:] == candidate[candidate_tail:], "Impact material tail changed")
    original_descriptors = shader_tables.reflection_descriptors(original_text, old.murmur64)
    check_path = ANALYSIS / "shaders/1cc58f33452ca960/program-01.green.tmp.dxbc"
    try:
        check_path.write_bytes(signed)
        reflected = reflection.dump(check_path).decode()
    finally:
        if check_path.exists():
            check_path.unlink()
    reflected_descriptors = shader_tables.reflection_descriptors(reflected, old.murmur64)
    if reflected_descriptors != original_descriptors:
        summary = {
            name: (len(original_descriptors.get(name, [])), len(reflected_descriptors.get(name, [])))
            for name in sorted(set(original_descriptors) | set(reflected_descriptors))
            if original_descriptors.get(name) != reflected_descriptors.get(name)
        }
        raise ValueError("Impact shader reflection changed: " + json.dumps(summary, sort_keys=True))
    require(build.canonical(module, shaders) == build.canonical(reflected, shaders),
            "Impact executable readback")
    replacement_parts = parts(signed)
    require(all(original_parts[tag] == replacement_parts[tag] for tag in ("SFI0", "ISG1", "OSG1", "PSV0")),
            "Impact shader signature/binding changed")
    stat_path = ANALYSIS / "shaders/1cc58f33452ca960/program-01.green-STAT-readback.tmp"
    try:
        stat_path.write_bytes(replacement_parts["STAT"])
        stat = reflection.dump(stat_path).decode()
    finally:
        if stat_path.exists():
            stat_path.unlink()
    require(checks.count_instructions(reflected) == checks.counters(stat), "Impact STAT counters")
    return candidate, {
        "baseline_sha256": PARENT_SHA,
        "sha256": sha(candidate),
        "size": len(candidate),
        "changed_programs": list(COLOR_PROGRAMS),
        "unchanged_programs": 24,
        "replacement_program_sha256": sha(signed),
        "rgb": rgb,
        "dxc_valid": True,
        "bindings_unchanged": True,
        "no_op_roundtrip": True,
        "decoded_reverse_roundtrip": True,
        "exact_reverse_roundtrip": False,
    }


def run(output):
    output = output.resolve()
    require(output.parent.is_dir() and not output.exists() and output.is_relative_to(MOD / "analysis"),
            "Output must be a fresh analysis child")
    source = SOURCE_PACKAGE.read_bytes()
    require(sha(source) == PACKAGE_SHA, "Impact package baseline drift")
    container = enemy_bundle.fmt.read(source, enemy_bundle.baseline.decoder())
    stock_records = enemy_bundle.fmt.records(container)
    require(len(stock_records) == 30, "Impact stock record count")
    murmur = enemy_bundle.baseline.assets.index.murmur
    particle_type, material_type = murmur("particles"), murmur("material")
    original_identity = (particle_type, murmur(EFFECT), 0)
    particle_record, = [row for row in stock_records if row["identity"] == original_identity]
    require(sha(particle_record["raw"]) == PARTICLE_SHA, "Impact particle record baseline")
    require(len(particle_record["bodies"]) == 1, "Impact particle variants")
    _, particle, tail = particle_record["bodies"][0]
    require(not tail and sha(particle) == PARTICLE_BODY_SHA, "Impact particle body baseline")
    output.mkdir()
    stock_folder = output / "stock/bundle"
    stock_folder.mkdir(parents=True)
    (stock_folder / PACKAGE).write_bytes(source)
    stream_folder = output / "bundle/data/rf"
    stream_folder.mkdir(parents=True)
    index = list(container.index)
    appended = bytearray()
    generated = set()
    manifest_presets = {}
    all_streams = {}
    for preset, hsv in PRESETS.items():
        effect = EFFECT_PREFIX + preset
        effect_hash = murmur(effect)
        parent_hash = murmur(effect + "_parent")
        child_hashes = [murmur(effect + f"_material_{index}") for index in range(1, 4)]
        identities = {effect_hash, parent_hash, *child_hashes}
        require(len(identities) == 5 and not identities.intersection(generated)
                and not identities.intersection(name for _, name, _ in container.index),
                "Impact candidate identity collision")
        generated.update(identities)
        rgb = hsv_rgb(*hsv)
        parent, parent_report = build_parent(rgb)
        child_streams = []
        for original_hash, child_hash in zip(CHILDREN, child_hashes, strict=True):
            child = (ANALYSIS / f"materials-stream/hash-only/{original_hash:016x}.material").read_bytes()
            require(sha(child) == CHILD_SHA[original_hash], "Impact child baseline drift")
            old_parent = struct.pack("<Q", PARENT)
            require(child.count(old_parent) == 1, "Impact child parent reference")
            child_streams.append(child.replace(old_parent, struct.pack("<Q", parent_hash)))
        new_particle = particle
        for original_hash, child_hash in zip(CHILDREN, child_hashes, strict=True):
            old_child = struct.pack("<Q", original_hash)
            require(new_particle.count(old_child) == 1, "Impact particle child reference")
            new_particle = new_particle.replace(old_child, struct.pack("<Q", child_hash))
        stream_values = [(parent_hash, parent), *zip(child_hashes, child_streams, strict=True)]
        for identity, value in stream_values:
            (stream_folder / f"{identity:016x}").write_bytes(value)
            all_streams[identity] = value
            resource_identity = (material_type, identity, 4)
            index.append(resource_identity)
            pointer = presets.stream_pointer(f"data/rf/{identity:016x}")
            appended += presets.resource_record(resource_identity, pointer, True)
        particle_identity = (particle_type, effect_hash, 0)
        index.append(particle_identity)
        appended += presets.resource_record(particle_identity, new_particle, False)
        manifest_presets[preset] = {
            "effect": effect,
            "effect_hash": f"{effect_hash:016x}",
            "parent_hash": f"{parent_hash:016x}",
            "child_hashes": [f"{value:016x}" for value in child_hashes],
            "particle_sha256": sha(new_particle),
            "parent": parent_report,
        }
    candidate = presets.serialize_expanded(container, index, container.logical + appended)
    reread = presets.read_expanded(candidate, len(index))
    after = enemy_bundle.fmt.records(reread)
    require(len(after) == len(stock_records) + 5 * len(PRESETS), "Impact candidate record count")
    require(all(a["raw"] == b["raw"] for a, b in zip(stock_records, after)),
            "Impact stock record changed")
    require(len({row["identity"] for row in after}) == len(after), "Impact candidate duplicate records")
    bundle_path = output / "bundle" / PACKAGE
    bundle_path.write_bytes(candidate)
    manifest = {
        "status": "OFFLINE IMPACT PRESETS; GREEN TESTED IN GAME; OTHER COLORS UNTESTED",
        "source_bundle_sha256": PACKAGE_SHA,
        "stock_bundle": {"path": f"stock/bundle/{PACKAGE}", "size": len(source), "sha256": sha(source)},
        "bundle": {"path": f"bundle/{PACKAGE}", "size": len(candidate), "sha256": sha(candidate)},
        "presets": manifest_presets,
        "streams": {f"bundle/data/rf/{identity:016x}": {"size": len(value), "sha256": sha(value)}
                    for identity, value in all_streams.items()},
        "preserved_stock_records": len(stock_records),
        "added_records": 5 * len(PRESETS),
        "color_transform": "sampled RGB -> fixed preset RGB scaled by sampled G; downstream shaping and alpha unchanged",
        "installed_writes": 0,
        "runtime_observed": False,
    }
    (output / "candidate.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="ascii")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--output", type=Path, required=True)
    run(cli.parse_args().output)
