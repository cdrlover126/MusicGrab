from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import __version__

VERSION = __version__

SAMPLE_RATE = 44100
CHANNELS = 2
ID3_VERSION = 3

DEFAULT_OUTPUT_DIR = Path.home() / "Music" / "MusicGrab"
TEMP_DIR_NAME = ".douyin_mp3_tmp"

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
        QualityPreset("128", "128k", "标准 128kbps", "体积最小，车机兼容性最好"),
        QualityPreset("192", "192k", "高清 192kbps", "音质与体积平衡，推荐"),
        QualityPreset("256", "256k", "超清 256kbps", "高保真，体积较大"),
        QualityPreset("320", "320k", "极清 320kbps", "最高质量 MP3，体积最大"),
    )
}

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


OUTPUT_FORMATS: dict[str, OutputFormat] = {
    f.key: f
    for f in (
        OutputFormat("mp3", "mp3", "MP3（通用，车机首选）", "libmp3lame", note="有损，兼容性最好"),
        OutputFormat("wav", "wav", "WAV（无损，体积大）", "pcm_s16le", lossless=True, note="未压缩 PCM"),
        OutputFormat("flac", "flac", "FLAC（无损，体积小）", "flac", lossless=True, note="无损压缩"),
        OutputFormat("m4a", "m4a", "M4A / AAC（Apple 生态）", "aac", container="ipod", note="有损，体积小"),
        OutputFormat("aac", "aac", "AAC（ADTS 裸流）", "aac", note="有损"),
        OutputFormat("ogg", "ogg", "OGG Vorbis（开源格式）", "libvorbis", note="有损"),
        OutputFormat(
            "opus", "opus", "Opus（高压缩比）", "libopus", note="有损，语音友好", sample_rate=48000
        ),
        OutputFormat("wma", "wma", "WMA（老车机兼容）", "wmav2", note="有损，Windows Media"),
    )
}

OUTPUT_FORMAT_CHOICES = tuple(OUTPUT_FORMATS.keys())

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
    quality = str(quality).strip().lower().rstrip("k").strip()
    if quality in QUALITY_PRESETS:
        return QUALITY_PRESETS[quality].bitrate
    value = int(quality)
    if not 32 <= value <= 320:
        raise ValueError(f"比特率需在 32-320 kbps 之间，收到: {quality}")
    return f"{value}k"


def temp_dir() -> Path:
    d = Path.home() / TEMP_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def resolve_output_format(fmt: str) -> OutputFormat:
    key = (fmt or "mp3").strip().lower().lstrip(".")
    if key not in OUTPUT_FORMATS:
        raise ValueError(
            f"不支持的输出格式: {fmt}（可选: {', '.join(OUTPUT_FORMAT_CHOICES)}）"
        )
    return OUTPUT_FORMATS[key]


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

    @property
    def bitrate(self) -> str:
        return resolve_bitrate(self.quality)

    @property
    def use_builtin_parser(self) -> bool:
        """内置解析器（抖音/快手/酷狗）优先，其余走 yt-dlp。"""
        return self.engine in ("auto", "douyin")
