from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__

VERSION = __version__

SAMPLE_RATE = 44100
CHANNELS = 2
ID3_VERSION = 3

DEFAULT_OUTPUT_DIR = Path.home() / "Music" / "MusicGrab"
TEMP_DIR_NAME = ".douyin_mp3_tmp"
#: 覆盖层目录名（外置 yt-dlp / ffmpeg / CA 证书包都放这里）
OVERLAY_DIR_NAME = "MusicGrab"

MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1"
)
PC_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

REQUEST_TIMEOUT = 30
DOWNLOAD_TIMEOUT = 120
MAX_RETRIES = 3
DELAY_BETWEEN_TASKS = 1.5
PROXY_TIMEOUT = 3.0


@dataclass(frozen=True)
class QualityPreset:
    key: str
    bitrate: str
    label: str
    note: str


QUALITY_PRESETS: dict[str, QualityPreset] = {
    p.key: p
    for p in (
        QualityPreset(
            "v0",
            "v0",
            "V0 最佳 VBR（推荐）",
            "MP3 可变码率，质量/体积最佳；其他有损格式按 320k 处理",
        ),
        QualityPreset("320", "320k", "320 kbps CBR（极清）", "固定码率，体积最大"),
        QualityPreset("256", "256k", "256 kbps CBR（超清）", "固定码率，体积较大"),
        QualityPreset("192", "192k", "192 kbps CBR（高清）", "音质与体积平衡"),
        QualityPreset("128", "128k", "128 kbps CBR（标准）", "体积最小，车机兼容性最好"),
        QualityPreset("96", "96k", "96 kbps CBR（省空间）", "语音/播客足够，车机兼容性最好"),
    )
}

#: 默认音质
DEFAULT_QUALITY = "320"

AUDIO_SOURCE_CHOICES = ("auto", "video", "music")
AUDIO_SOURCE_LABELS = {
    "auto": "自动（抖音优先配乐原曲，其他站点取最佳音轨）",
    "video": "视频音轨（含人声解说，仅抖音生效）",
    "music": "配乐原曲（纯音乐，仅抖音生效）",
}

ENGINE_CHOICES = ("auto", "douyin", "generic")
ENGINE_LABELS = {
    "auto": "自动（抖音/快手/酷狗用内置解析器，其余走 yt-dlp）",
    "douyin": "内置解析器（抖音/快手/酷狗，无第三方依赖）",
    "generic": "yt-dlp 通用引擎（可配合 cookies 处理需登录站点）",
}

COOKIE_BROWSER_CHOICES = ("edge", "chrome", "firefox", "chromium", "brave", "opera")


@dataclass(frozen=True)
class OutputFormat:
    """输出音频格式定义。"""

    key: str
    ext: str
    label: str
    codec: str
    container: str = ""
    lossless: bool = False
    note: str = ""
    sample_rate: int = 0  # 0 表示使用全局采样率

    @property
    def is_copy(self) -> bool:
        """是否为「不转码，直接复制源音轨」格式。"""
        return self.codec == "copy"


OUTPUT_FORMATS: dict[str, OutputFormat] = {
    f.key: f
    for f in (
        OutputFormat("mp3", "mp3", "MP3（通用，车机首选）", "libmp3lame", note="有损，兼容性最好"),
        OutputFormat("m4a", "m4a", "M4A / AAC（Apple 生态）", "aac", container="ipod", note="有损，体积小"),
        OutputFormat("opus", "opus", "Opus（高压缩比）", "libopus", note="有损，语音友好", sample_rate=48000),
        OutputFormat("flac", "flac", "FLAC（无损，体积小）", "flac", lossless=True, note="无损压缩"),
        OutputFormat("wav", "wav", "WAV（无损，体积大）", "pcm_s16le", lossless=True, note="未压缩 PCM"),
        OutputFormat(
            "best",
            "",
            "BEST（源格式，不转码）",
            "copy",
            note="零损失零转码，速度最快；输出扩展名随源音频格式而定",
        ),
    )
}

OUTPUT_FORMAT_CHOICES = tuple(OUTPUT_FORMATS.keys())

#: 音频编码 → 容器扩展名（用于 BEST「不转码」模式）
#: 复制音轨时容器必须能装下该编码，否则 ffmpeg 会报错
CODEC_EXTENSIONS: dict[str, str] = {
    "mp3": "mp3",
    "mp3float": "mp3",
    "aac": "m4a",
    "alac": "m4a",
    "opus": "opus",
    "vorbis": "ogg",
    "flac": "flac",
    "pcm_s16le": "wav",
    "pcm_s24le": "wav",
    "pcm_s32le": "wav",
    "pcm_f32le": "wav",
    "pcm_u8": "wav",
    "wavpack": "wv",
    "ape": "ape",
    "wmav2": "wma",
    "wmapro": "wma",
}

# 常见视频容器（用于识别本地视频文件）
VIDEO_EXTENSIONS = frozenset(
    {
        ".mp4", ".m4v", ".mov", ".mkv", ".avi", ".flv", ".f4v", ".wmv", ".webm", ".ts",
        ".m2ts", ".mts", ".3gp", ".3g2", ".rmvb", ".rm", ".mpg", ".mpeg", ".mpe", ".vob",
        ".asf", ".ogv", ".ogm", ".divx", ".xvid", ".f4v", ".dv", ".mxf", ".roq", ".nsv",
        ".flv", ".mkv", ".wtv", ".trp", ".tp", ".amv", ".m2v", ".mpe",
    }
)

# 常见音频文件（本地输入时同样可提取）
AUDIO_EXTENSIONS = frozenset(
    {".mp3", ".wav", ".flac", ".aac", ".m4a", ".ogg", ".oga", ".opus", ".wma", ".ape", ".mka", ".aiff", ".aif"}
)


def resolve_bitrate(quality: str) -> str:
    """把音质选项解析成 ffmpeg 码率参数。

    * ``v0``  → ``"v0"``（MP3 可变码率，由转换器翻译成 ``-q:a 0``）
    * 数字   → ``"320k"`` 这种形式
    """
    quality = str(quality).strip().lower().rstrip("k").strip()
    if quality in QUALITY_PRESETS:
        return QUALITY_PRESETS[quality].bitrate
    value = int(quality)
    if not 32 <= value <= 320:
        raise ValueError(f"比特率需在 32-320 kbps 之间，收到: {quality}")
    return f"{value}k"


def describe_quality(quality: str) -> str:
    """把音质选项描述成可读文本（用于日志与报告）。"""
    key = str(quality or "").strip().lower()
    preset = QUALITY_PRESETS.get(key)
    if preset:
        return preset.label
    try:
        return f"{resolve_bitrate(key)} CBR"
    except (ValueError, TypeError):
        return key or "未知"


def temp_dir() -> Path:
    d = Path.home() / TEMP_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def overlay_root() -> Path:
    """覆盖层根目录（外置组件与 CA 证书包都放这里）。"""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / OVERLAY_DIR_NAME


def resolve_output_format(fmt: str) -> OutputFormat:
    key = (fmt or "mp3").strip().lower().lstrip(".")
    if key not in OUTPUT_FORMATS:
        raise ValueError(
            f"不支持的输出格式: {fmt}（可选: {', '.join(OUTPUT_FORMAT_CHOICES)}）"
        )
    return OUTPUT_FORMATS[key]


#: 转换报告（CSV）的保存方式
#: - overwrite：固定文件名「转换报告.csv」，每次覆盖，输出目录里最多留一份
#: - history：带时间戳的新文件，保留全部历史
#: - none：不生成报告
REPORT_MODES = ("overwrite", "history", "none")
REPORT_MODE_LABELS = {
    "overwrite": "覆盖同名文件（默认，只保留一份）",
    "history": "每次新建（带时间戳，保留历史）",
    "none": "不生成报告",
}
#: 覆盖模式下的报告文件名
REPORT_FILE_NAME = "转换报告.csv"
#: 历史报告文件名（带时间戳）
REPORT_HISTORY_PREFIX = "转换报告_"
REPORT_HISTORY_SUFFIX = ".csv"


@dataclass
class ConvertOptions:
    output_dir: Path = field(default_factory=lambda: DEFAULT_OUTPUT_DIR)
    quality: str = "320"
    output_format: str = "mp3"
    audio_source: str = "auto"
    engine: str = "auto"
    filename_template: str = "{index:03d}_{title}"
    skip_existing: bool = False
    delay: float = DELAY_BETWEEN_TASKS
    max_retries: int = MAX_RETRIES
    keep_temp: bool = False
    proxy: str | None = None
    trust_env: bool = False
    route_mode: str = "auto"
    ffmpeg_path: str | None = None
    cookies_file: str | None = None
    cookies_from_browser: str | None = None
    report_mode: str = "overwrite"

    @property
    def bitrate(self) -> str:
        return resolve_bitrate(self.quality)

    @property
    def use_builtin_parser(self) -> bool:
        """内置解析器（抖音/快手/酷狗）优先，其余走 yt-dlp。"""
        return self.engine in ("auto", "douyin")
