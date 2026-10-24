# Microsoft Store 发布检查清单

## 应用质量
- [x] 应用具备正式名称、图标（多尺寸 PNG + ICO）、版本号（1.0.0.0）
- [x] EXE 内嵌版本资源信息（version_info.txt）
- [x] 无控制台窗口（--windowed）
- [x] 不要求管理员权限，仅写入用户选择目录与用户临时目录
- [x] 提供隐私政策（docs/PRIVACY_POLICY.md）
- [x] 提供开源许可（MIT LICENSE）

## 打包与标识
- [x] Identity: `com.cdrlover.musicgrab`
- [x] Publisher: `CN=cdrlover`（提交 Partner Center 后需与账户中的证书主体一致）
- [x] MSIX 清单：packaging/msix/AppxManifest.xml
- [x] 能力声明仅 `internetClient` + `runFullTrust`（桌面桥信任调用）

## 提交 Partner Center 前需要人工完成的事项
1. 注册 Microsoft Partner Center 账户（个人开发者 $19 一次性注册费）
2. 创建应用包名称（Name 一旦创建不可更改，建议先确认 `com.cdrlover.musicgrab`）
3. 使用账户下发的 Publisher 证书替换 `CN=cdrlover`，重新打包 MSIX
4. 准备商店素材：
   - 应用截图 1280×768 至少 4 张（含主界面、转换过程、结果示例）
   - 应用海报图 300×300（Square310x310Logo 亦可复用）
   - 简介（中文 + 英文）、关键词：抖音、MP3、音乐提取、车机
5. 完成内容合规自查：
   - 应用仅处理用户主动粘贴的公开分享链接
   - 不内置绕过 DRM/付费内容的逻辑，不抓取用户隐私数据
   - 在简介与隐私政策中明确用途为“个人学习研究”
6. 在 Partner Center 选择分发范围（商店 / 私有组织分发 / 直接发行 URL）

## 本地构建命令
```powershell
pip install -r requirements.txt pyinstaller
powershell -ExecutionPolicy Bypass -File packaging\build_exe.ps1
```
产物：
- `dist\MusicGrab.exe` — 单文件应用，可直接分发
- `dist\MusicGrab_1.0.0.0_x64.msix` — 商店/侧载安装包（需 SDK）
