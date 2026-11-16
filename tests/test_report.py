"""转换报告保存方式测试（覆盖 / 历史 / 不生成）。"""

from __future__ import annotations

from pathlib import Path

from musicgrab.batch import BatchProcessor
from musicgrab.config import REPORT_FILE_NAME, ConvertOptions

ROWS = [
    {
        "序号": 1,
        "状态": "ok",
        "标题": "示例",
        "歌手": "未知歌手",
        "时长秒": 12.3,
        "大小字节": 1024,
        "输出": "001_示例.mp3",
        "来源": "https://v.douyin.com/abc/",
        "说明": "",
    }
]


def _processor(tmp_path: Path, mode: str) -> BatchProcessor:
    options = ConvertOptions(output_dir=tmp_path, report_mode=mode)
    processor = BatchProcessor(options)
    processor.on_log = lambda msg: None
    return processor


def test_default_mode_is_overwrite(tmp_path: Path) -> None:
    assert ConvertOptions().report_mode == "overwrite"


def test_overwrite_uses_fixed_file_name(tmp_path: Path) -> None:
    processor = _processor(tmp_path, "overwrite")
    processor._write_report(ROWS)

    assert (tmp_path / REPORT_FILE_NAME).exists()
    assert not list(tmp_path.glob("转换报告_*.csv"))


def test_overwrite_removes_old_history_reports(tmp_path: Path) -> None:
    old = tmp_path / "转换报告_20260101_120000.csv"
    old.write_text("旧报告", encoding="utf-8")

    processor = _processor(tmp_path, "overwrite")
    processor._write_report(ROWS)

    assert not old.exists()
    assert (tmp_path / REPORT_FILE_NAME).exists()
    assert len(list(tmp_path.glob("*.csv"))) == 1


def test_overwrite_replaces_previous_content(tmp_path: Path) -> None:
    processor = _processor(tmp_path, "overwrite")
    processor._write_report(ROWS)
    processor._write_report(ROWS)

    assert len(list(tmp_path.glob("*.csv"))) == 1


def test_history_mode_creates_timestamped_file(tmp_path: Path) -> None:
    processor = _processor(tmp_path, "history")
    processor._write_report(ROWS)

    files = list(tmp_path.glob("转换报告_*.csv"))
    assert len(files) == 1
    assert not (tmp_path / REPORT_FILE_NAME).exists()


def test_none_mode_writes_nothing(tmp_path: Path) -> None:
    processor = _processor(tmp_path, "none")
    processor._write_report(ROWS)

    assert list(tmp_path.glob("*.csv")) == []


def test_empty_rows_writes_nothing(tmp_path: Path) -> None:
    processor = _processor(tmp_path, "overwrite")
    processor._write_report([])

    assert list(tmp_path.glob("*.csv")) == []


def test_report_is_utf8_bom_excel_friendly(tmp_path: Path) -> None:
    processor = _processor(tmp_path, "overwrite")
    processor._write_report(ROWS)

    raw = (tmp_path / REPORT_FILE_NAME).read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    assert "示例".encode("utf-8") in raw
