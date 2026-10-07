"""Offline surface-DXIL analysis. Does not serialize or install game resources."""
import re
from typing import TypedDict

import live_shader

EXPORTS = ((live_shader.HSV, 3, 96, 16), (live_shader.CYCLE, 1, 112, 8))


class RampSample(TypedDict):
    sample: str
    rgb: list[str]
    instruction: str


class Profile(TypedDict):
    stage: str
    buffers: dict[str, str]
    ramp_samples: list[RampSample]
    ramp_texture_indices: list[str]
    ramp_sampler_indices: list[str]


def definitions(text):
    return {key: value.split(';', 1)[0].rstrip()
            for key, value in re.findall(r'^  (%[\w.]+) = (.+)$', text, re.M)}


def ancestors(value, definitions):
    pending, seen = [value], set()
    while pending:
        value = pending.pop()
        if value in seen:
            continue
        seen.add(value)
        pending.extend(v for v in re.findall(r'%[\w.]+', definitions.get(value, ''))
                       if v in definitions)
    return seen


def inspect(text) -> Profile:
    text = text.replace('\r\n', '\n')
    entry = re.search(r'define void @(\w+)\(', text)
    if not entry:
        raise ValueError('Entry point missing')
    stage = entry[1]
    defs = definitions(text)
    buffers = {}
    for name, binding in re.findall(r'^; (\w+)\s+cbuffer\s+NA\s+NA\s+CB\d+\s+cb(\d+)\s+1$', text, re.M):
        handles = [key for key, value in defs.items() if re.fullmatch(
            r'call %dx.types.Handle @dx.op.createHandle\(i32 57, i8 2, i32 \d+, i32 '
            + binding + r', i1 false\)', value)]
        if not handles:
            continue
        if len(handles) != 1:
            raise ValueError('Cbuffer handle: '+name)
        buffers[name] = handles[0]
    material = buffers.get('c_material_exports')
    if material:
        for name, offset in (('__BINDLESS_SAMPLER_texture_map_c6ad88db', 8),
                             ('__BINDLESS_TEX2D_texture_map_c6ad88db', 48)):
            if not re.search(r';\s+uint2? '+name+r';\s*; Offset:\s*'+str(offset)+r'\s*$', text, re.M):
                raise ValueError('Ramp reflection field moved: '+name)

    def loads(handle, register, component):
        rows = [key for key, value in defs.items() if value ==
                f'call %dx.types.CBufRet.i32 @dx.op.cbufferLoadLegacy.i32(i32 59, %dx.types.Handle {handle}, i32 {register})']
        return [key for key, value in defs.items() if any(value ==
                f'extractvalue %dx.types.CBufRet.i32 {row}, {component}' for row in rows)]

    indices = loads(material, 3, 0) if material else []
    samplers = loads(material, 0, 2) if material else []
    samples: list[RampSample] = []
    for key, value in defs.items():
        if '@dx.op.sample' not in value:
            continue
        handles = re.findall(r'%dx.types.Handle (%[\w.]+)', value)
        if len(handles) != 2:
            raise ValueError('Sample handle count')
        texture_path, sampler_path = (ancestors(h, defs) for h in handles)
        if not (texture_path.intersection(indices) and sampler_path.intersection(samplers)):
            continue
        rgb = []
        for channel in range(3):
            extracts = [k for k, v in defs.items() if v ==
                        f'extractvalue %dx.types.ResRet.f32 {key}, {channel}']
            if len(extracts) != 1:
                raise ValueError('Ramp RGB extraction')
            rgb.append(extracts[0])
        samples.append({'sample': key, 'rgb': rgb, 'instruction': value})
    texture_handles = [key for key, value in defs.items()
                       if '@dx.op.createHandle(i32 57, i8 0,' in value
                       and ancestors(key, defs).intersection(indices)]
    for handle in texture_handles:
        consumers = [key for key, value in defs.items()
                     if re.search(re.escape(handle)+r'(?![\w.])', value)]
        if any(key not in [s['sample'] for s in samples]
               and not defs[key].startswith('call float @dx.op.calculateLOD.f32(i32 81,')
               for key in consumers):
            raise ValueError('Unsupported ramp texture consumer: '+str((handle, consumers)))
    return {'stage': stage, 'buffers': buffers, 'ramp_samples': samples,
            'ramp_texture_indices': indices, 'ramp_sampler_indices': samplers}


def module_for(original, stat, shaders, include_original=False):
    original, stat = original.replace('\r\n', '\n'), stat.replace('\r\n', '\n')
    profile = inspect(original)
    if profile['stage'] != 'ps_main' or len(profile['ramp_samples']) != 1:
        raise ValueError('Expected one evidenced ramp sample in a pixel program')
    body = re.search(r'^define void @ps_main\(\) \{\n.*?^\}', original, re.M | re.S)
    if not body:
        raise ValueError('Pixel body missing')
    executable = body[0]
    module = stat[stat.index('target datalayout'):]
    if module.count('declare void @ps_main()') != 1:
        raise ValueError('STAT entry mismatch')
    module = module.replace('!2 = !{i32 0, i32 0}', '!2 = !{i32 1, i32 7}')
    counters = re.search(r'^!dx.counters = !\{(!\d+)\}$', module, re.M)
    if not counters:
        raise ValueError('STAT counters missing')
    module = re.sub(r'^!dx.counters = .*\n', '', module, flags=re.M)
    module = re.sub(r'^'+re.escape(counters[1])+r' = .*\n', '', module, flags=re.M)
    refs = sorted(set(re.findall(r'!(\d+)', executable)), key=int)
    next_id = 1+max(map(int, re.findall(r'^!(\d+) =', module, re.M)))
    hints = {key: str(next_id+i) for i, key in enumerate(refs)}
    for key, new in hints.items():
        hint = re.search(r'^!'+key+r' = distinct !\{!'+key+r', !"dx.controlflow.hints", i32 ([12])\}$', original, re.M)
        if not hint:
            raise ValueError('Unsupported executable metadata')
        module += f'\n!{new} = distinct !{{!{new}, !"dx.controlflow.hints", i32 {hint[1]}}}\n'
    executable = re.sub(r'!(\d+)', lambda m: '!'+hints[m[1]], executable)
    old_type = re.search(r'^%c_material_exports = type \{(.*)\}$', module, re.M)
    resource = re.search(r'(%c_material_exports\* undef, !"c_material_exports", i32 0, i32 \d+, i32 1, i32 )(\d+)(, null)', module)
    annotation = re.search(r'%c_material_exports undef, (!(\d+))', module)
    if not old_type or not resource or not annotation or int(resource[2]) != 84:
        raise ValueError('Surface reflection layout')
    module = module[:resource.start(2)]+'120'+module[resource.end(2):]
    # Offset 80 is particle_max_size. New exports start at the next free float4.
    module = module.replace(old_type[0], old_type[0][:-2]+', <4 x float>, <2 x float> }')
    row = re.search(r'^'+re.escape(annotation[1])+r' = !\{i32 (\d+), (.*)\}$', module, re.M)
    if not row or int(row[1]) != 84:
        raise ValueError('Surface annotation layout')
    next_id = 1+max(map(int, re.findall(r'^!(\d+) =', module, re.M)))
    module = module.replace(row[0], f'{annotation[1]} = !{{i32 120, {row[2]}, !{next_id}, !{next_id+1}}}')
    for i, (name, _, offset, _) in enumerate(EXPORTS):
        module += f'\n!{next_id+i} = !{{i32 6, !"{name}", i32 3, i32 {offset}, i32 7, i32 9}}\n'
    rgb = profile['ramp_samples'][0]['rgb']
    material = profile['buffers']['c_material_exports']
    viewport = profile['buffers']['global_viewport']
    fragment = (f'  %enemy.clock = call %dx.types.CBufRet.f32 @dx.op.cbufferLoadLegacy.f32(i32 59, %dx.types.Handle {viewport}, i32 90)\n'
                '  %enemy.time = extractvalue %dx.types.CBufRet.f32 %enemy.clock, 0\n')
    controls = live_shader.instructions(rgb, '%enemy.time', shaders, include_original, False)
    for name, register in (('hsv', 6), ('cycle', 7)):
        controls = re.sub(r'(%rf\.'+name+r' = call .*?%dx.types.Handle )%\w+, i32 \d+\)',
                          lambda m: m[1]+material+f', i32 {register})', controls)
    fragment += controls
    lines = executable.splitlines(keepends=True)
    positions = [i for i, line in enumerate(lines) if any(line.startswith('  '+r+' =') for r in rgb)]
    if len(positions) != 3:
        raise ValueError('RGB insertion boundary')
    boundary = max(positions)+1
    suffix = ''.join(lines[boundary:])
    for source, channel in zip(rgb, 'rgb'):
        suffix, count = re.subn(re.escape(source)+r'(?![\w.])', '%rf.'+channel, suffix)
        if count != 1:
            raise ValueError('Expected one ramp-channel consumer')
    executable = ''.join(lines[:boundary])+fragment+suffix
    module = module.replace('declare void @ps_main()', executable)
    if 'declare float @dx.op.binary.f32(' not in module:
        module += '\ndeclare float @dx.op.binary.f32(i32, float, float) #0\n'
    return module
