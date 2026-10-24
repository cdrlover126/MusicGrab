from __future__ import annotations

import pytest

from douyin_mp3.batch import BatchProcessor
from douyin_mp3.config import (
    AUDIO_EXTENSIONS,
    OUTPUT_FORMATS,
    VIDEO_EXTENSIONS,
    ConvertOptions,
    resolve_output_format,
)


def test_output_formats_cover_common_types():
    for key in ("mp3", "wav", "flac", "m4a", "aac", "ogg", "opus", "wma"):
        assert key in OUTPUT_FORMATS
        spec = OUTPUT_FORMATS[key]
        assert spec.ext and spec.codec and spec.label


def test_resolve_output_format_normalizes():
    assert resolve_output_format("MP3").ext == "mp3"
    assert resolve_output_format(".flac").ext == "flac"
    assert resolve_output_format("opus").sample_rate == 48000
    with pytest.raises(ValueError):
        resolve_output_format("aiff")


def test_lossless_formats_have_no_bitrate():
    assert OUTPUT_FORMATS["flac"].lossless
    assert OUTPUT_FORMATS["wav"].lossless
    assert not OUTPUT_FORMATS["mp3"].lossless


def test_collect_local_files_detects_media(tmp_path):
    video = tmp_path / "a.mp4"
    video.write_bytes(b"x")
    audio = tmp_path / "b.flac"
    audio.write_bytes(b"x")
    other = tmp_path / "c.txt"
    other.write_bytes(b"x")
    lines = [
        str(video),
        str(audio),
        str(other),
        "https://v.douyin.com/abc/",
        str(tmp_path / "missing.mp4"),
    ]
    found = BatchProcessor.collect_local_files(lines)
    assert found == [video, audio]


def test_collect_local_files_ignores_urls(tmp_path):
    assert BatchProcessor.collect_local_files(["https://v.douyin.com/x/"]) == []


def test_video_extensions_include_common_containers():
    for ext in (".mp4", ".mkv", ".mov", ".avi", ".flv", ".wmv", ".webm", ".ts", ".m4v"):
        assert ext in VIDEO_EXTENSIONS
    for ext in (".mp3", ".wav", ".flac", ".m4a", ".ogg", ".opus", ".wma"):
        assert ext in AUDIO_EXTENSIONS


def test_default_options_use_highest_quality_and_mp3():
    options = ConvertOptions()
    assert options.quality == "320"
    assert options.output_format == "mp3"
    assert options.bitrate == "320k"


def test_unique_path_uses_selected_extension(tmp_path):
    options = ConvertOptions(output_dir=tmp_path, output_format="flac")
    processor = BatchProcessor(options)
    path = processor._unique_path(tmp_path, "", 1, "测试")
    assert path.suffix == ".flac"
