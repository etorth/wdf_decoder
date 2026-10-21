import contextlib
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

from wdf import FormatError, Sprite, Wdf, export, main, png_bytes


def make_sprite(rows, width, *, x=-3, y=7, header=12, extra_empty=False):
    base = header + 4
    palette = [0] * 256
    palette[1:4] = [0xF800, 0x07E0, 0x001F]
    count = 2 if extra_empty else 1
    frame_offset = 512 + count * 4
    line_offset = 16 + len(rows) * 4
    offsets = []
    for row in rows:
        offsets.append(line_offset)
        line_offset += len(row)
    frame = (struct.pack("<4i", x, y, width, len(rows))
             + struct.pack(f"<{len(rows)}I", *offsets) + b"".join(rows))
    return (struct.pack("<2s5H2h", b"SP", header, 1, count, width, len(rows), 4, 5)
            + bytes(base - 16) + struct.pack("<256H", *palette)
            + struct.pack("<I", frame_offset) + (bytes(4) if extra_empty else b"")
            + frame)


def make_archive(resources):
    payload = b"".join(data for _, data in resources)
    index = 12 + len(payload)
    entries = []
    offset = 12
    for uid, data in resources:
        entries.append(struct.pack("<4I", uid, offset, len(data), 0))
        offset += len(data)
    return struct.pack("<4sII", b"PFDW", len(entries), index) + payload + b"".join(entries)


class SpriteTests(unittest.TestCase):
    def test_all_color_modes_alpha_skip_and_origins(self):
        row = bytes([0x22, 1, 2, 16, 2, 0x42, 1, 3, 0x82, 3, 0xC2, 0])
        frame = Sprite(make_sprite([row, row], 9)).decode(0)
        pixels = [
            (255, 0, 0, 16),
            (0, 255, 0, 128), (0, 255, 0, 128),
            (255, 0, 0, 255), (0, 0, 255, 255),
            (0, 0, 255, 255), (0, 0, 255, 255),
            (0, 0, 0, 0), (0, 0, 0, 0),
        ]
        self.assertEqual(frame.rgba, bytes(c for pixel in pixels * 2 for c in pixel))
        self.assertEqual((frame.x, frame.y, frame.width, frame.height), (-3, 7, 9, 2))

    def test_zero_alpha_run_advances_without_color(self):
        row = bytes([2, 0, 1, 0x81, 3, 0])
        frame = Sprite(make_sprite([row, row], 3)).decode(0)
        self.assertEqual(frame.rgba[:12], bytes(8) + bytes([0, 0, 255, 255]))

    def test_reserved_c0_payload_is_not_pixels(self):
        frame = Sprite(make_sprite([bytes([0xC0, 123, 234, 0x81, 1, 0])], 1)).decode(0)
        self.assertEqual(frame.rgba, bytes([255, 0, 0, 255]))

    def test_interlaced_rows_repeat_even_rows(self):
        sprite = Sprite(make_sprite([bytes([0x82, 1, 0]), b"\0",
                                     bytes([0x82, 3, 0]), b"\0"], 2))
        frame = sprite.decode(0)
        red, blue = bytes([255, 0, 0, 255]) * 2, bytes([0, 0, 255, 255]) * 2
        self.assertEqual(frame.rgba, red + red + blue + blue)

    def test_odd_color_disables_interlace(self):
        frame = Sprite(make_sprite([bytes([0x81, 1, 0]), b"\0",
                                    bytes([0x81, 3, 0]), bytes([0x81, 2, 0])], 1)).decode(0)
        self.assertEqual(frame.rgba[4:8], bytes(4))

    def test_extended_header_and_empty_frame(self):
        sprite = Sprite(make_sprite([bytes([0x81, 1, 0])], 1, header=16, extra_empty=True))
        self.assertEqual(sprite.decode(0).rgba, bytes([255, 0, 0, 255]))
        self.assertIsNone(sprite.decode(1))
        with self.assertRaises(IndexError):
            sprite.decode(-1)

    def test_rejects_truncation_bad_offsets_dimensions_and_runs(self):
        valid = make_sprite([bytes([0x81, 1, 0])], 1)
        cases = [valid[:15], valid[:520], valid[:-2],
                 make_sprite([bytes([0x82, 1, 0])], 1),
                 make_sprite([bytes([0x40, 0])], 1),
                 make_sprite([bytes([1, 33, 1, 0])], 1)]
        bad_offset = bytearray(valid)
        struct.pack_into("<I", bad_offset, 528, 1)
        cases.append(bad_offset)
        bad_line = bytearray(valid)
        struct.pack_into("<I", bad_line, 532 + 16, 0)
        cases.append(bad_line)
        big = bytearray(valid)
        struct.pack_into("<2i", big, 532 + 8, 100000, 100000)
        cases.append(big)
        for data in cases:
            with self.subTest(data=bytes(data[-24:])):
                with self.assertRaises(FormatError):
                    Sprite(data).decode(0)


class ArchiveTests(unittest.TestCase):
    def test_unsorted_ids_and_raw_roundtrip(self):
        archive = Wdf(make_archive([(42, b"abc"), (3, b"defg")]))
        self.assertEqual([entry.uid for entry in archive.entries], [42, 3])
        self.assertEqual([archive.read(e) for e in archive.entries], [b"abc", b"defg"])

    def test_rejects_invalid_archive(self):
        valid = make_archive([(42, b"abc")])
        overlap = bytearray(valid)
        struct.pack_into("<I", overlap, 15 + 4, 0)
        cases = [b"", b"XXXX" + valid[4:], valid[:-1],
                 make_archive([(1, b"a"), (1, b"b")]), overlap]
        outside = bytearray(valid)
        struct.pack_into("<I", outside, 15 + 8, 99999)
        cases.append(outside)
        for data in cases:
            with self.subTest(data=data):
                with self.assertRaises(FormatError):
                    Wdf(data)

    def test_export_metadata_raw_png_preview_and_unknown_entry(self):
        sprite = make_sprite([bytes([0x81, 1, 0])], 1, extra_empty=True)
        archive = Wdf(make_archive([(7, sprite), (8, b"\x00unknown"),
                                    (9, b"1 0 256\r\n")]))
        with tempfile.TemporaryDirectory() as root:
            output = Path(root)
            self.assertEqual(export(archive, archive.entries, output, True), 1)
            self.assertEqual((output / "raw/00000007.was").read_bytes(), sprite)
            self.assertEqual((output / "raw/00000008.bin").read_bytes(), b"\x00unknown")
            self.assertEqual((output / "raw/00000009.txt").read_bytes(), b"1 0 256\r\n")
            manifest = json.loads((output / "manifest.json").read_text())
            item = manifest["entries"][0]
            self.assertEqual(item["frames"][0]["x"], -3)
            self.assertTrue(item["frames"][1]["empty"])
            self.assertTrue((output / item["frames"][0]["file"]).is_file())
            self.assertTrue((output / item["metadata"]).is_file())
            self.assertIn('"id": "00000007"', (output / "index.html").read_text())

    def test_cli_selection_missing_ids_and_output_protection(self):
        with tempfile.TemporaryDirectory() as root:
            source, output = Path(root) / "input.wdf", Path(root) / "output"
            source.write_bytes(make_archive([(3, b"three"), (42, b"forty-two")]))
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(["extract", str(source), "-o", str(output), "--id", "0x2a"]), 0)
                self.assertEqual(main(["extract", str(source), "-o", str(output)]), 1)
                self.assertEqual(main(["list", str(source), "--id", "99"]), 1)
            self.assertEqual(sorted(p.name for p in (output / "raw").iterdir()), ["0000002A.txt"])


class PngTests(unittest.TestCase):
    def test_png_contains_exact_rgba_scanlines_and_valid_crcs(self):
        import binascii

        rgba = bytes([255, 0, 0, 128, 0, 0, 0, 0])
        png = png_bytes(1, 2, rgba)
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        pos, compressed = 8, b""
        while pos < len(png):
            size = struct.unpack_from(">I", png, pos)[0]
            tag, payload = png[pos + 4:pos + 8], png[pos + 8:pos + 8 + size]
            crc = struct.unpack_from(">I", png, pos + 8 + size)[0]
            self.assertEqual(crc, binascii.crc32(tag + payload) & 0xFFFFFFFF)
            if tag == b"IDAT":
                compressed += payload
            pos += 12 + size
        self.assertEqual(zlib.decompress(compressed), b"\0" + rgba[:4] + b"\0" + rgba[4:])


if __name__ == "__main__":
    unittest.main()
