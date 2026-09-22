# Reverse Engineering RainbowFlame

The intial idea was to fix the stuttering that plagues Darktide together with gir489. However, suddenly
finding a hint on shaders (from HD2) struck me with the idea of having AI reverse engineer the
the findings. That is something I am not capable of doing myself. Once I got the first clues, 
skills for the AI had to be devloped. The following text is a diary from my swedish notes, 
but obviously technically explained by AI to make other developers/AI understand. 
My one single hope by spending all this time, is for other, more skilled programmers, use the
findings to make better mods than I am able to.

## Scope

RainbowFlame changes visual effects that a normal Darktide Lua mod cannot create
or load on its own. The Inferno staff flame, Zealot flamer, wall impacts, and
persistent Soulblaze effects are compiled resources assembled from particle
definitions, materials, textures, shader programs, and external data streams.
Darktide resolves those resources through bundle indexes before DMF Lua code runs.

This document describes how those resources were traced, parsed, changed, rebuilt,
and tested. It is a report on the profiles used by RainbowFlame, not an official
specification for every Stingray or Darktide file. The tooling deliberately rejects
inputs that differ from the layouts established during the investigation.

The work did not involve patching process memory, hooking `Darktide.exe`, modifying
native game code, or bypassing a protection mechanism. The game files were studied
offline. Resource mutations were performed through installed files. Later
investigations also used bounded, read-only LuaExec probes to inspect runtime state;
they did not patch functions or mutate game state.

No extracted Darktide resources are included here. The released mod contains
authenticated delta data rather than complete original bundles.

## Why Lua was not enough

The first question was whether the flame could be changed through particle color
data or a Lua runtime property. That would have been the least invasive solution,
but it did not match the rendering path.

The relevant Inferno materials sample a grayscale main image and a separate RGB
color ramp. Particle `COLOR0.x` is used as one scalar emission multiplier. The
pixel shaders do not use the particle RGB channels as three independent tint
values. Changing an apparent particle RGB curve therefore does not provide an
arbitrary tint for these materials.

There was another limitation. DMF can request resources already known to the game,
but it does not register arbitrary compiled particles, materials, or bundles placed
inside `mods/RainbowFlame`. New wall-impact variants needed valid bundle records and
material streams in the resource structure Darktide already loads.

The final design separates two responsibilities:

- Compiled resources contain the additional material, shader, and particle
  variants.
- Lua selects among those indexed and installed variants and controls hue, brightness,
  opacity, rainbow speed, and the choice of impact preset.

## Evidence standards

Different kinds of evidence had to remain separate throughout the work:

1. A parser accepting a file proves only that the file matches that parser.
2. An identity-preserving round trip proves that known logical resources survived
   reconstruction. It does not prove that Darktide accepts the rebuilt container.
3. A no-op file loading in game establishes acceptance of that physical encoding.
4. A visible targeted change establishes that the selected field participates in
   the observed effect.
5. A result in the Psykanium does not establish every mission, third-person, or
   dedicated-server context.

Where physical encoding or shader repacking changed, unchanged-content controls
were used before targeted visual trials. Later profiles also used exact offline
round trips and preservation checks.

## Using Helldivers 2 as a structural reference

Helldivers 2 was useful because it is also built on a Stingray-derived engine and
has public community tooling for compiled particle and material resources. That
made it a good source of structural leads, but not a specification for Darktide.
The compared source was pinned to exact commits and read rather than imported or
executed.

The main particle references were
[`hd2-particle-modder`](https://github.com/RaidingForPants/hd2-particle-modder/tree/a8193322d6b6e3a50ab460500341e7bc97e657fb)
and
[`HD2_PM_ParticleModder`](https://github.com/USKUMMEL/HD2_PM_ParticleModder/tree/85315558f10046536bd6d7a94ebf1566d92e1316).
Their `ParticleEffect`, `ParticleSystem`, `Visualizer`, `Graph`, and `ColorGraph`
parsers supplied concrete comparison layouts. In particular, they suggested where
to look for visualizer records, material identities, scalar graphs, and
ColorGraph-shaped records containing ten times followed by ten three-component
values.

Those leads made a bounded Darktide-specific search possible. It mapped all nine
records in the retained Inferno particle body, seven material-reference fields,
and nine paired scalar/interleaved-three-component graph records matching the
public `ColorGraph` layout. The public visualizer definitions also provided the
billboard/light interpretation used for comparison. Material hashes, record
extents, graph bounds, key counts, and full-body consumption were then validated
independently against the Darktide bytes.

The distinction mattered because the compared HD2 parsers were not compatible with
the target. They support particle discriminators `0x6d` and later, while this
Darktide resource uses `0x66`. Applying the compared count offset produced
`1,106,247,680`, the 260-byte system header had no bounded match, and the older
color trailer did not match. The retained target's ColorGraph-shaped records also
have an empirically observed trailing key count that the compared HD2 layout does
not decode. We therefore used the shared shapes as search hypotheses and wrote a
restricted decoder from Darktide evidence instead of weakening an HD2 parser until
it accepted the file.

[`Filediver`](https://github.com/xypwn/filediver/tree/3e5f5e5df7e9a382194eb5f6f998b0d6adc8f9b8)
provided a second kind of lead: HD2 GPU-material and standard DXBC container
framing. Its `rawMaterialGPU` layout was also rejected for direct use. On the two
Darktide shader sections it would interpret one word as 37,781 or 38,236 immediate
88-byte entries, requiring more than 3.3 MB from sections of roughly 41 KiB.
Filediver's framing and DXBC code helped identify questions to test, but it did not
supply the Darktide shader43 wrapper or compression envelope.

This comparison shortened the search without turning engine ancestry into a format
claim. Each inference was checked against the target bytes using counts, bounds,
hashes, exhaustive traversal, or independent tooling as applicable. Incompatible
HD2 layouts remained documented negative results.

## Finding the Inferno resource chain

The initial target was:

```text
content/fx/particles/weapons/flame_staff/psyker_flame_staff_code_control.particles
```

The name and resource type were converted to the same seed-zero MurmurHash64A
identities used by the bundle indexes. The indexed resource was found in a
version-8 bundle. Its particle body contained values whose little-endian 64-bit
forms matched material identities in the same resource set.

This produced the dependency chain used for the investigation:

```text
particle resource
    -> material bundle record
        -> external material61 stream
            -> shader43 section
                -> framed DXBC programs
                    -> Shader Model 6.0 DXIL
            -> texture references
                -> grayscale main image
                -> shared RGB ramp
```

The relationship was established through matching identities and parsed references,
not inferred only from filenames. Six material records were retained from the
particle investigation, and their external stream paths were resolved and hashed.

## Darktide format-8 bundle profile

The outer bundle reader was based on the public Darktide version-7/8 support in
[`limn`](https://github.com/manshanko/limn/tree/ca9a36b64be908d105a3a7ddb6022f726e5a1f2b).
RainbowFlame added a restricted writer and stronger preservation checks for the
specific bundles under test.

All integers in the following layouts are little-endian unless stated otherwise.

```text
u64 magic_and_version
u32 resource_count
u8  opaque_bundle_data[256]

resource_count entries:
    u64 type_hash
    u64 name_hash
    u32 mode

u32 chunk_count
u32 chunk_sizes[chunk_count]
padding to the next absolute 16-byte file boundary

u32 logical_decompressed_length
u32 reserved_zero

for each chunk:
    u32 inline_chunk_size
    padding to the next absolute 16-byte file boundary
    u8 chunk_data[inline_chunk_size]
```

For each chunk, `inline_chunk_size` must equal the corresponding entry in
`chunk_sizes[]`.

The observed version-8 magic was:

```text
08 00 00 f0 03 00 00 00
```

Interpreted as a little-endian integer, this is
`0x00000003f0000008`.

Each chunk has a decompressed capacity of `0x80000` bytes, or 512 KiB. A physical
chunk stored with a size of exactly `0x80000` is copied directly. Smaller physical
chunks in the examined files use Oodle compression and decode into that capacity.
The separate logical-length field determines how much of the final decoded chunk is
part of the logical resource stream.

This stored-chunk behavior was useful because an identity-preserving candidate
could be written without implementing an Oodle compressor. The original compressed
chunk was decoded, the complete logical stream and decoded bytes beyond its logical
end were preserved,
and a full 512 KiB stored chunk was emitted.

### Resource index and identity

An index entry is 20 bytes:

```text
u64 type_hash
u64 name_hash
u32 mode
```

The `(type_hash, name_hash)` pair identifies the logical resource. `mode` remains
part of the index and must be preserved, but it is not repeated as part of the
record identity inside the decompressed stream.

The writer preserves index order and rejects duplicate type/name identities. It
does not describe the name hash as a content hash. For the resources examined here,
it is a hash of the resource name resolved with the same MurmurHash64A convention
used by the public reader and dictionaries.

The algorithm that generates unrelated stock `data/...` filenames was not
established. RainbowFlame generates its own names and records explicitly rather
than claiming a general filename derivation rule.

## Logical resource records

The decompressed stream contains sequential resource records. No additional
inter-record alignment was required by the bundles examined.

```text
u64 type_hash
u64 name_hash
u32 variant_count
u32 reserved_zero

variant_count descriptors:
    u32 kind
    u8  first_flag
    u32 body_size
    u8  second_flag
    u32 tail_size

for each descriptor, in descriptor order:
    u8 body[body_size]
    u8 tail[tail_size]
```

The fixed record header is 24 bytes. Each variant descriptor is 14 bytes. A common
single-variant body therefore begins at byte 38 of the raw record.

The restricted parser requires exact stream exhaustion, exact agreement between
index and record order, bounded variant counts, known flag values, and valid body
and tail extents. Those bounds are acceptance policies for the RainbowFlame tools;
they are not claims that no other engine-valid profile exists.

### External material records

The retained stock material records used index mode 4 and one streamed variant.
The body contained a NUL-padded external path such as:

```text
data/85/85d24accc98ef272
```

In the observed stock profile, the body was 30 bytes: 24 printable path bytes and
six zero bytes. Combined with the record header and variant descriptor, the raw
record was 68 bytes.

That 30-byte size is not treated as a universal rule. The record contains an
explicit body length. Generated RainbowFlame records use the actual length of the
new pointer and retain the same logical record structure.

A material stream is not a complete resource by itself. Darktide also needs the
bundle record that supplies its type/name identity, mode, variant information, and
external path.

## The identity-preserving bundle writer

Before changing visual data, a writer was built for one known format-8 profile. It
started from the complete original bundle, not from extracted resources alone.

The no-op writer preserved:

- the version-8 magic;
- the complete 256-byte opaque block;
- every ordered index entry and mode;
- every record identity and variant descriptor;
- all bodies, tails, references, and opaque record bytes;
- the logical stream length;
- known alignment bytes;
- decoded bytes after the logical end of the final chunk.

The target round trip contained 19 resources. The original and rebuilt bundle were
independently extracted with the pinned public reader, and all 19 raw records
matched exactly. The physical container bytes differed because the rebuilt bundle
used a full stored chunk instead of the original compressed chunk.

The writer rejects unsupported versions, duplicate identities, truncation,
inconsistent chunk tables, invalid alignment, unknown nonzero padding that cannot
be preserved, malformed variants, index/record disagreement, reordered records,
and unconsumed logical or physical data.

Only after that offline round trip passed was an unchanged logical bundle tested
in game. This no-op deployment separated the question "can we edit this format?"
from "will Darktide accept this physical encoding?"

## Particle RGB trial

The first color candidate changed 32 bytes in particle data that appeared to hold
active neutral RGB triples. It retained green-channel intensity, timing, opacity,
and all other resources. The rebuilt candidate parsed correctly and differed only
at the intended locations.

In game, the no-op bundle remained visible but the edited candidate did not. The
binary edit was controlled; the interpretation was wrong.

Later shader analysis explained the failure. The particle color path contributes
`COLOR0.x` as a scalar emission gain. Zeroing the wrong first component can remove
the emitted RGB contribution instead of turning the result green. Exact byte
editing did not establish field semantics.

Arbitrary particle-curve trials stopped at that point. The next work moved to the
materials and shaders that actually produced color.

## Material61 profile

The relevant external material streams began with seven 32-bit fields:

```text
offset 0x00: version
offset 0x04: material_template_offset
offset 0x08: material_template_size
offset 0x0c: shader_offset
offset 0x10: shader_size
offset 0x14: following_section_offset
offset 0x18: following_section_size
```

For the first two flame materials, `version` was 61 and the material template began
at byte 28. The shader section immediately followed the template. A four-byte zero
section followed the shader.

When the shader size changed, the writer changed only fields whose relocation
behavior had been established:

- shader size at material byte 16;
- following-section offset at material byte 20.

The material template, resource references, and following section were preserved.
The parsed template contains counted tables, a values area, and opaque fixed-width
records. The builder checks all self-relative table offsets but does not assign
unsupported meanings to opaque fields.

## Shader43 profile

The material shader section used a 12-word header:

```text
u32 version                         // 43
u32 opaque
u32 contexts_offset
u32 context_count
u32 conditions_offset
u32 default_data_offset
u32 dependency_offset
u32 dependency_count
u32 group_data_offset
u32 group_data_size
u32 device_data_offset
u32 device_data_size
```

For the original two Inferno materials, the exact profile contained contexts,
dependencies, one resource group, buffer descriptors, associations, opaque
technique/state data, a device-data area, and a self-relative default-data table.

Only two shader header fields needed relocation for the initial hue-cycle build:

- the default-data start at byte 20;
- the device-data size at byte 44.

The device-data start and all pre-device regions were preserved. Default payload
offsets were recalculated according to their established self-relative convention.
Padding before default data was recomputed as zero padding to a four-byte boundary,
and terminal shader padding was recomputed to a 16-byte boundary.

Later impact and flamer materials used larger profiles with different resource
groups and program counts. Each additional profile has independent count, extent,
round-trip, and preservation checks.

## Framed shader programs

The first two Inferno materials each contained four programs in device data. Across
the pair, eight programs were decoded. They consisted of a vertex shader, a color
pixel shader, another vertex shader, and a pixel shader with no color output.

Each program used this envelope:

```text
u32 envelope                         // observed value 1
u32 frame_length
u8  frame[frame_length]

u32 metadata_kind                    // observed value 5
u32 decoded_dxbc_length
u64 frame_key
counted metadata tables and opaque state
```

The semantic names of the constant values 1 and 5 remain unassigned. They are
preserved because their behavior was not needed to rebuild the target.

### Kraken framing

Every original frame began with:

```text
8c 06
three-byte big-endian quantum header
compressed payload
```

For the observed single-quantum frames:

```text
big_endian_24_value + 1 == frame_length - 5
```

The public Kraken decoder behavior used during the investigation has a stored
branch: when packed payload size equals requested output size, the payload is
copied. This made it possible to serialize a changed program without an Oodle
compressor:

```text
8c 06
big_endian_24(decoded_dxbc_length - 1)
exact DXBC bytes
```

This is bounded to the established one-quantum size profile. It is not a general
encoder for arbitrary Oodle streams.

### Program frame key

The 64-bit key in program metadata was determined across all eight original
records:

```text
frame_key = MurmurHash64A(complete_frame, seed=0)
```

The hashed input includes `8c 06`, the three-byte quantum header, and the complete
compressed or stored payload. It excludes the preceding envelope and all following
metadata.

Sixteen candidate models were compared across eight records. Only seed-zero
MurmurHash64A over the complete frame matched all eight. Hashes of decoded DXBC,
DXIL, STAT, reflection data, zeroed containers, and partial digests did not match.

This establishes how to reproduce the serialized value for this profile. It does
not establish how the engine uses that key for caching or deduplication.

## DXBC and DXIL reconstruction

Each decoded program was a complete DXBC container with seven contiguous chunks:

```text
SFI0
ISG1
OSG1
PSV0
STAT
HASH
DXIL
```

The programs contained Shader Model 6.0 DXIL and valid LLVM bitcode. Microsoft's
[DirectX Shader Compiler](https://github.com/microsoft/DirectXShaderCompiler)
accepted and independently disassembled all eight containers.

The changed shaders were not built by editing opaque bytes and retaining stale
reflection data. The process was:

1. Decode and disassemble the original executable and STAT programs.
2. Recover typed resources and annotations from STAT.
3. Reinsert the exact original executable body into the typed module.
4. Restore the observed validator version and remove stale `dx.counters` metadata.
5. Assemble a typed no-op control and the changed module through DXC.
6. Let DXC regenerate reflection and counters.
7. Validate and sign the complete container with a separately pinned validator.
8. Disassemble the complete output and its STAT program independently.

For the hue-cycle shaders, full buffer layouts, names, field offsets, resource
types, and bindings remained equal. `SFI0`, `ISG1`, `OSG1`, and `PSV0` were
byte-identical. Instruction counts agreed with regenerated STAT metadata. The
typed no-op executable body matched the original disassembly.

## The Inferno color equation

Shader reflection connected the material texture hashes to two roles:

- a BC4 main image sampled through its red channel;
- a shared BC1 color ramp sampled as RGB.

The pixel shader obtains descriptor indices from material data at runtime. There
is no fixed `t1 = main` and `t2 = ramp` relationship; the source fields and their
uses had to be followed through the DXIL.

Let:

```text
H(x) = x*x*(3 - 2*x)
sat(x) = clamp(x, 0, 1)
```

For ordinary finite values, the established color path is:

```text
S = sample(main, uv).r
q = H(sat(S / threshold))
L = sample(shared_ramp, (q, q)).rgb
E = material_emission * COLOR0.x
D = sat((abs(scene_depth.r) - view_depth) / depth_scale)

coverage = material-specific function of D, COLOR0.w, and q

output.rgb = coverage * fog_term * (1 + emissive_intensity) * E * L
output.a   = 0
```

This is the color pixel shader output before render-target blending, exposure, and
postprocessing. It is not a final screen-pixel equation.

The analysis showed that hue comes from `L`, the shared RGB ramp. `COLOR0.x`
scales all RGB channels together. Other particle color values are forwarded, but
these color pixel shaders do not consume them as independent RGB tint inputs.

## Proving the ramp route with green

Before attempting an animated shader, the complete small color-ramp stream was
rebuilt. Its observed profile was:

```text
u32 kind
u32 packed_size
u32 unpacked_size
compressed complete DDS
156 bytes of retained texture metadata
```

The decoded texture was a 512 by 8, one-mip BC1 texture. A stored-codec no-op was
tested before the changed texture. The green candidate converted each decoded
ramp texel to a green value while preserving intensity behavior and all wrapper
metadata.

The user reported a visible green first-person flame in the Psykanium and supplied
a screenshot. The screenshot was conversation evidence and was not retained as a
local artifact. The main bundle and particle curves remained unchanged during that
test. This was the first runtime evidence that the shared ramp, rather than the
guessed particle fields, was the correct hue path.

The shared ramp could have other consumers, so replacing it was useful as a proof
but not the final isolated design.

## Building the animated hue cycle

Both color pixel shaders already read a viewport constant buffer at `cb0, space0`.
The field at byte 1440, `c90.x`, is used by existing feedback logic. It provided a
shader clock without adding a new binding or inventing a Lua-to-GPU time channel.

The inserted operation runs after the original ramp sample and immediately before
the original RGB multiplications:

```hlsl
float value = max(rampRGB.r, max(rampRGB.g, rampRGB.b));
float hue = frac(shaderTime * 0.125 + 1.0 / 3.0);
float3 unitRGB = saturate(
    abs(frac(hue + float3(0, 2.0 / 3.0, 1.0 / 3.0)) * 6 - 3) - 1
);
float3 newRGB = value * unitRGB;
```

The sequence is green, cyan, blue, magenta, red, yellow, then green again. Sampled
RGB determines amplitude through `max(r, g, b)` but no longer determines hue or
phase.

Only the three original RGB consumers were redirected. Texture sampling, descriptor
selection, min-LOD handling, streaming feedback atomics, branches, depth coverage,
emission gain, fog, and alpha output remained in their original paths.

The factor `0.125` gives a period of eight shader-time units. Those units were not
proven to be seconds. Epoch, pause behavior, time scaling, and synchronization
between viewports were also not established. The effect uses continuous global
phase and does not restart when firing begins.

The two material streams were first rebuilt with unchanged shader bytecode but new
stored framing. The user reported that the no-op retained the previous appearance.
The hue-cycle streams were then installed, and the user reported that the animated
whole-flame rainbow worked in first-person Psykanium testing. No retained video or
measured cycle period accompanies that report.

## Inferno wall-impact presets

A static custom staff color needs a compatible impact color. The target impact
material profile contained 32 framed programs and eight resource groups.

Program analysis isolated eight color pixel shaders at indices:

```text
1, 5, 9, 13, 17, 21, 25, 29
```

The other 24 programs were preserved exactly.

For each color shader, the builder verifies one expected ramp sample and traces its
texture and sampler handles back to the established descriptor fields. It locates
the three sampled RGB results and requires exactly one downstream consumer for
each. The transform replaces those consumers with a fixed color scaled by sampled
green-channel amplitude. Downstream shaping and alpha remain unchanged.

Eight presets were built:

```text
Red       0 degrees
Orange   30 degrees
Yellow   55 degrees
Green   120 degrees
Cyan    180 degrees
Blue    240 degrees
Violet  275 degrees
Pink    325 degrees, reduced saturation
```

The impact bundle originally contained 30 records. The builder:

- preserves all 30 stock records byte-for-byte and in original order;
- generates one cloned particle identity per preset;
- generates one parent and three child material identities per preset;
- adds 40 records;
- writes 32 external material streams;
- rejects generated identity collisions;
- verifies every rewritten parent and child reference occurs exactly once;
- rereads the completed bundle and verifies identities and record counts.

The parent material is the only stream whose eight color programs change. Each
child material is cloned with its parent reference redirected. Each cloned particle
has its three child references redirected. This isolates presets from the stock
effect rather than globally replacing the original identity.

Lua maps the hue setting to the nearest of these eight indexed and installed
presets. Original and Rainbow modes use the original impact. Green was the first
live proof. The user later reported that all eight presets worked, but no retained
per-color capture or measured visual test matrix accompanies that report.

## Extending the method to the Zealot flamer

The flamer work reused the established container and shader methods but did not
assume that the Inferno particles or material tables were identical.

Four target particle resources were located by hashed path and type identity:

```text
content/fx/particles/weapons/rifles/player_flamer/flamer_code_control
content/fx/particles/weapons/rifles/player_flamer/flamer_code_control_burst
content/fx/particles/weapons/rifles/player_flamer/flamer_code_control_3p
content/fx/particles/weapons/rifles/zealot_flamer/zealot_flamer_impact_delay
```

They cover the braced stream, primary burst, third-person stream, and wall impact.
Each had one format-8 index match in the inspected bundle set.

### Stream particle selection

The three stream particles contain multiple cloud systems. Only the billboard
records that route through the selected material chain were renamed:

| Stream | Cloud systems profiled | Selected records |
|---|---:|---:|
| Continuous | 10 | 4 |
| Burst | 10 | 5 |
| Third-person | 11 | 3 |

Each old 32-bit cloud identifier was required to occur exactly once at its decoded
field. New identifiers were checked against stock and generated identities. All
non-particle bundle records remained byte-identical, and replacing new identifiers
with old ones had to reconstruct the original logical stream exactly.

The selected records resolve through one child material and two shader-bearing
parent material profiles. One parent contains 19 programs, including three compute
programs. Four color pixel shaders are targets and 15 frames remain unchanged. The
other parent contains 48 graphics programs. Twelve color pixel shaders are targets
and 36 frames remain unchanged.

The parents use different material-buffer sizes and allocation layouts. Their new
control exports were appended at profile-specific offsets rather than copied from
the Inferno offsets.

### Runtime controls in the material buffer

Two exports were added:

```text
rainbow_flame_hsv_enable : float4
rainbow_flame_cycle      : float2
```

The first vector carries normalized hue, opacity, brightness, and mode. The second
carries rainbow enable and speed. The established mode contract is:

```text
mode == 0  -> untouched stock RGB; opacity ignored
mode == -1 -> original sampled RGB scaled by opacity
mode > 0   -> selected hue with brightness and opacity
cycle.x > 0 -> animated hue using time * cycle.y
```

The animated path includes a smooth transition through the sampled original ramp.
Lua supplies separate staff and flamer settings and writes both control vectors to
every cloud in the identified profile.

The flamer is additive. Its opacity option therefore scales visible stream
intensity rather than behaving like ordinary translucent alpha blending. Impacts
ignore opacity.

### Flamer impact graph

The Zealot impact particle contains eight cloud records. Records 0 through 3 form
the selected color-bearing material graph; records 4 through 7 remain routed to
stock resources.

Each of the eight presets generates seven identities:

1. one particle effect;
2. two custom parent materials;
3. four custom child materials.

The stock impact package contains 43 records. The completed profile adds 56 records
and reaches 99 records. It writes 48 external material streams. All 43 original
records remain byte-identical.

One parent reuses the already verified staff fixed-color authoring path. The other
uses the separately established 48-program profile. Both parent transformations,
all child reference rewrites, and all particle reference rewrites are required to
reverse exactly to their originals.

Lua again chooses the nearest preset only for fixed Color mode. Original and
Rainbow retain the stock impact, and brightness and opacity do not affect impacts.

### Flamer runtime evidence

The active README records user testing of the primary burst, braced stream,
Rainbow mode, a fixed-color impact, opacity, and independence from staff settings.
The retained build reports establish offline validation but do not contain a
separate in-game capture for those checks. Teammate third-person flamer rendering,
regular missions, and dedicated-server behavior were not claimed as user-tested at
the time of writing.

## Persistent enemy Soulblaze

Enemy Soulblaze uses a separate cloned particle and material graph. The builder
indexes and installs hidden, original-opacity, and fixed-color variants while
preserving stock records and checking every rewritten reference. Lua selects hidden
at 0 percent opacity, original-opacity variants at 25, 50, or 75 percent, or one of
eight colors at 25, 50, 75, or 100 percent.

The setting affects newly created, locally rendered persistent Soulblaze effects.
Existing effects retain the resource selected when they were created. The visual
selection does not change damage, buffs, networking, or gameplay state.

Staff color, flamer color, impacts, and enemy Soulblaze remain separate controls.

## From research scripts to release payload

The final builders are fail-closed. Before using retained inputs, they check exact
SHA-256 identities. They refuse an unexpected material version, shader version,
section boundary, record count, program count, table width, descriptor extent,
reference count, hash, or generated identity collision.

Production invariants include:

- every original record remains byte-identical unless it is an explicit target;
- every unselected shader frame and metadata block remains byte-identical;
- untargeted template, default, binding, and tail data are preserved; intentional
  exports, defaults, and material-buffer changes are validated separately;
- changed DXBC is independently validated and reflected;
- generated bundles are parsed again after serialization;
- payload files are authenticated by size and SHA-256;
- no output is accepted merely because one parser can open it.

The installer payload uses COPY/INSERT operations and authenticated insert blobs
instead of shipping full extracted game bundles. A replacement can be reconstructed
only from the expected stock input. Unknown source bytes are rejected.

## Installation and rollback safety

Compiled-resource modification has a different risk profile from an ordinary Lua
mod. RainbowFlame's installer therefore treats file identity and ownership as part
of the format contract.

Before installation it verifies:

- the selected Darktide root;
- the supported Steam build and executable version;
- DML and DMF dependencies;
- that Darktide is stopped;
- every payload hash;
- every stock input hash;
- that additions are absent or already owned exact outputs;
- that managed paths contain no reparse points.

Writes are staged on the target volume, journaled, flushed, replaced, and verified.
Original replacement files receive versioned SHA-256-checked backups. Additions are
tracked through an ownership receipt. Uninstall restores only authenticated files
owned by the matching release.

`Repair after update` relaxes only the Steam build and executable version check.
Before creating a new operation journal or writing a file, it checks the complete
managed set. Every replacement must be either the exact RainbowFlame output or the
exact known stock input. Every addition must be absent or the exact owned output.
Receipt metadata and uninstall backups must also match.

If Fatshark changes one required resource, repair stops before writing. The feature
can recover from updates that merely overwrite modded files but cannot promise
compatibility with every future Darktide build.

## A reproducible workflow for similar research

The method can be reused, but target-specific layouts cannot be assumed.

1. Identify one exact resource by type/name identity and retain its complete source
   bundle, index entry, mode, and SHA-256.
2. Follow references from the particle to material records and external streams.
   Do not classify unknown integers as references without independent evidence.
3. Implement a bounded reader that exhausts the input and rejects unknown layouts.
4. Build an identity-preserving round trip before authoring a change.
5. Compare every ordered record with an independent reader.
6. Test the no-op physical encoding in game with an exact rollback copy.
7. Form one narrow semantic hypothesis and change the smallest possible region.
8. Treat a failed visual result as evidence about semantics, not as permission to
   broaden the edit.
9. If shaders control the result, recover complete programs, typed bindings, and
   reflection. Rebuild metadata rather than copying stale data.
10. Preserve every unrelated program, table, state block, and opaque field.
11. Test an unchanged-bytecode material rebuild before the changed shader.
12. Record exact build, context, hashes, observations, rollback, and untested areas.
13. Convert the working experiment into a hash-pinned builder and authenticated
   installer. Do not distribute complete extracted game files.

For another particle, material family, texture profile, or shader43 variant, repeat
the profiling steps. A successful Inferno profile is evidence for the method, not
for identical layouts elsewhere.

## What remains unknown

The work does not establish:

- the semantics of every byte in the 256-byte bundle block;
- universal meanings for all index modes or variant flags;
- the algorithm behind stock external `data/...` filenames;
- a general-purpose Darktide bundle registration API;
- arbitrary patch precedence in the bundle database;
- a universal material61 or shader43 schema;
- the meaning of every state, association, and technique field;
- the engine's cache use of the shader frame key;
- exact wall-clock units for `global_viewport.time`;
- final screen color after blending, exposure, and postprocessing;
- every consumer of shared materials;
- future-build compatibility;
- dedicated-server execution or every third-person rendering context.

The absence of those answers is reflected in the tooling. Unknown profiles are
rejected rather than normalized or guessed.

## Public references and publication boundary

The outer bundle work was cross-checked against the public `limn` reader at commit
[`ca9a36b64be908d105a3a7ddb6022f726e5a1f2b`](https://github.com/manshanko/limn/tree/ca9a36b64be908d105a3a7ddb6022f726e5a1f2b).
Shader assembly, validation, reflection, and disassembly used pinned builds and
source references from Microsoft's
[DirectX Shader Compiler](https://github.com/microsoft/DirectXShaderCompiler).

Useful findings that can be shared are layouts, algorithms, preservation rules,
pseudocode, hashes, validation strategy, and RainbowFlame's own tooling. Publishing
those findings does not require distributing the underlying game data.

The following should not be redistributed as part of an RE write-up:

- original or rebuilt complete Darktide bundles;
- extracted particle records or material streams;
- original texture or DDS exports;
- decoded original DXBC, DXIL, or STAT blobs;
- rollback copies from an installed game;
- Oodle binaries taken from the game;
- broad dictionary or resource dumps.

RainbowFlame's release payload follows that boundary. Users supply their own
supported stock files, and the installer accepts them only when their identities
match the authenticated release manifest.

## Result

RainbowFlame was not produced by finding one undocumented color constant. The
retained evidence supports this sequence:

1. locate the exact flame resources;
2. map particle, material, texture, and shader dependencies;
3. build a logical-record-preserving format-8 writer;
4. prove the physical no-op bundle loads;
5. reject a failed particle-color interpretation;
6. decode the shader programs and establish the color equation;
7. prove the RGB ramp route with a fixed-green runtime result;
8. identify an existing shader clock;
9. rebuild valid reflected and signed DXIL;
10. derive the framed-program hash and serializer rules;
11. pass unchanged-bytecode material no-ops;
12. confirm animated whole-flame shaders in game;
13. clone, index, and install isolated impact and Soulblaze presets;
14. extend the method to separately profiled flamer streams and impacts;
15. package the result as authenticated, reversible deltas.

The exact files and offsets belong to the tested profiles. Each additional target
requires its own profile and runtime validation.
