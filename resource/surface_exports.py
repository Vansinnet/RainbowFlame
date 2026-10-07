"""Experimental offline surface registration authoring; native routing unverified."""
import copy
import hashlib
import struct

from export_resources import material_template, serialize_material, default_table, serialize_defaults
from shader_tables import words
import surface_shader
import surface_tables


def append_template(data, hash32):
    model = material_template(data)
    if serialize_material(model) != data:
        raise ValueError('Template identity roundtrip')
    for name, kind, _, width in surface_shader.EXPORTS:
        key = hash32(name)
        if any(d[2] == key for d in model['descriptors']):
            raise ValueError('Export collision')
        model['descriptors'].append([kind, 0, key, len(model['values']), width])
        model['values'] += bytes(width)
    return serialize_material(model)


def register_groups(groups, hash32):
    result = copy.deepcopy(groups)
    particle = hash32('particle_max_size')
    changed = []
    for i, group in enumerate(result):
        found = [b for b in group['buffers'] if any(d[2] == particle for d in b['descriptors'])]
        if i in (4, 5):
            if found:
                raise ValueError('Unexpected material in compute-only group')
            continue
        if len(found) != 1:
            raise ValueError('Material descriptor identity')
        buffer = found[0]
        if buffer['size'] != 96 or not any(d == [0,0,particle,80,4] for d in buffer['descriptors']):
            raise ValueError('Original material buffer layout')
        boundary = buffer['allocation_offset'] + 96
        for other in group['buffers']:
            if other is not buffer and other['allocation_offset'] >= boundary:
                other['allocation_offset'] += 32
        for name, kind, gpu, width in surface_shader.EXPORTS:
            key = hash32(name)
            if any(d[2] == key for d in buffer['descriptors']):
                raise ValueError('Group export collision')
            buffer['descriptors'].append([kind,0,key,gpu,width])
        buffer['size'] = 128
        group['allocation'] += 32
        changed.append(i)
    if changed != [0,1,2,3,6,7]:
        raise ValueError('Surface registration groups')
    surface_tables.serialize(result)
    return result


def author(parent, report, replacements, old, repack):
    if hashlib.sha256(parent).hexdigest() != 'a5c007c5b0af581b834d62b5053237a56888da2d575666461fefc77ab9665e32':
        raise ValueError('Exact parent identity')
    if set(replacements) != {1,10,19,23} or len(report['programs']) != 32:
        raise ValueError('Exact replacement profile')
    version, mo, ms, so, ss, tail, tail_size = struct.unpack_from('<7I', parent)
    if (version, mo, so, tail, tail_size) != (61,28,28+ms,so+ss,14437) or tail+tail_size != len(parent):
        raise ValueError('Packed parent material61 profile')
    hash32 = lambda name: old.murmur64(name.encode()) >> 32
    shader = parent[so:so+ss]
    start, length, device_start, device_length = struct.unpack_from('<4I', shader, 32)
    default = struct.unpack_from('<I', shader, 20)[0]
    groups = surface_tables.parse(shader[start:start+length])
    registered = register_groups(groups, hash32)
    predevice = surface_tables.serialize(registered)
    prefix = bytearray(shader[:start] + predevice)
    prefix += bytes((-len(prefix)) % 4)
    new_device_start = len(prefix)
    device = bytearray()
    cursor = device_start
    changed_metadata = []
    for index, program in enumerate(report['programs']):
        begin, end = program['frame']
        meta = surface_tables.metadata(shader[:device_start+device_length], end)
        stop = meta['span'][1]
        if begin-8 < cursor:
            raise ValueError('Overlapping program metadata')
        device += shader[cursor:begin-8]
        frame = shader[begin:end]
        metadata = bytearray(shader[end:stop])
        if index in replacements:
            frame = repack.stored_frame(replacements[index])
            struct.pack_into('<IQ', metadata, 4, len(replacements[index]), old.murmur64(frame))
        for n, row in enumerate(meta['tables'][0]['rows']):
            if row[0] == hash32('c_material_exports'):
                if row[2] != 96:
                    raise ValueError('Original device allocation')
                struct.pack_into('<I', metadata, meta['tables'][0]['offset']-end+4+n*24+8,128)
                changed_metadata.append(index)
        device += words([1,len(frame)]) + frame + metadata
        cursor = stop
    device += shader[cursor:device_start+device_length]
    new_default = (new_device_start+len(device)+3)&~3
    defaults = default_table(shader[default:])
    for name, _, _, width in surface_shader.EXPORTS:
        if any(key == hash32(name) for key, _ in defaults):
            raise ValueError('Default collision')
        defaults.append((hash32(name), bytes(width)))
    struct.pack_into('<I', prefix,20,new_default)
    struct.pack_into('<3I',prefix,36,len(predevice),new_device_start,len(device))
    new_shader = bytes(prefix)+device+bytes(new_default-new_device_start-len(device))+serialize_defaults(defaults)
    new_shader += bytes((-len(new_shader))%16)
    template = append_template(parent[mo:mo+ms], hash32)
    new_so = 28+len(template)
    output = words([61,28,len(template),new_so,len(new_shader),new_so+len(new_shader),tail_size])+template+new_shader+parent[tail:]
    return output, dict(changed_metadata=changed_metadata, groups=registered,
                        original_groups=groups, resource_ready=False,
                        reason='Experimental offline registration; surface cloud routing and native loading unverified')


def author_child(original, hash32):
    if hashlib.sha256(original).hexdigest() != 'b55f7d9c5d7577bf46c625ae4a776872a6592944f8db93057736ef8fd217019b':
        raise ValueError('Exact inherited child identity')
    header = list(struct.unpack_from('<7I', original))
    version, mo, ms, so, ss, tail, tail_size = header
    if (version,mo,so,ss,tail,tail_size) != (61,28,0xffffffff,0,0xffffffff,0) or mo+ms != len(original):
        raise ValueError('Inherited child material61 profile')
    template = append_template(original[mo:mo+ms],hash32)
    return words([61,mo,len(template),so,ss,tail,tail_size])+template
