# 构建与交付

现状：开发中。负责人：捞鱼工作室。最后更新：2026-09-30。

稳定产品 ID laoyu-sync；Windows 主程序 LaoyuSync.exe。使用 PyInstaller onedir，ZIP 根目录直接放主程序，完整保留 _internal 与资源。构建脚本校验官方 Syncthing 发布哈希，不携带任何开发者 config.xml、设备密钥或 token。第三方声明包含 Syncthing MPL-2.0 与源码链接。

安装版每用户 LocalAppData/Programs/LaoyuSync，无管理员要求。开始菜单与卸载登记固定；桌面快捷方式、开机自启由用户选择。卸载不删除用户同步文件或引擎配置。

启动器适配入口：E:\\共享\\tools\\软件开发\\启动器适配\\laoyu-launcher-adapter\\SKILL.md。描述文件与严格报告不代替真实安装、识别和打开；旧软件中心客户端需要新版白名单。
