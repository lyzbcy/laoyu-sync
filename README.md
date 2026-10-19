# 捞鱼同步小助手 Laoyu Sync

中文引导电脑文件同步：配对、项目共享、实时状态，还有会摆尾吐泡的桌面小鱼。文件由 Syncthing 在设备之间传输，不上传作者服务器，无遥测。

## 使用

Windows 完整包内置 Python 与 Syncthing，无需另外安装。下载入口 https://github.com/lyzbcy/laoyu-sync/releases 。正式发布与验收状态以 docs/roadmap.md 为准，源码推送不代表包已公开。

已有 Tailscale 会自动识别，无需重新组网；已有 Syncthing 的项目、配对和身份直接沿用。网络在线与文件同步状态分别显示。

想节省代理流量，可在「设置 / 关于 → 同步网络」选择「优先直连」，保存后重开助手。TUN／全局 VPN 用户还需按页面说明添加进程直连规则，并检查代理连接记录。

1. 两台电脑安装并打开助手；便携 ZIP 完整解压后打开 LaoyuSync.exe。
2. 在「设备与配对」交换电脑号码，互相添加并接受。
3. 在「同步项目」选择文件夹，共享给对方；对方选择保存位置接收。

先用测试文件夹体验。修改和删除会同步，新项目默认保留远端覆盖/删除的旧文件 30 天（.stversions）；同步不能代替备份。本机已同步不代表离线设备已收到。

项目可调整共享、暂停/继续、停止同步并保留文件。关于页开关桌面小鱼、复制诊断日志、检查更新。退出助手会停止自己启动的引擎，已有独立引擎不被停止。

配置和日志存于用户数据目录 LaoyuSync；引擎已有配置兼容。日志可能含路径和设备名，分享前检查。反馈服务未配置时仅复制内容，不伪造送达。

## 开发

先读 SKILL.md → docs/agent.md。Python 3.12：

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python scripts/fetch_engine.py
python scripts/make_icon.py
python scripts/prepare_resources.py
python core/app.py --console
python -m PyInstaller --noconfirm LaoyuSync.spec
python scripts/package.py
```

Inno Setup 6 的 ISCC 编译 installer/windows.iss；Actions 构建 Windows 和 Mac 独立包。Mac 包为临时签名、未公证，CI 原生应用验收不代替用户设备实机验收。Windows 当前无代码签名。

隔离参数 LAOYU_SYNC_DATA、LAOYU_SYNC_PORT、LAOYU_ST_HOME、LAOYU_ST_GUI；--headless 启动 API。禁止在真实用户同步目录做回归。

## 许可

外壳 MIT，Syncthing MPL-2.0 独立进程，原始许可证与源码地址随包提供。见 THIRD_PARTY_NOTICES.md。原创表情素材归原作者所有。

当前正式版为 0.3.13，正式发行状态以 version.json 和 docs/roadmap.md 为准。规范修复与验收范围见 docs/standards-remediation.md；旧审计保留为修复前快照。

反馈直接发至作者企业微信，日志为 ZIP 附件，不经过作者服务器。官方包在构建时注入渠道；自行构建需先配置私有 LAOYU_FEEDBACK_WEBHOOK，运行 scripts/prepare_feedback.py。未配置渠道时正式构建会失败，凭据不提交源码仓库。

Windows 与 Mac 的完整应用支持一键更新，按平台和架构选择 ZIP，比较 GitHub 与固定镜像线路并验证完整 SHA-256；新版窗口和引擎确认就绪后保留旧版 24 小时，再按安全凭据自动清理。已有旧 Mac 版需手动安装一次支持该更新器的新版本。修改和删除同步项目的行为不因更新而改变。
