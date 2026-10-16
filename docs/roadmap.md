## 2026-10-16 0.3.9 正式发布

发布页：https://github.com/lyzbcy/laoyu-sync/releases/tag/v0.3.9 。最终源码 15c24b8261af6ae8bd0e86efcd2572936c2052f1；CI 38836703687 两端成功，Windows 112 项全过、Mac 102 项通过/10 项 Windows 专用跳过。最终原始 CI 包完成 Windows 原生主窗口/renderer+engine ACK/宠物开关与退出清理、Mac Apple Silicon 透明显示/关闭/重开/关闭后重启记忆/Cmd-Q 清理实机验证。未用源码测试代替包运行结论。

发布前捕获并修复：Windows 就绪标记仍在写入时被父进程删除导致 WinError32，改临时文件写完关闭后原子发布，清理标记失败不覆盖启动结果；Mac 共享 bundle 身份的窗口恢复警告会阻塞子进程，启动前注册忽略旧窗口恢复；安装器手写版本遗漏，prepare_resources 同时从 core/version.py 生成 EXE/安装器版本，隔离回归固定防漏。

Windows ZIP/安装器/Mac arm64 ZIP 及 SHA256SUMS-039.txt 四项公开；逐包公网完整回读 SHA-256 与本地原始字节、GitHub 服务端 digest 一致。安装器 ProductVersion 与文件名均为 0.3.9；本轮没有以元数据检查冒充真实安装。根 version.json 在公开回读后切换，launcher-adapter 同步真实 ZIP 哈希。Mac 未 Apple 公证，Windows 未代码签名；不发布未验证的 Intel Mac 包。证据在 verification/release-039，测试身份/令牌和配置不提交。

## 2026-10-15 Mac 桌面小精灵（0.3.9 本机候选）

修复旧版仅 Windows 启动宠物、Mac 隐藏开关的问题。复用小蓝鱼和同一状态快照：关于页可开启/关闭并记住选择，右键关闭经主网关保存；就绪握手失败返回错误，不把未启动视为成功；并发开关串行，退出关闭态阻止迟到线程重新拉起。Mac 使用原生透明、中文字体、右键与原生落位纠正，详情面板使用 withdraw/deiconify。浏览器回退同样启动和清理宠物，宠物失败不停止主服务。Mac Cmd-Q 会跳过 webview 返回，故在同步 closing 事件与 finally 中执行幂等清理，只停止 owned 进程。

107 项隔离测试：97 通过、10 Windows helper 按平台跳过；独立审查发现的回退清理、Mac Windows API 调用及回退启动错误隔离均已修复。完整 arm64 冻结包实机验证：初始显示、鉴权/非布尔负例、关→进程消失、关后重启记忆、开→重新出现、Cmd-Q 后 owned 宠物与隔离引擎均退出；透明背景截图和 result.json 在 verification/mac-pet-039。Tk 9.0.4 实机黑底，最终候选用 Tk 8.6，spec 拒绝未验证的 Tk 9，详见 packaging.md。临时签名校验通过，未公证。

本机安装到 ~/Applications/LaoyuSync.app（0.3.9），保留软件中心原 0.3.8 不可变目录与下载回执。通过本机手动关联记录切换中心启动目标。真实关于页开关通过点击关闭/开启验证；继续沿用既有 Syncthing 1 项目/2 设备，外部引擎 PID 1119/70740 前后保持。助手设置备份留在本机 verification，不提交任何 config/token/身份。原有同步文件失败状态仍如实显示，本次未处理其原因或更改项目。

仅本机候选，未发布 0.3.9 Release，未修改正式 version.json 或帮助站。源码在既定仓库独立候选分支备份，保持仓库既有可见性。

## 2026-10-15 Windows 实机升级验收与更新占用修复（0.3.8 开发）

0.3.7 发布后 Windows 真实升级验收（本机 0.3.6 中心管理便携副本，经产品自身 /api/update/start 触发）：下载校验全部通过，但旧实例退出后备份改名 5/5 必现 [WinError 32] 事务回滚，旧版自愈重启、数据无损。取证（verification/win-037）：stmanager 引擎探测每约 2 秒孵化 powershell 子进程并继承安装目录为 CWD，单个存活约 2 秒，目录被近乎连续占用；helper 只等待旧主进程 PID，孤儿探测进程在改名瞬间持有目录。handle64 快照与探针实验（EXE+CWD 同目录 → 改名 WinError 32）固定证据链。

0.3.8 修复：config.relocate_cwd() 启动即迁离安装目录（app.main 调用）；两个 powershell 探测显式 cwd=数据目录；updater.spawn_update_helper 以暂存目录为 CWD；apply_update 备份改名最多重试 10 秒。tests/test_cwd_relocation.py 3 项 + test_update_transaction.py 2 项先行红后绿。0.3.6/0.3.7 既有安装自更新到 0.3.8 仍会命中旧 helper 单次改名，预期失败后回滚保平安，需发布页 setup 或软件中心重装一次进入可自更新状态。

0.3.8 已发布并完成 Windows 实机验收（verification/win-037/result.json release_038 节）：v0.3.8 三资产 SHA 三方核验一致；中心管理副本目录交换升级与 setup.exe 实装（注册表 0.3.8/开始菜单/卸载登记）双路径验证；0.3.8 运行中 handle64 实证安装目录零 CWD 句柄；启动器适配 strict --installed 全过（真实识别注册表安装）；软件中心权威分支 e2943eb 登记 0.3.8，中心测试 211 过。0.3.8 起后续版本一键自更新恢复可用（待下个版本发布时实证端到端）。

## 2026-10-15 Mac 实机验收与退出清理修复（0.3.7 开发）

CI 0.3.3 macOS arm64 包（run 36809010572，commit 60bf481，SHA-256 已固化）在 Apple M5 / macOS 26.6.2 首次实机隔离验收：功能 13 项通过（启动/前端/内置引擎/gateway 鉴权/全部核心 API/项目暂停恢复移除/设备增删/中文错误提示），真实引擎与 gongxiang-win 配置全程未动。发现 2 项 blocking：SIGTERM 退出后自启引擎残留（MAC-QUIT-1）、后台启动继承 SIG_IGN 导致 SIGINT 不触发清理（MAC-QUIT-2），证据 verification/native-mac/result.json。

0.3.7 修复：新增 core/exit_signals.py，SIGTERM/SIGINT 统一转 KeyboardInterrupt 走既有 except 分支（server.shutdown+stop_owned），覆盖 SIG_IGN 继承场景，非主线程安全跳过；tests/test_exit_signals.py 4 项新增单测通过，全套 85 项（Mac 环境既有 4 项路径断言失败与本修复无关）。源码级 SIGTERM 优雅退出通过；打包包复测与 GUI 窗口关闭路径复测进行中，未以源码结果宣称已发布。

## 2026-10-09 11:10 新反馈：0.3.5本机API拒绝访问

新真实附件3c1da025已读到明确unauthorized/403 CSRF Error。现有0.3.5说明了失败，但尚未自动核实旧配置与运行实例的访问凭据对应关系。0.3.6开发增加已知本机目录的只读凭据+公开设备证书匹配，唯一通过才接入，不关闭认证/修改密钥/换身份或扫远端。81项隔离测试通过，包含HTTP403→唯一配置→原有项目读回与XML/证书/私钥文件不变、重复匹配拒绝、权威自定义目录、代理/重定向保护。真实当前电脑证书匹配算法只读验证通过；反馈电脑新包效果仍需回执，不能据单个模拟推断所有授权失败根因。最终EXE的HTTP403恢复与原项目/配置/公开证书/私钥文件不变见verification/frozen-csrf-036/result.json；原生可见窗口、引擎、小鱼、反馈渠道和退出见verification/native-036/result.json。发布资产与清单在核验后切换0.3.6。

## 2026-10-09 软件反馈群：0.3.5 启动状态与诊断

按用户指定daily-note-summarizer刷新10月8日/9日企业微信缓存，确认10月8日15:32的0.3.4连接反馈“长期热身”；原始ZIP诊断仅剩HTTP轮询，无法据此断言用户引擎根因。修复确定的显示错误：checking/starting/ready/failed、等待秒数、50秒兜底、退出/缺引擎/权限或TLS/超时原因；首页与小鱼失败同步，重试期间禁重复；当前配置的进程识别不将明确不同home实例误作本机目标，未知不重复启动或修改身份。

诊断附当前启动阶段/错误码和近期关键事件，过滤成功轮询，读取有界轮转日志和引擎警告；取消附日志不读取。71项隔离测试、独立Kimi 8状态×两尺寸通过（verification/startup-feedback-ui）。最终EXE正常启动/引擎/反馈渠道/小鱼/退出通过；隔离损坏配置真实EXE显示engine_exited和engine_failed，原有真实同步进程未停止。旧0.3.4完整包冷启动实测在API就绪前独立查新升级耗时约3分钟，并改写内置二进制；0.3.5由助手启动的进程使用--no-upgrade，内置引擎只随已校验完整包更新，不改外部独立实例；打包仅包含指定引擎文件，避免自动升级产生的.old混入包。跨版本0.3.4→0.3.5另见verification/cross-version-035.json。修改状态判断不等于已确认反馈机器的具体驱动/配置根因。

同群微信语音失声在BluetoothDeviceConnector准备1.9.23候选，真实听音仍待现场验收，未以离线测试声称已解决或发布。

## 2026-10-02 0.3.4 历史更新结果和安全暂存清理

56项隔离单测、独立Kimi 6种结果×两尺寸UI回归通过。原始失败JSON归档保留，未来版本失败/同版真实失败/recovery仍显示；Windows真实进程占用阻止删除，退出后清理与身份文件/凭据保留通过（verification/real-cleanup-034.json）。最终EXE可见窗口/引擎/渲染/反馈渠道/小鱼/正常退出通过；真实成功与失败回滚保留身份和用户数据（verification/update-034.txt），另执行原0.3.3包与旧助手到0.3.4的完整跨版本验收（verification/cross-version-034.json）。没有操作真实同步项目或终止真实运行程序。

软件中心的同协议清理已单独提交646c90a，52项现有测试通过；中心原有未提交工作保留。同步助手自身能在中心管理的父目录清理符合凭据的暂存；不能把中心源码已修复表述为已经重发中心安装包。

## 2026-10-01 用户指定企业微信直发（0.3.3待发行）

取消未部署的中转服务；留言与日志ZIP直接发机器人，不依赖现有服务器。业务errcode核验、部分失败续发、双击去重、中文长文分段与旧空配置使用包内默认实现，44项测试通过；真实合成日志ZIP上传和群文字/文件消息获成功确认。机器人配置不进Git，通过仓库外构建注入，安装包中可以提取此链接的限制已告知用户。最终包与界面验收进行中。

## 2026-10-01 反馈机器人接入准备

用户提供机器人链接，凭据保存于仓库外；一次明确测试消息获企业微信errcode=0确认。服务端日志ZIP/7天随机链接/限流/收据与重试去重实现，5项模拟服务端测试通过；客户端41项测试通过。公网部署尚缺SSH配置，未发布0.3.3、未切换客户端反馈地址，不能宣称粉丝端已完成反馈。见server/README.md、docs/feedback.md。

## 2026-10-01 规范重新审计

正式版0.3.2反馈未按要求完成，完整审计见requirements-audit.md。0.3.3开发版补一级反馈入口、分类、日志选择预览及接收确认，修复后台更新结果不刷新；41项测试及独立Kimi反馈与版本提醒回归通过（模拟不代表真实送达）。反馈实际接收端、日志链接服务尚缺配置，尚未正式发布，不宣称已能提交到作者。

## 2026-09-30 0.3.2 已有项目与小鱼修复（已发行）

用户反馈另一台电脑网络已识别，但首页仍催新建、小鱼显示尚未配置。已修复含空格的完整引号home参数，增加SyncTrayzor等常用配置位置；没有运行引擎且仅一份有项目的旧配置时，优先旧配置，避免空默认配置遮挡。运行中的引擎与多身份不自动切换；GUI凭证仅读取所选home，避免错接另一身份。同步文件/身份不迁移不改写。

后端setup摘要统一首页与小鱼：读取中、已有项目、待接收、另一份旧配置、网络就绪但本机无项目分别显示。首页提供接入与配置路径诊断，小鱼新增浅色状态卡、中文详情、直接处理入口，空项目不显示同步成功。Tailscale共享目录不会自行变成Syncthing项目；另一台用户电脑的实际旧工具类型仍待用户补充，不能宣称已在其电脑复现并修好。

35项隔离单测通过；实际0.3.2 EXE前端/引擎ACK、可见窗口、小鱼开关、正常退出通过，verification/native-032/result.json。小鱼截图verification/adoption-032/pet-network-ready.png、pet-receive.png、pet-details.png。独立Kimi回归30页面与8路径诊断通过，verification/adoption-032/web-regression.md。最终CI 36728562198（0d6e3b9）Windows/Mac成功；CI原始ZIP真实EXE验收通过，verification/native-032-ci/result.json。0.3.2已公开发布，资产digest/HEAD长度已核验，正式version.json同步0.3.2。帮助页在保留其他任务v1.16.0更新基础上发布v1.16.1，同步助手入口指向0.3.2；公网HTML逐字节回读一致，verification/adoption-032/public-help.json。软件中心0.7.4内置目录仍为0.3.1，用户可通过同步助手自身检查更新或新版安装器升级，不声称旧软件中心目录已经切换。

## 2026-09-30 公开发布

用户明确授权公开发布、同步帮助站与上架软件中心。Windows0.3.1已公开：[发布页](https://github.com/lyzbcy/laoyu-sync/releases/tag/v0.3.1)。安装版/ZIP/checksums的GitHub资产digest与固定CI文件逐字节SHA-256一致；两个公网下载URL HEAD200且长度一致，证据verification/public-release.json与public-downloads.json。根version.json同步正式0.3.1清单。Mac不作为正式资产。

软件中心0.7.4打包版31核心测试及正常/小窗口冒烟通过，二进制已公开于lyzbcy/laoyu-software-center-downloads，源码仍私有。工作室服务器镜像及更新清单需要独立SSH发布权限；不宣称已经切换。帮助站原地址已更新至v1.15.0，公网HTML SHA-256与发布文件完全一致（c1a9f3ee095ba8d77e892cbd8a2a80c170f2e646ce0d1c3b0dbc583de6430524），证据verification/published-help-page.json。同步助手详情：https://help.wshoto.com/resource/5ea68b60e5b24df78ddce46cf1614671/27da304c.html#project/laoyu-sync。独立线上回归通过：1366×900与390×844首页/详情/下载6状态无横向溢出，17旧路由及全部旧链接保留，见verification/publish-web-regression.md。

# 0.3.1 窗口与已有网络接入交付

现状：Windows安装/便携包验收通过，0.3.1已公开发布。运行时提交9f43183575ea58ae510cfa9ab2781e300b39eddc，Windows/Mac CI [36697806429](https://github.com/lyzbcy/laoyu-sync/actions/runs/36697806429)成功。

- 移除Windows原生白色标题栏，用44px自绘标题栏、统一小鱼标识；简化侧栏与同步概览，修复920px品牌换行。
- Tailscale已有登录与网络自动只读识别，展示节点在线；不重组网、不重登、不改网络设置。
- 原有Syncthing项目/设备/身份直接沿用；网络与文件同步状态分开；就绪网络用户从选择文件开始。

|最终原始CI资产|SHA-256|
|---|---|
|laoyu-sync-0.3.1-win-x64.zip|3b0a823d02afce863ca529b8efa2201291d34aa016afb353499eeaee337f2167|
|laoyu-sync-0.3.1-win-x64-setup.exe|8cce0fb96c7b2418466111c767d42c3ced99686ee9a15cd75145f470b8d747ee|

验收：Windows30项/Mac23通用项通过（7个Windows helper跳过）；独立Kimi五页×两尺寸与网络状态负例通过，verification/ui-network-regression.md。真实源码原生窗口FormBorderStyle=None、DOM44px、点击网页按钮最大化/还原/最小化/关闭通过，verification/chrome-native/result.json。没有声称原生拖动已实测。

最终EXE直接接入现有1项目/3设备，Tailscale在线节点与CLI一致（测试过程中2台变1台），配置哈希保持，退出不关闭既有引擎。窗口nonclient_height=0，无原生标题栏：verification/adoption-packaged/result.json。全新隔离引擎启动/renderer ACK/小鱼/正常退出：verification/native-031-frozen/result.json。安装器实际安装日志verification/install-031.log，安装后启动verification/installed-031-smoke/result.json；启动器strict --installed报告verification/launcher-adapter-031-report.json。

真实同版本完整包切换和启动故障回滚分别见verification/upgrade-ok-b6_spp8g/verification-result.json与verification/upgrade-fault-h5jp7cj3/verification-result.json，保留设备身份/用户数据和可见窗口。公网版本清单及正式资产已发布并回读验证；跨版本自动升级尚未实测。

Windows包未签名，干净系统WebView2缺失场景未实机验；Mac仅构建，无签名/公证/实机验收。软件中心0.7.4已发行并同步新哈希；0.7.3用户需安装新版客户端。根version.json已切换至公开0.3.1资产。

以下保留0.3.0的历史验收记录。

---

# 0.3.0 开发交付与验收

现状：Windows 开发包完成验收，尚未公开发布；Mac 完成 CI 构建，待实机与签名公证。

负责人：捞鱼工作室。最后更新：2026-09-30。

## 已完成

- 程序资源、用户配置和同步引擎分离；内置官方 Syncthing 2.1.5，无需用户安装 Python。
- 中文首次引导、设备配对/邀请/共享、路径校验、暂停恢复、停止同步保留本机文件。
- 正确区分空、未知、失败和暂停状态；新项目默认保留远端旧文件30天。
- Windows 桌面小鱼开关与生命周期、双通道日志/脱敏诊断、原创表情/关于推广、15天免打扰求Star。
- 每日UTC+8和手动版本检查、可信下载/SHA-256、进度、完整包切换与失败恢复、恢复结果显示。
- Windows 安装/便携包、稳定AppID、安装登记/卸载入口、版本资源0.3.0、第三方许可证。
- 独立Kimi网页回归、真实双引擎同步；源码与模块文档同步远端。
- 软件中心0.7.4候选源码适配、目录/图标/精确主程序白名单与ZIP准备。

## 固定产物

运行时提交：071731e5c3eaae6dce9fd3e0adaf6fcd646c7a65。
Windows/Mac CI：[36693333182](https://github.com/lyzbcy/laoyu-sync/actions/runs/36693333182)，成功。
Windows产物直接保留CI原始字节，未重新压缩：

|文件|SHA-256|
|---|---|
|laoyu-sync-0.3.0-win-x64.zip|fa8c02a9b4675d9afafa6e271df66f2f96e81642c61c321b1ce9d7cff9eca8cd|
|laoyu-sync-0.3.0-win-x64-setup.exe|e89896f24e0ad858fce9d1d7e49d4d61015efc1049d4753da8222dd5ded87e12|

本机dist包含包、候选version.json、SHA256SUMS.txt和发布说明。

## 实际验收证据

- Windows 23/23 单测；Mac 16通用项通过、7 Windows helper项按平台跳过。
- 独立网页回归：verification/regression-report.md、updater-review.md；发现的共享保持、布局、复制失败提示已修复复测。
- 真实双引擎：verification/real-sync-result.json，首次/修改/二进制哈希、离线补齐、删除旧版留存、移除文件保留通过。
- 固定CI EXE：verification/frozen-native/result.json；实际安装后：verification/frozen-installed/result.json。两者均前端/引擎ACK、可见窗口、小鱼开关、正常退出通过。桌面截图因抓取不可用，不作为视觉证据。
- 安装日志verification/install-final.log；卸载注册表AppID、DisplayIcon/InstallLocation及EXE版本0.3.0核对。
- 最终包真实事务：verification/upgrade-ok-yi8g3a3a/verification-result.json；JS失败注入：verification/upgrade-fault-b0n1d702/verification-result.json。切换/恢复、可见窗口、身份/用户数据保留通过。属于同版本完整包验证，不能冒充公网跨版本更新。
- 启动器：verification/launcher-adapter-report.json，strict --installed全部通过；启动器31/31单测。实际候选界面另见launcher-smoke.log。现有正式0.7.3客户端尚未包含新产品白名单。

## 发布与平台边界

Windows包未代码签名；当前机器有WebView2，新装系统无WebView2的体验需干净机器验收。Mac缺签名/公证/实机验收，桌面小鱼仅Windows。反馈服务未配置时复制，不宣称送达。同步会传播修改与删除，不能替代备份。

根version.json仍为0.2.0正式更新清单。正式发布0.3.0资产并核对公网下载后再切换，随后验收真实跨版本更新。软件中心0.7.4发行与公开目录发布另行完成。

verification含测试设备密钥，不提交、不进入发布包。原桌面bat和原用户同步项目保持原样。
