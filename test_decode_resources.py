from io import BytesIO
import json
from pathlib import Path
import struct
import tempfile
import unittest

from PIL import Image

from decode_resources import decode_tree, export_map, repair_map_jpeg
from test_wdf import make_sprite
from wdf import FormatError


def map_jpeg(color):
    buffer = BytesIO()
    Image.new("RGB", (320, 240), color).save(buffer, format="JPEG")
    jpeg = buffer.getvalue()
    sos = jpeg.index(b"\xff\xda")
    length = struct.unpack_from(">H", jpeg, sos + 2)[0]
    if length != 12:
        raise AssertionError("test JPEG needs a 3-component scan")
    header = jpeg[2:sos] + b"\xff\xda\x00\x09" + jpeg[sos + 4:sos + 11]
    entropy = jpeg[sos + 14:-2].replace(b"\xff\x00", b"\xff")
    return b"\xff\xd8\xff\xa0" + header + entropy + b"\xff\xd9", jpeg


def make_map():
    tiles = [map_jpeg("red")[0], map_jpeg("blue")[0]]
    payload = bytearray()
    offsets = []
    for tile in tiles:
        offsets.append(20 + len(payload))
        payload.extend(struct.pack("<I4sI", 0, b"GEPJ", len(tile)) + tile)
    return (struct.pack("<4s4I", b"0.1M", 400, 200, *offsets) + payload)


class MapTests(unittest.TestCase):
    def test_repair_recovers_exact_original_jpeg(self):
        proprietary, expected = map_jpeg("green")
        self.assertEqual(repair_map_jpeg(proprietary), expected)

    def test_map_tiles_stitch_and_crop_to_header_dimensions(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            metadata = export_map(make_map(), directory)
            self.assertEqual(len(metadata["tiles"]), 2)
            with Image.open(directory / "map.png") as image:
                self.assertEqual(image.size, (400, 200))
                self.assertGreater(image.getpixel((0, 0))[0], 240)
                self.assertGreater(image.getpixel((399, 199))[2], 240)
            self.assertTrue((directory / "tile_0001.jpg").is_file())

    def test_rejects_truncated_and_invalid_maps(self):
        invalid = [b"", b"bad" * 20, make_map()[:-10]]
        bad_offset = bytearray(make_map())
        struct.pack_into("<I", bad_offset, 12, 0)
        invalid.append(bad_offset)
        with tempfile.TemporaryDirectory() as root:
            for data in invalid:
                with self.subTest(data=data[:20]):
                    with self.assertRaises(FormatError):
                        export_map(data, Path(root))
        with self.assertRaises(FormatError):
            repair_map_jpeg(b"\xff\xd8\xff\xd9")


class TreeTests(unittest.TestCase):
    def test_tree_preserves_paths_originals_and_supported_formats(self):
        with tempfile.TemporaryDirectory() as root:
            source, output = Path(root) / "source", Path(root) / "output"
            (source / "res/addon").mkdir(parents=True)
            (source / ".git").mkdir()
            (source / ".git/ignored").write_text("not an asset")
            sprite = make_sprite([bytes([0x81, 1, 0])], 1)
            (source / "res/addon/2231ebb4").write_bytes(sprite)
            (source / "res/scene.map").write_bytes(make_map())
            (source / "res/audio.mp3").write_bytes(b"audio fixture")
            (source / "res/opaque.dat").write_bytes(bytes(range(256)))
            (source / "res/addon.wdf.ini").write_text("2231EBB4=team leader\n")
            Image.new("RGB", (2, 3)).save(source / "res/image.png")
            manifest = decode_tree(source, output)
            self.assertEqual(manifest["errors"], [])
            self.assertEqual(manifest["png_frames"], 1)
            self.assertEqual(len(manifest["entries"]), 6)
            entries = {e["source"]: e for e in manifest["entries"]}
            marker = entries["res/addon/2231ebb4"]
            self.assertEqual(marker["label"], "team leader")
            self.assertTrue((output / marker["preview"]).is_file())
            self.assertEqual((output / marker["original"]).read_bytes(), sprite)
            self.assertEqual(entries["res/scene.map"]["tile_count"], 2)
            self.assertEqual(entries["res/audio.mp3"]["type"], "audio")
            self.assertEqual(entries["res/image.png"]["type"], "image")
            self.assertEqual(entries["res/opaque.dat"]["type"], "preserved")
            metadata = json.loads((output / marker["metadata"]).read_text())
            self.assertEqual(metadata["frames"][0]["file"], "d00_f000.png")
            with self.assertRaises(FileExistsError):
                decode_tree(source, output)
            with self.assertRaises(ValueError):
                decode_tree(source, source / "nested-output")

    def test_corrupt_sprite_is_reported_and_original_retained(self):
        with tempfile.TemporaryDirectory() as root:
            source, output = Path(root) / "source", Path(root) / "output"
            source.mkdir()
            (source / "broken.tcp").write_bytes(b"SP")
            manifest = decode_tree(source, output)
            self.assertEqual(len(manifest["errors"]), 1)
            self.assertEqual(manifest["errors"][0]["source"], "broken.tcp")
            self.assertEqual((output / "originals/broken.tcp").read_bytes(), b"SP")
            self.assertTrue((output / "manifest.json").is_file())


if __name__ == "__main__":
    unittest.main()
