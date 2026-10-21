#!/usr/bin/env python3
"""Read PFDW archives and decode classic SP/WAS sprites using only the stdlib."""

import argparse
import binascii
from dataclasses import dataclass
import json
from pathlib import Path
import struct
import sys
import zlib


class FormatError(ValueError):
    """An unsupported or malformed archive or sprite."""


def require_range(data, offset, size, label):
    if offset < 0 or size < 0 or offset + size > len(data):
        raise FormatError(f"{label}: range {offset}+{size} exceeds {len(data)} bytes")


@dataclass(frozen=True)
class Entry:
    uid: int
    offset: int
    size: int
    space: int

    @property
    def name(self):
        return f"{self.uid:08X}"


class Wdf:
    def __init__(self, data):
        self.data = data
        require_range(data, 0, 12, "WDF header")
        magic, count, index = struct.unpack_from("<4sII", data)
        if magic != b"PFDW":
            raise FormatError(f"unsupported WDF signature {magic!r}; expected PFDW")
        if index < 12:
            raise FormatError("WDF index overlaps the header")
        require_range(data, index, count * 16, "WDF index")
        self.entries = []
        seen = set()
        for i in range(count):
            entry = Entry(*struct.unpack_from("<4I", data, index + i * 16))
            require_range(data, entry.offset, entry.size, f"entry {entry.name}")
            if entry.size and (
                entry.offset < 12
                or (entry.offset < index + count * 16 and entry.offset + entry.size > index)
            ):
                raise FormatError(f"entry {entry.name} overlaps WDF metadata")
            if entry.uid in seen:
                raise FormatError(f"duplicate entry ID {entry.name}")
            seen.add(entry.uid)
            self.entries.append(entry)

    def read(self, entry):
        return self.data[entry.offset:entry.offset + entry.size]


@dataclass
class Frame:
    x: int
    y: int
    width: int
    height: int
    rgba: bytes


class Sprite:
    MAX_PIXELS = 16_777_216

    def __init__(self, data):
        self.data = data
        require_range(data, 0, 16, "SP header")
        if data[:2] != b"SP":
            raise FormatError(f"unsupported sprite signature {data[:2]!r}")
        header, self.directions, self.frames_per_direction, self.width, self.height, \
            self.x, self.y = struct.unpack_from("<5H2h", data, 2)
        if header < 12 or not self.directions or not self.frames_per_direction:
            raise FormatError("invalid SP header size or frame counts")
        self.base = header + 4
        total = self.directions * self.frames_per_direction
        require_range(data, self.base, 512 + total * 4, "SP palette and frame table")
        self.palette = []
        for color in struct.unpack_from("<256H", data, self.base):
            r, g, b = color >> 11, (color >> 5) & 63, color & 31
            self.palette.append(bytes(((r << 3) | (r >> 2),
                                       (g << 2) | (g >> 4),
                                       (b << 3) | (b >> 2))))
        self.offsets = struct.unpack_from(f"<{total}I", data, self.base + 512)
        minimum = 512 + total * 4
        for offset in self.offsets:
            if offset and offset < minimum:
                raise FormatError("SP frame overlaps palette or frame table")
        ends = sorted({self.base + o for o in self.offsets if o} | {len(data)})
        self.ends = dict(zip(ends, ends[1:]))
        for offset in self.offsets:
            if offset:
                require_range(data, self.base + offset, 16, "SP frame header")

    def decode(self, index):
        if not 0 <= index < len(self.offsets):
            raise IndexError(f"frame index {index} out of range")
        offset = self.offsets[index]
        if not offset:
            return None
        start = self.base + offset
        end = self.ends[start]
        x, y, width, height = struct.unpack_from("<4i", self.data, start)
        if width == 0 or height == 0:
            if width < 0 or height < 0:
                raise FormatError(f"frame {index}: negative dimensions")
            return None
        if width < 0 or height < 0 or width * height > self.MAX_PIXELS:
            raise FormatError(f"frame {index}: invalid or excessive dimensions {width}x{height}")
        table_end = start + 16 + height * 4
        if table_end > end:
            raise FormatError(f"frame {index}: truncated scanline table")
        pixels = bytearray(width * height * 4)
        odd_has_color = False
        for row in range(height):
            relative = struct.unpack_from("<I", self.data, start + 16 + row * 4)[0]
            pos = start + relative
            if pos < table_end or pos >= end:
                raise FormatError(f"frame {index}, row {row}: invalid scanline offset")
            column = 0
            while column < width:
                if pos >= end:
                    raise FormatError(f"frame {index}, row {row}: truncated RLE command")
                command = self.data[pos]
                pos += 1
                if command == 0:
                    break
                mode = command >> 6
                count = command & 63
                alpha = 32
                if mode == 0:
                    if command & 32:
                        count, alpha, needed = 1, command & 31, 1
                    else:
                        count, needed = command & 31, 2
                elif mode == 1:
                    needed = count
                elif mode == 2:
                    needed = 1
                else:
                    needed = 2 if count == 0 else 0
                if pos + needed > end:
                    raise FormatError(f"frame {index}, row {row}: truncated RLE payload")
                if mode != 3 and count == 0:
                    raise FormatError(f"frame {index}, row {row}: zero-length color run")
                if column + count > width:
                    raise FormatError(f"frame {index}, row {row}: RLE run exceeds width")
                if mode != 3:
                    odd_has_color |= bool(row & 1)
                    if mode == 0 and not command & 32:
                        alpha = self.data[pos]
                        color = self.data[pos + 1]
                    elif mode != 1:
                        color = self.data[pos]
                    if alpha > 32:
                        raise FormatError(f"frame {index}, row {row}: invalid alpha {alpha}")
                    dest = (row * width + column) * 4
                    a = bytes(((alpha * 255 + 16) // 32,))
                    if mode == 1:
                        run = b"".join(self.palette[c] + b"\xff"
                                       for c in self.data[pos:pos + count])
                    else:
                        run = (self.palette[color] + a) * count if alpha else bytes(count * 4)
                    pixels[dest:dest + count * 4] = run
                pos += needed
                column += count
        # Classic interlaced sprites omit all colored commands on odd scanlines.
        if not odd_has_color:
            stride = width * 4
            for row in range(1, height, 2):
                pixels[row * stride:(row + 1) * stride] = pixels[(row - 1) * stride:row * stride]
        return Frame(x, y, width, height, bytes(pixels))


def png_bytes(width, height, rgba):
    if width <= 0 or height <= 0 or len(rgba) != width * height * 4:
        raise ValueError("invalid PNG dimensions or RGBA buffer")

    def chunk(tag, payload):
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", binascii.crc32(tag + payload) & 0xFFFFFFFF))

    stride = width * 4
    rows = b"".join(b"\0" + rgba[p:p + stride] for p in range(0, len(rgba), stride))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">2I5B", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows))
            + chunk(b"IEND", b""))


PREVIEW = """<!doctype html>
<meta charset="utf-8">
<title>WDF sprite preview</title>
<style>
body{font:16px system-ui;background:#202124;color:#eee;margin:24px}
#gallery{display:flex;flex-wrap:wrap;gap:16px}
article{background:#303134;padding:12px;width:240px}
canvas{width:240px;height:240px;object-fit:contain;
background:repeating-conic-gradient(#555 0% 25%,#444 0% 50%) 0/16px 16px}
select{margin:8px} a{color:#9cf}
</style>
<h1>WDF sprite preview</h1>
<p>One card per resource. Select a direction; animations run at 10 fps
(preview speed, not timing stored in the source). PNGs retain transparency.</p>
<div id="gallery"></div>
<script id="manifest" type="application/json">__MANIFEST__</script>
<script>
const manifest=JSON.parse(document.getElementById('manifest').textContent);
for(const resource of manifest.entries){
 if(!resource.frames) continue;
 const card=document.createElement('article'), title=document.createElement('div');
 title.textContent=resource.id+' / '+resource.directions+' directions';
 const select=document.createElement('select');
 for(let d=0;d<resource.directions;d++)select.add(new Option('Direction '+d,d));
 const canvas=document.createElement('canvas'), ctx=canvas.getContext('2d');
 const frames=resource.frames.filter(f=>!f.empty);
 if(!frames.length)continue;
 const left=Math.min(...frames.map(f=>-f.x)),top=Math.min(...frames.map(f=>-f.y));
 canvas.width=Math.max(...frames.map(f=>f.width-f.x))-left;
 canvas.height=Math.max(...frames.map(f=>f.height-f.y))-top;
 const images=resource.frames.map(f=>{
  if(f.empty)return null;
  const image=new Image();image.src=f.file;return image;
 });
 let tick=0;
 const link=document.createElement('a');link.href=resource.metadata;link.textContent='metadata';
 card.append(title,select,link,canvas);document.getElementById('gallery').append(card);
 function draw(){
  const i=Number(select.value)*resource.frames_per_direction+tick%resource.frames_per_direction;
  const f=resource.frames[i],image=images[i];
  ctx.clearRect(0,0,canvas.width,canvas.height);
  if(image&&image.complete&&image.naturalWidth)ctx.drawImage(image,-f.x-left,-f.y-top);
  tick++;
 }
 setInterval(draw,100);draw();
}
</script>
"""


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def export_sprite(data, directory, prefix=""):
    sprite = Sprite(data)
    directory.mkdir(parents=True, exist_ok=True)
    info = dict(directions=sprite.directions,
                frames_per_direction=sprite.frames_per_direction,
                width=sprite.width, height=sprite.height,
                x=sprite.x, y=sprite.y, frames=[],
                metadata=f"{prefix}metadata.json")
    for index in range(len(sprite.offsets)):
        frame = sprite.decode(index)
        direction, number = divmod(index, sprite.frames_per_direction)
        item = {"index": index, "direction": direction, "frame": number,
                "empty": frame is None}
        if frame is not None:
            name = f"d{direction:02d}_f{number:03d}.png"
            (directory / name).write_bytes(png_bytes(frame.width, frame.height, frame.rgba))
            item.update(x=frame.x, y=frame.y, width=frame.width,
                        height=frame.height, file=f"{prefix}{name}")
        info["frames"].append(item)
    return info


def export(archive, entries, output, decode):
    output.mkdir(parents=True, exist_ok=True)
    manifest = {"format": "PFDW", "entries": []}
    total_frames = 0
    for entry in entries:
        data = archive.read(entry)
        is_sp = data[:2] == b"SP"
        is_text = bool(data) and all(c in (9, 10, 13) or 32 <= c <= 126 for c in data)
        extension = ".was" if is_sp else ".txt" if is_text else ".bin"
        raw = output / "raw" / (entry.name + extension)
        raw.parent.mkdir(exist_ok=True)
        raw.write_bytes(data)
        info = {"id": entry.name, "uid": entry.uid, "offset": entry.offset,
                "size": entry.size, "space": entry.space,
                "raw": raw.relative_to(output).as_posix()}
        if decode and is_sp:
            try:
                directory = output / entry.name
                info.update(export_sprite(data, directory, f"{entry.name}/"))
                total_frames += sum(not f["empty"] for f in info["frames"])
                write_json(directory / "metadata.json", info)
            except FormatError as exc:
                raise FormatError(f"resource {entry.name}: {exc}") from exc
        manifest["entries"].append(info)
    write_json(output / "manifest.json", manifest)
    if decode:
        # Escape '<' so archive-derived JSON cannot close the script element.
        embedded = json.dumps(manifest, ensure_ascii=True).replace("<", "\\u003c")
        (output / "index.html").write_text(PREVIEW.replace("__MANIFEST__", embedded),
                                         encoding="utf-8")
    return total_frames


def parse_uid(value):
    try:
        uid = int(value, 16) if value.lower().startswith("0x") else int(value, 10)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("ID must be decimal or 0x-prefixed hexadecimal") from exc
    if not 0 <= uid <= 0xFFFFFFFF:
        raise argparse.ArgumentTypeError("ID must fit in an unsigned 32-bit integer")
    return uid


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("list", "extract", "decode"))
    parser.add_argument("archive", type=Path)
    parser.add_argument("-o", "--output", type=Path, help="new output directory")
    parser.add_argument("--id", type=parse_uid, action="append", help="select ID (repeatable)")
    args = parser.parse_args(argv)
    try:
        archive = Wdf(args.archive.read_bytes())
        entries = archive.entries
        if args.id is not None:
            wanted = set(args.id)
            missing = wanted - {e.uid for e in entries}
            if missing:
                raise FormatError("IDs not found: " + ", ".join(f"{i:08X}" for i in sorted(missing)))
            entries = [e for e in entries if e.uid in wanted]
        if args.command == "list":
            print("ID        OFFSET       SIZE TYPE")
            for entry in entries:
                kind = "SP/WAS" if archive.read(entry)[:2] == b"SP" else "binary"
                print(f"{entry.name} {entry.offset:10d} {entry.size:10d} {kind}")
            print(f"{len(entries)} entries")
        else:
            output = args.output or Path(f"{args.archive.stem}_{args.command}")
            if output.exists():
                raise FileExistsError(f"output already exists: {output}; choose a new directory")
            count = export(archive, entries, output, args.command == "decode")
            print(f"Exported {len(entries)} resources, {count} PNG frames to {output.resolve()}")
    except (OSError, FormatError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
