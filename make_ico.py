"""生成 app.ico（16/24/32/48/64 用 BMP，128/256 用 PNG）。"""
import struct
import zlib

import iconfx


def _png(w, h, rgba_rows):
    raw = b"".join(b"\x00" + bytes(r) for r in rgba_rows)

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def _bmp_entry(bgra, size):
    """ICO 里的 BMP：BITMAPINFOHEADER + 自下而上的 BGRA + 1bpp AND 掩码。"""
    header = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    rows = []
    for y in range(size - 1, -1, -1):
        rows.append(bgra[y * size * 4:(y + 1) * size * 4])
    pixels = b"".join(rows)
    mask_row = ((size + 31) // 32) * 4
    mask = b"\x00" * (mask_row * size)
    return header + pixels + mask


def _png_entry(bgra, size):
    rows = []
    for y in range(size):
        row = bytearray()
        for x in range(size):
            i = (y * size + x) * 4
            b, g, r, a = bgra[i:i + 4]
            row += bytes((r, g, b, a))
        rows.append(row)
    return _png(size, size, rows)


def build(path="app.ico", level=100, kind="mouse"):
    sizes = [16, 24, 32, 48, 64, 128, 256]
    blobs = []
    for s in sizes:
        bgra = iconfx.render(level, kind, False, s)
        blobs.append((s, _bmp_entry(bgra, s) if s <= 64 else _png_entry(bgra, s)))

    out = struct.pack("<HHH", 0, 1, len(blobs))
    offset = 6 + 16 * len(blobs)
    directory = b""
    data = b""
    for s, blob in blobs:
        directory += struct.pack("<BBBBHHII", s if s < 256 else 0, s if s < 256 else 0,
                                 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
        data += blob
    with open(path, "wb") as f:
        f.write(out + directory + data)
    return path


if __name__ == "__main__":
    p = build(r"D:\DSH\Data\Woek area all\default\battery-viewer\app.ico")
    import os
    print("ok", p, os.path.getsize(p))
