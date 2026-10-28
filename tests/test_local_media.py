from __future__ import annotations

from pathlib import Path

import pytest

from douyin_mp3.local_media import collect_media_paths, is_media_file


def _touch(path: Path, data: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_single_media_file(tmp_path: Path) -> None:
    video = _touch(tmp_path / "a.mp4")
    files, truncated = collect_media_paths([video])
    assert files == [video]
    assert truncated is False


def test_unsupported_file_is_ignored(tmp_path: Path) -> None:
    _touch(tmp_path / "note.txt")
    _touch(tmp_path / "cover.jpg")
    files, truncated = collect_media_paths([tmp_path])
    assert files == []
    assert truncated is False


def test_folder_is_scanned_recursively_and_sorted(tmp_path: Path) -> None:
    _touch(tmp_path / "b.mp3")
    _touch(tmp_path / "a.flac")
    _touch(tmp_path / "sub" / "c.mkv")
    _touch(tmp_path / "sub" / "deep" / "d.wav")
    _touch(tmp_path / "sub" / "ignore.txt")

    files, truncated = collect_media_paths([tmp_path])

    assert [p.name for p in files] == ["a.flac", "b.mp3", "c.mkv", "d.wav"]
    assert truncated is False


def test_hidden_and_system_dirs_are_skipped(tmp_path: Path) -> None:
    _touch(tmp_path / "ok.mp4")
    _touch(tmp_path / ".hidden" / "secret.mp4")
    _touch(tmp_path / "__MACOSX" / "junk.mp4")
    _touch(tmp_path / "node_modules" / "pkg" / "x.mp4")

    files, _ = collect_media_paths([tmp_path])

    assert [p.name for p in files] == ["ok.mp4"]


def test_deduplicates_file_and_folder(tmp_path: Path) -> None:
    video = _touch(tmp_path / "a.mp4")

    files, _ = collect_media_paths([video, tmp_path, video])

    assert files == [video]


def test_limit_marks_truncated(tmp_path: Path) -> None:
    for i in range(5):
        _touch(tmp_path / f"{i}.mp3")

    files, truncated = collect_media_paths([tmp_path], limit=3)

    assert len(files) == 3
    assert truncated is True


def test_exact_limit_is_not_truncated(tmp_path: Path) -> None:
    for i in range(3):
        _touch(tmp_path / f"{i}.mp3")

    files, truncated = collect_media_paths([tmp_path], limit=3)

    assert len(files) == 3
    assert truncated is False


def test_missing_path_is_ignored(tmp_path: Path) -> None:
    files, truncated = collect_media_paths([tmp_path / "nope.mp4"])
    assert files == []
    assert truncated is False


def test_limit_must_be_positive(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        collect_media_paths([tmp_path], limit=0)


def test_is_media_file_case_insensitive(tmp_path: Path) -> None:
    upper = _touch(tmp_path / "VIDEO.MP4")
    assert is_media_file(upper) is True
    assert is_media_file(tmp_path) is False
