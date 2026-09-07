# agent.md — 架构总览与目录导读

## 这是什么

「捞鱼同步小助手」= 给 Syncthing 套的一层中文友好壳。组成：

1. **core/** 本地核心服务（Python，端口默认 8390，仅监听 127.0.0.1）：
   - 管理 syncthing.exe 进程（没运行就拉起，API 就绪前显示“启动中”）
   - 反向代理 Syncthing REST API，聚合成前端友好的状态快照
   - **添加设备向导**（本项目核心卖点）：我的设备 ID + 二维码、待确认设备一键接受、按 ID 添加、勾选共享文件夹
   - 活动事件流（用户可见“现在在干什么”）+ 开发日志（logs/）
   - 版本号与自适应更新检测（更新源未配置时静默跳过）
2. **ui/** 纯静态前端（无构建链），由 core 直接托管。页面：仪表盘 / 设备与配对 / 同步文件夹 / 动态 / 关于（推广页按个人推广页规范做在软件内 `#/about`）。
3. **小精灵**（`../syncthing-pet/syncthing_pet.py`）= 第一个插件，独立进程读同一个 Syncthing API，菜单里可打开本管理界面。

## 关键事实（接手前先记住）

- Syncthing GUI 地址与 API key 启动时从 `%LOCALAPPDATA%\Syncthing\config.xml` 读取，不要写死。
- 本机现有同步文件夹：`ban-gong`（E:\共享，45GB+），对端设备 `zeendeMacBook-Air`（跑官方 Syncthing v2.1.3）。
- 网关与前端之间的鉴权：启动时生成的 token，UI 通过 `?t=<token>` 拿到，API 请求带头 `X-Token`。
- Syncthing 的 `/rest/config` 修改后可能返回 `requiresRestart: true`，此时网关会自动调 `/rest/system/restart`。
- Windows DPI：本机 4K 屏 150% 缩放，pywebview 窗口默认尺寸按物理像素给。

## 目录

```
core/            后端（Python 标准库 + qrcode + pywebview）
  app.py         入口：单实例 → 拉起 Syncthing → 起 HTTP 服务 → 开窗口
  config.py      config.json 读写（token/端口/更新源/反馈地址）
  stmanager.py   Syncthing 进程管理、REST 客户端、状态聚合、速度采样
  wizard.py      添加设备/文件夹业务（校验、pending、共享、重启处理）
  activity.py    用户可见事件流 + logs/ 开发日志（双通道日志系统）
  version.py     版本号 + CHANGELOG + 更新检查
  gateway.py     HTTP 网关：/api/* + 托管 ui/ 静态文件
ui/              前端（index.html / app.js / style.css / assets/stickers 原创表情）
docs/            agent.md、todo.md、reference/*（渐进式披露）
```

## 本地跑起来

- 双击项目根目录 `启动捞鱼同步小助手.bat`（pythonw 启动，无黑框）。
- 开发调试：`python core/app.py --console`（浏览器打开，日志打到控制台）。
- 网关地址：http://127.0.0.1:8390/?t=<token>（token 在 core/config.json）。
