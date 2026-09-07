# 本地网关 API（core/gateway.py 托管，端口 127.0.0.1:8390）

鉴权：除静态文件外全部要求请求头 `X-Token: <core/config.json 里的 token>`。
前端通过 `?t=<token>` 进入后保存在 sessionStorage。

## 状态类

- `GET /api/status` — 聚合快照：
  `{syncthing:{running,api_ok,version,uptime}, folders:[{id,label,state,globalBytes,inSyncBytes,needBytes,needFiles,pullErrors,errors,pct}], devices:[{id,name,self,connected,address,clientVersion,inRate,outRate}], total:{pct,needBytes,speed}}`
- `GET /api/events?since=<id>` — 用户可见活动事件 `{events:[{id,ts,level,text}], last}`
- `GET /api/mydevice` — `{name,id,qr:"/api/qr?..."}`
- `GET /api/pending` — 待确认设备 `{devices:[{deviceID,name,address,time}]}`
- `GET /api/qr?text=...` — SVG 二维码

## 操作类

- `POST /api/device/add` — body `{device_id, name, folders:[folderId...]}`。校验 ID 格式 → 添加设备 → 逐个共享文件夹 → 视 `requiresRestart` 自动重启 Syncthing。返回 `{ok, restarted, pending_accepted}`（来源可能是 pending 一键接受，`pending_accepted=true`）。
- `POST /api/device/remove` — body `{device_id}`（前端必须二次确认）。
- `POST /api/folder/add` — body `{path, label}`。校验路径存在；folder id 自动生成 `sync-xxxxxxxx`。
- `POST /api/feedback` — body `{text}`。配置了 `feedback_url` 则转发，否则 `{ok:false, reason:"not_configured"}`，前端降级为复制到剪贴板。

## 版本与配置

- `GET /api/version` — `{version, changelog:[{ver,date,items}], update:{enabled, remote_version, download_url, note}}`（更新源未配置时 `update.enabled=false`）
- `POST /api/version/check` — 立即执行一次更新检查（关于页"检查更新"按钮）
- `GET /api/meta` — `{feedback_url_configured, product:"同步精灵"}`

## 错误约定

所有非 2xx 返回 `{ok:false, error:"<中文可读原因>"}`，前端直接展示。
