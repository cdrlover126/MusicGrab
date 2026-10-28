from __future__ import annotations

import csv
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

import requests

from .config import (
    REPORT_FILE_NAME,
    REPORT_HISTORY_PREFIX,
    REPORT_HISTORY_SUFFIX,
    ConvertOptions,
    describe_quality,
    resolve_output_format,
    temp_dir,
)
from .converter import (
    ConverterError,
    Mp3Meta,
    convert_to_audio,
    convert_to_mp3,
    probe_duration_seconds,
    resolve_extension,
    sanitize_filename,
)
from .cookies import CookieError
from .downloader import DownloadError, download_file, download_with_retry
from .generic import GenericParseError, download_generic_audio
from .kuaishou import KuaishouClient, KuaishouParseError
from .kugou import KugouClient, KugouParseError
from .local_media import collect_media_paths, is_media_file
from .parser import (
    DouyinClient,
    DouyinParseError,
    VideoInfo,
    classify_platform,
    extract_urls,
)
from .proxy import (
    ROUTE_MODE_LABELS,
    ProxyUnreachableError,
    Route,
    build_session,
    check_proxy_reachable,
    describe_effective_proxy,
    is_proxy_error,
    is_timeout_error,
    normalize_proxy,
    proxy_error_message,
    resolve_route,
    timeout_error_message,
)


@dataclass
class TaskResult:
    index: int
    source: str
    status: str
    message: str = ""
    output_path: str = ""
    title: str = ""
    artist: str = ""
    duration: float = 0.0
    size: int = 0


@dataclass
class BatchSummary:
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    results: list[TaskResult] = field(default_factory=list)


LogFn = Callable[[str], None]
ItemStartFn = Callable[[int, int, str], None]
ItemDoneFn = Callable[[TaskResult], None]
AllDoneFn = Callable[[BatchSummary], None]


class BatchProcessor:
    def __init__(self, options: ConvertOptions, *, ffmpeg_path: str | None = None):
        self.options = options
        self.ffmpeg_path = ffmpeg_path or options.ffmpeg_path
        self._cancel = threading.Event()
        self._kuaishou: KuaishouClient | None = None
        self._kugou: KugouClient | None = None
        self.on_log: LogFn = lambda msg: None
        self.on_item_start: ItemStartFn = lambda idx, total, url: None
        self.on_item_done: ItemDoneFn = lambda result: None
        self.on_all_done: AllDoneFn = lambda summary: None

    def _kuaishou_client(self) -> KuaishouClient:
        if self._kuaishou is None:
            # 代理按每条任务的路由决策动态设置，此处不固定
            self._kuaishou = KuaishouClient(
                proxy=None,
                cookies_file=self.options.cookies_file,
                cookies_from_browser=self.options.cookies_from_browser,
                trust_env=False,
            )
        return self._kuaishou

    def _kugou_client(self) -> KugouClient:
        if self._kugou is None:
            self._kugou = KugouClient(
                proxy=None,
                cookies_file=self.options.cookies_file,
                cookies_from_browser=self.options.cookies_from_browser,
                trust_env=False,
            )
        return self._kugou

    def cancel(self) -> None:
        self._cancel.set()

    def _log(self, msg: str) -> None:
        self.on_log(msg)

    @staticmethod
    def collect_links(lines: list[str]) -> list[str]:
        links: list[str] = []
        for line in lines:
            for url in extract_urls(line):
                if url not in links:
                    links.append(url)
        return links

    @staticmethod
    def collect_local_files(lines: list[str]) -> list[Path]:
        """从输入行中收集本地媒体文件路径（文件夹会递归展开）。"""
        candidates: list[Path] = []
        for line in lines:
            text = line.strip().strip('"').strip("'")
            if not text or "://" in text:
                continue
            path = Path(text).expanduser()
            if path.is_dir() or is_media_file(path):
                candidates.append(path)
        files, _ = collect_media_paths(candidates)
        return files

    def _base_path(
        self,
        directory: Path,
        template_index: int,
        title: str,
        ext: str | None = None,
    ) -> Path:
        """按命名模板算出「首选」输出路径（不考虑重名）。"""
        name = self.options.filename_template.format(
            index=template_index, title=sanitize_filename(title)
        )
        name = sanitize_filename(name.replace("/", "_"))
        if ext is None:
            ext = resolve_output_format(self.options.output_format).ext
        return directory / f"{name}.{ext}"

    def _unique_path(
        self,
        directory: Path,
        template_index: int,
        title: str,
        ext: str | None = None,
    ) -> Path:
        candidate = self._base_path(directory, template_index, title, ext)
        counter = 2
        while candidate.exists():
            candidate = candidate.with_name(f"{candidate.stem} ({counter}){candidate.suffix}")
            counter += 1
        return candidate

    def _output_extension(self, source: Path | None = None) -> str:
        """决定输出扩展名。

        BEST（不转码）模式下扩展名取决于源音频编码，必须先探测才知道。
        """
        return resolve_extension(
            self.options.output_format,
            source,
            find_ffmpeg_cached(self.ffmpeg_path) or None,
        )

    def _fetch_cover(
        self,
        cover_url: str,
        work_dir: Path,
        proxy: str | None = None,
    ) -> Path | None:
        """下载封面图；失败返回 None（封面缺失不应阻断转码）。"""
        if not cover_url:
            return None
        ext = ".png" if ".png" in cover_url.lower() else ".jpg"
        dest = work_dir / f"cover{ext}"
        parts = urlsplit(cover_url)
        headers = {"Referer": f"{parts.scheme}://{parts.netloc}/"} if parts.netloc else None
        try:
            session = build_session(proxy, trust_env=self.options.trust_env)
            download_file(cover_url, dest, session=session, timeout=30, headers=headers)
        except (DownloadError, OSError, requests.RequestException):
            dest.unlink(missing_ok=True)
            return None
        if not dest.exists() or dest.stat().st_size < 512:
            dest.unlink(missing_ok=True)
            return None
        return dest

    def _frame_cover(self, source: Path, work_dir: Path) -> Path | None:
        """从本地视频抽一帧当封面（离线可用）。"""
        ffmpeg = find_ffmpeg_cached(self.ffmpeg_path)
        if not ffmpeg:
            return None
        dest = work_dir / "frame.jpg"
        for seek in ("1", "0"):
            dest.unlink(missing_ok=True)
            cmd = [
                ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                seek,
                "-i",
                str(source),
                "-frames:v",
                "1",
                "-q:v",
                "3",
                str(dest),
            ]
            try:
                proc = subprocess.run(cmd, capture_output=True, timeout=60)
            except (OSError, subprocess.SubprocessError):
                continue
            if proc.returncode == 0 and dest.exists() and dest.stat().st_size > 512:
                return dest
        dest.unlink(missing_ok=True)
        return None

    def _pick_source_url(self, info: VideoInfo) -> tuple[str, list[str]]:
        mode = self.options.audio_source
        primary_music = bool(info.music_url)
        if mode == "music" or (mode == "auto" and primary_music):
            if info.music_url:
                return info.music_url, [info.video_url] if info.video_url else []
            self._log(f"[{info.aweme_id}] 未找到配乐原曲，改用视频音轨")
        if info.video_url:
            return info.video_url, []
        if info.music_url:
            return info.music_url, []
        raise DownloadError("该视频没有可用的播放地址")

    def run(self, lines: list[str], indices: list[int] | None = None) -> BatchSummary:
        links = self.collect_links(lines)
        local_files = self.collect_local_files(lines)
        total_items = len(links) + len(local_files)
        summary = BatchSummary(total=total_items)
        if not total_items:
            self._log("未从输入中解析到链接或本地文件")
            self.on_all_done(summary)
            return summary

        options = self.options
        options.output_dir.mkdir(parents=True, exist_ok=True)

        # 路由模式说明
        self._log(f"路由模式: {ROUTE_MODE_LABELS.get(options.route_mode, options.route_mode)}")
        if options.route_mode == "auto":
            self._log("规则: 国内平台直连 · 境外站点优先用指定代理，无代理时尝试系统代理/直连")
        self._log(describe_effective_proxy(options.proxy, options.route_mode))

        # 代理预检：代理不通时给出明确提示
        proxy_ok = True
        try:
            check_proxy_reachable(options.proxy)
        except ProxyUnreachableError as exc:
            proxy_ok = False
            self._log(f"代理检测失败: {exc}")
            if options.route_mode == "proxy":
                self.on_all_done(summary)
                return summary
            if options.route_mode == "auto":
                self._log("已跳过代理，国内平台仍按直连处理；境外站点将无法访问。")

        client = DouyinClient(
            proxy=None,
            cookies_file=options.cookies_file,
            cookies_from_browser=options.cookies_from_browser,
            trust_env=options.trust_env,
        )
        work_dir = temp_dir() / uuid.uuid4().hex[:8]
        work_dir.mkdir(parents=True, exist_ok=True)

        fmt_label = resolve_output_format(options.output_format).label
        self._log(
            f"共 {len(links)} 条链接"
            + (f" + {len(local_files)} 个本地文件" if local_files else "")
            + f"，输出目录: {options.output_dir}，音质: {describe_quality(options.quality)}，格式: {fmt_label}"
        )
        report_rows: list[dict] = []

        tasks: list[tuple[str, str]] = [("link", url) for url in links]
        tasks.extend(("file", str(path)) for path in local_files)

        try:
            for position, (kind, target) in enumerate(tasks):
                index = indices[position] if indices and position < len(indices) else position + 1
                if self._cancel.is_set():
                    self._log("已取消剩余任务")
                    break
                self.on_item_start(position + 1, total_items, target)
                if kind == "file":
                    result = self._process_local_file(
                        work_dir, index, Path(target), total_items, position + 1
                    )
                else:
                    result = self._process_one(
                        client, work_dir, index, target, total_items, position + 1
                    )
                summary.results.append(result)
                if result.status == "ok":
                    summary.succeeded += 1
                else:
                    summary.failed += 1
                report_rows.append(
                    {
                        "序号": result.index,
                        "状态": result.status,
                        "标题": result.title,
                        "歌手": result.artist,
                        "时长秒": round(result.duration, 1),
                        "大小字节": result.size,
                        "输出": result.output_path,
                        "来源": result.source,
                        "说明": result.message,
                    }
                )
                self.on_item_done(result)
                if index < total_items and not self._cancel.is_set():
                    time.sleep(max(options.delay, 0))
        finally:
            if not options.keep_temp:
                _rmtree(work_dir)
            self._write_report(report_rows)

        self._log(f"完成：成功 {summary.succeeded}，失败 {summary.failed}")
        self.on_all_done(summary)
        return summary

    def _process_local_file(
        self,
        work_dir: Path,
        index: int,
        src: Path,
        total: int,
        display: int | None = None,
    ) -> TaskResult:
        """处理本地视频/音频文件：直接用 ffmpeg 提取音轨，无需解析与下载。"""
        options = self.options
        display = display or index
        try:
            if not src.is_file():
                return TaskResult(index, str(src), "failed", f"文件不存在: {src}")

            title = sanitize_filename(src.stem)
            self._log(f"[{display}/{total}] 本地文件《{title}》({src.suffix.lower()})")

            duration = probe_duration_seconds(find_ffmpeg_cached(self.ffmpeg_path) or "", src)
            ext = self._output_extension(src)
            out_path = self._unique_path(options.output_dir, index, title, ext)
            cover = self._frame_cover(src, work_dir)
            convert_to_audio(
                src,
                out_path,
                options.bitrate,
                fmt=options.output_format,
                ffmpeg=self.ffmpeg_path,
                meta=Mp3Meta(
                    title=title,
                    artist="本地文件",
                    album="本地媒体",
                    comment=str(src),
                    track=index,
                ),
                cover=cover,
            )
            size = out_path.stat().st_size
            self._log(f"[{display}/{total}] 完成 -> {out_path.name} ({size / 1024 / 1024:.1f} MB)")
            return TaskResult(
                index, str(src), "ok", "成功", str(out_path), title, "本地文件", duration, size
            )
        except (ConverterError, OSError, ValueError) as exc:
            self._log(f"[{display}/{total}] 失败: {exc}")
            return TaskResult(index, str(src), "failed", str(exc))

    def _apply_route(self, client: DouyinClient, route: Route) -> None:
        """按当前任务的路由决策配置会话。"""
        text = normalize_proxy(self.options.proxy) if route.use_proxy else ""
        if text:
            client.session.trust_env = False
            client.session.proxies.update({"http": text, "https": text})
        else:
            client.session.trust_env = route.use_system
            client.session.proxies.clear()

    def _process_one(
        self,
        client: DouyinClient,
        work_dir: Path,
        index: int,
        url: str,
        total: int,
        display: int | None = None,
    ) -> TaskResult:
        options = self.options
        display = display or index
        tmp_src = work_dir / f"{index:03d}.bin"
        platform = classify_platform(url)
        use_builtin = options.use_builtin_parser
        if not use_builtin and platform in ("douyin", "kuaishou", "kugou"):
            platform = "generic"

        # 逐条决定直连 / 走代理
        route = resolve_route(url, options.route_mode, options.proxy)
        if route.error:
            self._log(f"[{display}/{total}] {route.error}")
            return TaskResult(index, url, "failed", route.error)
        self._log(f"[{display}/{total}] 路由: {route.reason}")
        task_proxy = normalize_proxy(options.proxy) if route.use_proxy else None

        try:
            def _cb(done: int, done_total: int) -> None:
                if done_total:
                    pct = done * 100 // done_total
                    self._log(f"[{display}/{total}] 下载中 {pct}%")

            title = artist = comment = ""
            duration = 0.0
            album = "抖音音乐"
            cover_url = ""

            if platform == "douyin":
                self._apply_route(client, route)
                info = None
                last_error: Exception | None = None
                for attempt in range(1, options.max_retries + 1):
                    try:
                        info = client.fetch_info(url)
                        break
                    except (DouyinParseError, requests.RequestException) as exc:
                        last_error = exc
                        if is_proxy_error(exc):
                            msg = proxy_error_message(exc, options.proxy)
                            self._log(f"[{display}/{total}] {msg}")
                            return TaskResult(index, url, "failed", msg)
                        if is_timeout_error(exc):
                            msg = timeout_error_message(exc, options.proxy)
                            self._log(f"[{display}/{total}] {msg}")
                            return TaskResult(index, url, "failed", msg)
                        self._log(f"[{display}/{total}] 解析失败(第{attempt}次): {exc}")
                        time.sleep(2 * attempt)
                if info is None:
                    return TaskResult(index, url, "failed", f"解析失败: {last_error}")

                self._log(f"[{display}/{total}] 《{info.display_title}》 - {info.artist}")
                primary, fallbacks = self._pick_source_url(info)
                download_with_retry(
                    primary,
                    tmp_src,
                    attempts=options.max_retries,
                    session=client.session,
                    progress=_cb,
                    fallback_urls=[u for u in fallbacks if u],
                )
                title, artist, comment = info.display_title, info.artist, info.share_url
                duration = info.duration_ms / 1000 or probe_duration_seconds(
                    find_ffmpeg_cached(self.ffmpeg_path), tmp_src
                )
                cover_url = info.cover_url
            elif platform == "kuaishou":
                kuaishou_client = self._kuaishou_client()
                self._apply_route(kuaishou_client, route)
                info = None
                last_error = None
                for attempt in range(1, options.max_retries + 1):
                    try:
                        info = kuaishou_client.fetch_info(url)
                        break
                    except (KuaishouParseError, requests.RequestException) as exc:
                        last_error = exc
                        if is_proxy_error(exc):
                            msg = proxy_error_message(exc, options.proxy)
                            self._log(f"[{display}/{total}] {msg}")
                            return TaskResult(index, url, "failed", msg)
                        if is_timeout_error(exc):
                            msg = timeout_error_message(exc, options.proxy)
                            self._log(f"[{display}/{total}] {msg}")
                            return TaskResult(index, url, "failed", msg)
                        self._log(f"[{display}/{total}] 快手解析失败(第{attempt}次): {exc}")
                        time.sleep(2 * attempt)
                if info is None:
                    return TaskResult(index, url, "failed", f"快手解析失败: {last_error}")

                self._log(f"[{display}/{total}] 《{info.display_title}》 - {info.artist}")
                download_with_retry(
                    info.video_urls[0],
                    tmp_src,
                    attempts=options.max_retries,
                    session=kuaishou_client.session,
                    progress=_cb,
                    fallback_urls=info.video_urls[1:],
                )
                title, artist, comment = info.display_title, info.artist, info.share_url
                duration = info.duration_ms / 1000 or probe_duration_seconds(
                    find_ffmpeg_cached(self.ffmpeg_path), tmp_src
                )
                cover_url = info.cover_url
            elif platform == "kugou":
                kugou_client = self._kugou_client()
                self._apply_route(kugou_client, route)
                info = None
                last_error = None
                for attempt in range(1, options.max_retries + 1):
                    try:
                        info = kugou_client.fetch_info(url)
                        break
                    except (KugouParseError, requests.RequestException) as exc:
                        last_error = exc
                        if is_proxy_error(exc):
                            msg = proxy_error_message(exc, options.proxy)
                            self._log(f"[{display}/{total}] {msg}")
                            return TaskResult(index, url, "failed", msg)
                        if is_timeout_error(exc):
                            msg = timeout_error_message(exc, options.proxy)
                            self._log(f"[{display}/{total}] {msg}")
                            return TaskResult(index, url, "failed", msg)
                        self._log(f"[{display}/{total}] 酷狗解析失败(第{attempt}次): {exc}")
                        time.sleep(2 * attempt)
                if info is None:
                    return TaskResult(index, url, "failed", f"酷狗解析失败: {last_error}")

                self._log(f"[{display}/{total}] 《{info.title}》 - {info.artist}")
                download_with_retry(
                    info.play_url,
                    tmp_src,
                    attempts=options.max_retries,
                    session=kugou_client.session,
                    progress=_cb,
                    fallback_urls=[],
                )
                title, artist, comment = info.title, info.artist or "未知歌手", info.share_url
                album = info.album or "酷狗音乐"
                duration = info.duration_ms / 1000 or probe_duration_seconds(
                    find_ffmpeg_cached(self.ffmpeg_path), tmp_src
                )
                cover_url = info.cover_url
            else:
                from .parser import PLATFORM_LABELS

                label = PLATFORM_LABELS.get(platform, platform)
                self._log(f"[{display}/{total}] 识别为{label}链接，使用通用引擎(yt-dlp)")
                meta = download_generic_audio(
                    url,
                    tmp_src,
                    proxy=task_proxy,
                    progress=_cb,
                    cookies_file=options.cookies_file,
                    cookies_from_browser=options.cookies_from_browser,
                    trust_env=route.use_system,
                )
                title, artist, comment = meta.title, meta.artist, meta.webpage_url
                album = meta.album or "网络音乐"
                duration = meta.duration or probe_duration_seconds(
                    find_ffmpeg_cached(self.ffmpeg_path), tmp_src
                )
                cover_url = meta.thumbnail
                self._log(f"[{display}/{total}] 《{title}》 - {artist}")

            ext = self._output_extension(tmp_src)
            if options.skip_existing:
                preview = self._base_path(options.output_dir, index, title, ext)
                if preview.exists():
                    return TaskResult(
                        index, url, "skipped", "已存在，跳过", str(preview), title, artist
                    )

            out_path = self._unique_path(options.output_dir, index, title, ext)
            cover = self._fetch_cover(cover_url, work_dir, task_proxy)
            convert_to_audio(
                tmp_src,
                out_path,
                options.bitrate,
                fmt=options.output_format,
                ffmpeg=self.ffmpeg_path,
                meta=Mp3Meta(
                    title=sanitize_filename(title),
                    artist=artist,
                    album=album if platform != "douyin" else "抖音音乐",
                    comment=comment,
                    track=index,
                ),
                cover=cover,
            )
            size = out_path.stat().st_size
            note = "，含封面" if cover else ""
            self._log(
                f"[{display}/{total}] 完成 -> {out_path.name} ({size / 1024 / 1024:.1f} MB){note}"
            )
            return TaskResult(index, url, "ok", "成功", str(out_path), title, artist, duration, size)
        except (
            DownloadError,
            DouyinParseError,
            KuaishouParseError,
            KugouParseError,
            GenericParseError,
            CookieError,
            OSError,
            ValueError,
        ) as exc:
            self._log(f"[{display}/{total}] 失败: {exc}")
            return TaskResult(index, url, "failed", str(exc))
        finally:
            tmp_src.unlink(missing_ok=True)

    def _write_report(self, rows: list[dict]) -> None:
        """写出转换报告 CSV。

        默认「覆盖同名文件」：输出目录里只保留一份 ``转换报告.csv``，
        并顺带清掉历史遗留的时间戳报告，避免目录越用越乱。
        """
        mode = getattr(self.options, "report_mode", "overwrite") or "overwrite"
        if mode == "none" or not rows:
            return
        output_dir = self.options.output_dir
        removed = 0
        if mode == "overwrite":
            report = output_dir / REPORT_FILE_NAME
            removed = self._remove_history_reports(output_dir)
        else:
            stamp = time.strftime("%Y%m%d_%H%M%S")
            report = output_dir / f"{REPORT_HISTORY_PREFIX}{stamp}{REPORT_HISTORY_SUFFIX}"
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            with open(report, "w", newline="", encoding="utf-8-sig") as fh:
                writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)
            self._log(f"报告已保存: {report}")
            if removed:
                self._log(f"已清理 {removed} 个历史报告文件（{REPORT_HISTORY_PREFIX}*）")
        except OSError as exc:
            self._log(f"写报告失败: {exc}")

    @staticmethod
    def _remove_history_reports(output_dir: Path) -> int:
        """删除旧版本留下的时间戳报告文件，返回删除数量。"""
        removed = 0
        try:
            stale = sorted(output_dir.glob(f"{REPORT_HISTORY_PREFIX}*{REPORT_HISTORY_SUFFIX}"))
        except OSError:
            return 0
        for old in stale:
            try:
                old.unlink()
                removed += 1
            except OSError:
                continue
        return removed


_ffmpeg_cache: str | None = None


def find_ffmpeg_cached(configured: str | None = None) -> str | None:
    global _ffmpeg_cache
    if _ffmpeg_cache is None:
        from .converter import find_ffmpeg

        try:
            _ffmpeg_cache = find_ffmpeg(configured)
        except Exception:
            return configured
    return _ffmpeg_cache


def _rmtree(path: Path) -> None:
    import shutil

    shutil.rmtree(path, ignore_errors=True)
