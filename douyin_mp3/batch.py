from __future__ import annotations

import csv
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import requests

from .config import ConvertOptions, temp_dir
from .converter import Mp3Meta, convert_to_mp3, probe_duration_seconds, sanitize_filename
from .downloader import DownloadError, download_with_retry
from .parser import DouyinClient, DouyinParseError, VideoInfo, extract_urls


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
        self.on_log: LogFn = lambda msg: None
        self.on_item_start: ItemStartFn = lambda idx, total, url: None
        self.on_item_done: ItemDoneFn = lambda result: None
        self.on_all_done: AllDoneFn = lambda summary: None

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

    def _unique_path(self, directory: Path, base: str, template_index: int, title: str) -> Path:
        name = self.options.filename_template.format(index=template_index, title=sanitize_filename(title))
        name = sanitize_filename(name.replace("/", "_"))
        candidate = directory / f"{name}.mp3"
        counter = 2
        while candidate.exists():
            candidate = directory / f"{name} ({counter}).mp3"
            counter += 1
        return candidate

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

    def run(self, lines: list[str]) -> BatchSummary:
        links = self.collect_links(lines)
        summary = BatchSummary(total=len(links))
        if not links:
            self._log("未从输入中解析到抖音链接")
            self.on_all_done(summary)
            return summary

        options = self.options
        options.output_dir.mkdir(parents=True, exist_ok=True)
        client = DouyinClient(proxy=options.proxy)
        work_dir = temp_dir() / uuid.uuid4().hex[:8]
        work_dir.mkdir(parents=True, exist_ok=True)

        self._log(f"共 {len(links)} 条链接，输出目录: {options.output_dir}，质量: {options.bitrate}")
        report_rows: list[dict] = []

        try:
            for index, url in enumerate(links, start=1):
                if self._cancel.is_set():
                    self._log("已取消剩余任务")
                    break
                self.on_item_start(index, len(links), url)
                result = self._process_one(client, work_dir, index, url, len(links))
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
                if index < len(links) and not self._cancel.is_set():
                    time.sleep(max(options.delay, 0))
        finally:
            if not options.keep_temp:
                _rmtree(work_dir)
            self._write_report(report_rows)

        self._log(f"完成：成功 {summary.succeeded}，失败 {summary.failed}")
        self.on_all_done(summary)
        return summary

    def _process_one(
        self, client: DouyinClient, work_dir: Path, index: int, url: str, total: int
    ) -> TaskResult:
        options = self.options
        tmp_src = work_dir / f"{index:03d}.bin"
        try:
            info = None
            last_error: Exception | None = None
            for attempt in range(1, options.max_retries + 1):
                try:
                    info = client.fetch_info(url)
                    break
                except (DouyinParseError, requests.RequestException) as exc:
                    last_error = exc
                    self._log(f"[{index}/{total}] 解析失败(第{attempt}次): {exc}")
                    time.sleep(2 * attempt)
            if info is None:
                return TaskResult(index, url, "failed", f"解析失败: {last_error}")

            self._log(
                f"[{index}/{total}] 《{info.display_title}》 - {info.artist}"
            )
            if options.skip_existing:
                preview = self._unique_path(options.output_dir, "", index, info.display_title)
                if preview.exists():
                    return TaskResult(
                        index, url, "skipped", "已存在，跳过", str(preview), info.display_title, info.artist
                    )

            primary, fallbacks = self._pick_source_url(info)

            def _cb(done: int, done_total: int) -> None:
                if done_total:
                    pct = done * 100 // done_total
                    self._log(f"[{index}/{total}] 下载中 {pct}%")

            download_with_retry(
                primary,
                tmp_src,
                attempts=options.max_retries,
                session=client.session,
                progress=_cb,
                fallback_urls=[u for u in fallbacks if u],
            )

            duration = probe_duration_seconds(find_ffmpeg_cached(self.ffmpeg_path), tmp_src)
            title = sanitize_filename(info.display_title)
            out_path = self._unique_path(options.output_dir, "", index, info.display_title)
            convert_to_mp3(
                tmp_src,
                out_path,
                options.bitrate,
                ffmpeg=self.ffmpeg_path,
                meta=Mp3Meta(
                    title=title,
                    artist=info.artist,
                    comment=info.share_url,
                    track=index,
                ),
            )
            size = out_path.stat().st_size
            self._log(f"[{index}/{total}] 完成 -> {out_path.name} ({size / 1024 / 1024:.1f} MB)")
            return TaskResult(
                index,
                url,
                "ok",
                "成功",
                str(out_path),
                info.title,
                info.artist,
                duration,
                size,
            )
        except (DownloadError, DouyinParseError, OSError, ValueError) as exc:
            self._log(f"[{index}/{total}] 失败: {exc}")
            return TaskResult(index, url, "failed", str(exc))
        finally:
            tmp_src.unlink(missing_ok=True)

    def _write_report(self, rows: list[dict]) -> None:
        if not rows:
            return
        report = self.options.output_dir / f"转换报告_{time.strftime('%Y%m%d_%H%M%S')}.csv"
        try:
            with open(report, "w", newline="", encoding="utf-8-sig") as fh:
                writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)
            self._log(f"报告已保存: {report}")
        except OSError as exc:
            self._log(f"写报告失败: {exc}")


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
