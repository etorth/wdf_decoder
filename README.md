# MHXY resource collection and WDF / WAS decoder

This directory contains decoded Menghuan Xiyou (梦幻西游 / MHXY) resources,
local browsing galleries, their original resource files and the Python tools
used to export them.

## Where these files came from

| Directory | Source | Contents |
| --- | --- | --- |
| `shape1_decode/` | User-supplied `/home/anhong/win_download/m5_media/shape1.wdf` | 229 SP resources, 7,521 PNG frames, raw WAS files and an animation gallery |
| `smap_decode/` | User-supplied `/home/anhong/win_download/m5_media/smap.wdf` | 143 SP resources, 143 PNG images, raw WAS files and a gallery |
| `shape_wd1_decode/` | User-supplied `/home/anhong/win_download/m5_media/shape.wd1` | 284 numeric text resources under `raw/`, plus an index; no sprite images |
| `team_leader_decode/` | Standalone `game/res/addon/2231ebb4` from JavaXYQ, linked below | Team-leader overhead token, ID `0x2231EBB4`, with 16 PNG frames and the original WAS |
| `javaxyq_resources_decode/` | Full export of the JavaXYQ repository, revision below | Searchable gallery, decoded sprites/maps, existing images/audio and byte-exact originals |

The user-supplied archives were already available locally; they were not
downloaded by these tools. Their earlier provenance has not been independently
verified, and the original WDF containers remain at the external paths above.
Their extracted entries are retained in each export's `raw/` directory.
No MHXY installer was downloaded.

### JavaXYQ source and revision

- Repository: [valuetodays/javaxyq-im](https://github.com/valuetodays/javaxyq-im).
- Exported commit: [`65721a683c61c4393f281db3bac805bc41cf8f8d`](https://github.com/valuetodays/javaxyq-im/tree/65721a683c61c4393f281db3bac805bc41cf8f8d).
- Upstream README credits the earlier project
  [kylixs/javaxyq](https://github.com/kylixs/javaxyq).
- Standalone team-leader token:
  [`game/res/addon/2231ebb4`](https://github.com/valuetodays/javaxyq-im/blob/65721a683c61c4393f281db3bac805bc41cf8f8d/game/res/addon/2231ebb4).

The temporary `javaxyq-im/` clone, including its `.git/` packfiles, has been
removed. **All 2,212 non-Git files from that revision remain byte-for-byte
under `javaxyq_resources_decode/originals/`**, with paths preserved.
The export's `manifest.json` records their SHA-256 hashes and generated
outputs; `provenance.json` records the repository and commit.
The clone is not needed to browse any of the exported galleries.

The token was identified by client code in
[`a565551313/MHXY2`](https://github.com/a565551313/MHXY2/blob/4c1169e6f16ef15f4606a473557e31c1b8a6f9ca/客户端源码/script/全局/玩家.lua),
which loads `0x2231EBB4` as the team marker and draws it above the leader.
The resource table in
[`oceancx/CXEngine`](https://github.com/oceancx/CXEngine/blob/35dba2be2e217314b24ebe9b0d269e7aae06b7b9/assets/tables/ini/addon.wdf.ini)
also labels the ID as the team status icon. These were identification
references, not the downloaded asset source.

### Browsing and version control

Open `javaxyq_resources_decode/index.html` directly in a browser for the
searchable collection, or `team_leader_decode/index.html` for the token.
Each other image export has its own `index.html`.

Decoded outputs and preserved originals are intentionally **not ignored**
by `.gitignore`, so they can be tracked with this directory as a single Git
repository. Python caches, `.venv/` and a future temporary `javaxyq-im/`
clone are ignored. No Git repository has been initialized here by this cleanup.

**Rights:** these are third-party game assets, not assets authored for this
decoder. Downloading, extracting or tracking them does not grant permission
to redistribute them. Verify the relevant licenses and permissions before
publishing this directory. The libm5 MIT notice applies to the referenced
decoder material, not automatically to the game assets or JavaXYQ files.

## Decoder tools

A Python 3.9+ command-line decoder for classic Menghuan Xiyou (梦幻西游)
`PFDW` archives and embedded `SP` / WAS / TCP sprites. Uses only the Python
standard library; no installation or Windows runtime required.

## Usage

```sh
# List resource IDs, byte offsets, sizes and types.
python3 wdf.py list /home/anhong/win_download/m5_media/shape1.wdf

# Decode every sprite and retain the original resources.
python3 wdf.py decode /home/anhong/win_download/m5_media/shape1.wdf -o shape1_decode

# Extract raw resources without image decoding.
python3 wdf.py extract /home/anhong/win_download/m5_media/shape1.wdf -o shape1_extract

# Select specific IDs: decimal, or hexadecimal with a 0x prefix.
python3 wdf.py decode /home/anhong/win_download/m5_media/shape1.wdf \
  --id 0 --id 0x217 -o selected_decode
```

Open `shape1_decode/index.html` directly in a browser. It embeds the manifest,
so a web server is not required. Each resource has an animated preview and
a direction selector. Preview playback is fixed at 10 fps: the decoded
format does not supply a reliable animation duration.

Output directories must not already exist, to avoid overwriting prior results.
Errors go to stderr with a nonzero exit code. A failed export can leave partial
output; it is not reported as successful and has no completed manifest.

## Output

```text
shape1_decode/
  index.html                  Animated gallery (decode only)
  manifest.json               Archive index and sprite/frame metadata
  raw/
    00000000.was              Unmodified SP resource
    00001000.txt              Printable ASCII text (when present)
    ...                       Unknown types preserved as .bin
  00000000/
    metadata.json
    d00_f000.png              Direction 0, frame 0; cropped RGBA
    d00_f001.png
    d01_f000.png
    ...
```

IDs in filenames and JSON `id` fields are eight-digit hexadecimal; JSON `uid`
is the corresponding integer. **An ID is not an original filename**: WDF
indexes do not include a filename table.

Frame indices and directions are zero-based. Metadata retains both the sprite
header dimensions/anchor (`width`, `height`, `x`, `y`) and each frame's own
dimensions/anchor. To place a cropped frame at an animation origin `(ox, oy)`,
draw it at `(ox - frame.x, oy - frame.y)`. The preview uses the union of these
frame bounds so animation alignment is preserved without clipping.

An absent frame offset or zero-size frame is recorded as `empty: true` with no
PNG. Raw extraction preserves such records and all source bytes.

## Supported format and boundaries

- Little-endian `PFDW`: 12-byte header and 16-byte index records
  (`uint32 id, offset, size, space`). `space` is preserved, not interpreted as
  a compression flag.
- Classic `SP`: variable header size, RGB565 palette, direction-major frame
  offset table, signed frame origins and per-scanline RLE.
- Literal colors, repeated colors, transparent skips, individual/repeated
  alpha pixels, reserved `0xC0` two-byte payload, and classic interlaced
  scanlines as handled by libm5.
- Alpha follows libm5's 0–32 convention (32 opaque), scaled to PNG's 0–255.
  RGB565 is expanded by bit replication, with straight rather than
  premultiplied PNG alpha.
- Bounds, duplicate IDs, invalid dimensions, invalid alpha and scanline runs
  exceeding frame width are rejected. Individual frames are limited to
  16,777,216 pixels. Archives are read into memory; images are exported one
  frame at a time.
- Encrypted WDF variants, newer non-SP sprite formats, palette recoloring,
  audio decoding, repacking and recovering original resource names are not
  implemented. Unknown resource types are still extracted unchanged.

The supplied `shape1.wdf` has 229 SP resources and 7,521 nonempty frames.
The supplied `smap.wdf` has 143 SP resources and 143 nonempty frames.
`shape.wd1` is also a PFDW archive, but contains 284 numeric ASCII text
resources rather than images. These are exported unchanged as `.txt` files;
their numeric configuration data is not applied as palette transformations.
Printable ASCII with tabs/newlines is recognized as text; other non-SP data
is retained as `.bin`.
The source file is only read, never modified.

## Decode a whole resource repository

`decode_resources.py` handles loose sprites as well as classic `0.1M` maps.
Unlike `wdf.py`, this script requires Pillow for stitching JPEG map tiles.

```sh
python3 -m pip install -r requirements.txt
git clone --depth 1 https://github.com/valuetodays/javaxyq-im.git
git -C javaxyq-im checkout --detach 65721a683c61c4393f281db3bac805bc41cf8f8d
python3 decode_resources.py javaxyq-im -o javaxyq_resources_rebuilt
```

The shallow-clone command assumes the upstream HEAD is still the recorded
revision. If it has changed, fetch the recorded commit before checking it out:
`git -C javaxyq-im fetch --depth 1 origin 65721a683c61c4393f281db3bac805bc41cf8f8d`.
The rebuild uses a fresh output name because existing exports are not overwritten.

Open `javaxyq_resources_decode/index.html` directly in a browser. The gallery
supports searching by original path, hexadecimal ID and labels found in the
repository's INI tables, plus filtering by resource type. Results are paged
in groups of 60; animated previews open separately and audio loads on demand.

For JavaXYQ revision `65721a683c61c4393f281db3bac805bc41cf8f8d`, the export contains:

| Type | Resources | Result |
| --- | ---: | --- |
| SP/WAS/TCP sprites | 1,352 | 11,187 transparent PNG frames, per-resource animations and metadata |
| Maps | 18 | Stitched background PNGs and 657 restored JPEG tiles |
| Existing images | 69 | Original images linked in the gallery |
| Audio | 55 | Original MP3 files with browser playback controls |
| Other files | 718 | Preserved unchanged and indexed, not converted |

Original source paths are retained under `originals/`. Decoded files are
under `decoded/<original-source-path>/`, including extensionless SP resources
such as `decoded/game/res/addon/2231ebb4/`. The root `manifest.json` records
every file's source path, size, SHA-256, type, output links and any errors.
All non-`.git` files are accounted for, including code and configuration.

Map exports are **backgrounds only**: collision/occlusion masks, palette
descriptors, font data and other non-image files are preserved, not rendered
or semantically decoded. No cloned executable, script, DLL or JAR is run.
An export with decoding errors writes the inventory and errors, and exits
nonzero rather than silently reporting full success.

## Development

```sh
python3 -m unittest test_wdf -v  # Standard-library WDF/SP tests
python3 -m unittest -v          # Also map/tree tests; requires Pillow
```

## Format references

The implementation was written in Python using the format and decoding
behavior documented by these MIT-licensed libm5 sources:

- [etorth/libm5](https://github.com/etorth/libm5),
  commit `f66e86242c48d1f62f2c276dc87748d98e1d28cd`.
- [`libcc/cWas.cpp`](https://github.com/etorth/libm5/blob/f66e86242c48d1f62f2c276dc87748d98e1d28cd/libcc/cWas.cpp):
  WDF index, SP headers, palette and frame offsets.
- [`libutil/cSp.cpp`](https://github.com/etorth/libm5/blob/f66e86242c48d1f62f2c276dc87748d98e1d28cd/libutil/cSp.cpp):
  RLE commands, alpha convention and interlaced-row compatibility.

Upstream attribution and license are retained in `THIRD_PARTY_NOTICES`.
Classic map tile layout and JPEG restoration were cross-referenced against
[`MapDecoder.java`](https://github.com/valuetodays/javaxyq-im/blob/65721a683c61c4393f281db3bac805bc41cf8f8d/common/src/main/java/com/javaxyq/util/MapDecoder.java).
The JavaXYQ clone and its assets are external source material, not part of
the libm5 MIT license grant.
This local collection includes exported game assets alongside the tools;
rights to those assets remain with their respective owners.
