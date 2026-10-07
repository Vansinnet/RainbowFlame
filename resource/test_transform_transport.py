"""Execute authored control DXIL under float32 math; native matrix upload is not mocked as proof."""
import ast
import json
import math
import random
import re
import struct
from pathlib import Path

import audit_transform_transport as audit
import diagnostic_surface as ds
import surface_shader
import transform_surface as author
from test_build import f32
from test_live import execute as staff_execute
import live_shader

OUT = author.OUT
CANDIDATE = OUT / 'candidate-v2'


def matrix(hue, brightness, speed, rainbow, transpose=False, normalize=False):
    x = f32((hue + 361 * rainbow + 1) / 65536)
    y = f32((brightness + 1) / 16384)
    z = f32((speed + 1) / 262144)
    w = f32(math.sqrt(1 - x*x - y*y - z*z))
    if normalize:
        n = f32(math.sqrt(f32(f32(x*x) + f32(y*y) + f32(z*z) + f32(w*w))))
        x, y, z, w = (f32(v/n) for v in (x, y, z, w))
    mul = lambda a, b: f32(a*b)
    add = lambda a, b: f32(a+b)
    sub = lambda a, b: f32(a-b)
    m = [[sub(1, mul(2, add(mul(y,y), mul(z,z)))), mul(2, sub(mul(x,y),mul(z,w))), mul(2, add(mul(x,z),mul(y,w)))],
         [mul(2, add(mul(x,y),mul(z,w))), sub(1, mul(2, add(mul(x,x),mul(z,z)))), mul(2, sub(mul(y,z),mul(x,w)))],
         [mul(2, sub(mul(x,z),mul(y,w))), mul(2, add(mul(y,z),mul(x,w))), sub(1, mul(2, add(mul(x,x),mul(y,y))))]]
    return [list(row) + [0] for row in (zip(*m) if transpose else m)]


def execute(fragment, initial, matrix_rows, particle_handle, material_handle, marker):
    values = dict(initial)
    buffers = {}
    def value(token):
        if token.startswith('%'):
            return values[token]
        if token.startswith('0x'):
            return struct.unpack('>d', bytes.fromhex(token[2:]))[0]
        return float(token)
    for line in fragment.splitlines():
        name, op = line.strip().split(' = ')
        if '@dx.op.cbufferLoadLegacy' in op:
            match = re.search(r'%dx.types.Handle (%\w+), i32 (\d+)\)', op)
            assert match
            handle, register = match[1], int(match[2])
            if handle == particle_handle:
                assert 1 <= register <= 3
                buffers[name] = matrix_rows[register - 1]
            else:
                assert handle == material_handle and register == 6
                buffers[name] = [0, 0, 0, marker]
            continue
        if op.startswith('extractvalue'):
            match = re.search(r' (%[\w.]+), (\d+)$', op)
            assert match
            result = buffers[match[1]][int(match[2])]
        elif op.startswith('select'):
            match = re.fullmatch(r'select i1 (%[\w.]+), float ([^,]+), float (.+)', op)
            assert match
            result = value(match[2] if values[match[1]] else match[3])
        elif op.startswith('and i1'):
            a, b = op[7:].split(', ')
            result = bool(values[a] and values[b])
        elif op.startswith('fcmp'):
            match = re.fullmatch(r'fcmp (\w+) float ([^,]+), (.+)', op)
            assert match
            a, b = value(match[2]), value(match[3])
            result = {'oeq': a == b, 'ogt': a > b, 'oge': a >= b, 'ole': a <= b, 'olt': a < b}[match[1]]
        elif op.startswith('call'):
            args = [value(t) for t in re.findall(r', float ([^,) ]+)', op)]
            match = re.search(r'i32 (\d+)', op)
            assert match
            code = int(match[1])
            if code == 35: result = max(args)
            elif code == 22: result = args[0] - math.floor(args[0])
            elif code == 6: result = abs(args[0])
            elif code == 7: result = min(1, max(0, args[0]))
            elif code == 24: result = math.sqrt(args[0])
            elif code == 26: result = round(args[0]) if math.isfinite(args[0]) else args[0]
            else: raise AssertionError(op)
        else:
            code, args = op.split(' float ')
            a, b = map(value, args.split(', '))
            if code == 'fmul': result = a*b
            elif code == 'fadd': result = a+b
            elif code == 'fsub': result = a-b
            elif code == 'fdiv': result = a/b
            else: raise AssertionError(op)
        values[name] = f32(result)
    return values


def main():
    old, shaders, repack, _, _ = ds.build.dependencies()
    _, parser = old.prior()
    audit_rows = json.loads((OUT / 'matrix-loads.json').read_text())
    assert len(audit_rows) == 36
    for row in audit_rows:
        path = audit.ROOT / row['path']
        assert audit.sha(path.read_bytes()) == row['sha256']
        folder = ds.B1 if path.is_relative_to(ds.B1) else ds.E1
        assert path.read_bytes() == ds.sealed(folder, path.relative_to(folder).as_posix())
        stage, buffers = audit.inspect(path.read_text())
        assert stage == row['stage'] and buffers == row['buffers']
        for buffer in row['buffers']:
            if buffer['name'] == 'c_particle_system_per_frame':
                assert not set(range(16, 80)).intersection(buffer['accessed_bytes'])
            if buffer['name'] == 'c_per_object':
                assert not set(range(0, 128)).intersection(buffer['accessed_bytes'])
    manifest = json.loads((CANDIDATE / 'candidate.json').read_text())
    for key in ('parent', 'child'):
        assert ds.sha((CANDIDATE / manifest[key]['file']).read_bytes()) == manifest[key]['sha256']
    parent = (CANDIDATE / manifest['parent']['file']).read_bytes()
    baseline = ds.sealed(ds.E1, 'enemy-4ab784b71d6e9eb6.EXPERIMENTAL.material')
    before, _, bd, bs, bt = ds.layout(baseline)
    after, _, ad, ass, at = ds.layout(parent)
    assert parent[28:ass] == baseline[28:bs] and parent[at:] == baseline[bt:]
    assert ds.er.default_table(before[bd:]) == ds.er.default_table(after[ad:])
    pre_size = struct.unpack_from('<I', before, 40)[0]
    assert struct.unpack_from('<I', after, 40)[0] == pre_size
    a, b = bytearray(before[:pre_size]), bytearray(after[:pre_size])
    for offset in (20, 44):
        a[offset:offset+4] = b[offset:offset+4] = bytes(4)
    assert a == b
    malformed = 0
    for bad in (parent[:-1], bytes(4)+parent[4:], parent[:16]+struct.pack('<I', 0xffffffff)+parent[20:]):
        try:
            ds.layout(bad)
        except (ValueError, struct.error):
            malformed += 1
        else:
            raise AssertionError('Malformed material accepted')
    body_recovery = 0
    for i in ds.SELECTED:
        original = ds.sealed(ds.B1, f'program-{i:02d}.ll.txt').decode()
        previous = ds.sealed(ds.E1, f'enemy/program-{i:02d}.input.ll').decode()
        module = (CANDIDATE / f'program-{i:02d}.input.ll').read_text()
        profile = surface_shader.inspect(original)
        injected = author.controls(profile['buffers']['c_particle_system_per_frame'])
        old_prefix = re.search(r'^  %rf\.cycle = .*?^  %rf\.speed = extractvalue[^\n]*\n', previous, re.M | re.S)
        assert old_prefix and module.count(injected) == 1
        assert module.replace(injected, old_prefix[0]) == previous
        body_recovery += 1
    # Independently interpret the actual emitted module, not the authoring helper.
    module = (CANDIDATE / 'program-01.input.ll').read_text()
    block = re.search(r'^  %rf\.hsv = .*?^  %rf\.b = [^\n]*\n', module, re.M | re.S)
    assert block
    profile = surface_shader.inspect(ds.sealed(ds.B1, 'program-01.ll.txt').decode())
    rgb_names = profile['ramp_samples'][0]['rgb']
    staff = live_shader.instructions(('%r', '%g', '%b'), '%time', shaders, True)
    rng = random.Random(20260919)
    cases = [(h, 200, 4000, r) for h in range(361) for r in (0, 1)]
    cases += [(360, b, 4000, 1) for b in range(201)]
    cases += [(360, 200, s, 1) for s in range(1, 4001)]
    cases += [(rng.randrange(361), rng.randrange(201), rng.randrange(1,4001), rng.randrange(2)) for _ in range(1000)]
    maximum_error, checked = 0, 0
    for n, (h, b, s, rainbow) in enumerate(cases):
        rgb = tuple(map(f32, ((0.1, 0.5, 2) if n % 3 else (0, 0, 0))))
        time = f32((0, 1, 123.456, 3600.5, .625/(s/1000))[n % 5])
        initial = dict(zip(rgb_names, rgb))
        initial['%enemy.time'] = time
        expected = staff_execute(staff, rgb, time, (h/360, 1, b/100, 1), (rainbow, s/1000))
        for transpose in (False, True):
            values = execute(block[0], initial, matrix(h, b, s, rainbow, transpose, n % 2 == 0),
                profile['buffers']['c_particle_system_per_frame'], profile['buffers']['c_material_exports'], -1)
            assert values['%rf.enable'] == 1 and values['%rf.rainbow'] == rainbow
            assert values['%rf.hue'] == f32(h/360)
            assert values['%rf.brightness'] == f32(b/100)
            assert values['%rf.speed'] == f32(s/1000)
            assert tuple(values['%rf.'+c] for c in 'rgb') == expected
            maximum_error = max(maximum_error, *(values[f'%pose.{axis}.distance'] for axis in 'xyz'))
            checked += 1
    identity = [[1,0,0,0], [0,1,0,0], [0,0,1,0]]
    for marker, mat in ((-1, identity), (0, matrix(270,100,204,0)),
                        (-1, [[0]*4 for _ in range(3)]), (-1, [[float('nan')]*4 for _ in range(3)])):
        rgb = (f32(.125), f32(.5), f32(2))
        values = execute(block[0], {**dict(zip(rgb_names, rgb)), '%enemy.time': 8}, mat,
                         profile['buffers']['c_particle_system_per_frame'], profile['buffers']['c_material_exports'], marker)
        assert values['%rf.enable'] == 0 and tuple(values['%rf.'+c] for c in 'rgb') == rgb
    for path in (Path(__file__), OUT.parents[1] / 'mods/active/RainbowFlame/resource/transform_surface.py',
                 OUT.parents[1] / 'mods/active/RainbowFlame/resource/audit_transform_transport.py'):
        ast.parse(path.read_text(), filename=str(path))
    result = dict(float32_shader_cases=checked, exact_staff_output_matches=checked,
                  maximum_integer_grid_error=maximum_error, tolerance=1/64,
                  original_module_recoveries=body_recovery, invalid_or_unmarked_stock_cases=4,
                  original_programs_audited=36, no_original_world_matrix_consumers=True,
                  malformed_material_rejections=malformed, template_defaults_bindings_raytracing_preserved=True,
                  native_matrix_upload_tested=False, runtime_tested=False)
    report = OUT / 'shader-tests-v2.json'
    text = json.dumps(result, indent=2) + '\n'
    if report.exists():
        assert report.read_text() == text
    else:
        with report.open('x', encoding='utf-8') as file:
            file.write(text)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
