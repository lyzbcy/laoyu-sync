# 构建与交付

现状：0.3.1 Windows原始CI安装/便携包验收通过，已在GitHub发布；Mac CI通过，待实机。

负责人：捞鱼工作室。最后更新：2026-09-30。

稳定产品ID laoyu-sync，主程序LaoyuSync.exe，AppID studio.laoyu.sync。PyInstaller onedir，ZIP根目录放主程序与完整_internal资源。官方Syncthing 2.1.5下载与上游校验值匹配，不携带开发者config.xml、设备密钥或token。THIRD_PARTY_NOTICES与实际依赖许可证随包交付。

Inno每用户安装默认LocalAppData/Programs/LaoyuSync，无管理员要求；提供开始菜单和卸载登记，桌面快捷方式/开机自启默认关闭。用户同步文件/配置与程序分离。最终CI安装器已安装到verification/installed-031并启动验收，详细证据与精确哈希见roadmap.md。

Windows包尚无代码签名。Mac单独CI构建且引擎匹配runner架构；未经签名公证/实机验证，不标为正式Mac交付。Mac通过发布页更新；Windows实现受校验完整包事务与恢复。

启动器入口E:/共享/tools/软件开发/启动器适配/laoyu-launcher-adapter/SKILL.md。描述文件launcher-adapter.json、严格报告与真实安装识别通过。软件中心0.7.4已公开发行，含目录、图标、installed和portable白名单；0.7.3需升级客户端。

根version.json仅正式发行清单；dist/version.json为固定候选包清单。发布必须使用已验收原始字节，不能重压缩后沿用旧哈希。

## 2026-10-15 Mac 小精灵本机候选 0.3.9

Mac 构建必须使用已实机验证的 Tcl/Tk 8.6。当前独立运行时 Python 3.12.14 带 Tk 9.0.4，能创建窗口但透明画布变黑且原生边框异常；spec 主动拒绝此组合，避免构建成功后交付坏包。其他 Python 3.12 补丁版配 Tk 8.6 仍可使用，不以 Python 版本单独判断。本机用 Python 3.12.11 / Tcl/Tk 8.6、PyInstaller 6.16.0，构建时 TCL_LIBRARY/TK_LIBRARY 指向该运行时的 lib/tcl8.6 与 lib/tk8.6；冻结包中资源由 PyInstaller 收集，运行无需开发环境变量。

完整候选在 verification/mac-pet-039/dist/LaoyuSync.app，版本元数据跟随 core/version.py。内置引擎来自本机已校验的正式 0.3.8 原包；不包含真实同步配置或身份。本次只做本机安装，不修改 version.json、GitHub Release 或软件中心的可信下载回执，不覆盖原不可变下载目录。候选为本地临时签名，未做开发者签名/公证。

2026-10-16 正式发布 0.3.9，原始 CI 38836703687 的 Windows 安装/便携与 Mac arm64 ZIP 已逐包公开回读核验。安装器 #define AppVersion 由 prepare_resources.py 从 core/version.py 自动更新，避免人工多处改版本遗漏；缺失声明拒绝构建。Mac 和 Windows 包的宠物开关与正常退出均已验证。安装器本轮验证版本元数据，不宣称在用户电脑重新实装。详见 roadmap 最新发布记录。
