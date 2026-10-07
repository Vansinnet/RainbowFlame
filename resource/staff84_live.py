"""Exact retained 84dc/2d07 offline candidate; no installation or runtime access."""
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
import surface_shader
import surface_tables

ROOT = Path(__file__).resolve().parents[4]
ANALYSIS = ROOT / 'docs/analysis-rainbow-staff-3p-20260921-a1'
LAYERS = ANALYSIS / 'layers'
OUTPUT = ANALYSIS / 'live84-offline'
PARENT = '84dce57f22a9d409'
CHILD = '2d0708b33f17b5e4'
SOURCE = ROOT / 'docs/analysis-flame-ramp-20260918-k1/materials' / (PARENT+'.material')
CHILD_SOURCE = ROOT / 'docs/analysis-flame-target-20260917-a1/materials-4e6163c275b96d00-v8-stream/hash-only' / (CHILD+'.material')
SOURCE_SHA = 'c4d900493a29f564ebb8d844cc0dac4f759288d254612c4aba84ace6ef37d08f'
CHILD_SHA = 'e1b7c9e8a483009c090f31641261471d3a60d2c25cc7879e201e079ecb18139c'
TARGETS = tuple(range(1, 32, 4))
EXPORTS = ((live_shader.HSV, 3, 80, 16), (live_shader.CYCLE, 1, 96, 8))
GROUP_KEYS = (3268308642, 305202949, 495865501, 2287683504,
              3743261651, 2790771169, 1634595616, 2751495883)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def identity(data):
    return dict(size=len(data), sha256=hashlib.sha256(data).hexdigest())


def serialize_groups(groups):
    result = tables.words([len(groups)])
    for g in groups:
        result += tables.words([g['key'], g['allocation']])+tables.table(g['resources'])
        result += tables.words([len(g['buffers'])])
        for b in g['buffers']:
            result += tables.table(b['descriptors'])+tables.words([b['size'], b['allocation_offset']])
        result += tables.table(g['associations'])+tables.words([len(g['techniques'])//17])
        result += g['techniques']+g['trailer']
    return result


def groups_for(data, extended=False):
    c = tables.Cursor(data)
    require(c.words() == [8], 'Eight registration groups')
    groups = []
    for key in GROUP_KEYS:
        actual, allocation = c.words(2)
        require(actual == key and allocation == (384 if extended else 352), 'Group identity/allocation')
        resources = c.table(4)
        require(len(resources) == 9 and c.words() == [4], 'Resources/buffer count')
        buffers = []
        for size, offset in ((1776,0), (400,0), (128,144), (112 if extended else 80,272)):
            descriptors = c.table(5)
            require(c.words(2) == [size,offset], 'Buffer allocation profile')
            for kind, elements, name, field, width in descriptors:
                require(name and kind <= 10 and field+max(1,elements)*width <= size, 'Descriptor extent')
                require(kind > 3 or (elements == 0 and width == 4*(kind+1)), 'Descriptor kind')
            buffers.append(dict(descriptors=descriptors,size=size,allocation_offset=offset))
        require([len(b['descriptors']) for b in buffers] == [69,58,2,15 if extended else 13], 'Descriptor counts')
        associations = c.table(7)
        require(len(associations) == 6 and c.words() == [2], 'Association/technique counts')
        groups.append(dict(key=key,allocation=allocation,resources=resources,buffers=buffers,
                           associations=associations,techniques=c.read(34),trailer=c.read(8)))
    require(c.p == len(data) and serialize_groups(groups) == data, 'Registration exact roundtrip')
    return groups


def inspect(original):
    require(identity(original)['sha256'] == SOURCE_SHA, 'Exact parent identity')
    h = struct.unpack_from('<7I',original)
    require(h == (61,28,340,368,315632,316000,4), 'Parent material61 profile')
    model = exports.material_template(original[28:368])
    require(exports.serialize_material(model) == original[28:368], 'Template roundtrip')
    shader = original[368:316000]
    header = struct.unpack_from('<12I',shader)
    start,length,ds,dl = header[8:12]
    require(header[0] == 43 and (start,length) == (468,26132) and
            start+length <= ds < ds+dl <= header[5] < len(shader), 'Shader43 bounds')
    groups_for(shader[start:start+length])
    defaults = exports.serialize_defaults(exports.default_table(shader[header[5]:]))
    require(defaults+bytes(len(shader)-header[5]-len(defaults)) == shader[header[5]:], 'Default roundtrip')
    return shader


def color_path(text):
    defs = surface_shader.definitions(text)
    require('define void @ps_main()' in text, 'Pixel stage')
    require(re.search(r'; c_material_exports\s+cbuffer\s+NA\s+NA\s+CB1\s+cb1\s+1',text), 'Material binding')
    require(defs.get('%4') == 'call %dx.types.Handle @dx.op.createHandle(i32 57, i8 2, i32 1, i32 1, i1 false)', 'Material handle')
    for field,offset in [('__BINDLESS_TEX2D_texture_map_fc5c271f',24),
                         ('__BINDLESS_SAMPLER_texture_map_fc5c271f',4)]:
        require(re.search(r';\s+uint2? '+field+r';\s*; Offset:\s*'+str(offset)+r'\s*$',text,re.M), 'Ramp offset')
    for name,expected in {
        '%66':'call %dx.types.CBufRet.i32 @dx.op.cbufferLoadLegacy.i32(i32 59, %dx.types.Handle %4, i32 1)',
        '%67':'extractvalue %dx.types.CBufRet.i32 %66, 2',
        '%47':'call %dx.types.CBufRet.i32 @dx.op.cbufferLoadLegacy.i32(i32 59, %dx.types.Handle %4, i32 0)',
        '%48':'extractvalue %dx.types.CBufRet.i32 %47, 1',
        '%149':'call %dx.types.ResRet.f32 @dx.op.sample.f32(i32 60, %dx.types.Handle %69, %dx.types.Handle %50, float %143, float %143, float undef, float undef, i32 0, i32 0, i32 undef, float %148)',
        '%5':'call %dx.types.Handle @dx.op.createHandle(i32 57, i8 2, i32 0, i32 0, i1 false)',
        '%153':'call %dx.types.CBufRet.f32 @dx.op.cbufferLoadLegacy.f32(i32 59, %dx.types.Handle %5, i32 90)',
        '%154':'extractvalue %dx.types.CBufRet.f32 %153, 0',
    }.items():
        require(defs.get(name) == expected, 'Ramp/time anchor '+name)
    require('%67' in surface_shader.ancestors('%69',defs) and
            '%48' in surface_shader.ancestors('%50',defs), 'Ramp handle ancestry')
    for channel,source,consumer,gain,store in zip(range(3),(150,151,152),(193,197,201),(192,196,200),(194,198,202)):
        require(defs.get(f'%{source}') == f'extractvalue %dx.types.ResRet.f32 %149, {channel}', 'RGB extraction')
        uses = [key for key,value in defs.items() if re.search(r'%'+str(source)+r'(?![\w.])',value)]
        require(uses == [f'%{consumer}'] and defs[f'%{consumer}'] == f'fmul fast float %{gain}, %{source}', 'Exclusive RGB consumer')
        require(f'%{source}' in surface_shader.ancestors(f'%{store}',defs) and
                f'i8 {channel}, float %{store})' in text, 'RGB store ancestry')
    require('i8 3, float 0.000000e+00)' in text, 'Stock zero alpha')
    return dict(sample='%149',rgb=['%150','%151','%152'],consumers=['%193','%197','%201'],time='%154',shape='%143')


def module_for(original, stat, shaders):
    original,stat = original.replace('\r\n','\n'),stat.replace('\r\n','\n')
    color_path(original)
    body = shaders.body(original)
    module = stat[stat.index('target datalayout'):]
    require(module.count('declare void @ps_main()') == 1, 'STAT entry')
    require('!2 = !{i32 0, i32 0}' in module, 'STAT validator version')
    module = module.replace('!2 = !{i32 0, i32 0}','!2 = !{i32 1, i32 7}')
    counter = re.search(r'^!dx.counters = !\{(!\d+)\}$',module,re.M)
    if counter is None:
        raise ValueError('STAT counters')
    module = re.sub(r'^!dx.counters = .*\n','',module,flags=re.M)
    module = re.sub(r'^'+re.escape(counter[1])+r' = .*\n','',module,flags=re.M)
    typ = re.search(r'^%c_material_exports = type \{.*\}$',module,re.M)
    resource = re.search(r'(%c_material_exports\* undef, !"c_material_exports", i32 0, i32 1, i32 1, i32 )76(, null)',module)
    annotation = re.search(r'%c_material_exports undef, (!\d+)',module)
    if typ is None or resource is None or annotation is None:
        raise ValueError('76-byte CB1 STAT layout')
    module = module[:resource.start()]+resource[1]+'104'+resource[2]+module[resource.end():]
    module = module.replace(typ[0],typ[0][:-2]+', <4 x float>, <2 x float> }')
    row = re.search(r'^'+re.escape(annotation[1])+r' = !\{i32 76, (.*)\}$',module,re.M)
    if row is None:
        raise ValueError('76-byte annotation')
    next_id = max(map(int,re.findall(r'^!(\d+) =',module,re.M)))+1
    module = module.replace(row[0],f'{annotation[1]} = !{{i32 104, {row[1]}, !{next_id}, !{next_id+1}}}')
    for i,(name,_,offset,_) in enumerate(EXPORTS):
        module += f'\n!{next_id+i} = !{{i32 6, !"{name}", i32 3, i32 {offset}, i32 7, i32 9}}\n'
    require(not re.search(r'!\d+',body), 'Unexpected executable metadata')
    fragment = live_shader.instructions(('%150','%151','%152'),'%154',shaders,True,True)
    anchor = '  %193 = fmul fast float %192, %150'
    require(body.count(anchor) == 1, 'RGB insertion point')
    changed = body.replace(anchor,fragment+anchor)
    reverse = changed.replace(fragment,'')
    for channel,source,target,gain in zip('rgb',(150,151,152),(193,197,201),(192,196,200)):
        old = f'%{target} = fmul fast float %{gain}, %{source}'
        new = f'%{target} = fmul fast float %{gain}, %rf.{channel}'
        changed = changed.replace(old,new)
    restored = changed.replace(fragment,'')
    for channel,source,target,gain in zip('rgb',(150,151,152),(193,197,201),(192,196,200)):
        restored = restored.replace(f'%{target} = fmul fast float %{gain}, %rf.{channel}',
                                    f'%{target} = fmul fast float %{gain}, %{source}')
    require(restored == reverse == body, 'Exact executable reverse')
    require('declare float @dx.op.binary.f32(' not in module, 'Unexpected binary declaration')
    return module.replace('declare void @ps_main()',changed)+'\ndeclare float @dx.op.binary.f32(i32, float, float) #0\n'


def append_template(model, hash32, expected_size):
    result = copy.deepcopy(model)
    require(len(result['values']) == expected_size, 'Packed template extent')
    for name,kind,_,width in EXPORTS:
        key = hash32(name)
        require(not any(d[2] == key for d in result['descriptors']), 'Template export collision')
        result['descriptors'].append([kind,0,key,len(result['values']),width])
        result['values'] += bytes(width)
    reverse = copy.deepcopy(result)
    reverse['values'] = reverse['values'][:-24]
    reverse['descriptors'] = reverse['descriptors'][:-2]
    require(reverse == model, 'Entire template reverse')
    return result


def child_for(original, hash32):
    require(identity(original)['sha256'] == CHILD_SHA, 'Exact child identity')
    h = list(struct.unpack_from('<7I',original))
    require(h == [61,28,272,0xffffffff,0,0xffffffff,0] and len(original) == 300, 'Child absence sentinels')
    model = exports.material_template(original[28:])
    require(exports.serialize_material(model) == original[28:], 'Child template roundtrip')
    new = append_template(model,hash32,52)
    template = exports.serialize_material(new)
    h[2] = len(template)
    result = tables.words(h)+template
    reverse = copy.deepcopy(new)
    reverse['values'],reverse['descriptors'] = reverse['values'][:-24],reverse['descriptors'][:-2]
    require(original[:28]+exports.serialize_material(reverse) == original, 'Whole child reverse')
    require(exports.material_template(template) == new, 'Child readback')
    return result


def material_for(original, programs, replacements, old, repack):
    shader = inspect(original)
    require(len(programs) == 32 and set(replacements) == set(TARGETS), 'Exact replacement profile')
    start,length,ds,dl = struct.unpack_from('<4I',shader,32)
    default = struct.unpack_from('<I',shader,20)[0]
    groups = groups_for(shader[start:start+length])
    stock_groups = copy.deepcopy(groups)
    hash32 = lambda name: old.murmur64(name.encode()) >> 32
    stock_model = exports.material_template(original[28:368])
    model = append_template(stock_model,hash32,36)
    defaults = exports.default_table(shader[default:])
    stock_defaults = copy.deepcopy(defaults)
    for name,kind,offset,width in EXPORTS:
        key = hash32(name)
        require(not any(k == key for k,_ in defaults), 'Default collision')
        defaults.append((key,bytes(width)))
        for g in groups:
            b = g['buffers'][3]
            require(not any(d[2] == key for d in b['descriptors']), 'Group export collision')
            b['descriptors'].append([kind,0,key,offset,width])
    for g in groups:
        g['buffers'][3]['size'] = 112
        g['allocation'] = 384
    registration = serialize_groups(groups)
    require(groups_for(registration,True) == groups, 'Extended registration readback')
    reverse_groups = copy.deepcopy(groups)
    for g in reverse_groups:
        g['buffers'][3]['descriptors'] = g['buffers'][3]['descriptors'][:-2]
        g['buffers'][3]['size'] = 80
        g['allocation'] = 352
    require(reverse_groups == stock_groups, 'All registration fields reverse')
    prefix = bytearray(shader[:start]+registration)
    prefix += bytes((-len(prefix))%4)
    new_ds = len(prefix)
    device,reverse_device,cursor,frames = bytearray(),bytearray(),ds,[]
    for i,p in enumerate(programs):
        begin,end = p['frame']
        meta = surface_tables.metadata(shader,end)
        stop = meta['span'][1]
        require(cursor <= begin-8 < end < stop <= ds+dl, 'Program ordering')
        require(struct.unpack_from('<II',shader,begin-8) == (1,end-begin), 'Frame envelope')
        require(meta['header'][3] << 32 | meta['header'][2] == old.murmur64(shader[begin:end]), 'Original frame key')
        reconstructed = tables.words(meta['header'])+b''.join(tables.table(t['rows']) for t in meta['tables'])
        require(reconstructed == shader[end:stop], 'Every metadata table roundtrip')
        gap = shader[cursor:begin-8]
        device += gap
        reverse_device += gap
        frame = shader[begin:end]
        metadata = bytearray(shader[end:stop])
        if i in replacements:
            frame = repack.stored_frame(replacements[i])
            struct.pack_into('<IQ',metadata,4,len(replacements[i]),old.murmur64(frame))
        table = meta['tables'][0]
        matches = []
        for j,row in enumerate(table['rows']):
            if row[0] == hash32('c_material_exports'):
                require(row[1:3] == [3,80], 'Original material association/allocation')
                position = table['offset']-end+4+j*24+8
                struct.pack_into('<I',metadata,position,112)
                matches.append(position)
        require(len(matches) == 1, 'One material association per program')
        after = surface_tables.metadata(metadata,0)
        for t,(a,b) in enumerate(zip(meta['tables'],after['tables'],strict=True)):
            expected = copy.deepcopy(a['rows'])
            if t == 0:
                for row in expected:
                    if row[0] == hash32('c_material_exports'):
                        row[2] = 112
            require(expected == b['rows'], 'All32 metadata preservation')
        new_begin = new_ds+len(device)+8
        device += tables.words([1,len(frame)])+frame+metadata
        frames.append(dict(index=i,frame=[new_begin,new_begin+len(frame)],unchanged=i not in replacements))
        metadata[:16] = shader[end:end+16]
        struct.pack_into('<I',metadata,matches[0],80)
        require(metadata == shader[end:stop], 'Metadata byte reverse')
        reverse_device += shader[begin-8:end]+metadata
        cursor = stop
    device += shader[cursor:ds+dl]
    reverse_device += shader[cursor:ds+dl]
    require(reverse_device == shader[ds:ds+dl], 'Complete device reverse')
    new_default = (new_ds+len(device)+3)&~3
    struct.pack_into('<I',prefix,20,new_default)
    struct.pack_into('<3I',prefix,36,len(registration),new_ds,len(device))
    new_shader = bytes(prefix)+device+bytes(new_default-new_ds-len(device))+exports.serialize_defaults(defaults)
    new_shader += bytes((-len(new_shader))%16)
    template = exports.serialize_material(model)
    new_so = 28+len(template)
    result = tables.words([61,28,len(template),new_so,len(new_shader),new_so+len(new_shader),4])+template+new_shader+original[316000:]
    require(exports.material_template(template) == model, 'Parent template readback')
    require(exports.default_table(new_shader[new_default:]) == defaults and defaults[:-2] == stock_defaults, 'All defaults preserved')
    require(new_shader[48:start] == shader[48:start], 'Context/condition/dependency bytes')
    for i,f in enumerate(frames):
        a,b = f['frame']
        x,y = programs[i]['frame']
        if i in replacements:
            require(repack.frame_payload(new_shader[a:b],len(replacements[i]),{}) == replacements[i], 'Stored replacement readback')
        else:
            require(new_shader[a:b] == shader[x:y], 'Non-target frame identity')
    reverse_model = copy.deepcopy(model)
    reverse_model['values'],reverse_model['descriptors'] = reverse_model['values'][:-24],reverse_model['descriptors'][:-2]
    reverse_shader = shader[:start]+serialize_groups(reverse_groups)+shader[start+length:ds]+bytes(reverse_device)+shader[ds+dl:default]+exports.serialize_defaults(defaults[:-2])
    reverse_shader += bytes(len(shader)-len(reverse_shader))
    require(original[:28]+exports.serialize_material(reverse_model)+reverse_shader+original[316000:] == original, 'Whole parent exact reverse')
    return result,new_shader,dict(frames=frames,byte_exact_reverse=True,non_target_frames_preserved=24,
                                  all_32_metadata_tables_verified=True,registration_groups=8,
                                  old_allocation=352,new_allocation=384,material_buffer_size=112)


def verify_buffer_definitions(original, authored):
    def blocks(text):
        return text.replace('\r\n','\n').split('; Buffer Definitions:')[1].split('; Resource Bindings:')[0]
    before,after = blocks(original),blocks(authored)
    for name,_,offset,width in EXPORTS:
        after,count = re.subn(r'^;\s+float'+str(width//4)+' '+name+r';\s*; Offset:\s*'+str(offset)+r'\n','',after,flags=re.M)
        require(count == 1, 'Exact custom buffer declaration')
    stock_size = re.search(r'\} c_material_exports;\s*; Offset:\s*0 Size:\s*76',before)
    if stock_size is None:
        raise ValueError('Original buffer extent')
    after,count = re.subn(r'\} c_material_exports;\s*; Offset:\s*0 Size:\s*104',lambda _: stock_size[0],after)
    require(count == 1 and before == after, 'All original buffer definitions including matrices/arrays')


def run(output, resume=False):
    output = Path(output).resolve()
    require(output == OUTPUT and (not output.exists() or resume), 'Unique live84-offline output required')
    require(not (output/'SHA256SUMS.json').exists(), 'Completed output cannot be reused')
    original,child = SOURCE.read_bytes(),CHILD_SOURCE.read_bytes()
    shader = inspect(original)
    retained = json.loads((LAYERS/'reflection.json').read_text())
    row = next(r for r in retained if r['material'] == PARENT)
    require(row['sha256'] == SOURCE_SHA and len(row['programs']) == 32, 'Reflection source identity')
    old,shaders,repack,reflection,checks = build.dependencies()
    prepare,parser = old.prior()
    dxc = prepare.Dxc()
    hash32 = lambda name: old.murmur64(name.encode()) >> 32
    new_child = child_for(child,hash32)
    start,length = struct.unpack_from('<2I',shader,32)
    groups = groups_for(shader[start:start+length])
    inputs = []
    for i,p in enumerate(row['programs']):
        base = LAYERS/PARENT/f'program-{i:02d}'
        data = base.with_suffix('.dxbc').read_bytes()
        text = base.with_suffix('.ll.txt').read_text().replace('\r\n','\n')
        require(identity(data)['sha256'] == p['sha256'], 'Retained program identity')
        require(surface_tables.metadata(shader,p['frame'][1])['header'][1] == len(data), 'Retained program length')
        require(re.search(r';\s*\} c_material_exports;\s*; Offset:\s*0 Size:\s*76',text), 'Original reflected extent')
        signed,message = dxc.operation(data,assemble=False)
        require(not message and signed == data and data[4:20] != bytes(16), 'Original signed DXIL')
        require(reflection.dump(base.with_suffix('.dxbc')).decode().replace('\r\n','\n') == text, 'Original reflection readback')
        require(p['stage'] == ('vs_main' if i%2 == 0 else 'ps_main'), 'Stage profile')
        if i in TARGETS:
            color_path(text)
        elif i%2:
            require('@dx.op.storeOutput' not in text and '@dx.op.discard' in text, 'Discard-only program')
        fields = tables.reflection_descriptors(text,old.murmur64)['c_material_exports']
        for g in groups:
            native = g['buffers'][3]['descriptors']
            require(len(native) == len(fields) == 13, 'All32 material field count')
            for d,f in zip(native,fields,strict=True):
                require(d[3:] == [f['offset'],f['width']], 'All32 original native field offsets')
                if not f['name'].startswith('__BINDLESS_'):
                    require(d[2] == f['hash'], 'All32 named descriptor identity')
        inputs.append((data,text))
    output.mkdir(exist_ok=resume)
    def save(name,data):
        if resume and (output/name).exists():
            require((output/name).read_bytes() == data, 'Resume artifact differs: '+name)
            return
        with (output/name).open('xb') as file:
            file.write(data)
    def chunks(data):
        return {c['tag']:data[c['offset']+8:c['offset']+8+c['size']] for c in parser.dxbc(data)}
    replacements,reports = {},[]
    for i,(data,text) in enumerate(inputs):
        stem = f'program-{i:02d}'
        if i not in TARGETS:
            save(stem+'.dxbc',data)
            save(stem+'.ll.txt',text.encode())
            reports.append(dict(index=i,sha256=identity(data)['sha256'],signed_validation=True,reflection_readback=True,unchanged=True))
            continue
        parts = chunks(data)
        save(stem+'-original-STAT.program',parts['STAT'])
        stat = reflection.dump(output/(stem+'-original-STAT.program')).decode()
        save(stem+'-original-STAT.ll.txt',stat.encode())
        module = module_for(text,stat,shaders)
        save(stem+'.input.ll',module.encode())
        assembled,message = dxc.operation(module.encode(),assemble=True)
        require(not message, 'DXIL assembly: '+str(message))
        signed,message = dxc.operation(assembled,assemble=False)
        require(not message and signed[4:20] != bytes(16), 'Signed validation: '+str(message))
        save(stem+'.dxbc',signed)
        reflected = reflection.dump(output/(stem+'.dxbc')).decode().replace('\r\n','\n')
        save(stem+'.ll.txt',reflected.encode())
        require(build.canonical(module,shaders) == build.canonical(reflected,shaders), 'Signed canonical executable')
        before = tables.reflection_descriptors(text,old.murmur64)
        after = tables.reflection_descriptors(reflected,old.murmur64)
        require(before.keys() == after.keys(), 'Original buffer set')
        for name,fields in before.items():
            require(fields == (after[name][:-2] if name == 'c_material_exports' else after[name]), 'Original reflected offsets')
        require(after['c_material_exports'][-2:] == [dict(name=n,hash=hash32(n),offset=o,width=w) for n,_,o,w in EXPORTS], 'Custom field offsets')
        verify_buffer_definitions(text,reflected)
        require(text.split('; Resource Bindings:')[1].split('; ViewId state:')[0] == reflected.split('; Resource Bindings:')[1].split('; ViewId state:')[0], 'Every resource binding')
        new_parts = chunks(signed)
        for tag in ('SFI0','ISG1','OSG1','PSV0'):
            require(parts[tag] == new_parts[tag], 'Unchanged signature/binding chunk '+tag)
        save(stem+'-STAT.program',new_parts['STAT'])
        new_stat = reflection.dump(output/(stem+'-STAT.program')).decode()
        save(stem+'-STAT.ll.txt',new_stat.encode())
        require(checks.count_instructions(reflected) == checks.counters(new_stat), 'STAT instruction counters')
        replacements[i] = signed
        reports.append(dict(index=i,**identity(signed),signed_validation=True,reflection_readback=True,
                            original_bindings_and_fields=True,canonical_executable=True,stat_counters=True,exact_body_reverse=True))
    material,new_shader,verification = material_for(original,row['programs'],replacements,old,repack)
    save(PARENT+'.material',material)
    save(PARENT+'.shader43',new_shader)
    save(CHILD+'.material',new_child)
    report = dict(status='OFFLINE CANDIDATE; NATIVE LOADING AND INHERITED LIVE CONTROLS UNTESTED',
                  source=identity(original),child_source=identity(child),material=identity(material),
                  shader=identity(new_shader),child=identity(new_child),exports=EXPORTS,programs=reports,
                  verification=verification,child_exact_reverse=True,child_textures_and_absence_sentinels_preserved=True,
                  controls=dict(default='w=0: stock RGB, opacity ignored',original='w=-1: stock RGB times opacity; brightness ignored',
                                selected='w>0: selected hue, brightness and opacity',rainbow='cycle.x>0: time*cycle.y with smooth Original pause'),
                  limitations=['Native inherited field-fill/default precedence, GPU upload and live writes are not established.',
                               'Retained manifest links compressed source frames to exported DXIL; original decompression was not repeated.',
                               'Shared parent scope is not established as effect-local. No cloud routing or runtime changes.',
                               'No installed access, deployment, in-game or dedicated-server result.'])
    save('report.json',(json.dumps(report,indent=2)+'\n').encode())
    manifest = {p.name:identity(p.read_bytes()) for p in sorted(output.iterdir()) if p.is_file()}
    save('SHA256SUMS.json',(json.dumps(manifest,indent=2)+'\n').encode())
    print(json.dumps({k:report[k] for k in ('status','material','shader','child')},indent=2))


if __name__ == '__main__':
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--output',default=str(OUTPUT))
    cli.add_argument('--resume',action='store_true',help='Require identical existing artifacts in an incomplete candidate')
    args = cli.parse_args()
    run(args.output,args.resume)
