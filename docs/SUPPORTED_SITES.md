# 支持站点清单与实测结果

- 版本：v1.3.0
- 实测环境：Windows + 本机直连（**无代理**），实测日期见仓库提交记录
- 说明：**内置解析器**指本项目自研解析（无需 yt-dlp）；**通用引擎**指 yt-dlp

## 一、内置专用解析器（推荐，无需第三方依赖）

| 平台 | 支持的链接形态 | 备注 |
|---|---|---|
| 抖音 | `v.douyin.com/xxx` 分享口令、`www.douyin.com/video/{id}`、`/note/{id}`、`iesdouyin.com/share/video/{id}` | 可选配乐原曲 / 视频音轨 |
| 快手 | `v.kuaishou.com/xxx` 短链、`www.kuaishou.com/short-video/{id}`、`*.chenzhongtech.com/fw/photo/{id}` | 取最高码率视频音轨；部分作品需 App/登录 |
| 酷狗 | `www.kugou.com/mixsong/{id}.html`、`www.kugou.com/song/#{id}`（新版分享页）、带 `hash=` 的链接 | 抓取页面 `dataFromSmarty` 元数据 + 移动端播放接口取直链；`/song/#{id}` 会自动归一化为 `/mixsong/{id}.html` 解析；**VIP/付费歌曲需登录**（`--cookies`/`--cookies-from-browser`） |

## 二、yt-dlp 通用引擎（1751 个 extractor，覆盖 1500+ 站点）

### 国内平台

| 平台 | yt-dlp 支持 | 本机实测 | 备注 |
|---|---|---|---|
| B站（含 b23.tv 短链、番剧、音频区、直播、合集） | 支持 | **通过 3/3** | 开箱即用 |
| 微博视频 / 微博用户 | 支持 | **通过 2/2** | 开箱即用 |
| 网易云音乐（歌曲/专辑/歌单/电台/MV） | 支持 | **通过 1/2** | 部分歌曲地域限制 |
| 抖音（yt-dlp 路径） | 支持 Douyin | 需 cookies | 与内置解析器二选一 |
| 西瓜视频 | 支持 Ixigua | 需 cookies | 报错会提示加 cookies |
| 小红书 | 支持 XiaoHongShu | 需 cookies | — |
| QQ音乐（歌曲/专辑/歌单/榜单/MV） | 支持 | 需 cookies | 非登录用户不可用 |
| 优酷 / 爱奇艺 / 腾讯视频 / 芒果TV / 搜狐 / 央视网 | 支持 | 未逐条实测 | 视频站，可提取音轨 |
| 酷我音乐 / 斗鱼 / 虎牙 / AcFun / 喜马拉雅 / 蜻蜓FM / 今日头条 / 百度视频 | 支持 | 未逐条实测 | — |
| 快手 | **不支持** | — | yt-dlp 无 extractor，请用内置解析器 |
| 酷狗 | **不支持** | — | yt-dlp 无 extractor，请用内置解析器 |
| 好看视频 / 咪咕视频 | **不支持** | — | yt-dlp 无 extractor |

### 境外平台

| 平台 | yt-dlp 支持 | 本机实测 | 备注 |
|---|---|---|---|
| YouTube / YouTube Music | 支持 | 超时 | 需代理（本机无代理） |
| TikTok | 支持 | 超时 | 需代理 |
| X/Twitter、Instagram、Facebook | 支持 | 超时 | 需代理 |
| Niconico、SoundCloud、Vimeo、Dailymotion | 支持 | 超时 | 需代理 |

> 境外站点全部可解析，只是本机网络无法直连；设置代理即可：
> `--proxy http://127.0.0.1:7890`（GUI 内有代理输入框）

## 三、实测明细

| 链接 | 引擎 | 结果 |
|---|---|---|
| `https://www.bilibili.com/video/BV1rcn56hEoT` | yt-dlp | 通过（BiliBili，1914s） |
| `https://b23.tv/BV1GJ411x7h7` | yt-dlp | 通过 → MP3 4.87MB / 212s / 192kbps |
| `https://www.bilibili.com/video/BV16GJv6SEeE` | yt-dlp | 通过（2209s） |
| `https://www.weibo.com/tv/show/1034:5334385348509751` | yt-dlp | 通过 → MP3 2.29MB / 100s |
| `https://music.163.com/song?id=347230` | yt-dlp | 通过《海阔天空》 326s |
| `https://music.163.com/song?id=186016` | yt-dlp | 失败：地域限制 |
| `https://www.douyin.com/video/7300755515695484170` | 内置 | 通过 → MP3 1.67MB / 73s（首次常遇风控，自动重试后成功） |
| `https://www.douyin.com/video/7178820623546813734` | 内置 | 失败：页面无数据（风控/作品限制） |
| `https://v.kuaishou.com/8OS21F` | 内置 | 通过 → 视频音轨 118s，作者「老徐动物世界」 |
| `https://v.kuaishou.com/nmqf0KDZ` | 内置 | 失败：页面无数据（作品需 App/登录） |
| `https://m.ixigua.com/video/7310526900030407205` | yt-dlp | 失败：需 cookies（已提示解法） |
| `https://y.qq.com/n/ryqq/songDetail/0039MnYb0qxYhV` | yt-dlp | 失败：仅注册用户（需 cookies） |
| `https://www.kugou.com/mixsong/g56rmzfd.html` | 内置 | 通过 → MP3 6.8MB《…》（免费曲，192kbps） |
| `https://www.kugou.com/song/#g5jy4e47` | 内置 | 通过 → MP3 5.4MB《前路有光》张杰（免费曲，192kbps） |
| `https://www.kugou.com/mixsong/67ixk467.html` | 内置 | 失败：VIP/付费歌曲（`pay_type=3`，未登录不返回直链） |
| `https://www.kugou.com/mixsong/5r7dnu63.html` | 内置 | 失败：VIP/付费歌曲（同上） |
| YouTube / TikTok / X / Instagram 示例 | yt-dlp | 失败：本机无代理超时 |

混合批量端到端（抖音 + 快手 + 微博 + B站）均成功产出 192kbps MP3，ID3v2.3 标签完整。

## 四、需要登录的站点怎么用

```powershell
# 方式一：直接用浏览器已登录的 cookies（需完全退出浏览器）
douyin-mp3 convert "https://m.ixigua.com/video/xxx" --cookies-from-browser edge

# 方式二：导出 cookies.txt（Netscape 格式）后指定文件
douyin-mp3 convert "https://m.ixigua.com/video/xxx" --cookies cookies.txt

# 强制走 yt-dlp（处理抖音需 cookies 的场景）
douyin-mp3 convert "https://www.douyin.com/video/xxx" --engine generic --cookies-from-browser edge
```
