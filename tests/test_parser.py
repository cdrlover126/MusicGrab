from __future__ import annotations

from douyin_mp3.batch import BatchProcessor
from douyin_mp3.config import ConvertOptions
from douyin_mp3.converter import sanitize_filename
from douyin_mp3.parser import (
    classify_platform,
    extract_aweme_id,
    extract_urls,
)


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


def test_extract_urls_keeps_multi_platform():
    text = (
        "抖音 https://v.douyin.com/aaa111/ "
        "B站 https://www.bilibili.com/video/BV1xx411c7mD "
        "油管 https://youtu.be/xxxxxxxx"
    )
    urls = extract_urls(text)
    assert len(urls) == 3
    assert any("bilibili.com" in u for u in urls)
    assert any("youtu.be" in u for u in urls)


def test_classify_platform():
    assert classify_platform("https://v.douyin.com/abc/") == "douyin"
    assert classify_platform("https://www.iesdouyin.com/share/video/123/") == "douyin"
    assert classify_platform("https://www.douyin.com/video/7341234567890123") == "douyin"
    assert classify_platform("https://www.bilibili.com/video/BV1xx411c7mD") == "bilibili"
    assert classify_platform("https://b23.tv/abcdef") == "bilibili"
    assert classify_platform("https://www.youtube.com/watch?v=abc") == "youtube"
    assert classify_platform("https://youtu.be/abc") == "youtube"
    assert classify_platform("https://v.kuaishou.com/abc") == "kuaishou"
    assert classify_platform("https://www.kuaishou.com/short-video/3xabc") == "kuaishou"
    assert classify_platform("https://kphm5nf3.m.chenzhongtech.com/fw/photo/3xabc") == "kuaishou"
    assert classify_platform("https://www.kugou.com/mixsong/g5jy4e47.html") == "kugou"
    assert classify_platform("https://www.kugou.com/song/#g5jy4e47") == "kugou"
    assert classify_platform("https://www.kugou.com/song/#hash=FF3432CE123121722CFF5CCA609AD434") == "kugou"
    assert classify_platform("https://www.weibo.com/tv/show/1034:123") == "generic"
    assert classify_platform("https://example.com/video") == "generic"


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
