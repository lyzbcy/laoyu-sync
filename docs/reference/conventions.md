# 软件开发规范落实

现状：0.3.0 Windows包已验收。负责人：捞鱼工作室。最后更新：2026-09-30。

来源 E:/共享/tools/软件开发，全量读取于2026-09-30。

|要求|落实与证据|
|---|---|
|开发Skill与渐进文档|SKILL.md、agent/roadmap/tech、模块文档；版本core/version.py|
|Win与Mac架构|core/ui分层，独立CI和架构匹配引擎；Mac实机/公证未完成|
|双通道日志|轮转文件、事件流、进度、脱敏诊断复制|
|自适应更新|UTC+8尝试/成功分开、正式版比较、可信哈希、进度/重启/回滚，见updater与roadmap|
|静默Skill维护|scripts/skill_sync.py每日UTC+8静默远端检查；干净fast-forward，失败/有改动不覆盖；运行不执行远端Skill|
|原创表情|ui/assets/stickers原作；原生app图标与小鱼|
|关于推广|软件子页、作者/主页/二维码；直达反馈未配置时仅复制|
|不打扰求Star|5次启动且使用7天，关闭15天免打扰|
|网页回归|独立Kimi代理、隔离真实引擎与verification报告|
|静态强制刷新|本机页面no-store，无公网HTML缓存；版本和日志一级入口|
|启动器适配|launcher-adapter + 源码白名单/目录、严格报告，客户端发布与安装另验|
