# 乐取 MusicGrab — 多平台音轨批量提取转 MP3（抖音 / 快手 / 酷狗 / B站 / 微博 / 网易云 等）

批量粘贴视频或音乐分享链接，自动识别平台并提取其中的音轨，转换为**车机系统可直接播放**的 MP3。

- **车机友好**：MP3、ID3v2.3 标签（歌名/歌手/专辑/来源注释）、44.1kHz 双声道、码率可调
- **批量处理**：一次粘贴多条，自动识别平台并排队转换
- **双引擎**：国内主流平台优先用内置解析器（更省资源、更适配），其余走 yt-dlp 通用引擎（覆盖范围极广）
- **本地化体验**：支持 Cookies、代理、失败重试、防风控间隔、CSV 转换报告

## 1. 支持平台

| 平台 | 引擎 | 说明 |
|---|---|---|
| 抖音 | 内置解析器（推荐） | 支持分享口令整段粘贴、`v.douyin.com`、`www.douyin.com/video/...` 等，可选配乐原曲/视频音轨 |
| 快手 | 内置解析器（推荐） | 支持 `v.kuaishou.com` 短链，自动取最高码率音轨。部分作品需登录或 App 环境 |
| 酷狗 | 内置解析器（推荐） | 支持 `www.kugou.com/mixsong/...`、`www.kugou.com/song/...`、带 `hash=` 的链接等，自动提取可用音频并写入 ID3 标签。**VIP/付费歌曲需登录**（配合 `--cookies-from-browser` 或 `cookies.txt`）；接口可能随酷狗改版而失效 |
| B 站、微博、网易云音乐、优酷、爱奇艺、腾讯视频、芒果 TV、AcFun 等 | yt-dlp 通用引擎 | 大多数可直接提取音轨并打上 ID3 标签 |
| 西瓜视频、小红书、QQ 音乐等 | yt-dlp 通用引擎 | 部分需要登录，建议配合 `--cookies-from-browser` 或 `cookies.txt` 使用 |
| YouTube、TikTok、X(Twitter)、Instagram、Niconico、SoundCloud 等境外站点 | yt-dlp 通用引擎 | **需自备代理**，直连可能超时 |

> 完整清单、支持形态及实测结果见 [docs/SUPPORTED_SITES.md](docs/SUPPORTED_SITES.md)。yt-dlp 当前内置 1751 个 extractor，理论上可覆盖 1500+ 站点。

## 2. 功能一览

- **批量转换**：支持多行粘贴、分享口令混合、批量排队
- **解析引擎切换**：`auto`（默认，智能选择）/ `douyin`（强制内置解析器）/ `generic`（强制 yt-dlp）
- **音频来源（抖音专用）**：`auto` / `video`（视频音轨）/ `music`（纯配乐）
- **音质调节**：预设 128/192/256/320 kbps，也可自定义 32～320 kbps
- **车机兼容**：统一输出 MP3、ID3v2.3 标签，44.1kHz 双声道
- **登录站点支持**：`--cookies`（Netscape 格式）或 `--cookies-from-browser`（edge/chrome/firefox/chromium/brave/opera）
- **代理支持**：`--proxy`，适用于境外站点或网络受限场景
- **内置 ffmpeg**：使用 `imageio-ffmpeg`，开箱即用无需手动配置
- **稳健处理**：防风控间隔、失败自动重试、文件重名自动编号、转换 CSV 报告
- **双界面**：图形界面（PySide6）+ 命令行（`douyin-mp3`）

## 3. 环境准备

### 方式 A：直接使用成品（最省事）
如果已拿到 `dist\MusicGrab.exe`，双击即可运行，无需安装 Python 环境。

### 方式 B：从源码运行
需要 Python 3.10+。

```powershell
# 克隆仓库（示例）
git clone <your-repo-url>
cd douyin-mp3

# 安装依赖
pip install -r requirements.txt

# （可选）安装 GUI 依赖
pip install -e ".[gui]"

# （可选）开发依赖（测试、打包）
pip install -e ".[dev]"
```

## 4. 使用方法

### 4.1 图形界面（推荐）

```powershell
# 源码方式
python -m douyin_mp3

# 安装包方式（pip install -e . 后）
douyin-mp3
# 或
乐取 MusicGrab
```

界面要点：
- **链接输入**：将分享口令或链接粘贴到文本框，每行一条即可
- **输出设置（可折叠）**：音质、音频来源、解析引擎、条数间隔、代理、Cookies、浏览器 Cookies、输出目录
- **开始/停止**：支持随时停止当前批量任务
- **详情日志**：默认隐藏，点击“显示详情日志”可查看解析、下载、转码的完整过程，便于排查问题
- **进度显示**：仅显示百分比进度，转换完成后会弹窗提示成功/失败数量

### 4.2 命令行

```powershell
# 抖音 / 快手 / 酷狗（内置解析器，默认 auto 即可）
douyin-mp3 convert "https://v.douyin.com/xxxxxxx/" "https://v.kuaishou.com/xxxxxx" "https://www.kugou.com/mixsong/xxxxxx.html" -q 192 -o "D:\Music\车机音乐"

# B站、微博、网易云等（自动走 yt-dlp）
douyin-mp3 convert "https://www.bilibili.com/video/BV1xx411c7mD" "https://music.163.com/song?id=xxxx" -q 320

# 需登录站点：从已登录的浏览器读取 cookies（使用前请完全退出该浏览器）
douyin-mp3 convert "https://m.ixigua.com/video/xxxx" --cookies-from-browser edge

# 使用本地 cookies.txt（Netscape 格式）
douyin-mp3 convert "https://y.qq.com/n/ryqq/songDetail/xxx" --cookies ".\cookies.txt"

# 多平台混合 + 代理（境外站点）
douyin-mp3 convert "分享口令 https://v.douyin.com/aaa/" "https://youtu.be/xxxxxxxx" `
  --quality 320 --source auto --engine auto --proxy http://127.0.0.1:7890 --skip-existing
```

#### 命令行参数说明

| 参数 | 默认值 | 说明 |
|---|---|---|
| `urls`（位置参数） | 必填 | 一条或多条分享链接/口令，支持混合粘贴 |
| `-q, --quality` | `192` | `128`/`192`/`256`/`320` 或 `32-320` 任意整数 |
| `-s, --source` | `auto` | `auto`/`video`/`music`（仅抖音内置解析器生效） |
| `--engine` | `auto` | `auto`（智能选择）/`douyin`（强制内置：抖音、快手）/`generic`（强制 yt-dlp） |
| `-o, --output` | `~/Music/MusicGrab` | 输出目录（会自动创建） |
| `--proxy` | 空 | 代理地址，如 `http://127.0.0.1:7890`、`socks5://127.0.0.1:7891` |
| `--cookies` | 空 | `cookies.txt` 路径（需为 Netscape 格式） |
| `--cookies-from-browser` | 空 | 从浏览器提取 cookies：`edge`、`chrome`、`firefox`、`chromium`、`brave`、`opera`、`vivaldi` 等 |
| `--ffmpeg` | 空（自动） | 指定自定义 `ffmpeg.exe` 路径，默认优先使用 `imageio-ffmpeg` 内置 |
| `--skip-existing` | 否 | 跳过已存在的同名文件（可避免重复转换） |
| `--delay` | `2` | 每条链接之间的间隔秒数（有助于降低风控概率） |

## 5. 故障排查（常见问题）

| 问题 | 原因 | 解决方案 |
|---|---|---|
| **解析失败 / “页面无数据”** | 抖音/快手风控、作品已删除、或需要登录环境 | 稍后重试、换网络、使用 `--engine auto` 让程序自动切换；部分快手作品仅 App 可见暂时无法解析 |
| **“需 cookies” / 登录相关报错** | 西瓜、小红书、QQ 音乐等站点需登录态 | 完全退出浏览器后用 `--cookies-from-browser <浏览器名>`，或导出 Netscape 格式 `cookies.txt` 并用 `--cookies` 指定 |
| **酷狗提示“VIP/付费歌曲”** | 该曲目为酷狗 VIP/付费内容，未登录不返回播放地址 | 登录酷狗后导出 cookies，用 `--cookies-from-browser edge` 或 `--cookies cookies.txt` 重试 |
| **境外站点超时（YouTube/TikTok/X/Instagram）** | 本机直连境外网络不可用 | 配置代理（如 Clash/V2rayN）后设置 `--proxy http://127.0.0.1:7890`（以实际端口为准） |
| **读取浏览器 cookies 失败** | 浏览器未完全退出、加密存储、权限受限 | 关闭所有浏览器进程（检查任务管理器），以当前用户权限运行程序，再重试 |
| **转码报错 / 找不到 ffmpeg** | 环境异常或自定义路径错误 | 默认已用 `imageio-ffmpeg`，如仍报错可用 `--ffmpeg "C:\path\to\ffmpeg.exe"` 手动指定 |
| **音质偏低 / 只能提取试听片段** | 平台限制或仅提供低码率音轨 | 部分平台确实只提供预览音频，换其他链接或站点可能会有更好选择 |
| **文件名乱码/特殊字符** | 原标题含特殊符号 | 程序已做文件名清洗，会自动替换非法字符并用编号避免重名 |

> 提示：工具会在转换完成后生成 `conversion_report_*.csv`，记录每条链接的状态、文件名、时长、码率等，便于复盘和排查。

## 6. 生成应用（打包成 EXE）

适合在无 Python 环境的 Windows 机器上分发。

```powershell
# 安装打包依赖
pip install pyinstaller

# 执行打包脚本
powershell -ExecutionPolicy Bypass -File packaging\build_exe.ps1
```

产物：
- `dist\MusicGrab.exe` — 单文件、无控制台、内置图标和版本信息（约 100MB）
- `dist\MusicGrab_*.msix`（如需）— Microsoft Store/侧载用的 MSIX 安装包

打包细节见 `packaging/` 目录（`build_exe.ps1`、`version_info.txt`、`msix/AppxManifest.xml`）。

## 7. 测试、文档与发布

```powershell
# 运行单元测试
pytest tests -q
```

相关文档：
- [docs/SUPPORTED_SITES.md](docs/SUPPORTED_SITES.md) — 平台支持清单与实测明细
- [docs/STORE_CHECKLIST.md](docs/STORE_CHECKLIST.md) — Microsoft Store 发布检查清单
- [docs/PRIVACY_POLICY.md](docs/PRIVACY_POLICY.md) — 隐私政策模板

## 8. 免责声明与许可

- **仅供个人学习研究**：本工具仅供个人学习、研究和非商业用途使用。请勿将其用于商业运营、批量分发或任何侵犯他人版权的场景。
- **责任自负**：用户需自行遵守所访问平台的服务条款及所在地法律法规。因使用本工具产生的任何法律责任由使用者自行承担。
- **公开链接为准**：本工具仅处理用户**主动粘贴的公开分享链接**，不内置破解、绕过 DRM 或获取付费内容的功能。
- **隐私**：程序完全本地运行，不会上传链接、Cookies 或下载文件到第三方服务器。Cookies 仅用于访问用户已登录的站点请求。

**License:** [MIT](LICENSE)
