# 回归与隔离

现状：业务、真实同步、网页和Windows事务通过。负责人：捞鱼工作室。最后更新：2026-09-30。

python -m unittest discover -s tests -v：Windows23项通过；Mac16项平台通用通过、7项Windows helper按平台跳过。CI两平台构建通过，不能据此声称Mac用户设备实机验收。

独立Kimi回归代理在隔离Chrome中检查五页、勾选保持、非法ID、暂停/恢复、共享、移除、日志与关于页；发现问题修复并强制刷新复测。verification/regression-report.md保存过程与截图。

真实双引擎：生成独立身份，关闭公网发现与中继，使用测试目录，配对、共享、待接收、首次/修改/1MB哈希一致；离线恢复补齐；删除传播且旧版留存；移除后本机文件保留。证据verification/real-sync-result.json。不改原E:/共享同步项目。

Windows scripts/verify_windows.py验证完整EXE、可见窗口、前端+引擎ACK、小鱼开关及正常退出；scripts/verify_update.py使用同版本真实完整包事务注入，验证切换、JS启动失败回滚、身份/数据和可见窗口保留。

最终冻结包的安装、卸载登记、启动器严格报告与发布清单见roadmap.md。verification含测试身份私钥/令牌，整个目录不提交、不进发布包；文档仅记录结果，不公开个人配置。

交付清理：仅关闭18390/18391隔离助手与其测试引擎；最终安装器已通过实际卸载，测试卸载登记移除，验收JSON/日志保留。原用户引擎和桌面bat未动。

0.3.1新增已有网络7项，总计Windows30项/Mac23通用项（7个Windows helper跳过）。独立Kimi对五页×两尺寸、网络状态模拟和既有配置文案验收，报告verification/ui-network-regression.md；原生无框44px以及点击真实页面按钮最大化/还原/最小化/关闭验证见verification/chrome-native/result.json。
