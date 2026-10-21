#!/usr/bin/env python3
"""Export a resource tree as PNG animations, stitched maps and a local gallery."""

import argparse
from collections import Counter
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import struct
import sys
from urllib.parse import quote

from PIL import Image

from wdf import FormatError, PREVIEW, export, export_sprite, require_range, Wdf, write_json


def repair_map_jpeg(data):
    """Restore JPEG markers omitted by classic 0.1M map tiles."""
    if data[:4] != b"\xff\xd8\xff\xa0" or data[-2:] != b"\xff\xd9":
        raise FormatError("unsupported map JPEG envelope")
    output = bytearray(b"\xff\xd8")
    pos = 4
    while pos < len(data) - 2:
        require_range(data, pos, 4, "map JPEG marker")
        if data[pos] != 255:
            raise FormatError("invalid map JPEG marker")
        length = struct.unpack_from(">H", data, pos + 2)[0]
        if length < 2:
            raise FormatError("invalid map JPEG segment length")
        require_range(data, pos, 2 + length, "map JPEG segment")
        if data[pos + 1] == 0xDA:
            if length != 9 or data[pos + 4] != 3:
                raise FormatError("unsupported map JPEG scan header")
            output.extend(b"\xff\xda\x00\x0c")
            output.extend(data[pos + 4:pos + 2 + length])
            output.extend(b"\x00\x3f\x00")
            output.extend(data[pos + 2 + length:-2].replace(b"\xff", b"\xff\x00"))
            output.extend(b"\xff\xd9")
            return bytes(output)
        output.extend(data[pos:pos + 2 + length])
        pos += 2 + length
    raise FormatError("map JPEG has no scan")


def export_map(data, directory):
    require_range(data, 0, 12, "map header")
    if data[:4] != b"0.1M":
        raise FormatError("unsupported map signature")
    width, height = struct.unpack_from("<2I", data, 4)
    if not width or not height or width * height > 100_000_000:
        raise FormatError(f"invalid or excessive map size {width}x{height}")
    columns, rows = (width + 319) // 320, (height + 239) // 240
    count = columns * rows
    require_range(data, 12, count * 4, "map tile table")
    offsets = struct.unpack_from(f"<{count}I", data, 12)
    directory.mkdir(parents=True, exist_ok=True)
    canvas = Image.new("RGB", (width, height))
    tiles = []
    for index, offset in enumerate(offsets):
        if offset < 12 + count * 4:
            raise FormatError("map tile overlaps header")
        require_range(data, offset, 4, "map tile header")
        links = struct.unpack_from("<I", data, offset)[0]
        pos = offset + 4 + links * 4
        require_range(data, pos, 8, "map JPEG block")
        if data[pos:pos + 4] != b"GEPJ":
            raise FormatError(f"tile {index}: expected GEPJ block")
        size = struct.unpack_from("<I", data, pos + 4)[0]
        require_range(data, pos + 8, size, "map JPEG payload")
        jpeg = repair_map_jpeg(data[pos + 8:pos + 8 + size])
        with Image.open(BytesIO(jpeg)) as tile:
            if tile.size != (320, 240):
                raise FormatError(f"tile {index}: unexpected size {tile.size}")
            tile.load()
            x, y = (index % columns) * 320, (index // columns) * 240
            canvas.paste(tile, (x, y))
        filename = f"tile_{index:04d}.jpg"
        (directory / filename).write_bytes(jpeg)
        tiles.append({"file": filename, "x": x, "y": y})
    canvas.save(directory / "map.png")
    canvas.thumbnail((320, 240))
    canvas.save(directory / "thumbnail.png")
    info = {"width": width, "height": height, "columns": columns, "rows": rows,
            "image": "map.png", "tiles": tiles,
            "note": "Background only. Occlusion masks and collision data are retained in originals."}
    write_json(directory / "metadata.json", info)
    return info


GALLERY = """<!doctype html>
<meta charset="utf-8"><title>JavaXYQ resource gallery</title>
<style>
body{font:15px system-ui;background:#202124;color:#eee;margin:24px}
input,select,button{padding:8px;margin:4px}input{width:340px}
a{color:#9cf}#gallery{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:16px}
article{background:#303134;padding:12px;overflow-wrap:anywhere;min-width:0}
img{display:block;width:100%;height:180px;object-fit:contain;image-rendering:auto;
background:repeating-conic-gradient(#555 0% 25%,#444 0% 50%) 0/16px 16px}
audio{width:100%}small{display:block;margin:8px 0}
</style>
<h1>JavaXYQ resource gallery</h1>
<p>Search paths / IDs / resource labels. Sprite previews animate at 10 fps.
Source assets retain their original owners' rights.</p>
<input id="search" placeholder="e.g. addon, 2231ebb4, shape, 组队">
<select id="kind"><option value="">All types</option><option>sprite</option>
<option>map</option><option>image</option><option>audio</option><option>archive</option>
<option>preserved</option></select>
<button id="prev">Previous</button><button id="next">Next</button><span id="status"></span>
<p><a href="manifest.json">Full inventory / metadata</a></p><div id="gallery"></div>
<script id="data" type="application/json">__DATA__</script>
<script>
const entries=JSON.parse(document.getElementById('data').textContent);
const search=document.getElementById('search'),kind=document.getElementById('kind');
const gallery=document.getElementById('gallery');let page=0;
function render(){
 const q=search.value.toLowerCase();
 const matches=entries.filter(e=>(!kind.value||e.type===kind.value)&&
  (e.source+' '+(e.label||'')).toLowerCase().includes(q));
 const pages=Math.max(1,Math.ceil(matches.length/60));page=Math.min(page,pages-1);
 gallery.replaceChildren();
 for(const e of matches.slice(page*60,(page+1)*60)){
  const card=document.createElement('article'),title=document.createElement('strong');
  title.textContent=e.source;card.append(title);
  const desc=document.createElement('small');
  desc.textContent=e.type+(e.label?' / '+e.label:'')+
    (e.frame_count!==undefined?' / '+e.frame_count+' frames':'');
  card.append(desc);
  if(e.thumbnail){
   const link=document.createElement('a');link.href=e.preview;
   const img=document.createElement('img');img.src=e.thumbnail;img.loading='lazy';
   img.alt=e.source;link.append(img);card.append(link);
  }
  if(e.type==='audio'){
   const audio=document.createElement('audio');audio.controls=true;audio.preload='none';
   audio.src=e.original;card.append(audio);
  }
  for(const [label,url] of [['Open preview',e.preview],['Original file',e.original],
                           ['Metadata',e.metadata]]){
   if(!url)continue;
   const link=document.createElement('a');link.href=url;link.textContent=label;
   card.append(link,document.createTextNode(' '));
  }
  gallery.append(card);
 }
 document.getElementById('status').textContent=
  matches.length+' resources | Page '+(page+1)+' / '+pages;
 document.getElementById('prev').disabled=page===0;
 document.getElementById('next').disabled=page+1>=pages;
}
search.oninput=kind.onchange=()=>{page=0;render()};
document.getElementById('prev').onclick=()=>{page--;render()};
document.getElementById('next').onclick=()=>{page++;render()};render();
</script>
"""


def resource_labels(root):
    labels = {}
    for path in sorted(root.rglob("*.ini")):
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                text = raw.decode("gb18030")
            except UnicodeDecodeError:
                continue
        for line in text.splitlines():
            fields = line.strip().replace("=", "\t", 1).split(None, 1)
            if len(fields) == 2 and len(fields[0]) == 8:
                try:
                    int(fields[0], 16)
                except ValueError:
                    continue
                labels.setdefault(fields[0].lower(), fields[1])
    return labels


def decode_tree(source, output):
    source, output = source.resolve(), output.resolve()
    if not source.is_dir():
        raise NotADirectoryError(source)
    if source == output or source in output.parents:
        raise ValueError("output must be outside the source tree")
    if output.exists():
        raise FileExistsError(f"output already exists: {output}")
    files = sorted(p for p in source.rglob("*")
                   if p.is_file() and ".git" not in p.relative_to(source).parts)
    labels = resource_labels(source)
    output.mkdir(parents=True)
    entries, errors = [], []
    for path in files:
        relative = path.relative_to(source)
        data = path.read_bytes()
        original = output / "originals" / relative
        original.parent.mkdir(parents=True, exist_ok=True)
        original.write_bytes(data)
        info = {"source": relative.as_posix(), "size": len(data),
                "sha256": sha256(data).hexdigest(), "type": "preserved",
                "original": quote(original.relative_to(output).as_posix())}
        label = labels.get(path.stem.lower())
        if label:
            info["label"] = label
        directory = output / "decoded" / relative
        prefix = quote(directory.relative_to(output).as_posix()) + "/"
        try:
            if data[:2] == b"SP":
                sprite = export_sprite(data, directory)
                write_json(directory / "metadata.json", sprite)
                local = dict(sprite, id=relative.as_posix())
                embedded = json.dumps({"entries": [local]}, ensure_ascii=True).replace("<", "\\u003c")
                (directory / "index.html").write_text(
                    PREVIEW.replace("__MANIFEST__", embedded), encoding="utf-8")
                visible = [f for f in sprite["frames"] if not f["empty"]]
                info.update(type="sprite", frame_count=len(visible),
                            frame_slots=len(sprite["frames"]), directions=sprite["directions"],
                            frames_per_direction=sprite["frames_per_direction"],
                            preview=prefix + "index.html", metadata=prefix + "metadata.json")
                if visible:
                    info["thumbnail"] = prefix + visible[0]["file"]
            elif data[:4] == b"0.1M":
                tilemap = export_map(data, directory)
                info.update(type="map", width=tilemap["width"], height=tilemap["height"],
                            tile_count=len(tilemap["tiles"]), preview=prefix + "map.png",
                            thumbnail=prefix + "thumbnail.png", metadata=prefix + "metadata.json")
            elif data[:4] == b"PFDW":
                archive = Wdf(data)
                frames = export(archive, archive.entries, directory, True)
                info.update(type="archive", frame_count=frames, preview=prefix + "index.html",
                            metadata=prefix + "manifest.json")
            elif path.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".bmp"):
                with Image.open(BytesIO(data)) as image:
                    image.load()
                    info.update(type="image", width=image.width, height=image.height,
                                thumbnail=info["original"], preview=info["original"])
            elif path.suffix.lower() in (".mp3", ".wav", ".ogg"):
                info.update(type="audio")
        except (FormatError, OSError, ValueError) as exc:
            info["error"] = str(exc)
            errors.append({"source": relative.as_posix(), "error": str(exc)})
            print(f"error: {relative}: {exc}", file=sys.stderr)
        entries.append(info)
    counts = dict(Counter(e["type"] for e in entries))
    manifest = {"source": str(source), "counts": counts, "errors": errors, "entries": entries,
                "png_frames": sum(e.get("frame_count", 0) for e in entries),
                "notes": ["No programs, scripts or JARs from the source were executed.",
                          "Unconverted files are retained byte-for-byte, including masks, "
                          "palette descriptors, fonts, configuration and code."]}
    write_json(output / "manifest.json", manifest)
    embedded = json.dumps(entries, ensure_ascii=True).replace("<", "\\u003c")
    (output / "index.html").write_text(GALLERY.replace("__DATA__", embedded), encoding="utf-8")
    print(json.dumps({"counts": counts, "png_frames": manifest["png_frames"],
                      "errors": len(errors), "output": str(output)}, indent=2))
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        manifest = decode_tree(args.source, args.output)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 1 if manifest["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
