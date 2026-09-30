# 开发导航

现状：0.3.0 Windows包完成验收、公开发布待完成。负责人：捞鱼工作室。最后更新：2026-09-30。

先读 roadmap.md，开发前查对应模块。

- roadmap.md：目标、验收证据、交付缺口。
- tech.md：资源/用户数据/引擎分离与鉴权。
- updater.md：每日检查、可信下载、哈希、重启/回滚；修改更新器必读。
- packaging.md：内置引擎、安装/便携、Mac与启动器接入。
- testing.md：隔离真实引擎、独立Kimi回归。
- todo.md：0.1/0.2历史，新工作记roadmap。
- reference/core-api.md与syncthing-api.md：旧端点资料，以gateway.py为准。
- reference/conventions.md：软件开发规范落实。

入口core/app.py → gateway.py → stmanager.py/wizard.py。config.py只存助手配置，同步配置唯一来源是引擎。pet.py使用同一快照，不独立把未知显示成功。ui/无构建链。

禁止回归操作真实用户同步项目。用户数据目录LaoyuSync，测试放verification/或临时目录，不提交密钥和config。

启动器入口 E:/共享/tools/软件开发/启动器适配/laoyu-launcher-adapter/SKILL.md；launcher-adapter.json。版本core/version.py；最终包生成dist/version.json，确认公开下载后才替换根version.json，源码提交不提前指向不存在的包。
