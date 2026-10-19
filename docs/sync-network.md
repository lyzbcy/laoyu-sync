# 同步优先直连

现状：0.3.14 已正式发布，一键直连自检与一键接管随包分发。
负责人：捞鱼工作室。
最后更新时间：2026-10-19。

粉丝入口：设置 / 关于 → 同步网络 → 文件同步连接方式。可选择「沿用环境代理」或「优先直连」。保存后退出并重新打开小助手；由其他工具启动的 Syncthing 需先从原工具退出，再由小助手启动。设置持久化于助手配置，不写同步引擎配置、设备身份或项目文件。

优先直连在创建引擎进程时移除大小写形式的 HTTP_PROXY、HTTPS_PROXY、ALL_PROXY 与原 NO_PROXY，设置 NO_PROXY/no_proxy=*；保留父进程环境和其他变量。默认沿用环境，避免自动改变依赖 SOCKS 代理才能连接的用户网络。软件更新和反馈不受此选项影响。

操作系统路由优先于应用环境：TUN、全局 VPN、透明网关无法靠删除代理变量绕过。界面内提供 Clash/Mihomo、Surge、sing-box 1.11+ 配置片段，按 Windows 的 syncthing.exe 和 Mac 的 syncthing 进程分流，规则需放在兜底规则之前，使用规则模式并确保支持进程识别。订阅配置应通过客户端覆写持久保存；sing-box 的直连出站标签需与现有配置一致。规则生成仅返回静态片段，不改订阅、不读代理凭据，也不把复制成功当作配置成功。

其他 VPN 可使用其分应用排除入口；不支持分流时需关闭 VPN 或更换网络同步。Tailscale 等组网进程也可能被代理接管，需另为组网工具配置直连。不使用固定远端 IP 或整个项目目录作为排除规则。

是否省代理流量以代理软件连接记录为准：确认同步进程连接命中 DIRECT／直连。Syncthing 的 TCP/QUIC/中继类型不能证明是否被 VPN 接管；不把设备在线、私网地址、没有 HTTP_PROXY 或配置保存成功视为已验证直连。

接口：GET /api/network-preference（偏好、当前引擎应用情况及限制）；POST /api/settings 的 sync_network_mode（system/direct，严格类型校验）；GET /api/network-rules?format=clash|surge|singbox；GET /api/network-check（按需触发的直连自检，见下）；POST /api/engine/takeover（用户确认后的一键接管：经引擎自身 REST 接口优雅退出外部引擎并等待其退出，成功后才由小助手启动自己的引擎应用当前偏好；退出失败返回 409 且不启动第二引擎避免端口冲突，无外部引擎时直接启动）。全部沿用本机令牌、Host、Origin 校验并走变更串行锁；network-check 要跑 tasklist/netstat/PowerShell（秒级），只按钮触发、不进轮询接口。

一键接管（stmanager.shutdown_external）：只在能核实本机回环 GUI 地址与 API key 时发送 /rest/system/shutdown，绝不强杀进程（引擎可能正在写数据库/配置）；退出请求后轮询最多 15 秒确认进程消失，超时按失败处理提示从原工具退出。前端在自检报告命中「外部引擎正在运行」（engine_running=true 且 state=external_or_stopped）时显示接管按钮，弹确认框说明不强杀、不改同步配置与设备身份；开机自启的独立引擎下次登录可能再次启动，届时重复接管或在原工具关闭自启——不代删用户的计划任务/自启项。自动场景一律不触发接管，保持"不自动停止外部引擎"的既有边界。

一键自检（0.3.14 起，core/network_check.py）：收集五项本地旁证——引擎归属（applied/restart_required/external_or_stopped 三态与对应处理指引；报告附带 engine_running 标记外部引擎是否在跑，前端据此显示一键接管按钮）、本地代理端口（引擎是否连 127.0.0.1 常见代理端口或环境代理变量指向的地址，命中为 fail）、系统层接管（默认路由接口名与适配器描述含 TUN/TAP 等字样、198.18.0.0/15 网关、1/8+128/8 覆盖路由，命中为 warn）、转发痕迹比对（引擎公网连接目标与常见代理内核进程连接目标的交集，交集非空为 warn）、系统代理（仅说明，Syncthing 不读取）。整体结论按 fail>warn>pass 聚合，info 只作说明不定级；快照获取失败降级为 info 并提示重试，不冒充通过。中文系统虚拟网卡的 TAP/TUN 字样常只在适配器描述里（接口名是「以太网 2」），路由快照同时取 InterfaceAlias 与 InterfaceDescription，PowerShell 输出强制 UTF-8。非 Windows 平台连接与路由级检测明确报「暂不支持」，不猜结果。所有结论措辞保持"未发现痕迹／疑似"，不出现"已验证直连"；代理软件内部的 DIRECT／节点命中仍只能在其连接记录确认，自检不读代理凭据。

状态区分：applied 只表示本助手创建的活动进程已应用对应环境；restart_required 表示偏好与活动进程启动方式不同；external_or_stopped 表示未管理活动引擎，不自动停止原独立引擎。verified_direct 始终 false，系统分流需在代理软件核实。

验收：tests/test_sync_network.py 覆盖变量大小写、父环境不变、重启持久化、无效设置、进程创建失败、外部引擎保护、规则与 API 鉴权；tests/test_network_check.py 覆盖 tasklist CSV（含引号内逗号）、netstat IPv4/IPv6/非 ESTABLISHED 行、路由快照标量 JSON/乱输入/中文接口名+TAP 描述、代理端口命中（含环境变量指向端口）、目标交集三态、聚合定级、快照失败降级、非 Windows 不猜结果、API 鉴权，以及一键接管（非回环拒绝与送达失败说明、退出轮询、端点 401/409/成功启动引擎/无外部引擎直接启动，退出失败绝不并发启动第二引擎）；另在真实中文 Windows 上对照手工 netstat/route 排查复核（外部引擎+ikuuu 系统代理场景：引擎无本地代理连接、与代理内核目标无交集、默认路由物理网卡，自检结果与手工结论一致）。scripts/verify_sync_network.py 生成两个独立身份，关闭公网发现/中继/NAT，在继承指向本机测试 SOCKS 端口的代理环境中启动直连引擎，同步 1 MiB 二进制并校验内容，测试代理 0 次连接。该验证仅证明隔离局域网与应用环境绕过，不代表真实公网或 TUN 已验证。测试产物位于 verification/，不入包。
