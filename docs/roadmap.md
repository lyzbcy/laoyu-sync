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
