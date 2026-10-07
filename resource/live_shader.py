"""DXIL authoring for two new, explicitly named material exports.

Only stock RGB consumers change. Native material registration is validated
separately from DXC and remains an experimental resource-authoring contract.
"""
import re

import build

HSV = 'rainbow_flame_hsv_enable'
CYCLE = 'rainbow_flame_cycle'
EXPORTS = ((HSV, 3, 80, 16), (CYCLE, 1, 96, 8))


def extend_types(module):
    old_type = re.search(r'^%c_material_exports = type \{(.*)\}$', module, re.M)
    if not old_type:
        raise ValueError('Material buffer type missing')
    module = module.replace(old_type[0], old_type[0][:-2]+', <4 x float>, <2 x float> }')
    resource = re.search(r'(%c_material_exports\* undef, !"c_material_exports", i32 0, i32 \d+, i32 1, i32 )(\d+)(, null)', module)
    annotation = re.search(r'%c_material_exports undef, (!(\d+))', module)
    if not resource or not annotation or int(resource[2]) not in (72, 80):
        raise ValueError('Material reflection layout')
    module = module[:resource.start(2)]+'104'+module[resource.end(2):]
    row = re.search(r'^'+re.escape(annotation[1])+r' = !\{i32 (\d+), (.*)\}$', module, re.M)
    if not row:
        raise ValueError('Material annotation row')
    next_id = 1+max(map(int, re.findall(r'^!(\d+) =', module, re.M)))
    module = module.replace(row[0], f'{annotation[1]} = !{{i32 104, {row[2]}, !{next_id}, !{next_id+1}}}')
    for i, (name, _, offset, _) in enumerate(EXPORTS):
        module += f'\n!{next_id+i} = !{{i32 6, !"{name}", i32 3, i32 {offset}, i32 7, i32 9}}\n'
    return module


def instructions(rgb, time, shaders, include_original=False, apply_opacity=True):
    lines = [
        '  %rf.hsv = call %dx.types.CBufRet.f32 @dx.op.cbufferLoadLegacy.f32(i32 59, %dx.types.Handle %4, i32 5)',
        '  %rf.cycle = call %dx.types.CBufRet.f32 @dx.op.cbufferLoadLegacy.f32(i32 59, %dx.types.Handle %4, i32 6)',
    ]
    controls = ((0, 'hue'), (2, 'brightness'), (3, 'enable'))
    if apply_opacity:
        controls = ((0, 'hue'), (1, 'opacity'), (2, 'brightness'), (3, 'enable'))
    for i, name in controls:
        lines.append(f'  %rf.{name} = extractvalue %dx.types.CBufRet.f32 %rf.hsv, {i}')
    lines += [
        '  %rf.rainbow = extractvalue %dx.types.CBufRet.f32 %rf.cycle, 0',
        '  %rf.speed = extractvalue %dx.types.CBufRet.f32 %rf.cycle, 1',
        '  %rf.cycling = fcmp ogt float %rf.rainbow, 0.000000e+00',
        '  %rf.active = fcmp ogt float %rf.enable, 0.000000e+00',
    ]
    if apply_opacity:
        lines.append('  %rf.managed = fcmp one float %rf.enable, 0.000000e+00')
    lines += [
        '  %rf.rate = select i1 %rf.cycling, float %rf.speed, float 0.000000e+00',
        '  %rf.offset = select i1 %rf.cycling, float 0.000000e+00, float %rf.hue',
    ]
    fragment = build.instructions(rgb, time, build.settings(), shaders.float_ir)
    fragment = fragment.replace(shaders.float_ir(0.125), '%rf.rate')
    fragment = fragment.replace('float %hc.scaled, '+shaders.float_ir(120/360), 'float %hc.scaled, %rf.offset')
    fragment = fragment.replace('float %hc.value, '+shaders.float_ir(1), 'float %hc.value, %rf.brightness')
    if include_original:
        fragment = fragment.replace('  %hc.phase =', '  %rf.phase =')
        anchor = '  %rf.phase = call float @dx.op.unary.f32(i32 22, float %hc.shifted)\n'
        # Reserve a quarter-cycle at blue for a smooth trip to the sampled ramp
        # and back. Compress, rather than discard, the complete HSV wheel.
        phase = [
            '  %rf.pause.start = fsub float %rf.phase, 5.000000e-01',
            '  %rf.pause.scaled = fmul float %rf.pause.start, 4.000000e+00',
            '  %rf.pause = call float @dx.op.unary.f32(i32 7, float %rf.pause.scaled)',
            '  %rf.pause.length = fmul float %rf.pause, 2.500000e-01',
            '  %rf.wheel.short = fsub float %rf.phase, %rf.pause.length',
            '  %rf.wheel = fmul float %rf.wheel.short, '+shaders.float_ir(4/3),
            '  %hc.phase = select i1 %rf.cycling, float %rf.wheel, float %rf.phase',
            '  %rf.distance = fsub float %rf.phase, 6.250000e-01',
            '  %rf.distance.abs = call float @dx.op.unary.f32(i32 6, float %rf.distance)',
            '  %rf.distance.scaled = fmul float %rf.distance.abs, 8.000000e+00',
            '  %rf.triangle = fsub float 1.000000e+00, %rf.distance.scaled',
            '  %rf.weight = call float @dx.op.unary.f32(i32 7, float %rf.triangle)',
            '  %rf.weight.square = fmul float %rf.weight, %rf.weight',
            '  %rf.weight.twice = fmul float %rf.weight, 2.000000e+00',
            '  %rf.weight.factor = fsub float 3.000000e+00, %rf.weight.twice',
            '  %rf.smooth = fmul float %rf.weight.square, %rf.weight.factor',
            '  %rf.blend = select i1 %rf.cycling, float %rf.smooth, float 0.000000e+00',
            '  %rf.complement = fsub float 1.000000e+00, %rf.blend',
        ]
        if fragment.count(anchor) != 1:
            raise ValueError('Original-cycle phase anchor')
        fragment = fragment.replace(anchor, anchor+'\n'.join(phase)+'\n')
    lines.append(fragment.rstrip())
    for channel, source in zip('rgb', rgb):
        result = '%hc.'+channel
        if include_original:
            lines += [
                f'  %rf.{channel}.stock = fmul float {source}, %rf.brightness',
                f'  %rf.{channel}.native = fmul float %rf.{channel}.stock, %rf.blend',
                f'  %rf.{channel}.wheel = fmul float %hc.{channel}, %rf.complement',
                f'  %rf.{channel}.mixed = fadd float %rf.{channel}.native, %rf.{channel}.wheel',
            ]
            result = '%rf.'+channel+'.mixed'
        if apply_opacity:
            lines += [
                f'  %rf.{channel}.color = select i1 %rf.active, float {result}, float {source}',
                f'  %rf.{channel}.faded = fmul float %rf.{channel}.color, %rf.opacity',
                f'  %rf.{channel} = select i1 %rf.managed, float %rf.{channel}.faded, float {source}',
            ]
        else:
            lines.append(f'  %rf.{channel} = select i1 %rf.active, float {result}, float {source}')
    return '\n'.join(lines)+'\n'


def module_for(stem, original, stat, shaders, custom, include_original=False):
    original, stat = original.replace('\r\n','\n'), stat.replace('\r\n','\n')
    function = 'vs_main' if 'define void @vs_main' in original else 'ps_main'
    body = re.search(r'^define void @'+function+r'\(\) \{\n.*?^\}', original, re.M | re.S)
    if not body:
        raise ValueError('Program body missing')
    module = stat[stat.index('target datalayout'):]
    if module.count(f'declare void @{function}()') != 1:
        raise ValueError('STAT function mismatch')
    module = module.replace('!2 = !{i32 0, i32 0}', '!2 = !{i32 1, i32 7}')
    counters = re.search(r'^!dx.counters = !\{(!\d+)\}$', module, re.M)
    if not counters:
        raise ValueError('STAT counter metadata')
    module = re.sub(r'^!dx.counters = .*\n', '', module, flags=re.M)
    module = re.sub(r'^'+re.escape(counters[1])+r' = .*\n', '', module, flags=re.M)
    executable = body[0]
    # Executable and STAT modules use independent metadata numbering. Preserve
    # branch-hint nodes (including their self reference) under fresh IDs.
    refs = set(re.findall(r'!(\d+)', executable))
    next_hint = 1+max(map(int,re.findall(r'^!(\d+) =',module,re.M)))
    hint_map = {key:str(next_hint+i) for i,key in enumerate(sorted(refs,key=int))}
    for key in hint_map:
        hint = re.search(r'^!'+key+r' = distinct !\{!'+key+r', !"dx.controlflow.hints", i32 ([12])\}$',original,re.M)
        if not hint:
            raise ValueError('Unsupported executable metadata; do not discard it')
        new = hint_map[key]
        module += f'\n!{new} = distinct !{{!{new}, !"dx.controlflow.hints", i32 {hint[1]}}}\n'
    executable = re.sub(r'!(\d+)',lambda m:'!'+hint_map[m[1]],executable)
    if custom:
        if not re.search(r'%4 = call %dx.types.Handle @dx.op.createHandle\(i32 57, i8 2, i32 2, i32 2, i1 false\)', executable):
            raise ValueError('Expected material cbuffer handle missing')
        if not re.search(r'; c_material_exports\s+cbuffer\s+NA\s+NA\s+CB2\s+cb2\s+1', original):
            raise ValueError('Material handle does not match independent reflection')
        rgb, time, outputs = (('%152','%153','%154'), '%156', (190,191,192)) if stem.startswith('a8') else (('%146','%147','%148'), '%150', (184,185,186))
        anchor = f'  %{outputs[0]} = fmul fast float {rgb[0]}, %7'
        if executable.count(anchor) != 1:
            raise ValueError('RGB insertion point')
        executable = executable.replace(anchor, instructions(rgb,time,shaders,include_original)+anchor)
        for channel, source, target, gain in zip('rgb',rgb,outputs,(7,8,9)):
            executable = executable.replace(f'%{target} = fmul fast float {source}, %{gain}',
                                            f'%{target} = fmul fast float %rf.{channel}, %{gain}')
        module += '\ndeclare float @dx.op.binary.f32(i32, float, float) #0\n'
    module = module.replace(f'declare void @{function}()', executable)
    return extend_types(module)
