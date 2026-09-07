# 打包发布（规划，v0.3）

目标：Windows + macOS 双端安装包，内置 syncthing 引擎，用户装完即用。

## 方案要点

1. **壳的选型**：v0.1 用 pywebview 验证产品；v0.3 迁 Tauri（Rust sidecar 跑 syncthing，安装包小）或继续 Python + PyInstaller。前端 ui/ 无构建链，两种壳都能原样托管，这是 SKILL.md 铁律 3 的原因。
2. **捆绑 syncthing**：Win 用 winget 包里的 syncthing.exe（当前 v2.1.3）；Mac 用官方 tar.gz 的 syncthing 二进制。升级策略：随包更新 + 引擎独立检测。
3. **Windows 安装器**：Inno Setup；开机自启为可选项（默认勾选）；安装后注册 `syncthing://` 协议（v0.2 配对链接用）。
4. **macOS**：app bundle + LaunchAgent 自启；Gatekeeper 公证。
5. **数据目录**：引擎配置继续用各平台默认（Win %LOCALAPPDATA%\Syncthing，Mac ~/Library/Application Support/Syncthing），保证与官方版互切。
6. **更新**：docs 已定机制的落地——manifest 指向 GitHub Releases，下载进度条 + 国内代理提醒 + 失败跳转发布页。
