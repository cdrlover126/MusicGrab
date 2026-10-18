from __future__ import annotations

from douyin_mp3.batch import BatchProcessor
from douyin_mp3.config import ConvertOptions
from douyin_mp3.converter import sanitize_filename
from douyin_mp3.parser import extract_aweme_id, extract_urls


def test_extract_urls_from_share_text():
    text = "7.99 复制打开抖音 https://v.douyin.com/abc123XY/ 看看这个热门歌曲，超好听！"
    urls = extract_urls(text)
    assert urls == ["https://v.douyin.com/abc123XY/"]


def test_extract_multiple_urls_dedup():
    text = (
        "https://v.douyin.com/aaa111/\n"
        "看这个 https://www.iesdouyin.com/share/video/7300000000000000001/?x=1\n"
        "https://v.douyin.com/aaa111/"
    )
    urls = extract_urls(text)
    assert len(urls) == 2
    assert "v.douyin.com/aaa111" in urls[0]
    assert "7300000000000000001" in urls[1]


def test_extract_urls_ignores_other_domains():
    assert extract_urls("https://example.com/foo") == []
    assert extract_urls("看看这个作品 https://www.bilibili.com/video/BV1xx") == []


def test_extract_aweme_id():
    assert extract_aweme_id("https://www.iesdouyin.com/share/video/7341234567890123456/") == "7341234567890123456"
    assert extract_aweme_id("https://www.douyin.com/note/7341234567890123456") == "7341234567890123456"
    assert extract_aweme_id("https://v.douyin.com/iAbCdEf/") is None


def test_collect_links_via_processor():
    lines = ["口令A https://v.douyin.com/xyz789/ 结尾", "https://v.douyin.com/xyz789/", "无链接"]
    links = BatchProcessor.collect_links(lines)
    assert links == ["https://v.douyin.com/xyz789/"]


def test_sanitize_filename():
    assert sanitize_filename('a/b:c*d?e"f<g>h|i') == "a_b_c_d_e_f_g_h_i"
    assert sanitize_filename("  稻香 - 周杰伦 ") == "稻香 - 周杰伦"
    assert sanitize_filename("") == "未命名"
    assert len(sanitize_filename("x" * 200)) == 80


def test_convert_options_bitrate():
    assert ConvertOptions(quality="320").bitrate == "320k"
    assert ConvertOptions(quality="192").bitrate == "192k"
    assert ConvertOptions(quality="200").bitrate == "200k"
