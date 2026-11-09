---
name: laoyu-sync-agent
description: 在同一台电脑上查看捞鱼文件夹同步的状态、排查故障，并按用户授权修复或调整同步设置。
---

# 捞鱼文件夹同步 · 本机 Agent 接口

先让应用保持运行。接口只监听 `127.0.0.1`。从与应用同机的终端访问，使用提示词给出的端口，或读取本机配置的 `port`。默认端口为 8390。

从下列位置读取应用的 `config.json`。若运行时设置了 `LAOYU_SYNC_DATA`，配置在该目录。若设置了 `LAOYU_SYNC_PORT`，优先使用该端口。

| 系统 | 配置 |
| --- | --- |
| Windows | `%LOCALAPPDATA%\LaoyuSync\config.json` |
| macOS | `~/Library/Application Support/LaoyuSync/config.json` |
| Linux 源码运行 | `~/.local/share/LaoyuSync/config.json` |

把 `token` 只放在发往该本机网关的 `X-Token` 请求头里。绕过 HTTP 代理，禁止跟随重定向。请勿回显配置、令牌或完整响应。回复中隐藏设备 ID、网络地址和完整文件路径。

## 先读状态，再排查

| 方法与路径 | 用途 |
| --- | --- |
| `GET /api/version` | 确认当前应用版本 |
| `GET /api/status` | 查看引擎、设备、项目及传输进度。先检查 `syncthing.api_ok` |
| `GET /api/folders` | 查看已有项目、项目 ID 和共享配置 |
| `GET /api/pending` | 查看等待确认的设备和项目 |
| `GET /api/sync-diagnose` | 获取引擎、对端和文件级异常及处理建议 |
| `GET /api/network-check` | 按需自检本机同步的代理和直连状态 |

下面是一个无需第三方库的 Python 调用示例。先看脱敏摘要，需要时再在本机代码里分析报告明细。

```python
import http.client
import json
import os
import sys
from pathlib import Path

home = Path.home()
if sys.platform == "win32":
    default_dir = Path(os.environ["LOCALAPPDATA"]) / "LaoyuSync"
elif sys.platform == "darwin":
    default_dir = home / "Library/Application Support/LaoyuSync"
else:
    default_dir = home / ".local/share/LaoyuSync"
data_dir = Path(os.environ.get("LAOYU_SYNC_DATA", default_dir))
cfg = json.loads((data_dir / "config.json").read_text(encoding="utf-8"))
port = int(os.environ.get("LAOYU_SYNC_PORT", cfg.get("port", 8390)))
conn = http.client.HTTPConnection("127.0.0.1", port, timeout=90)
try:
    conn.request("GET", "/api/sync-diagnose", headers={"X-Token": cfg["token"]})
    response = conn.getresponse()
    if response.status != 200:
        raise RuntimeError(f"本机同步助手返回 HTTP {response.status}")
    report = json.load(response)
    print([item["code"] for item in report.get("issues", [])])
finally:
    conn.close()
```

401 时核对令牌和端口。连接失败时请用户打开应用。引擎不可达时保留未知状态。用实际读回的状态判断是否完成同步。

## 用户授权后执行

发送 JSON 对象并设置 `Content-Type: application/json`。执行前说明操作、影响的项目和设备。项目 ID 与设备 ID 使用只读接口返回值。

| 方法与路径 | JSON 参数 |
| --- | --- |
| `POST /api/sync-repair` | `{}`。同应用的「排查并自动修复」，执行有界重试 |
| `POST /api/folder/add` | `path`（现有本机目录）、`label`、`share_with`（设备 ID 数组） |
| `POST /api/folder/accept` | `folder_id`、`label`、`path`、`device_id`。用于收到的共享邀请 |
| `POST /api/folder/update` | `folder_id`，以及要修改的 `devices`（完整共享设备 ID 数组）或 `paused`（布尔值） |
| `POST /api/device/add` | `device_id`、`name`、`folders`（要共享的项目 ID 数组） |

修复后重新读状态，区分「已发起重试」和「已同步完成」。项目和设备移除、外部引擎接管与日志发送交给用户在应用界面确认。不要直接编辑 Syncthing 配置、身份文件或同步目录内容。
