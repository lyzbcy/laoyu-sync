# 回归与隔离

现状：0.3.13 已正式发布；最终数量和平台范围见 CI 与补齐报告。
负责人：捞鱼工作室。
最后更新时间：2026-10-19。

## 0.3.13 当前实现

python -m unittest discover -s tests -v。bootstrap 为测试隔离 LAOYU_SYNC_DATA、LAOYU_ST_HOME、HOME、USERPROFILE、LOCALAPPDATA、APPDATA；临时身份和凭据不入包。独立测试文件也应能单独运行。

Windows scripts/verify_windows.py 验冻结包可见窗口、renderer/engine ACK、反馈渠道、小精灵开关和退出；verify_update.py 验真实目录交换与 JS 故障回退。Mac scripts/verify_macos.py 在隔离配置运行真实 .app/helper，验证窗口和引擎 ACK、反馈配置、小精灵、成功替换与故障恢复；测试用关闭触发器只加在隔离副本，不进入发行包。

download_routes 的测速/坏哈希/回退、Mac 包链接安全、健康备份保留期/占用/身份保护有独立负例。真实用户目录不作测试夹具，不发送真实反馈消息来替代模拟测试。

遵循共享规范：主 Agent 操作同时，由独立子 Agent 通过 Kimi bridge 观察 UI 并写报告。截图大小、覆盖状态和未测项目必须写实；源码模拟不冒充最终包，CI 不冒充用户 Mac 实机。最终范围见 standards-remediation.md。

## 历史记录（保留原验收范围）

# 回归与隔离

现状：业务、真实同步、网页和Windows事务通过。负责人：捞鱼工作室。最后更新：2026-09-30。

python -m unittest discover -s tests -v：Windows23项通过；Mac16项平台通用通过、7项Windows helper按平台跳过。CI两平台构建通过，不能据此声称Mac用户设备实机验收。

独立Kimi回归代理在隔离Chrome中检查五页、勾选保持、非法ID、暂停/恢复、共享、移除、日志与关于页；发现问题修复并强制刷新复测。verification/regression-report.md保存过程与截图。

真实双引擎：生成独立身份，关闭公网发现与中继，使用测试目录，配对、共享、待接收、首次/修改/1MB哈希一致；离线恢复补齐；删除传播且旧版留存；移除后本机文件保留。证据verification/real-sync-result.json。不改原E:/共享同步项目。

Windows scripts/verify_windows.py验证完整EXE、可见窗口、前端+引擎ACK、小鱼开关及正常退出；scripts/verify_update.py使用同版本真实完整包事务注入，验证切换、JS启动失败回滚、身份/数据和可见窗口保留。

最终冻结包的安装、卸载登记、启动器严格报告与发布清单见roadmap.md。verification含测试身份私钥/令牌，整个目录不提交、不进发布包；文档仅记录结果，不公开个人配置。

交付清理：仅关闭18390/18391隔离助手与其测试引擎；最终安装器已通过实际卸载，测试卸载登记移除，验收JSON/日志保留。原用户引擎和桌面bat未动。

0.3.1新增已有网络7项，总计Windows30项/Mac23通用项（7个Windows helper跳过）。独立Kimi对五页×两尺寸、网络状态模拟和既有配置文案验收，报告verification/ui-network-regression.md；原生无框44px以及点击真实页面按钮最大化/还原/最小化/关闭验证见verification/chrome-native/result.json。

0.3.1实际安装与卸载通过，隔离测试助手26390及测试引擎26384已清理；只处理本次测试进程，原用户引擎保持运行。
