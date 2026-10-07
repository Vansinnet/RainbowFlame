"""Offline exact-profile HSV shader builder. Never reads an installed game."""
import argparse
import importlib
import importlib.util
import json
import math
import re
import struct
from pathlib import Path
import sys

sys.dont_write_bytecode = True
if not __debug__:
    raise RuntimeError('Run without -O: inherited exact-profile checks require assertions')
WORKSPACE = Path(__file__).resolve().parents[4]
O1 = WORKSPACE / 'docs/analysis-flame-huecycle-build-20260918-o1'


def settings(hue: float=120, saturation: float=1, brightness: float=1, rainbow=True, speed=0.125, enabled=True):
    values = dict(hue=hue, saturation=saturation, brightness=brightness, speed=speed)
    for key, lower, upper in [('hue', 0, 360), ('saturation', 0, 1),
                              ('brightness', 0, 2), ('speed', 0.001, 4)]:
        value = values[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not lower <= value <= upper:
            raise ValueError(f'{key} must be finite in [{lower}, {upper}]')
    if type(rainbow) is not bool or type(enabled) is not bool:
        raise ValueError('rainbow and enabled must be booleans')
    return dict(values, rainbow=rainbow, enabled=enabled)


def dependencies():
    # Verify every imported o1 helper before executing it; inherited readers pin n1/j1.
    import hashlib
    seal_bytes = (O1 / 'SHA256SUMS.json').read_bytes()
    if hashlib.sha256(seal_bytes).hexdigest() != '7a88bc35ec52849cd6c415cbccc6bcd032b5896049138844c2e9a40b0fc750e7':
        raise ValueError('o1 manifest identity changed')
    for name, row in json.loads(seal_bytes).items():
        if Path(name).name != name:
            raise ValueError('unsafe seal path')
        data = (O1 / name).read_bytes()
        if len(data) != row['size'] or hashlib.sha256(data).hexdigest() != row['sha256']:
            raise ValueError('o1 input drift: ' + name)
    sys.path.insert(0, str(O1))
    old = importlib.import_module('investigate')
    shaders = importlib.import_module('build_shaders')
    repack = importlib.import_module('repack')
    reflection = importlib.import_module('inspect_reflection')
    spec = importlib.util.spec_from_file_location('rainbow_o1_checks', O1 / 'verify.py')
    assert spec is not None and spec.loader is not None
    checks = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checks)
    return old, shaders, repack, reflection, checks


def instructions(rgb, time, config, float_ir):
    r, g, b = rgb
    f = float_ir
    lines = [
        f'  %hc.maxrg = call float @dx.op.binary.f32(i32 35, float {r}, float {g})',
        f'  %hc.value = call float @dx.op.binary.f32(i32 35, float %hc.maxrg, float {b})',
        f'  %hc.scaled = fmul float {time}, {f(config["speed"] if config["rainbow"] else 0)}',
        f'  %hc.shifted = fadd float %hc.scaled, {f(config["hue"] / 360)}',
        '  %hc.phase = call float @dx.op.unary.f32(i32 22, float %hc.shifted)',
        f'  %hc.gain = fmul float %hc.value, {f(config["brightness"])}',
    ]
    for channel, offset in [('r', 0), ('g', 2/3), ('b', 1/3)]:
        n = '%hc.' + channel
        lines += [
            f'  {n}.offset = fadd float %hc.phase, {f(offset)}',
            f'  {n}.frac = call float @dx.op.unary.f32(i32 22, float {n}.offset)',
            f'  {n}.six = fmul float {n}.frac, 6.000000e+00',
            f'  {n}.center = fsub float {n}.six, 3.000000e+00',
            f'  {n}.abs = call float @dx.op.unary.f32(i32 6, float {n}.center)',
            f'  {n}.minus = fsub float {n}.abs, 1.000000e+00',
            f'  {n}.unit = call float @dx.op.unary.f32(i32 7, float {n}.minus)',
            f'  {n}.desat = fsub float {n}.unit, 1.000000e+00',
            f'  {n}.saturated = fmul float {n}.desat, {f(config["saturation"])}',
            f'  {n}.tint = fadd float {n}.saturated, 1.000000e+00',
            f'  {n} = fmul float {n}.tint, %hc.gain',
        ]
    return '\n'.join(lines) + '\n'


def module_for(stem, original, config, shaders):
    module = shaders.merged_module(stem, original, config['enabled'])
    if config['enabled']:
        rgb, time = (('%152', '%153', '%154'), '%156') if stem.startswith('a8') else (('%146', '%147', '%148'), '%150')
        previous = shaders.hue_instructions(rgb, time)
        if module.count(previous) != 1:
            raise ValueError('unexpected insertion point')
        module = module.replace(previous, instructions(rgb, time, config, shaders.float_ir))
    return module


def canonical(text, shaders):
    def constant(match):
        token = match.group()
        value = struct.unpack('>d', bytes.fromhex(token[2:]))[0] if token.startswith('0x') else float(token)
        return struct.pack('>f', value).hex()
    return [re.sub(r'0x[0-9A-Fa-f]{16}|-?\d+\.\d+e[+-]\d+', constant, line)
            for line in shaders.canonical_body(text)]


def build(output, config):
    config = settings(**config)
    # All generated outputs are new directories directly beneath docs.
    output = Path(output).resolve()
    if output.parent != WORKSPACE / 'docs' or not output.name.startswith('analysis-rainbow-flame-'):
        raise ValueError('output must be a new docs/analysis-rainbow-flame-* directory')
    if output.exists():
        raise ValueError('output already exists; use a new build directory')
    old, shaders, repack, reflection, checks = dependencies()
    prepare, parser = old.prior()
    dxc = prepare.Dxc()
    known = repack.known_frames()
    output.mkdir()
    rows = []

    def save(name, data):
        with (output / name).open('xb') as file:
            file.write(data)

    def chunks(data):
        return {c['tag']: data[c['offset']+8:c['offset']+8+c['size']] for c in parser.dxbc(data)}

    for info in repack.material_info():
        name = info['material']
        stem = name + '-second'
        original = repack.material_original(info)
        _, _, offset, size = repack.material_sections(original)
        original_shader = original[offset:offset+size]
        before = repack.parse_shader(original_shader, known)
        original_text = old.sealed(old.J1 / (stem + '.ll.txt'), old.J1).decode()
        module = module_for(stem, original_text, config, shaders)
        save(stem + '.input.ll', module.encode())
        assembled, assembly = dxc.operation(module.encode(), assemble=True)
        signed, validation = dxc.operation(assembled, assemble=False)
        assert not assembly and not validation and signed[4:20] != bytes(16)
        save(stem + '.dxbc', signed)
        text = reflection.dump(output / (stem + '.dxbc'))
        save(stem + '.ll.txt', text)
        parts = chunks(signed)
        save(stem + '-STAT.program', parts['STAT'])
        stat = reflection.dump(output / (stem + '-STAT.program'))
        save(stem + '-STAT.ll.txt', stat)
        assert shaders.reflection(text.decode()) == shaders.reflection(original_text)
        assert canonical(text.decode(), shaders) == canonical(module, shaders)
        assert checks.count_instructions(text.decode()) == checks.counters(stat.decode())
        original_parts = chunks(before['programs'][1]['data'])
        for tag in ['SFI0', 'ISG1', 'OSG1', 'PSV0']:
            assert parts[tag] == original_parts[tag], tag
        shader = repack.replace_ps(original_shader, signed, known)
        candidate = repack.replace_shader(original, shader)
        after = repack.parse_shader(shader, known)
        assert candidate[:16] == original[:16]
        assert candidate[24:offset] == original[24:offset]
        for i in [0, 2, 3]:
            assert after['programs'][i]['data'] == before['programs'][i]['data']
        save(name + '.material', candidate)
        save(name + '.shader43', shader)
        rows.append(dict(material=name, source_reference=info['stream_reference'],
                         original_sha256=old.sha(original), file=name + '.material',
                         sha256=old.sha(candidate), size=len(candidate),
                         counters=checks.count_instructions(text.decode()),
                         external_validation='passed', reflection_equal=True,
                         unchanged_other_programs=[0, 2, 3]))
    manifest = dict(status='OFFLINE STATIC PRESET; NO LIVE LUA BINDING; NOT DEPLOYED',
                    settings=config, speed_units='cycles per shader-time unit; seconds uncalibrated',
                    stock_ramp_compatible=True, stock_ramp_runtime_tested=False,
                    shared_material_scope=True, targets=rows)
    save('manifest.json', (json.dumps(manifest, indent=2) + '\n').encode())
    hashes = {p.name: dict(size=p.stat().st_size, sha256=old.sha(p.read_bytes())) for p in output.iterdir()}
    save('SHA256SUMS.json', (json.dumps(hashes, indent=2) + '\n').encode())
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--output', required=True)
    cli.add_argument('--hue', type=float, default=120)
    cli.add_argument('--saturation', type=float, default=1)
    cli.add_argument('--brightness', type=float, default=1)
    cli.add_argument('--speed', type=float, default=0.125)
    cli.add_argument('--fixed', action='store_true')
    cli.add_argument('--stock', action='store_true')
    args = cli.parse_args()
    build(args.output, settings(args.hue, args.saturation, args.brightness,
                               not args.fixed, args.speed, not args.stock))
