"""图片尺寸解析：从 PNG/JPEG/GIF/WebP 文件头读取宽高，不引入 PIL 依赖。"""

import struct

_MAGIC: tuple[tuple[str, bytes], ...] = (
    ("image/png", b"\x89PNG\r\n\x1a\n"),
    ("image/jpeg", b"\xff\xd8\xff"),
    ("image/gif", b"GIF8"),
    ("image/webp", b"RIFF"),
)


def sniff_image_mime(content: bytes) -> str | None:
    for mime_type, magic in _MAGIC:
        if content.startswith(magic):
            return mime_type
    return None


def image_dimensions(content: bytes, mime_type: str) -> tuple[int, int] | None:
    if mime_type == "image/png":
        return _png_dimensions(content)
    if mime_type == "image/jpeg":
        return _jpeg_dimensions(content)
    if mime_type == "image/gif":
        return _gif_dimensions(content)
    if mime_type == "image/webp":
        return _webp_dimensions(content)
    return None


def _png_dimensions(content: bytes) -> tuple[int, int] | None:
    # PNG: 8 字节魔数 + IHDR 块（长度/类型各 4 字节），宽高在偏移 16/20 处的大端 uint32。
    if len(content) < 24 or not content.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    width, height = struct.unpack(">II", content[16:24])
    return (width, height) if width > 0 and height > 0 else None


def _gif_dimensions(content: bytes) -> tuple[int, int] | None:
    # GIF: 6 字节头 + 逻辑屏幕描述符，宽高为偏移 6/8 处的小端 uint16。
    if len(content) < 10 or not content.startswith(b"GIF8"):
        return None
    width, height = struct.unpack("<HH", content[6:10])
    return (width, height) if width > 0 and height > 0 else None


def _jpeg_dimensions(content: bytes) -> tuple[int, int] | None:
    # JPEG: 扫描 SOFn 段（0xC0-0xCF，排除 DHT/DAC/RST 等无尺寸段）。
    if len(content) < 4 or not content.startswith(b"\xff\xd8"):
        return None
    offset = 2
    while offset + 9 < len(content):
        if content[offset] != 0xFF:
            offset += 1
            continue
        marker = content[offset + 1]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            height, width = struct.unpack(">HH", content[offset + 5 : offset + 9])
            return (width, height) if width > 0 and height > 0 else None
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            offset += 2
            continue
        segment_length = struct.unpack(">H", content[offset + 2 : offset + 4])[0]
        if segment_length < 2:
            return None
        offset += 2 + segment_length
    return None


def _webp_dimensions(content: bytes) -> tuple[int, int] | None:
    # WebP: RIFF 头 + VP8/VP8L/VP8X 块。
    if len(content) < 30 or content[:4] != b"RIFF" or content[8:12] != b"WEBP":
        return None
    chunk = content[12:16]
    if chunk == b"VP8X":
        width = 1 + int.from_bytes(content[24:27], "little")
        height = 1 + int.from_bytes(content[27:30], "little")
        return width, height
    if chunk == b"VP8 " and len(content) >= 30:
        width, height = struct.unpack("<HH", content[26:30])
        return (width & 0x3FFF, height & 0x3FFF)
    if chunk == b"VP8L" and len(content) >= 25:
        bits = int.from_bytes(content[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    return None
