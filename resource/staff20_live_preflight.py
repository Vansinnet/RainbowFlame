"""Fail-closed offline authoring preflight for the retained 20b9 3P material.

No installed files, decompressor, or native allocation guesses are used.
"""
import hashlib
from pathlib import Path
import struct
import sys

sys.dont_write_bytecode = True
import export_resources
import shader_tables
import surface_tables

ROOT = Path(__file__).resolve().parents[4]
ANALYSIS = ROOT / 'docs/analysis-rainbow-staff-3p-20260921-a1'
LAYERS = ANALYSIS / 'layers'
TARGET = '20b91c9f8a8cc4aa'
SOURCE_SHA = '73943bfb02628b95f6e822cddfea241e87feaa7849080f157952a012cb7efce3'


def identity(data):
    return dict(size=len(data), sha256=hashlib.sha256(data).hexdigest())


def group_probe(data):
    """Try the reviewed surface partition without assigning native semantics."""
    c = shader_tables.Cursor(data)
    if c.words() != [4]:
        raise ValueError('Expected four groups')
    groups = []
    for _ in range(4):
        key, allocation = c.words(2)
        resources = c.table(4)
        buffers = []
        if c.words() != [4]:
            raise ValueError('Expected four buffers per retained group')
        for _ in range(4):
            descriptors = c.table(5)
            size, offset = c.words(2)
            buffers.append(dict(descriptors=descriptors, size=size, allocation_offset=offset))
        associations = c.table(7)
        count = c.words()[0]
        if count != 2:
            raise ValueError('Expected two retained techniques per group')
        techniques, trailer = c.read(17*count), c.read(8)
        groups.append(dict(key=key, allocation=allocation, resources=resources, buffers=buffers,
                           associations=associations, techniques=techniques, trailer=trailer))
    if c.p != len(data):
        raise ValueError(f'Reviewed group partition exhausts {c.p} of {len(data)} bytes')
    return groups


def inspect(data):
    if identity(data)['sha256'] != SOURCE_SHA:
        raise ValueError('Retained material identity changed')
    version, mo, ms, so, ss, tail, ts = struct.unpack_from('<7I', data)
    if version != 61 or mo != 28 or so != mo + ms or tail != so + ss or tail + ts != len(data):
        raise ValueError('Packed material61 bounds')
    template = data[mo:mo+ms]
    model = export_resources.material_template(template)
    if export_resources.serialize_material(model) != template:
        raise ValueError('Material template no-op mismatch')
    shader = data[so:so+ss]
    header = struct.unpack_from('<12I', shader)
    start, length, ds, dl = header[8:12]
    if header[0] != 43 or not 48 <= start < start+length <= ds < ds+dl <= header[5] < len(shader):
        raise ValueError('Shader43 bounds')
    tables = shader[start:start+length]
    attempts = {}
    for name, parse in [('shader_tables.parse', shader_tables.parse), ('surface_tables.parse', surface_tables.parse)]:
        try:
            parse(tables)
        except ValueError as error:
            attempts[name] = str(error)
        else:
            attempts[name] = 'accepted'
    defaults = export_resources.default_table(shader[header[5]:])
    serialized = export_resources.serialize_defaults(defaults)
    if serialized + bytes(len(shader)-header[5]-len(serialized)) != shader[header[5]:]:
        raise ValueError('Defaults no-op mismatch')
    return dict(material_header=[version,mo,ms,so,ss,tail,ts], shader_header=list(header),
                template_noop=True, defaults_noop=True, registration=identity(tables),
                registration_prefix_words=list(struct.unpack_from('<12I', tables)),
                reviewed_parser_results=attempts), shader
