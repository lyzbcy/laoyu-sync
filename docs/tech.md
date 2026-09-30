# 架构与数据

现状：Windows0.3.0实现与回归通过。负责人：捞鱼工作室。最后更新：2026-09-30。

Python标准库业务核心 + pywebview桌面窗口 + 原生HTML/JS/CSS。PyInstaller onedir包含UI、宠物与Syncthing。Windows Inno Setup每用户安装；Mac独立CI、架构对应官方引擎。

程序资源只读；配置与轮转日志在用户数据目录LaoyuSync。引擎已有config.xml兼容读取，第一次生成后自动重新读取；同步配置始终由Syncthing管理，新项目默认30天回收站版本管理。测试用LAOYU_SYNC_DATA、LAOYU_ST_HOME、LAOYU_SYNC_PORT、LAOYU_ST_GUI隔离。

网关只监听回环，API校验令牌、Host和Origin，限制JSON大小和静态路径。浏览器桥只打开HTTP(S)，日志隐藏token/API key，不收集遥测和文件内容。小鱼读取同一网关，不独立把未知状态报成功。退出只停止自己启动的引擎，不停止已有独立引擎。

更新与恢复见updater.md；安装与软件中心见packaging.md；隔离测试见testing.md。
