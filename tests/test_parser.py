from __future__ import annotations

from douyin_mp3.batch import BatchProcessor
from douyin_mp3.config import ConvertOptions
from douyin_mp3.converter import sanitize_filename
from douyin_mp3.parser import (
    classify_platform,
    extract_aweme_id,
    extract_urls,
    normalize_bilibili,
    resolve_bili_short_link,
)


def test_normalize_bilibili_locale_prefix():
    """语言前缀会让 yt-dlp 匹配不上 BiliBili 提取器，必须去掉。"""
    assert (
        normalize_bilibili(
            "https://www.bilibili.com/zh-Hans/video/"
            "BV1XynB6EEiM/?trackid=web_pegasus_0.router-web"
        )
        == "https://www.bilibili.com/video/BV1XynB6EEiM"
    )


def test_normalize_bilibili_keeps_page_param():
    assert (
        normalize_bilibili(
            "https://www.bilibili.com/video/BV1GJ411x7h7?p=3&spm_id_from=333.88"
        )
        == "https://www.bilibili.com/video/BV1GJ411x7h7?p=3"
    )


def test_normalize_bilibili_mobile_host():
    assert (
        normalize_bilibili("https://m.bilibili.com/video/BV1GJ411x7h7")
        == "https://www.bilibili.com/video/BV1GJ411x7h7"
    )


def test_normalize_bilibili_av_id():
    assert (
        normalize_bilibili("https://www.bilibili.com/video/av75450513?bvid=xx")
        == "https://www.bilibili.com/video/av75450513"
    )


def test_normalize_bilibili_bvid_case_preserved():
    """BVID 区分大小写，必须原样保留。"""
    vid = "BV1XynB6EEiM"
    result = normalize_bilibili(f"https://www.bilibili.com/video/{vid}")
    assert result.endswith(vid)


def test_normalize_bilibili_non_video_page_keeps_path():
    out = normalize_bilibili(
        "https://www.bilibili.com/bangumi/play/ep21495/?bsource=x&trackid=t"
    )
    assert out == "https://www.bilibili.com/bangumi/play/ep21495/?bsource=x"


def test_normalize_bilibili_passthrough_others():
    url = "https://example.com/video/BV1234567890"
    assert normalize_bilibili(url) == url
    assert normalize_bilibili("") == ""


def test_normalize_bilibili_short_link(monkeypatch):
    """b23.tv 短链：解析成功用最终地址，失败保留原链接。"""
    import douyin_mp3.parser as p

    monkeypatch.setattr(
        p,
        "resolve_bili_short_link",
        lambda url: "https://www.bilibili.com/video/BV1GJ411x7h7",
    )
    assert (
        p.normalize_bilibili("https://b23.tv/abcxyz")
        == "https://www.bilibili.com/video/BV1GJ411x7h7"
    )

    monkeypatch.setattr(p, "resolve_bili_short_link", lambda url: None)
    assert p.normalize_bilibili("https://b23.tv/abcxyz") == "https://b23.tv/abcxyz"


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


def test_extract_aweme_id_from_query_param():
    assert extract_aweme_id("https://www.douyin.com/discover?modal_id=7341234567890123456") == "7341234567890123456"
    assert extract_aweme_id("https://www.douyin.com/?aweme_id=7341234567890123456") == "7341234567890123456"


def test_extract_urls_from_share_text_variants():
    # 分享面板「复制链接」「复制口令」得到的文本都能提取到链接
    for text in (
        "https://v.douyin.com/iAbCdEf/",
        "https://v.douyin.com/iAbCdEf/ 复制打开抖音，看看【某人的作品】",
        "7.92 复制打开抖音，看看【某人的作品】 https://v.douyin.com/iAbCdEf/  ",
    ):
        assert extract_urls(text) == ["https://v.douyin.com/iAbCdEf/"]


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
