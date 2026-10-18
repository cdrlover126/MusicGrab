from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import APP_NAME, __version__

VERSION = __version__

SAMPLE_RATE = 44100
CHANNELS = 2
ID3_VERSION = 3

DEFAULT_OUTPUT_DIR = Path.home() / "Music" / "DouyinMP3"
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
    "auto": "自动（优先配乐原曲）",
    "video": "视频音轨（含人声解说）",
    "music": "配乐原曲（纯音乐）",
}


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


@dataclass
class ConvertOptions:
    output_dir: Path = field(default_factory=lambda: DEFAULT_OUTPUT_DIR)
    quality: str = "192"
    audio_source: str = "auto"
    filename_template: str = "{index:03d}_{title}"
    skip_existing: bool = False
    delay: float = DELAY_BETWEEN_TASKS
    max_retries: int = MAX_RETRIES
    keep_temp: bool = False
    proxy: str | None = None
    ffmpeg_path: str | None = None

    @property
    def bitrate(self) -> str:
        return resolve_bitrate(self.quality)
