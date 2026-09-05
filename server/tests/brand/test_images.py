"""品牌素材图片尺寸与 MIME 嗅探的纯函数测试。"""

import struct

from reven.brand.images import image_dimensions, sniff_image_mime

PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c626001000000ffff030000060005"
    "57bfabd40000000049454e44ae426082"
)


def _png(width: int, height: int) -> bytes:
    header = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR"
    return header + struct.pack(">II", width, height) + b"\x08\x06\x00\x00\x00" + b"\x00" * 16


def _gif(width: int, height: int) -> bytes:
    return b"GIF89a" + struct.pack("<HH", width, height) + b"\x00" * 8


def _jpeg(width: int, height: int) -> bytes:
    sof = b"\xff\xc0" + struct.pack(">H", 17) + b"\x08" + struct.pack(">HH", height, width) + b"\x03" + b"\x00" * 6
    return b"\xff\xd8" + b"\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 9 + sof


def _webp_vp8x(width: int, height: int) -> bytes:
    payload = (
        b"RIFF" + b"\x00" * 4 + b"WEBPVP8X" + b"\x0a\x00\x00\x00" + b"\x00" * 4
        + (width - 1).to_bytes(3, "little") + (height - 1).to_bytes(3, "little") + b"\x00" * 4
    )
    return payload


def test_sniff_image_mime() -> None:
    assert sniff_image_mime(PNG_1X1) == "image/png"
    assert sniff_image_mime(_jpeg(2, 3)) == "image/jpeg"
    assert sniff_image_mime(_gif(4, 5)) == "image/gif"
    assert sniff_image_mime(_webp_vp8x(6, 7)) == "image/webp"
    assert sniff_image_mime(b"not an image") is None
    assert sniff_image_mime(b"") is None


def test_image_dimensions() -> None:
    assert image_dimensions(_png(900, 383), "image/png") == (900, 383)
    assert image_dimensions(_gif(80, 80), "image/gif") == (80, 80)
    assert image_dimensions(_jpeg(1200, 630), "image/jpeg") == (1200, 630)
    assert image_dimensions(_webp_vp8x(640, 360), "image/webp") == (640, 360)
    assert image_dimensions(b"\x89PNG broken", "image/png") is None
    assert image_dimensions(b"whatever", "image/svg+xml") is None
