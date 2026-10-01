# 捞鱼同步小助手 Laoyu Sync

中文引导电脑文件同步：配对、项目共享、实时状态，还有会摆尾吐泡的桌面小鱼。文件由 Syncthing 在设备之间传输，不上传作者服务器，无遥测。

## 使用

Windows 完整包内置 Python 与 Syncthing，无需另外安装。下载入口 https://github.com/lyzbcy/laoyu-sync/releases 。正式发布与验收状态以 docs/roadmap.md 为准，源码推送不代表包已公开。

已有 Tailscale 会自动识别，无需重新组网；已有 Syncthing 的项目、配对和身份直接沿用。网络在线与文件同步状态分别显示。

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

Inno Setup 6 的 ISCC 编译 installer/windows.iss；Actions 构建 Windows 和 Mac 独立包。Mac 包未签名公证，CI 构建不代替实机验收。Windows 当前无代码签名。

隔离参数 LAOYU_SYNC_DATA、LAOYU_SYNC_PORT、LAOYU_ST_HOME、LAOYU_ST_GUI；--headless 启动 API。禁止在真实用户同步目录做回归。

## 许可

外壳 MIT，Syncthing MPL-2.0 独立进程，原始许可证与源码地址随包提供。见 THIRD_PARTY_NOTICES.md。原创表情素材归原作者所有。

开发版0.3.3规范审计见docs/requirements-audit.md：反馈客户端已补一级入口、分类、日志选择/预览和接收确认，但接收服务尚未开通，不能直达作者；正式发布版仍为0.3.2。

0.3.3按用户指定方式直发企业微信：日志为群内ZIP附件，不经过捞鱼服务器。预配置机器人链接仅注入发行包，不放公开源码；自行从源码构建未注入配置时不会发送。
