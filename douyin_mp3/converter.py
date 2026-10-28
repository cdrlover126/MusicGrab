from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from mutagen.id3 import ID3, COMM, TALB, TCON, TIT2, TPE1, TRCK
from mutagen.id3._util import ID3NoHeaderError

from .config import CHANNELS, ID3_VERSION, SAMPLE_RATE, resolve_output_format

DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


class ConverterError(RuntimeError):
    pass


def find_ffmpeg(configured: str | None = None) -> str:
    candidates: list[str] = []
    if configured:
        candidates.append(configured)
    # 「组件升级」安装的外置 ffmpeg 优先于系统与内置版本
    try:
        from .updater import overlay_ffmpeg_exe

        overlay = overlay_ffmpeg_exe()
        if overlay:
            candidates.append(str(overlay))
    except Exception:
        pass
    env_path = shutil.which("ffmpeg")
    if env_path:
        candidates.append(env_path)
    try:
        import imageio_ffmpeg

        candidates.append(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:
        pass
    for cand in candidates:
        if cand and Path(cand).exists():
            return cand
    raise ConverterError(
        "未找到 ffmpeg。请安装 ffmpeg，或执行 pip install imageio-ffmpeg 使用内置转码器。"
    )


def probe_duration_seconds(ffmpeg: str, src: Path) -> float:
    try:
        proc = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", str(src)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        m = DURATION_RE.search(proc.stderr or "")
        if m:
            h, mi, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
            return h * 3600 + mi * 60 + s
    except OSError:
        pass
    return 0.0


@dataclass
class Mp3Meta:
    title: str
    artist: str
    album: str = "抖音音乐"
    comment: str = ""
    track: int = 0


def _sanitize_tag_text(value: str, max_len: int = 200) -> str:
    return "".join(ch for ch in (value or "") if ch.isprintable()).strip()[:max_len]


def write_id3(mp3_path: Path, meta: Mp3Meta) -> None:
    try:
        tags = ID3(mp3_path)
    except ID3NoHeaderError:
        tags = ID3()
    tags.setall("TIT2", [TIT2(encoding=3, text=_sanitize_tag_text(meta.title))])
    tags.setall("TPE1", [TPE1(encoding=3, text=_sanitize_tag_text(meta.artist))])
    tags.setall("TALB", [TALB(encoding=3, text=_sanitize_tag_text(meta.album))])
    tags.setall("TCON", [TCON(encoding=3, text="Pop")])
    if meta.track:
        tags.setall("TRCK", [TRCK(encoding=3, text=str(meta.track))])
    if meta.comment:
        tags.setall(
            "COMM",
            [COMM(encoding=3, lang="chi", desc="", text=_sanitize_tag_text(meta.comment))],
        )
    tags.save(mp3_path, v2_version=ID3_VERSION)


def sanitize_filename(name: str, max_len: int = 80) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", name or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    cleaned = re.sub(r"_+", "_", cleaned)
    if not cleaned:
        cleaned = "未命名"
    return cleaned[:max_len].rstrip(" .")


def convert_to_mp3(
    src: Path,
    dst: Path,
    bitrate: str,
    *,
    ffmpeg: str | None = None,
    meta: Mp3Meta | None = None,
) -> Path:
    """转码为 MP3（保留原有调用方式）。"""
    return convert_to_audio(src, dst, bitrate, fmt="mp3", ffmpeg=ffmpeg, meta=meta)


def _ffmpeg_metadata_args(meta: Mp3Meta) -> list[str]:
    """以 ffmpeg -metadata 方式写入标签（适用于 flac/ogg/m4a/wav/wma 等）。"""
    args: list[str] = []
    for key, value in (
        ("title", meta.title),
        ("artist", meta.artist),
        ("album", meta.album),
        ("comment", meta.comment),
    ):
        text = _sanitize_tag_text(value)
        if text:
            args.extend(["-metadata", f"{key}={text}"])
    if meta.track:
        args.extend(["-metadata", f"track={meta.track}"])
    return args


def convert_to_audio(
    src: Path,
    dst: Path,
    bitrate: str,
    *,
    fmt: str = "mp3",
    ffmpeg: str | None = None,
    meta: Mp3Meta | None = None,
) -> Path:
    """把音视频源转码为指定音频格式。

    - MP3 额外用 mutagen 写入 ID3v2.3 标签（车机兼容性最好）
    - 其余格式由 ffmpeg 通过 -metadata 写入对应容器标签
    """
    spec = resolve_output_format(fmt)
    ffmpeg_bin = find_ffmpeg(ffmpeg)
    dst.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        ffmpeg_bin,
        "-y",
        "-hide_banner",
        "-nostdin",
        "-i",
        str(src),
        "-vn",
        "-sn",
        "-dn",
        "-map_metadata",
        "-1",
        "-codec:a",
        spec.codec,
    ]
    if not spec.lossless:
        cmd.extend(["-b:a", bitrate])
    cmd.extend(["-ar", str(spec.sample_rate or SAMPLE_RATE), "-ac", str(CHANNELS)])

    if spec.key == "mp3":
        cmd.extend(["-write_xing", "1"])
    else:
        if meta:
            cmd.extend(_ffmpeg_metadata_args(meta))
    if spec.container:
        cmd.extend(["-f", spec.container])
    cmd.append(str(dst))

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0 or not dst.exists() or dst.stat().st_size == 0:
        tail = (proc.stderr or "").strip().splitlines()[-8:]
        raise ConverterError("ffmpeg 转码失败:\n" + "\n".join(tail))
    if meta and spec.key == "mp3":
        write_id3(dst, meta)
    return dst
