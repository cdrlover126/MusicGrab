from __future__ import annotations

import subprocess

import pytest
from mutagen.id3 import ID3

from douyin_mp3.converter import Mp3Meta, convert_to_mp3, find_ffmpeg, write_id3


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
