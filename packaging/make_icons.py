"""生成应用图标与 MSIX 所需 PNG 素材（开发工具，非运行时依赖）。"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
MSIX = ROOT / "packaging" / "msix"


def _font(size: int) -> ImageFont.FreeTypeFont:
    for name in ("seguisb.ttf", "msyh.ttc", "arialbd.ttf", "arial.ttf"):
        path = Path("C:/Windows/Fonts") / name
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def make_icon_image(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    m = max(2, size // 16)
    draw.rounded_rectangle(
        (m, m, size - m, size - m), radius=size // 4, fill=(29, 161, 242, 255)
    )
    draw.rounded_rectangle(
        (size // 2, size // 2 - m, size - 3 * m, size - m),
        radius=size // 8,
        fill=(255, 255, 255, 255),
    )
    note = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ndraw = ImageDraw.Draw(note)
    f = _font(int(size * 0.58))
    ndraw.text((size * 0.22, size * 0.08), "\u266a", font=f, fill=(255, 255, 255, 255))
    img = Image.alpha_composite(img, note)
    return img


def main() -> None:
    ASSETS.mkdir(exist_ok=True)
    MSIX.mkdir(parents=True, exist_ok=True)
    ico_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    icon = make_icon_image(256)
    icon.save(ASSETS / "icon.ico", sizes=ico_sizes)
    icon.save(ASSETS / "icon.png")
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
    print("icons generated:", ASSETS / "icon.ico", MSIX)


if __name__ == "__main__":
    main()
