# 贡献指南

感谢你对 **乐取 MusicGrab** 的关注。

## 开发环境

- Python 3.10+
- Windows（GUI 与打包主要面向 Windows；核心逻辑可在其他平台按需调试）

```bash
pip install -r requirements.txt
pip install -e ".[dev,gui]"
```

## 测试

提交前请确保测试通过：

```bash
pytest tests -q
```

## 提交建议

- 保持改动聚焦，避免无关格式化。
- 涉及平台解析/下载/转码行为时，请在 PR 中说明影响范围与验证方式。
- 请勿提交 Cookie、账号凭据、内网地址、个人隐私数据或版权受限的媒体文件。
- 涉及第三方站点行为时，请遵守目标平台服务条款与当地法律法规。

## Issue / PR

- Bug 请尽量提供版本号、系统环境、可脱敏的复现步骤与日志。
- 功能建议请说明使用场景与预期行为。
