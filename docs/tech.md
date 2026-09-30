# 架构与数据

现状：开发中。负责人：捞鱼工作室。最后更新：2026-09-30。

Python 标准库业务核心 + pywebview 桌面窗口 + 原生 HTML/JS/CSS。PyInstaller onedir 包包含 UI、桌面宠物和 Syncthing 引擎。Windows Inno Setup 每用户安装，Mac 独立 CI 构建。

程序资源只读；自身配置与轮转日志存放用户数据目录 LaoyuSync。Syncthing 配置始终由引擎管理，已有配置兼容，新增项目默认使用回收站版本管理。测试通过 LAOYU_SYNC_DATA、LAOYU_ST_HOME、LAOYU_SYNC_PORT 隔离，不能拿真实同步文件夹做测试。

本机网关只监听回环；API 校验令牌、Host、Origin；外部浏览器桥仅允许 HTTP(S)。诊断日志隐藏令牌，不附带文件内容。小精灵使用同一网关快照，不重复扫描同步配置。

升级按 docs/updater.md；打包按 docs/packaging.md；产品体验验收按 docs/testing.md。
