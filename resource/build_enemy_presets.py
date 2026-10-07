"""Build selectable, baked Soulblaze resources from retained offline inputs."""
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
    raise RuntimeError("Run without -O: exact-profile assertions are required")

import build
import diagnostic_surface as surface
import enemy_cloud_bundle as enemy_bundle
import shader_tables
import surface_shader

ROOT = build.WORKSPACE
STOCK_BUNDLE = ROOT / "docs/analysis-rainbow-enemy-material-routing-20260919-l1/30ebeee18093c079.stock.rollback"
STOCK_BUNDLE_SHA = "53fd3e19870d70e18377151233f3aa3a141ead0339c55ad4dd83b4625fa5e531"
GLOBAL_PACKAGE = "30ebeee18093c079"
ORIGINAL_EFFECT = "content/fx/particles/enemies/buff_warpfire"
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
OPACITY_LEVELS = (0, 25, 50, 75, 100)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(value, message):
    if not value:
        raise ValueError(message)


def hsv_rgb(hue, saturation, value):
    chroma = value * saturation
    sector = (hue % 360) / 60
    x = chroma * (1 - abs(sector % 2 - 1))
    colors = ((chroma, x, 0), (x, chroma, 0), (0, chroma, x),
              (0, x, chroma), (x, 0, chroma), (chroma, 0, x))
    base = colors[int(sector) % 6]
    match = value - chroma
    return tuple(channel + match for channel in base)


def fixed_module(text, rgb, float_ir):
    changed = text
    for channel, factor in zip("rgb", rgb):
        pattern = rf"^  %rf\.{channel} = select i1 %rf.active, float %rf\.{channel}\.mixed, float %\d+$"
        replacement = f"  %rf.{channel} = fmul float %hc.value, {float_ir(factor)}"
        changed, count = re.subn(pattern, replacement, changed, flags=re.M)
        require(count == 1, "Unexpected final ramp consumer: " + channel)
    require(sum(a != b for a, b in zip(text.splitlines(), changed.splitlines())) == 3,
            "Nonminimal shader edit")
    return changed


def scaled_module(text, opacity, float_ir):
    changed = text
    for channel in "rgb":
        pattern = rf"^  %rf\.{channel} = (select i1 %rf.active, float %rf\.{channel}\.mixed, float %\d+)$"
        replacement = (f"  %rf.{channel}.opacity_source = \\1\n"
                       f"  %rf.{channel} = fmul float %rf.{channel}.opacity_source, {float_ir(opacity)}")
        changed, count = re.subn(pattern, replacement, changed, flags=re.M)
        require(count == 1, "Unexpected final ramp consumer: " + channel)
    require(len(changed.splitlines()) == len(text.splitlines()) + 3,
            "Nonminimal opacity shader edit")
    return changed


def variants():
    yield "hidden", "content/fx/particles/rainbow_flame/buff_warpfire_hidden", None, (0, 0, 0), 0
    for opacity in OPACITY_LEVELS[1:-1]:
        effect = f"content/fx/particles/rainbow_flame/buff_warpfire_original_opacity_{opacity}"
        yield f"original_{opacity}", effect, "original", None, opacity
    for preset, hsv in PRESETS.items():
        base_rgb = hsv_rgb(*hsv)
        for opacity in OPACITY_LEVELS[1:]:
            suffix = "" if opacity == 100 else f"_opacity_{opacity}"
            effect = f"content/fx/particles/rainbow_flame/buff_warpfire_{preset}{suffix}"
            rgb = tuple(channel * opacity / 100 for channel in base_rgb)
            yield f"{preset}_{opacity}", effect, preset, rgb, opacity


def build_parent(rgb, opacity):
    parent = (surface.G1 / "4ab784b71d6e9eb6.EXPERIMENTAL.material").read_bytes()
    require(sha(parent) == surface.PARENT_HASH, "Parent baseline drift")
    original_shader = surface.sealed(surface.B1, "surface.shader43")
    report = json.loads(surface.sealed(surface.B1, "decoded.json"))
    old, shaders, repack, _, _ = build.dependencies()
    prepare, parser = old.prior()
    dxc = prepare.Dxc()
    before = surface.walk(parent, original_shader, report, old, parser)
    replacements = {}
    for row in before:
        if row["index"] not in surface.SELECTED:
            continue
        stem = f"program-{row['index']:02d}"
        source = surface.sealed(surface.E1, "enemy/" + stem + ".input.ll").decode()
        module = (scaled_module(source, opacity / 100, shaders.float_ir)
                  if rgb is None else fixed_module(source, rgb, shaders.float_ir))
        assembled, error = dxc.operation(module.encode(), assemble=True)
        require(not error, error)
        signed, error = dxc.operation(assembled, assemble=False)
        require(not error and signed[4:20] != bytes(16), str(error))
        replacements[row["index"]] = signed
    require(tuple(replacements) == surface.SELECTED, "Selected shader set")
    candidate = surface.repack_parent(parent, before, replacements, old, repack)
    after = surface.walk(candidate, original_shader, report, old, parser)
    for previous, current in zip(before, after, strict=True):
        require(current["data"] == replacements.get(previous["index"], previous["data"]),
                "Shader readback")
    return candidate


def resource_record(identity, body, streamed):
    kind, flag = (0, 1) if streamed else (0, 0)
    descriptor = struct.pack("<IBIBI", kind, flag, len(body), 1, 0)
    return struct.pack("<QQII", identity[0], identity[1], 1, 0) + descriptor + body


def stream_pointer(relative):
    encoded = relative.encode("ascii") + bytes(4)
    require(len(encoded) <= 64, "Stream pointer bound")
    return encoded


def serialize_expanded(bundle, index, logical):
    prefix = enemy_bundle.fmt.MAGIC + struct.pack("<I", len(index)) + bundle.prefix[12:268]
    prefix += b"".join(struct.pack("<QQI", *entry) for entry in index)
    chunks = math.ceil(len(logical) / enemy_bundle.fmt.CHUNK)
    padded = logical + bytes(chunks * enemy_bundle.fmt.CHUNK - len(logical))
    out = bytearray(prefix)
    out += struct.pack("<I", chunks)
    out += struct.pack("<" + "I" * chunks, *([enemy_bundle.fmt.CHUNK] * chunks))
    out += bytes((-len(out)) % 16)
    out += struct.pack("<II", len(logical), 0)
    for number in range(chunks):
        out += struct.pack("<I", enemy_bundle.fmt.CHUNK)
        out += bytes((-len(out)) % 16)
        out += padded[number * enemy_bundle.fmt.CHUNK:(number + 1) * enemy_bundle.fmt.CHUNK]
    return bytes(out)


def read_expanded(data, expected_count):
    cursor = enemy_bundle.fmt.Cursor(data)
    require(cursor.take(8) == enemy_bundle.fmt.MAGIC, "Candidate header")
    count, = cursor.unpack("<I")
    require(count == expected_count, "Candidate index count")
    cursor.take(256)
    index = [cursor.unpack("<QQI") for _ in range(count)]
    chunks, = cursor.unpack("<I")
    sizes = [cursor.unpack("<I")[0] for _ in range(chunks)]
    require(all(size == enemy_bundle.fmt.CHUNK for size in sizes), "Candidate stored chunks")
    table_padding = cursor.align()
    length, zero = cursor.unpack("<II")
    require(zero == 0 and math.ceil(length / enemy_bundle.fmt.CHUNK) == chunks,
            "Candidate logical length")
    blocks, pads = [], []
    for size in sizes:
        require(cursor.unpack("<I")[0] == size, "Candidate inline chunk size")
        pads.append(cursor.align())
        blocks.append(cursor.take(size))
    require(cursor.pos == len(data), "Candidate trailing bytes")
    full = b"".join(blocks)
    bundle = enemy_bundle.fmt.Bundle(data[:268 + 20 * count], index, table_padding, pads,
                                     full[:length], full[length:], sizes)
    return bundle


def run(output):
    output = output.resolve()
    require(output.parent.is_dir() and not output.exists() and output.is_relative_to(ROOT / "docs"),
            "Output must be a fresh docs child")
    source = STOCK_BUNDLE.read_bytes()
    require(sha(source) == STOCK_BUNDLE_SHA, "Stock global bundle drift")
    container, _ = enemy_bundle.read(source, enemy_bundle.baseline.decoder())
    records = enemy_bundle.fmt.records(container)
    murmur = enemy_bundle.baseline.assets.index.murmur
    particle_type, material_type = murmur("particles"), murmur("material")
    original_name = murmur(ORIGINAL_EFFECT)
    particle_record, = [row for row in records if row["identity"][:2] == (particle_type, original_name)]
    _, original_particle, tail = particle_record["bodies"][0]
    require(not tail and original_particle.count(struct.pack("<Q", 0x612E95B62B8E2AEB)) == 1,
            "Soulblaze material reference")
    base_child = surface.sealed(surface.E1, "enemy-612e95b62b8e2aeb.EXPERIMENTAL.material")
    old_parent = struct.pack("<Q", 0x4AB784B71D6E9EB6)
    require(base_child.count(old_parent) == 1, "Child parent reference")

    output.mkdir()
    streams = output / "bundle/data/rf"
    streams.mkdir(parents=True)
    index = list(container.index)
    appended = bytearray()
    manifest = {}
    variant_rows = tuple(variants())
    for key, effect, preset, rgb, opacity in variant_rows:
        parent_name = effect + "_parent"
        child_name = effect + "_material"
        parent_hash, child_hash = murmur(parent_name), murmur(child_name)
        particle_hash = murmur(effect)
        require(len({parent_hash, child_hash, particle_hash}) == 3, "Preset hash collision")
        parent = build_parent(rgb, opacity)
        child = base_child.replace(old_parent, struct.pack("<Q", parent_hash))
        particle = original_particle.replace(struct.pack("<Q", 0x612E95B62B8E2AEB), struct.pack("<Q", child_hash))
        parent_pointer = f"data/rf/{parent_hash:016x}"
        child_pointer = f"data/rf/{child_hash:016x}"
        (streams / f"{parent_hash:016x}").write_bytes(parent)
        (streams / f"{child_hash:016x}").write_bytes(child)
        entries = (
            ((material_type, parent_hash, 4), stream_pointer(parent_pointer), True),
            ((material_type, child_hash, 4), stream_pointer(child_pointer), True),
            ((particle_type, particle_hash, 0), particle, False),
        )
        for identity, body, streamed in entries:
            require(identity not in index, "Resource identity collision")
            index.append(identity)
            appended += resource_record(identity, body, streamed)
        manifest[key] = {
            "effect": effect,
            "color": preset,
            "opacity": opacity,
            "rgb": rgb,
            "particle_hash": f"{particle_hash:016x}",
            "parent_hash": f"{parent_hash:016x}",
            "child_hash": f"{child_hash:016x}",
            "parent_size": len(parent),
            "child_size": len(child),
            "parent_sha256": sha(parent),
            "child_sha256": sha(child),
            "particle_sha256": sha(particle),
        }
    candidate = serialize_expanded(container, index, container.logical + appended)
    reread = read_expanded(candidate, len(index))
    after = enemy_bundle.fmt.records(reread)
    require(len(after) == len(records) + 3 * len(variant_rows), "Expanded record count")
    require(all(a["raw"] == b["raw"] for a, b in zip(records, after)), "Stock records changed")
    bundle_path = output / GLOBAL_PACKAGE
    bundle_path.write_bytes(candidate)
    result = {
        "status": "OFFLINE PRODUCTION CANDIDATE; NOT INSTALLED; RUNTIME SELECTION UNTESTED",
        "source_bundle_sha256": STOCK_BUNDLE_SHA,
        "bundle": {"path": GLOBAL_PACKAGE, "size": len(candidate), "sha256": sha(candidate)},
        "preserved_stock_records": len(records),
        "added_records": 3 * len(variant_rows),
        "opacity_levels": OPACITY_LEVELS,
        "variants": manifest,
        "installed_writes": 0,
    }
    (output / "candidate.json").write_text(json.dumps(result, indent=2) + "\n", encoding="ascii")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--output", type=Path, required=True)
    run(cli.parse_args().output)
