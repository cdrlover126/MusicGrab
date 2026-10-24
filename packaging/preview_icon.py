"""预览图标：生成多尺寸对比图，供人工检查（开发工具）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PIL import Image

from make_icons import make_icon_image

out = Path(__file__).parent / "icon_preview.png"
sizes = [256, 128, 64, 48, 32, 24, 16]
pad = 16
imgs = [make_icon_image(s) for s in sizes]
total_w = sum(i.width for i in imgs) + pad * (len(imgs) + 1)
total_h = max(i.height for i in imgs) + pad * 2
canvas = Image.new("RGBA", (total_w, total_h), (245, 246, 248, 255))
x = pad
for i in imgs:
    canvas.alpha_composite(i, (x, pad))
    x += i.width + pad
canvas.save(out)
print("preview:", out, canvas.size)
