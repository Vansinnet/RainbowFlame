"""Fail-closed offline live-control authoring for retained Zealot flamer materials."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

sys.dont_write_bytecode = True
import build
import export_resources as exports
import live_shader
import shader_tables as tables
import staff20_live
import surface_shader
import surface_tables

ROOT = Path(__file__).resolve().parents[4]
ANALYSIS = ROOT / "mods/active/RainbowFlame/analysis/flamer-streams-20260922-a1"
STOCK = ANALYSIS / "stock/bundle"
REFLECTION = ANALYSIS / "reflection"
OUTPUT = ANALYSIS / "authored-materials"
CHILD = "3bbd4f5f32613f4b"
CHILD_STREAM = "data/45/455db6cbdf8e1dcf"
CHILD_SHA = "22ddeb2a2cfc1855634a35a9066ed79fd992bab1314ebbcc3ae6f257e7577c4d"

SPECS = {
    "da27aa083a052838": {
        "stream": "data/53/533194479779e27b",
        "sha256": "2a0b46efa9255d0912e32b1467dd9d2a70b6cbfc1ac0c17eb9b9228b33f8b03f",
        "targets": (1, 5, 9, 13),
        "programs": 19,
        "graphics": 16,
        "group_keys": (2458667051, 180305884, 3726170908, 567475058,
                       1738392509, 3193379250, 2938697923),
        "old_size": 96,
        "new_size": 128,
        "old_allocation": 384,
        "new_allocation": 416,
        "exports": ((live_shader.HSV, 3, 96, 16), (live_shader.CYCLE, 1, 112, 8)),
        "reflection_size": 92,
        "new_reflection_size": 120,
        "rgb": ("%146", "%147", "%148"),
        "time": "%150",
        "consumers": ("%197 = fmul fast float %196, %146",
                      "%202 = fmul fast float %201, %147",
                      "%207 = fmul fast float %206, %148"),
    },
    "be9333164c3ddf4a": {
        "stream": "data/c5/c54a5bfcf52f138d",
        "sha256": "886bb655bbc3ffa675ff33bdc49f80ef8a2cd2e45c8f502b97ea9539bbe1bd7e",
        "targets": tuple(range(1, 48, 4)),
        "programs": 48,
        "graphics": 48,
        "group_keys": (1942017389, 2344082089, 3051478205, 4071299203,
                       1971505776, 753235683, 1048270521, 2875303904,
                       3541708854, 2126836343, 3025818495, 2687166906),
        "old_size": 80,
        "new_size": 112,
        "old_allocation": 368,
        "new_allocation": 400,
        "exports": ((live_shader.HSV, 3, 80, 16), (live_shader.CYCLE, 1, 96, 8)),
        "reflection_size": 80,
        "new_reflection_size": 104,
        "rgb": ("%152", "%153", "%154"),
        "time": "%156",
        "consumers": ("%190 = fmul fast float %152, %7",
                      "%191 = fmul fast float %153, %8",
                      "%192 = fmul fast float %154, %9"),
    },
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def identity(data):
    return {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def source(name):
    spec = SPECS[name]
    data = (STOCK / spec["stream"]).read_bytes()
    require(identity(data)["sha256"] == spec["sha256"], "Exact retained source identity: " + name)
    return data


def parse_groups(data, spec, extended=False):
    c = tables.Cursor(data)
    require(c.words() == [len(spec["group_keys"])], "Registration group count")
    groups = []
    for index, key in enumerate(spec["group_keys"]):
        actual, allocation = c.words(2)
        require(actual == key, "Registration group key")
        resources = c.table(4)
        buffer_count = c.words()[0]
        graphics = index < len(spec["group_keys"]) - (3 if spec["programs"] == 19 else 0)
        require(len(resources) == (9 if graphics else 8), "Registration resource count")
        require(buffer_count == (4 if graphics else 3), "Registration buffer count")
        buffers = []
        for _ in range(buffer_count):
            descriptors = c.table(5)
            size, offset = c.words(2)
            require(descriptors and size > 0, "Registration buffer profile")
            for kind, elements, name, field, width in descriptors:
                require(name and kind <= 10 and field + max(1, elements) * width <= size,
                        "Registration descriptor extent")
                require(kind > 3 or (elements == 0 and width == 4 * (kind + 1)),
                        "Registration descriptor kind")
            buffers.append({"descriptors": descriptors, "size": size, "allocation_offset": offset})
        associations = c.table(7)
        technique_count = c.words()[0]
        techniques, trailer = c.read(17 * technique_count), c.read(8)
        if graphics:
            expected_size = spec["new_size"] if extended else spec["old_size"]
            expected_allocation = spec["new_allocation"] if extended else spec["old_allocation"]
            require(allocation == expected_allocation and len(associations) == 6 and technique_count == 2,
                    "Graphics registration profile")
            require([(len(b["descriptors"]), b["size"], b["allocation_offset"]) for b in buffers] ==
                    [(69, 1776, 0), (58, 400, 0), (3, 144, 144),
                     (16 if extended else 14, expected_size, 288)],
                    "Graphics buffer layout")
            require(trailer == b"\x01\x00\x00\x00\x00\x00\x00\x00", "Graphics trailer")
        else:
            require((allocation, len(associations), technique_count, trailer) ==
                    (224, 0, 1, bytes(8)), "Compute registration profile")
            require([(len(b["descriptors"]), b["size"], b["allocation_offset"]) for b in buffers] ==
                    [(69, 1776, 0), (12, 48, 112), (1, 64, 160)], "Compute buffer layout")
        groups.append({"key": key, "allocation": allocation, "resources": resources,
                       "buffers": buffers, "associations": associations,
                       "techniques": techniques, "trailer": trailer})
    require(c.p == len(data), "Registration exhaustion")
    return groups


def serialize_groups(groups):
    data = tables.words([len(groups)])
    for group in groups:
        data += tables.words([group["key"], group["allocation"]]) + tables.table(group["resources"])
        data += tables.words([len(group["buffers"])])
        for buffer in group["buffers"]:
            data += tables.table(buffer["descriptors"])
            data += tables.words([buffer["size"], buffer["allocation_offset"]])
        data += tables.table(group["associations"])
        data += tables.words([len(group["techniques"]) // 17]) + group["techniques"] + group["trailer"]
    return data


def inspect_parent(name, original):
    spec = SPECS[name]
    require(identity(original)["sha256"] == spec["sha256"], "Parent identity: " + name)
    version, mo, ms, so, ss, other, other_size = struct.unpack_from("<7I", original)
    require(version == 61 and mo == 28 and so == mo + ms and other == so + ss and
            other + other_size == len(original), "Material61 bounds: " + name)
    model = exports.material_template(original[mo:mo + ms])
    require(exports.serialize_material(model) == original[mo:mo + ms], "Template roundtrip: " + name)
    shader = original[so:so + ss]
    header = struct.unpack_from("<12I", shader)
    start, length, device, device_length = header[8:12]
    require(header[0] == 43 and start + length <= device < device + device_length <= header[5] < len(shader),
            "Shader43 bounds: " + name)
    groups = parse_groups(shader[start:start + length], spec)
    require(serialize_groups(groups) == shader[start:start + length], "Registration byte roundtrip: " + name)
    defaults = exports.default_table(shader[header[5]:])
    encoded = exports.serialize_defaults(defaults)
    require(encoded + bytes(len(shader) - header[5] - len(encoded)) == shader[header[5]:],
            "Defaults byte roundtrip: " + name)
    return shader


def color_path(name, text):
    spec = SPECS[name]
    text = text.replace("\r\n", "\n")
    if name == "be9333164c3ddf4a":
        path = staff20_live.color_path(text)
        require(tuple(path["rgb"]) == spec["rgb"] and path["time"] == spec["time"], "be93 topology")
        return path
    defs = surface_shader.definitions(text)
    require("define void @ps_main()" in text, "da27 pixel program")
    require(re.search(r"; c_material_exports\s+cbuffer\s+NA\s+NA\s+CB2\s+cb2\s+1", text),
            "da27 material binding")
    require(defs.get("%4") == "call %dx.types.Handle @dx.op.createHandle(i32 57, i8 2, i32 2, i32 2, i1 false)",
            "da27 material handle")
    expected = {
        "%67": "call %dx.types.CBufRet.i32 @dx.op.cbufferLoadLegacy.i32(i32 59, %dx.types.Handle %4, i32 1)",
        "%68": "extractvalue %dx.types.CBufRet.i32 %67, 2",
        "%48": "call %dx.types.CBufRet.i32 @dx.op.cbufferLoadLegacy.i32(i32 59, %dx.types.Handle %4, i32 0)",
        "%49": "extractvalue %dx.types.CBufRet.i32 %48, 1",
        "%145": "call %dx.types.ResRet.f32 @dx.op.sample.f32(i32 60, %dx.types.Handle %70, %dx.types.Handle %51, float %139, float %139, float undef, float undef, i32 0, i32 0, i32 undef, float %144)",
        "%149": "call %dx.types.CBufRet.f32 @dx.op.cbufferLoadLegacy.f32(i32 59, %dx.types.Handle %6, i32 90)",
        "%150": "extractvalue %dx.types.CBufRet.f32 %149, 0",
    }
    for value, definition in expected.items():
        require(defs.get(value) == definition, "da27 ramp/time anchor " + value)
    require("%68" in surface_shader.ancestors("%70", defs) and
            "%49" in surface_shader.ancestors("%51", defs), "da27 ramp ancestry")
    for channel, source, consumer, store in zip(range(3), spec["rgb"], spec["consumers"], ("%199", "%204", "%209")):
        require(defs.get(source) == f"extractvalue %dx.types.ResRet.f32 %145, {channel}", "da27 RGB extraction")
        require(defs.get(consumer.split(" =", 1)[0]) == consumer.split(" = ", 1)[1], "da27 RGB consumer")
        uses = [key for key, value in defs.items() if re.search(re.escape(source) + r"(?![\w.])", value)]
        require(uses == [consumer.split(" =", 1)[0]], "da27 exclusive RGB consumer")
        require(source in surface_shader.ancestors(store, defs), "da27 RGB output ancestry")
        require(f"i8 {channel}, float {store})" in text, "da27 RGB store")
    require("i8 3, float 0.000000e+00)" in text, "da27 stock alpha")
    return {"sample": "%145", "rgb": list(spec["rgb"]), "time": spec["time"], "shape": "%139"}


def module_for(name, original, stat, shaders):
    spec = SPECS[name]
    original, stat = original.replace("\r\n", "\n"), stat.replace("\r\n", "\n")
    color_path(name, original)
    body = shaders.body(original)
    require(not re.search(r"!\d+", body), "Unsupported executable metadata")
    module = stat[stat.index("target datalayout"):]
    require(module.count("declare void @ps_main()") == 1, "STAT entry")
    require("!2 = !{i32 0, i32 0}" in module, "STAT validator version")
    module = module.replace("!2 = !{i32 0, i32 0}", "!2 = !{i32 1, i32 7}")
    counters = re.search(r"^!dx.counters = !\{(!\d+)\}$", module, re.M)
    if counters is None:
        raise ValueError("STAT counters")
    module = re.sub(r"^!dx.counters = .*\n", "", module, flags=re.M)
    module = re.sub(r"^" + re.escape(counters[1]) + r" = .*\n", "", module, flags=re.M)
    old_type = re.search(r"^%c_material_exports = type \{.*\}$", module, re.M)
    resource = re.search(r"(%c_material_exports\* undef, !\"c_material_exports\", i32 0, i32 2, i32 1, i32 )" +
                         str(spec["reflection_size"]) + r"(, null)", module)
    annotation = re.search(r"%c_material_exports undef, (!\d+)", module)
    if old_type is None or resource is None or annotation is None:
        raise ValueError("Exact material reflection layout")
    module = module[:resource.start()] + resource[1] + str(spec["new_reflection_size"]) + resource[2] + module[resource.end():]
    module = module.replace(old_type[0], old_type[0][:-2] + ", <4 x float>, <2 x float> }")
    row = re.search(r"^" + re.escape(annotation[1]) + r" = !\{i32 " + str(spec["reflection_size"]) + r", (.*)\}$", module, re.M)
    if row is None:
        raise ValueError("Exact material annotation")
    next_id = 1 + max(map(int, re.findall(r"^!(\d+) =", module, re.M)))
    module = module.replace(row[0], f'{annotation[1]} = !{{i32 {spec["new_reflection_size"]}, {row[1]}, !{next_id}, !{next_id + 1}}}')
    for index, (export, _, offset, _) in enumerate(spec["exports"]):
        module += f'\n!{next_id + index} = !{{i32 6, !"{export}", i32 3, i32 {offset}, i32 7, i32 9}}\n'
    controls = live_shader.instructions(spec["rgb"], spec["time"], shaders, True, True)
    for control, register in (("hsv", spec["exports"][0][2] // 16),
                              ("cycle", spec["exports"][1][2] // 16)):
        controls, count = re.subn(r"(%rf\." + control + r" = call .*?%dx.types.Handle %4, i32 )\d+(\))",
                                  lambda match: match[1] + str(register) + match[2], controls)
        require(count == 1, "Control register rewrite")
    anchor = "  " + spec["consumers"][0]
    require(body.count(anchor) == 1, "RGB insertion point")
    changed = body.replace(anchor, controls + anchor)
    for channel, source, consumer in zip("rgb", spec["rgb"], spec["consumers"]):
        replacement = consumer.replace(source, "%rf." + channel)
        require(changed.count("  " + consumer) == 1, "Exact RGB consumer")
        changed = changed.replace("  " + consumer, "  " + replacement)
    reverse = changed.replace(controls, "")
    for channel, source, consumer in zip("rgb", spec["rgb"], spec["consumers"]):
        reverse = reverse.replace("  " + consumer.replace(source, "%rf." + channel), "  " + consumer)
    require(reverse == body, "Exact executable reverse")
    module = module.replace("declare void @ps_main()", changed)
    require("declare float @dx.op.binary.f32(" not in module, "Unexpected binary declaration")
    return module + "\ndeclare float @dx.op.binary.f32(i32, float, float) #0\n"


def append_template(model, hash32):
    result = copy.deepcopy(model)
    for name, kind, _, width in ((live_shader.HSV, 3, 0, 16), (live_shader.CYCLE, 1, 0, 8)):
        key = hash32(name)
        require(not any(row[2] == key for row in result["descriptors"]), "Material export collision")
        result["descriptors"].append([kind, 0, key, len(result["values"]), width])
        result["values"] += bytes(width)
    reverse = copy.deepcopy(result)
    reverse["descriptors"], reverse["values"] = reverse["descriptors"][:-2], reverse["values"][:-24]
    require(reverse == model, "Material template exact reverse")
    return result


def child_for(original, hash32):
    require(identity(original)["sha256"] == CHILD_SHA, "Child identity")
    header = list(struct.unpack_from("<7I", original))
    require(header == [61, 28, 316, 0xffffffff, 0, 0xffffffff, 0], "Child absence sentinels")
    model = exports.material_template(original[28:])
    require(exports.serialize_material(model) == original[28:], "Child template roundtrip")
    parent = struct.unpack_from("<Q", model["head"], 4)[0]
    require(parent == int("da27aa083a052838", 16), "Child parent reference")
    authored = append_template(model, hash32)
    template = exports.serialize_material(authored)
    header[2] = len(template)
    result = tables.words(header) + template
    reverse = copy.deepcopy(authored)
    reverse["descriptors"], reverse["values"] = reverse["descriptors"][:-2], reverse["values"][:-24]
    require(tables.words([61, 28, 316, 0xffffffff, 0, 0xffffffff, 0]) + exports.serialize_material(reverse) == original,
            "Whole child exact reverse")
    return result


def material_for(name, original, programs, replacements, old, repack):
    spec = SPECS[name]
    shader = inspect_parent(name, original)
    require(len(programs) == spec["programs"] and set(replacements) == set(spec["targets"]),
            "Exact replacement profile")
    _, mo, ms, _, _, other, other_size = struct.unpack_from("<7I", original)
    start, length, device_start, device_length = struct.unpack_from("<4I", shader, 32)
    default = struct.unpack_from("<I", shader, 20)[0]
    stock_groups = parse_groups(shader[start:start + length], spec)
    groups = copy.deepcopy(stock_groups)
    hash32 = lambda value: old.murmur64(value.encode()) >> 32
    stock_model = exports.material_template(original[mo:mo + ms])
    model = append_template(stock_model, hash32)
    defaults = exports.default_table(shader[default:])
    stock_defaults = copy.deepcopy(defaults)
    for export, kind, offset, width in spec["exports"]:
        key = hash32(export)
        require(not any(row[0] == key for row in defaults), "Default export collision")
        defaults.append((key, bytes(width)))
        for group in groups[:spec["graphics"] // 4]:
            buffer = group["buffers"][3]
            require(not any(row[2] == key for row in buffer["descriptors"]), "Registration export collision")
            buffer["descriptors"].append([kind, 0, key, offset, width])
    for group in groups[:spec["graphics"] // 4]:
        group["buffers"][3]["size"] = spec["new_size"]
        group["allocation"] = spec["new_allocation"]
    registration = serialize_groups(groups)
    require(parse_groups(registration, spec, True) == groups, "Extended registration readback")
    reversed_groups = copy.deepcopy(groups)
    for group in reversed_groups[:spec["graphics"] // 4]:
        group["buffers"][3]["descriptors"] = group["buffers"][3]["descriptors"][:-2]
        group["buffers"][3]["size"] = spec["old_size"]
        group["allocation"] = spec["old_allocation"]
    require(reversed_groups == stock_groups and serialize_groups(reversed_groups) == shader[start:start + length],
            "Registration exact reverse")
    prefix = bytearray(shader[:start] + registration)
    prefix += bytes((-len(prefix)) % 4)
    new_device_start = len(prefix)
    device, reverse_device, cursor, frames = bytearray(), bytearray(), device_start, []
    material_hash = hash32("c_material_exports")
    for index, program in enumerate(programs):
        begin, end = program["frame"]
        metadata = surface_tables.metadata(shader, end)
        stop = metadata["span"][1]
        require(cursor <= begin - 8 < end < stop <= device_start + device_length, "Program ordering")
        require(struct.unpack_from("<II", shader, begin - 8) == (1, end - begin), "Program frame envelope")
        require(metadata["header"][2] | metadata["header"][3] << 32 == old.murmur64(shader[begin:end]),
                "Program frame key")
        gap = shader[cursor:begin - 8]
        device += gap
        reverse_device += gap
        frame = shader[begin:end]
        authored_metadata = bytearray(shader[end:stop])
        if index in replacements:
            frame = repack.stored_frame(replacements[index])
            struct.pack_into("<IQ", authored_metadata, 4, len(replacements[index]), old.murmur64(frame))
        matches = []
        table = metadata["tables"][0]
        for row_index, row in enumerate(table["rows"]):
            if row[0] == material_hash:
                require(row[1:3] == [3, spec["old_size"]], "Program material association")
                position = table["offset"] - end + 4 + row_index * 24 + 8
                struct.pack_into("<I", authored_metadata, position, spec["new_size"])
                matches.append(position)
        require(len(matches) == (1 if index < spec["graphics"] else 0), "Program material association count")
        after = surface_tables.metadata(authored_metadata, 0)
        for table_index, (before_table, after_table) in enumerate(zip(metadata["tables"], after["tables"], strict=True)):
            expected = copy.deepcopy(before_table["rows"])
            if table_index == 0:
                for row in expected:
                    if row[0] == material_hash:
                        row[2] = spec["new_size"]
            require(expected == after_table["rows"], "Unexpected metadata mutation")
        new_begin = new_device_start + len(device) + 8
        device += tables.words([1, len(frame)]) + frame + authored_metadata
        frames.append({"index": index, "frame": [new_begin, new_begin + len(frame)],
                       "unchanged": index not in replacements})
        authored_metadata[:16] = shader[end:end + 16]
        for position in matches:
            struct.pack_into("<I", authored_metadata, position, spec["old_size"])
        require(authored_metadata == shader[end:stop], "Program metadata exact reverse")
        reverse_device += shader[begin - 8:end] + authored_metadata
        cursor = stop
    device += shader[cursor:device_start + device_length]
    reverse_device += shader[cursor:device_start + device_length]
    require(reverse_device == shader[device_start:device_start + device_length], "Complete device exact reverse")
    new_default = (new_device_start + len(device) + 3) & ~3
    struct.pack_into("<I", prefix, 20, new_default)
    struct.pack_into("<3I", prefix, 36, len(registration), new_device_start, len(device))
    new_shader = bytes(prefix) + device + bytes(new_default - new_device_start - len(device))
    new_shader += exports.serialize_defaults(defaults)
    new_shader += bytes((-len(new_shader)) % 16)
    template = exports.serialize_material(model)
    new_shader_offset = 28 + len(template)
    result = (tables.words([61, 28, len(template), new_shader_offset, len(new_shader),
                            new_shader_offset + len(new_shader), other_size]) +
              template + new_shader + original[other:])
    require(exports.material_template(template) == model, "Authored template readback")
    require(exports.default_table(new_shader[new_default:]) == defaults and defaults[:-2] == stock_defaults,
            "Authored defaults readback")
    require(new_shader[48:start] == shader[48:start], "Shader context/dependency preservation")
    for index, frame in enumerate(frames):
        begin, end = frame["frame"]
        old_begin, old_end = programs[index]["frame"]
        if index in replacements:
            require(repack.frame_payload(new_shader[begin:end], len(replacements[index]), {}) == replacements[index],
                    "Replacement frame readback")
        else:
            require(new_shader[begin:end] == shader[old_begin:old_end], "Non-target frame byte identity")
    reverse_model = copy.deepcopy(model)
    reverse_model["descriptors"], reverse_model["values"] = reverse_model["descriptors"][:-2], reverse_model["values"][:-24]
    reverse_shader = (shader[:start] + serialize_groups(reversed_groups) + shader[start + length:device_start] +
                      bytes(reverse_device) + shader[device_start + device_length:default] +
                      exports.serialize_defaults(defaults[:-2]))
    reverse_shader += bytes(len(shader) - len(reverse_shader))
    require(original[:28] + exports.serialize_material(reverse_model) + reverse_shader + original[other:] == original,
            "Whole parent exact reverse")
    return result, new_shader, {"frames": frames, "byte_exact_reverse": True,
                                "non_target_frames_preserved": spec["programs"] - len(spec["targets"]),
                                "metadata_tables_verified": spec["programs"],
                                "registration_groups": len(groups),
                                "compute_groups_preserved": 3 if spec["programs"] == 19 else 0,
                                "old_allocation": spec["old_allocation"],
                                "new_allocation": spec["new_allocation"],
                                "material_buffer_size": spec["new_size"]}


def verify_buffer_definitions(original, authored, spec):
    def block(text):
        return text.replace("\r\n", "\n").split("; Buffer Definitions:")[1].split("; Resource Bindings:")[0]
    before, after = block(original), block(authored)
    for name, _, offset, width in spec["exports"]:
        after, count = re.subn(r"^;\s+float" + str(width // 4) + " " + name +
                               r";\s*; Offset:\s*" + str(offset) + r"\n", "", after, flags=re.M)
        require(count == 1, "Exact custom buffer declaration")
    stock_extent = re.search(r"^;\s+\} c_material_exports;\s*; Offset:\s*0 Size:\s*" +
                             str(spec["reflection_size"]) + r"\s*$", before, re.M)
    if stock_extent is None:
        raise ValueError("Original material-buffer extent")
    after, count = re.subn(r"^;\s+\} c_material_exports;\s*; Offset:\s*0 Size:\s*" +
                           str(spec["new_reflection_size"]) + r"\s*$",
                           stock_extent[0], after, flags=re.M)
    require(count == 1 and before == after, "All original buffer definitions")


def run(output=OUTPUT, resume=False):
    output = Path(output).resolve()
    require(output == OUTPUT and (not output.exists() or resume), "New authored-materials directory required")
    require(not (output / "SHA256SUMS.json").exists(), "Completed output cannot be resumed")
    manifest = json.loads((REFLECTION / "manifest.json").read_text())
    rows = {row["material"]: row for row in manifest}
    old, shaders, repack, reflection, checks = build.dependencies()
    prepare, parser = old.prior()
    dxc = prepare.Dxc()
    parents = {name: source(name) for name in SPECS}
    child_original = (STOCK / CHILD_STREAM).read_bytes()
    hash32 = lambda value: old.murmur64(value.encode()) >> 32
    child = child_for(child_original, hash32)
    output.mkdir(exist_ok=resume)

    def save(name, data):
        if resume and (output / name).exists():
            require((output / name).read_bytes() == data, "Resume artifact differs: " + name)
            return
        with (output / name).open("xb") as stream:
            stream.write(data)

    def chunks(data):
        return {chunk["tag"]: data[chunk["offset"] + 8:chunk["offset"] + 8 + chunk["size"]]
                for chunk in parser.dxbc(data)}

    reports = {}
    for name, spec in SPECS.items():
        original = parents[name]
        shader = inspect_parent(name, original)
        row = rows[name]
        require(row["source_sha256"] == spec["sha256"] and len(row["programs"]) == spec["programs"],
                "Reflection manifest source identity")
        replacements, program_reports = {}, []
        for index, program in enumerate(row["programs"]):
            base = REFLECTION / name / f"program-{index:02d}"
            data = base.with_suffix(".dxbc").read_bytes()
            text = base.with_suffix(".ll.txt").read_text().replace("\r\n", "\n")
            require(identity(data)["sha256"] == program["sha256"], "Retained program identity")
            metadata = surface_tables.metadata(shader, program["frame"][1])
            require(metadata["header"][1] == len(data), "Retained program length")
            signed, message = dxc.operation(data, assemble=False)
            require(not message and signed == data and data[4:20] != bytes(16), "Original signed DXIL")
            require(reflection.dump(base.with_suffix(".dxbc")).decode().replace("\r\n", "\n") == text,
                    "Retained reflection readback")
            if index >= spec["graphics"]:
                require(program["stage"] == "cs_main", "Compute stage profile")
            else:
                require(program["stage"] == ("vs_main" if index % 2 == 0 else "ps_main"), "Graphics stage profile")
            if index not in spec["targets"]:
                program_reports.append({"index": index, **identity(data), "unchanged": True,
                                        "signed_validation": True, "reflection_readback": True})
                continue
            color_path(name, text)
            parts = chunks(data)
            save(f"{name}-program-{index:02d}-original-STAT.program", parts["STAT"])
            stat = reflection.dump(output / f"{name}-program-{index:02d}-original-STAT.program").decode()
            module = module_for(name, text, stat, shaders)
            save(f"{name}-program-{index:02d}.input.ll", module.encode())
            assembled, message = dxc.operation(module.encode(), assemble=True)
            require(not message, "DXIL assembly: " + str(message))
            signed, message = dxc.operation(assembled, assemble=False)
            require(not message and signed[4:20] != bytes(16), "DXIL signed validation: " + str(message))
            stem = f"{name}-program-{index:02d}"
            save(stem + ".dxbc", signed)
            reflected = reflection.dump(output / (stem + ".dxbc")).decode().replace("\r\n", "\n")
            save(stem + ".ll.txt", reflected.encode())
            require(build.canonical(module, shaders) == build.canonical(reflected, shaders),
                    "Signed executable canonical identity")
            before_fields = tables.reflection_descriptors(text, old.murmur64)
            after_fields = tables.reflection_descriptors(reflected, old.murmur64)
            require(before_fields.keys() == after_fields.keys(), "Original reflected buffer set")
            for buffer_name, fields in before_fields.items():
                require(fields == (after_fields[buffer_name][:-2] if buffer_name == "c_material_exports" else after_fields[buffer_name]),
                        "Original reflected offsets")
            require(after_fields["c_material_exports"][-2:] ==
                    [{"name": export, "hash": hash32(export), "offset": offset, "width": width}
                     for export, _, offset, width in spec["exports"]], "Custom reflected fields")
            verify_buffer_definitions(text, reflected, spec)
            require(text.split("; Resource Bindings:")[1].split("; ViewId state:")[0] ==
                    reflected.split("; Resource Bindings:")[1].split("; ViewId state:")[0],
                    "Every original resource binding")
            new_parts = chunks(signed)
            for tag in ("SFI0", "ISG1", "OSG1", "PSV0"):
                require(parts[tag] == new_parts[tag], "Unchanged signature/binding chunk " + tag)
            save(stem + "-STAT.program", new_parts["STAT"])
            new_stat = reflection.dump(output / (stem + "-STAT.program")).decode()
            save(stem + "-STAT.ll.txt", new_stat.encode())
            require(checks.count_instructions(reflected) == checks.counters(new_stat), "STAT instruction counters")
            replacements[index] = signed
            program_reports.append({"index": index, **identity(signed), "unchanged": False,
                                    "signed_validation": True, "reflection_readback": True,
                                    "canonical_executable": True, "stat_counters": True,
                                    "exact_body_reverse": True})
        material, new_shader, verification = material_for(name, original, row["programs"], replacements, old, repack)
        save(name + ".material", material)
        save(name + ".shader43", new_shader)
        reports[name] = {"source": identity(original), "material": identity(material),
                         "shader": identity(new_shader), "exports": spec["exports"],
                         "targets": list(spec["targets"]), "programs": program_reports,
                         "verification": verification}
    save(CHILD + ".material", child)
    report = {
        "status": "OFFLINE VERIFIED; NATIVE LOADING AND LIVE REGISTRATION UNTESTED",
        "parents": reports,
        "child": {"source": identity(child_original), "material": identity(child),
                  "parent_reference": "da27aa083a052838", "byte_exact_reverse": True},
        "controls": {"default": "w=0: stock RGB, opacity ignored",
                     "original": "w=-1: stock RGB times opacity; brightness ignored",
                     "selected": "w>0: selected hue, brightness and opacity",
                     "rainbow": "cycle.x>0: time*cycle.y with smooth Original pause"},
        "preservation": {"all_stock_descriptors_and_defaults": True,
                         "all_non_target_programs": True, "da27_compute_programs_16_18": True,
                         "other_and_tail_payloads": True, "exact_parent_and_child_reverse": True},
        "limitations": ["No installed files, payload, Lua, deployment, native loading, or in-game behavior were tested."],
    }
    save("report.json", (json.dumps(report, indent=2) + "\n").encode())
    sums = {path.name: identity(path.read_bytes()) for path in sorted(output.iterdir()) if path.is_file()}
    save("SHA256SUMS.json", (json.dumps(sums, indent=2) + "\n").encode())
    print(json.dumps({"output": str(output), "parents": {key: value["material"] for key, value in reports.items()},
                      "child": report["child"]["material"]}, indent=2))


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--output", default=str(OUTPUT))
    cli.add_argument("--resume", action="store_true")
    args = cli.parse_args()
    run(args.output, args.resume)
