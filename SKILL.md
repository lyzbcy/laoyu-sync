# 捞鱼同步小助手 Laoyu Sync — 开发 Skill

一套给 Syncthing 做的中文友好套壳：本地核心服务（网关）+ 网页管理界面 + 桌面小精灵插件。

## 任何 Agent 接手本项目的必读路径（渐进式披露）

1. 先读 `docs/agent.md` —— 架构总览、目录导读、当前开发情况。
2. 再读 `docs/todo.md` —— 现在的 To-do 和里程碑。
3. 要开发某一块组件时，去 `docs/reference/` 找对应文件精读，不要一上来扫全仓库：
   - `core-api.md` 本地网关 API 一览（前后端联调必读）
   - `syncthing-api.md` 我们依赖的 Syncthing 官方 REST 端点笔记
   - `conventions.md` 用户《软件开发》规范 → 本项目的落地映射（日志/更新/推广/测试等约定）
   - `packaging.md` 打包发布（Mac + Windows 双端，规划中）
4. 代码入口：`core/app.py`（进程入口）→ `core/gateway.py`（本地 HTTP 网关）→ `core/stmanager.py`（Syncthing 管理与状态聚合）→ `core/wizard.py`（添加设备/文件夹业务）→ `ui/`（前端）。

## 铁律

1. **每次开发完成必须更新版本号**：改 `core/version.py` 的 `__version__` 与 `CHANGELOG`，并同步到 `docs/todo.md` 的开发记录。本项目将实现自适应更新检测，版本号不同步会导致更新机制失效。
2. 配置永远以 Syncthing 自身的 `config.xml` / REST 为唯一事实来源，本软件只做客户端，不另存一份同步配置。
3. 后端只用 Python 标准库 + `qrcode`（二维码）+ `pywebview`（窗口壳）；前端纯 HTML/JS/CSS，不引入构建链。换 Tauri/Electron 壳时前端必须可以原样搬走。
4. 所有面向用户的文案用中文；表情优先用 `ui/assets/stickers/` 里的原创表情包（星星布丁）。
5. 运行期日志在 `logs/`，不要提交；用户可见的活动提示走 `activity.py` 的事件流，不要直接 print。
