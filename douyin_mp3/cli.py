from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .batch import BatchProcessor
from .config import (
    AUDIO_SOURCE_CHOICES,
    COOKIE_BROWSER_CHOICES,
    DEFAULT_OUTPUT_DIR,
    ENGINE_CHOICES,
    OUTPUT_FORMAT_CHOICES,
    ConvertOptions,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="douyin-mp3",
        description=(
            "批量提取视频中的音乐/歌曲为车机可播放的 MP3"
            "（抖音/快手/酷狗用内置解析器，B站/YouTube/微博/网易云等站点走 yt-dlp 通用引擎）"
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")

    convert = sub.add_parser("convert", help="批量转换（命令行模式）")
    convert.add_argument(
        "inputs", nargs="+", help="视频链接或包含链接的分享文本（抖音/快手/酷狗/B站/微博/网易云等）"
    )
    convert.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"输出目录（默认: {DEFAULT_OUTPUT_DIR}）",
    )
    convert.add_argument(
        "-q",
        "--quality",
        default="320",
        help="音质: 128/192/256/320 或 32-320 任意整数（默认 320）",
    )
    convert.add_argument(
        "-f",
        "--format",
        choices=OUTPUT_FORMAT_CHOICES,
        default="mp3",
        help="输出格式: mp3/wav/flac/m4a/aac/ogg/opus/wma（默认 mp3，车机首选）",
    )
    convert.add_argument(
        "-s",
        "--source",
        choices=AUDIO_SOURCE_CHOICES,
        default="auto",
        help="音频来源: auto=优先配乐原曲, video=视频音轨, music=纯配乐（抖音专用）",
    )
    convert.add_argument(
        "--engine",
        choices=ENGINE_CHOICES,
        default="auto",
        help="解析引擎: auto=抖音/快手/酷狗用内置解析器, douyin=强制内置, generic=强制 yt-dlp",
    )
    convert.add_argument("--proxy", default=None, help="代理，如 http://127.0.0.1:7890")
    convert.add_argument(
        "--direct",
        action="store_true",
        help="强制直连，忽略系统/环境变量中的代理（默认行为，显式声明用）",
    )
    convert.add_argument(
        "--follow-system-proxy",
        action="store_true",
        help="跟随系统/环境变量中的代理（默认直连；国内平台直连即可，境外站点请用 --proxy）",
    )
    convert.add_argument(
        "--cookies",
        default=None,
        help="cookies 文件（Netscape 格式，用于西瓜/小红书/QQ音乐等需登录站点）",
    )
    convert.add_argument(
        "--cookies-from-browser",
        choices=COOKIE_BROWSER_CHOICES,
        default=None,
        help="从浏览器读取 cookies（edge/chrome/firefox 等），免手工导出",
    )
    convert.add_argument("--ffmpeg", default=None, help="指定 ffmpeg 路径")
    convert.add_argument("--skip-existing", action="store_true", help="跳过同名已存在文件")
    convert.add_argument("--delay", type=float, default=1.5, help="每条任务间隔秒数（防风控）")
    convert.add_argument("--keep-temp", action="store_true", help="保留临时文件便于排查")

    sub.add_parser("gui", help="启动图形界面（默认）")
    return parser


def run_convert(args: argparse.Namespace) -> int:
    options = ConvertOptions(
        output_dir=Path(args.output).expanduser(),
        quality=args.quality,
        output_format=args.format,
        audio_source=args.source,
        engine=args.engine,
        proxy=args.proxy,
        trust_env=args.follow_system_proxy and not args.direct,
        ffmpeg_path=args.ffmpeg,
        skip_existing=args.skip_existing,
        delay=args.delay,
        keep_temp=args.keep_temp,
        cookies_file=args.cookies,
        cookies_from_browser=args.cookies_from_browser,
    )
    processor = BatchProcessor(options, ffmpeg_path=args.ffmpeg)
    processor.on_log = lambda msg: print(msg, flush=True)
    lines = list(args.inputs)
    summary = processor.run(lines)
    return 0 if summary.succeeded else 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "convert":
        return run_convert(args)
    from .gui import run_gui

    return run_gui()


if __name__ == "__main__":
    sys.exit(main())
