"""打包 CSDN 资源上传用的发布物料（开发工具）。

产出: dist/release/MusicGrab-v1.8.0-win-x64.zip
      dist/release/发布说明.md
      dist/release/SHA256SUMS.txt
"""
from __future__ import annotations

import hashlib
import shutil
import zipfile
from pathlib import Path

root = Path(r"E:\ai\opencode\内网web自动化开发\douyin-mp3")
version = "1.8.0"
rel = root / "dist" / "release"
rel.mkdir(parents=True, exist_ok=True)

exe = root / "dist" / "MusicGrab.exe"
if not exe.exists():
    raise SystemExit("未找到 dist\\MusicGrab.exe，请先运行 packaging\\build_exe.ps1")

stage = rel / "MusicGrab-v1.8.0-win-x64"
if stage.exists():
    shutil.rmtree(stage)
stage.mkdir(parents=True)

# 应用本体
shutil.copy2(exe, stage / "MusicGrab.exe")

# 文档
for name in ("README.md", "LICENSE"):
    src = root / name
    if src.exists():
        shutil.copy2(src, stage / name)

# 发布说明（从 docs/releases 同步，作为资源详情页的底稿）
release_notes = root / "docs" / "releases" / f"v{version}.md"
if release_notes.exists():
    import re

    text = release_notes.read_text(encoding="utf-8")
    # zip 内不能写 zip 自身的 SHA256（自引用会导致校验值永远对不上），
    # 改为指向包外的 SHA256SUMS.txt；exe 的校验值不受影响，原样保留。
    text = re.sub(
        r"(SHA256 \(发布包[^)]*\)\s*[:：]\s*\n)`?[0-9a-f]{64}`?",
        r"\1见发布包同级的 SHA256SUMS.txt（写进包内会形成自引用）",
        text,
    )
    (stage / "发布说明.md").write_text(text, encoding="utf-8")

# 使用说明
usage = """乐取 MusicGrab v1.8.0 —— 使用说明
================================

【这是什么】
一个把各平台视频/音乐链接里的音轨批量提取、转换为车机可直接播放的音频文件的
Windows 桌面工具。同时支持直接处理本地视频文件。

【快速开始】
1. 双击 MusicGrab.exe（单文件，免安装，无需 Python 环境）
2. 在上方文本框粘贴链接，每行一条；也可以把视频文件、整个文件夹直接拖进窗口
   - 抖音：v.douyin.com/xxx/ 或 www.douyin.com/video/123 或 ?modal_id=123
   - 快手：v.kuaishou.com/xxx
   - 酷狗：www.kugou.com/mixsong/xxx.html
   - B站/微博/网易云/YouTube 等：直接贴链接
3. 点「开始转换」，结果默认输出到  C:\\Users\\<你的用户名>\\Music\\MusicGrab
4. 需要换目录/格式/音质，在「输出设置」页调整
5. 完成后切到「任务结果」页查看每条状态，右键可重试/打开文件

【处理本地视频】
点「添加本地文件…」或「添加文件夹…」，也可以直接把文件/文件夹拖进窗口。
文件夹会递归扫描（单次最多 2000 个），直接提取音轨，不需要联网。

【拖放说明】
- 可以拖：视频/音频文件、整个文件夹（拖到窗口任意位置都可以）
- 暂不支持拖动浏览器标签页：各浏览器给出的数据差异较大，网址请复制后粘贴

【转换报告】
每次批量结束会在输出目录写一份 CSV（序号/状态/标题/歌手/时长/大小/输出文件/来源）。
默认覆盖同名 转换报告.csv，目录里最多留一份；想保留历史可在
「输出设置 → 转换报告」改为「每次新建」，不需要则选「不生成」。

【关于代理】
默认「智能」模式：国内平台直连，境外站点（YouTube/TikTok/X 等）自动走代理。
如果访问不了境外站点，在「输出设置 → 代理」填入代理地址，例如 http://127.0.0.1:7890。
境外的用户请用「全部直连」模式。

【输出格式】
MP3 / M4A / Opus / FLAC / WAV / BEST（源格式不转码）
- MP3：车机首选，写 ID3v2.3 标签
- M4A / Opus：有损压缩，体积更小
- FLAC / WAV：无损，体积较大
- BEST：直接复制源音轨，不转码、零损失；扩展名随源音频编码
默认 MP3 320kbps，44.1kHz 立体声。

【音质】
V0（LAME 最佳 VBR，推荐）/ 320 / 256 / 192 / 128 / 96 kbps 固定码率。
FLAC / WAV / BEST 会自动忽略码率设置。

【封面嵌入】
抖音 / 快手 / 酷狗 / B站等会自动抓取平台封面并写入音频；本地视频抽取第一帧。
MP3 / M4A / FLAC 支持封面；WAV / Opus 容器不支持，会自动跳过（不影响音频）。

【任务结果与重试】
转换完成后切到「任务结果」页，逐条显示成功/失败、标题、时长、大小与输出文件。
右键单条可「重试此任务」「打开文件」「打开所在文件夹」「复制来源地址」；
顶部「重试全部失败项」可一键重跑，文件名序号保持不变。

【组件自检与在线升级】
程序内置的 yt-dlp 与 ffmpeg 是打包时冻结的副本，不会自动更新。
启动时会联网比对官方最新版本，若发现新版本，窗口顶部会出现黄色提示条，
点「立即升级」即可下载官方安装包并替换内置的那一份（仅需重启一次生效）。
不想联网可在「输出设置 → 组件更新」里关掉自动检查。

下载好的组件放在哪里？
- 优先放在 MusicGrab.exe 同目录的 MusicGrab_components 文件夹里（便携模式：
  换电脑、拷到 U 盘时，把这个文件夹一起带走即可，不用重新下载）
- 如果 exe 所在目录不可写（例如放在 Program Files），则放在
  %LOCALAPPDATA%\\MusicGrab\\ ，同一台电脑上的多个程序副本共用一份
组件的版本号记录在组件自己身上，因此即使状态文件被清理掉，也不会反复提示更新。
想回到程序内置的版本：点「输出设置 → 组件更新 → 恢复内置组件」。

【常见问题】
- 提示「代理无法连接」：代理软件没启动或端口不对，用「全部直连」或填正确地址
- 提示「境外站点不可达」：需要配置代理
- 提示「VIP/付费歌曲」：该曲目为平台付费内容，未登录无法下载
- 抖音提示「页面结构未找到视频数据」：平台风控，程序会自动重试，可稍后再试
- 某个站点突然解析不了：多半是内置 yt-dlp 过旧，用顶部的「立即升级」更新一下
- 杀毒软件误报：PyInstaller 打包的常见误报，可加信任

【重要声明】
本工具仅供个人学习、研究与非商业用途使用。
使用者需自行遵守所访问平台的服务条款及所在地法律法规，
由此产生的任何法律责任由使用者自行承担。
"""
( stage / "使用说明.txt").write_text(usage, encoding="utf-8")

# 打包
zip_path = rel / f"MusicGrab-v{version}-win-x64.zip"
if zip_path.exists():
    zip_path.unlink()
with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
    for p in sorted(stage.rglob("*")):
        if p.is_file():
            zf.write(p, p.relative_to(stage))
shutil.rmtree(stage)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


sums = f"{sha256(zip_path)}  {zip_path.name}\n"
(rel / "SHA256SUMS.txt").write_text(sums, encoding="utf-8")

print("发布包:", zip_path)
print("大小: %.1f MB" % (zip_path.stat().st_size / 1024 / 1024))
print("SHA256:", sha256(zip_path))
print("EXE SHA256:", sha256(exe))
print("EXE 大小: %.1f MB" % (exe.stat().st_size / 1024 / 1024))
