"""生成技术架构图 / 流程图（博文插图）。开发工具。

用法: python packaging/make_diagrams.py
输出: docs/images/05-系统架构图.png、06-处理流程图.png、07-智能路由决策图.png
"""
from __future__ import annotations

import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

OUT = root / "docs" / "images"
OUT.mkdir(parents=True, exist_ok=True)

BG = (255, 255, 255)
INK = (17, 24, 39)
MUTED = (107, 114, 128)
BLUE = (37, 99, 235)
BLUE_L = (219, 234, 254)
GREEN = (34, 197, 94)
GREEN_L = (220, 252, 231)
AMBER = (217, 119, 6)
AMBER_L = (254, 243, 199)
PURPLE = (124, 58, 237)
PURPLE_L = (237, 233, 254)
SLATE = (100, 116, 139)
SLATE_L = (241, 245, 249)
BORDER = (203, 213, 225)


def font(size: int, bold: bool = False):
    for name in ("msyhbd.ttc", "msyh.ttc", "seguisb.ttf", "segoeui.ttf", "arialbd.ttf"):
        p = Path("C:/Windows/Fonts") / name
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size)
            except OSError:
                continue
    return ImageFont.load_default()


def arrow(d, x1, y1, x2, y2, color=(148, 163, 184), width=3):
    d.line([(x1, y1), (x2, y2)], fill=color, width=width)
    import math

    ang = math.atan2(y2 - y1, x2 - x1)
    L = 12
    for da in (2.6, -2.6):
        d.line(
            [(x2, y2), (x2 + L * math.cos(ang + da), y2 + L * math.sin(ang + da))],
            fill=color,
            width=width,
        )


def box(d, x, y, w, h, title, sub, bg, bd, tsize=26, ssize=17):
    d.rounded_rectangle((x, y, x + w, y + h), radius=12, fill=bg, outline=bd, width=2)
    d.text((x + w / 2, y + h / 2 - 16), title, font=font(tsize, True), fill=INK, anchor="mm")
    if sub:
        d.text((x + w / 2, y + h / 2 + 20), sub, font=font(ssize), fill=MUTED, anchor="mm")


# ───────────────────────── 05 系统架构图 ─────────────────────────
W, H = 1400, 900
img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img)
d.text((W / 2, 40), "乐取 MusicGrab 系统架构", font=font(38, True), fill=INK, anchor="mm")
d.text(
    (W / 2, 78),
    "双引擎解析 + 智能路由 + 多格式转码",
    font=font(20),
    fill=MUTED,
    anchor="mm",
)

layers = [
    ("接入层", SLATE_L, SLATE, [("链接粘贴", "多行 / 口令 / 短链"), ("本地文件", "30+ 视频容器")]),
    ("路由层", BLUE_L, BLUE, [("智能路由", "国内直连·境外代理"), ("代理预检", "连通性校验")]),
    ("解析层", GREEN_L, GREEN, [("内置解析器", "抖音/快手/酷狗"), ("通用引擎", "yt-dlp 1500+")]),
    ("处理层", AMBER_L, AMBER, [("下载", "重试/回退源"), ("转码", "ffmpeg 8 格式")]),
    ("输出层", PURPLE_L, PURPLE, [("ID3 标签", "v2.3 / 原生标签"), ("CSV 报告", "可追溯")]),
]
y = 120
for i, (name, bg, bd, items) in enumerate(layers):
    d.rounded_rectangle((70, y, 250, y + 108), radius=12, fill=bg, outline=bd, width=2)
    d.text((160, y + 54), name, font=font(28, True), fill=INK, anchor="mm")
    x = 310
    for title, sub in items:
        box(d, x, y, 480, 108, title, sub, (255, 255, 255), bd)
        x += 520
    if i < len(layers) - 1:
        arrow(d, W / 2, y + 112, W / 2, y + 138, color=(203, 213, 225), width=4)
    y += 142

d.rounded_rectangle((70, 838, W - 70, 878), radius=10, fill=(248, 250, 252), outline=BORDER, width=2)
d.text(
    (W / 2, 858),
    "PySide6 GUI + CLI 双入口  ·  单文件 EXE 分发（内置 imageio-ffmpeg）",
    font=font(19),
    fill=MUTED,
    anchor="mm",
)
img.save(OUT / "05-系统架构图.png")
print("saved 05-系统架构图.png", img.size)

# ───────────────────────── 06 处理流程图 ─────────────────────────
W, H = 1200, 1000
img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img)
d.text((W / 2, 40), "单条任务处理流程", font=font(36, True), fill=INK, anchor="mm")

steps = [
    ("输入一行文本", "extract_urls 提取 URL / 识别本地路径", SLATE_L, SLATE),
    ("判定类型", "本地文件 → ffmpeg 直取音轨；链接 → 进入路由", SLATE_L, SLATE),
    ("解析路由", "国内直连 / 境外走代理 / 代理预检", BLUE_L, BLUE),
    ("解析元数据", "内置解析器 或 yt-dlp 通用引擎", GREEN_L, GREEN),
    ("下载音频", "带重试与备用源回退", AMBER_L, AMBER),
    ("转码输出", "MP3/WAV/FLAC/M4A/AAC/OGG/Opus/WMA", PURPLE_L, PURPLE),
    ("写入标签", "ID3v2.3 或容器原生标签", PURPLE_L, PURPLE),
    ("汇总报告", "逐条结果写入 CSV 报告", SLATE_L, SLATE),
]
y = 90
for i, (title, sub, bg, bd) in enumerate(steps):
    box(d, 150, y, W - 300, 84, title, sub, bg, bd, tsize=24, ssize=16)
    if i < len(steps) - 1:
        arrow(d, W / 2, y + 88, W / 2, y + 112, color=(203, 213, 225), width=4)
    y += 116

img.save(OUT / "06-处理流程图.png")
print("saved 06-处理流程图.png", img.size)

# ───────────────────────── 07 智能路由决策图 ─────────────────────────
W, H = 1300, 780
img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img)
d.text((W / 2, 38), "智能路由决策（auto 模式）", font=font(34, True), fill=INK, anchor="mm")

box(d, W / 2 - 190, 76, 380, 74, "目标 URL", "取 hostname", SLATE_L, SLATE, tsize=24, ssize=16)
arrow(d, W / 2, 154, W / 2, 186)

box(d, W / 2 - 220, 190, 440, 74, "域名属于境外站点？", "youtube / tiktok / x …", AMBER_L, AMBER, tsize=24, ssize=16)

# 左：国内平台
box(d, 90, 320, 420, 190, "国内平台", "douyin / kuaishou / kugou\nbilibili / weibo / 163.com", GREEN_L, GREEN, tsize=26, ssize=17)
d.text((300, 478), "CDN 全球可达 → 直连", font=font(19, True), fill=GREEN, anchor="mm")
arrow(d, W / 2 - 160, 268, 300, 316, color=GREEN, width=4)

# 右：境外站点
box(d, 790, 320, 420, 190, "境外站点", "youtube / tiktok / x / ig\nsoundcloud / nicovideo …", AMBER_L, AMBER, tsize=26, ssize=17)
d.text((1000, 478), "国内网络通常不通 → 走代理", font=font(19, True), fill=AMBER, anchor="mm")
arrow(d, W / 2 + 160, 268, 1000, 316, color=AMBER, width=4)

box(d, 790, 560, 420, 96, "有指定代理？", "有 → 走代理；无 → 探测直连", AMBER_L, AMBER, tsize=22, ssize=16)
arrow(d, 1000, 514, 1000, 556, color=AMBER, width=4)

box(d, 90, 560, 420, 96, "境外用户同样适用", "直连可达 → 直接下载", GREEN_L, GREEN, tsize=22, ssize=16)
arrow(d, 786, 608, 516, 608, color=SLATE, width=3)

d.rounded_rectangle((70, 684, W - 70, 744), radius=10, fill=(248, 250, 252), outline=BORDER, width=2)
d.text(
    (W / 2, 714),
    "三种模式：auto（智能） / direct（全部直连） / proxy（全部走代理）",
    font=font(20),
    fill=MUTED,
    anchor="mm",
)
img.save(OUT / "07-智能路由决策图.png")
print("saved 07-智能路由决策图.png", img.size)
