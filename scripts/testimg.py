"""生成一张"配电柜示意图"测试图（纯标准库，无 Pillow 依赖）。

供 setup_vision.py 和 smoke.py 共用，避免两个脚本各写一份。
画面：灰柜体 + 红/黄/绿三个指示灯 + 指针式仪表（红色指针）+ 标签条。
"""

from __future__ import annotations

import struct
import zlib


def _png(width: int, height: int, painter) -> bytes:
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter type 0
        for x in range(width):
            raw.extend(painter(x, y))

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8bit RGB
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def make_test_image() -> bytes:
    W, H = 400, 300

    def in_circle(x: int, y: int, cx: int, cy: int, r: int) -> bool:
        return (x - cx) ** 2 + (y - cy) ** 2 <= r * r

    def painter(x: int, y: int) -> tuple[int, int, int]:
        if 40 <= x < 360 and 30 <= y < 270:
            if 60 <= x < 340 and 50 <= y < 250 and (x < 66 or x > 333 or y < 56 or y > 243):
                return (60, 60, 66)  # 柜体边框
            if 66 <= x < 333 and 56 <= y < 243:
                if in_circle(x, y, 110, 90, 14):
                    return (220, 40, 40)  # 红灯
                if in_circle(x, y, 190, 90, 14):
                    return (230, 200, 60)  # 黄灯
                if in_circle(x, y, 270, 90, 14):
                    return (50, 190, 90)  # 绿灯
                if in_circle(x, y, 200, 165, 55):  # 仪表盘
                    if abs(x - 200) <= 3 and y <= 165 and in_circle(x, y, 200, 165, 50):
                        return (210, 30, 30)  # 指针
                    if in_circle(x, y, 200, 165, 8):
                        return (40, 40, 40)  # 轴心
                    return (240, 240, 240)
                if 90 <= x < 310 and 215 <= y < 235:
                    return (200, 200, 205)  # 标签条
                return (35, 38, 45)
            return (150, 152, 158)
        return (198, 200, 205)

    return _png(W, H, painter)


if __name__ == "__main__":
    import pathlib

    out = pathlib.Path(__file__).resolve().parents[1] / "data" / "test_cabinet.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(make_test_image())
    print(f"已生成 {out}")
