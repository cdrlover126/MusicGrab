from __future__ import annotations

import pytest

from douyin_mp3.batch import BatchProcessor
from douyin_mp3.config import (
    AUDIO_EXTENSIONS,
    DEFAULT_QUALITY,
    OUTPUT_FORMATS,
    QUALITY_PRESETS,
    VIDEO_EXTENSIONS,
    ConvertOptions,
    describe_quality,
    resolve_bitrate,
    resolve_output_format,
)
from douyin_mp3.converter import _audio_bitrate_args, resolve_extension


def test_output_formats_cover_common_types():
    for key in ("mp3", "wav", "flac", "m4a", "opus", "best"):
        assert key in OUTPUT_FORMATS
        spec = OUTPUT_FORMATS[key]
        assert spec.label
        if not spec.is_copy:
            assert spec.ext and spec.codec


def test_best_format_is_copy_mode():
    spec = OUTPUT_FORMATS["best"]
    assert spec.is_copy
    assert spec.codec == "copy"
    # 复制源音轨时不能声明固定扩展名，需按源编码探测
    assert spec.ext == ""


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


def test_collect_local_files_expands_folders(tmp_path):
    (tmp_path / "sub").mkdir()
    first = tmp_path / "a.mp4"
    second = tmp_path / "sub" / "b.flac"
    first.write_bytes(b"x")
    second.write_bytes(b"x")
    (tmp_path / "note.txt").write_text("ignore", encoding="utf-8")

    found = BatchProcessor.collect_local_files([str(tmp_path)])

    assert found == [first, second]


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


def test_quality_presets_include_v0_and_fallbacks():
    assert DEFAULT_QUALITY == "320"
    assert set(QUALITY_PRESETS) == {"v0", "320", "256", "192", "128", "96"}
    assert resolve_bitrate("v0") == "v0"
    assert resolve_bitrate("V0") == "v0"
    assert resolve_bitrate("192") == "192k"
    assert resolve_bitrate("192k") == "192k"
    assert describe_quality("v0").startswith("V0")
    assert "192" in describe_quality("192")


def test_bitrate_args_follow_format_rules():
    mp3 = OUTPUT_FORMATS["mp3"]
    m4a = OUTPUT_FORMATS["m4a"]
    flac = OUTPUT_FORMATS["flac"]
    best = OUTPUT_FORMATS["best"]

    assert _audio_bitrate_args(mp3, "v0") == ["-q:a", "0"]
    assert _audio_bitrate_args(m4a, "v0") == ["-b:a", "320k"]
    assert _audio_bitrate_args(mp3, "192k") == ["-b:a", "192k"]
    # 无损与不转码都必须忽略码率
    assert _audio_bitrate_args(flac, "320k") == []
    assert _audio_bitrate_args(OUTPUT_FORMATS["wav"], "320k") == []
    assert _audio_bitrate_args(best, "320k") == []


def test_best_extension_mapping(monkeypatch, tmp_path):
    from douyin_mp3 import converter

    monkeypatch.setattr(
        converter, "probe_media_info", lambda _ff, _src: converter.MediaInfo(1.0, "opus")
    )
    assert resolve_extension("best", tmp_path / "x.webm", "ffmpeg") == "opus"
    monkeypatch.setattr(
        converter, "probe_media_info", lambda _ff, _src: converter.MediaInfo(1.0, "aac")
    )
    assert resolve_extension("best", tmp_path / "x.mp4", "ffmpeg") == "m4a"


def test_best_extension_falls_back_to_source_suffix(monkeypatch, tmp_path):
    from douyin_mp3 import converter

    monkeypatch.setattr(
        converter, "probe_media_info", lambda _ff, _src: converter.MediaInfo(1.0, "unknown")
    )
    assert resolve_extension("best", tmp_path / "x.wma", "ffmpeg") == "wma"
    assert resolve_extension("best", None, "ffmpeg") == "mka"


def test_unique_path_uses_selected_extension(tmp_path):
    options = ConvertOptions(output_dir=tmp_path, output_format="flac")
    processor = BatchProcessor(options)
    path = processor._unique_path(tmp_path, 1, "测试")
    assert path.suffix == ".flac"
    assert path.name.startswith("001_")
    path.write_bytes(b"x")
    again = processor._unique_path(tmp_path, 1, "测试")
    assert again.name != path.name
    assert again.stem.endswith("(2)")


def test_base_path_is_stable_for_skip_existing(tmp_path):
    processor = BatchProcessor(ConvertOptions(output_dir=tmp_path))
    first = processor._base_path(tmp_path, 3, "同名")
    assert first == tmp_path / "003_同名.mp3"
    processor._unique_path(tmp_path, 3, "同名").write_bytes(b"x")
    assert processor._base_path(tmp_path, 3, "同名") == first
