"""Rebuild RainbowFlame's whole payload from the installed game's stock files.

Run this after every Darktide update that `reforge verify` reports as changed:

    python mods/active/RainbowFlame/resource/rebuild_payload.py

RainbowFlame's 166 files are edits of stock resources: 8 replaced material streams, 152 preset
streams under payload/direct/data/rf cloned from 11 stock materials, 5 weapon effect bundles with
renamed cloud identifiers and the preset host package (stock debug package plus 204 records cloned
from the Soulblaze, staff impact and flamer impact packages). The builders that authored them are
pinned to build 24735202, so this script carries the edits forward instead of re-authoring them:

* resource/rebuild_recipe.json records, for every payload file, its stock origin and how that
  stock differs from the payload (reverse patches of the material template, registration buffer,
  defaults and device segments; the stock body of every edited shader program as a line patch of
  the payload's disassembly; the swapped identifiers in bundles and cloned particles). The payload
  plus the recipe therefore stand in for the stock the payload was built from, without keeping game
  files.
* A rebuild is a three-way merge of that stock (A), the payload (V) and the installed stock (B):
  parts only RainbowFlame changed come from V, parts only the game changed come from B, and every
  edited shader program is transplanted onto B's program through an SSA alignment checked
  instruction by instruction, reassembled and signed with DXC. This is the method that carried the
  1.4.0 edits to material version 62 (analysis/v62-update-20261003).

It stops on anything it cannot merge mechanically: a new material or shader version, a changed
frame count, a part both sides changed, an unaligned edited instruction, a missing identifier. That
is the point to read REVERSE_ENGINEERING.md and the stopped file's builder again.

After a real run it pins the new stock hashes with `reforge add` (keeping `late_load`), records a
new recipe from the new stock, ready for the next patch, and runs `reforge build`.

Tools: the game's Oodle library (through tools/reforge/cli/bundle8.py) and Microsoft's DXC in
tools/dxc/bin/x64 (dxcompiler.dll and dxc.exe; override with RF_DXC). Windows only.
"""
import argparse
import ctypes as C
import difflib
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
MOD = HERE.parent
WORKSPACE = MOD.parents[2]
sys.path.insert(0, str(WORKSPACE / "tools/reforge/cli"))
import bundle8  # noqa: E402

GAME = Path(r"D:\Steam\steamapps\common\Warhammer 40,000 DARKTIDE")
DXC = Path(os.environ.get("RF_DXC", WORKSPACE / "tools/dxc/bin/x64"))
RECIPE = HERE / "rebuild_recipe.json"
PAYLOAD = MOD  # folder holding payload/ (--payload)
OVERLAY = None  # older stock files laid out like the game's, used where present (--stock)
KNOWN_VERSIONS = {61, 62}
SHADER_VERSION = 43
NONE = 0xFFFFFFFF
PARTICLE = 0xA8193123526FAD64
MATERIAL = 0xEAC0B497876ADEDF
HOST = "bundle/ac7ddd2788c1ef1f"
# The packages the presets were cloned from (commit 1f1f70a): Soulblaze, flamer impact, staff impact.
SOURCES = ("bundle/30ebeee18093c079", "bundle/3d487cca8bd5c544", "bundle/97498862fb42b0d6")


def sha(data):
    return hashlib.sha256(data).hexdigest()


class Fail(Exception):
    pass


def need(condition, message):
    if not condition:
        raise Fail(message)


def words(values):
    return struct.pack(f"<{len(values)}I", *values)


def W(data, offset, n=1):
    return struct.unpack_from(f"<{n}I", data, offset)


def murmur64(data):
    multiplier, mask = 0xC6A4A7935BD1E995, (1 << 64) - 1
    value = len(data) * multiplier & mask
    end = len(data) // 8 * 8
    for (word,) in struct.iter_unpack("<Q", data[:end]):
        word = word * multiplier & mask
        word ^= word >> 47
        value = (value ^ (word * multiplier & mask)) * multiplier & mask
    if data[end:]:
        value = (value ^ int.from_bytes(data[end:], "little")) * multiplier & mask
    value ^= value >> 47
    value = value * multiplier & mask
    return value ^ (value >> 47)


# ---- Reverse patches: rebuild the stock part from the payload part ----

def rpatch(v, a):
    """None when equal, else the common prefix/suffix lengths and A's middle."""
    if v == a:
        return None
    p = 0
    while p < min(len(v), len(a)) and v[p] == a[p]:
        p += 1
    s = 0
    while s < min(len(v), len(a)) - p and v[-1 - s] == a[-1 - s]:
        s += 1
    return [p, s, a[p:len(a) - s].hex()]


def unpatch(v, patch):
    if patch is None:
        return v
    p, s, middle = patch
    return v[:p] + bytes.fromhex(middle) + v[len(v) - s:]


def line_patch(lv, la):
    return [[i1, i2, la[j1:j2]] for tag, i1, i2, j1, j2 in
            difflib.SequenceMatcher(None, lv, la, autojunk=False).get_opcodes() if tag != "equal"]


def line_unpatch(lv, patch):
    out, k = [], 0
    for i1, i2, lines in patch:
        out += lv[k:i1] + lines
        k = i2
    return out + lv[k:]


# ---- DXC (COM through ctypes; one calling convention on x64) ----

P, H, U = C.c_void_p, C.c_int32, C.c_uint32


def _method(obj, slot, result, *types):
    table = C.cast(obj, C.POINTER(C.POINTER(P))).contents
    return C.CFUNCTYPE(result, P, *types)(table[slot])


def _release(obj):
    if obj:
        _method(obj, 2, U)(obj)


def _check(hr):
    if hr < 0:
        raise Fail(f"DXC HRESULT 0x{hr & 0xffffffff:08x}")


def _blob_bytes(blob):
    if not blob:
        return b""
    size = _method(blob, 4, C.c_size_t)(blob)
    need(size <= 4_000_000, "DXC blob too large")
    return C.string_at(_method(blob, 3, P)(blob), size)


class Dxc:
    """IDxcAssembler and IDxcValidator from dxcompiler.dll (the validator signs the container)."""

    def __init__(self, folder=DXC):
        need((folder / "dxcompiler.dll").is_file() and (folder / "dxc.exe").is_file(),
             f"DXC not found in {folder} (set RF_DXC)")
        os.add_dll_directory(str(folder))
        self.folder = folder
        self.lib = C.CDLL(str(folder / "dxcompiler.dll"))
        self.version = subprocess.run([str(folder / "dxc.exe"), "--version"], capture_output=True,
                                      timeout=30).stdout.decode().strip()
        self.dumps = {}

    def _create(self, clsid, iid):
        fn = self.lib.DxcCreateInstance
        fn.argtypes, fn.restype = [P, P, C.POINTER(P)], H
        c, i = (C.create_string_buffer(uuid.UUID(x).bytes_le) for x in (clsid, iid))
        obj = P()
        _check(fn(c, i, C.byref(obj)))
        need(obj, "DXC returned no object")
        return obj

    def _blob(self, data):
        need(0 < len(data) <= 4_000_000, "DXC input out of bounds")
        utils = self._create("6245d6af-66e0-48fd-80b4-4d271796748c", "4605c4cb-2019-492a-ada4-65f20bb7d67f")
        blob = P()
        try:
            self._memory = C.create_string_buffer(data)
            _check(_method(utils, 6, H, P, U, U, C.POINTER(P))(utils, self._memory, len(data), 0, C.byref(blob)))
            return blob
        finally:
            _release(utils)

    def _operation(self, data, assemble):
        blob, obj, res, out, err = self._blob(data), P(), P(), P(), P()
        try:
            if assemble:
                obj = self._create("d728db68-f903-4f80-94cd-dccf76ec7151", "091f7a26-1c1f-4948-904b-e6e3a8a771d5")
                _check(_method(obj, 3, H, P, C.POINTER(P))(obj, blob, C.byref(res)))
            else:
                obj = self._create("8ca3e215-f728-4cf3-8cdd-88af917587a1", "a6e82bd2-1fd7-4826-9811-2857e797f49a")
                _check(_method(obj, 3, H, P, U, C.POINTER(P))(obj, blob, 0, C.byref(res)))
            status = H()
            _check(_method(res, 3, H, C.POINTER(H))(res, C.byref(status)))
            _check(_method(res, 5, H, C.POINTER(P))(res, C.byref(err)))
            message = _blob_bytes(err).decode("utf-8", "replace").rstrip("\0")
            need(status.value >= 0, f"DXC operation failed: {message}")
            _check(_method(res, 4, H, C.POINTER(P))(res, C.byref(out)))
            return _blob_bytes(out), message
        finally:
            for item in (err, out, res, obj, blob):
                _release(item)

    def compile(self, module):
        """LLVM IR text -> validated, signed DXBC container."""
        encoded, warning = self._operation(module.encode(), assemble=True)
        need(not warning, "DXC assembly warning: " + warning)
        signed, warning = self._operation(encoded, assemble=False)
        need(not warning and signed[4:20] != bytes(16), "DXC validation failed: " + warning)
        return signed

    def dump(self, data):
        key = sha(data)
        if key not in self.dumps:
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "program.bin"
                path.write_bytes(data)
                result = subprocess.run([str(self.folder / "dxc.exe"), "-dumpbin", str(path)],
                                        capture_output=True, timeout=60)
            need(result.returncode == 0 and not result.stderr and 0 < len(result.stdout) <= 8_000_000,
                 "DXC disassembly failed: " + result.stderr.decode("utf-8", "replace"))
            self.dumps[key] = result.stdout.decode().replace("\r\n", "\n")
        return self.dumps[key]


def dxbc_parts(data):
    need(len(data) >= 32 and data[:4] == b"DXBC" and W(data, 24)[0] == len(data), "DXBC header")
    out = {}
    for i in range(W(data, 28)[0]):
        offset = W(data, 32 + 4 * i)[0]
        size = W(data, offset + 4)[0]
        need(offset + 8 + size <= len(data), "DXBC chunk bounds")
        out[data[offset:offset + 4].decode("ascii")] = data[offset + 8:offset + 8 + size]
    return out


# ---- Program transplant (the v62 rebase, analysis/v62-update-20261003/rebase/tools/rebase.py) ----

BODY = re.compile(r"^define void @(\w+)\(\) \{\n.*?^\}", re.M | re.S)
TOK = re.compile(r"%(\d+)\b")
SAFE = ("@dx.op.cbufferLoadLegacy", "extractvalue ")


def body(text):
    m = BODY.search(text)
    need(m, "disassembly has no entry function")
    return m[0], m[1]


def typed_module(dxc, program):
    """The program's executable body reinserted into its STAT typed module (as the builders did)."""
    original = dxc.dump(program)
    stat = dxc.dump(dxbc_parts(program)["STAT"])
    executable, function = body(original)
    module = stat[stat.index("target datalayout"):]
    need(module.count(f"declare void @{function}()") == 1 and module.count("!2 = !{i32 0, i32 0}") == 1,
         "unsupported STAT module framing")
    module = module.replace("!2 = !{i32 0, i32 0}", "!2 = !{i32 1, i32 7}")
    counters = re.search(r"^!dx.counters = !\{(!\d+)\}$", module, re.M)
    need(counters, "missing STAT counter metadata")
    module = re.sub(r"^!dx.counters = .*\n", "", module, flags=re.M)
    module = re.sub(r"^" + re.escape(counters[1]) + r" = .*\n", "", module, flags=re.M)
    refs = set(re.findall(r"!(\d+)", executable))
    following = 1 + max(map(int, re.findall(r"^!(\d+) =", module, re.M)))
    mapping = {k: str(following + i) for i, k in enumerate(sorted(refs, key=int))}
    for k, new in mapping.items():
        hint = re.search(r"^!" + k + r" = distinct !\{!" + k + r', !"dx.controlflow.hints", i32 ([12])\}$',
                         original, re.M)
        need(hint, f"unsupported executable metadata !{k}")
        module += f'\n!{new} = distinct !{{!{new}, !"dx.controlflow.hints", i32 {hint[1]}}}\n'
    executable = re.sub(r"!(\d+)", lambda m: "!" + mapping[m[1]], executable)
    return module.replace(f"declare void @{function}()", executable)


def norm(line):
    line = line.split(";", 1)[0].rstrip() if not line.startswith("; <label>") else line.split("; preds")[0].strip()
    return TOK.sub("%#", line)


def toks(line):
    return TOK.findall(line.split(";", 1)[0] if not line.startswith("; <label>") else line.split("; preds")[0])


def deftok(line):
    m = re.match(r"\s*%(\d+) = ", line) or re.match(r"; <label>:(\d+)", line)
    return m[1] if m else None


def optoks(line):
    t, d = toks(line), deftok(line)
    if d is not None and t and t[0] == d:
        t = t[1:]
    return t


def ssa_map(la, lb):
    na, nb = [norm(x) for x in la], [norm(x) for x in lb]
    ka = [re.sub(r"i1 (true|false)", "C", x) for x in na]
    kb = [re.sub(r"i1 (true|false)", "C", x) for x in nb]
    cand = {}
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ka, kb, autojunk=False).get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                cand[i1 + k] = j1 + k
        elif tag == "replace" and i2 - i1 == j2 - j1:
            for k in range(i2 - i1):
                if ka[i1 + k] == kb[j1 + k]:
                    cand[i1 + k] = j1 + k
    while True:
        dm = {}
        for i, j in cand.items():
            a, b = deftok(la[i]), deftok(lb[j])
            if (a is None) != (b is None):
                continue
            if a is not None:
                dm[a] = b
        bad = []
        for i, j in cand.items():
            oa, ob = optoks(la[i]), optoks(lb[j])
            if len(oa) != len(ob):
                bad.append(i)
                continue
            for a, b in zip(oa, ob):
                if a == "0" and b == "0":
                    continue
                if dm.get(a) != b:
                    bad.append(i)
                    break
        if not bad:
            break
        for i in bad:
            del cand[i]
    line = {i: (j if na[i] == nb[j] else ("changed", j)) for i, j in cand.items()}
    m = dict(dm)
    m.setdefault("0", "0")
    return line, m


def defs_of(lines):
    out = {}
    for i, line in enumerate(lines):
        m = re.match(r"\s*%(\d+) = ", line)
        if m:
            out[m[1]] = i
    return out


class Ctx:
    def __init__(self, la, m):
        self.la, self.m, self.da, self.made, self.materialized = la, m, defs_of(la), [], {}


def translate(line, ctx, prelude):
    def rename(mm):
        t = mm[1]
        if t in ctx.m:
            return "%" + ctx.m[t]
        if t in ctx.materialized:
            return ctx.materialized[t]
        need(t in ctx.da, f"unmapped %{t} in: {line.strip()}")
        src = ctx.la[ctx.da[t]]
        need(any(k in src for k in SAFE), f"unmapped %{t} defined by an unsafe instruction: {src.strip()}")
        name = "%rf.m" + t
        ctx.materialized[t] = name
        prelude.append("  " + name + " =" + translate(src.split("=", 1)[1], ctx, prelude))
        ctx.made.append(src.strip())
        return name
    if ";" in line and not line.lstrip().startswith("; <label>"):
        code, comment = line.split(";", 1)
        return TOK.sub(rename, code) + ";" + comment
    return TOK.sub(rename, line)


def anchor(line, i):
    v = line.get(i)
    if isinstance(v, int):
        return v
    for k in range(i - 1, -1, -1):
        v = line.get(k)
        if isinstance(v, int):
            return v + 1
        if isinstance(v, tuple):
            return v[1] + 1
    raise Fail(f"no aligned anchor before stock line {i}")


def transplant_body(ba, bv, bb):
    la, lv, lb = ba.split("\n"), bv.split("\n"), bb.split("\n")
    line, m = ssa_map(la, lb)
    ctx = Ctx(la, m)
    inserts, replaced = {}, {}
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, la, lv, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        prelude = []
        new = [translate(x, ctx, prelude) for x in lv[j1:j2]]
        if tag == "insert":
            inserts.setdefault(anchor(line, i1), []).extend(prelude + new)
        else:
            idx = []
            for i in range(i1, i2):
                need(isinstance(line.get(i), int), f"edited stock line {i} not exactly aligned: {la[i]}")
                idx.append(line[i])
            need(idx == list(range(idx[0], idx[0] + len(idx))), "edited block not contiguous in the new stock")
            replaced[idx[0]] = (len(idx), prelude + new)
    out, k = [], 0
    while k < len(lb):
        if k in inserts:
            out += inserts[k]
        if k in replaced:
            n, new = replaced[k]
            out += new
            k += n
        else:
            out.append(lb[k])
            k += 1
    return "\n".join(out), ctx


def material_exports(text):
    t = re.search(r"^%c_material_exports = type \{(.*)\}$", text, re.M)
    size = re.search(r'%c_material_exports\* undef, !"c_material_exports", i32 \d+, i32 \d+, i32 1, i32 (\d+), null',
                     text)
    ann = re.search(r"%c_material_exports undef, !(\d+)", text)
    row = re.search(r"^!" + ann[1] + r" = !\{i32 (\d+), (.*)\}$", text, re.M) if ann else None
    fields = []
    if row:
        for ref in re.findall(r"!(\d+)", row[2]):
            r = re.search(r"^!" + ref + r" = !\{(.*)\}$", text, re.M)[1]
            fields.append([re.search(r'!"(\w+)"', r)[1], r])
    return {"type": t[0] if t else None, "size": int(size[1]) if size else None, "fields": fields}


def extend_like(module, ea, ev):
    eb = material_exports(module)
    need((eb["type"], eb["size"], [f for f, _ in eb["fields"]]) ==
         (ea["type"], ea["size"], [f for f, _ in ea["fields"]]),
         "material exports layout differs between the old and new stock")
    module = module.replace(eb["type"], ev["type"])
    res = re.search(r'(%c_material_exports\* undef, !"c_material_exports", i32 \d+, i32 \d+, i32 1, i32 )(\d+)(, null)',
                    module)
    module = module[:res.start(2)] + str(ev["size"]) + module[res.end(2):]
    ann = re.search(r"%c_material_exports undef, !(\d+)", module)[1]
    row = re.search(r"^!" + ann + r" = !\{i32 (\d+), (.*)\}$", module, re.M)
    have = {f for f, _ in ea["fields"]}
    add = [r for f, r in ev["fields"] if f not in have]
    following = 1 + max(map(int, re.findall(r"^!(\d+) =", module, re.M)))
    refs = ", ".join(f"!{following + i}" for i in range(len(add)))
    module = module.replace(row[0], f'!{ann} = !{{i32 {ev["size"]}, {row[2]}, {refs}}}')
    for i, r in enumerate(add):
        module += f"\n!{following + i} = !{{{r}}}\n"
    return module


def cb_fields(module):
    """struct name -> {offset: field} from dx.typeAnnotations rows."""
    out = {}
    for st, ref in re.findall(r"%(?:hostlayout\.)?([\w.]+) undef, !(\d+)", module):
        row = re.search(r"^!" + ref + r" = !\{i32 \d+, (.*)\}$", module, re.M)
        if not row:
            continue
        fields = {}
        for r2 in re.findall(r"!(\d+)", row[1]):
            fr = re.search(r"^!" + r2 + r' = !\{i32 6, !"(\w+)",(.*)\}$', module, re.M)
            if fr:
                fields[int(re.search(r"i32 3, i32 (\d+)", fr[2])[1])] = fr[1]
        out[st] = fields
    return out


def check_materialized(ctx, ma, mb):
    """A re-materialised stock load must read the same constant-buffer field in the new stock."""
    loads = {}
    for src in ctx.made:
        m = re.search(r"%(\d+) = call %dx.types.CBufRet.f32 @dx.op.cbufferLoadLegacy.f32\(i32 59, "
                      r"%dx.types.Handle %(\d+), i32 (\d+)\)", src)
        if m:
            loads[m[1]] = (m[2], int(m[3]))
    for src in ctx.made:
        ev = re.search(r"extractvalue %dx.types.CBufRet.f32 %(\d+), (\d+)", src)
        if not ev:
            continue
        handle, row = loads.get(ev[1], (None, None))
        need(handle is not None, "materialised extract of a load that was not materialised")
        offset = row * 16 + 4 * int(ev[2])
        rng = re.search(r"createHandle\(i32 57, i8 2, i32 (\d+),", ctx.la[ctx.da[handle]])
        need(rng, "materialised load from an unexpected handle")

        def struct_of(text):
            for mm in re.finditer(r"!\{i32 (\d+), %(?:hostlayout\.)?([\w.]+)\* undef, !\"\w*\", i32 \d+, i32 \d+, "
                                  r"i32 1, i32 \d+, null\}", text):
                if mm[1] == rng[1]:
                    return mm[2]
        sa, sb = struct_of(ma), struct_of(mb)
        fa, fb = cb_fields(ma).get(sa, {}), cb_fields(mb).get(sb, {})
        need(fa.get(offset) and fa.get(offset) == fb.get(offset) and sa == sb,
             f"materialised field mismatch {sa}:{fa.get(offset)} vs {sb}:{fb.get(offset)} at {offset}")


def rebase_program(dxc, program, exports, v, b):
    """Transplant the edit (stock body -> payload v) onto the new stock program b."""
    tv, tb = dxc.dump(v), dxc.dump(b)
    bv, fv = body(tv)
    bb, fb = body(tb)
    ba = "\n".join(line_unpatch(bv.split("\n"), program["stock_body"]))
    need(sha(ba.encode()) == program["stock_body_sha256"], "stock body does not reconstruct from the recipe")
    need(fv == fb == program["function"], f"entry point changed ({program['function']} -> {fb})")
    mb = typed_module(dxc, b)
    ha, hv = re.findall(r"!\d+", ba), re.findall(r"!\d+", bv)
    need(len(ha) == len(hv), "hint metadata count changed")
    hm = dict(zip(hv, ha))
    bv = re.sub(r"!\d+", lambda x: hm[x[0]], bv)
    newbody, ctx = transplant_body(ba, bv, bb)
    if ctx.made:
        check_materialized(ctx, typed_module(dxc, v), mb)
    ea, ev = exports[program["stock_exports"]], material_exports(tv)
    if (ea["type"], ea["size"], ea["fields"]) != (ev["type"], ev["size"], ev["fields"]):
        mb = extend_like(mb, ea, ev)
    for d in re.findall(r"^declare .*$", tv, re.M):
        name = re.search(r"@[\w.]+", d)[0]
        if name not in mb and name + "(" in newbody:
            mb += "\n" + d + "\n"
    exb, _ = body(mb)
    hints = dict(zip(re.findall(r"!\d+", bb), re.findall(r"!\d+", exb)))
    need(not set(re.findall(r"!\d+", newbody)) - set(hints), "new metadata references in the body")
    newbody = re.sub(r"!\d+", lambda x: hints.get(x[0], x[0]), newbody)
    out = dxc.compile(mb.replace(exb, newbody))
    return out, {"stock_changed": bb != ba, "materialised": len(ctx.made)}


# ---- Material streams ----

def stream(data):
    head = W(data, 0, 7)
    version, mo, ms, so, ss, to, ts = head
    need(version in KNOWN_VERSIONS, f"material version {version} is new; check the format before adding it")
    need(mo == 28, "material envelope changed")
    out = {"version": version, "template": data[mo:mo + ms]}
    if so == NONE:
        need(ss == 0 and to == NONE and ts == 0 and 28 + ms == len(data), "material envelope changed")
        return out
    need(so == 28 + ms and (to == NONE or to == so + ss), "material envelope changed")
    s = data[so:so + ss]
    h = W(s, 0, 12)
    need(h[0] == SHADER_VERSION, f"shader version {h[0]} is new; check the format before adding it")
    out.update(shader=h, ctx=s[48:h[4]], cond=s[h[4]:h[6]], dep=s[h[6]:h[8]], group=s[h[8]:h[8] + h[9]],
               gap=s[h[8] + h[9]:h[10]], dev=s[h[10]:h[10] + h[11]], pad=s[h[10] + h[11]:h[5]], defaults=s[h[5]:])
    out["tail"] = data[to:to + ts] if to != NONE else None
    return out


def device_units(dev):
    """Inter-frame segments and framed program units (envelope, frame, kind, size, key)."""
    found, i = [], 0
    while (i := dev.find(b"\x8c\x06", i)) != -1:
        if i >= 8:
            env, flen = W(dev, i - 8, 2)
            if env == 1 and i + flen + 16 <= len(dev):
                kind, _, key = struct.unpack_from("<IIQ", dev, i + flen)
                if kind == 5 and murmur64(dev[i:i + flen]) == key:
                    found.append((i - 8, i + flen + 16))
                    i += flen
                    continue
        i += 2
    segments, units, p = [], [], 0
    for a, b in found:
        segments.append(dev[p:a])
        units.append(dev[a:b])
        p = b
    segments.append(dev[p:])
    return segments, units


def unit_program(unit, oodle):
    flen = W(unit, 4)[0]
    frame = unit[8:8 + flen]
    _, size = W(unit, 8 + flen, 2)
    if len(frame) - 5 == size and int.from_bytes(frame[2:5], "big") + 1 == size:
        return frame[5:]
    out = oodle.decompress(frame, size)
    need(len(out) == size, "Kraken decoded length mismatch")
    return out


def wrap_program(program):
    need(len(program) < 1 << 18, "program too large for a stored frame")
    frame = b"\x8c\x06" + (len(program) - 1).to_bytes(3, "big") + program
    return words([1, len(frame)]) + frame + words([5, len(program)]) + struct.pack("<Q", murmur64(frame))


def default_rows(data):
    count = W(data, 4)[0]
    need(W(data, 0)[0] == 0 and count <= 4096, "shader defaults prefix")
    rows, p = [], 8 + 12 * count
    for i in range(count):
        name, size, offset = W(data, 8 + 12 * i, 3)
        need(size in (1, 2, 3, 4) and offset == p, "shader defaults bounds")
        rows.append((name, data[p:p + 4 * size]))
        p += 4 * size
    need(not any(data[p:]) and len(data) - p <= 15, "shader defaults padding")
    return rows


def defaults_bytes(rows):
    offset, table, values = 8 + 12 * len(rows), b"", b""
    for name, value in rows:
        table += words([name, len(value) // 4, offset])
        values += value
        offset += len(value)
    return words([0, len(rows)]) + table + values


class Cur:
    def __init__(self, data):
        self.data, self.p = data, 0

    def w(self, n=1):
        v = W(self.data, self.p, n)
        self.p += 4 * n
        return list(v)

    def table(self, width):
        return [self.w(width) for _ in range(self.w()[0])]

    def read(self, n):
        v = self.data[self.p:self.p + n]
        need(len(v) == n, "registration buffer truncated")
        self.p += n
        return v


def parse_groups(data):
    c, groups = Cur(data), []
    for _ in range(c.w()[0]):
        key, alloc = c.w(2)
        res = c.table(4)
        bufs = []
        for _ in range(c.w()[0]):
            d = c.table(5)
            size, off = c.w(2)
            bufs.append((tuple(map(tuple, d)), size, off))
        assoc = c.table(7)
        tech = c.read(17 * c.w()[0])
        groups.append({"key": key, "alloc": alloc, "res": tuple(map(tuple, res)), "bufs": bufs,
                       "assoc": tuple(map(tuple, assoc)), "tech": tech, "trailer": c.read(8)})
    need(c.p == len(data), "registration buffer not exhausted")
    return groups


def groups_bytes(groups):
    out = words([len(groups)])
    for g in groups:
        out += words([g["key"], g["alloc"], len(g["res"])]) + b"".join(words(r) for r in g["res"])
        out += words([len(g["bufs"])])
        for d, size, off in g["bufs"]:
            out += words([len(d)]) + b"".join(words(r) for r in d) + words([size, off])
        out += words([len(g["assoc"])]) + b"".join(words(r) for r in g["assoc"])
        out += words([len(g["tech"]) // 17]) + g["tech"] + g["trailer"]
    return out


def _jsonable(value):
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, (tuple, list)):
        return [_jsonable(x) for x in value]
    return value


def _tupled(value):
    return tuple(_tupled(x) for x in value) if isinstance(value, list) else value


def groups_patch(gv, ga):
    """[[group, field, buffer or None, stock value]] where the stock registration buffer differs."""
    v, a = parse_groups(gv), parse_groups(ga)
    need(len(v) == len(a), "payload changed the registration group count")
    out = []
    for i, (x, y) in enumerate(zip(v, a)):
        for k in ("key", "alloc", "res", "assoc", "tech", "trailer"):
            if x[k] != y[k]:
                out.append([i, k, None, _jsonable(y[k])])
        need(len(x["bufs"]) == len(y["bufs"]), "payload changed a registration buffer count")
        out += [[i, "bufs", j, _jsonable(q)] for j, (p, q) in enumerate(zip(x["bufs"], y["bufs"])) if p != q]
    need(groups_unpatch(gv, out) == ga, "registration buffer patch round trip")
    return out


def groups_unpatch(gv, patch):
    groups = parse_groups(gv)
    for i, k, j, value in patch:
        if k in ("tech", "trailer"):
            groups[i][k] = bytes.fromhex(value)
        elif k == "bufs":
            groups[i]["bufs"][j] = _tupled(value)
        else:
            groups[i][k] = _tupled(value)
    return groups_bytes(groups)


def pick(a, v, b, what):
    if a == v:
        return b
    if a == b or v == b:
        return v
    raise Fail(f"{what}: changed by both RainbowFlame and the game")


def merge_groups(ga, gv, gb):
    a, v, b = parse_groups(ga), parse_groups(gv), parse_groups(gb)
    need([g["key"] for g in a] == [g["key"] for g in v] == [g["key"] for g in b], "registration groups changed")
    out = []
    for x, y, z in zip(a, v, b):
        g = {k: pick(x[k], y[k], z[k], f"group {x['key']:08x} {k}") for k in
             ("key", "alloc", "res", "assoc", "tech", "trailer")}
        need(len(x["bufs"]) == len(y["bufs"]) == len(z["bufs"]), "registration buffer count changed")
        g["bufs"] = [pick(p, q, r, f"group {x['key']:08x} buffer {i}")
                     for i, (p, q, r) in enumerate(zip(x["bufs"], y["bufs"], z["bufs"]))]
        out.append(g)
    data = groups_bytes(out)
    need(groups_bytes(b) == gb and groups_bytes(v) == gv, "registration buffer round trip")
    return data


def merge_words(a, v, b, what):
    if a == v:
        return b
    if a == b:
        return v
    need(len(a) == len(v) == len(b), f"{what}: changed by both sides with different lengths")
    dv = [i for i in range(len(a)) if a[i] != v[i]]
    db = {i for i in range(len(a)) if a[i] != b[i]}
    for i in dv:
        need(not any(j in db for j in range(i - 3, i + 4)), f"{what}: byte {i} changed by both sides")
    out = bytearray(b)
    for i in dv:
        out[i] = v[i]
    return bytes(out)


def exports_key(value, table):
    key = sha(json.dumps(value, sort_keys=True).encode())[:16]
    need(table.setdefault(key, value) == value, "export layout key collision")
    return key


def capture_stream(a, v, oodle, dxc, programs, exports):
    sa, sv = stream(a), stream(v)
    need(sa["version"] == sv["version"], "payload and stock material versions differ")
    need(("shader" in sa) == ("shader" in sv), "payload and stock differ in having shaders")
    entry = {"template": rpatch(sv["template"], sa["template"])}
    if "shader" not in sa:
        return entry
    for k in ("ctx", "cond", "dep", "gap"):
        need(sa[k] == sv[k], f"payload changed the shader {k} section")
    for i in (0, 1, 2, 3, 6, 7):
        need(sa["shader"][i] == sv["shader"][i], f"payload changed shader header word {i}")
    need(sa["tail"] == sv["tail"], "payload changed the tail section")
    entry["group"] = groups_patch(sv["group"], sa["group"])
    entry["defaults"] = rpatch(defaults_bytes(default_rows(sv["defaults"])),
                               defaults_bytes(default_rows(sa["defaults"])))
    ga, ua = device_units(sa["dev"])
    gv, uv = device_units(sv["dev"])
    need(len(ua) == len(uv), "payload and stock frame counts differ")
    entry["segments"] = {str(i): rpatch(y, x) for i, (x, y) in enumerate(zip(ga, gv)) if x != y}
    entry["frames"] = {}
    for i, (x, y) in enumerate(zip(ua, uv)):
        if x == y:
            continue
        pa, pv = unit_program(x, oodle), unit_program(y, oodle)
        key = sha(pv)
        ba, fa = body(dxc.dump(pa))
        bv, fv = body(dxc.dump(pv))
        need(fa == fv, "edited program changed its entry point")
        ma = typed_module(dxc, pa)
        row = {"function": fa, "stock_body_sha256": sha(ba.encode()),
               "stock_body": line_patch(bv.split("\n"), ba.split("\n")),
               "stock_exports": exports_key(material_exports(ma), exports)}
        need("\n".join(line_unpatch(bv.split("\n"), row["stock_body"])) == ba, "stock body patch round trip")
        need(programs.setdefault(key, row) == row, f"program {key[:12]} has two different stock bodies")
        entry["frames"][str(i)] = key
    return entry


def rebuild_stream(v, b, entry, recipe, oodle, dxc, cache, stats):
    sv, sb = stream(v), stream(b)
    ta = unpatch(sv["template"], entry["template"])
    template = pick(ta, sv["template"], sb["template"], "material template")
    if "shader" not in sv:
        need("shader" not in sb, "the stock material gained shaders")
        return words([sb["version"], 28, len(template), NONE, 0, NONE, 0]) + template
    need("shader" in sb, "the stock material lost its shaders")
    group = merge_groups(groups_unpatch(sv["group"], entry["group"]), sv["group"], sb["group"])
    gv, uv = device_units(sv["dev"])
    gb, ub = device_units(sb["dev"])
    need(len(uv) == len(ub), f"frame count changed ({len(uv)} -> {len(ub)})")
    ga = [unpatch(x, entry["segments"].get(str(i))) for i, x in enumerate(gv)]
    dev = b""
    for i in range(len(uv)):
        dev += merge_words(ga[i], gv[i], gb[i], f"device segment {i}")
        key = entry["frames"].get(str(i))
        if key is None:
            dev += ub[i]
            continue
        pv, pb = unit_program(uv[i], oodle), unit_program(ub[i], oodle)
        cached = (key, sha(pb))
        if cached not in cache:
            try:
                cache[cached] = rebase_program(dxc, recipe["programs"][key], recipe["exports"], pv, pb)
            except Fail as exc:
                raise Fail(f"frame {i}: {exc}") from None
        out, row = cache[cached]
        stats["programs"] += 1
        stats["stock_changed"] += row["stock_changed"]
        dev += wrap_program(out)
    dev += merge_words(ga[-1], gv[-1], gb[-1], "device tail segment")
    dv = default_rows(sv["defaults"])
    da = default_rows(unpatch(defaults_bytes(dv), entry["defaults"]))
    defaults = defaults_bytes(pick(da, dv, default_rows(sb["defaults"]), "shader defaults"))
    h = list(sb["shader"])
    need(not any(sb["gap"]) and len(sb["gap"]) == (-(h[8] + h[9])) % 4, "registration gap profile")
    need(not any(sb["pad"]) and len(sb["pad"]) == (-(h[10] + h[11])) % 4, "device padding profile")
    h[9] = len(group)
    gap = bytes((-(h[8] + h[9])) % 4)
    h[10] = h[8] + h[9] + len(gap)
    h[11] = len(dev)
    pad = bytes((-(h[10] + h[11])) % 4)
    h[5] = h[10] + h[11] + len(pad)
    shader = words(h) + sb["ctx"] + sb["cond"] + sb["dep"] + group + gap + dev + pad
    shader += defaults + bytes((-(len(shader) + len(defaults))) % 16)
    tail = sb["tail"]
    so = 28 + len(template)
    return words([sb["version"], 28, len(template), so, len(shader),
                  so + len(shader) if tail is not None else NONE, len(tail or b"")]) + template + shader + (tail or b"")


# ---- Bundles ----

def read_bundle(data, oodle):
    layout = bundle8.parse(data)
    parts, left = [], layout.length
    for block in layout.blocks:
        want = min(bundle8.CHUNK, left)
        parts.append(block[:want] if len(block) == bundle8.CHUNK else oodle.decompress(block)[:want])
        left -= want
    raw = b"".join(parts)
    count = W(data, 8)[0]
    index = [struct.unpack_from("<QQI", data, 268 + 20 * i) for i in range(count)]
    records, p = [], 0
    for t, n, mode in index:
        rt, rn, vc, z = struct.unpack_from("<QQII", raw, p)
        need((rt, rn) == (t, n), "bundle index and records disagree")
        q, desc = p + 24, []
        for _ in range(vc):
            desc.append(struct.unpack_from("<IBIBI", raw, q))
            q += 14
        values = []
        for _, _, bs, _, ts in desc:
            values.append((raw[q:q + bs], raw[q + bs:q + bs + ts]))
            q += bs + ts
        records.append({"type": t, "name": n, "mode": mode, "z": z, "desc": desc, "vars": values})
        p = q
    need(p == len(raw), "bundle records do not fill the stream")
    return {"block": data[12:268], "records": records}


def record_bytes(r):
    out = struct.pack("<QQII", r["type"], r["name"], len(r["desc"]), r["z"])
    for (k, f1, bs, f2, ts), (x, y) in zip(r["desc"], r["vars"]):
        need(len(x) == bs and len(y) == ts, "record descriptor and data disagree")
        out += struct.pack("<IBIBI", k, f1, bs, f2, ts)
    return out + b"".join(x + y for x, y in r["vars"])


def bundle_stored(block, records):
    """A format-8 bundle with stored chunks (compressed afterwards by bundle8.pack / pack_exact)."""
    raw = b"".join(record_bytes(r) for r in records)
    prefix = bundle8.MAGIC + words([len(records)]) + block + b"".join(
        struct.pack("<QQI", r["type"], r["name"], r["mode"]) for r in records)
    chunks = [raw[i:i + bundle8.CHUNK] for i in range(0, len(raw), bundle8.CHUNK)]
    chunks[-1] += bytes(bundle8.CHUNK - len(chunks[-1]))
    layout = bundle8.Layout(prefix, [bundle8.CHUNK] * len(chunks), b"", len(raw), [b""] * len(chunks), chunks)
    return bundle8.build(layout, chunks)


def key_of(r):
    return f"{r['type']:016x}:{r['name']:016x}"


def swaps_between(old, new, width, names=None):
    """[[offset, old hex, new hex]] covering every differing byte with `width`-byte identifiers.

    With `names` (known new identifiers) the windows are their occurrences in `new`; otherwise each
    window starts at the next differing byte.
    """
    need(len(old) == len(new), "record size changed")
    diff = [i for i in range(len(old)) if old[i] != new[i]]
    if names is None:
        starts, covered = [], -1
        for i in diff:
            if i >= covered:
                starts.append(i)
                covered = i + width
    else:
        starts = [o for o in range(len(new) - width + 1) if int.from_bytes(new[o:o + width], "little") in names]
    need(all(s + width <= len(old) for s in starts) and
         all(b - a >= width for a, b in zip(starts, starts[1:])), "identifier windows overlap")
    need(set(diff) <= {s + k for s in starts for k in range(width)}, "edit is not a set of identifier swaps")
    return [[s, old[s:s + width].hex(), new[s:s + width].hex()] for s in starts if old[s:s + width] != new[s:s + width]]


def apply_swaps(data, swaps, what):
    """Swap identifiers at their offsets; on a changed record, by unique occurrence of the old value."""
    out = bytearray(data)
    for offset, a, v in swaps:
        old, new = bytes.fromhex(a), bytes.fromhex(v)
        if out[offset:offset + len(old)] != old:
            hits = [m.start() for m in re.finditer(re.escape(old), bytes(out))]
            need(len(hits) == 1, f"{what}: identifier {old.hex()} found {len(hits)} times, expected once")
            offset = hits[0]
        out[offset:offset + len(old)] = new
    return bytes(out)


def capture_bundle(stock, payload, oodle):
    a, v = read_bundle(stock, oodle), read_bundle(payload, oodle)
    need(a["block"] == v["block"], "payload changed the bundle header block")
    need([key_of(r) for r in a["records"]] == [key_of(r) for r in v["records"]], "payload changed the record list")
    edits = {}
    for x, y in zip(a["records"], v["records"]):
        if x == y:
            continue
        need(x["desc"] == y["desc"] and x["z"] == y["z"] and x["mode"] == y["mode"] and len(x["vars"]) == 1 and
             x["vars"][0][1] == y["vars"][0][1], "payload record differs beyond its data")
        edits[key_of(x)] = swaps_between(x["vars"][0][0], y["vars"][0][0], 4)
    return {"records": edits}


def rebuild_bundle(payload, stock, entry, oodle):
    v, b = read_bundle(payload, oodle), read_bundle(stock, oodle)
    out = []
    for r in b["records"]:
        swaps = entry["records"].get(key_of(r))
        if swaps is not None:
            r = dict(r, vars=[(apply_swaps(r["vars"][0][0], swaps, key_of(r)), r["vars"][0][1])])
        out.append(r)
    need(set(entry["records"]) <= {key_of(r) for r in b["records"]}, "an edited record is gone from the stock bundle")
    return bundle8.pack_exact(bundle_stored(b["block"], out), oodle, stock)


def capture_host(stock, payload, sources, oodle):
    a, v = read_bundle(stock, oodle), read_bundle(payload, oodle)
    n = len(a["records"])
    need(a["block"] == v["block"] and v["records"][:n] == a["records"], "host package stock records changed")
    rf = {r["name"] for r in v["records"][n:] if r["type"] == MATERIAL}
    added = []
    for r in v["records"][n:]:
        if r["type"] == MATERIAL:
            added.append({"record": key_of(r)})
            continue
        need(r["type"] == PARTICLE and len(r["vars"]) == 1, "unexpected host record type")
        data = r["vars"][0][0]
        best = []
        for path, bundle in sources.items():
            for s in bundle["records"]:
                if s["type"] != PARTICLE or s["desc"] != r["desc"] or s["vars"][0][1] != r["vars"][0][1]:
                    continue
                try:
                    best.append((path, s, swaps_between(s["vars"][0][0], data, 8, rf)))
                except Fail:
                    continue
        need(len(best) == 1, f"clone {key_of(r)} matches {len(best)} stock particles, expected one")
        path, s, swaps = best[0]
        need(s["z"] == r["z"] and s["mode"] == r["mode"], "clone header differs from its source")
        added.append({"record": key_of(r), "source": path, "source_record": key_of(s), "swaps": swaps})
    return {"added": added}


def rebuild_host(payload, stock, entry, sources, oodle):
    v, b = read_bundle(payload, oodle), read_bundle(stock, oodle)
    by_key = {key_of(r): r for r in v["records"]}
    out = list(b["records"])
    stock_keys = {key_of(r) for r in out}
    for row in entry["added"]:
        r = by_key[row["record"]]
        need(row["record"] not in stock_keys, f"the stock host package now has {row['record']}")
        if "source" in row:
            src = {key_of(s): s for s in sources[row["source"]]["records"]}.get(row["source_record"])
            need(src is not None, f"clone source {row['source_record']} is gone from {row['source']}")
            need(src["desc"] == r["desc"] and src["vars"][0][1] == r["vars"][0][1], "clone source layout changed")
            data = apply_swaps(src["vars"][0][0], row["swaps"], row["source_record"])
            r = dict(r, vars=[(data, r["vars"][0][1])])
        out.append(r)
    # The payload keeps the stock header block (checked when recording), so the new stock's is used.
    return bundle8.pack(bundle_stored(b["block"], out), oodle)


# ---- Recipe: origins of the 152 preset streams ----

def material_path(r):
    return "bundle/" + r["vars"][0][0].split(b"\0")[0].decode()


def find_origins(game, payload_host, stock_host, sources, oodle):
    """Each data/rf preset stream -> the stock material it was cloned from.

    Cloned particles name custom materials where the stock particle named stock ones; custom child
    materials name custom parents where the stock child named stock parents. Both are followed.
    """
    v, a = read_bundle(payload_host, oodle), read_bundle(stock_host, oodle)
    names = {}
    for bundle in [a] + list(sources.values()):
        for r in bundle["records"]:
            if r["type"] == MATERIAL:
                names.setdefault(r["name"], set()).add(material_path(r))
    rf = {r["name"]: material_path(r) for r in v["records"][len(a["records"]):] if r["type"] == MATERIAL}
    origin = {}

    def link(new, old):
        paths = names.get(old, set())
        need(len(paths) == 1, f"stock material {old:016x} resolves to {len(paths)} streams")
        stock = next(iter(paths))
        need(origin.setdefault(rf[new], stock) == stock, f"{rf[new]} has two stock origins")

    for row in capture_host(stock_host, payload_host, sources, oodle)["added"]:
        for _, old, new in row.get("swaps", ()):
            link(int.from_bytes(bytes.fromhex(new), "little"), int.from_bytes(bytes.fromhex(old), "little"))
    pending = list(origin)
    while pending:
        path = pending.pop()
        data, base = payload("payload/direct/" + path[len("bundle/"):]), stock(game, origin[path])
        for name in rf:
            for m in re.finditer(re.escape(struct.pack("<Q", name)), data):
                before = len(origin)
                link(name, struct.unpack_from("<Q", base, m.start())[0])
                if len(origin) > before:
                    pending.append(rf[name])
    need(set(origin) == set(rf.values()), "some preset streams have no stock origin")
    return origin


# ---- Whole payload ----

def load(path):
    need(path.is_file(), f"{path} is missing")
    return path.read_bytes()


def stock(game, rel):
    if OVERLAY is not None and (OVERLAY / rel).is_file():
        return (OVERLAY / rel).read_bytes()
    return load(game / rel)


def payload(rel):
    return load(PAYLOAD / rel)


def capture(game, redirects, virtual, oodle, dxc):
    """The recipe for the payload as it is now, against the installed stock it was built from."""
    for r in redirects:
        need(OVERLAY is not None or sha(load(game / r["stock"])) == r["sha256"],
             f"{r['stock']} does not match its pin; the recipe must be recorded against the payload's own stock")
    sources = {p: read_bundle(stock(game, p), oodle) for p in SOURCES}
    files, programs, exports = {}, {}, {}
    host = next(r for r in redirects if r["stock"] == HOST)
    origins = find_origins(game, payload(host["file"]), stock(game, HOST), sources, oodle)
    targets = [(r["file"], r["stock"]) for r in redirects]
    targets += [(virtual["dir"] + "/" + Path(p).name, o) for p, o in sorted(origins.items())]
    need(sorted(Path(f).name for f, _ in targets if f.startswith(virtual["dir"])) ==
         sorted(p.name for p in (PAYLOAD / virtual["dir"]).iterdir()), "data/rf holds files the recipe does not know")
    for file, origin in targets:
        a, v = stock(game, origin), payload(file)
        try:
            if origin == HOST:
                entry = capture_host(a, v, sources, oodle)
            elif bundle8.is_bundle(a):
                entry = capture_bundle(a, v, oodle)
            else:
                entry = capture_stream(a, v, oodle, dxc, programs, exports)
        except Fail as exc:
            raise Fail(f"{file}: {exc}") from None
        files[file] = {"origin": origin, "origin_sha256": sha(a), "payload_sha256": sha(v)} | entry
    return {"note": "Generated by rebuild_payload.py; the payload plus this recipe reconstruct the stock it was "
                    "built from.", "files": files, "programs": programs, "exports": exports}


def rebuild(game, recipe, oodle, dxc):
    sources = {p: read_bundle(stock(game, p), oodle) for p in SOURCES}
    outputs, report, cache = {}, [], {}
    for file, entry in recipe["files"].items():
        v, b = payload(file), load(game / entry["origin"])
        need(sha(v) == entry["payload_sha256"], f"{file} changed since the recipe was recorded; record it again")
        stats = {"programs": 0, "stock_changed": 0}
        try:
            if entry["origin"] == HOST:
                out = rebuild_host(v, b, entry, sources, oodle)
            elif "records" in entry:
                out = rebuild_bundle(v, b, entry, oodle)
            else:
                out = rebuild_stream(v, b, entry, recipe, oodle, dxc, cache, stats)
        except Fail as exc:
            raise Fail(f"{file} (from {entry['origin']}): {exc}") from None
        outputs[file] = out
        report.append({"file": file, "origin": entry["origin"], "origin_changed": sha(b) != entry["origin_sha256"],
                       "origin_sha256": sha(b), "output_sha256": sha(out), "unchanged": out == v} | stats)
    return outputs, report


def pin(game, redirects):
    """`reforge add` every redirect again (it re-hashes the stock), then restore the keys it drops."""
    reforge = WORKSPACE / "tools/reforge/reforge.cmd"
    for r in redirects:
        subprocess.run([str(reforge), "add", str(MOD), r["stock"], "--file", r["file"], "--game", str(game)],
                       check=True, capture_output=True)
    path = MOD / "reforge.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    extra = {r["stock"]: {k: v for k, v in r.items() if k not in ("stock", "file", "sha256")} for r in redirects}
    for r in data["redirects"]:
        r.update(extra.get(r["stock"], {}))
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def save_recipe(recipe, path):
    """One compact line per file, program and export layout, so a new recipe diffs by file."""
    def section(name):
        rows = [f" {json.dumps(k)}: {json.dumps(v, sort_keys=True, separators=(',', ':'))}"
                for k, v in sorted(recipe[name].items())]
        return f'"{name}": {{\n' + ",\n".join(rows) + "\n}"
    text = "{\n" + f'"note": {json.dumps(recipe["note"])},\n' + ",\n".join(
        section(n) for n in ("exports", "files", "programs")) + "\n}\n"
    need(json.loads(text) == recipe, "recipe serialisation round trip")
    path.write_text(text, encoding="utf-8", newline="\n")


def main():
    global PAYLOAD, OVERLAY
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--game", type=Path, default=GAME)
    parser.add_argument("--out", type=Path, help="write the rebuilt files under this folder (payload paths) instead "
                        "of the mod; nothing is pinned and the recipe is kept")
    parser.add_argument("--record", action="store_true", help="only record the recipe from the payload and the "
                        "installed stock (which must match the pins)")
    parser.add_argument("--stock", type=Path, help="with --record: older stock files laid out like the game's "
                        "(bundle/...), used instead of the game's where present; the pins are not checked")
    parser.add_argument("--payload", type=Path, help="read payload/ from this folder instead of the mod "
                        "(e.g. an older release); with a rebuild it needs --out")
    parser.add_argument("--recipe", type=Path, default=RECIPE, help="recipe file to record or use")
    args = parser.parse_args()
    need(not args.stock or args.record, "--stock only applies to --record")
    need(not args.payload or args.record or args.out, "a rebuild from another --payload needs --out")
    PAYLOAD, OVERLAY = args.payload or MOD, args.stock
    oodle = bundle8.Oodle(args.game / "binaries/oo2core_9_win64.dll")
    dxc = Dxc()
    source = json.loads((MOD / "reforge.json").read_text(encoding="utf-8"))
    redirects = source["redirects"]
    (virtual,) = source["virtual_dirs"]
    if args.record:
        save_recipe(capture(args.game, redirects, virtual, oodle, dxc), args.recipe)
        print(f"recipe recorded: {args.recipe}")
        return
    need(args.recipe.is_file(), "no recipe; run with --record while the stock still matches the pins")
    recipe = json.loads(args.recipe.read_text(encoding="utf-8"))
    need({r["file"] for r in redirects} <= set(recipe["files"]), "reforge.json redirects differ from the recipe")
    outputs, report = rebuild(args.game, recipe, oodle, dxc)
    print(f"{len(outputs)} files rebuilt; {sum(r['origin_changed'] for r in report)} stock origins changed; "
          f"{sum(r['unchanged'] for r in report)} identical to the payload they were rebuilt from; "
          f"{sum(r['programs'] for r in report)} programs transplanted "
          f"({sum(r['stock_changed'] for r in report)} onto changed stock)")
    folder = MOD / "analysis" / ("rebuild-" + sha("".join(r["origin_sha256"] for r in report).encode())[:12])
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "report.json").write_text(json.dumps({"dxc": dxc.version, "game": str(args.game), "out": str(args.out),
                                                    "files": report}, indent=1) + "\n", encoding="utf-8")
    print(f"report: {folder / 'report.json'}")
    root = args.out or MOD
    for file, data in outputs.items():
        path = root / file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    if args.out:
        print(f"files written under {args.out}; reforge.json and the recipe not changed")
        return
    pin(args.game, redirects)
    redirects = json.loads((MOD / "reforge.json").read_text(encoding="utf-8"))["redirects"]
    save_recipe(capture(args.game, redirects, virtual, oodle, dxc), args.recipe)
    subprocess.run([str(WORKSPACE / "tools/reforge/reforge.cmd"), "build", str(MOD), "--game", str(args.game)],
                   check=True)
    print("pinned the stock hashes, recorded a new recipe and rebuilt the Reforge manifest")


if __name__ == "__main__":
    try:
        main()
    except Fail as exc:
        sys.exit(f"rebuild_payload: {exc}")
