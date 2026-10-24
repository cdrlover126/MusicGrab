"""生成应用图标与 MSIX 所需 PNG 素材（开发工具，非运行时依赖）。

设计：蓝色渐变圆角方形（squircle）底板 + 白色「声波条 ⇅ 下载箭头」标记，
表达「从各平台抓取音轨并保存为本地音频文件」。
所有形状以矢量方式在 4 倍超采样画布上绘制后降采样，保证小尺寸边缘干净。
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
MSIX = ROOT / "packaging" / "msix"

MASTER = 1024
SS = 4  # 超采样倍数

BG_TOP = (29, 161, 242)  # #1DA1F2
BG_BOTTOM = (11, 127, 212)  # #0B7FD4
WHITE = (255, 255, 255, 255)

# 主体标记几何（归一化坐标，相对画布边长）
SHAFT_W = 0.084
SHAFT_TOP = 0.235
SHAFT_BOTTOM = 0.505
ARROW_APEX_Y = 0.678
ARROW_SHOULDER_Y = 0.455
ARROW_HALF_W = 0.130
# 声波条：(中心 x, 顶端 y, 底端 y)
WAVE_BARS = (
    (0.228, 0.395, 0.565),
    (0.315, 0.300, 0.660),
    (0.685, 0.300, 0.660),
    (0.772, 0.395, 0.565),
)
BAR_HALF_W = 0.033


def _squircle_mask(size: int) -> Image.Image:
    """圆角方形遮罩（Windows Fluent 风格圆角）。"""
    canvas = Image.new("L", (size * SS, size * SS), 0)
    draw = ImageDraw.Draw(canvas)
    radius = size * SS * 0.223
    draw.rounded_rectangle((0, 0, size * SS - 1, size * SS - 1), radius=radius, fill=255)
    return canvas.resize((size, size), Image.LANCZOS)


def _vertical_gradient(size: int, top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    strip = Image.new("RGB", (1, size))
    pixels = strip.load()
    for y in range(size):
        t = y / max(1, size - 1)
        pixels[0, y] = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
    return strip.resize((size, size), Image.BILINEAR)


def _draw_mark(size: int) -> Image.Image:
    """绘制白色主体标记：声波条 + 下载箭头。返回 RGBA 图层。"""
    canvas = Image.new("RGBA", (size * SS, size * SS), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    s = size * SS

    def u(value: float) -> float:
        return value * s

    # 下载箭头主干
    draw.rounded_rectangle(
        (u(0.5 - SHAFT_W / 2), u(SHAFT_TOP), u(0.5 + SHAFT_W / 2), u(SHAFT_BOTTOM)),
        radius=u(SHAFT_W / 2),
        fill=WHITE,
    )
    # 箭头三角头（向下）
    draw.polygon(
        [
            (u(0.5), u(ARROW_APEX_Y)),
            (u(0.5 - ARROW_HALF_W), u(ARROW_SHOULDER_Y)),
            (u(0.5 + ARROW_HALF_W), u(ARROW_SHOULDER_Y)),
        ],
        fill=WHITE,
    )
    # 声波条
    for cx, top, bottom in WAVE_BARS:
        draw.rounded_rectangle(
            (u(cx - BAR_HALF_W), u(top), u(cx + BAR_HALF_W), u(bottom)),
            radius=u(BAR_HALF_W),
            fill=WHITE,
        )

    return canvas.resize((size, size), Image.LANCZOS)


def make_icon_image(size: int) -> Image.Image:
    """生成指定尺寸的完整图标（透明背景 + 圆角渐变底板 + 白色标记）。"""
    base = _vertical_gradient(size, BG_TOP, BG_BOTTOM).convert("RGBA")
    base.putalpha(_squircle_mask(size))
    base.alpha_composite(_draw_mark(size))
    return base


def main() -> None:
    ASSETS.mkdir(exist_ok=True)
    MSIX.mkdir(parents=True, exist_ok=True)

    ico_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    make_icon_image(MASTER).save(ASSETS / "icon.png")
    make_icon_image(256).save(ASSETS / "icon.ico", sizes=ico_sizes)

    for name, px in (
        ("Square44x44Logo", 44),
        ("Square150x150Logo", 150),
        ("Wide310x150Logo", 310),
        ("StoreLogo", 50),
        ("Square71x71Logo", 71),
        ("Square310x310Logo", 310),
    ):
        if name == "Wide310x150Logo":
            base = make_icon_image(150)
            canvas = Image.new("RGBA", (310, 150), (0, 0, 0, 0))
            canvas.paste(base, (80, 0), base)
            canvas.save(MSIX / f"{name}.png")
        else:
            make_icon_image(px).save(MSIX / f"{name}.png")

    print("icons generated:", ASSETS / "icon.ico", ASSETS / "icon.png", MSIX)


if __name__ == "__main__":
    main()
