"""Bounded target shader43 table reader/writer. Opaque associations stay explicit.

Descriptor class/elements/hash/offset/stride follow the retained material source
and are checked against independent DXC reflection. This is not a native loader.
"""
import struct
from typing import TypedDict


class Buffer(TypedDict):
    descriptors: list[list[int]]
    size: int
    allocation_offset: int


class ShaderTables(TypedDict):
    key: int
    allocation: int
    resources: list[list[int]]
    buffers: list[Buffer]
    associations: list[list[int]]
    techniques_opaque: bytes


class Cursor:
    def __init__(self, data):
        self.data, self.p = bytes(data), 0

    def read(self, n):
        if n < 0 or self.p+n > len(self.data):
            raise ValueError('Table bounds')
        result = self.data[self.p:self.p+n]
        self.p += n
        return result

    def words(self, n=1) -> list[int]:
        return list(struct.unpack('<'+'I'*n, self.read(4*n)))

    def table(self, width) -> list[list[int]]:
        count = self.words()[0]
        if count > 4096 or count*width*4 > len(self.data)-self.p:
            raise ValueError('Table count')
        return [self.words(width) for _ in range(count)]


def words(values):
    return struct.pack('<'+'I'*len(values), *values)


def table(rows):
    return words([len(rows)]) + b''.join(words(row) for row in rows)


def parse(data) -> ShaderTables:
    c = Cursor(data)
    count, key, allocation = c.words(3)
    if count != 1:
        raise ValueError('Only the exact single-group target is supported')
    resources = c.table(4)
    if len(resources) != 9:
        raise ValueError('Target resource table')
    buffer_count = c.words()[0]
    if buffer_count != 4:
        raise ValueError('Target buffer table')
    buffers: list[Buffer] = []
    for _ in range(buffer_count):
        descriptors = c.table(5)
        size, allocation_offset = c.words(2)
        if not descriptors or size % 16 or size > 65536:
            raise ValueError('Buffer size')
        for kind, elements, name, offset, stride in descriptors:
            if kind > 10 or offset+stride*max(1, elements) > size or not name:
                raise ValueError('Descriptor bounds')
            if kind <= 3 and (elements != 0 or stride != 4*(kind+1)):
                raise ValueError('Scalar/vector descriptor contract')
        buffers.append({'descriptors':descriptors, 'size':size, 'allocation_offset':allocation_offset})
    associations = c.table(7)
    # Remaining per-technique bytes have no evidenced authoring schema yet.
    tail = c.read(len(data)-c.p)
    if len(associations) != 6 or len(tail) != 46 or int.from_bytes(tail[:4], 'little') != 2:
        raise ValueError('Target association/technique profile')
    if buffers[-1]['allocation_offset']+buffers[-1]['size'] != allocation:
        raise ValueError('Target final allocation extent')
    return {'key':key, 'allocation':allocation, 'resources':resources, 'buffers':buffers,
            'associations':associations, 'techniques_opaque':tail}


def serialize(model):
    data = words([1, model['key'], model['allocation']]) + table(model['resources'])
    data += words([len(model['buffers'])])
    for buffer in model['buffers']:
        data += table(buffer['descriptors']) + words([buffer['size'], buffer['allocation_offset']])
    data += table(model['associations']) + model['techniques_opaque']
    parse(data)
    return data


def reflection_descriptors(text, murmur):
    import re
    blocks = re.findall(r'; cbuffer (\w+)\s*\n; \{(.*?)\n; \}', text, re.S)
    result = {}
    for name, block in blocks:
        fields = []
        for kind, field, offset in re.findall(r';\s+(float[234]?|uint[234]?)\s+(\w+);\s*; Offset:\s*(\d+)', block):
            width = int(kind[-1]) if kind[-1].isdigit() else 1
            fields.append(dict(name=field, hash=murmur(field.encode()) >> 32,
                               offset=int(offset), width=4*width))
        result[name] = fields
    return result
