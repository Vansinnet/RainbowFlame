"""Exact-profile material61/shader43 experimental export authoring."""
import copy
import struct
from typing import TypedDict

import live_shader
from shader_tables import Cursor, words, table, parse, serialize


class MaterialTemplate(TypedDict):
    head: bytes
    unknown1: list[list[int]]
    textures: list[list[int]]
    contexts: list[list[int]]
    descriptors: list[list[int]]
    values: bytes
    unknown2: bytes
    unknown3: list[list[int]]


def material_template(data) -> MaterialTemplate:
    c = Cursor(data)
    head = c.read(20)
    unknown1, textures, contexts, descriptors = c.table(1), c.table(3), c.table(2), c.table(5)
    values = c.read(c.words()[0])
    count = c.words()[0]
    if count > 4096:
        raise ValueError('Material trailing table count')
    unknown2 = c.read(count*5)
    unknown3 = c.table(2)
    if c.p != len(data):
        raise ValueError('Material template exhaustion')
    return {'head':head, 'unknown1':unknown1, 'textures':textures, 'contexts':contexts,
            'descriptors':descriptors, 'values':values, 'unknown2':unknown2, 'unknown3':unknown3}


def serialize_material(model):
    return (model['head']+table(model['unknown1'])+table(model['textures'])+
            table(model['contexts'])+table(model['descriptors'])+words([len(model['values'])])+
            model['values']+words([len(model['unknown2'])//5])+model['unknown2']+table(model['unknown3']))


def default_table(data):
    c = Cursor(data)
    if c.words() != [0]:
        raise ValueError('Shader defaults prefix')
    rows = c.table(3)
    result = []
    for name, size, offset in rows:
        if size not in (1,2,3,4) or c.p != offset:
            raise ValueError('Shader defaults bounds')
        result.append((name, c.read(4*size)))
    if any(data[c.p:]) or len(data)-c.p > 15:
        raise ValueError('Shader defaults padding')
    return result


def serialize_defaults(rows):
    offset = 8+12*len(rows)
    descriptors, values = [], b''
    for name, value in rows:
        if len(value) not in (4,8,12,16):
            raise ValueError('Shader default width')
        descriptors.append([name,len(value)//4,offset])
        values += value
        offset += len(value)
    return words([0])+table(descriptors)+values


def author(original, replacements, repack, old, parser, known):
    mo, ms, so, ss = repack.material_sections(original)
    template = material_template(original[mo:mo+ms])
    if serialize_material(template) != original[mo:mo+ms]:
        raise ValueError('Material template identity roundtrip')
    shader = original[so:so+ss]
    before = repack.parse_shader(shader,known)
    start, length = struct.unpack_from('<II',shader,32)
    model = parse(shader[start:start+length])
    if serialize(model) != shader[start:start+length]:
        raise ValueError('Shader table identity roundtrip')
    defaults = default_table(shader[before['default']:])
    original_model = copy.deepcopy(model)
    exported = []
    for name, kind, gpu, width in live_shader.EXPORTS:
        key = old.murmur64(name.encode()) >> 32
        if any(d[2] == key for d in template['descriptors']) or any(d[2] == key for d in model['buffers'][3]['descriptors']):
            raise ValueError('Export hash collision')
        material_offset = len(template['values'])
        template['descriptors'].append([kind,0,key,material_offset,width])
        template['values'] += bytes(width)
        model['buffers'][3]['descriptors'].append([kind,0,key,gpu,width])
        defaults.append((key,bytes(width)))
        exported.append(dict(name=name,hash32=f'{key:08x}',material_offset=material_offset,
                             gpu_offset=gpu,width=width,default=[0]*(width//4)))
    model['buffers'][3]['size'] = 112
    model['allocation'] = model['buffers'][3]['allocation_offset']+112
    predevice = serialize(model)
    prefix = bytearray(shader[:start])+predevice
    prefix += bytes((-len(prefix)) % 4)
    device_start = len(prefix)
    device = b''
    p = before['device'][0]
    for index, program in enumerate(before['programs']):
        begin, end = program['frame']
        stop = program['metadata']['span'][1]
        device += shader[p:begin-8]
        replacement = replacements[index]
        frame = repack.stored_frame(replacement)
        metadata = bytearray(shader[end:stop])
        struct.pack_into('<IQ',metadata,4,len(replacement),old.murmur64(frame))
        buffer_table = program['metadata']['tables'][0]
        matched = 0
        for i, row in enumerate(buffer_table['rows']):
            if row[0] == old.murmur64(b'c_material_exports') >> 32:
                if row[1:3] != [3,80]:
                    raise ValueError('Program material-buffer association')
                struct.pack_into('<I',metadata,buffer_table['offset']-end+4+24*i+8,112)
                matched += 1
        if matched != 1:
            raise ValueError('Program material-buffer count')
        device += words([1,len(frame)])+frame+metadata
        p = stop
    device += shader[p:before['device'][1]]
    new_default = (device_start+len(device)+3) & ~3
    struct.pack_into('<I',prefix,20,new_default)
    struct.pack_into('<3I',prefix,36,len(predevice),device_start,len(device))
    new_shader = bytes(prefix)+device+bytes(new_default-device_start-len(device))+serialize_defaults(defaults)
    new_shader += bytes((-len(new_shader)) % 16)
    template_data = serialize_material(template)
    # Both retained material61 profiles pack shader43 directly after the template.
    new_so = 28+len(template_data)
    result = (words([61,28,len(template_data),new_so,len(new_shader),new_so+len(new_shader),4])+
              template_data+new_shader+bytes(4))
    repack.material_sections(result)
    # Independent inherited program traversal: normalize only the now-enlarged
    # defaults back to the original table, leaving all authored device bytes intact.
    normalized = new_shader[:new_default]+serialize_defaults(defaults[:-2])
    normalized += bytes((-len(normalized)) % 16)
    after = repack.parse_shader(normalized,known)
    if [p['data'] for p in after['programs']] != replacements:
        raise ValueError('Authored program readback')
    readback = material_template(result[28:28+len(template_data)])
    if readback != template or default_table(new_shader[new_default:]) != defaults:
        raise ValueError('Authored defaults/material readback')
    for i, (a,b) in enumerate(zip(before['programs'],after['programs'])):
        for t, (x,y) in enumerate(zip(a['metadata']['tables'],b['metadata']['tables'])):
            expected = copy.deepcopy(x.get('rows',[]))
            if t == 0:
                for row in expected:
                    if row[0] == old.murmur64(b'c_material_exports') >> 32:
                        row[2] = 112
            if expected != y.get('rows',[]):
                raise ValueError('Unexpected device table mutation')
    return result, new_shader, dict(exports=exported, old_allocation=original_model['allocation'],
                                    new_allocation=model['allocation'], buffer_size=112,
                                    technique_bytes_unchanged=True, defaults_stock=True,
                                    runtime_registration_observed=False)
