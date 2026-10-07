"""Bounded surface43 tables. Unknown technique/UAV words remain opaque.

Exact retained profile only; this is not a native loader or a general format claim.
"""
from typing import TypedDict

from shader_tables import Cursor, table, words

GROUP_KEYS = (2342404262, 3693339818, 1737503052, 382775272,
              2369853855, 1551924889, 1511676746, 1065936201)
BUFFER_COUNTS = (7, 7, 5, 5, 2, 2, 4, 4)
TECHNIQUE_COUNTS = (5, 5, 2, 2, 1, 1, 1, 1)


class MetadataTable(TypedDict):
    offset: int
    rows: list[list[int]]
    width: int
    count: int


class Metadata(TypedDict):
    span: list[int]
    header: list[int]
    tables: list[MetadataTable]


def parse(data):
    c = Cursor(data)
    if c.words() != [8]:
        raise ValueError('Surface group count')
    groups = []
    for key, buffer_count, technique_count in zip(GROUP_KEYS, BUFFER_COUNTS, TECHNIQUE_COUNTS):
        actual, allocation = c.words(2)
        if actual != key:
            raise ValueError('Surface group identity')
        resources = c.table(4)
        if c.words() != [buffer_count]:
            raise ValueError('Surface buffer count')
        buffers = []
        for _ in range(buffer_count):
            descriptors = c.table(5)
            size, offset = c.words(2)
            if not descriptors or not 0 < size <= 65536 or size % 16:
                raise ValueError('Surface buffer extent')
            for kind, elements, name, field, stride in descriptors:
                if kind > 10 or not name or field + max(1, elements)*stride > size:
                    raise ValueError('Surface descriptor extent')
                if kind <= 3 and (elements or stride != 4*(kind+1)):
                    raise ValueError('Surface scalar/vector descriptor')
            buffers.append(dict(descriptors=descriptors, size=size, allocation_offset=offset))
        associations = c.table(7)
        if c.words() != [technique_count]:
            raise ValueError('Surface technique count')
        # Audited exact byte partition: no semantics or relocations assigned here.
        techniques = c.read(17*technique_count)
        trailer = c.read(8)
        if buffers[-1]['allocation_offset'] + buffers[-1]['size'] != allocation:
            raise ValueError('Surface final allocation extent')
        groups.append(dict(key=key, allocation=allocation, resources=resources,
                           buffers=buffers, associations=associations,
                           techniques=techniques, trailer=trailer))
    if c.p != len(data):
        raise ValueError('Surface group exhaustion')
    return groups


def serialize(groups):
    result = words([len(groups)])
    for group in groups:
        result += words([group['key'], group['allocation']]) + table(group['resources'])
        result += words([len(group['buffers'])])
        for buffer in group['buffers']:
            result += table(buffer['descriptors']) + words([buffer['size'], buffer['allocation_offset']])
        result += table(group['associations']) + words([len(group['techniques'])//17])
        result += group['techniques'] + group['trailer']
    parse(result)
    return result


def metadata(data, start) -> Metadata:
    c = Cursor(data)
    c.p = start
    header = c.words(4)
    if header[0] != 5:
        raise ValueError('Surface program metadata kind')
    tables: list[MetadataTable] = []
    # Table 5's seven opaque words are independently matched to compute UAV
    # names/registers below by the audit. Previously it was only witnessed empty.
    for width in (6, 0, 0, 7, 7, 7, 7, 4, 3, 3):
        offset = c.p
        if width:
            rows = c.table(width)
        else:
            if c.words() != [0]:
                raise ValueError('Unwitnessed nonempty surface metadata table')
            rows = []
        tables.append({'offset':offset, 'rows':rows, 'width':width*4, 'count':len(rows)})
    return {'span':[start, c.p], 'header':header, 'tables':tables}
