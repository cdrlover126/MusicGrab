from __future__ import annotations

import subprocess

import pytest
from mutagen.id3 import ID3

from douyin_mp3.converter import (
    Mp3Meta,
    convert_to_audio,
    convert_to_mp3,
    describe_audio_quality,
    find_ffmpeg,
    resolve_extension,
    write_id3,
)


@pytest.fixture(scope="module")
def ffmpeg_bin() -> str:
    return find_ffmpeg()


@pytest.fixture()
def source_wav(tmp_path, ffmpeg_bin):
    wav = tmp_path / "tone.wav"
    subprocess.run(
        [
            ffmpeg_bin,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            str(wav),
        ],
        check=True,
        capture_output=True,
    )
    return wav


def test_find_ffmpeg(ffmpeg_bin):
    assert ffmpeg_bin


@pytest.mark.parametrize("bitrate", ["128k", "192k", "320k"])
def test_convert_to_mp3(tmp_path, source_wav, ffmpeg_bin, bitrate):
    out = tmp_path / f"out_{bitrate}.mp3"
    convert_to_mp3(
        source_wav,
        out,
        bitrate,
        ffmpeg=ffmpeg_bin,
        meta=Mp3Meta(title="测试歌曲", artist="测试歌手", comment="https://v.douyin.com/x/"),
    )
    assert out.exists()
    assert out.stat().st_size > 1000
    with open(out, "rb") as fh:
        assert fh.read(3) == b"ID3"
    tags = ID3(out)
    assert tags["TIT2"].text[0] == "测试歌曲"
    assert tags["TPE1"].text[0] == "测试歌手"


def test_write_id3_v23(tmp_path, source_wav, ffmpeg_bin):
    out = tmp_path / "tag.mp3"
    convert_to_mp3(source_wav, out, "192k", ffmpeg=ffmpeg_bin)
    write_id3(out, Mp3Meta(title="A", artist="B"))
    raw = out.read_bytes()[:10]
    assert raw[3] == 3


def test_v0_uses_lame_vbr(tmp_path, source_wav, ffmpeg_bin):
    out = tmp_path / "vbr.mp3"
    convert_to_audio(
        source_wav, out, "v0", fmt="mp3", ffmpeg=ffmpeg_bin, meta=Mp3Meta(title="V", artist="A")
    )
    assert out.exists() and out.stat().st_size > 1000


def test_best_mode_copies_source_without_transcoding(tmp_path, source_wav, ffmpeg_bin):
    mp3 = tmp_path / "lossy.mp3"
    convert_to_audio(source_wav, mp3, "128k", fmt="mp3", ffmpeg=ffmpeg_bin)
    assert resolve_extension("best", mp3, ffmpeg_bin) == "mp3"

    copied = tmp_path / "copied.mp3"
    convert_to_audio(
        mp3,
        copied,
        "320k",
        fmt="best",
        ffmpeg=ffmpeg_bin,
        meta=Mp3Meta(title="原样", artist="歌手"),
    )
    assert copied.exists() and copied.stat().st_size > 0
    # 复制音轨：输出体积应和源基本一致（转码到 320k 会明显变大）
    assert abs(copied.stat().st_size - mp3.stat().st_size) < 2048


def test_cover_is_embedded_in_mp3(tmp_path, source_wav, ffmpeg_bin):
    cover = tmp_path / "cover.jpg"
    subprocess.run(
        [
            ffmpeg_bin,
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=300x300:d=1",
            "-frames:v",
            "1",
            str(cover),
        ],
        check=True,
        capture_output=True,
    )
    out = tmp_path / "covered.mp3"
    convert_to_audio(
        source_wav,
        out,
        "192k",
        fmt="mp3",
        ffmpeg=ffmpeg_bin,
        meta=Mp3Meta(title="封面", artist="歌手"),
        cover=cover,
    )
    tags = ID3(out)
    assert tags.getall("APIC"), "MP3 应包含 APIC 封面帧"


def test_describe_audio_quality_mp3(tmp_path, source_wav, ffmpeg_bin):
    out = tmp_path / "q.mp3"
    convert_to_mp3(source_wav, out, "192k", ffmpeg=ffmpeg_bin)
    text = describe_audio_quality(out)
    assert "192" in text and " kbps" in text, text
    assert "kHz" in text, text
    assert ("单声道" in text) or ("立体声" in text), text


def test_describe_audio_quality_flac_shows_bits(tmp_path, source_wav, ffmpeg_bin):
    out = tmp_path / "q.flac"
    convert_to_audio(source_wav, out, "320k", fmt="flac", ffmpeg=ffmpeg_bin)
    text = describe_audio_quality(out)
    assert "bit" in text, text
    assert "kHz" in text, text


def test_describe_audio_quality_corrupt_file_returns_empty(tmp_path):
    broken = tmp_path / "broken.mp3"
    broken.write_bytes(b"not an audio file at all")
    assert describe_audio_quality(broken) == ""
    assert describe_audio_quality(tmp_path / "missing.mp3") == ""
