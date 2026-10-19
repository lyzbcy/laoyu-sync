---
name: laoyu-sync-dev
description: 开发维护捞鱼同步小助手。先读开发导航，按模块渐进阅读，保护用户真实同步配置。
---

# 捞鱼同步小助手开发 Skill

## 项目与技术栈

面向普通用户的文件同步助手。Python 3.12 标准库 + pywebview/qrcode，原生 HTML/JS/CSS；PyInstaller 完整包、Inno Setup，每个平台独立 Syncthing 进程。小鱼支持 Windows/Mac，由用户开关控制。

## 地图

- core/：app入口、gateway鉴权、stmanager快照、wizard配对/共享、pet小鱼、updater和updater_mac更新事务、download_routes测速/回退、feedback反馈协议/脱敏、activity双通道日志。
- ui/：中文界面与原创表情，无构建链。
- docs/：唯一导航 docs/agent.md，开发任何功能前先读对应模块。
- assets/图标；scripts/官方引擎校验/构建；installer/安装器；tests/安全回归。
- verification/、dist/、engine/：本机验收、构建与上游引擎，不入库。

## 约定

先读 docs/roadmap.md 和模块文档。小写英文文件名；稳定产品 ID laoyu-sync，主程序 LaoyuSync.exe。小改沿用main，大改feature/<主题>；提交说明结果与验证。长操作 activity.user 事件流，开发日志轮转到用户数据目录；禁止记录令牌、密钥、文件内容。

版本源 core/version.py 的 __version__/CHANGELOG，当前候选 0.3.13；正式版本以根 version.json 与公开发布页为准，候选不等于已发行。每次交付同步代码、文档、版本并推送既定远端，不改变可见性。安装器/界面/Mac元数据同步。scripts/package.py、package_mac.py 生成真实哈希；正式 version.json 保留旧 Windows 字段并提供 platforms 的分平台资产，包公开并校验后才更新。同版本公开包不可覆盖。

## 能力与验收入口

- 日志已实现轮转、事件流、脱敏复制；更新已实现每日UTC+8尝试/成功、手动重试、正式版本比较、可信地址与哈希、进度、重启与恢复，真实验收见 roadmap/updater。
- Windows 完整引擎/小鱼；python -m unittest discover -s tests -v。包运行、更新、安装分别留证，不能只看构建成功。
- Mac独立CI包；updater_mac.py 提供 .app 替换、原进程退出等待、随机就绪握手、可见窗口/引擎 ACK 和失败恢复，scripts/verify_macos.py 在隔离目录验真实包。Mac公证和用户设备实机验收范围另记，不以单元测试代替。
- 启动器适配先读 E:/共享/tools/软件开发/启动器适配/laoyu-launcher-adapter/SKILL.md；launcher-adapter.json + 严格自查，目录登记、客户端发布和真实安装识别分开记录。
- 独立 Kimi 网页回归与报告在 verification/。
- 求Star/写真实评价达到使用门槛后提示，所有关闭方式记15天不打扰；评价直接进入本机反馈表单。反馈直发企业微信，取消日志不上传，失败保留输入，业务回执才表示送达。机器人凭据不入Git；scripts/prepare_feedback.py 从私有环境/CI Secret生成 .build-cache/feedback-channel.json，正式构建与最终包验收拒绝缺少渠道。分发包中凭据可被提取的既有边界保留，禁止在日志或报告记录其值。
- 更新线路只用于发行 ZIP 测速/回退，预期哈希仍来自 GitHub TLS 正式清单；每条探测最多16KB。旧版备份只有成功健康回执、24小时恢复窗口、路径/哈希/身份与占用核查都通过才回收；不批量删除猜测的旧目录。

## 红线

不得修改真实 E:/共享 同步项目、用户文件、设备身份；测试用 LAOYU_* 隔离。同步配置唯一来源是Syncthing。后端保持标准库+qrcode/pywebview；前端不增加构建链。更新器变更必须记录原因与负例及真实升级/回滚；源码环境不覆盖代码。升级保留用户数据和卸载入口。

Skill自身维护：每日首次接手先运行 `python scripts/skill_sync.py` 静默检查远端，干净工作区自动fast-forward；网络失败用旧版，有本地改动不覆盖。UTC+8尝试/成功状态在.git内记录，手动可加--force。程序运行不下载执行远端Skill。
