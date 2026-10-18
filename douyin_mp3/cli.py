from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .batch import BatchProcessor
from .config import (
    AUDIO_SOURCE_CHOICES,
    DEFAULT_OUTPUT_DIR,
    ConvertOptions,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="douyin-mp3",
        description="批量提取视频中的音乐/歌曲为车机可播放的 MP3（支持抖音专用解析，B站/YouTube等站点走 yt-dlp 通用引擎）",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")

    convert = sub.add_parser("convert", help="批量转换（命令行模式）")
    convert.add_argument("inputs", nargs="+", help="视频链接或包含链接的分享文本（抖音/B站/YouTube/快手等）")
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
        default="192",
        help="音质: 128/192/256/320 或 32-320 任意整数（默认 192）",
    )
    convert.add_argument(
        "-s",
        "--source",
        choices=AUDIO_SOURCE_CHOICES,
        default="auto",
        help="音频来源: auto=优先配乐原曲, video=视频音轨, music=纯配乐",
    )
    convert.add_argument("--proxy", default=None, help="代理，如 http://127.0.0.1:7890")
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
        audio_source=args.source,
        proxy=args.proxy,
        ffmpeg_path=args.ffmpeg,
        skip_existing=args.skip_existing,
        delay=args.delay,
        keep_temp=args.keep_temp,
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
