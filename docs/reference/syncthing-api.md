# 依赖的 Syncthing REST 端点笔记（v2.1.3 实测）

Base：从 `%LOCALAPPDATA%\Syncthing\config.xml` 读 `gui/address` + `gui/apikey`（tls 属性决定 http/https）。
所有请求带头 `X-API-Key`。

| 端点 | 用途 | 备注 |
|---|---|---|
| `GET /rest/system/status` | myID、uptime | |
| `GET /rest/config` | folders[] / devices[] 全量配置 | devices[].deviceID、name；folders[].id/label/path |
| `GET /rest/db/status?folder=<id>` | state、globalBytes、inSyncBytes、needBytes、needFiles、pullErrors | 进度 = inSync/global；state ∈ idle/syncing/scanning/error/... |
| `GET /rest/system/connections` | 设备连接状态 + 总收发字节 | **注意是 connections（复数）**，/rest/system/connection 是 404；速度用两次采样差值算 |
| `GET /rest/cluster/pending/devices` | 想连进来的待确认设备 | 一键接受 = 正常 POST /rest/config/devices |
| `POST /rest/config/devices` | 添加设备 | body 至少 deviceID；addresses 用 ["dynamic"]；返回里 requiresRestart=true 时补 `POST /rest/system/restart` |
| `DELETE /rest/config/devices/<id>` | 移除设备 | 同样注意 requiresRestart |
| `PUT /rest/config/folders/<id>` | 修改文件夹（共享给新设备=往 devices[] 里 append） | PUT 整个 folder 对象 |
| `POST /rest/config/folders` | 新建文件夹 | id 自生成、type=sendreceive、fsWatcherEnabled=true |
| `GET /rest/folder/errors?folder=<id>` | 失败文件清单 | errors 为 null 表示没有 |
| `POST /rest/system/restart` | 应用需要重启的配置 | |

设备 ID 格式：**8 组** 7 位 base32（字母大写 + 数字 2-7）共 56 字符，末位是校验字符，`^([A-Z2-7]{7}-){7}[A-Z2-7]{7}$`；粘贴时容忍小写/空格/无横线。编造的假 ID 过不了 Syncthing 的校验位检查（会 400），测试要用 `syncthing generate` 生成真 ID。
