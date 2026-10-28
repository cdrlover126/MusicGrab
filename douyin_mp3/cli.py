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
    REPORT_MODES,
    ConvertOptions,
)
from .proxy import ROUTE_MODES


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="douyin-mp3",
        description=(
            "批量提取视频中的音乐/歌曲为车机可播放的 MP3"
            "（抖音/快手/酷狗用内置解析器，B站/YouTube/微博/网易云等站点走 yt-dlp 通用引擎）"
        ),
        epilog=(
            "子命令: convert 批量转换 | gui 图形界面 | "
            "check-update 检查 yt-dlp/ffmpeg 组件更新（内置组件不会自动更新）"
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")

    convert = sub.add_parser("convert", help="批量转换（命令行模式）")
    convert.add_argument(
        "inputs", nargs="+", help="视频链接、分享文本，或本地视频/音频文件、文件夹路径"
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
        help="音质: v0=最佳VBR，320/256/192/128/96=CBR，或 32-320 任意整数（默认 320）",
    )
    convert.add_argument(
        "-f",
        "--format",
        choices=OUTPUT_FORMAT_CHOICES,
        default="mp3",
        help="输出格式: mp3/m4a/opus/flac/wav/best（best=源格式不转码，默认 mp3）",
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
        "--route",
        choices=ROUTE_MODES,
        default="auto",
        help="路由: auto=智能(国内直连/境外走代理) direct=全部直连 proxy=全部走代理",
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
    convert.add_argument(
        "--report",
        choices=REPORT_MODES,
        default="overwrite",
        help=(
            "转换报告保存方式：overwrite=覆盖同名文件（默认，只留一份）| "
            "history=每次新建带时间戳 | none=不生成"
        ),
    )

    sub.add_parser("gui", help="启动图形界面（默认）")

    check = sub.add_parser(
        "check-update",
        help="检查 yt-dlp / ffmpeg 组件是否有新版本（打包后内置组件不会自动更新）",
    )
    check.add_argument("--json", action="store_true", help="以 JSON 输出，便于脚本处理")
    check.add_argument(
        "--upgrade",
        action="store_true",
        help="发现新版本时直接下载安装（需要重启程序后生效）",
    )
    return parser


def run_convert(args: argparse.Namespace) -> int:
    options = ConvertOptions(
        output_dir=Path(args.output).expanduser(),
        quality=args.quality,
        output_format=args.format,
        audio_source=args.source,
        engine=args.engine,
        proxy=args.proxy,
        route_mode=args.route,
        trust_env=False,
        ffmpeg_path=args.ffmpeg,
        skip_existing=args.skip_existing,
        delay=args.delay,
        keep_temp=args.keep_temp,
        cookies_file=args.cookies,
        cookies_from_browser=args.cookies_from_browser,
        report_mode=args.report,
    )
    processor = BatchProcessor(options, ffmpeg_path=args.ffmpeg)
    processor.on_log = lambda msg: print(msg, flush=True)
    lines = list(args.inputs)
    summary = processor.run(lines)
    return 0 if summary.succeeded else 1


def run_check_update(args: argparse.Namespace) -> int:
    """检查组件版本，可选直接升级。"""
    from . import updater

    statuses = updater.check_components()
    payload = [
        {
            "key": s.key,
            "label": s.label,
            "current": s.current,
            "latest": s.latest,
            "has_update": s.has_update,
            "source": s.source,
            "detail": s.detail,
            "error": s.error,
        }
        for s in statuses
    ]
    if args.json:
        print(__import__("json").dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"组件版本自检（{updater.overlay_root()}）")
        for item in payload:
            if item["error"]:
                print(f"  {item['label']}: 检查失败 —— {item['error']}")
                continue
            mark = "有更新" if item["has_update"] else "已是最新"
            print(f"  {item['label']}: {item['current'] or '未知'} → {item['latest']}  [{mark}]")
            if item["detail"]:
                print(f"      {item['detail']}")

    if not args.upgrade:
        return 0 if any(s.has_update for s in statuses) else 0

    changed = False
    for status in statuses:
        if not status.has_update:
            continue
        try:
            print(f"  正在升级 {status.label} → {status.latest} …", flush=True)
            print("  " + updater.upgrade_component(status))
            changed = True
        except Exception as exc:
            print(f"  升级 {status.label} 失败：{exc}", file=sys.stderr)
    if changed:
        print("  完成，重启程序后新版本才会生效。")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "convert":
        return run_convert(args)
    if args.command == "check-update":
        return run_check_update(args)
    from .gui import run_gui

    return run_gui()


if __name__ == "__main__":
    sys.exit(main())
