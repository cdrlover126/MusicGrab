from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from mutagen.id3 import ID3, COMM, TALB, TCON, TIT2, TPE1, TRCK
from mutagen.id3._util import ID3NoHeaderError

from .config import (
    CHANNELS,
    CODEC_EXTENSIONS,
    ID3_VERSION,
    SAMPLE_RATE,
    OutputFormat,
    resolve_output_format,
)

DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
AUDIO_CODEC_RE = re.compile(r"Stream #\d+:\d+.*?:\s*Audio:\s*([A-Za-z0-9_]+)")


class ConverterError(RuntimeError):
    pass


@dataclass
class MediaInfo:
    """ffmpeg 探测到的媒体信息。"""

    duration: float = 0.0
    audio_codec: str = ""


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


def probe_media_info(ffmpeg: str, src: Path) -> MediaInfo:
    """解析媒体信息：总时长 + 音频编码名。

    BEST（不转码）模式需要靠音频编码决定输出容器，否则复制音轨会因
    「容器装不下该编码」而失败。
    """
    try:
        proc = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", str(src)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return MediaInfo()
    text = proc.stderr or ""
    duration = 0.0
    match = DURATION_RE.search(text)
    if match:
        h, mi, s = int(match.group(1)), int(match.group(2)), float(match.group(3))
        duration = h * 3600 + mi * 60 + s
    codec = ""
    match = AUDIO_CODEC_RE.search(text)
    if match:
        codec = match.group(1).lower()
    return MediaInfo(duration=duration, audio_codec=codec)


def probe_duration_seconds(ffmpeg: str, src: Path) -> float:
    return probe_media_info(ffmpeg, src).duration


def describe_audio_quality(path: Path) -> str:
    """读取输出文件的实际音质参数，返回任务结果里展示的简短描述。

    用 mutagen 直接读文件头，不依赖 ffmpeg、不联网。返回形如
    ``320 kbps · 44.1 kHz · 立体声`` 的字符串；无损格式会带上位深
    （``16 bit``）。读不出（文件损坏 / 极端编码）时返回空串。
    """
    path = Path(path)
    try:
        from mutagen import File as MutagenFile

        audio = MutagenFile(str(path))
    except Exception:  # noqa: BLE001  载入失败就当作拿不到音质
        return ""
    info = getattr(audio, "info", None)
    if info is None:
        return ""

    parts: list[str] = []

    # 码率（FLAC/WAV 等无损头里没有，用 体积×8/时长 反推平均值）
    bitrate = int(getattr(info, "bitrate", 0) or 0)
    if bitrate <= 0:
        try:
            duration = float(getattr(info, "length", 0) or 0)
            if duration >= 0.5:
                bitrate = int(path.stat().st_size * 8 / duration)
        except OSError:
            bitrate = 0
    if bitrate > 0:
        parts.append(f"{round(bitrate / 1000)} kbps")

    # 采样率
    sample_rate = int(getattr(info, "sample_rate", 0) or 0)
    if sample_rate > 0:
        khz = sample_rate / 1000
        parts.append(f"{khz:g} kHz")

    # 位深（无损格式才有意义）
    bits = int(getattr(info, "bits_per_sample", 0) or 0)
    if bits > 0:
        parts.append(f"{bits:g} bit")

    # 声道数
    channels = int(getattr(info, "channels", 0) or 0)
    if channels == 1:
        parts.append("单声道")
    elif channels == 2:
        parts.append("立体声")
    elif channels > 2:
        parts.append(f"{channels} 声道")

    return " · ".join(parts)


def resolve_extension(
    fmt: str,
    source: Path | None = None,
    ffmpeg: str | None = None,
) -> str:
    """决定输出文件的扩展名。

    普通格式直接取定义里的扩展名；**BEST（不转码）**则按源音频编码反查容器，
    保证「复制音轨」这一步不会因为容器不兼容而失败。
    """
    spec = resolve_output_format(fmt)
    if not spec.is_copy:
        return spec.ext
    if source is not None:
        try:
            info = probe_media_info(ffmpeg or find_ffmpeg(), source)
        except ConverterError:
            info = MediaInfo()
        ext = CODEC_EXTENSIONS.get(info.audio_codec, "")
        if ext:
            return ext
    if source is not None and source.suffix:
        return source.suffix.lstrip(".").lower()
    return "mka"  # Matroska 音频：几乎什么编码都装得下


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


def _audio_bitrate_args(spec: OutputFormat, bitrate: str) -> list[str]:
    """按格式与音质生成码率参数。

    * 无损格式与 BEST（不转码）→ **忽略码率**
    * ``v0`` → MP3 用 LAME 可变码率 ``-q:a 0``；其他有损格式回落到 320k
    """
    if spec.is_copy or spec.lossless:
        return []
    if bitrate == "v0":
        if spec.key == "mp3":
            return ["-q:a", "0"]
        return ["-b:a", "320k"]
    return ["-b:a", bitrate]


def convert_to_audio(
    src: Path,
    dst: Path,
    bitrate: str,
    *,
    fmt: str = "mp3",
    ffmpeg: str | None = None,
    meta: Mp3Meta | None = None,
    cover: Path | None = None,
) -> Path:
    """把音视频源转码为指定音频格式。

    - MP3 额外用 mutagen 写入 ID3v2.3 标签（车机兼容性最好）
    - 其余格式由 ffmpeg 通过 -metadata 写入对应容器标签
    - BEST 模式直接复制源音轨（零损失），扩展名由 ``resolve_extension`` 决定
    - 传入 ``cover`` 可把封面图嵌入音频文件
    """
    spec = resolve_output_format(fmt)
    ffmpeg_bin = find_ffmpeg(ffmpeg)
    dst.parent.mkdir(parents=True, exist_ok=True)

    # WAV 没有标准的封面承载位置；OGG/Opus 容器不支持 attached_pic，
    # 强行写入会让 ffmpeg 直接报 "Unsupported codec id in stream 1"
    use_cover = (
        cover
        if (cover and cover.exists() and spec.key not in ("wav", "opus"))
        else None
    )

    cmd = [ffmpeg_bin, "-y", "-hide_banner", "-nostdin", "-i", str(src)]
    if use_cover is not None:
        cmd.extend(["-i", str(use_cover)])
        # 有封面时不能再用 -vn（会把封面也一起去掉），改为显式映射
        cmd.extend(["-map", "0:a", "-map", "1:v", "-sn", "-dn"])
    else:
        cmd.extend(["-vn", "-sn", "-dn"])
    cmd.extend(["-map_metadata", "-1", "-codec:a", spec.codec])

    if not spec.is_copy:
        # 不转码时不能改采样率/声道，否则 ffmpeg 会被迫重编码
        cmd.extend(["-ar", str(spec.sample_rate or SAMPLE_RATE), "-ac", str(CHANNELS)])

    cmd.extend(_audio_bitrate_args(spec, bitrate))

    if spec.key == "mp3":
        cmd.extend(["-write_xing", "1"])
    else:
        if meta:
            cmd.extend(_ffmpeg_metadata_args(meta))
    if use_cover is not None:
        cmd.extend(["-codec:v", "mjpeg", "-disposition:v:0", "attached_pic"])
    if spec.container and not spec.is_copy:
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
