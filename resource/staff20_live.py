"""Exact retained 20b9 offline live-color authoring; never installs resources."""
import argparse
import copy
import json
from pathlib import Path
import re
import struct
import sys

sys.dont_write_bytecode = True
import build
import export_resources as exports
import live_shader
import shader_tables
import surface_shader
import surface_tables
import staff20_live_preflight as preflight

TARGETS = (1, 5, 9, 13)
EXPORTS = ((live_shader.HSV, 3, 112, 16), (live_shader.CYCLE, 1, 128, 8))
GROUP_KEYS = (4248073976, 3514040914, 2508369774, 2414443937)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def serialize_groups(groups):
    data = shader_tables.words([len(groups)])
    for g in groups:
        data += shader_tables.words([g['key'], g['allocation']])+shader_tables.table(g['resources'])
        data += shader_tables.words([len(g['buffers'])])
        for b in g['buffers']:
            data += shader_tables.table(b['descriptors'])+shader_tables.words([b['size'], b['allocation_offset']])
        data += shader_tables.table(g['associations'])+shader_tables.words([len(g['techniques'])//17])
        data += g['techniques']+g['trailer']
    require(preflight.group_probe(data) == groups, 'Group serialization readback')
    return data


def groups_for(data):
    groups = preflight.group_probe(data)
    require(tuple(g['key'] for g in groups) == GROUP_KEYS, 'Group identities')
    for g in groups:
        require(g['allocation'] == 400 and len(g['resources']) == 9 and len(g['associations']) == 6,
                'Group allocation/resource/association profile')
        require([(b['size'], b['allocation_offset']) for b in g['buffers']] ==
                [(1776,0), (400,0), (144,144), (112,288)], 'Buffer allocation profile')
        require(len(g['techniques']) == 34, 'Technique partition')
        for b in g['buffers']:
            for kind, elements, name, offset, width in b['descriptors']:
                require(name and kind <= 10 and offset+max(1,elements)*width <= b['size'], 'Descriptor extent')
                require(kind > 3 or (elements == 0 and width == 4*(kind+1)), 'Descriptor kind')
    require(serialize_groups(groups) == data, 'Registration byte identity roundtrip')
    return groups


def color_path(text):
    """Prove the exact sample -> extracts -> tint -> RGB output path."""
    defs = surface_shader.definitions(text)
    require('define void @ps_main()' in text, 'Not a pixel program')
    require(re.search(r'; c_material_exports\s+cbuffer\s+NA\s+NA\s+CB2\s+cb2\s+1', text), 'Material binding')
    require(defs.get('%4') == 'call %dx.types.Handle @dx.op.createHandle(i32 57, i8 2, i32 2, i32 2, i1 false)', 'Material handle')
    for field, offset in [('__BINDLESS_TEX2D_texture_map_fc5c271f',24),
                          ('__BINDLESS_SAMPLER_texture_map_fc5c271f',4)]:
        require(re.search(r';\s+uint2? '+field+r';\s*; Offset:\s*'+str(offset)+r'\s*$',text,re.M), 'Ramp field offset')
    require(defs.get('%67') == 'call %dx.types.CBufRet.i32 @dx.op.cbufferLoadLegacy.i32(i32 59, %dx.types.Handle %4, i32 1)', 'Ramp texture load')
    require(defs.get('%68') == 'extractvalue %dx.types.CBufRet.i32 %67, 2', 'Ramp texture index')
    require('%68' in surface_shader.ancestors('%70',defs), 'Ramp texture ancestry')
    require(defs.get('%49') == 'extractvalue %dx.types.CBufRet.i32 %48, 1', 'Ramp sampler index')
    require(defs.get('%48') == 'call %dx.types.CBufRet.i32 @dx.op.cbufferLoadLegacy.i32(i32 59, %dx.types.Handle %4, i32 0)', 'Ramp sampler load')
    require('%49' in surface_shader.ancestors('%51',defs), 'Ramp sampler ancestry')
    require(defs.get('%151') == 'call %dx.types.ResRet.f32 @dx.op.sample.f32(i32 60, %dx.types.Handle %70, %dx.types.Handle %51, float %144, float %144, float undef, float undef, i32 0, i32 0, i32 undef, float %150)', 'Color sample and shape UV')
    for channel, source, output, tint, store in zip(range(3), (152,153,154), (190,191,192), (7,8,9), (205,208,211)):
        require(defs.get(f'%{source}') == f'extractvalue %dx.types.ResRet.f32 %151, {channel}', 'Color extraction')
        uses = [key for key,value in defs.items() if re.search(r'%'+str(source)+r'(?![\w.])',value)]
        require(uses == [f'%{output}'] and defs[f'%{output}'] == f'fmul fast float %{source}, %{tint}', 'Exclusive color consumer')
        require(f'%{source}' in surface_shader.ancestors(f'%{store}',defs), 'Color output ancestry')
        require(f'i8 {channel}, float %{store})' in text, 'RGB store')
    require('i8 3, float 0.000000e+00)' in text, 'Stock output alpha')
    require(defs.get('%156') == 'extractvalue %dx.types.CBufRet.f32 %155, 0' and
            defs.get('%155') == 'call %dx.types.CBufRet.f32 @dx.op.cbufferLoadLegacy.f32(i32 59, %dx.types.Handle %6, i32 90)', 'Viewport time at byte 1440')
    return dict(sample='%151', texture='%70', sampler='%51', shape_uv='%144',
                rgb=['%152','%153','%154'], consumers=['%190','%191','%192'], time='%156', alpha='constant zero')


def module_for(original, stat, shaders):
    original, stat = original.replace('\r\n','\n'), stat.replace('\r\n','\n')
    color_path(original)
    body = shaders.body(original)
    module = stat[stat.index('target datalayout'):]
    require(module.count('declare void @ps_main()') == 1, 'STAT entry')
    require('!2 = !{i32 0, i32 0}' in module, 'STAT validator version')
    module = module.replace('!2 = !{i32 0, i32 0}', '!2 = !{i32 1, i32 7}')
    counters = re.search(r'^!dx.counters = !\{(!\d+)\}$',module,re.M)
    if counters is None:
        raise ValueError('STAT counters')
    module = re.sub(r'^!dx.counters = .*\n','',module,flags=re.M)
    module = re.sub(r'^'+re.escape(counters[1])+r' = .*\n','',module,flags=re.M)
    old_type = re.search(r'^%c_material_exports = type \{.*\}$',module,re.M)
    resource = re.search(r'(%c_material_exports\* undef, !"c_material_exports", i32 0, i32 2, i32 1, i32 )104(, null)',module)
    annotation = re.search(r'%c_material_exports undef, (!\d+)',module)
    if not old_type or not resource or not annotation:
        raise ValueError('104-byte material reflection')
    module = module[:resource.start()]+resource[1]+'136'+resource[2]+module[resource.end():]
    module = module.replace(old_type[0], old_type[0][:-2]+', <4 x float>, <2 x float> }')
    row = re.search(r'^'+re.escape(annotation[1])+r' = !\{i32 104, (.*)\}$',module,re.M)
    if row is None:
        raise ValueError('104-byte material annotation')
    next_id = max(map(int,re.findall(r'^!(\d+) =',module,re.M)))+1
    module = module.replace(row[0], f'{annotation[1]} = !{{i32 136, {row[1]}, !{next_id}, !{next_id+1}}}')
    for i,(name,_,offset,_) in enumerate(EXPORTS):
        module += f'\n!{next_id+i} = !{{i32 6, !"{name}", i32 3, i32 {offset}, i32 7, i32 9}}\n'
    controls = live_shader.instructions(('%152','%153','%154'), '%156', shaders, True, True)
    for name, old_register, new_register in [('hsv',5,7), ('cycle',6,8)]:
        old = f'%rf.{name} = call %dx.types.CBufRet.f32 @dx.op.cbufferLoadLegacy.f32(i32 59, %dx.types.Handle %4, i32 {old_register})'
        require(controls.count(old) == 1, 'Control register anchor')
        controls = controls.replace(old, old[:-2]+f'{new_register})')
    anchor = '  %190 = fmul fast float %152, %7'
    require(body.count(anchor) == 1, 'Insertion point')
    changed = body.replace(anchor, controls+anchor)
    for channel,source,target,tint in zip('rgb',(152,153,154),(190,191,192),(7,8,9)):
        changed = changed.replace(f'%{target} = fmul fast float %{source}, %{tint}',
                                  f'%{target} = fmul fast float %rf.{channel}, %{tint}')
    reverse = changed.replace(controls,'')
    for channel,source,target,tint in zip('rgb',(152,153,154),(190,191,192),(7,8,9)):
        reverse = reverse.replace(f'%{target} = fmul fast float %rf.{channel}, %{tint}',
                                  f'%{target} = fmul fast float %{source}, %{tint}')
    require(reverse == body, 'Exact executable reverse (shape/UV/alpha/unrelated body)')
    module = module.replace('declare void @ps_main()',changed)
    require('declare float @dx.op.binary.f32(' not in module, 'Unexpected binary declaration')
    return module+'\ndeclare float @dx.op.binary.f32(i32, float, float) #0\n'


def material_for(original, programs, replacements, old, repack):
    require(preflight.identity(original)['sha256'] == preflight.SOURCE_SHA, 'Exact retained authoring source')
    require(len(programs) == 16 and set(replacements) == set(TARGETS), 'Exact color replacement profile')
    _,mo,ms,so,ss,tail,ts = struct.unpack_from('<7I',original)
    shader = original[so:so+ss]
    start,length,ds,dl = struct.unpack_from('<4I',shader,32)
    default = struct.unpack_from('<I',shader,20)[0]
    groups = groups_for(shader[start:start+length])
    original_groups = copy.deepcopy(groups)
    hash32 = lambda name: old.murmur64(name.encode()) >> 32
    model = exports.material_template(original[mo:mo+ms])
    stock_model = copy.deepcopy(model)
    defaults = exports.default_table(shader[default:])
    stock_defaults = copy.deepcopy(defaults)
    for name,kind,offset,width in EXPORTS:
        key = hash32(name)
        require(not any(d[2] == key for d in model['descriptors']) and not any(k == key for k,_ in defaults), 'Export collision')
        model['descriptors'].append([kind,0,key,len(model['values']),width])
        model['values'] += bytes(width)
        defaults.append((key,bytes(width)))
        for g in groups:
            b = g['buffers'][3]
            require(not any(d[2] == key for d in b['descriptors']), 'Group export collision')
            b['descriptors'].append([kind,0,key,offset,width])
    for g in groups:
        g['buffers'][3]['size'] = 144
        g['allocation'] = 432
    registration = serialize_groups(groups)
    # Reverse only the appended fields and evidenced final allocation increments.
    reverse_groups = copy.deepcopy(groups)
    for g in reverse_groups:
        g['buffers'][3]['descriptors'] = g['buffers'][3]['descriptors'][:-2]
        g['buffers'][3]['size'] -= 32
        g['allocation'] -= 32
    require(reverse_groups == original_groups, 'Registration reverse')
    require(serialize_groups(reverse_groups) == shader[start:start+length], 'Registration byte reverse')
    require(model['values'][:-24] == stock_model['values'] and model['descriptors'][:-2] == stock_model['descriptors'], 'Template preserved')
    prefix = bytearray(shader[:start]+registration)
    prefix += bytes((-len(prefix))%4)
    new_ds = len(prefix)
    device = bytearray()
    reverse_device = bytearray()
    cursor = ds
    frames = []
    for i,p in enumerate(programs):
        begin,end = p['frame']
        meta = surface_tables.metadata(shader[:ds+dl],end)
        stop = meta['span'][1]
        require(cursor <= begin-8 < end < stop <= ds+dl, 'Program ordering')
        gap = shader[cursor:begin-8]
        device += gap
        reverse_device += gap
        frame = shader[begin:end]
        require(struct.unpack_from('<II',shader,begin-8) == (1,len(frame)), 'Frame envelope')
        require(struct.unpack_from('<Q',shader,end+8)[0] == old.murmur64(frame), 'Original frame key')
        metadata = bytearray(shader[end:stop])
        if i in replacements:
            frame = repack.stored_frame(replacements[i])
            struct.pack_into('<IQ',metadata,4,len(replacements[i]),old.murmur64(frame))
        table = meta['tables'][0]
        matched = 0
        for j,row in enumerate(table['rows']):
            if row[0] == hash32('c_material_exports'):
                require(row[1:3] == [3,112], 'Original native material association/allocation')
                struct.pack_into('<I',metadata,table['offset']-end+4+j*24+8,144)
                matched += 1
        require(matched == 1, 'One material association per program')
        after = surface_tables.metadata(metadata,0)
        for t,(a,b) in enumerate(zip(meta['tables'],after['tables'],strict=True)):
            expected = copy.deepcopy(a['rows'])
            if t == 0:
                for row in expected:
                    if row[0] == hash32('c_material_exports'):
                        row[2] = 144
            require(expected == b['rows'], 'Unexpected metadata table mutation')
        new_begin = new_ds+len(device)+8
        device += shader_tables.words([1,len(frame)])+frame+metadata
        frames.append(dict(index=i, frame=[new_begin,new_begin+len(frame)],
                           frame_identity=preflight.identity(frame), frame_unchanged=i not in replacements))
        reversed_metadata = bytearray(metadata)
        reversed_metadata[:16] = shader[end:end+16]
        for j,row in enumerate(table['rows']):
            if row[0] == hash32('c_material_exports'):
                struct.pack_into('<I',reversed_metadata,table['offset']-end+4+j*24+8,112)
        require(reversed_metadata == shader[end:stop], 'All metadata bytes reverse')
        reverse_device += shader[begin-8:end]+reversed_metadata
        cursor = stop
    device += shader[cursor:ds+dl]
    reverse_device += shader[cursor:ds+dl]
    require(reverse_device == shader[ds:ds+dl], 'Complete device byte reverse')
    new_default = (new_ds+len(device)+3)&~3
    struct.pack_into('<I',prefix,20,new_default)
    struct.pack_into('<3I',prefix,36,len(registration),new_ds,len(device))
    new_shader = bytes(prefix)+device+bytes(new_default-new_ds-len(device))+exports.serialize_defaults(defaults)
    new_shader += bytes((-len(new_shader))%16)
    template = exports.serialize_material(model)
    new_so = 28+len(template)
    result = shader_tables.words([61,28,len(template),new_so,len(new_shader),new_so+len(new_shader),ts])+template+new_shader+original[tail:]
    require(exports.material_template(template) == model, 'Template readback')
    require(exports.default_table(new_shader[new_default:]) == defaults, 'Defaults readback')
    require(exports.default_table(new_shader[new_default:])[:-2] == stock_defaults, 'Stock defaults preserved')
    require(new_shader[48:start] == shader[48:start], 'Context/condition/dependency bytes')
    for i,p in enumerate(frames):
        a,b = p['frame']
        if i not in replacements:
            x,y = programs[i]['frame']
            require(new_shader[a:b] == shader[x:y], 'Non-target frame byte identity')
        else:
            require(repack.frame_payload(new_shader[a:b],len(replacements[i]),{}) == replacements[i], 'Stored frame readback')
    # Reconstruct the original material from independently reversed sections.
    reverse_template = copy.deepcopy(model)
    reverse_template['descriptors'] = reverse_template['descriptors'][:-2]
    reverse_template['values'] = reverse_template['values'][:-24]
    reverse_shader = shader[:start]+serialize_groups(reverse_groups)+shader[start+length:ds]+bytes(reverse_device)+shader[ds+dl:default]+exports.serialize_defaults(defaults[:-2])
    reverse_shader += bytes(len(shader)-len(reverse_shader))
    reverse = original[:28]+exports.serialize_material(reverse_template)+reverse_shader+original[tail:]
    require(reverse == original, 'Whole material exact reverse')
    return result, new_shader, dict(frames=frames, byte_exact_reverse=True, non_target_frames_preserved=12,
                                    all_16_metadata_tables_verified=True, registration_groups=4,
                                    old_allocation=400,new_allocation=432,material_buffer_size=144)


def run(output, resume=False):
    output = Path(output).resolve()
    require(output.parent == preflight.ANALYSIS and (not output.exists() or resume), 'Unique direct analysis output directory required')
    require(not (output/'SHA256SUMS.json').exists(), 'Completed output cannot be reused')
    original = (preflight.LAYERS/(preflight.TARGET+'.material')).read_bytes()
    audit, shader = preflight.inspect(original)
    start,length = struct.unpack_from('<2I',shader,32)
    groups = groups_for(shader[start:start+length])
    retained = json.loads((preflight.LAYERS/'reflection.json').read_text())
    row = next(r for r in retained if r['material'] == preflight.TARGET)
    require(row['sha256'] == preflight.SOURCE_SHA and len(row['programs']) == 16, 'Reflection manifest identity')
    old,shaders,repack,reflection,checks = build.dependencies()
    prepare,parser = old.prior()
    dxc = prepare.Dxc()
    inputs, paths = [], []
    for i,p in enumerate(row['programs']):
        base = preflight.LAYERS/preflight.TARGET/f'program-{i:02d}'
        data = base.with_suffix('.dxbc').read_bytes()
        text = base.with_suffix('.ll.txt').read_text().replace('\r\n','\n')
        require(preflight.identity(data)['sha256'] == p['sha256'], 'Retained program identity')
        metadata = surface_tables.metadata(shader,p['frame'][1])
        require(metadata['header'][1] == len(data), 'Retained program metadata length')
        require(re.search(r';\s*\} c_material_exports;\s*; Offset:\s*0 Size:\s*104',text), 'Original material buffer extent')
        signed,message = dxc.operation(data,assemble=False)
        require(not message and signed == data and data[4:20] != bytes(16), 'Original signed DXIL')
        require(reflection.dump(base.with_suffix('.dxbc')).decode().replace('\r\n','\n') == text, 'Retained reflection readback')
        if i in TARGETS:
            paths.append(dict(index=i,**color_path(text)))
        else:
            require(p['stage'] == ('vs_main' if i%2 == 0 else 'ps_main'), 'Non-target stage')
            if i%2:
                require('@dx.op.storeOutput' not in text and '@dx.op.discard' in text, 'Depth/discard-only pixel program')
        inputs.append((data,text))
    hash32 = lambda name: old.murmur64(name.encode()) >> 32
    fields = shader_tables.reflection_descriptors(inputs[1][1],old.murmur64)['c_material_exports']
    for g in groups:
        native = g['buffers'][3]['descriptors']
        require(len(native) == len(fields) == 16, 'All material fields accounted for')
        for d,f in zip(native,fields,strict=True):
            require(d[3:] == [f['offset'],f['width']], 'Every original material offset/width')
            if not f['name'].startswith('__BINDLESS_'):
                require(d[2] == f['hash'], 'Named material descriptor identity')
    output.mkdir(exist_ok=resume)
    def save(name,data):
        if resume and (output/name).exists():
            require((output/name).read_bytes() == data, 'Resume artifact differs: '+name)
            return
        with (output/name).open('xb') as stream:
            stream.write(data)
    def chunks(data):
        return {c['tag']:data[c['offset']+8:c['offset']+8+c['size']] for c in parser.dxbc(data)}
    replacements,program_reports = {},[]
    for i in TARGETS:
        data,text = inputs[i]
        stem = f'program-{i:02d}'
        parts = chunks(data)
        save(stem+'-original-STAT.program',parts['STAT'])
        stat = reflection.dump(output/(stem+'-original-STAT.program')).decode()
        save(stem+'-original-STAT.ll.txt',stat.encode())
        module = module_for(text,stat,shaders)
        save(stem+'.input.ll',module.encode())
        assembled,message = dxc.operation(module.encode(),assemble=True)
        require(not message, 'DXIL assembly: '+str(message))
        signed,message = dxc.operation(assembled,assemble=False)
        require(not message and signed[4:20] != bytes(16), 'DXIL validation: '+str(message))
        save(stem+'.dxbc',signed)
        reflected = reflection.dump(output/(stem+'.dxbc')).decode()
        save(stem+'.ll.txt',reflected.encode())
        require(build.canonical(module,shaders) == build.canonical(reflected,shaders), 'Signed executable canonical identity')
        before_fields = shader_tables.reflection_descriptors(text,old.murmur64)
        after_fields = shader_tables.reflection_descriptors(reflected,old.murmur64)
        for name,old_fields in before_fields.items():
            require(old_fields == (after_fields[name][:-2] if name == 'c_material_exports' else after_fields[name]), 'Original reflected offsets')
        require(after_fields['c_material_exports'][-2:] == [dict(name=n,hash=hash32(n),offset=o,width=w) for n,_,o,w in EXPORTS], 'Custom reflection offsets/widths')
        verify_buffer_definitions(text,reflected)
        require(text.split('; Resource Bindings:')[1].split('; ViewId state:')[0] == reflected.replace('\r\n','\n').split('; Resource Bindings:')[1].split('; ViewId state:')[0], 'Every original resource binding')
        new_parts = chunks(signed)
        for tag in ('SFI0','ISG1','OSG1','PSV0'):
            require(parts[tag] == new_parts[tag], 'Unchanged signature/binding chunk '+tag)
        save(stem+'-STAT.program',new_parts['STAT'])
        new_stat = reflection.dump(output/(stem+'-STAT.program')).decode()
        save(stem+'-STAT.ll.txt',new_stat.encode())
        require(checks.count_instructions(reflected) == checks.counters(new_stat), 'STAT instruction counters')
        replacements[i] = signed
        program_reports.append(dict(index=i,**preflight.identity(signed),signed_validation=True,
                                    original_bindings_and_fields=True,custom_offsets=[112,128],
                                    canonical_executable=True,stat_counters=True,exact_body_reverse=True))
    material,new_shader,verification = material_for(original,row['programs'],replacements,old,repack)
    save(preflight.TARGET+'.material',material)
    save(preflight.TARGET+'.shader43',new_shader)
    report = dict(status='OFFLINE VERIFIED; NATIVE LOADING AND LIVE REGISTRATION UNTESTED',
                  source=preflight.identity(original), material=preflight.identity(material),
                  shader=preflight.identity(new_shader),exports=EXPORTS,color_paths=paths,
                  programs=program_reports,verification=verification,
                  controls=dict(default='w=0: stock RGB, opacity ignored', original='w=-1: stock RGB times opacity; brightness ignored',
                                selected='w>0: selected hue, brightness and opacity',rainbow='cycle.x>0: time*cycle.y, with Original pause'),
                  limitations=['No native allocation/registration contract or in-game behavior established.',
                               'Retained reflection manifest links compressed source frames to exported programs; original decompression was not repeated.',
                               'No runtime Lua, cloud routing, installer, installed files, deployment or release changes.'])
    save('report.json',(json.dumps(report,indent=2)+'\n').encode())
    manifest = {p.name:preflight.identity(p.read_bytes()) for p in sorted(output.iterdir()) if p.is_file()}
    save('SHA256SUMS.json',(json.dumps(manifest,indent=2)+'\n').encode())
    print(json.dumps(dict(output=str(output),material=report['material'],shader=report['shader'],verification=verification),indent=2))


def verify_buffer_definitions(original, authored):
    """Include matrices/arrays and every reflected field, not just scalar rows."""
    def blocks(text):
        return text.replace('\r\n','\n').split('; Buffer Definitions:')[1].split('; Resource Bindings:')[0]
    before,after = blocks(original),blocks(authored)
    for name,_,offset,width in EXPORTS:
        pattern = r'^;\s+float'+str(width//4)+' '+name+r';\s*; Offset:\s*'+str(offset)+r'\n'
        after,count = re.subn(pattern,'',after,flags=re.M)
        require(count == 1, 'Exact custom buffer declaration')
    after,count = re.subn(r'(\} c_material_exports;\s*; Offset:\s*0 Size:\s*)136',r'\g<1>104',after)
    require(count == 1 and before == after, 'All original buffer definitions including matrix/array offsets')


if __name__ == '__main__':
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--output',required=True)
    cli.add_argument('--resume',action='store_true',help='Resume an incomplete build, requiring identical existing artifacts')
    args = cli.parse_args()
    run(args.output,args.resume)
