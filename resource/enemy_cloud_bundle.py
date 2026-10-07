"""Offline cloud-name fix for the globally loaded enemy-assets bundle.

Uses the retained format-8 layout and pinned offline Oodle decoder. Only the
chunk containing buff_warpfire may change; all other compressed chunks survive.
Never writes installed resources. Output must be a fresh analysis directory.
"""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "docs/analysis-rainbow-enemy-sync-20260919-g1"))
baseline = importlib.import_module("build_candidate")
fmt = baseline.fmt
NAME = "30ebeee18093c079"
STOCK_SHA = "53fd3e19870d70e18377151233f3aa3a141ead0339c55ad4dd83b4625fa5e531"
PARTICLE_SHA = "2cee810ec3e74753f7e2617f47ff065320223642c5bd09f0fffb84183ffe3a88"


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read(data, decoder):
    require(len(data) <= 64 * 1024 * 1024, "Physical bound")
    c = fmt.Cursor(data)
    require(c.take(8) == fmt.MAGIC, "Format-8 header")
    count, = c.unpack("<I")
    require(count == 711, "Exact enemy-assets index count")
    c.take(256)
    index = [c.unpack("<QQI") for _ in range(count)]
    require(len({entry[:2] for entry in index}) == count, "Duplicate identity")
    prefix = data[:c.pos]
    chunks, = c.unpack("<I")
    require(1 <= chunks <= 128, "Chunk count bound")
    sizes = [c.unpack("<I")[0] for _ in range(chunks)]
    require(all(0 < size <= fmt.CHUNK for size in sizes), "Chunk sizes")
    table_padding = c.align()
    length, zero = c.unpack("<II")
    require(zero == 0 and 0 < length <= 128 * fmt.CHUNK
            and (length + fmt.CHUNK - 1) // fmt.CHUNK == chunks, "Logical length")
    blocks, pads = [], []
    for size in sizes:
        require(c.unpack("<I")[0] == size, "Inline chunk size")
        pads.append(c.align())
        blocks.append(c.take(size))
    require(c.pos == len(data), "Trailing physical bytes")
    decoded = [block if len(block) == fmt.CHUNK else decoder(block) for block in blocks]
    require(all(len(block) == fmt.CHUNK for block in decoded), "Decoded sizes")
    full = b"".join(decoded)
    bundle = fmt.Bundle(prefix, index, table_padding, pads, full[:length], full[length:], sizes)
    fmt.records(bundle)
    return bundle, blocks


def serialize(bundle, blocks):
    out = bytearray(bundle.prefix)
    out.extend(struct.pack("<I", len(blocks)))
    out.extend(struct.pack("<" + "I" * len(blocks), *(len(block) for block in blocks)))
    require(len(bundle.table_padding) == (-len(out)) % 16, "Table alignment")
    out.extend(bundle.table_padding)
    out.extend(struct.pack("<II", len(bundle.logical), 0))
    for block, old_pad in zip(blocks, bundle.chunk_padding):
        out.extend(struct.pack("<I", len(block)))
        needed = (-len(out)) % 16
        require(len(old_pad) == needed or not any(old_pad), "Nonzero relocated padding")
        out.extend(old_pad if len(old_pad) == needed else bytes(needed))
        out.extend(block)
    return bytes(out)


def build(source):
    require(sha(source) == STOCK_SHA, "Enemy-assets baseline drift")
    require(baseline.assets.index.murmur("content/characters/enemy/enemy_character_assets")
            == int(NAME, 16), "Global package identity")
    decoder = baseline.decoder()
    bundle, blocks = read(source, decoder)
    require(serialize(bundle, blocks) == source, "No-op physical roundtrip")
    records = fmt.records(bundle)
    identity = (baseline.assets.index.murmur("particles"),
                baseline.assets.index.murmur(baseline.PARTICLE_NAME), 0)
    target = records[82]
    require(target["identity"] == identity and sha(target["raw"]) == PARTICLE_SHA,
            "Exact target particle")
    require(len(target["bodies"]) == 1, "Target variants")
    start, body, tail = target["bodies"][0]
    require(not tail and struct.unpack_from("<I", body, 44)[0] == 0x9C85CCEF,
            "Original cloud word")
    new_id = baseline.assets.index.murmur(baseline.CLOUD_NAME) >> 32
    require(new_id == 0xC26CF312, "Authored cloud hash")
    offset = start + 44
    chunk, within = divmod(offset, fmt.CHUNK)
    require(within + 4 <= fmt.CHUNK, "Cloud word crosses chunk")
    full = bundle.logical + bundle.final_padding
    replacement = bytearray(full[chunk * fmt.CHUNK:(chunk + 1) * fmt.CHUNK])
    struct.pack_into("<I", replacement, within, new_id)
    edited_blocks = list(blocks)
    edited_blocks[chunk] = bytes(replacement)
    candidate = serialize(bundle, edited_blocks)
    after, after_blocks = read(candidate, decoder)
    after_records = fmt.records(after)
    changes = [i for i, (a, b) in enumerate(zip(bundle.logical, after.logical)) if a != b]
    require(changes == list(range(offset, offset + 4)), "Exact four-byte logical change")
    require(len(after.logical) == len(bundle.logical) and after.prefix == bundle.prefix
            and after.final_padding == bundle.final_padding, "Envelope preservation")
    require(all(a == b for i, (a, b) in enumerate(zip(blocks, after_blocks)) if i != chunk),
            "Unrelated compressed chunk changed")
    require(all(a["raw"] == b["raw"] for i, (a, b) in enumerate(zip(records, after_records))
                if i != 82), "Unrelated resource changed")
    primary = fmt.read((baseline.GAME / "bundle/28d55df9efb7f8e5").read_bytes())
    require(after_records[82]["raw"] == fmt.records(primary)[0]["raw"],
            "Global and h1 standalone particle disagree")
    report = {"status": "OFFLINE CANDIDATE; NOT INSTALLED; NATIVE SURFACE LOOKUP UNTESTED",
              "target": str(baseline.GAME / "bundle" / NAME),
              "package": "content/characters/enemy/enemy_character_assets",
              "original_sha256": sha(source), "candidate_sha256": sha(candidate),
              "original_bytes": len(source), "candidate_bytes": len(candidate),
              "logical_bytes": len(bundle.logical), "chunks": len(blocks),
              "changed_chunk": chunk, "changed_logical_offsets": changes,
              "unchanged_resources": len(records) - 1,
              "unchanged_compressed_chunks": len(blocks) - 1,
              "global_particle_equals_h1_standalone": True,
              "noop_roundtrip": True, "installed_writes": 0}
    return candidate, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    require(output.is_dir() and output.is_relative_to(ROOT / "docs"), "Existing docs output directory")
    paths = [output / (NAME + suffix) for suffix in (".EXPERIMENTAL.bundle", ".stock.rollback")]
    manifest = output / "candidate-manifest.json"
    require(not any(path.exists() for path in paths + [manifest]), "Refusing overwrite")
    source = (baseline.GAME / "bundle" / NAME).read_bytes()
    candidate, report = build(source)
    for path, data in zip(paths, (candidate, source)):
        with path.open("xb") as stream:
            stream.write(data)
        require(sha(path.read_bytes()) == sha(data), "Output readback")
    with manifest.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
