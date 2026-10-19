# 同步优先直连

0.3.11 开发版，2026-10-19。

粉丝入口：设置 / 关于 → 同步网络 → 文件同步连接方式。可选择「沿用环境代理」或「优先直连」。保存后退出并重新打开小助手；由其他工具启动的 Syncthing 需先从原工具退出，再由小助手启动。设置持久化于助手配置，不写同步引擎配置、设备身份或项目文件。

优先直连在创建引擎进程时移除大小写形式的 HTTP_PROXY、HTTPS_PROXY、ALL_PROXY 与原 NO_PROXY，设置 NO_PROXY/no_proxy=*；保留父进程环境和其他变量。默认沿用环境，避免自动改变依赖 SOCKS 代理才能连接的用户网络。软件更新和反馈不受此选项影响。

操作系统路由优先于应用环境：TUN、全局 VPN、透明网关无法靠删除代理变量绕过。界面内提供 Clash/Mihomo、Surge、sing-box 1.11+ 配置片段，按 Windows 的 syncthing.exe 和 Mac 的 syncthing 进程分流，规则需放在兜底规则之前，使用规则模式并确保支持进程识别。订阅配置应通过客户端覆写持久保存；sing-box 的直连出站标签需与现有配置一致。规则生成仅返回静态片段，不改订阅、不读代理凭据，也不把复制成功当作配置成功。

其他 VPN 可使用其分应用排除入口；不支持分流时需关闭 VPN 或更换网络同步。Tailscale 等组网进程也可能被代理接管，需另为组网工具配置直连。不使用固定远端 IP 或整个项目目录作为排除规则。

是否省代理流量以代理软件连接记录为准：确认同步进程连接命中 DIRECT／直连。Syncthing 的 TCP/QUIC/中继类型不能证明是否被 VPN 接管；不把设备在线、私网地址、没有 HTTP_PROXY 或配置保存成功视为已验证直连。

接口：GET /api/network-preference（偏好、当前引擎应用情况及限制）；POST /api/settings 的 sync_network_mode（system/direct，严格类型校验）；GET /api/network-rules?format=clash|surge|singbox。全部沿用本机令牌、Host、Origin 校验。

状态区分：applied 只表示本助手创建的活动进程已应用对应环境；restart_required 表示偏好与活动进程启动方式不同；external_or_stopped 表示未管理活动引擎，不自动停止原独立引擎。verified_direct 始终 false，系统分流需在代理软件核实。

验收：tests/test_sync_network.py 覆盖变量大小写、父环境不变、重启持久化、无效设置、进程创建失败、外部引擎保护、规则与 API 鉴权。scripts/verify_sync_network.py 生成两个独立身份，关闭公网发现/中继/NAT，在继承指向本机测试 SOCKS 端口的代理环境中启动直连引擎，同步 1 MiB 二进制并校验内容，测试代理 0 次连接。该验证仅证明隔离局域网与应用环境绕过，不代表真实公网或 TUN 已验证。测试产物位于 verification/，不入包。
