from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from mutagen.id3 import ID3, COMM, TALB, TCON, TIT2, TPE1, TRCK
from mutagen.id3._util import ID3NoHeaderError

from .config import CHANNELS, ID3_VERSION, SAMPLE_RATE

DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


class ConverterError(RuntimeError):
    pass


def find_ffmpeg(configured: str | None = None) -> str:
    candidates: list[str] = []
    if configured:
        candidates.append(configured)
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
        "libmp3lame",
        "-b:a",
        bitrate,
        "-ar",
        str(SAMPLE_RATE),
        "-ac",
        str(CHANNELS),
        "-write_xing",
        "1",
        str(dst),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0 or not dst.exists() or dst.stat().st_size == 0:
        tail = (proc.stderr or "").strip().splitlines()[-8:]
        raise ConverterError("ffmpeg 转码失败:\n" + "\n".join(tail))
    if meta:
        write_id3(dst, meta)
    return dst
