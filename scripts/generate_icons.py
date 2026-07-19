#!/usr/bin/env python3
"""icons/icon-192.png, icon-512.png, apple-touch-icon.png を生成する。

杉玉(酒蔵の軒先に吊るす杉の葉を球状にまとめた飾り。新酒ができた合図として
吊るされる)をモチーフに、絵文字ではなく図形として描画する。
高解像度(1024px)で描いてから縮小することで、どのサイズでも縁が滑らかになる。
"""

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw

MASTER_SIZE = 1024
ICON_DIR = Path(__file__).resolve().parent.parent / "icons"

BG_COLOR = (34, 51, 74, 255)  # #22334a (テーマカラーと合わせる)
INNER_CIRCLE_COLOR = (24, 38, 56, 255)  # 背景円に少し立体感を出すための濃淡
ROPE_COLOR = (196, 164, 108, 255)  # 藁縄の色
NEEDLE_COLORS = [
    (52, 84, 48, 255),
    (67, 100, 58, 255),
    (40, 66, 38, 255),
    (80, 112, 66, 255),
]
BALL_BASE_COLOR = (58, 90, 54, 255)


def draw_master():
    size = MASTER_SIZE
    img = Image.new("RGBA", (size, size), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # 背景円(maskable対応: 中央の安全領域に収まるよう少し内側に敷く)
    margin = int(size * 0.04)
    draw.ellipse([margin, margin, size - margin, size - margin], fill=INNER_CIRCLE_COLOR)

    # 杉玉本体
    ball_radius = size * 0.30
    cx, cy = size / 2, size / 2 + size * 0.04
    draw.ellipse(
        [cx - ball_radius, cy - ball_radius, cx + ball_radius, cy + ball_radius],
        fill=BALL_BASE_COLOR,
    )

    # 杉の葉のテクスチャ: 球の中に短い線を大量に描き、葉が密集した質感を出す。
    # 毎回同じ見た目になるよう乱数シードを固定する。
    rng = random.Random(42)
    for _ in range(2600):
        angle = rng.uniform(0, 2 * math.pi)
        dist = rng.uniform(0, ball_radius * 0.95)
        px = cx + dist * math.cos(angle)
        py = cy + dist * math.sin(angle)

        stroke_angle = rng.uniform(0, 2 * math.pi)
        length = rng.uniform(size * 0.012, size * 0.03)
        dx = length * math.cos(stroke_angle)
        dy = length * math.sin(stroke_angle)

        color = rng.choice(NEEDLE_COLORS)
        width = rng.choice([2, 2, 3])
        draw.line([(px, py), (px + dx, py + dy)], fill=color, width=width)

    # 左上からの光を意識した、ふんわりしたハイライト(丸みを感じさせる)
    highlight = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    hdraw = ImageDraw.Draw(highlight)
    hl_r = ball_radius * 0.55
    hl_cx, hl_cy = cx - ball_radius * 0.35, cy - ball_radius * 0.4
    hdraw.ellipse(
        [hl_cx - hl_r, hl_cy - hl_r, hl_cx + hl_r, hl_cy + hl_r],
        fill=(255, 255, 255, 28),
    )
    img = Image.alpha_composite(img, highlight)
    draw = ImageDraw.Draw(img)

    # 吊り下げる藁縄(球の上端から画像の上端まで)
    rope_width = int(size * 0.018)
    draw.line(
        [(cx, cy - ball_radius), (cx, margin)],
        fill=ROPE_COLOR,
        width=rope_width,
    )

    return img


def generate(size, out_path, master):
    resized = master.resize((size, size), Image.LANCZOS)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    resized.save(out_path)
    print(f"生成: {out_path}")


def main():
    master = draw_master()
    generate(192, ICON_DIR / "icon-192.png", master)
    generate(512, ICON_DIR / "icon-512.png", master)
    generate(180, ICON_DIR / "apple-touch-icon.png", master)


if __name__ == "__main__":
    main()
