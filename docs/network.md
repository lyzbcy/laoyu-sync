# 已有网络与同步配置接入

现状：0.3.1实现，真实本机只读验收通过。负责人：捞鱼工作室。最后更新：2026-09-30。

core/network.py只调用Tailscale的status --json；PATH、Windows Program Files和常见Mac/Linux安装位置自动检测。识别已连接/等待登录/等待授权/暂停/连接中/暂不可读/未安装，读取节点名、在线与IP；不调用up/down/login，不安装服务，不改变路由或ACL，不保存Tailscale凭证。10秒后台缓存，5秒进程超时，接口轮询不会等待CLI。失败显示未知，不虚报断网。

Tailscale网络在线、Syncthing设备在线、项目文件同步分别展示。已组网用户不被要求重设Tailscale；网络设备列表仅作现有网络展示，不代表已授权文件共享。只有Tailscale而没有同步项目时选择文件夹并确认共享；不扫描远端API密钥或自动信任所有节点。

stmanager.py沿用标准目录Syncthing配置，也读取正在运行引擎唯一的--home/--config路径。隔离LAOYU_ST_HOME优先；多个独立自定义引擎或默认与自定义同时运行时优先标准配置，避免随机接入其他身份。UI标明已接入原有项目和同步设备，既有配对/地址/版本管理不重写。退出不停止原独立引擎。

本机只读验收：现有1项目、3设备、1同步对端在线；Tailscale2节点在线；接入前后配置文件哈希一致、退出后旧引擎仍就绪。证据verification/adoption-live-result.json；最终EXE证据另见roadmap。7项新增自动测试覆盖状态误判、探测失败、缓存、已有引擎不启动/停止、custom home与测试隔离。

0.3.2：补齐SyncTrayzor常用目录与完整引号home参数；空默认配置遮挡唯一旧配置时仅在无运行引擎下优先旧配置。GUI凭据不跨home回退。setup统一首页/小鱼，待接收项目与只有Tailscale分开；路径诊断仅本机显示。不扫描远端、不自动授权共享，另一台电脑的项目需对方共享并本机选择位置。
