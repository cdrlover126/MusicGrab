# DouyinMP3 — 视频音乐批量转 MP3（抖音/快手/B站/微博/网易云…）

批量粘贴视频分享口令/链接，自动识别平台并提取其中的音乐歌曲，转换为**车机系统可直接播放**的 MP3（ID3v2.3 标签、44.1kHz 立体声、码率可调），并生成转换报告。

## 支持平台
| 平台 | 引擎 | 说明 |
|---|---|---|
| 抖音 | 内置专用解析器 | 支持分享口令整段粘贴，可选配乐原曲/视频音轨 |
| 快手 | 内置专用解析器 | 支持 v.kuaishou.com 短链，自动取最高码率音轨 |
| B站 / 微博 / 网易云 / 优酷 / 爱奇艺 / 腾讯视频 / 西瓜 等 | yt-dlp 通用引擎 | 自动取最佳音轨 |
| YouTube / TikTok 等境外站点 | yt-dlp 通用引擎 | 需自备代理 |

完整清单与实测结果见 [docs/SUPPORTED_SITES.md](docs/SUPPORTED_SITES.md)（yt-dlp 内置 1751 个 extractor）。

## 功能
- 批量处理：一次粘贴多条分享文本或链接，平台自动识别
- 解析引擎可选：自动 / 内置解析器（抖音、快手）/ yt-dlp 通用引擎
- 音频来源可选：自动 / 视频音轨 / 纯配乐（抖音专用；其他站点取最佳音轨）
- 质量可调：128 / 192 / 256 / 320 kbps，或 32–320 任意整数
- 车机兼容：MP3 + ID3v2.3 标签（歌名/歌手/专辑/来源注释），44.1kHz、双声道
- 登录站点支持：`--cookies` / `--cookies-from-browser`（西瓜、小红书、QQ音乐等）
- 内置 ffmpeg（imageio-ffmpeg），无需单独安装
- 图形界面 + 命令行双模式
- CSV 转换报告、防风控间隔、失败自动重试、重名自动编号

## 安装
```powershell
pip install -r requirements.txt
```

## 使用

### 图形界面（推荐）
```powershell
python -m douyin_mp3
# 或安装后
douyin-mp3
```

### 命令行
```powershell
# 抖音 / 快手（内置解析器）
douyin-mp3 convert "https://v.douyin.com/xxxxxxx/" "https://v.kuaishou.com/xxxxxx" -q 192 -o D:\Music\车机音乐

# B站 / 微博 / 网易云 / YouTube 等（自动走 yt-dlp 通用引擎）
douyin-mp3 convert "https://www.bilibili.com/video/BV1xx411c7mD" "https://youtu.be/xxxxxxxx" -q 320

# 需登录站点（西瓜/小红书/QQ音乐）：读取浏览器 cookies
douyin-mp3 convert "https://m.ixigua.com/video/xxxx" --cookies-from-browser edge

# 多平台混合批量 + 完整参数
douyin-mp3 convert "分享口令1 https://v.douyin.com/aaa/" "https://www.bilibili.com/video/BV1yy" `
  --quality 320 --source auto --engine auto --proxy http://127.0.0.1:7890 --skip-existing
```

| 参数 | 说明 |
|---|---|
| `-q/--quality` | 128/192/256/320 或任意 32-320 整数 |
| `-s/--source` | auto / video / music（抖音专用） |
| `--engine` | auto / douyin（强制内置） / generic（强制 yt-dlp） |
| `-o/--output` | 输出目录，默认 `~/Music/DouyinMP3` |
| `--proxy` | 代理地址（境外站点需要） |
| `--cookies` | cookies 文件（Netscape 格式） |
| `--cookies-from-browser` | 从浏览器读取 cookies：edge / chrome / firefox 等 |
| `--ffmpeg` | 指定本机 ffmpeg 路径（默认自动使用内置） |

## 生成应用
```powershell
pip install pyinstaller
powershell -ExecutionPolicy Bypass -File packaging\build_exe.ps1
```
生成 `dist\DouyinMP3.exe`（单文件、无控制台、带图标与版本信息）及可选 MSIX 安装包。

## 发布到应用商店
已具备发布条件，见 [docs/STORE_CHECKLIST.md](docs/STORE_CHECKLIST.md)；隐私政策模板见 [docs/PRIVACY_POLICY.md](docs/PRIVACY_POLICY.md)。

## 测试
```powershell
pytest tests -q
```

## 免责声明
本工具仅供个人学习研究使用，请勿用于商业用途或侵犯他人版权；用户对所下载内容的使用承担全部责任。

## License
MIT
