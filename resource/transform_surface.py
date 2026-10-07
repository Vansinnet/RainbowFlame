"""Offline rotation-transport candidate; native pose-to-cbuffer delivery is untested."""
import argparse
import json
from pathlib import Path
import re
import struct

import build
import diagnostic_surface as ds
import export_resources as er
import shader_tables
import surface_shader

ROOT = build.WORKSPACE
OUT = ROOT / 'docs/analysis-rainbow-transform-transport-20260919-t1'
RUNTIME = ROOT / 'mods/active/RainbowFlame/scripts/mods/RainbowFlame/RainbowFlame.lua'
PARENT = '4ab784b71d6e9eb6.TRANSFORM.material'
CHILD = '612e95b62b8e2aeb.TRANSFORM.material'


def controls(handle):
    lines = []
    for i in range(3):
        lines.append(f'  %pose.row{i} = call %dx.types.CBufRet.f32 @dx.op.cbufferLoadLegacy.f32(i32 59, %dx.types.Handle {handle}, i32 {i+1})')
        for j in range(3):
            lines.append(f'  %pose.m{i}{j} = extractvalue %dx.types.CBufRet.f32 %pose.row{i}, {j}')
    lines += [
        '  %pose.trace0 = fadd float %pose.m00, %pose.m11',
        '  %pose.trace1 = fadd float %pose.trace0, %pose.m22',
        '  %pose.trace2 = fadd float %pose.trace1, 1.000000e+00',
        '  %pose.trace = call float @dx.op.binary.f32(i32 35, float %pose.trace2, float 1.000000e+00)',
        '  %pose.root = call float @dx.op.unary.f32(i32 24, float %pose.trace)',
        '  %pose.denominator = fmul float %pose.root, 2.000000e+00',
        '  %pose.marker = extractvalue %dx.types.CBufRet.f32 %rf.hsv, 3',
        '  %pose.marked = fcmp oeq float %pose.marker, -1.000000e+00',
    ]
    for axis, a, b, scale, maximum in (
            ('x', '12', '21', 65536, 722),
            ('y', '20', '02', 16384, 201),
            ('z', '01', '10', 262144, 4001)):
        lines += [
            f'  %pose.{axis}.difference = fsub float %pose.m{a}, %pose.m{b}',
            f'  %pose.{axis}.absolute = call float @dx.op.unary.f32(i32 6, float %pose.{axis}.difference)',
            f'  %pose.{axis}.quaternion = fdiv float %pose.{axis}.absolute, %pose.denominator',
            f'  %pose.{axis}.code = fmul float %pose.{axis}.quaternion, {float(scale):.6e}',
            f'  %pose.{axis}.rounded = call float @dx.op.unary.f32(i32 26, float %pose.{axis}.code)',
            f'  %pose.{axis}.low = fcmp oge float %pose.{axis}.rounded, 1.000000e+00',
            f'  %pose.{axis}.high = fcmp ole float %pose.{axis}.rounded, {float(maximum):.6e}',
            f'  %pose.{axis}.range = and i1 %pose.{axis}.low, %pose.{axis}.high',
            f'  %pose.{axis}.error = fsub float %pose.{axis}.code, %pose.{axis}.rounded',
            f'  %pose.{axis}.distance = call float @dx.op.unary.f32(i32 6, float %pose.{axis}.error)',
            f'  %pose.{axis}.grid = fcmp olt float %pose.{axis}.distance, 1.562500e-02',
            f'  %pose.{axis}.valid = and i1 %pose.{axis}.range, %pose.{axis}.grid',
            f'  %pose.{axis}.safe = select i1 %pose.{axis}.valid, float %pose.{axis}.rounded, float 1.000000e+00',
            f'  %pose.{axis}.value = fsub float %pose.{axis}.safe, 1.000000e+00',
        ]
    lines += [
        '  %pose.xy = and i1 %pose.x.valid, %pose.y.valid',
        '  %pose.xyz = and i1 %pose.xy, %pose.z.valid',
        '  %pose.valid = and i1 %pose.xyz, %pose.marked',
        '  %pose.rainbow = fcmp oge float %pose.x.value, 3.610000e+02',
        '  %pose.hue.rainbow = fsub float %pose.x.value, 3.610000e+02',
        '  %pose.hue = select i1 %pose.rainbow, float %pose.hue.rainbow, float %pose.x.value',
        '  %rf.hue = fdiv float %pose.hue, 3.600000e+02',
        '  %rf.brightness = fdiv float %pose.y.value, 1.000000e+02',
        '  %rf.enable = select i1 %pose.valid, float 1.000000e+00, float 0.000000e+00',
        '  %rf.rainbow = select i1 %pose.rainbow, float 1.000000e+00, float 0.000000e+00',
        '  %rf.speed = fdiv float %pose.z.value, 1.000000e+03',
    ]
    return '\n'.join(lines) + '\n'


def module_for(source, original):
    profile = surface_shader.inspect(original)
    handle = profile['buffers']['c_particle_system_per_frame']
    # Keep the existing material load solely as the child-specific transport marker.
    pattern = r'^  %rf\.cycle = .*?^  %rf\.speed = extractvalue[^\n]*\n'
    modified, count = re.subn(pattern, controls(handle), source, flags=re.M | re.S)
    if count != 1 or '%rf.opacity =' in modified:
        raise ValueError('Unexpected e1 control prefix')
    return modified


def mark_child(data, old):
    version, begin, length, shader, shader_size, tail, tail_size = struct.unpack_from('<7I', data)
    assert (version, begin, shader, shader_size, tail, tail_size) == (61, 28, 0xffffffff, 0, 0xffffffff, 0)
    assert begin + length == len(data)
    model = er.material_template(data[begin:begin+length])
    assert er.serialize_material(model) == data[begin:begin+length]
    key = old.murmur64(b'rainbow_flame_hsv_enable') >> 32
    descriptor, = [d for d in model['descriptors'] if d[2] == key]
    assert descriptor[0] == 3 and descriptor[4] == 16
    offset = descriptor[3] + 12
    values = bytearray(model['values'])
    assert struct.unpack_from('<f', values, offset)[0] == 0
    struct.pack_into('<f', values, offset, -1)
    model['values'] = bytes(values)
    replacement = er.serialize_material(model)
    assert len(replacement) == length
    candidate = data[:begin] + replacement + data[begin+length:]
    assert sum(a != b for a, b in zip(candidate, data)) == 2
    return candidate, descriptor


def run(output):
    assert not output.exists() and output.parent.is_dir() and output.is_relative_to(ROOT / 'docs')
    parent = (ds.G1 / '4ab784b71d6e9eb6.EXPERIMENTAL.material').read_bytes()
    assert ds.sha(parent) == ds.PARENT_HASH
    assert parent == ds.sealed(ds.E1, 'enemy-4ab784b71d6e9eb6.EXPERIMENTAL.material')
    original_shader = ds.sealed(ds.B1, 'surface.shader43')
    original_report = json.loads(ds.sealed(ds.B1, 'decoded.json'))
    old, shaders, repack, reflection, checks = build.dependencies()
    prepare, parser = old.prior()
    dxc = prepare.Dxc()
    before = ds.walk(parent, original_shader, original_report, old, parser)
    output.mkdir()
    replacements, receipts = {}, []
    for row in before:
        i = row['index']
        stem = f'program-{i:02d}'
        expected = ds.sealed(ds.E1, 'enemy/' + stem + '.dxbc') if i in ds.SELECTED else ds.sealed(ds.B1, stem + '.dxbc')
        assert row['data'] == expected
        if i not in ds.SELECTED:
            continue
        source = ds.sealed(ds.E1, 'enemy/' + stem + '.input.ll').decode()
        original = ds.sealed(ds.B1, stem + '.ll.txt').decode()
        module = module_for(source, original)
        assembled, error = dxc.operation(module.encode(), assemble=True)
        assert not error, error
        signed, error = dxc.operation(assembled, assemble=False)
        assert not error and signed[4:20] != bytes(16), error
        ds.save(output, stem + '.input.ll', module.encode())
        ds.save(output, stem + '.dxbc', signed)
        reflected = reflection.dump(output / (stem + '.dxbc')).decode()
        ds.save(output, stem + '.ll.txt', reflected.encode())
        previous = ds.sealed(ds.E1, 'enemy/' + stem + '.ll.txt').decode()
        assert shader_tables.reflection_descriptors(previous, old.murmur64) == shader_tables.reflection_descriptors(reflected, old.murmur64)
        parts = lambda data: {c['tag']: data[c['offset']+8:c['offset']+8+c['size']] for c in parser.dxbc(data)}
        a, b = parts(expected), parts(signed)
        for tag in ('SFI0', 'ISG1', 'OSG1', 'PSV0'):
            assert a[tag] == b[tag], tag
        canonical = lambda text: build.canonical(re.sub(r', !dx.controlflow.hints !\d+', '', text), shaders)
        assert canonical(module) == canonical(reflected)
        ds.save(output, stem + '-STAT.program', b['STAT'])
        stat = reflection.dump(output / (stem + '-STAT.program')).decode()
        assert checks.count_instructions(reflected) == checks.counters(stat)
        replacements[i] = signed
        receipts.append(dict(index=i, sha256=ds.sha(signed), bindings_unchanged=True, dxc_valid=True,
                             executable_readback=True, stat_counters=True))
    assert tuple(replacements) == ds.SELECTED
    assert ds.repack_parent(parent, before, {}, old, repack) == parent
    candidate = ds.repack_parent(parent, before, replacements, old, repack)
    after = ds.walk(candidate, original_shader, original_report, old, parser)
    for a, b in zip(before, after):
        assert b['data'] == replacements.get(a['index'], a['data'])
        assert a['metadata'][16:] == b['metadata'][16:]
        if a['index'] not in ds.SELECTED:
            assert (a['frame'], a['metadata']) == (b['frame'], b['metadata'])
    assert ds.repack_parent(candidate, after, {i: before[i]['data'] for i in ds.SELECTED}, old, repack) == parent
    child = ds.sealed(ds.E1, 'enemy-612e95b62b8e2aeb.EXPERIMENTAL.material')
    child_candidate, marker = mark_child(child, old)
    ds.save(output, PARENT, candidate)
    ds.save(output, CHILD, child_candidate)
    manifest = dict(status='OFFLINE CANDIDATE; NATIVE ROTATION DELIVERY AND CULLING UNTESTED',
                    parent=dict(file=PARENT, sha256=ds.sha(candidate), baseline_sha256=ds.sha(parent)),
                    child=dict(file=CHILD, sha256=ds.sha(child_candidate), baseline_sha256=ds.sha(child), marker=marker),
                    programs=receipts, unchanged_programs=28, exact_reverse_roundtrip=True,
                    transport='unit quaternion encoded by source-supported World.move_particles rotation',
                    matrix='existing c_particle_system_per_frame, bytes 16..79, no original shader consumers',
                    runtime_observed=False, installed_writes=0)
    ds.save(output, 'candidate.json', (json.dumps(manifest, indent=2) + '\n').encode())
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--snapshot', action='store_true')
    cli.add_argument('--output', type=Path)
    args = cli.parse_args()
    if args.snapshot:
        data = RUNTIME.read_bytes()
        ds.save(OUT, 'RainbowFlame.before-transform.lua.reference', data)
        ds.save(OUT, 'runtime-baseline.json', (json.dumps(dict(path=str(RUNTIME.relative_to(ROOT)), sha256=ds.sha(data)), indent=2)+'\n').encode())
    else:
        assert args.output is not None
        run(args.output.resolve())
