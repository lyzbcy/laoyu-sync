---
name: laoyu-sync-dev
description: 开发维护捞鱼同步小助手。先读开发导航，按模块渐进阅读，保护用户真实同步配置。
---

# 捞鱼同步小助手开发 Skill

## 项目与技术栈

面向普通用户的文件同步助手。Python 3.12 标准库 + pywebview/qrcode，原生 HTML/JS/CSS；PyInstaller 完整包、Inno Setup，每个平台独立 Syncthing 进程。小鱼是 Windows 插件。

## 地图

- core/：app入口、gateway鉴权、stmanager快照、wizard配对/共享、pet小鱼、updater校验升级、feedback反馈协议/脱敏、activity双通道日志。
- ui/：中文界面与原创表情，无构建链。
- docs/：唯一导航 docs/agent.md，开发任何功能前先读对应模块。
- assets/图标；scripts/官方引擎校验/构建；installer/安装器；tests/安全回归。
- verification/、dist/、engine/：本机验收、构建与上游引擎，不入库。
- server/：独立反馈中转服务与部署配置，不随客户端打包；群机器人凭据仅保存在服务器/仓库外。

## 约定

先读 docs/roadmap.md 和模块文档。小写英文文件名；稳定产品 ID laoyu-sync，主程序 LaoyuSync.exe。小改沿用main，大改feature/<主题>；提交说明结果与验证。长操作 activity.user 事件流，开发日志轮转到用户数据目录；禁止记录令牌、密钥、文件内容。

版本源 core/version.py 的 __version__/CHANGELOG，当前 0.3.3。每次交付同步代码、文档、版本并推送既定远端，不改变可见性。安装器/界面/Mac元数据同步。scripts/package.py 生成真实哈希；根 version.json 是正式更新元数据，包公开并校验后才更新，不以源码版本冒充已发布版本。同版本公开包不可覆盖。

## 能力与验收入口

- 日志已实现轮转、事件流、脱敏复制；更新已实现每日UTC+8尝试/成功、手动重试、正式版本比较、可信地址与哈希、进度、重启与恢复，真实验收见 roadmap/updater。
- Windows 完整引擎/小鱼；python -m unittest discover -s tests -v。包运行、更新、安装分别留证，不能只看构建成功。
- Mac独立CI包；签名公证和实机验收待完成，一键目录替换不开放。
- 启动器适配先读 E:/共享/tools/软件开发/启动器适配/laoyu-launcher-adapter/SKILL.md；launcher-adapter.json + 严格自查，目录登记、客户端发布和真实安装识别分开记录。
- 独立 Kimi 网页回归与报告在 verification/。
- 求Star达到使用天数/次数门槛后提示，关闭15天不打扰。正式0.3.2反馈未完成；0.3.3开发版增加一级入口、分类和日志预览，接收服务尚缺配置。无接收渠道禁用提交，复制是单独动作，不宣称送达。

## 红线

不得修改真实 E:/共享 同步项目、用户文件、设备身份；测试用 LAOYU_* 隔离。同步配置唯一来源是Syncthing。后端保持标准库+qrcode/pywebview；前端不增加构建链。更新器变更必须记录原因与负例及真实升级/回滚；源码环境不覆盖代码。升级保留用户数据和卸载入口。

Skill自身维护：每日首次接手先运行 `python scripts/skill_sync.py` 静默检查远端，干净工作区自动fast-forward；网络失败用旧版，有本地改动不覆盖。UTC+8尝试/成功状态在.git内记录，手动可加--force。程序运行不下载执行远端Skill。
