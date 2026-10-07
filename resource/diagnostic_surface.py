"""Offline-only forced-magenta surface diagnostic. NOT a production color mode.

Reuses the sealed e1 executable and changes exactly its three final chroma
assignments. Never reads installed files; output must be a new docs directory.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

import build
import export_resources as er
import shader_tables
import surface_shader
import surface_tables

ROOT = build.WORKSPACE
B1 = ROOT / "mods/active/RainbowFlame/analysis/enemy-follow-20260919-b1"
E1 = ROOT / "docs/analysis-rainbow-live-controls-20260919-e1"
G1 = ROOT / "docs/analysis-rainbow-enemy-sync-20260919-g1"
SELECTED = (1, 10, 19, 23)
PARENT_HASH = "3abeecaa0e2602feaa99179c3b2a05049bd5eed5f1c31b5a92f02929324e60b8"
FILENAME = "4ab784b71d6e9eb6.DIAGNOSTIC-MAGENTA.material"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def sealed(folder, name):
    seal = (folder / "SHA256SUMS.json").read_bytes()
    if folder == E1 and sha(seal) != "571e137362e4f1a159b2cdb034d39842731e1a4a27915a80803a239a40f0bec2":
        raise ValueError("e1 seal identity")
    rows = json.loads(seal)
    rows = rows.get("artifacts", rows)
    rows = {key.replace("\\", "/"): value for key, value in rows.items()}
    data = (folder / name).read_bytes()
    if sha(data) != rows[name]["sha256"] or len(data) != rows[name]["size"]:
        raise ValueError("Sealed input drift: " + name)
    return data


def magenta_module(text):
    # hc.value is max(stock ramp RGB), before the UI brightness multiplication.
    changed = text
    for channel, factor in (("r", "1.000000e+00"), ("g", "0.000000e+00"), ("b", "1.000000e+00")):
        pattern = rf"^  %rf\.{channel} = select i1 %rf.active, float %rf\.{channel}.mixed, float %\d+$"
        changed, count = re.subn(pattern, f"  %rf.{channel} = fmul float %hc.value, {factor}", changed, flags=re.M)
        if count != 1:
            raise ValueError("Unexpected final ramp consumer: " + channel)
    if len([1 for a, b in zip(text.splitlines(), changed.splitlines()) if a != b]) != 3:
        raise ValueError("Nonminimal executable change")
    return changed


def layout(data):
    if len(data) < 28:
        raise ValueError("Short material")
    v, mo, ms, so, ss, tail, ts = struct.unpack_from("<7I", data)
    if (v, mo, so, tail, ts, tail + ts) != (61, 28, mo + ms, so + ss, 14437, len(data)):
        raise ValueError("Not the retained packed parent profile")
    shader = data[so:tail]
    if struct.unpack_from("<I", shader)[0] != 43:
        raise ValueError("Shader version")
    start, size, ds, length = struct.unpack_from("<4I", shader, 32)
    default = struct.unpack_from("<I", shader, 20)[0]
    if not 48 <= start < start + size <= ds < ds + length <= default <= len(shader):
        raise ValueError("Shader bounds")
    template = data[mo:so]
    if er.serialize_material(er.material_template(template)) != template:
        raise ValueError("Material roundtrip")
    groups = shader[start:start + size]
    if surface_tables.serialize(surface_tables.parse(groups)) != groups:
        raise ValueError("Group roundtrip")
    er.default_table(shader[default:])
    return shader, (ds, ds + length), default, so, tail


def walk(data, original_shader, original_report, old, parser):
    shader, (start, end), _, _, _ = layout(data)
    old_cursor = struct.unpack_from("<I", original_shader, 40)[0]
    cursor = start
    rows = []
    for i, original in enumerate(original_report["programs"]):
        begin, finish = original["frame"]
        gap = original_shader[old_cursor:begin - 8]
        if shader[cursor:cursor + len(gap)] != gap:
            raise ValueError("Opaque program gap changed")
        cursor += len(gap)
        kind, length = struct.unpack_from("<II", shader, cursor)
        begin_new, end_new = cursor + 8, cursor + 8 + length
        if kind != 1 or not begin_new < end_new < end:
            raise ValueError("Frame bounds")
        meta = surface_tables.metadata(shader[:end], end_new)
        frame = shader[begin_new:end_new]
        if old.murmur64(frame) != struct.unpack_from("<Q", shader, end_new + 8)[0]:
            raise ValueError("Frame hash")
        decoded = parser.decompress(frame, meta["header"][1])
        rows.append(dict(index=i, begin=begin_new, end=end_new, stop=meta["span"][1],
                         data=decoded, frame=frame, metadata=shader[end_new:meta["span"][1]]))
        cursor = meta["span"][1]
        old_cursor = surface_tables.metadata(original_shader, finish)["span"][1]
    old_end = sum(struct.unpack_from("<II", original_shader, 40))
    if shader[cursor:end] != original_shader[old_cursor:old_end] or len(rows) != 32:
        raise ValueError("Opaque device suffix/profile")
    return rows


def repack_parent(data, rows, replacements, old, repack):
    shader, (start, end), default, so, tail = layout(data)
    device = bytearray()
    cursor = start
    for row in rows:
        device += shader[cursor:row["begin"] - 8]
        frame, meta = row["frame"], bytearray(row["metadata"])
        if row["index"] in replacements:
            replacement = replacements[row["index"]]
            frame = repack.stored_frame(replacement)
            struct.pack_into("<IQ", meta, 4, len(replacement), old.murmur64(frame))
        device += struct.pack("<II", 1, len(frame)) + frame + meta
        cursor = row["stop"]
    device += shader[cursor:end]
    prefix = bytearray(shader[:start])
    new_default = (start + len(device) + 3) & ~3
    struct.pack_into("<I", prefix, 20, new_default)
    struct.pack_into("<I", prefix, 44, len(device))
    new_shader = bytes(prefix) + device + bytes(new_default - start - len(device))
    new_shader += er.serialize_defaults(er.default_table(shader[default:]))
    new_shader += bytes((-len(new_shader)) % 16)
    header = bytearray(data[:28])
    struct.pack_into("<II", header, 16, len(new_shader), so + len(new_shader))
    return bytes(header) + data[28:so] + new_shader + data[tail:]


def save(folder, name, data):
    with (folder / name).open("xb") as stream:
        stream.write(data)


def run(output):
    output = output.resolve()
    if not output.is_relative_to(ROOT / "docs") or not output.parent.is_dir() or output.exists():
        raise ValueError("Output must be a fresh child of an existing docs directory")
    parent = (G1 / "4ab784b71d6e9eb6.EXPERIMENTAL.material").read_bytes()
    if sha(parent) != PARENT_HASH or parent != sealed(E1, "enemy-4ab784b71d6e9eb6.EXPERIMENTAL.material"):
        raise ValueError("Current h1/e1 parent identity")
    original_shader = sealed(B1, "surface.shader43")
    original_report = json.loads(sealed(B1, "decoded.json"))
    old, shaders, repack, reflection, checks = build.dependencies()
    prepare, parser = old.prior()
    dxc = prepare.Dxc()
    before = walk(parent, original_shader, original_report, old, parser)
    output.mkdir()
    replacements, receipts = {}, []
    for row in before:
        i = row["index"]
        stem = f"program-{i:02d}"
        expected = sealed(E1, "enemy/" + stem + ".dxbc") if i in SELECTED else sealed(B1, stem + ".dxbc")
        if row["data"] != expected:
            raise ValueError("Current parent program identity: " + stem)
        if i not in SELECTED:
            continue
        source = sealed(E1, "enemy/" + stem + ".input.ll").decode()
        original = sealed(B1, stem + ".ll.txt").decode()
        profile = surface_shader.inspect(original)
        rgb = profile["ramp_samples"][0]["rgb"]
        if f"%hc.maxrg = call float @dx.op.binary.f32(i32 35, float {rgb[0]}, float {rgb[1]})" not in source:
            raise ValueError("Stock ramp max input")
        if f"%hc.value = call float @dx.op.binary.f32(i32 35, float %hc.maxrg, float {rgb[2]})" not in source:
            raise ValueError("Stock ramp max input")
        module = magenta_module(source)
        assembled, message = dxc.operation(module.encode(), assemble=True)
        if message:
            raise ValueError(message)
        signed, message = dxc.operation(assembled, assemble=False)
        if message or signed[4:20] == bytes(16):
            raise ValueError("DXC validation: " + str(message))
        save(output, stem + ".input.ll", module.encode())
        save(output, stem + ".dxbc", signed)
        reflected = reflection.dump(output / (stem + ".dxbc")).decode()
        save(output, stem + ".ll.txt", reflected.encode())
        old_text = sealed(E1, "enemy/" + stem + ".ll.txt").decode()
        if shader_tables.reflection_descriptors(old_text, old.murmur64) != shader_tables.reflection_descriptors(reflected, old.murmur64):
            raise ValueError("Buffer reflection changed")
        parts = lambda data: {c["tag"]: data[c["offset"] + 8:c["offset"] + 8 + c["size"]] for c in parser.dxbc(data)}
        previous_parts, new_parts = parts(expected), parts(signed)
        for tag in ("SFI0", "ISG1", "OSG1", "PSV0"):
            if previous_parts[tag] != new_parts[tag]:
                raise ValueError("Signature/binding change: " + tag)
        canonical = lambda text: build.canonical(re.sub(r", !dx.controlflow.hints !\d+", "", text), shaders)
        if canonical(module) != canonical(reflected):
            raise ValueError("Executable readback")
        save(output, stem + "-STAT.program", new_parts["STAT"])
        stat = reflection.dump(output / (stem + "-STAT.program")).decode()
        if checks.count_instructions(reflected) != checks.counters(stat):
            raise ValueError("STAT counters")
        replacements[i] = signed
        receipts.append(dict(index=i, before_sha256=sha(expected), sha256=sha(signed), dxc_valid=True,
                             bindings_unchanged=True, executable_readback=True, changed_assignments=3))
    if tuple(replacements) != SELECTED:
        raise ValueError("Selected pixel set")
    if repack_parent(parent, before, {}, old, repack) != parent:
        raise ValueError("No-op physical roundtrip")
    candidate = repack_parent(parent, before, replacements, old, repack)
    after = walk(candidate, original_shader, original_report, old, parser)
    for a, b in zip(before, after, strict=True):
        expected = replacements.get(a["index"], a["data"])
        if b["data"] != expected or a["metadata"][16:] != b["metadata"][16:]:
            raise ValueError("Program/metadata preservation")
        if a["index"] not in SELECTED and (a["frame"], a["metadata"]) != (b["frame"], b["metadata"]):
            raise ValueError("Unrelated frame changed")
    restored = repack_parent(candidate, after, {i: before[i]["data"] for i in SELECTED}, old, repack)
    if restored != parent:
        raise ValueError("Reverse physical roundtrip to exact h1 baseline")
    bs, _, bd, bso, bt = layout(parent)
    cs, _, cd, cso, ct = layout(candidate)
    if parent[28:bso] != candidate[28:cso] or er.default_table(bs[bd:]) != er.default_table(cs[cd:]):
        raise ValueError("Template/defaults changed")
    if parent[bt:] != candidate[ct:]:
        raise ValueError("Raytracing payload changed")
    normal_bs, normal_cs = bytearray(bs[:before[0]["begin"] - 8]), bytearray(cs[:after[0]["begin"] - 8])
    for field in (20, 44):
        normal_bs[field:field + 4] = normal_cs[field:field + 4] = bytes(4)
    if normal_bs != normal_cs:
        raise ValueError("Shader header/predevice/allocations changed")
    save(output, FILENAME, candidate)
    manifest = dict(status="OFFLINE DIAGNOSTIC ONLY; NOT INSTALLED; NOT PRODUCTION", filename=FILENAME,
                    baseline_sha256=PARENT_HASH, baseline_size=len(parent), sha256=sha(candidate), size=len(candidate),
                    target_relative="bundle/data/a4/a40299ecf616514c", material="4ab784b71d6e9eb6",
                    changed_programs=receipts, unchanged_programs=28, no_op_roundtrip=True,
                    exact_reverse_roundtrip=True, raytracing_payload_sha256=sha(parent[bt:]),
                    raytracing_payload_size=len(parent[bt:]), current_exports_preserved=True,
                    sentinel="ramp RGB -> (max(ramp RGB), 0, max(ramp RGB)); downstream shaping and alpha unchanged",
                    settings_independent=True, runtime_observed=False)
    save(output, "candidate.json", (json.dumps(manifest, indent=2) + "\n").encode())
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--output", type=Path, required=True)
    run(cli.parse_args().output)
