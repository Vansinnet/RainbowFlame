# RainbowFlame design notes

The resource research and the history of every edit are in
[REVERSE_ENGINEERING.md](REVERSE_ENGINEERING.md). This file holds how the payload is kept working.

## Rebuilding the payload after a game update — 2026-10-27

RainbowFlame's 166 Reforge files are edits of stock resources: 8 replaced material streams, 152
preset streams in `payload/direct/data/rf` cloned from 11 stock materials, 5 weapon effect bundles
with renamed cloud identifiers, and the preset host package `ac7ddd2788c1ef1f` (late load: the stock
debug package plus 204 records cloned from the Soulblaze, staff impact and flamer impact packages).
The builders in `resource/` that authored them are pinned to build 24735202 and import research
modules that no longer exist, so they cannot be rerun.

`resource/rebuild_payload.py` replaces them for game updates. When `reforge verify` reports
changed files after a patch, run from the workspace root (Windows, game installed):

    python mods/active/RainbowFlame/resource/rebuild_payload.py

It rebuilds all 166 files from the installed stock, pins the new stock hashes with `reforge add`
(keeping `late_load`), records a new recipe and runs `reforge build`. Then run `reforge verify`,
review `git status`, test in game and commit the payload, `reforge.json`, the manifest and the
recipe together. `--out <folder>` writes the rebuilt files there and changes nothing in the mod.

How it works: `resource/rebuild_recipe.json` records, for every payload file, its stock origin and
how that stock differs from the payload: reverse patches of the material template, registration
buffer, shader defaults and device segments; the stock body of every edited shader program as a
line patch of the payload's disassembly (99 programs); the swapped identifiers in the 5 bundles and
in the cloned particles. Payload plus recipe stand in for the stock the payload was built from,
without keeping game files. A rebuild is a three-way merge of that stock, the payload and the
installed stock: parts only RainbowFlame changed come from the payload, parts only the game changed
come from the new stock, and every edited program is transplanted onto the new stock program
through an SSA alignment, reassembled and signed with DXC (`tools/dxc`, Microsoft's release; v1.9.2609
here). This is the method of the v62 update (`analysis/v62-update-20261003/rebase`), ported to
Windows DXC through ctypes and made self-contained. The origins of the 152 preset streams are
found by following the clones: each cloned particle names custom materials where its stock source
named stock ones, and each custom child names custom parents where its stock child named stock
parents.

It stops, naming the file, on anything it cannot merge mechanically: a new material or shader
version, a changed frame count, a part both sides changed (for example a stock child material that
gains a variable, which RainbowFlame also extends), an edited instruction that no longer aligns,
an identifier that is gone or no longer unique, a bundle chunk that no longer fits the stock
layout. That needs the stopped file's builder and REVERSE_ENGINEERING.md again. The recipe belongs
to the payload it was recorded with (`payload_sha256`); after changing the payload by other means,
record it again with `--record` while the installed stock still matches the pins.

Evidence (offline, 2026-10-27, Darktide 1.13.3, `reforge verify` 166 of 166):

- Identity: run with `--out` against the installed stock, all 166 files are byte-identical to the
  committed payload (compared with the Git blobs); 404 frames (99 distinct programs) were
  transplanted and recompiled, not copied. Windows DXC 1.9.2609 reproduces the programs Linux DXC
  1.9.2607 built for 1.4.1. A real run leaves `git status` clean apart from the two new files and
  writes an identical recipe.
- Replay of the October update: a recipe recorded from the 1.4.0 payload (Git) against v61 stock,
  then a rebuild onto the installed v62 stock, gives all 166 files byte-identical to the shipped
  1.4.1 payload, with 156 changed stock origins and 384 transplants onto changed programs. The v61
  stock came from the copies kept in `analysis/` (16 files, matched by the v62 rebase's input
  hashes); 5 child materials without a kept copy were made by setting the version word to 61, which
  is the only difference measured on the 5 children that have both copies. 4 replaced shader streams
  (`03f68803`, `809f0435`, `85d24acc`, `a124af34`) have no kept v61 copy and were replayed from their
  1.4.1 versions, so the replay does not cover their cross-version step.
- A material stamped version 63 stops the run with the file and the reason.

Not covered: a patch that changes something both sides edited (it stops; it does not merge), and
anything in game. The pipeline changes no runtime Lua and produced no new payload bytes, so there
is nothing new to test in game until it rebuilds for a real patch; then the README's smallest
check applies (fresh start, `/reforge` all active, staff, flamer, impact and Soulblaze colours).
